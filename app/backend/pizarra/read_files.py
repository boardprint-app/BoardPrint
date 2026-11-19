"""Lectura de archivos para el agente (`leer_archivo`, plan R36, D61): lógica pura, sin pizarra.

`read(path)` convierte un PDF, un Word, un Excel, un PowerPoint o un texto plano en trozos
(`Chunk`), cada uno con **dónde está** (D19: la cifra que el agente saque de ahí se cita con
ese sitio): `página 3` en un PDF; `párrafos 4-9` o `tabla 2` en un Word (un `.docx` no guarda
páginas: las calcula Word al pintarlo); `Hoja1!A1:F40` en un Excel, con la fila y la columna en
la propia tabla para que la celda se lea sin contar; `diapositiva 5` en un PowerPoint, con sus
tablas y sus notas; `líneas 1-200` en un texto.

Nunca devuelve texto vacío: un formato que no conoce (también el `.doc`, `.xls` y `.ppt`
antiguos), un archivo que no se puede abrir o uno sin texto (un PDF escaneado) dan `ReadError`
con el motivo. Sin OCR.

`read_part` da un tramo para una llamada de la herramienta: un catálogo largo no cabe entero
en una respuesta del agente, así que va por tramos (`next` para seguir, o `pages` para saltar a
unas páginas de un PDF). Un PDF se lee página a página, solo las que se devuelven, y se cierra
al terminar cada llamada (nunca queda abierto mientras el usuario lo edita): en un catálogo
maquetado cada página cuesta más de un segundo. Lo leído queda en caché por ruta, fecha y
tamaño, así que seguir no relee y un archivo cambiado se lee de nuevo.
"""
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import datetime
import json
import os
from pathlib import Path
import threading

TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
             ".log", ".xml"}
OLD_OFFICE = {".doc": ".docx", ".xls": ".xlsx", ".ppt": ".pptx"}
KNOWN = "PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx) y texto plano"

PARAGRAPH_CHARS = 3000      # un trozo de Word junta párrafos hasta este tamaño
TEXT_LINES = 100            # un trozo de texto plano
SHEET_CELLS = 1000          # un trozo de Excel: tantas filas como quepan en estas celdas
PAGE_CHARS = 20_000         # lo que da como mucho una llamada de `leer_archivo` (agent.TOOL_CHARS)


class ReadError(ValueError):
    """El archivo no se puede leer; el mensaje dice por qué."""


@dataclass(frozen=True)
class Chunk:
    """Un trozo: `where` (dónde está) y su `text` o su `table` (filas de textos)."""
    where: str
    text: str = ""
    table: tuple = ()

    def as_dict(self):
        out = {"where": self.where}
        if self.text:
            out["text"] = self.text
        if self.table:
            out["table"] = [list(r) for r in self.table]
        return out

    @property
    def empty(self):
        return not self.text.strip() and not any(c for r in self.table for c in r)


# --- PDF ----------------------------------------------------------------------------------

def _inside(obj, box):
    x0, top, x1, bottom = box
    return (obj["x0"] >= x0 - 1 and obj["x1"] <= x1 + 1
            and obj["top"] >= top - 1 and obj["bottom"] <= bottom + 1)


TABLE_CELL_CHARS = 400      # una «tabla» con una celda más larga es un recuadro de maquetación


def _real_table(rows):
    """¿Es una tabla de datos? Un catálogo maquetado con recuadros hace que el detector vea
    tablas que son párrafos enmarcados: al menos dos filas y dos columnas con algo, y ninguna
    celda como un párrafo. Si no lo es, su texto se queda en el de la página."""
    full_rows = [r for r in rows if sum(1 for c in r if c) >= 2]
    full_cols = {i for r in rows for i, c in enumerate(r) if c}
    return (len(full_rows) >= 2 and len(full_cols) >= 2
            and max((len(c) for r in rows for c in r), default=0) <= TABLE_CELL_CHARS)


def _pdf_page(page, i):
    tables = []
    for t in page.find_tables():
        rows = tuple(tuple(_cell(c) for c in row) for row in t.extract())
        if _real_table(rows):
            tables.append((t.bbox, rows))
    boxes = [b for b, _ in tables]
    # el texto de una tabla va en la tabla, no repetido en el de la página
    rest = page.filter(lambda o: not any(_inside(o, b) for b in boxes)) if boxes else page
    out = [Chunk(f"página {i}", (rest.extract_text() or "").strip())]
    out += [Chunk(f"página {i}, tabla {n}", table=rows) for n, (_, rows) in enumerate(tables, 1)]
    return out


