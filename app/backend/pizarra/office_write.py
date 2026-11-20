"""Escribir Word, Excel y PowerPoint para el agente (plan D61, D176): lógica pura, sin pizarra.

`create(tipo, contenido, carpeta, nombre)` escribe un archivo nuevo a partir de un contenido
estructurado y simple (Word: títulos, párrafos y tablas; Excel: hojas con filas; PowerPoint:
diapositivas con título, viñetas y una tabla opcional). **Nunca pisa**: si el nombre ya está,
el primer `_n` libre (como `files.first_free`), y el archivo se crea en exclusiva.

`edit_copy(origen, cambios)` aplica unos cambios a una **copia** (`<nombre>_n.<ext>`, el primer
libre junto al original) y devuelve el diff legible (`[{where, before, after}]`). El original
solo se abre para leer: la biblioteca lo carga en memoria y lo cambiado se guarda en la copia.
Si un cambio no vale, no queda nada escrito.

Dónde está cada cambio (`where`), con la misma numeración que `leer_archivo` (`read_files`):
`párrafo n` (los párrafos con texto del cuerpo, en orden) y `tabla n, fila r, columna c` en un
Word; `Hoja!B4` en un Excel; `diapositiva n, forma k` (las formas con texto, de arriba abajo y
de izquierda a derecha) en un PowerPoint. Todo desde 1.

Límite conocido: openpyxl no conserva todo lo de un Excel (imágenes, gráficos que no entiende):
la copia puede perderlo; el original sigue intacto.
"""
import io
from pathlib import Path
import re

from pizarra import read_files

TYPES = {"docx": "Word", "xlsx": "Excel", "pptx": "PowerPoint"}
NAME_MAX = 120
ITEMS_MAX = 5000            # bloques de un Word, filas de una hoja, diapositivas…
TEXT_MAX = 32_767           # lo que cabe en una celda de Excel; vale para cualquier texto
CHANGES_MAX = 500
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class OfficeError(ValueError):
    """El contenido, los cambios o el archivo no valen; el mensaje dice por qué."""


# --- nombres ------------------------------------------------------------------------------

def check_type(tipo):
    if tipo not in TYPES:
        raise OfficeError(f"`tipo` es docx (Word), xlsx (Excel) o pptx (PowerPoint), no {tipo!r}")
    return tipo


def check_name(nombre, tipo):
    """El nombre del archivo, con su extensión: sin carpetas ni caracteres que Windows no
    admite. Con otra extensión, se le pone la del tipo detrás."""
    check_type(tipo)
    if not isinstance(nombre, str) or not nombre.strip():
        raise OfficeError("el archivo necesita `nombre`")
    name = nombre.strip().rstrip(". ")
    if _BAD_NAME.search(name) or name in (".", "..") or not name:
        raise OfficeError(f"{nombre!r} no vale como nombre de archivo: sin carpetas ni "
                          '< > : " / \\ | ? *')
    if Path(name).suffix.lower() != f".{tipo}":
        name = f"{name}.{tipo}"
    if len(name) > NAME_MAX:
        raise OfficeError(f"el nombre pasa de {NAME_MAX} caracteres")
    return name


def _create_exclusive(folder, name, write, numbered=False):
    """Escribe en `folder/name` o, si ya está, en el primer `<nombre>_<n><ext>` libre (como
    `files.first_free`); con `numbered`, siempre con `_n` (una copia nunca se llama como su
    original). Lo crea en exclusiva: si otro lo crea a la vez, prueba el siguiente.
    `write(fileobj)`. Devuelve la ruta. Un fallo no deja nada."""
    folder = Path(folder)
    stem, suffix = Path(name).stem, Path(name).suffix
    names = ([name] if not numbered else []) + [f"{stem}_{n}{suffix}" for n in range(1, 10_000)]
    for candidate in names:
        path = folder / candidate
        if path.exists():
            continue
        try:
            f = open(path, "xb")
        except FileExistsError:
            continue
        try:
            with f:
                write(f)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path
    raise OfficeError(f"no encuentro un nombre libre para {name} en {folder}")


