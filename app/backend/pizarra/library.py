"""La librería de componentes del workspace (docs/PLAN_V020.md §5, V14, V15, V17; D32, D33).

`<workspace>/library/` guarda las fichas del usuario en el formato de las de los paquetes
(TOML con `[meta]`, `[source]` o `[[sources]]` y `[values]`) y su stock (`stock.csv`). El
almacenamiento (`Workspace`) guarda el texto; esto es lo que el núcleo sabe de una ficha, que
es poco a propósito (V15): **valida `[meta]` (`key`, `type`, `status`) y guarda el resto tal
cual**. No sabe qué es una reductora ni qué campos lleva: eso es del paquete que la usa, que la
lee por el SDK (`ctx.library`, `boardprint_sdk.library`).

Las fichas que traen los paquetes (`<paquete>/library/<tipo>s/*.toml`, la convención de las
fichas de componentes) se ven aquí en solo lectura, con su paquete, para que el ingeniero les
apunte stock y el agente las encuentre (`buscar_libreria`). Una ficha del workspace con la misma
clave manda sobre la del paquete (V15): la tabla lo dice (`overrides`).

Lo que significan los campos de un tipo lo declara el paquete, como datos, en
`<paquete>/library/schema.toml` (docs/PLAN_LIBRERIA.md L3): la carga de los paquetes lo lee
(`library_schema.read`) sin ejecutar su código, y de ahí salen la unidad y la descripción de
cada campo (`fields`) y las pestañas de los tipos que aún no tienen fichas (`types`). En la
raíz de `library/`, nunca se lee como una ficha (esas van en `library/<tipo>s/`).

El stock es por clave (`{cantidad, ubicacion, fecha, nota}`); `cantidad` None es «desconocida»,
nunca 0 (D33): «no sé cuántas tengo» no es «no tengo».

Importar un CSV o un Excel con mapeo de columnas (V16) está en `library_import`.
"""
import datetime
import math
import re
import tomllib
from pathlib import Path

import tomli_w

from boardprint_sdk.library import STOCK_COLUMNS, Library, _quantity
from pizarra import i18n
from pizarra.library_schema import PACK_LIBRARY
from pizarra.storage import InvalidName, NotFound
from pizarra.storage.names import check_ficha_key, check_ficha_type
from pizarra.validation import ValidationError

STATUSES = ("unverified", "verified")
STOCK_TEXT = STOCK_COLUMNS[2:]            # ubicacion, fecha, nota
ORIGIN_WORKSPACE, ORIGIN_PACK, ORIGIN_STOCK = "workspace", "pack", "stock"
SEARCH_MAX = 20                           # lo que devuelve `buscar_libreria` como mucho
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


# ------------------------------------------------------------------------ una ficha
def parse(text):
    """El TOML de una ficha como dict, o `ValidationError` con el motivo."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(i18n.t("libreria.ilegible", motivo=exc)) from None


def meta_errors(data, key=None):
    """Lo que no vale de `[meta]` (V15): `key`, `type` y `status`, y que `key` sea la clave
    con que se guarda. Lo demás de la ficha no se mira."""
    meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        return [i18n.t("libreria.sin_meta")]
    errs = [i18n.t("libreria.meta_falta", campo=c) for c in ("key", "type", "status")
            if not isinstance(meta.get(c), str) or not meta[c].strip()]
    if errs:
        return errs
    for check, value in ((check_ficha_key, meta["key"]), (check_ficha_type, meta["type"])):
        try:
            check(value)
        except InvalidName as exc:
            errs.append(str(exc))
    if meta["status"] not in STATUSES:
        errs.append(i18n.t("libreria.estado_no_valido", valor=repr(meta["status"])))
    if key is not None and meta["key"] != key:
        errs.append(i18n.t("libreria.clave_distinta", meta=repr(meta["key"]), clave=repr(key)))
    return errs


def check(text, key=None):
    """El dict de una ficha válida para guardar, o `ValidationError` con todos los motivos."""
    if not isinstance(text, str):
        raise ValidationError(i18n.t("libreria.sin_texto"))
    data = parse(text)
    errs = meta_errors(data, key)
    if errs:
        raise ValidationError("; ".join(errs))
    return data


def jsonable(x):
    """Lo de un TOML que no es JSON (fechas y horas), como texto ISO."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [jsonable(v) for v in x]
    if isinstance(x, (datetime.date, datetime.time, datetime.datetime)):
        return x.isoformat()
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    return x


def _toml_value(x):
    """Un valor en una línea de TOML (las listas también, a diferencia de `tomli_w`)."""
    if isinstance(x, list):
        return "[" + ", ".join(_toml_value(v) for v in x) + "]"
    if isinstance(x, dict):
        return "{ " + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in x.items()) + " }"
    return tomli_w.dumps({"x": x})[4:].rstrip("\n")


