"""El perfil del workspace en un `.zip`: exportarlo e importarlo (docs/PLAN_LIBRERIA.md §5, L8-L10;
PLAN_PIZARRA D26, D27).

**Qué lleva** (L8), todo dentro de una carpeta `perfil/` (así no se desparrama al
descomprimirlo, y se abre con `pack_install.open_archive`, como un `.bppack`):

    perfil/manifest.toml            esquema = 1, app (versión), fecha y [lleva]
    perfil/fabricacion.md           el perfil de fabricación, si hay uno guardado
    perfil/library/<tipo>s/<clave>.toml   las fichas del workspace (las de `[meta]` válido)
    perfil/library/stock.csv        el stock, **solo si se pide** (desmarcado por defecto)

Nunca ajustes, claves, sesiones, proyectos ni rutas del disco: solo se lee del almacenamiento
el perfil de fabricación, las fichas y el stock. El zip es determinista (`pack_install.write_zip`):
el mismo perfil el mismo día da los mismos bytes.

**Importar** (D27, L9) solo sustituye el perfil del workspace actual, en tres tiempos como
importar un CSV (`library_import`): `plan(ws, ruta)` lee el zip y devuelve el resumen con un
`token`, sin escribir nada; `apply(ws, token)` lo vuelve a leer y, si sale lo mismo, escribe;
si el zip o el perfil han cambiado, `Conflict` (409). Antes de escribir nada guarda el perfil
de ahora entero (con el stock y las fichas que no valen) en `profile_copy_dir()`
(`profile/.copias/<fecha>.zip` en local): sin esa carpeta no se importa.

Aplicar sustituye `library/` entera (las fichas que no vienen en el zip se van a la papelera)
y, **solo si el zip los trae**, `fabricacion.md` y `stock.csv`: lo que no trae se queda.

**Lo que se valida** (L10): el zip como un `.bppack` (rutas dentro, sin enlaces, cuántos
ficheros y cuánto pesan) y el `esquema` del manifiesto (uno mayor que `ESQUEMA` no se importa);
si algo de eso falla, no se escribe nada. Cada ficha pasa la validación de `[meta]` de la
librería y tiene que estar en la carpeta de su tipo; una que no vale no para las demás: sale en
el resumen con su motivo y no se escribe.
"""
import datetime
import hashlib
import json
import re
import tempfile
import threading
import time
import tomllib
import uuid
from pathlib import Path

import tomli_w

from boardprint_sdk.library import STOCK_FILE, _read_stock
from pizarra import i18n, pack_install
from pizarra.library import check as check_ficha, meta_errors, parse
from pizarra.storage import Conflict, InvalidName
from pizarra.storage.local import stock_csv
from pizarra.storage.names import check_ficha_key, check_ficha_type
from pizarra.validation import ValidationError