# --- contenido de un archivo nuevo --------------------------------------------------------

def _text(v, what):
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise OfficeError(f"{what} tiene que ser un texto")
    s = str(v)
    if len(s) > TEXT_MAX:
        raise OfficeError(f"{what} pasa de {TEXT_MAX} caracteres")
    return s


def _rows(rows, what, cell=None):
    cell = cell or (lambda v, w: _text("" if v is None else v, w))
    if not isinstance(rows, list) or not rows or len(rows) > ITEMS_MAX:
        raise OfficeError(f"{what} es una lista de filas (de 1 a {ITEMS_MAX})")
    out = []
    for r, row in enumerate(rows, 1):
        if not isinstance(row, list):
            raise OfficeError(f"{what}, fila {r}: cada fila es una lista de celdas")
        out.append([cell(v, f"{what}, fila {r}") for v in row])
    if not any(out):
        raise OfficeError(f"{what} no tiene ninguna celda")
    return out


def _xl_value(v, what):
    if v is None or isinstance(v, (bool, int, float)):
        return v
    return _text(v, what)


def check_content(tipo, contenido):
    """El contenido normalizado, o OfficeError con lo que falla.

    - docx: `{"bloques": [{"titulo": t, "nivel"?: 1-3} | {"parrafo": t} | {"tabla": filas}]}`
    - xlsx: `{"hojas": [{"nombre": n, "filas": [[valor, …], …]}]}` (números, textos, sí/no; un
      texto que empieza por `=` es una fórmula)
    - pptx: `{"diapositivas": [{"titulo": t, "vinetas"?: [t, …], "tabla"?: filas}]}`
    """
    check_type(tipo)
    if not isinstance(contenido, dict):
        raise OfficeError("`contenido` es un objeto: " + CONTENT_HELP[tipo])
    if tipo == "docx":
        items = contenido.get("bloques")
        if not isinstance(items, list) or not items or len(items) > ITEMS_MAX:
            raise OfficeError("un Word lleva `bloques`: " + CONTENT_HELP[tipo])
        out = []
        for i, b in enumerate(items, 1):
            keys = set(b) & {"titulo", "parrafo", "tabla"} if isinstance(b, dict) else set()
            if len(keys) != 1:
                raise OfficeError(f"bloque {i}: lleva uno de titulo, parrafo o tabla")
            k = keys.pop()
            if k == "tabla":
                out.append({"tabla": _rows(b["tabla"], f"bloque {i}")})
            elif k == "titulo":
                nivel = b.get("nivel", 1)
                if nivel not in (1, 2, 3):
                    raise OfficeError(f"bloque {i}: `nivel` es 1, 2 o 3")
                out.append({"titulo": _text(b["titulo"], f"bloque {i}"), "nivel": nivel})
            else:
                out.append({"parrafo": _text(b["parrafo"], f"bloque {i}")})
        return {"bloques": out}
    if tipo == "xlsx":
        sheets = contenido.get("hojas")
        if not isinstance(sheets, list) or not sheets or len(sheets) > 100:
            raise OfficeError("un Excel lleva `hojas`: " + CONTENT_HELP[tipo])
        out, names = [], set()
        for i, h in enumerate(sheets, 1):
            if not isinstance(h, dict):
                raise OfficeError(f"hoja {i}: es un objeto {{nombre, filas}}")
            name = str(h.get("nombre") or f"Hoja{i}").strip()
            if re.search(r"[\[\]:*?/\\]", name) or len(name) > 31 or name.casefold() in names:
                raise OfficeError(f"hoja {i}: {name!r} no vale como nombre de hoja (hasta 31 "
                                  "caracteres, sin [ ] : * ? / \\, y sin repetir)")
            names.add(name.casefold())
            out.append({"nombre": name, "filas": _rows(h.get("filas"), f"hoja {name}",
                                                       _xl_value)})
        return {"hojas": out}
    slides = contenido.get("diapositivas")
    if not isinstance(slides, list) or not slides or len(slides) > ITEMS_MAX:
        raise OfficeError("un PowerPoint lleva `diapositivas`: " + CONTENT_HELP[tipo])
    out = []
    for i, d in enumerate(slides, 1):
        if not isinstance(d, dict):
            raise OfficeError(f"diapositiva {i}: es un objeto {{titulo, vinetas?, tabla?}}")
        s = {"titulo": _text(d.get("titulo") or "", f"diapositiva {i}")}
        vin = d.get("vinetas") or []
        if not isinstance(vin, list):
            raise OfficeError(f"diapositiva {i}: `vinetas` es una lista de textos")
        s["vinetas"] = [_text(v, f"diapositiva {i}") for v in vin]
        if d.get("tabla") is not None:
            s["tabla"] = _rows(d["tabla"], f"diapositiva {i}")
        if not s["titulo"] and not s["vinetas"] and "tabla" not in s:
            raise OfficeError(f"diapositiva {i}: está vacía")
        out.append(s)
    return {"diapositivas": out}


