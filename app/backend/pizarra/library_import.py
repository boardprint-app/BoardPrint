"""Importar a la librería un CSV o un Excel con mapeo de columnas (docs/PLAN_V020.md V16; D33).

Tres pasos, y **nada se escribe hasta el tercero**:

1. `inspect(ruta, hoja)`: las hojas, las columnas (la primera fila con algo es la cabecera) y
   unas filas de muestra.
2. `plan(librería, ruta, hoja, tipo, mapeo)`: qué fila crea una ficha, cuál la actualiza, cuál
   solo toca el stock, cuál no cambia nada y cuál **no vale y por qué**. Devuelve un `token`.
3. `apply(librería, token)`: vuelve a hacer el plan con lo mismo y, si da lo mismo que se
   enseñó, lo escribe; si el archivo o la librería han cambiado entre tanto, `Conflict`.

Una fila mala **nunca tumba las buenas**: sale en el resumen con su motivo y se salta.

El mapeo es `{columna: campo}`; los campos son `key` (obligatorio), `manufacturer` y `kind`
(de `[meta]`), `cantidad`, `ubicacion`, `fecha` y `nota` (del stock) y `values.<campo>` (un
valor de la ficha, con lo que el paquete use para ese tipo: `WorkspaceLibrary.fields`). El
núcleo no sabe los campos de un tipo (V15), así que acepta cualquiera.

Reglas de lo que se escribe:
- Una celda vacía no borra lo que ya había. En el stock, una entrada nueva sin cantidad queda
  con la cantidad desconocida (None), nunca 0 (D33).
- Una ficha nueva nace «sin verificar», con el archivo como fuente (`[source]` con su sha256) y
  cada valor con su sitio (`Stock.xlsx, Hoja1, fila 7`): la regla de los números (D19).
- Cambiar un valor de una ficha verificada la deja «sin verificar» (lo dice el resumen).
- Una ficha que solo está en un paquete se copia entera al workspace con los cambios (la del
  workspace manda, V15); si el mapeo no lleva campos de ficha, solo se toca el stock: una fila
  de stock nunca tapa la ficha de un paquete.
"""
import copy
import csv
import datetime
import hashlib
import io
import json
import math
import threading
import time
import uuid
from pathlib import Path

from pizarra import i18n
from pizarra.library import ORIGIN_PACK, ORIGIN_WORKSPACE, STOCK_TEXT, dump
from pizarra.storage import Conflict, InvalidName
from pizarra.storage.names import check_ficha_key, check_ficha_type
from pizarra.validation import ValidationError
from boardprint_sdk.library import _quantity

EXTS = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm"}
META_TARGETS = ("manufacturer", "kind")
STOCK_TARGETS = ("cantidad", *STOCK_TEXT)
VALUE_PREFIX = "values."
MAX_ROWS = 20_000
SAMPLE_ROWS = 8
PLAN_SECONDS = 30 * 60          # lo que vale un resumen antes de aplicarlo
MAX_PLANS = 20
_FIELD_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


# ------------------------------------------------------------------ leer la tabla
def _cell(v):
    """Una celda como dato: vacía → None; una fecha, su ISO; un número entero, int."""
    if v is None:
        return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return (v.date() if isinstance(v, datetime.datetime) and not (v.hour or v.minute or v.second)
                else v).isoformat()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        return v.strip() or None
    return v


def _decode(raw):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _csv_rows(path):
    text = _decode(path.read_bytes())
    try:
        dialect = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    return [[_cell(c) for c in row] for row in csv.reader(io.StringIO(text), dialect)]


def _xlsx(path, sheet):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        names = list(wb.sheetnames)
        if sheet in (None, ""):
            sheet = names[0]
        if sheet not in names:
            raise ValidationError(i18n.t("importar.hoja_no_existe", hoja=repr(sheet),
                                         hojas=", ".join(names)))
        rows = []
        for row in wb[sheet].iter_rows(values_only=True):
            rows.append([_cell(c) for c in row])
            if len(rows) > MAX_ROWS + 50:
                break
        return names, sheet, rows
    finally:
        wb.close()