def _toml_key(k):
    return k if _BARE_KEY.fullmatch(k) else tomli_w.dumps({k: 0}).rsplit(" = ", 1)[0]


def dump(data):
    """El TOML de una ficha en el formato de las de los paquetes: `[meta]`, las fuentes y
    `[values]` con cada campo en una línea (`ratio = { v = 100, src = "…" }`), y lo demás
    detrás, tal cual."""
    loose = {k: v for k, v in data.items() if not isinstance(v, dict)
             and not (isinstance(v, list) and v and all(isinstance(e, dict) for e in v))}
    parts = [tomli_w.dumps(loose)] if loose else []
    order = ["meta", "source", "sources", "values"]
    for k in order + [k for k in data if k not in order and k not in loose]:
        if k not in data or k in loose:
            continue
        v = data[k]
        if k == "values" and isinstance(v, dict) and all(isinstance(e, dict) for e in v.values()):
            parts.append("[values]\n" + "".join(f"{_toml_key(n)} = {_toml_value(e)}\n"
                                                 for n, e in v.items()))
        else:
            parts.append(tomli_w.dumps({k: v}))
    return "\n".join(p.rstrip("\n") + "\n" for p in parts if p.strip())


def _summary(key, data, origin, pack=None, error=None):
    meta = data.get("meta") if isinstance(data, dict) and isinstance(data.get("meta"), dict) else {}
    values = data.get("values") if isinstance(data, dict) and isinstance(data.get("values"), dict) else {}
    return {"key": key, "type": str(meta.get("type") or ""), "kind": str(meta.get("kind") or ""),
            "manufacturer": str(meta.get("manufacturer") or ""),
            "status": str(meta.get("status") or "unverified"),
            "verified_by": str(meta.get("verified_by") or ""),
            "verified_on": str(meta.get("verified_on") or ""),
            "fields": len(values), "origin": origin, "pack": pack, "overrides": None,
            "editable": origin == ORIGIN_WORKSPACE, "error": error}


# --------------------------------------------------------------------- stock
def clean_stock_entry(entry):
    """`{cantidad, ubicacion, fecha, nota}` validado; `cantidad` None o vacía = desconocida
    (D33), un número ≥ 0 (o su texto, con coma o punto). `ValidationError` con el motivo."""
    if not isinstance(entry, dict):
        raise ValidationError(i18n.t("libreria.stock_no_objeto"))
    for k in entry:
        if k not in ("cantidad", *STOCK_TEXT):
            raise ValidationError(i18n.t("libreria.stock_campo", campo=k))
    qty = entry.get("cantidad")
    if isinstance(qty, bool) or not (qty is None or isinstance(qty, (int, float, str))):
        raise ValidationError(i18n.t("libreria.stock_cantidad", valor=repr(qty)))
    try:
        qty = _quantity(qty if isinstance(qty, str) or qty is None else repr(qty))
    except ValueError:
        raise ValidationError(i18n.t("libreria.stock_cantidad", valor=repr(entry.get("cantidad")))) from None
    out = {"cantidad": qty}
    for c in STOCK_TEXT:
        v = entry.get(c)
        if v is not None and not isinstance(v, str):
            raise ValidationError(i18n.t("libreria.stock_texto", campo=c))
        out[c] = (v or "").strip()
    return out


def has_stock(entry):
    """¿Hay stock? Con cantidad > 0, o con una entrada de cantidad desconocida (la tiene
    apuntada: puede que haya); sin entrada o con 0, no."""
    return entry is not None and (entry["cantidad"] is None or entry["cantidad"] > 0)


# --------------------------------------------------------------- la librería entera
class PackLibrary(Library):
    """Las fichas de un paquete (`<paquete>/library/`) con lo que declara su esquema
    (`schema`, de `library_schema.read`, que lee la carga de los paquetes)."""

    def __init__(self, root=None, schema=None):
        super().__init__(root)
        self.schema = dict(schema or {})


def pack_libraries(registry):
    """`[(id, PackLibrary)]` de las fichas de los paquetes cargados sin error
    (`<paquete>/library/`), con su esquema, en el orden del registro: una clave en dos
    paquetes, la del primero. Un paquete con esquema y sin fichas también está."""
    out = []
    for p in getattr(registry, "packs", None) or []:
        if p.error or not p.path:
            continue
        d = Path(p.path) / PACK_LIBRARY
        if d.is_dir():
            out.append((p.id, PackLibrary(d, getattr(p, "library_schema", None))))
    return out