CONTENT_HELP = {
    "docx": '{"bloques": [{"titulo": "…", "nivel": 1}, {"parrafo": "…"}, '
            '{"tabla": [["…", "…"], ["…", "…"]]}]}',
    "xlsx": '{"hojas": [{"nombre": "Lista", "filas": [["Ref", "Cantidad"], ["M6", 4]]}]}',
    "pptx": '{"diapositivas": [{"titulo": "…", "vinetas": ["…"], "tabla": [["…"]]}]}',
}


def texts(tipo, contenido):
    """Todos los textos de un contenido ya normalizado (para la regla de los números, D19)."""
    out = []
    if tipo == "docx":
        for b in contenido["bloques"]:
            out += [c for row in b["tabla"] for c in row] if "tabla" in b \
                else [b.get("titulo") or b.get("parrafo") or ""]
    elif tipo == "xlsx":
        out += [str(v) for h in contenido["hojas"] for row in h["filas"] for v in row
                if v is not None and not isinstance(v, bool)]
    else:
        for d in contenido["diapositivas"]:
            out += [d["titulo"], *d["vinetas"], *(c for row in d.get("tabla") or () for c in row)]
    return [t for t in out if t]


def _write_docx(content, f):
    import docx
    d = docx.Document()
    for b in content["bloques"]:
        if "titulo" in b:
            d.add_heading(b["titulo"], level=b["nivel"])
        elif "parrafo" in b:
            d.add_paragraph(b["parrafo"])
        else:
            rows = b["tabla"]
            t = d.add_table(rows=len(rows), cols=max(len(r) for r in rows))
            t.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, v in enumerate(row):
                    t.cell(r, c).text = v
                    if r == 0:
                        for run in t.cell(r, c).paragraphs[0].runs:
                            run.bold = True
    d.save(f)


def _write_xlsx(content, f):
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for h in content["hojas"]:
        ws = wb.create_sheet(h["nombre"])
        for row in h["filas"]:
            ws.append(row)
        for cell in ws[1]:
            cell.font = Font(bold=True)
    wb.save(f)


def _write_pptx(content, f):
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    for d in content["diapositivas"]:
        layout = prs.slide_layouts[1 if d["vinetas"] else 5]      # título y contenido / solo título
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = d["titulo"]
        top = slide.shapes.title.top + slide.shapes.title.height
        if d["vinetas"]:
            body = slide.placeholders[1]
            body.text_frame.text = d["vinetas"][0]
            for v in d["vinetas"][1:]:
                body.text_frame.add_paragraph().text = v
            if "tabla" in d:              # la tabla, debajo de las viñetas
                body.height = Emu(int(body.height * 0.45))
                top = body.top + body.height
        if "tabla" in d:
            rows = d["tabla"]
            left, width = slide.shapes.title.left, slide.shapes.title.width
            height = Emu(min(prs.slide_height - top - Emu(300000), 370840 * len(rows)))
            t = slide.shapes.add_table(len(rows), max(len(r) for r in rows), left, top,
                                       width, height).table
            for r, row in enumerate(rows):
                for c, v in enumerate(row):
                    t.cell(r, c).text = v
    prs.save(f)


WRITERS = {"docx": _write_docx, "xlsx": _write_xlsx, "pptx": _write_pptx}


