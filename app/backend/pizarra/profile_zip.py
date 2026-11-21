"""El perfil del workspace en un `.zip`: exportarlo e importarlo (docs/PLAN_LIBRERIA.md §5, L8-L10;
PLAN_PIZARRA D26, D27).

**Qué lleva** (L8), todo dentro de una carpeta `perfil/` (así no se desparrama al
descomprimirlo, y se abre con `pack_install.open_archive`, como un `.bppack`):

    perfil/manifest.toml            esquema = 1, app (versión), fecha y [lleva]
    perfil/fabricacion.md           el perfil de fabricación, si hay uno guardado
    perfil/proveedores.toml         los proveedores, si hay lista (PLAN_APROVISIONAMIENTO A2);
                                    las ofertas (`ofertas.json`) nunca: caducan (A8)
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
y, **solo si el zip los trae**, `fabricacion.md`, `proveedores.toml` y `stock.csv`: lo que
no trae se queda.

**Hacia un workspace nuevo** (PLAN_WORKSPACES W4): `plan(None, ruta, destino="nuevo")` y
`apply(ws, token, destino="nuevo")` sobre el `LocalWorkspace` recién creado. No hay nada que
sustituir ni copia previa; si el workspace ya tiene perfil, `Conflict`. El token se ata al
fichero y al destino (el id del workspace, o «nuevo»): uno de otro destino es `Conflict`.

**Plantillas de sector** (W4, W5): una carpeta `profile_templates/<id>/` con los mismos
ficheros que la carpeta `perfil/` del zip (`manifest.toml`, con `generica = true` y su
`[plantilla]`, y `fabricacion.md`); un `<nombre>.<idioma>.md` de la raíz sustituye a
`<nombre>.md` en ese idioma. `write_template` la empaqueta como un zip, que pasa por el mismo
`plan`.

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
from pizarra import i18n, pack_install, supply
from pizarra.library import check as check_ficha, meta_errors, parse
from pizarra.storage import Conflict, InvalidName
from pizarra.storage.local import stock_csv
from pizarra.storage.names import check_ficha_key, check_ficha_type
from pizarra.validation import ValidationError

ESQUEMA = 1                      # el formato que escribe y lee esta app
TOP = "perfil"
MANIFEST = "manifest.toml"
MANUFACTURING = "fabricacion.md"
PROVIDERS = "proveedores.toml"   # A2: viaja con el perfil; las ofertas no (A8)
LIBRARY = "library"
BROKEN = ".ilegibles"            # en la copia de antes de importar: las fichas que no valen
FABRICACION_MAX = 20_000         # caracteres del perfil de fabricación (V8, `workspace_api`)
PLAN_SECONDS = 30 * 60
DESTINOS = ("actual", "nuevo")   # el workspace abierto, o uno recién creado (PLAN_WORKSPACES W4)
TEMPLATES_DIR = Path(__file__).resolve().parent / "profile_templates"
TEMPLATE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_VARIANT = re.compile(r"(?P<base>[^/]+)\.(?P<lang>[a-z]{2})(?P<ext>\.[a-z]+)")
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
    provs = ws.load_providers_text()
    if provs is not None:
        files.append((PROVIDERS, provs.encode("utf-8")))
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
            "stock": len(stock) if stock else None, "omitidas": omitidas,
            "proveedores": provs is not None}
    manifest = {"esquema": ESQUEMA, "app": app or "", "fecha": datetime.date.today().isoformat(),
                "lleva": {"fabricacion": info["fabricacion"], "fichas": info["fichas"],
                          "stock": bool(stock), "proveedores": info["proveedores"]}}
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
           "proveedores": None, "invalid": [], "ignored": [], "sha256": sha}

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
    if PROVIDERS in files:
        text = _text(files.pop(PROVIDERS))
        if text is None:
            bad(PROVIDERS, i18n.t("perfil_zip.no_utf8"))
        else:
            try:
                supply.parse_providers(text)
                out["proveedores"] = text
            except ValidationError as exc:
                bad(PROVIDERS, str(exc))
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
            "fecha": str(data.get("fecha") or ""), "generica": data.get("generica") is True}


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


def _destino(destino):
    if destino not in DESTINOS:
        raise ValidationError(i18n.t("perfil_zip.destino_no_valido", valor=repr(destino)))
    return destino


def _target(ws, destino):
    """A qué se ata un token: «nuevo», o el id del workspace (no el objeto, `id(ws)`)."""
    return "nuevo" if destino == "nuevo" else f"ws:{ws.info().id}"


def _compute(ws, path, destino="actual"):
    """`(resumen, lo leído)` de importar `path` en `ws` o, con `destino="nuevo"`, en un
    workspace nuevo (sin nada que sustituir ni copia: `ws` no se mira)."""
    nuevo = _destino(destino) == "nuevo"
    copies = None if nuevo else ws.profile_copy_dir()
    if copies is None and not nuevo:
        raise ValidationError(i18n.t("perfil_zip.sin_copia"))
    prof = read(path)
    cur = {} if nuevo else ws.list_library_fichas()
    incoming = {k.casefold() for k in prof["fichas"]}
    tipos = {}
    for type_, _ in prof["fichas"].values():
        tipos[type_] = tipos.get(type_, 0) + 1
    cur_stock = {} if nuevo else ws.load_stock()
    summary = {
        "file": str(path), "nombre": Path(str(path)).name, "manifest": prof["manifest"],
        "fichas": len(prof["fichas"]), "tipos": dict(sorted(tipos.items())),
        "fabricacion": prof["fabricacion"] is not None,
        "proveedores": prof["proveedores"] is not None,
        "stock": None if prof["stock"] is None else len(prof["stock"]),
        "invalid": prof["invalid"], "ignored": prof["ignored"],
        # lo que hay ahora y se va (la copia lo guarda antes)
        "sustituye": {
            "fichas": len(cur),
            "quitadas": sorted((k for k in cur if k.casefold() not in incoming), key=str.casefold),
            "fabricacion": prof["fabricacion"] is not None and not nuevo
                           and ws.load_manufacturing_profile() is not None,
            "stock": len(cur_stock) if prof["stock"] is not None and cur_stock else 0},
        "copia": None if nuevo else str(copies), "destino": destino}
    return summary, prof


def _digest(summary, prof):
    return hashlib.sha256(json.dumps([summary, prof["sha256"]], sort_keys=True,
                                     ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def plan(ws, path, destino="actual"):
    """El resumen de importar el perfil `path` en `ws` (con `destino="nuevo"`, en un workspace
    que aún no existe: `ws` puede ser None), con el `token` para aplicarlo. No escribe nada.
    `ValidationError` si el zip no vale entero o el destino no es uno de `DESTINOS`."""
    summary, prof = _compute(ws, path, destino)
    token = uuid.uuid4().hex
    now = time.monotonic()
    with _lock:
        for t in [t for t, p in _plans.items() if p["until"] < now]:
            del _plans[t]
        while len(_plans) >= MAX_PLANS:
            del _plans[min(_plans, key=lambda t: _plans[t]["until"])]
        _plans[token] = {"path": str(path), "digest": _digest(summary, prof),
                         "until": now + PLAN_SECONDS, "target": _target(ws, destino)}
    return {"token": token, **summary}


def _valid(p, ws, destino):
    """`(resumen, lo leído)` del plan `p` si sigue valiendo para `ws` y `destino`; si no,
    `Conflict`."""
    if p is None or p["until"] < time.monotonic() or (ws is None and destino != "nuevo") \
            or p["target"] != _target(ws, destino):
        raise Conflict(i18n.t("perfil_zip.plan_caducado"))
    summary, prof = _compute(ws, p["path"], destino)
    if _digest(summary, prof) != p["digest"]:
        raise Conflict(i18n.t("perfil_zip.plan_caducado"))
    return summary, prof


def check_token(token, destino="actual", ws=None):
    """`Conflict` si `apply` con `token` hacia `destino` no valdría (caducado, de otro destino
    o con el zip cambiado), sin gastarlo: así no se crea un workspace que luego no se llena."""
    with _lock:
        p = _plans.get(token) if isinstance(token, str) else None
    _valid(p, ws, _destino(destino))


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


def apply(ws, token, destino="actual"):
    """Escribe en `ws` lo del resumen `token` si sigue siendo lo mismo (si no, `Conflict`):
    primero la copia y después el perfil. Con `destino="nuevo"`, sin copia, y `Conflict` si
    `ws` ya tiene perfil. Devuelve `{copia, fichas, quitadas, fabricacion, stock}`."""
    _destino(destino)
    with _lock:
        p = _plans.pop(token, None) if isinstance(token, str) else None
    summary, prof = _valid(p, ws, destino)
    if destino == "nuevo":
        if (ws.list_library_fichas() or ws.load_manufacturing_profile() is not None
                or ws.load_providers_text() is not None or ws.load_stock()):
            raise Conflict(i18n.t("perfil_zip.destino_no_vacio"))
        copia = None
    else:
        copia = write_copy(ws)
    if prof["fabricacion"] is not None:
        ws.save_manufacturing_profile(prof["fabricacion"])
    if prof["proveedores"] is not None:
        ws.save_providers_text(prof["proveedores"])
    # fuera las que no vienen tal cual (también la `abc` de una `ABC` que viene: en Windows
    # serían el mismo fichero), y después las del zip
    for key in [k for k in ws.list_library_fichas() if k not in prof["fichas"]]:
        ws.trash_library_ficha(key)
    for key, (type_, text) in prof["fichas"].items():
        ws.save_library_ficha(key, type_, text)
    if prof["stock"] is not None:
        ws.save_stock(prof["stock"])
    return {"copia": None if copia is None else str(copia), "fichas": len(prof["fichas"]),
            "quitadas": len(summary["sustituye"]["quitadas"]),
            "fabricacion": prof["fabricacion"] is not None,
            "proveedores": prof["proveedores"] is not None, "stock": summary["stock"]}


# ----------------------------------------------------------- plantillas de sector (W4, W5)
def _template_dir(template_id):
    if not isinstance(template_id, str) or not TEMPLATE_ID.fullmatch(template_id) \
            or not (TEMPLATES_DIR / template_id / MANIFEST).is_file():
        raise ValidationError(i18n.t("perfil_zip.plantilla_no_existe", id=template_id))
    return TEMPLATES_DIR / template_id


def _localized(table, language):
    """El texto de `{es, en}` en `language` (si no lo tiene, en español)."""
    if not isinstance(table, dict):
        return str(table or "")
    return str(table.get(language or i18n.language()) or table.get("es") or "")


def templates(language=None):
    """Las plantillas que vienen con la app: `[{id, titulo, descripcion, generica, lleva}]`,
    con los textos en `language` (por defecto, el de la app); `lleva`, la del manifiesto."""
    out = []
    for d in sorted(TEMPLATES_DIR.iterdir()) if TEMPLATES_DIR.is_dir() else []:
        if not (TEMPLATE_ID.fullmatch(d.name) and (d / MANIFEST).is_file()):
            continue
        data = tomllib.loads((d / MANIFEST).read_text(encoding="utf-8"))
        info = data.get("plantilla") if isinstance(data.get("plantilla"), dict) else {}
        lleva = data.get("lleva") if isinstance(data.get("lleva"), dict) else {}
        out.append({"id": d.name, "titulo": _localized(info.get("titulo"), language),
                    "descripcion": _localized(info.get("descripcion"), language),
                    "generica": data.get("generica") is True,
                    "lleva": {"fabricacion": lleva.get("fabricacion") is True,
                              "fichas": int(lleva.get("fichas") or 0),
                              "proveedores": lleva.get("proveedores") is True}})
    return out


def write_template(template_id, carpeta, language=None):
    """Empaqueta la plantilla `template_id` en `<carpeta>/<id>.zip`, como un perfil exportado,
    con los ficheros de `language` (`fabricacion.en.md` en inglés; si no hay, el de por
    defecto). Lo mismo da los mismos bytes. `ValidationError` si no existe."""
    folder = _template_dir(template_id)
    language = language or i18n.language()
    files, variants = {}, {}
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(folder).as_posix()
        m = _VARIANT.fullmatch(rel)
        if m and m["lang"] in i18n.CATALOGS:
            if m["lang"] == language:
                variants[m["base"] + m["ext"]] = p.read_bytes()
            continue
        files[rel] = p.read_bytes()
    files.update(variants)
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    order = sorted(files, key=lambda r: (r != MANIFEST, r))
    return pack_install.write_zip(carpeta / f"{template_id}.zip",
                                  [(f"{TOP}/{rel}", files[rel]) for rel in order])