class WorkspaceLibrary:
    """La librería del workspace `ws`, con las fichas de los paquetes `packs` (de
    `pack_libraries`) en solo lectura."""

    def __init__(self, ws, packs=()):
        self.ws = ws
        self.packs = list(packs)

    # --------------------------------------------------------------- lectura
    def _workspace(self):
        """{clave: (texto, dict | None, error | None)} de las fichas del workspace."""
        out = {}
        for key, text in self.ws.list_library_fichas().items():
            try:
                data = parse(text)
            except ValidationError as exc:
                out[key] = (text, None, str(exc))
                continue
            errs = meta_errors(data, key)
            out[key] = (text, data, "; ".join(errs) if errs else None)
        return out

    def _pack_fichas(self):
        """{clave: (id del paquete, Ficha)}."""
        out = {}
        for pid, lib in self.packs:
            for f in lib.records():
                out.setdefault(f.key, (pid, f))
        return out

    def _all(self):
        """{clave: resumen} de todo (workspace, paquetes y stock sin ficha), con su stock."""
        stock = self.ws.load_stock()
        packs = self._pack_fichas()
        out = {}
        for key, (_text, data, error) in self._workspace().items():
            out[key] = _summary(key, data or {}, ORIGIN_WORKSPACE, error=error)
            if key in packs:
                out[key]["overrides"] = packs[key][0]
        for key, (pid, f) in packs.items():
            out.setdefault(key, _summary(key, f.data, ORIGIN_PACK, pack=pid))
        for key in stock:
            out.setdefault(key, _summary(key, {}, ORIGIN_STOCK))
        for key, s in out.items():
            s["stock"] = stock.get(key)
        return out

    def list(self, type_=None):
        """Los resúmenes, por clave; con `type_`, solo los de ese tipo."""
        items = self._all()
        return [s for _, s in sorted(items.items(), key=lambda kv: kv[0].casefold())
                if type_ in (None, "") or s["type"] == type_]

    def _declared(self):
        """{tipo: [campo]} de lo que declaran los esquemas de los paquetes (PLAN_LIBRERIA L4),
        cada campo con su `paquete`. Un tipo en dos paquetes: los campos de los dos, en el
        orden de carga, y uno repetido, el del primero."""
        out = {}
        for pid, lib in self.packs:
            for type_, fields in (getattr(lib, "schema", None) or {}).items():
                got = out.setdefault(type_, [])
                seen = {f["nombre"] for f in got}
                got += [{**f, "paquete": pid} for f in fields if f["nombre"] not in seen]
        return out

    def types(self):
        """Los tipos que hay, ordenados: los de alguna ficha o stock y los que declara el
        esquema de un paquete, aunque aún no tengan fichas (L4)."""
        return sorted({s["type"] for s in self._all().values() if s["type"]} | set(self._declared()))

    def get(self, key):
        """Una ficha entera: su resumen, el texto (`toml`), lo leído (`data`, sin fechas de
        TOML) y su stock. `NotFound` si no está en el workspace ni en un paquete."""
        check_ficha_key(key)
        stock = self.ws.load_stock().get(key)
        ws = self._workspace().get(key)
        packs = self._pack_fichas()
        if ws is not None:
            text, data, error = ws
            out = _summary(key, data or {}, ORIGIN_WORKSPACE, error=error)
            out["overrides"] = packs[key][0] if key in packs else None
        elif key in packs:
            pid, f = packs[key]
            text, data = f.path.read_text(encoding="utf-8", errors="replace"), f.data
            out = _summary(key, data, ORIGIN_PACK, pack=pid)
        else:
            raise NotFound(i18n.t("libreria.no_existe", clave=key))
        return {**out, "toml": text, "data": jsonable(data) if data else None, "stock": stock}

    def ficha_data(self, key):
        """`(origen, id del paquete | None, dict | None)` de la ficha que manda para `key`, o
        None si no hay ninguna (para importar encima)."""
        ws = self._workspace().get(key)
        if ws is not None:
            return ORIGIN_WORKSPACE, None, ws[1]
        f = self._pack_fichas().get(key)
        return (ORIGIN_PACK, f[0], f[1].data) if f else None

    def fields(self, type_):
        """Los campos de `[values]` de `type_`, lo que se ofrece al mapear un Excel (V16, L4):
        `[{nombre, unidad, descripcion, obligatorio, min, max, declarado, paquete}]`. Primero
        los que declaran los esquemas de los paquetes, en su orden (`declarado` True); después,
        por nombre, los que usan las fichas del tipo (las de los paquetes y las del workspace) y
        nadie declara (`declarado` False, sin unidad ni paquete). El núcleo no sabe qué
        significan: lo dice el paquete."""
        out = [{**f, "declarado": True} for f in self._declared().get(type_, [])]
        names = set()
        for _, data, _ in self._workspace().values():
            if data and (data.get("meta") or {}).get("type") == type_:
                names |= set((data.get("values") or {}))
        for _, f in self._pack_fichas().values():
            if f.type == type_:
                names |= set((f.data.get("values") or {}))
        names -= {f["nombre"] for f in out}
        out += [{"nombre": n, "unidad": "", "descripcion": "", "obligatorio": False, "min": None,
                 "max": None, "declarado": False, "paquete": None}
                for n in sorted(names, key=str.casefold)]
        return out

    # ------------------------------------------------------------- escritura
    def save(self, key, text):
        """Guarda la ficha `key` (su TOML, tal cual) si su `[meta]` vale; devuelve su resumen.
        Una de un tipo que ningún paquete conoce también (V15)."""
        check_ficha_key(key)
        data = check(text, key)
        self.ws.save_library_ficha(key, data["meta"]["type"], text)
        return next(s for s in self.list() if s["key"] == key)

    def delete(self, key):
        """La ficha del workspace a la papelera; la de un paquete no se toca (`ValidationError`).
        Su stock se queda: es de la clave."""
        check_ficha_key(key)
        if self.ws.load_library_ficha(key) is None:
            f = self._pack_fichas().get(key)
            if f is not None:
                raise ValidationError(i18n.t("libreria.de_paquete", clave=key, paquete=f[0]))
            raise NotFound(i18n.t("libreria.no_existe", clave=key))
        self.ws.trash_library_ficha(key)

    def stock(self):
        return self.ws.load_stock()

    def update_stock(self, changes):
        """`{clave: entrada | None}`: None quita la clave del stock. Valida todo antes de
        guardar nada; devuelve el stock entero."""
        if not isinstance(changes, dict):
            raise ValidationError(i18n.t("libreria.stock_no_objeto"))
        clean = {check_ficha_key(k): (None if v is None else clean_stock_entry(v))
                 for k, v in changes.items()}
        stock = self.ws.load_stock()
        for k, v in clean.items():
            if v is None:
                stock.pop(k, None)
            else:
                stock[k] = v
        self.ws.save_stock(stock)
        return stock

    # -------------------------------------------------------------- búsqueda
    def search(self, type_=None, text="", con_stock=None, limit=SEARCH_MAX):
        """Lo que da `buscar_libreria` (V17): las fichas (no el stock sin ficha) de `type_`, que
        tienen `text` en la clave, el fabricante, el tipo, la clase o las notas, y con stock
        (`con_stock` True), sin él (False) o todas (None). Cada una con sus valores (y su
        unidad, `units`, la de los que la declara el esquema de un paquete) y cómo
        citarla (`cite_as`, kind «ficha», D19). `(resultados, total)`."""
        words = [w for w in str(text or "").casefold().split() if w]
        ws, packs = self._workspace(), self._pack_fichas()
        stock = self.ws.load_stock()
        found = []
        for key, s in sorted(self._all().items(), key=lambda kv: kv[0].casefold()):
            if s["origin"] == ORIGIN_STOCK or s["error"]:
                continue
            if type_ and s["type"] != type_:
                continue
            if con_stock is not None and has_stock(stock.get(key)) != bool(con_stock):
                continue
            data = ws[key][1] if key in ws else packs[key][1].data
            notes = (data.get("meta") or {}).get("notes") or []
            hay = " ".join([key, s["manufacturer"], s["type"], s["kind"],
                            *(n for n in (notes if isinstance(notes, list) else [notes])
                              if isinstance(n, str))]).casefold()
            if all(w in hay for w in words):
                found.append((s, data))
        units = {t: {f["nombre"]: f["unidad"] for f in fs if f["unidad"]}
                 for t, fs in self._declared().items()}
        out = []
        for s, data in found[:max(1, int(limit))]:
            values = data.get("values") if isinstance(data.get("values"), dict) else {}
            unit_of = units.get(s["type"], {})
            out.append({
                "key": s["key"], "type": s["type"], "kind": s["kind"],
                "manufacturer": s["manufacturer"], "status": s["status"],
                "origin": s["origin"], "pack": s["pack"], "overrides": s["overrides"],
                "stock": s["stock"],
                "values": {n: jsonable(e.get("v") if isinstance(e, dict) else e)
                           for n, e in values.items()},
                # la unidad de cada valor, la que declara el esquema del paquete (L3)
                "units": {n: unit_of[n] for n in values if n in unit_of},
                "cite_as": {"kind": "ficha", "ref": f"ficha:{s['key']}"}})
        return out, len(found)