def read_table(path, sheet=None):
    """`(hojas, hoja, columnas, [(nº de fila, {columna: celda})])` del archivo. La primera fila
    con algo es la cabecera; una columna sin nombre se llama por su número; las filas vacías no
    salen. `ValidationError` con el motivo si no se puede."""
    path = Path(str(path or ""))
    if path.suffix.lower() not in EXTS:
        raise ValidationError(i18n.t("importar.formato", nombre=path.name or str(path)))
    if not path.is_file():
        raise ValidationError(i18n.t("importar.no_existe", ruta=path))
    try:
        if path.suffix.lower() in (".xlsx", ".xlsm"):
            sheets, sheet, rows = _xlsx(path, sheet)
        else:
            sheets, sheet, rows = [], "", _csv_rows(path)
    except ValidationError:
        raise
    except Exception as exc:          # noqa: BLE001 un archivo roto: el motivo al usuario
        raise ValidationError(i18n.t("importar.ilegible", nombre=path.name, motivo=exc)) from None
    numbered = [(i + 1, r) for i, r in enumerate(rows) if any(c is not None for c in r)]
    if len(numbered) < 2:
        raise ValidationError(i18n.t("importar.vacio", nombre=path.name))
    if len(numbered) > MAX_ROWS + 1:
        raise ValidationError(i18n.t("importar.demasiadas", nombre=path.name, max=MAX_ROWS))
    (_, head), body = numbered[0], numbered[1:]
    columns, seen = [], {}
    for i, h in enumerate(head):
        name = str(h).strip() if h is not None else f"#{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        columns.append(name)
    width = len(columns)
    table = [(n, {columns[j]: (r[j] if j < len(r) else None) for j in range(width)})
             for n, r in body]
    return sheets, sheet, columns, table


def inspect(path, sheet=None):
    """Lo que hace falta para mapear: `{file, sheets, sheet, columns, sample, rows}`; `sample`
    son las primeras filas como `{columna: celda}` (con su nº de fila en `_row`)."""
    sheets, sheet, columns, table = read_table(path, sheet)
    return {"file": str(path), "sheets": sheets, "sheet": sheet, "columns": columns,
            "sample": [{"_row": n, **row} for n, row in table[:SAMPLE_ROWS]], "rows": len(table)}


# --------------------------------------------------------------------- el mapeo
def check_mapping(mapping, columns):
    """`{columna: campo}` sin las columnas que no van a ningún sitio, o `ValidationError`."""
    if not isinstance(mapping, dict):
        raise ValidationError(i18n.t("importar.mapeo_no_objeto"))
    out, used = {}, set()
    for col, target in mapping.items():
        if target in (None, ""):
            continue
        if col not in columns:
            raise ValidationError(i18n.t("importar.columna_no_existe", columna=repr(col)))
        ok = target == "key" or target in META_TARGETS or target in STOCK_TARGETS or (
            isinstance(target, str) and target.startswith(VALUE_PREFIX)
            and target[len(VALUE_PREFIX):] and set(target[len(VALUE_PREFIX):]) <= _FIELD_OK
            and not target[len(VALUE_PREFIX)].isdigit())
        if not ok:
            raise ValidationError(i18n.t("importar.destino_no_valido", campo=repr(target)))
        if target in used:
            raise ValidationError(i18n.t("importar.destino_repetido", campo=target))
        used.add(target)
        out[col] = target
    if "key" not in used:
        raise ValidationError(i18n.t("importar.sin_clave"))
    return out


def _number(v):
    """Un valor de ficha: un número si lo es (con coma o punto decimal), si no el texto."""
    if isinstance(v, str):
        s = v.replace(",", ".") if v.count(",") == 1 and "." not in v else v
        try:
            x = float(s)
        except ValueError:
            return v
        if not math.isfinite(x):
            return v
        return int(x) if x.is_integer() and "e" not in s.lower() and "." not in s else x
    return v


def _text(v):
    return v if isinstance(v, str) else (str(v) if v is not None else None)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------- el plan