def create(tipo, contenido, folder, nombre):
    """Escribe el archivo nuevo en `folder` (que tiene que existir) y devuelve su ruta: con el
    nombre pedido o, si ya está, el primer `_n` libre. Nunca pisa un archivo."""
    content = check_content(tipo, contenido)
    name = check_name(nombre, tipo)
    folder = Path(folder)
    if not folder.is_dir():
        raise OfficeError(f"la carpeta {folder} no existe")
    buf = io.BytesIO()
    WRITERS[tipo](content, buf)       # primero en memoria: un fallo no deja un archivo a medias
    return _create_exclusive(folder, name, lambda f: f.write(buf.getvalue()))


# --- editar una copia ---------------------------------------------------------------------

def kind_of(path):
    """`docx`, `xlsx`, `xlsm` o `pptx` por la extensión, u OfficeError: el resto no se edita.
    Un `.xlsm` se edita como un `.xlsx` y conserva sus macros (`keep_vba`, PLAN_EXCEL X9)."""
    ext = Path(path).suffix.lower()[1:]
    if ext not in TYPES and ext != "xlsm":
        raise OfficeError(f"solo se editan Word (.docx), Excel (.xlsx) y PowerPoint (.pptx), "
                          f"no {Path(path).name}")
    return ext


def _index(v, what):
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise OfficeError(f"`{what}` es un número desde 1")
    return v


def _set_paragraph(p, text):
    """El texto de un párrafo de Word, conservando el formato de su primer trozo."""
    for h in list(getattr(p, "hyperlinks", ())):
        h._hyperlink.getparent().remove(h._hyperlink)
    runs = p.runs
    if runs:
        runs[0].text = text
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
    else:
        p.add_run().text = text


def _replace_in(paragraphs, old, new):
    """Cambia `old` por `new` en el párrafo que lo tiene; dentro de un trozo si cabe (el formato
    sigue igual), y si no, el párrafo entero con el formato de su primer trozo."""
    for p in paragraphs:
        if old not in p.text:
            continue
        for r in p.runs:
            if old in r.text:
                r.text = r.text.replace(old, new, 1)
                return
        _set_paragraph(p, p.text.replace(old, new, 1))
        return


def _cell_set(cell, text):
    ps = cell.paragraphs
    _set_paragraph(ps[0], text)
    for p in ps[1:]:
        p._p.getparent().remove(p._p)


def _edit_docx(src, changes):
    import docx
    from docx.table import Table
    d = docx.Document(src)
    pars, tables = [], []
    for item in d.iter_inner_content():
        if isinstance(item, Table):
            tables.append(item)
        elif item.text.strip():
            pars.append(item)

    def cells():
        for n, t in enumerate(tables, 1):
            seen = set()
            for r, row in enumerate(t.rows, 1):
                for c, cell in enumerate(row.cells, 1):
                    if id(cell._tc) in seen:       # una celda combinada sale repetida
                        continue
                    seen.add(id(cell._tc))
                    yield f"tabla {n}, fila {r}, columna {c}", cell

    diff = []
    for i, ch in enumerate(changes, 1):
        new = _text(ch.get("texto"), f"cambio {i}: `texto`")
        if "antes" in ch:
            old = _text(ch["antes"], f"cambio {i}: `antes`")
            if not old:
                raise OfficeError(f"cambio {i}: `antes` está vacío")
            spots = [(f"párrafo {n}", [p], p.text) for n, p in enumerate(pars, 1)] + \
                    [(w, c.paragraphs, c.text) for w, c in cells()]
            hits = [(w, ps, t) for w, ps, t in spots if old in t]
            count = sum(t.count(old) for _, _, t in hits)
            if count != 1:
                raise OfficeError(f"cambio {i}: {old!r} " + (
                    "no está en el documento" if not count else
                    f"sale {count} veces: da más texto alrededor o el índice"))
            where, ps, before = hits[0]
            _replace_in(ps, old, new)
            after = "\n".join(p.text for p in ps)
        elif "parrafo" in ch:
            n = _index(ch["parrafo"], "parrafo")
            if n > len(pars):
                raise OfficeError(f"cambio {i}: el documento tiene {len(pars)} párrafos con "
                                  f"texto, no hay párrafo {n}")
            where, before = f"párrafo {n}", pars[n - 1].text
            _set_paragraph(pars[n - 1], new)
            after = pars[n - 1].text
        elif "tabla" in ch:
            n = _index(ch["tabla"], "tabla")
            r, c = _index(ch.get("fila"), "fila"), _index(ch.get("columna"), "columna")
            if n > len(tables):
                raise OfficeError(f"cambio {i}: el documento tiene {len(tables)} tablas")
            rows = tables[n - 1].rows
            if r > len(rows) or c > len(rows[r - 1].cells):
                raise OfficeError(f"cambio {i}: la tabla {n} no tiene fila {r}, columna {c}")
            cell = rows[r - 1].cells[c - 1]
            where, before = f"tabla {n}, fila {r}, columna {c}", cell.text
            _cell_set(cell, new)
            after = cell.text
        else:
            raise OfficeError(f"cambio {i}: en un Word, `parrafo`, `tabla` (con fila y "
                              "columna) o `antes`, y `texto`")
        diff.append({"where": where, "before": before, "after": after})
    return d, diff