ESQUEMA = 1                      # el formato que escribe y lee esta app
TOP = "perfil"
MANIFEST = "manifest.toml"
MANUFACTURING = "fabricacion.md"
LIBRARY = "library"
BROKEN = ".ilegibles"            # en la copia de antes de importar: las fichas que no valen
FABRICACION_MAX = 20_000         # caracteres del perfil de fabricación (V8, `workspace_api`)
PLAN_SECONDS = 30 * 60
MAX_PLANS = 10
ARCHIVE_TEXTS = {k: f"perfil_zip.{k}" for k in pack_install.ARCHIVE_TEXTS if k != "id_no_valido"}
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ------------------------------------------------------------------------- exportar
def _entries(ws, con_stock, broken=False, app=""):
    """`(ficheros, lo que lleva)`: `[(ruta dentro de perfil/, bytes)]` del perfil de `ws` y
    `{fabricacion, fichas, tipos, stock, omitidas}`. Una ficha sin `[meta]` válido no tiene
    carpeta de tipo: no va (`omitidas`), salvo con `broken`, que la lleva en
    `library/.ilegibles/` (la copia de antes de importar no pierde nada)."""
    files, tipos, omitidas = [], {}, []
    fab = ws.load_manufacturing_profile()
    if fab is not None:
        files.append((MANUFACTURING, fab.encode("utf-8")))
    for key, text in sorted(ws.list_library_fichas().items(), key=lambda kv: kv[0].casefold()):
        try:
            data = parse(text)
            errs = meta_errors(data, key)
        except ValidationError:
            errs = ["ilegible"]
        if errs:
            omitidas.append(key)
            if broken:
                files.append((f"{LIBRARY}/{BROKEN}/{key}.toml", text.encode("utf-8")))
            continue
        type_ = data["meta"]["type"]
        tipos[type_] = tipos.get(type_, 0) + 1
        files.append((f"{LIBRARY}/{type_}s/{key}.toml", text.encode("utf-8")))
    stock = ws.load_stock() if con_stock else {}
    if stock:
        files.append((f"{LIBRARY}/{STOCK_FILE}", stock_csv(stock).encode("utf-8")))
    info = {"fabricacion": fab is not None, "fichas": sum(tipos.values()), "tipos": tipos,
            "stock": len(stock) if stock else None, "omitidas": omitidas}
    manifest = {"esquema": ESQUEMA, "app": app or "", "fecha": datetime.date.today().isoformat(),
                "lleva": {"fabricacion": info["fabricacion"], "fichas": info["fichas"],
                          "stock": bool(stock)}}
    files.insert(0, (MANIFEST, tomli_w.dumps(manifest).encode("utf-8")))
    return [(f"{TOP}/{rel}", data) for rel, data in files], info


def file_name(ws):
    """`<workspace>-perfil-<fecha>.zip`, con el nombre del workspace sin lo que no admite un
    nombre de fichero."""
    name = _BAD_NAME.sub("-", ws.info().name or "").strip(" .") or "workspace"
    return f"{name}-perfil-{datetime.date.today().isoformat()}.zip"


def export(ws, carpeta, con_stock=False, app=""):
    """Escribe el perfil de `ws` en `<carpeta>/<workspace>-perfil-<fecha>.zip` (L8); el stock
    solo con `con_stock`. Devuelve `{file, nombre, fabricacion, fichas, tipos, stock,
    omitidas}`. `ValidationError` si la carpeta no existe."""
    carpeta = Path(str(carpeta or ""))
    if not str(carpeta) or not carpeta.is_dir():
        raise ValidationError(i18n.t("perfil_zip.no_existe", ruta=carpeta))
    files, info = _entries(ws, con_stock, app=app)
    dest = pack_install.write_zip(carpeta / file_name(ws), files)
    return {"file": str(dest), "nombre": dest.name, **info}


