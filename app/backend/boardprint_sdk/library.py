"""La librería de componentes del workspace, vista desde un paquete (docs/PLAN_V020.md V14, V15;
SDK 1.5).

`<workspace>/library/` tiene una ficha TOML por componente, en el formato de las fichas de los
paquetes (`[meta]` con `key`, `type` y `status`; `[source]` o `[[sources]]`; `[values]`), en
`library/<tipo>s/<key>.toml`, y el stock en `library/stock.csv`
(`key,cantidad,ubicacion,fecha,nota`). Una cantidad vacía es **desconocida** (`None`), nunca 0
(D33): «no sé cuántas tengo» no es «no tengo».

Un paquete la lee con `ctx.library` en un bloque o una acción. Lo que no recibe `ctx` (una vista
previa, o el código de un paquete que la llama) la tiene en `current()` mientras dura la
llamada: el núcleo la pone con `using(...)`. Sin workspace (los tests de un paquete) la librería
está vacía, nunca da error; una ficha que no se puede leer no sale.

Solo stdlib: viaja al entorno de paquetes tal cual.
"""
import contextlib
import contextvars
import csv
import io
import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Ficha", "Library", "current", "using"]

STOCK_FILE = "stock.csv"
STOCK_COLUMNS = ("key", "cantidad", "ubicacion", "fecha", "nota")


@dataclass(frozen=True)
class Ficha:
    """Una ficha de la librería: lo de `[meta]` que hace falta para buscarla y el TOML entero
    (`data`), tal cual. `path`, el fichero (un STEP de la ficha va a su lado)."""
    key: str
    type: str
    status: str
    path: Path
    data: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def verified(self):
        return self.status == "verified"


def _quantity(text):
    """La cantidad de una celda del stock: vacía → None (desconocida, D33); un número ≥ 0 (con
    coma o punto decimal) → int si es entero, si no float. Otra cosa es `ValueError`."""
    s = str(text if text is not None else "").strip()
    if not s:
        return None
    try:
        x = float(s.replace(",", "."))
    except ValueError:
        raise ValueError(f"cantidad no válida: {s!r}") from None
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"cantidad no válida: {s!r}")
    return int(x) if x == int(x) else x


def _read_stock(text):
    """{key: {cantidad, ubicacion, fecha, nota}} de un `stock.csv`. Una fila sin `key` se salta;
    una cantidad que no se lee queda desconocida (None): leer nunca falla."""
    out = {}
    rows = csv.DictReader(io.StringIO(text or ""))
    for row in rows:
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        try:
            qty = _quantity(row.get("cantidad"))
        except ValueError:
            qty = None
        out[key] = {"cantidad": qty, **{c: str(row.get(c) or "").strip()
                                        for c in STOCK_COLUMNS[2:]}}
    return out


def _parse(path):
    """La `Ficha` de un fichero, o None si no se lee o no tiene `[meta]` con `type`."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    meta = data.get("meta")
    if not isinstance(meta, dict) or not isinstance(meta.get("type"), str):
        return None
    key = meta.get("key") if isinstance(meta.get("key"), str) and meta.get("key") else Path(path).stem
    return Ficha(key, meta["type"], str(meta.get("status") or "unverified"), Path(path), data)


class Library:
    """La librería de una carpeta (`<workspace>/library/`); sin carpeta, vacía."""

    def __init__(self, root=None):
        self.root = Path(root) if root else None

    def _files(self, pattern="*.toml"):
        if self.root is None or not self.root.is_dir():
            return []
        return sorted(p for p in self.root.glob(f"*/{pattern}")
                      if not p.parent.name.startswith("."))

    def records(self, type=None):        # noqa: A002 `type` es el nombre del campo de [meta]
        """Las fichas (todas o las de un `type`), por clave. Una clave repetida: la primera
        por ruta."""
        seen = {}
        for p in self._files():
            f = _parse(p)
            if f is not None and f.key not in seen:
                seen[f.key] = f
        return [f for _, f in sorted(seen.items()) if type is None or f.type == type]

    def load(self, key):
        """La ficha `key`, o None."""
        if not isinstance(key, str) or not key:
            return None
        for p in self._files(f"{key}.toml") if "/" not in key and "\\" not in key else []:
            f = _parse(p)
            if f is not None and f.key == key:
                return f
        return next((f for f in self.records() if f.key == key), None)

    def stock(self, key):
        """`{cantidad, ubicacion, fecha, nota}` de `key` en el stock (`cantidad` None si no se
        sabe), o None si el stock no la tiene."""
        if self.root is None:
            return None
        try:
            text = (self.root / STOCK_FILE).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return None
        got = _read_stock(text).get(key)
        return dict(got) if got is not None else None


_current = contextvars.ContextVar("boardprint_library", default=None)


def current():
    """La librería de la ejecución, la acción o la vista previa en curso; vacía fuera de ellas."""
    return _current.get() or Library()


@contextlib.contextmanager
def using(library):
    """Pone `library` como la de `current()` mientras dura el bloque (lo hace el núcleo)."""
    token = _current.set(library if isinstance(library, Library) else Library(library))
    try:
        yield _current.get()
    finally:
        _current.reset(token)
