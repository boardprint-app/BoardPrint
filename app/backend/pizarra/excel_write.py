"""Escribir las salidas de los bloques en una copia de un Excel (docs/PLAN_EXCEL.md §3.3, X6,
X8, R4).

- **La flecha de escritura** va de un bloque a una tarjeta `.xlsx`/`.xlsm` (`graph.writes_in`):
  no entra en el orden de ejecución ni en los ciclos (X8).
- **Qué va a cada nombre** se guarda en la tarjeta, `customData.writes = {nombre: {block, port,
  field}}`: un campo de salida de un bloque con flecha. Solo a un nombre admitido que no es una
  fórmula (escribir encima la borraría, R4), y con la unidad del campo pasada al sufijo del
  nombre (X4, `excel_names.convert_out`); lo que no casa se niega con su motivo.
- **«Escribir copia»** (`write_copy`) solo con todo elegido y cada bloque al día (sin resultado
  o desactualizado, el botón dice por qué). Escribe `<nombre>_n.xlsx` con `office_write.
  edit_copy` (el original solo se lee) y deja la propuesta de archivo de R47 (`change.file =
  {nuevo, diff, calc, aviso}`): aceptar pasa la tarjeta a la copia con el mismo id (sus
  conexiones, enlaces y escrituras la siguen) y rechazar manda la copia a la papelera.
- **Las fórmulas de la copia** pierden su valor guardado al escribirla openpyxl. Se recalculan
  con `excel_calc` (§3.4) sin esperar: la propuesta sale ya con las celdas escritas y `calc =
  {state: calculando}`, y `finish` (en un hilo, hasta `WAIT` s) da las fórmulas con nombre que
  cambian, que `apply_calc` añade al diff. Sin recálculo, `calc = {state: sin_valor, names,
  motivo}`: «ábrelo en Excel y guárdalo». Aceptar mientras calcula vale: la tarjeta lee la
  copia con la misma caché por huella.
"""
import uuid

from pizarra import excel_calc, excel_links, excel_names, files, graph, i18n, office_write, scene
from pizarra.config import AUTHOR_USER
from pizarra.read_files import _value as cell_text
from pizarra.validation import ValidationError

# Lo más que se espera al recálculo de la copia: el script tiene su tope (60 s), pero la primera
# vez se instala xlcalculator (unos 216 MB con numpy).
WAIT = 600


def writable(n):
    """¿Se puede escribir en el nombre `n` (`excel_names.Nombre`)? Una celda admitida (X3) que no
    es una fórmula (R4)."""
    return n.problema not in excel_links.NOT_ADMITTED and n.formula is None


def writers(board, card_id):
    """Los bloques con una flecha de escritura a la tarjeta, en orden."""
    return sorted({b for b, _, _ in graph.writes_in(board.elements, board.registry).get(card_id, ())})


def _book(board, card_id):
    """El `Book` de la tarjeta si es el del archivo de ahora, o None."""
    book, st = board.excel.get(card_id), board.sources.get(card_id)
    return book if book is not None and st is not None and book.hash == st.hash else None


def _title(board, block_id):
    el = graph.blocks_in(board.elements, board.registry).get(block_id)
    return board.registry[el["customData"]["blockType"]].title if el is not None else block_id


def _field(board, block_id, port, field):
    """El campo `{value, unit}` de la última salida del bloque, o None. Solo un valor (número,
    texto o sí/no): ni uno que cita un archivo ni un control (una vista 2D, una gráfica)."""
    f = (((board.state.get(block_id) or {}).get("outputs") or {}).get(port) or {}).get(field)
    ok = (isinstance(f, dict) and "file" not in f and not f.get("control")
          and isinstance(f.get("value"), (bool, int, float, str)))
    return f if ok else None


def _cards(board):
    return graph.sources_in(board.elements)


def _pending(board, card_id):
    return next((p for p in board.proposals
                 if p["target"] == card_id and p["state"] == "pendiente"), None)


def _row(board, name, w, book, statuses, ws, archivo):
    """`{block, port, field, value, unit, reason}` de lo que va a `name`: `value` ya en la unidad
    del sufijo; con `reason`, no se puede escribir."""
    bid, port, field = w.get("block"), w.get("port"), w.get("field")
    out = {"block": bid, "port": port, "field": field, "value": None,
           "unit": excel_names.suffix(name), "reason": None}
    title = _title(board, bid)

    def fail(motivo):
        out["reason"] = i18n.t("excel.escribir.fila", nombre=name, motivo=motivo,
                               origen=f"{title} · {port} · {field}")
        return out
    n = book.names.get(name) if book is not None else None
    if book is None:
        return fail(i18n.t("tarjeta.sin_comprobar"))
    if n is None:
        return fail(i18n.t("excel.nombre_borrado", archivo=archivo))
    if not writable(n):
        return fail(i18n.t("excel.escribir.es_formula") if n.formula is not None
                    else excel_links.problem_text(n.problema, book))
    if bid not in graph.blocks_in(board.elements, board.registry):
        return fail(i18n.t("excel.escribir.bloque_quitado"))
    if bid not in ws:
        return fail(i18n.t("excel.escribir.sin_flecha", bloque=title))
    status = statuses.get(bid)
    if status in ("desactualizado", "incompleto"):
        return fail(i18n.t(f"excel.escribir.{status}", bloque=title))
    f = _field(board, bid, port, field)
    if status != "al_dia" or f is None:
        if status == "al_dia":
            return fail(i18n.t("excel.escribir.campo_no_existe", bloque=title, campo=field,
                               salida=port))
        return fail(i18n.t("excel.escribir.sin_resultado", bloque=title))
    try:
        out["value"] = excel_names.convert_out(f["value"], f.get("unit") or "", n.unidad)
    except excel_names.UnitError as exc:
        return fail(i18n.t(f"excel.escribir.unidad.{exc.code}", **exc.vars))
    return out