# ------------------------------------------------------------------------ leer un zip
def _text(raw):
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def read(path):
    """Lo que trae el zip `path`: `{manifest, fabricacion, fichas: {clave: (tipo, texto)},
    stock, invalid: [{ruta, clave, motivo}], ignored: [ruta], sha256}`. `fabricacion` y
    `stock` son None si no los trae. `ValidationError`, sin haber escrito nada fuera de un
    temporal, si el zip no vale entero (L10)."""
    path = Path(str(path or ""))
    if not str(path) or not path.is_file():
        raise ValidationError(i18n.t("perfil_zip.no_existe", ruta=path))
    with tempfile.TemporaryDirectory() as tmp:
        try:
            top = pack_install.open_archive(path, tmp, texts=ARCHIVE_TEXTS, top_re=None)
        except ValidationError:
            raise
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        files = {p.relative_to(top).as_posix(): p.read_bytes()
                 for p in sorted(top.rglob("*")) if p.is_file()}
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = _manifest(path.name, files.pop(MANIFEST, None))
    out = {"manifest": manifest, "fabricacion": None, "fichas": {}, "stock": None,
           "invalid": [], "ignored": [], "sha256": sha}

    def bad(ruta, motivo, clave=None):
        out["invalid"].append({"ruta": ruta, "clave": clave, "motivo": motivo})

    if MANUFACTURING in files:
        text = _text(files.pop(MANUFACTURING))
        if text is None:
            bad(MANUFACTURING, i18n.t("perfil_zip.no_utf8"))
        elif len(text) > FABRICACION_MAX:
            bad(MANUFACTURING, i18n.t("perfil_zip.fabricacion_larga", max=FABRICACION_MAX))
        else:
            out["fabricacion"] = text
    stock_rel = f"{LIBRARY}/{STOCK_FILE}"
    if stock_rel in files:
        text = _text(files.pop(stock_rel))
        if text is None:
            bad(stock_rel, i18n.t("perfil_zip.no_utf8"))
        else:
            out["stock"] = {}
            for key, entry in _read_stock(text).items():
                try:
                    out["stock"][check_ficha_key(key)] = entry
                except InvalidName as exc:
                    bad(stock_rel, str(exc), key)
    seen = {}
    for rel, raw in files.items():
        parts = rel.split("/")
        if parts[0] != LIBRARY or not rel.endswith(".toml"):
            out["ignored"].append(rel)
            continue
        key = parts[-1][:-len(".toml")]
        motivo, ficha = _ficha(parts, key, raw)
        if motivo is None and key.casefold() in seen:
            motivo = i18n.t("perfil_zip.ficha_repetida", clave=key, otra=seen[key.casefold()])
        if motivo is not None:
            bad(rel, motivo, key)
            continue
        seen[key.casefold()] = rel
        out["fichas"][key] = ficha
    return out


def _manifest(archivo, raw):
    """El manifiesto como `{esquema, app, fecha}`, o `ValidationError`: sin él, ilegible o con
    un `esquema` que no es un entero ≥ 1 o es mayor que `ESQUEMA`, el zip no se importa."""
    if raw is None:
        raise ValidationError(i18n.t("perfil_zip.sin_manifiesto", archivo=archivo))
    try:
        data = tomllib.loads(_text(raw) or "\0")
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(i18n.t("perfil_zip.manifiesto_ilegible", archivo=archivo,
                                     motivo=exc)) from None
    esquema = data.get("esquema")
    if isinstance(esquema, bool) or not isinstance(esquema, int) or esquema < 1:
        raise ValidationError(i18n.t("perfil_zip.esquema_no_valido", archivo=archivo,
                                     valor=repr(esquema)))
    if esquema > ESQUEMA:
        raise ValidationError(i18n.t("perfil_zip.esquema_mayor", archivo=archivo,
                                     esquema=esquema, max=ESQUEMA))
    return {"esquema": esquema, "app": str(data.get("app") or ""),
            "fecha": str(data.get("fecha") or "")}


def _ficha(parts, key, raw):
    """`(motivo, None)` si la ficha `library/<tipo>s/<clave>.toml` no vale, o
    `(None, (tipo, texto))`."""
    if len(parts) != 3 or not parts[1].endswith("s"):
        return i18n.t("perfil_zip.ficha_ruta"), None
    type_ = parts[1][:-1]
    try:
        check_ficha_type(type_)
        check_ficha_key(key)
    except InvalidName as exc:
        return str(exc), None
    text = _text(raw)
    if text is None:
        return i18n.t("perfil_zip.no_utf8"), None
    try:
        data = check_ficha(text, key)
    except ValidationError as exc:
        return str(exc), None
    if data["meta"]["type"] != type_:
        return i18n.t("perfil_zip.ficha_carpeta", tipo=data["meta"]["type"], carpeta=parts[1]), None
    return None, (type_, text)


# --------------------------------------------------------------------------- importar
_plans = {}
_lock = threading.Lock()