def _compute(lib, path, sheet, type_, mapping):
    """`(resumen, escrituras)`: el resumen para el usuario y lo que `apply` escribiría
    (`{"fichas": {clave: (tipo, texto)}, "stock": {clave: entrada}}`)."""
    path = Path(str(path or ""))
    sheets, sheet, columns, table = read_table(path, sheet)
    mapping = check_mapping(mapping, columns)
    targets = set(mapping.values())
    ficha_targets = targets & set(META_TARGETS) | {t for t in targets if t.startswith(VALUE_PREFIX)}
    stock_targets = targets & set(STOCK_TARGETS)
    if ficha_targets:
        if not type_:
            raise ValidationError(i18n.t("importar.sin_tipo"))
        try:
            check_ficha_type(type_)
        except InvalidName as exc:
            raise ValidationError(str(exc)) from None
    sha = _sha256(path) if ficha_targets else ""
    where = sheet or ""
    stock = lib.stock()
    rows, seen = [], {}
    writes = {"fichas": {}, "stock": {}}
    for n, cells in table:
        got = {t: cells[c] for c, t in mapping.items()}
        key = _text(got.get("key"))
        row = {"row": n, "key": key, "ficha": None, "stock": None, "warnings": []}
        rows.append(row)

        def bad(reason):                # nada de la fila se escribe
            row.update(state="invalid", reason=reason, ficha=None, stock=None, warnings=[])

        if not key:
            bad(i18n.t("importar.fila_sin_clave"))
            continue
        try:
            check_ficha_key(key)
        except InvalidName as exc:
            bad(str(exc))
            continue
        if key in seen:
            bad(i18n.t("importar.fila_repetida", clave=key, fila=seen[key]))
            continue
        seen[key] = n
        ficha = None
        if ficha_targets:
            ficha, err = _ficha_for(lib, key, type_, got, row, path, where, n, sha)
            if err:
                bad(err)
                continue
        entry = None
        if stock_targets:
            try:
                entry = _stock_for(stock.get(key), got)
            except ValueError as exc:
                bad(i18n.t("libreria.stock_cantidad", valor=str(exc).split(": ", 1)[-1]))
                continue
            if entry is not None:
                row["stock"] = "update" if key in stock else "create"
                writes["stock"][key] = entry
                row["cantidad"] = entry["cantidad"]
        if ficha is not None:
            writes["fichas"][key] = ficha
        if row["ficha"] == "create" or (row["ficha"] is None and row["stock"] == "create"):
            row["state"] = "create"
        else:
            row["state"] = "update" if row["ficha"] or row["stock"] else "unchanged"
    counts = {s: sum(1 for r in rows if r.get("state") == s)
              for s in ("create", "update", "unchanged", "invalid")}
    summary = {"file": str(path), "sheet": sheet, "type": type_ or "", "mapping": mapping,
               "rows": rows, "counts": counts,
               "writes": {"fichas": len(writes["fichas"]), "stock": len(writes["stock"])}}
    return summary, writes