def view(board, card_id):
    """Lo que la tarjeta enseña para escribir (§3.5), o None si no tiene flechas de escritura ni
    nada elegido: `writers` [{id, title}], `rows` {nombre: `_row`}, `ready`, `reason` (por qué no
    se puede escribir) y `pending` (la propuesta que espera)."""
    el = _cards(board).get(card_id)
    if el is None:
        return None
    ws = writers(board, card_id)
    writes = el["customData"].get("writes") or {}
    if not ws and not writes:
        return None
    book = _book(board, card_id)
    statuses = board.statuses()
    archivo = board.card_path(el).name
    rows = {name: _row(board, name, w, book, statuses, ws, archivo) for name, w in writes.items()}
    pending = _pending(board, card_id)
    st = board.sources.get(card_id)
    if pending is not None:
        reason = i18n.t("excel.escribir.pendiente")
    elif st is None or not st.hash:
        reason = files.reason_text(getattr(st, "reason", None)) or i18n.t("tarjeta.sin_comprobar")
    elif not rows:
        reason = i18n.t("excel.escribir.elige")
    else:
        reason = next((r["reason"] for r in rows.values() if r["reason"]), None)
    return {"writers": [{"id": b, "title": _title(board, b)} for b in ws], "rows": rows,
            "ready": reason is None, "reason": reason,
            "pending": pending["id"] if pending else None}


def set_write(board, card_id, name, block=None, port=None, field=None):
    """Elige el campo `port`·`field` del bloque `block` para el nombre `name` de la tarjeta (sin
    `block`, quita lo elegido). Se niega (`ValidationError`, nada cambia) si la tarjeta no es un
    Excel, si el nombre no existe o no se escribe (X3, R4), si el bloque no tiene flecha a la
    tarjeta o ese campo, o si la unidad no casa (X4). Devuelve la tarjeta cambiada."""
    el = board.card(card_id)
    path = board.card_path(el)
    if not excel_links.is_excel_card(board, el):
        raise ValidationError(i18n.t("excel.escribir.no_es_excel", archivo=path.name))
    cd = el["customData"]
    writes = dict(cd.get("writes") or {})
    if block is None:
        writes.pop(name, None)
    else:
        book = excel_links.refresh(board, card_id)
        if book is None or book.error:
            raise ValidationError(i18n.t("excel.ilegible", motivo=book.error) if book
                                  else i18n.t("tarjeta.sin_comprobar"))
        n = book.names.get(name) if isinstance(name, str) else None
        if n is None:
            raise ValidationError(i18n.t("excel.nombre_no_existe", archivo=path.name))

        def refuse(motivo):
            raise ValidationError(i18n.t("excel.escribir.fila", nombre=name, motivo=motivo,
                                         origen=f"{_title(board, block)} · {port} · {field}"))
        if not writable(n):
            refuse(i18n.t("excel.escribir.es_formula") if n.formula is not None
                   else excel_links.problem_text(n.problema, book))
        if block not in writers(board, card_id):
            refuse(i18n.t("excel.escribir.sin_flecha", bloque=_title(board, block)))
        f = _field(board, block, port, field)
        if f is None:
            refuse(i18n.t("excel.escribir.campo_no_existe", bloque=_title(board, block),
                          campo=field, salida=port))
        try:
            excel_names.convert_out(f["value"], f.get("unit") or "", n.unidad)
        except excel_names.UnitError as exc:
            refuse(i18n.t(f"excel.escribir.unidad.{exc.code}", **exc.vars))
        writes[name] = {"block": block, "port": port, "field": field}
    cd = {k: v for k, v in cd.items() if k != "writes"}
    new = scene.bumped({**el, "customData": {**cd, **({"writes": writes} if writes else {})}})
    board.elements = [new if e["id"] == card_id else e for e in board.elements]
    return new


