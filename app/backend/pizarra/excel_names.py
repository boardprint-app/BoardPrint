"""Los nombres definidos de un Excel como datos de la pizarra (docs/PLAN_EXCEL.md §3.1).

Python puro (openpyxl): ni la pizarra ni i18n. `names(path)` lee los nombres definidos del libro
y de cada hoja (Fórmulas → Administrador de nombres) y da, de cada uno, su hoja, su celda, su
valor, su unidad y si es una fórmula. Solo un nombre de **una celda** da valor (X3); lo demás
lleva en `problema` el código de por qué no se admite, que la pizarra traduce (`excel.<código>`):

    varias_celdas   el nombre es un rango de más de una celda
    constante       el nombre es un número o un texto (`=0,5`), no una celda
    no_es_celda     el nombre es una fórmula o algo que no es una referencia
    ref_rota        `#REF!` o una hoja que ya no está
    vacia           la celda está vacía
    error_celda     la celda guarda un error de Excel (`#DIV/0!`, `#N/A`…)
    sin_valor       una fórmula sin valor guardado, y el recálculo tampoco lo da (X5, X7)

La unidad sale del sufijo del nombre (X4): el último trozo tras `_`, contra `SUFFIXES`. Uno que
la tabla no conoce cuenta como sin sufijo. `convert` pasa un valor a la unidad del parámetro o
lanza `UnitError` con el código del motivo: nunca se adivina.
"""
import math
from dataclasses import asdict, dataclass
from pathlib import Path

EXTS = (".xlsx", ".xlsm")       # X9: openpyxl no abre .xls ni .ods

# Cada unidad: su magnitud y cuánto vale en la base de esa magnitud. Las bases y los factores
# son los de la interfaz (`frontend/src/units.ts`: mm, kg, N, N·m, °) y las magnitudes, las de
# `pizarra/units.py`; el tiempo, en s, solo lo usa el Excel. Los alias son como los escriben
# los bloques ("deg", "Nm").
UNITS = {
    "mm": ("longitud", 1), "cm": ("longitud", 10), "m": ("longitud", 1000),
    "in": ("longitud", 25.4), "ft": ("longitud", 304.8),
    "g": ("masa", 0.001), "kg": ("masa", 1), "lb": ("masa", 0.45359237),
    "N": ("fuerza", 1), "kN": ("fuerza", 1000), "lbf": ("fuerza", 4.4482216152605),
    "N·m": ("par", 1), "Nm": ("par", 1), "N*m": ("par", 1), "N·mm": ("par", 0.001),
    "Nmm": ("par", 0.001), "kN·m": ("par", 1000), "kNm": ("par", 1000),
    "lbf·in": ("par", 0.1129848290276167),
    "°": ("angulo", 1), "deg": ("angulo", 1), "rad": ("angulo", 180 / 3.141592653589793),
    "s": ("tiempo", 1), "ms": ("tiempo", 0.001),
}
# Lo que puede ir de sufijo en el nombre de una celda (X4): solo letras, como se escriben en
# un nombre de Excel. Distinguen mayúsculas: `L_MM` no es `mm`.
SUFFIXES = ("mm", "cm", "m", "in", "ft", "g", "kg", "lb", "N", "kN", "lbf",
            "Nm", "Nmm", "kNm", "deg", "rad", "s", "ms")
# Los errores que Excel guarda como valor de una celda
ERRORS = {"#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA",
          "#SPILL!", "#CALC!", "#FIELD!", "#BLOCKED!", "#CONNECT!", "#BUSY!", "#UNKNOWN!"}


def is_excel(path):
    """¿Es un archivo cuyos nombres se leen (`.xlsx`, `.xlsm`)?"""
    return Path(str(path)).suffix.lower() in EXTS


def suffix(name):
    """La unidad del nombre (`L_brazo_mm` → `mm`), o "" si no tiene o no se conoce. El de una
    hoja (`Hoja!L_m`), por su nombre."""
    bare = str(name).rpartition("!")[2]
    head, sep, last = bare.rpartition("_")
    return last if sep and head and last in SUFFIXES else ""


def sheet_ref(title):
    """La hoja como va en una referencia: entre comillas si lleva algo que no es una letra, una
    cifra o `_` (como `read_files`)."""
    return f"'{title}'" if any(not (c.isalnum() or c == "_") for c in title) else title