@contextmanager
def _pdf(path):
    """Las páginas de un PDF, cada una leída solo cuando se pide: leer una cuesta de
    milisegundos en un datasheet a más de un segundo en un catálogo maquetado."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        yield len(pdf.pages), lambda i: _pdf_page(pdf.pages[i], i + 1)


# --- Word ---------------------------------------------------------------------------------

def _docx(path):
    import docx
    from docx.table import Table

    out, group, size, first, n_par, n_tab = [], [], 0, 0, 0, 0

    def flush():
        nonlocal group, size
        if group:
            where = f"párrafo {first}" if first == n_par else f"párrafos {first}-{n_par}"
            out.append(Chunk(where, "\n".join(group)))
        group, size = [], 0

    for item in docx.Document(path).iter_inner_content():
        if isinstance(item, Table):
            flush()
            n_tab += 1
            rows = tuple(tuple(_cell(c.text) for c in row.cells) for row in item.rows)
            out.append(Chunk(f"tabla {n_tab}", table=rows))
            continue
        text = item.text.strip()
        if not text:
            continue
        if size + len(text) > PARAGRAPH_CHARS:
            flush()
        n_par += 1
        if not group:
            first = n_par
        style = (item.style.name if item.style is not None else "") or ""
        if style.startswith("Heading") or style.startswith("Título") or style == "Title":
            text = "# " + text
        group.append(text)
        size += len(text)
    flush()
    return out


# --- Excel --------------------------------------------------------------------------------

def _col(n):
    """Letra de la columna `n` (1 → A, 27 → AA)."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_ref(title):
    return f"'{title}'" if any(not (c.isalnum() or c == "_") for c in title) else title


def _value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "VERDADERO" if v else "FALSO"
    if isinstance(v, float):
        return f"{v:.15g}"
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    return str(v).strip()


