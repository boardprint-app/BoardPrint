"""Parámetros de bloque enlazados a una celda con nombre de un Excel (docs/PLAN_EXCEL.md §3.2,
X2, X4, X5).

El enlace se guarda en el estado del bloque, `state[bloque]["links"] = {parámetro: {"card":
tarjeta, "name": nombre}}`, y el valor, en sus `params`, ya convertido a la unidad del
parámetro: el paquete ve un parámetro como cualquier otro. Lo leído de cada Excel (`Book`) lo da
el sondeo (`Board.probe`, D134) y no se guarda, como `sources`.

Va aparte de `board.py` (que ya roza las 1000 líneas): las funciones reciben la pizarra.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path

from pizarra import excel_calc, excel_names, files, graph, i18n, validation

# Lo que no se puede enlazar nunca (X3). Una celda sin valor sí: el bloque queda `incompleto`
# hasta que lo tenga (X5), y el recálculo (§3.4) se lo puede dar.
NOT_ADMITTED = {"varias_celdas", "constante", "no_es_celda", "ref_rota"}


@dataclass(frozen=True)
class Book:
    """Los nombres de un Excel con el hash del archivo del que salen. `error`: no se pudo
    leer. `calc_state`: el recálculo de sus fórmulas sin valor (§3.4), None si no hizo falta o
    ya está, `calculando` o `error`, con `calc_error` = `(código, vars)` del motivo."""
    hash: str
    names: dict = field(default_factory=dict)
    error: str | None = None
    calc_state: str | None = None
    calc_error: tuple | None = None


def calculator(board):
    """El recálculo de la pizarra: el suyo (tests) o el de la app (`excel_calc.configure`)."""
    return board.calc if getattr(board, "calc", None) is not None else excel_calc.current()


def read_book(path, digest, calc=None):
    """Los nombres del Excel `path`. Con `calc` (`excel_calc.Calculator`), las fórmulas sin
    valor guardado se recalculan en un hilo: mientras, su `problema` es `calculando`."""
    recalc = calc.recalc_for(digest) if calc is not None else None
    try:
        names = excel_names.names(path, recalc)
    except Exception as exc:            # noqa: BLE001 un Excel roto no tumba el sondeo
        return Book(digest, {}, f"{type(exc).__name__}: {exc}")
    state = recalc.state if recalc is not None else None
    if state == excel_calc.CALCULANDO:
        names = {k: replace(n, problema="calculando") if n.problema == "sin_valor" else n
                 for k, n in names.items()}
    return Book(digest, names, calc_state=state, calc_error=recalc.error if recalc else None)


def is_excel_card(board, el):
    return el["customData"]["kind"] == "file" and excel_names.is_excel(board.card_path(el))


def books(board, cards, sources):
    """`{tarjeta: Book}` de las tarjetas de Excel con hash: el de antes si el hash no cambió
    (los nombres solo dependen del contenido, también antes de ejecutar), salvo uno que
    estaba `calculando` y ya acabó: se vuelve a leer, con lo que dejó en la caché (§3.4)."""
    out, calc = {}, calculator(board)
    for cid, el in cards.items():
        st = sources.get(cid)
        if st is None or not st.hash or not is_excel_card(board, el):
            continue
        old = board.excel.get(cid)
        done = old is not None and old.calc_state == excel_calc.CALCULANDO and not (
            calc is not None and calc.running(old.hash))
        out[cid] = old if old is not None and old.hash == st.hash and not done \
            else read_book(board.card_path(el), st.hash, calc)
    return out


def problem_text(code, book=None):
    """El motivo de un `problema`. Una fórmula sin valor que no se pudo recalcular, con el
    porqué (sin entorno, sin red…)."""
    if code == "sin_valor" and book is not None and book.calc_error:
        key, kw = book.calc_error
        return i18n.t("excel.problema.sin_calculo", motivo=i18n.t(key, **kw))
    return i18n.t(f"excel.problema.{code}")


def names_view(book):
    """Lo que la tarjeta enseña de sus nombres (§3.5): cada uno con su valor, su unidad, su
    celda y, si no se admite o no tiene valor, el código (`problema`) y su texto (`motivo`)."""
    return [{**n.view(), "motivo": problem_text(n.problema, book) if n.problema else None}
            for n in book.names.values()]


def _spec(board, block_id, param):
    block = graph.blocks_in(board.elements, board.registry).get(block_id)
    if block is None:
        raise validation.ValidationError(i18n.t("bloque.no_existe", id=repr(block_id)))
    spec = board.registry[block["customData"]["blockType"]].params.get(param)
    if spec is None:
        raise validation.ValidationError(i18n.t("excel.parametro_no_existe", parametro=repr(param)))
    return spec


def resolve(board, block_id, param, link):
    """`{value, hash, where, reason}` de un enlace con lo último del sondeo, sin leer nada:
    con `reason`, el enlace no da valor (y `value` es None)."""
    spec = _spec(board, block_id, param)
    cid, name = link.get("card"), link.get("name")

    def fail(key, **kw):
        return {"value": None, "hash": None, "where": None,
                "reason": i18n.t("excel.enlace", parametro=spec.label or param, nombre=name,
                                 motivo=i18n.t(key, **kw) if key else kw["motivo"])}

    el = graph.sources_in(board.elements).get(cid)
    if el is None:
        return fail("excel.tarjeta_quitada")
    st = board.sources.get(cid)
    if st is None:
        return fail("tarjeta.sin_comprobar")
    if not st.hash:
        return fail(None, motivo=files.reason_text(st.reason) or i18n.t("tarjeta.sin_comprobar"))
    book = board.excel.get(cid)
    if book is None or book.hash != st.hash:
        return fail("tarjeta.sin_comprobar")
    if book.error:
        return fail("excel.ilegible", motivo=book.error)
    n = book.names.get(name)
    if n is None:
        return fail("excel.nombre_borrado", archivo=board.card_path(el).name)
    if n.problema:
        return fail(None, motivo=problem_text(n.problema, book))
    try:
        value = excel_names.convert(n.valor, n.unidad, spec.unit)
        validation.check_param(param, spec, value)
    except excel_names.UnitError as exc:
        return fail(f"excel.unidad.{exc.code}", **exc.vars)
    except validation.ValidationError as exc:
        return fail(None, motivo=str(exc))
    return {"value": value, "hash": st.hash, "where": n.where, "reason": None}


def _links(board):
    """`{bloque: {parámetro: enlace}}` de los bloques vivos con enlaces."""
    blocks = graph.blocks_in(board.elements, board.registry)
    return {bid: dict(st["links"]) for bid, st in board.state.items()
            if bid in blocks and st.get("links")}


def states(board):
    """`{bloque: {parámetro: (hash, motivo)}}` para `graph.explain`."""
    out = {}
    for bid, links in _links(board).items():
        for p, link in links.items():
            r = resolve(board, bid, p, link)
            out.setdefault(bid, {})[p] = (r["hash"], r["reason"])
    return out


def hashes(board, block_id):
    """`{parámetro: hash de su tarjeta}` de los enlaces con valor del bloque (`input_hash`)."""
    return {p: h for p, (h, why) in states(board).get(block_id, {}).items() if not why}


def apply(board):
    """Escribe en los `params` el valor de cada enlace que lo tiene (al sondear y antes de
    ejecutar). Uno sin valor deja el de antes: el bloque queda `incompleto`, nunca con un valor
    falso. Devuelve si cambió algún parámetro. Cambia la clave en su sitio: el sondeo corre en
    un hilo y nunca deja un `params` a medias."""
    changed = False
    for bid, links in _links(board).items():
        params = board.state[bid].setdefault("params", board.default_params(
            graph.blocks_in(board.elements, board.registry)[bid]["customData"]["blockType"]))
        for p, link in links.items():
            r = resolve(board, bid, p, link)
            if r["reason"] is None and (p not in params or params[p] != r["value"]
                                        or type(params[p]) is not type(r["value"])):
                params[p] = r["value"]
                changed = True
    return changed


def view(board):
    """`{bloque: {parámetro: {card, name, where, unit, value, reason, source}}}` para la
    interfaz: el candado, la celda y la fuente D19 (`archivo:<tarjeta>`, `Hoja!B3`)."""
    out = {}
    for bid, links in _links(board).items():
        params = board.state[bid].get("params") or {}
        for p, link in links.items():
            r = resolve(board, bid, p, link)
            out.setdefault(bid, {})[p] = {
                "card": link.get("card"), "name": link.get("name"), "where": r["where"],
                "unit": excel_names.suffix(link.get("name") or ""), "value": params.get(p),
                "reason": r["reason"],
                "source": {"kind": "archivo", "ref": f"archivo:{link.get('card')}",
                           "where": r["where"]} if r["where"] else None}
    return out


def link(board, block_id, param, card_id, name):
    """*Tomar de Excel* (§3.2): enlaza el parámetro con el nombre `name` de la tarjeta
    `card_id` y le pone ya su valor. Se niega (`ValidationError`, nada cambia) si la tarjeta no
    es un `.xlsx`/`.xlsm` de la pizarra, si el nombre no existe o no se admite (X3) o si la
    unidad no casa (X4). Un nombre sin valor sí se enlaza: el bloque queda `incompleto`."""
    spec = _spec(board, block_id, param)
    el = board.card(card_id)
    path = board.card_path(el)
    if not is_excel_card(board, el):
        raise validation.ValidationError(i18n.t("excel.no_es_excel", archivo=path.name))
    book = refresh(board, card_id)
    label = spec.label or param

    def refuse(motivo):
        raise validation.ValidationError(i18n.t("excel.enlace", parametro=label, nombre=name,
                                                motivo=motivo))
    st = board.sources.get(card_id)
    if book is None:
        refuse(files.reason_text(getattr(st, "reason", None)) or i18n.t("tarjeta.sin_comprobar"))
    if book.error:
        refuse(i18n.t("excel.ilegible", motivo=book.error))
    n = book.names.get(name) if isinstance(name, str) else None
    if n is None:
        refuse(i18n.t("excel.nombre_no_existe", archivo=path.name))
    if n.problema in NOT_ADMITTED:
        refuse(problem_text(n.problema))
    try:
        excel_names.check_unit(n.unidad, spec.unit)
        if n.valor is not None:
            validation.check_param(param, spec, excel_names.convert(n.valor, n.unidad, spec.unit))
    except excel_names.UnitError as exc:
        refuse(i18n.t(f"excel.unidad.{exc.code}", **exc.vars))
    except validation.ValidationError as exc:
        refuse(str(exc))
    st_block = board.state.setdefault(block_id, {})
    st_block["links"] = {**(st_block.get("links") or {}), param: {"card": card_id, "name": name}}
    apply(board)
    return view(board)[block_id][param]


def unlink(board, block_id, param):
    """*Quitar enlace*: el parámetro se queda con el último valor y vuelve a editarse a mano."""
    _spec(board, block_id, param)
    st = board.state.get(block_id) or {}
    links = {k: v for k, v in (st.get("links") or {}).items() if k != param}
    if "links" in st:
        if links:
            st["links"] = links
        else:
            del st["links"]


def refresh(board, card_id):
    """Sondea ya la tarjeta `card_id` (al enlazar no se espera al vigilante) y devuelve su
    `Book`, o None si el archivo no tiene hash."""
    el = board.card(card_id)
    with board._probe_lock:
        st = board.prober.probe_file(board.card_path(el))
        board.sources = {**board.sources, card_id: st}
        if not st.hash:
            return None
        found = books(board, {card_id: el}, {card_id: st}).get(card_id)
        board.excel = {**board.excel, card_id: found}
        return found


def check_manual(board, block_id, params):
    """Un parámetro enlazado no se cambia a mano (§3.5): `ValidationError` si `params` trae
    para uno de ellos otro valor que el que tiene. El mismo valor, sí (una interfaz que manda
    todos)."""
    st = board.state.get(block_id) or {}
    now = st.get("params") or {}
    for p in st.get("links") or {}:
        if p in params and params[p] != now.get(p):
            raise validation.ValidationError(i18n.t("excel.parametro_enlazado", parametro=p))