@dataclass(frozen=True)
class Nombre:
    """Un nombre definido. `valor` None siempre que hay `problema`."""
    nombre: str
    hoja: str | None = None
    celda: str | None = None
    valor: object = None
    unidad: str = ""
    formula: str | None = None
    problema: str | None = None

    @property
    def where(self):
        """`Hoja!B3`, la celda como la cita una fuente (D19); None si no es una celda."""
        return f"{sheet_ref(self.hoja)}!{self.celda}" if self.hoja and self.celda else None

    def view(self):
        """Para pasar a JSON (la interfaz): un valor que no es número, texto ni sí/no, en texto
        (una fecha)."""
        out = {**asdict(self), "where": self.where}
        v = out["valor"]
        if v is not None and not isinstance(v, (bool, int, float, str)):
            out["valor"] = str(v)
        return out


class UnitError(ValueError):
    """Un enlace que se niega por la unidad (X4). `code` es el motivo (`sin_sufijo`,
    `otra_magnitud`, `unidad_desconocida`, `con_sufijo_sin_unidad`, `no_es_numero`) y `vars`,
    lo que el texto necesita."""

    def __init__(self, code, **vars):
        super().__init__(code)
        self.code = code
        self.vars = vars


def check_unit(sfx, unit):
    """Lanza `UnitError` si un nombre con el sufijo `sfx` ("" sin él) no puede ir a un parámetro
    en `unit` ("" sin unidad)."""
    sfx, unit = sfx or "", unit or ""
    if not unit:
        if sfx:
            raise UnitError("con_sufijo_sin_unidad", sufijo=sfx)
        return
    if unit not in UNITS:
        raise UnitError("unidad_desconocida", unidad=unit)
    if not sfx:
        raise UnitError("sin_sufijo", unidad=unit)
    if UNITS[sfx][0] != UNITS[unit][0]:
        raise UnitError("otra_magnitud", sufijo=sfx, unidad=unit)


def compatible(sfx, unit):
    """¿Puede un nombre con el sufijo `sfx` ir a un parámetro en `unit`? (*Tomar de Excel*)."""
    try:
        check_unit(sfx, unit)
    except UnitError:
        return False
    return True


def convert(value, sfx, unit):
    """`value`, del nombre con el sufijo `sfx`, en la unidad `unit` del parámetro. Sin unidad
    en los dos lados, tal cual (también un texto). `UnitError` con el motivo si no se puede."""
    check_unit(sfx, unit)
    if not unit:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnitError("no_es_numero", valor=repr(value), unidad=unit)
    if sfx == unit or UNITS[sfx][1] == UNITS[unit][1]:
        return value
    return _clean(value * UNITS[sfx][1] / UNITS[unit][1])


def _clean(x):
    """Sin el ruido del último bit de la conversión (15 cifras significativas): 1,001 m daba
    1000,9999999999999 mm, y el bloque no daba lo mismo que con 1001 escrito a mano (§6)."""
    return float(f"{x:.15g}") if math.isfinite(x) else x


# ------------------------------------------------------------------------------- lectura

def _target(dn, sheets):
    """`(hoja, celda, problema)` de un nombre definido."""
    text = (dn.attr_text or "").strip()
    if "#REF!" in text.upper():
        return None, None, "ref_rota"
    if dn.type in ("NUMBER", "TEXT", "BOOL"):
        return None, None, "constante"
    if dn.type != "RANGE":
        return None, None, "ref_rota" if dn.type == "ERROR" else "no_es_celda"
    try:
        dests = list(dn.destinations)
    except Exception:                   # noqa: BLE001 lo que openpyxl no sabe partir
        return None, None, "no_es_celda"
    if len(dests) != 1:
        return None, None, "varias_celdas" if dests else "no_es_celda"
    sheet, ref = dests[0]
    if sheet not in sheets:
        return None, None, "ref_rota"
    from openpyxl.utils.cell import range_boundaries
    ref = ref.replace("$", "")
    try:
        c0, r0, c1, r1 = range_boundaries(ref)
    except (ValueError, TypeError):
        return None, None, "no_es_celda"
    if None in (c0, r0, c1, r1) or (c0, r0) != (c1, r1):
        return sheet, None, "varias_celdas"
    return sheet, ref, None