def _xlsx(path):
    import openpyxl

    values = openpyxl.load_workbook(path, read_only=True, data_only=True)
    formulas = openpyxl.load_workbook(path, read_only=True, data_only=False)
    out = []
    try:
        for ws in values.worksheets:
            # un archivo guardado por un programa que no es Excel no lleva el valor calculado
            # de sus fórmulas: entonces sale la fórmula, nunca una celda vacía que no lo está
            fws = formulas[ws.title]
            grid = []
            for vrow, frow in zip(ws.iter_rows(values_only=True), fws.iter_rows(values_only=True)):
                grid.append([_value(v) if v is not None else
                             (str(f) if isinstance(f, str) and f.startswith("=") else "")
                             for v, f in zip(vrow, frow)])
            cells = [(r, c) for r, row in enumerate(grid) for c, v in enumerate(row) if v]
            if not cells:
                continue
            r0, r1 = min(r for r, _ in cells), max(r for r, _ in cells)
            c0, c1 = min(c for _, c in cells), max(c for _, c in cells)
            cols = [_col(c + 1) for c in range(c0, c1 + 1)]
            step = max(1, SHEET_CELLS // len(cols))
            for a in range(r0, r1 + 1, step):
                b = min(a + step - 1, r1)
                rows = [("", *cols)]
                for r in range(a, b + 1):
                    row = grid[r] + [""] * (c1 + 1 - len(grid[r]))
                    rows.append((str(r + 1), *row[c0:c1 + 1]))
                where = f"{_sheet_ref(ws.title)}!{cols[0]}{a + 1}:{cols[-1]}{b + 1}"
                out.append(Chunk(where, table=tuple(rows)))
    finally:
        values.close()
        formulas.close()
    return out


# --- PowerPoint ---------------------------------------------------------------------------

def _shapes(shapes):
    """Las formas en orden de lectura (de arriba abajo y de izquierda a derecha), entrando en
    los grupos."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    flat = []
    for s in shapes:
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            flat.extend(_shapes(s.shapes))
        else:
            flat.append(s)
    return sorted(flat, key=lambda s: (s.top or 0, s.left or 0))


def _pptx(path):
    from pptx import Presentation

    out = []
    for i, slide in enumerate(Presentation(path).slides, 1):
        texts, tables = [], []
        for s in _shapes(slide.shapes):
            if getattr(s, "has_table", False) and s.has_table:
                tables.append(tuple(tuple(_cell(c.text) for c in row.cells)
                                    for row in s.table.rows))
            elif getattr(s, "has_text_frame", False) and s.has_text_frame and s.text_frame.text.strip():
                texts.append(s.text_frame.text.strip())
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                texts.append("Notas: " + notes.text.strip())
        out.append(Chunk(f"diapositiva {i}", "\n".join(texts)))
        for n, rows in enumerate(tables, 1):
            out.append(Chunk(f"diapositiva {i}, tabla {n}", table=rows))
    return out


# --- texto --------------------------------------------------------------------------------

def _text(path):
    raw = Path(path).read_bytes()
    if b"\x00" in raw[:8192]:
        raise ReadError(f"{Path(path).name} no es texto: tiene bytes binarios")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    lines = text.splitlines()
    return [Chunk(f"líneas {a + 1}-{min(a + TEXT_LINES, len(lines))}",
                  "\n".join(lines[a:a + TEXT_LINES]))
            for a in range(0, len(lines), TEXT_LINES)]


def _cell(v):
    return " ".join(str(v).split()) if v is not None else ""


READERS = {".pdf": _pdf, ".docx": _docx, ".docm": _docx, ".xlsx": _xlsx, ".xlsm": _xlsx,
           ".pptx": _pptx, ".pptm": _pptx, **{e: _text for e in TEXT_EXTS}}


def readable(path):
    """¿Sabe `read` leer este archivo (por su extensión)?"""
    return Path(str(path)).suffix.lower() in READERS


@contextmanager
def _whole(reader, path):
    """Un formato que se lee entero de una vez (Word, Excel, PowerPoint, texto): cada trozo es
    una unidad."""
    chunks = reader(path)
    yield len(chunks), lambda i: [chunks[i]]


# --- lectura por tramos, con caché --------------------------------------------------------

@dataclass
class _Doc:
    """Lo leído de un archivo: cuántas unidades tiene (páginas en un PDF, trozos en lo demás)
    y los trozos de las ya leídas, sin vacíos."""
    count: int
    units: dict = field(default_factory=dict)


_CACHE = OrderedDict()          # (ruta, fecha, tamaño) -> _Doc: seguir con `next` no relee
_CACHE_SIZE = 8
_LOCK = threading.Lock()


def _check(path):
    ext = path.suffix.lower()
    if ext in OLD_OFFICE:
        raise ReadError(f"{path.name} es del formato antiguo de Office ({ext}): solo se leen "
                        f"los nuevos; guárdalo como {OLD_OFFICE[ext]}")
    if ext not in READERS:
        raise ReadError(f"no se leen archivos {ext or 'sin extensión'} ({path.name}): solo "
                        f"{KNOWN}")
    return ext


def _pages(pages, count):
    """`"5"` o `"45-50"` (desde 1, ambos incluidos) → rango de unidades de un PDF."""
    try:
        a, _, b = str(pages).replace(" ", "").partition("-")
        lo, hi = int(a), int(b or a)
    except ValueError:
        raise ReadError(f"`pages` es una página o un rango, como '7' o '45-50', no {pages!r}") \
            from None
    if not 1 <= lo <= hi:
        raise ReadError(f"`pages` {pages!r} no es un rango de páginas")
    if lo > count:
        raise ReadError(f"el PDF tiene {count} página{'' if count == 1 else 's'}: no hay "
                        f"página {lo}")
    return lo - 1, min(hi, count)


def read_part(path, start=0, limit=PAGE_CHARS, pages=None):
    """`(trozos, siguiente, unidades)`: los trozos desde la unidad `start` que caben en
    `limit` caracteres, el índice de la unidad con la que seguir (o None si no queda) y cuántas
    unidades tiene el archivo (páginas en un PDF). En un PDF, `pages` limita el tramo (`"45-50"`)
    y solo se leen las páginas que se devuelven. Siempre da al menos una unidad, aunque pase
    de `limit`. `ReadError` si no se puede leer o el archivo no tiene texto."""
    path = Path(path)
    ext = _check(path)
    if pages is not None and ext != ".pdf":
        raise ReadError("`pages` solo vale en un PDF; lo demás se sigue con `from`")
    try:
        st = os.stat(path)
    except OSError:
        raise ReadError(f"no se encuentra {path}") from None
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    with _LOCK:
        doc = _CACHE.get(key)
        if doc is not None:
            _CACHE.move_to_end(key)
    out, size, opened = [], 0, None
    try:
        with ExitStack() as stack:
            def units():
                nonlocal opened
                if opened is None:
                    opened = stack.enter_context(_pdf(path) if ext == ".pdf"
                                                 else _whole(READERS[ext], path))
                return opened

            if doc is None:
                count, get = units()
                doc = _Doc(count)
                if ext != ".pdf":       # ya está todo leído: se guarda entero
                    doc.units = {i: [c for c in get(i) if not c.empty] for i in range(count)}
                with _LOCK:
                    _CACHE[key] = doc
                    while len(_CACHE) > _CACHE_SIZE:
                        _CACHE.popitem(last=False)
            lo, hi = _pages(pages, doc.count) if pages is not None else (0, doc.count)
            i = max(lo, int(start or 0))
            while i < hi:
                if i not in doc.units:
                    doc.units[i] = [c for c in units()[1](i) if not c.empty]
                chunks = doc.units[i]
                n = sum(len(json.dumps(c.as_dict(), ensure_ascii=False)) for c in chunks)
                if out and size + n > limit:
                    break
                out += chunks
                size += n
                i += 1
    except ReadError:
        raise
    except Exception as exc:  # un archivo roto, cifrado o que no es lo que dice su extensión
        raise ReadError(f"no se pudo leer {path.name}: {type(exc).__name__}: {exc}") from None
    if not out and len(doc.units) == doc.count and not any(doc.units.values()):
        hint = " (¿un PDF escaneado? no se lee texto de imágenes)" if ext == ".pdf" else ""
        raise ReadError(f"{path.name} no tiene texto que leer{hint}")
    return out, (i if i < hi else None), doc.count


def read(path):
    """Todos los trozos de un archivo, sin ninguno vacío. `ReadError` si no se puede."""
    return read_part(path, limit=float("inf"))[0]