_REF = re.compile(r"^(?:(?:'((?:[^']|'')+)'|([^!']+))!)?\$?([A-Za-z]{1,3})\$?(\d{1,7})$")


def _edit_xlsx(src, changes):
    import openpyxl
    # con las fórmulas: la copia las conserva; un .xlsm, también sus macros
    wb = openpyxl.load_workbook(src, keep_vba=Path(src).suffix.lower() == ".xlsm")
    diff = []
    for i, ch in enumerate(changes, 1):
        ref = ch.get("celda")
        m = _REF.match(str(ref or "").strip())
        if not m or "valor" not in ch:
            raise OfficeError(f"cambio {i}: en un Excel, `celda` (como 'Hoja1!B4') y `valor`")
        sheet = (m.group(1) or "").replace("''", "'") or m.group(2)
        if sheet is None:
            if len(wb.worksheets) > 1:
                raise OfficeError(f"cambio {i}: el libro tiene varias hojas: di cuál "
                                  "('Hoja1!B4')")
            ws = wb.worksheets[0]
        elif sheet.strip() in wb.sheetnames:
            ws = wb[sheet.strip()]
        else:
            raise OfficeError(f"cambio {i}: no hay ninguna hoja {sheet!r}; hay "
                              f"{', '.join(wb.sheetnames)}")
        coord = f"{m.group(3).upper()}{m.group(4)}"
        cell = ws[coord]
        if type(cell).__name__ == "MergedCell":
            raise OfficeError(f"cambio {i}: {coord} es parte de una celda combinada: escribe "
                              "en la de arriba a la izquierda")
        value = _xl_value(ch["valor"], f"cambio {i}: `valor`")
        before = read_files._value(cell.value)
        cell.value = value
        diff.append({"where": f"{read_files._sheet_ref(ws.title)}!{coord}", "before": before,
                     "after": read_files._value(value)})
    return wb, diff


def _set_shape_text(shape, text):
    """El texto de una forma de PowerPoint: una línea por párrafo, con el formato del primero."""
    import copy
    tf = shape.text_frame
    lines = text.split("\n")
    paras = tf.paragraphs
    first = paras[0]
    for p in paras[1:]:
        p._p.getparent().remove(p._p)
    runs = first.runs
    if runs:
        runs[0].text = lines[0]
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
    else:
        first.add_run().text = lines[0]
    prev = first._p
    for line in lines[1:]:
        p = copy.deepcopy(first._p)
        prev.addnext(p)
        prev = p
    for p, line in zip(tf.paragraphs[1:], lines[1:]):
        p.runs[0].text = line