def write_copy(board, card_id):
    """*Escribir copia*: escribe lo elegido en `<nombre>_n.xlsx` y deja la propuesta de archivo
    (R47). Devuelve `(propuesta, finish)`: `finish()` espera al recálculo de las fórmulas de la
    copia (en un hilo) y da lo que `apply_calc` añade a la propuesta; None si no hay que
    esperar. `ValidationError` con el motivo si no se puede: el original nunca se escribe."""
    v = view(board, card_id)
    if v is None or not v["ready"]:
        raise ValidationError(v["reason"] if v else i18n.t("excel.escribir.elige"))
    el = board.card(card_id)
    book = _book(board, card_id)
    names = book.names
    if all(names[n].valor == r["value"] and type(names[n].valor) is type(r["value"])
           for n, r in v["rows"].items()):
        raise ValidationError(i18n.t("excel.escribir.igual"))
    changes = [{"celda": names[n].where, "valor": r["value"]} for n, r in v["rows"].items()]
    try:
        dest, diff = office_write.edit_copy(board.card_path(el), changes)
    except office_write.OfficeError as exc:
        raise ValidationError(i18n.t("excel.escribir.no_se_escribe", motivo=exc)) from None
    by_where = {names[n].where: (n, r) for n, r in v["rows"].items()}
    diff = [{**d, "name": by_where[d["where"]][0],
             "source": "{} · {} · {}".format(_title(board, by_where[d["where"]][1]["block"]),
                                            by_where[d["where"]][1]["port"],
                                            by_where[d["where"]][1]["field"])}
            if d["where"] in by_where else d for d in diff]
    before = {k: cell_text(n.valor) if not n.problema else "" for k, n in names.items()
              if n.formula is not None}
    calc = excel_links.calculator(board)
    digest = files.file_digest(dest)
    formulas, state = _formulas(dest, digest, calc, before, wait=False)
    blocks = sorted({r["block"] for r in v["rows"].values()})
    n = len(diff)
    change = {"file": {"nuevo": files.stored_path(dest, board.ws.root), "diff": diff + formulas,
                       "calc": state, "aviso": i18n.t("excel.escribir.aviso")}}
    from pizarra import proposals as props
    p = {"id": uuid.uuid4().hex[:12], "author": AUTHOR_USER, "target": card_id,
         "base_version": el.get("version"), "base": props.content(el, board.state, change),
         "change": change,
         "reason": i18n.t("excel.escribir.motivo_uno" if n == 1 else "excel.escribir.motivo_varios",
                          n=n, bloques=", ".join(_title(board, b) for b in blocks)),
         "sources": [], "estimate": False, "state": "pendiente", "created": scene.now_iso()}
    board.proposals = board.proposals + [p]
    if state["state"] != excel_calc.CALCULANDO:
        return p, None
    return p, lambda: _formulas(dest, digest, calc, before, wait=True)


def _formulas(dest, digest, calc, before, wait):
    """`(filas del diff, calc)` de las fórmulas con nombre de la copia `dest`: las que cambian
    respecto de `before` ({nombre: texto del valor en el original}). Sin `wait`, si hay que
    recalcular, `([], {state: calculando})`."""
    recalc = calc.recalc_for(digest) if calc is not None else None
    names = excel_names.names(dest, recalc)
    if recalc is not None and recalc.state == excel_calc.CALCULANDO:
        if not wait:
            return [], {"state": excel_calc.CALCULANDO}
        calc.wait(digest, WAIT)
        recalc = calc.recalc_for(digest)
        names = excel_names.names(dest, recalc)
    rows, missing = [], []
    for key, n in names.items():
        if n.formula is None or n.problema in excel_links.NOT_ADMITTED:
            continue
        if n.problema or n.valor is None:
            missing.append(key)
            continue
        after = cell_text(n.valor)
        if after != before.get(key, ""):
            rows.append({"where": n.where, "name": key, "before": before.get(key, ""),
                         "after": after, "formula": True})
    if not missing:
        return rows, {"state": "hecho"}
    if recalc is not None and recalc.state == excel_calc.CALCULANDO:
        motivo = i18n.t("excel.problema.sin_calculo", motivo=i18n.t("excel.calculo.tiempo", s=WAIT))
    elif recalc is not None and recalc.error:
        key, kw = recalc.error
        motivo = i18n.t("excel.problema.sin_calculo", motivo=i18n.t(key, **kw))
    else:
        motivo = i18n.t("excel.problema.sin_valor")
    return rows, {"state": "sin_valor", "names": missing, "motivo": motivo}


def apply_calc(board, pid, result):
    """Añade a la propuesta `pid`, si sigue pendiente, las fórmulas recalculadas (`result`, lo que
    da `finish`). Devuelve si cambió."""
    rows, state = result
    for p in board.proposals:
        if p["id"] == pid and p["state"] == "pendiente" and "file" in p["change"]:
            f = p["change"]["file"]
            new = {**p, "change": {**p["change"], "file": {**f, "diff": f["diff"] + rows,
                                                           "calc": state}}}
            board.proposals = [new if q is p else q for q in board.proposals]
            return True
    return False