def _compute(ws, path):
    """`(resumen, lo leído)` de importar `path` en `ws`."""
    copies = ws.profile_copy_dir()
    if copies is None:
        raise ValidationError(i18n.t("perfil_zip.sin_copia"))
    prof = read(path)
    cur = ws.list_library_fichas()
    incoming = {k.casefold() for k in prof["fichas"]}
    tipos = {}
    for type_, _ in prof["fichas"].values():
        tipos[type_] = tipos.get(type_, 0) + 1
    cur_stock = ws.load_stock()
    summary = {
        "file": str(path), "nombre": Path(str(path)).name, "manifest": prof["manifest"],
        "fichas": len(prof["fichas"]), "tipos": dict(sorted(tipos.items())),
        "fabricacion": prof["fabricacion"] is not None,
        "stock": None if prof["stock"] is None else len(prof["stock"]),
        "invalid": prof["invalid"], "ignored": prof["ignored"],
        # lo que hay ahora y se va (la copia lo guarda antes)
        "sustituye": {
            "fichas": len(cur),
            "quitadas": sorted((k for k in cur if k.casefold() not in incoming), key=str.casefold),
            "fabricacion": prof["fabricacion"] is not None
                           and ws.load_manufacturing_profile() is not None,
            "stock": len(cur_stock) if prof["stock"] is not None and cur_stock else 0},
        "copia": str(copies)}
    return summary, prof


def _digest(summary, prof):
    return hashlib.sha256(json.dumps([summary, prof["sha256"]], sort_keys=True,
                                     ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def plan(ws, path):
    """El resumen de importar el perfil `path` en `ws`, con el `token` para aplicarlo. No
    escribe nada. `ValidationError` si el zip no vale entero."""
    summary, prof = _compute(ws, path)
    token = uuid.uuid4().hex
    now = time.monotonic()
    with _lock:
        for t in [t for t, p in _plans.items() if p["until"] < now]:
            del _plans[t]
        while len(_plans) >= MAX_PLANS:
            del _plans[min(_plans, key=lambda t: _plans[t]["until"])]
        _plans[token] = {"path": str(path), "digest": _digest(summary, prof),
                         "until": now + PLAN_SECONDS, "ws": id(ws)}
    return {"token": token, **summary}


def write_copy(ws):
    """El perfil de ahora entero (stock y fichas que no valen incluidos) en
    `<profile_copy_dir>/<fecha y hora>.zip`; devuelve su ruta. Nunca pisa otra copia."""
    d = ws.profile_copy_dir()
    if d is None:
        raise ValidationError(i18n.t("perfil_zip.sin_copia"))
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    dest, n = d / f"{stamp}.zip", 1
    while dest.exists():
        n += 1
        dest = d / f"{stamp}-{n}.zip"
    files, _ = _entries(ws, con_stock=True, broken=True)
    return pack_install.write_zip(dest, files)


def apply(ws, token):
    """Escribe lo del resumen `token` si sigue siendo lo mismo (si no, `Conflict`): primero la
    copia y después el perfil. Devuelve `{copia, fichas, quitadas, fabricacion, stock}`."""
    with _lock:
        p = _plans.pop(token, None) if isinstance(token, str) else None
    if p is None or p["until"] < time.monotonic() or p["ws"] != id(ws):
        raise Conflict(i18n.t("perfil_zip.plan_caducado"))
    summary, prof = _compute(ws, p["path"])
    if _digest(summary, prof) != p["digest"]:
        raise Conflict(i18n.t("perfil_zip.plan_caducado"))
    copia = write_copy(ws)
    if prof["fabricacion"] is not None:
        ws.save_manufacturing_profile(prof["fabricacion"])
    # fuera las que no vienen tal cual (también la `abc` de una `ABC` que viene: en Windows
    # serían el mismo fichero), y después las del zip
    for key in [k for k in ws.list_library_fichas() if k not in prof["fichas"]]:
        ws.trash_library_ficha(key)
    for key, (type_, text) in prof["fichas"].items():
        ws.save_library_ficha(key, type_, text)
    if prof["stock"] is not None:
        ws.save_stock(prof["stock"])
    return {"copia": str(copia), "fichas": len(prof["fichas"]),
            "quitadas": len(summary["sustituye"]["quitadas"]),
            "fabricacion": prof["fabricacion"] is not None, "stock": summary["stock"]}