def _defined(wb):
    """`[(clave, nombre, DefinedName)]`: los del libro por su nombre y los de una hoja como
    `Hoja!nombre`. Sin los internos de Excel (`_xlnm.Print_Area`, `_xlfn.`…)."""
    out = [(n, n, dn) for n, dn in wb.defined_names.items()]
    for ws in wb.worksheets:
        for n, dn in (getattr(ws, "defined_names", None) or {}).items():
            out.append((f"{ws.title}!{n}", n, dn))
    return [(k, n, dn) for k, n, dn in out if not n.startswith("_xl")]


def _formula_text(v):
    v = getattr(v, "text", v)           # una fórmula de matriz (ArrayFormula)
    return v if isinstance(v, str) and v.startswith("=") else None


def _cells(ws, coords):
    """`{(fila, columna): valor}` de las celdas `coords` de una hoja leída en `read_only`: una
    sola pasada por las filas que hacen falta (pedir una celda suelta relee la hoja)."""
    rows = sorted({r for r, _ in coords})
    c0, c1 = min(c for _, c in coords), max(c for _, c in coords)
    out = {}
    for r, row in enumerate(ws.iter_rows(min_row=rows[0], max_row=rows[-1], min_col=c0,
                                         max_col=c1, values_only=True), start=rows[0]):
        for c, v in enumerate(row, start=c0):
            if (r, c) in coords:
                out[(r, c)] = v
    return out


def names(path, recalc=None):
    """`{clave: Nombre}` de los nombres definidos de una celda del Excel `path`, y los que no se
    admiten con su `problema`. Libro abierto dos veces, como `read_files._xlsx`: con `data_only`
    para los valores guardados y sin él para saber qué celdas son fórmulas.

    `recalc(path, celdas) -> {"Hoja!B3": valor}` (§3.4): se llama una vez, solo con las
    fórmulas sin valor guardado. Lo que no devuelva, o si falla, queda `sin_valor`. Un valor
    guardado nunca se sustituye. Lanza lo que lance openpyxl si el archivo no se puede leer."""
    import openpyxl

    values = openpyxl.load_workbook(path, read_only=True, data_only=True)
    formulas = openpyxl.load_workbook(path, read_only=True, data_only=False)
    try:
        from openpyxl.utils.cell import coordinate_to_tuple
        sheets = set(values.sheetnames)
        found, pending, targets = {}, {}, []
        defined = _defined(values)
        for key, name, dn in defined:
            sheet, cell, problem = _target(dn, sheets)
            base = dict(nombre=key, hoja=sheet, celda=cell, unidad=suffix(name))
            if problem:
                found[key] = Nombre(**base, problema=problem)
            else:
                targets.append((key, base, sheet, coordinate_to_tuple(cell)))
        wanted = {}
        for _, _, sheet, rc in targets:
            wanted.setdefault(sheet, set()).add(rc)
        got_v = {s: _cells(values[s], rcs) for s, rcs in wanted.items()}
        got_f = {s: _cells(formulas[s], rcs) for s, rcs in wanted.items()}
        for key, base, sheet, rc in targets:
            v = got_v[sheet].get(rc)
            f = _formula_text(got_f[sheet].get(rc))
            if f is not None and v == f:
                v = None                # el texto de la fórmula nunca es su valor (X5)
            if isinstance(v, str) and v.strip() in ERRORS:
                found[key] = Nombre(**base, formula=f, problema="error_celda")
            elif v is not None:
                found[key] = Nombre(**base, valor=v, formula=f)
            elif f is None:
                found[key] = Nombre(**base, problema="vacia")
            else:
                found[key] = Nombre(**base, formula=f, problema="sin_valor")
                pending[key] = found[key].where
    finally:
        values.close()
        formulas.close()
    if pending and recalc is not None:
        try:
            got = recalc(path, sorted(set(pending.values()))) or {}
        except Exception:               # noqa: BLE001 sin recálculo, sin valor (§3.4)
            got = {}
        for key, where in pending.items():
            v = got.get(where)
            if v is None or isinstance(v, str) and v.strip() in ERRORS:
                continue
            n = found[key]
            found[key] = Nombre(n.nombre, n.hoja, n.celda, v, n.unidad, n.formula, None)
    return {key: found[key] for key, _, _ in defined}       # en el orden del libro