def _ficha_for(lib, key, type_, got, row, path, where, n, sha):
    """`(texto de la ficha a escribir | None, motivo si la fila no vale)`, y en `row` qué se
    hace (`ficha`: create/update) y los avisos."""
    meta_new = {t: _text(got[t]) for t in META_TARGETS if got.get(t) is not None}
    values_new = {t[len(VALUE_PREFIX):]: _number(got[t]) for t in got
                  if t.startswith(VALUE_PREFIX) and got[t] is not None}
    src = (i18n.t("importar.fuente", archivo=path.name, hoja=where, fila=n) if where
           else i18n.t("importar.fuente_csv", archivo=path.name, fila=n))
    known = lib.ficha_data(key)
    if known is not None and known[0] == ORIGIN_WORKSPACE and known[2] is None:
        return None, i18n.t("importar.fila_ilegible", clave=key)
    if known is not None:
        origin, pack, data = known
        old_type = (data.get("meta") or {}).get("type")
        if old_type != type_:
            return None, i18n.t("importar.fila_otro_tipo", clave=key, tipo=old_type, nuevo=type_)
        if not meta_new and not values_new:
            return None, None
        data = copy.deepcopy(data)
        meta = data.setdefault("meta", {})
        values = data.setdefault("values", {})
        changed_values = [k for k, v in values_new.items()
                          if not isinstance(values.get(k), dict) or values[k].get("v") != v]
        changed_meta = [k for k, v in meta_new.items() if meta.get(k) != v]
        if not changed_values and not changed_meta:
            return None, None
        meta.update(meta_new)
        for k in changed_values:
            values[k] = {"v": values_new[k], "src": src}
        if changed_values and meta.get("status") == "verified":
            meta.update(status="unverified", verified_by="", verified_on="")
            row["warnings"].append(i18n.t("importar.aviso_verificada"))
        if "source" not in data and "sources" not in data:
            data["source"] = {"title": path.name, "file": path.name, "sha256": sha}
        if origin == ORIGIN_PACK:
            row["warnings"].append(i18n.t("importar.aviso_paquete", paquete=pack))
            row["ficha"] = "create"
        else:
            row["ficha"] = "update"
    else:
        if not meta_new and not values_new:
            return None, None
        data = {"meta": {"key": key, "type": type_, "kind": meta_new.get("kind", ""),
                         "manufacturer": meta_new.get("manufacturer", ""), "status": "unverified",
                         "verified_by": "", "verified_on": ""},
                "source": {"title": path.name, "file": path.name, "sha256": sha},
                "values": {k: {"v": v, "src": src} for k, v in values_new.items()}}
        row["ficha"] = "create"
    return (type_, dump(data)), None


def _stock_for(old, got):
    """La entrada de stock tras la fila, o None si no cambia. Una celda vacía no borra lo que
    había; una entrada nueva sin cantidad, desconocida (D33). `ValueError` con la cantidad mala."""
    entry = dict(old) if old else {"cantidad": None, **{c: "" for c in STOCK_TEXT}}
    if got.get("cantidad") is not None:
        entry["cantidad"] = _quantity(got["cantidad"] if isinstance(got["cantidad"], str)
                                      else repr(got["cantidad"]))
    for c in STOCK_TEXT:
        if got.get(c) is not None:
            entry[c] = _text(got[c]).strip()
    return None if old is not None and entry == old else entry


# ------------------------------------------------------------- los resúmenes vivos
_plans = {}
_lock = threading.Lock()


def _digest(writes):
    return hashlib.sha256(json.dumps(writes, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()


def plan(lib, path, sheet, type_, mapping):
    """El resumen de lo que haría importar (`_compute`), con el `token` para aplicarlo. No
    escribe nada."""
    summary, writes = _compute(lib, path, sheet, type_, mapping)
    token = uuid.uuid4().hex
    now = time.monotonic()
    with _lock:
        for t in [t for t, p in _plans.items() if p["until"] < now]:
            del _plans[t]
        while len(_plans) >= MAX_PLANS:
            del _plans[min(_plans, key=lambda t: _plans[t]["until"])]
        _plans[token] = {"args": (str(path), sheet, type_, summary["mapping"]),
                         "digest": _digest(writes), "until": now + PLAN_SECONDS,
                         "ws": id(lib.ws)}
    return {"token": token, **summary}


def apply(lib, token):
    """Escribe lo del resumen `token` si sigue siendo lo mismo; si no, `Conflict` (hay que
    pedir otro). Devuelve `{created, updated, stock, skipped}`."""
    with _lock:
        p = _plans.pop(token, None) if isinstance(token, str) else None
    if p is None or p["until"] < time.monotonic() or p["ws"] != id(lib.ws):
        raise Conflict(i18n.t("importar.plan_caducado"))
    summary, writes = _compute(lib, *p["args"])
    if _digest(writes) != p["digest"]:
        raise Conflict(i18n.t("importar.plan_caducado"))
    for key, (type_, text) in writes["fichas"].items():
        lib.ws.save_library_ficha(key, type_, text)
    if writes["stock"]:
        stock = lib.stock()
        stock.update(writes["stock"])
        lib.ws.save_stock(stock)
    c = summary["counts"]
    return {"created": c["create"], "updated": c["update"], "unchanged": c["unchanged"],
            "invalid": c["invalid"], "fichas": len(writes["fichas"]),
            "stock": len(writes["stock"])}