def _edit_pptx(src, changes):
    from pptx import Presentation
    prs = Presentation(src)
    slides = list(prs.slides)

    def shapes(n):
        return [s for s in read_files._shapes(slides[n - 1].shapes)
                if getattr(s, "has_text_frame", False) and s.has_text_frame
                and s.text_frame.text.strip()]

    diff = []
    for i, ch in enumerate(changes, 1):
        new = _text(ch.get("texto"), f"cambio {i}: `texto`")
        n = ch.get("diapositiva")
        if n is not None:
            n = _index(n, "diapositiva")
            if n > len(slides):
                raise OfficeError(f"cambio {i}: la presentación tiene {len(slides)} diapositivas")
        if "antes" in ch:
            old = _text(ch["antes"], f"cambio {i}: `antes`")
            if not old:
                raise OfficeError(f"cambio {i}: `antes` está vacío")
            spots = [(f"diapositiva {k}, forma {j}", s) for k in ([n] if n else
                     range(1, len(slides) + 1)) for j, s in enumerate(shapes(k), 1)]
            hits = [(w, s) for w, s in spots if old in s.text_frame.text]
            count = sum(s.text_frame.text.count(old) for _, s in hits)
            if count != 1:
                raise OfficeError(f"cambio {i}: {old!r} " + (
                    "no está en la presentación" if not count else
                    f"sale {count} veces: da más texto alrededor o la forma"))
            where, s = hits[0]
            before = s.text_frame.text
            _replace_in(s.text_frame.paragraphs, old, new)
            if old != new and s.text_frame.text == before:
                raise OfficeError(f"cambio {i}: {old!r} cruza de un párrafo a otro: cámbialo "
                                  "por partes o la forma entera")
        elif n and "forma" in ch:
            k = _index(ch["forma"], "forma")
            found = shapes(n)
            if k > len(found):
                raise OfficeError(f"cambio {i}: la diapositiva {n} tiene {len(found)} formas "
                                  "con texto")
            s, where = found[k - 1], f"diapositiva {n}, forma {k}"
            before = s.text_frame.text
            _set_shape_text(s, new)
        else:
            raise OfficeError(f"cambio {i}: en un PowerPoint, `diapositiva` y `forma`, o "
                              "`antes` (con `diapositiva` si quieres), y `texto`")
        diff.append({"where": where, "before": before, "after": s.text_frame.text})
    return prs, diff


EDITORS = {"docx": _edit_docx, "xlsx": _edit_xlsx, "xlsm": _edit_xlsx, "pptx": _edit_pptx}


def _merge(diff):
    """Dos cambios en el mismo sitio salen como uno: lo de antes del primero, lo del último."""
    out = {}
    for d in diff:
        if d["where"] in out:
            out[d["where"]]["after"] = d["after"]
        else:
            out[d["where"]] = dict(d)
    return [d for d in out.values() if d["before"] != d["after"]]


def edit_copy(src, changes):
    """Aplica `changes` a una copia de `src` y devuelve `(ruta de la copia, diff)`. La copia
    es el primer `<nombre>_n.<ext>` libre junto al original; el original nunca se escribe. Si
    un cambio no vale o no cambia nada, OfficeError y no queda ninguna copia."""
    src = Path(src)
    tipo = kind_of(src)
    if not isinstance(changes, list) or not changes or len(changes) > CHANGES_MAX:
        raise OfficeError(f"`cambios` es una lista de 1 a {CHANGES_MAX} cambios")
    if not all(isinstance(c, dict) for c in changes):
        raise OfficeError("cada cambio es un objeto")
    if not src.is_file():
        raise OfficeError(f"{src.name}: no encontrado en {src.parent}")
    try:
        doc, diff = EDITORS[tipo](src, changes)
    except OfficeError:
        raise
    except Exception as exc:          # un archivo roto o que la biblioteca no entiende
        raise OfficeError(f"no se puede abrir {src.name}: {exc}") from None
    diff = _merge(diff)
    if not diff:
        raise OfficeError("los cambios dejan el archivo igual: no hay nada que proponer")
    buf = io.BytesIO()
    try:
        doc.save(buf)
    finally:
        vba = getattr(doc, "vba_archive", None)     # un .xlsm abierto con keep_vba
        if vba is not None:
            vba.close()
    dest = _create_exclusive(src.parent, src.name, lambda f: f.write(buf.getvalue()), True)
    return dest, diff
