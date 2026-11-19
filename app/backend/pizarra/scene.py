"""Escena de la pizarra: fusión de cambios y elementos que crea el backend.

Los elementos son los de Excalidraw (JSON). El backend guarda la escena completa y es quien
la persiste; el frontend pinta. Los elementos que crea el backend son mínimos: el frontend
los completa con `restoreElements` (rellena valores por defecto y mide el texto).
"""
import random
import time
import uuid
from datetime import datetime, timezone


def _wins(new, old):
    return old is None or new.get("version", 0) >= old.get("version", 0)


def accepted(current, incoming):
    """Los elementos de `incoming` que ganan a lo que hay: los que se reenvían a las demás
    ventanas del proyecto (D69)."""
    by_id = {e["id"]: e for e in current}
    return [e for e in incoming if _wins(e, by_id.get(e["id"]))]


def merge(current, incoming):
    """Fusiona un envío (parcial o completo) por id: gana la versión más alta (a igualdad, la
    entrante), como la reconciliación de Excalidraw en el caso de un usuario.

    Lo que no viene se queda como estaba y en su sitio, y lo nuevo va al final (D69). El orden
    de dibujo lo da el campo `index` de Excalidraw (índice fraccionario, se compara como
    texto): si todos los elementos lo llevan, se ordena por él; si no (elementos recién
    creados por el backend), se deja el orden de llegada hasta que el frontend se lo ponga.
    """
    pos = {e["id"]: i for i, e in enumerate(current)}
    out = list(current)
    for e in incoming:
        i = pos.get(e["id"])
        if i is None:
            pos[e["id"]] = len(out)
            out.append(e)
        elif _wins(e, out[i]):
            out[i] = e
    if out and all(isinstance(e.get("index"), str) for e in out):
        out.sort(key=lambda e: e["index"])            # estable: a igualdad, el orden de antes
    return out


def _base(type_, x, y, w, h, **kw):
    e = {
        "id": uuid.uuid4().hex[:20], "type": type_, "x": x, "y": y, "width": w, "height": h,
        "angle": 0, "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 1, "strokeStyle": "solid", "roughness": 1,
        "opacity": 100, "groupIds": [], "frameId": None, "roundness": None,
        "seed": random.randint(1, 2 ** 31 - 1), "version": 1,
        "versionNonce": random.randint(1, 2 ** 31 - 1), "isDeleted": False,
        "boundElements": None, "updated": int(time.time() * 1000), "link": None,
        "locked": False,
    }
    e.update(kw)
    return e


def bbox(e):
    """Caja real (x0, y0, x1, y1) de un elemento. En líneas, flechas y trazos libres los
    `points` son relativos a (x, y) y pueden ser negativos: la caja sale de ellos."""
    pts = e.get("points")
    if pts:
        xs = [e["x"] + p[0] for p in pts]
        ys = [e["y"] + p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)
    return e["x"], e["y"], e["x"] + e.get("width", 0), e["y"] + e.get("height", 0)


POSTIT_WIDTH = 260
POSTIT_MIN_HEIGHT = 120     # cabe la etiqueta y los controles del papel (D60, D80)
_CHARS_PER_LINE = 28        # Excalifont a 16 px en 240 px útiles; el frontend mide de verdad
POSTIT_LINK = "https://pizarra.local/postit/"
# La animación de un post-it (D175), encima de su texto: ancho y alto para los que se hace.
ANIMATION_SIZE = (240, 180)
# Relleno casi invisible y sin trazo en las tarjetas (post-its y bloques): Excalidraw solo da
# por tocado un elemento sin relleno en su borde, y la tarjeta se coge por todo el papel (el
# bloque, por su cabecera). El papel lo pinta la tarjeta con el skin; un relleno o un trazo de
# Excalidraw asomarían por el borde, y el tema oscuro los invierte.
CARD_FILL = "#ffffff01"
POSTIT_FILL = CARD_FILL


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bumped(e):
    """El elemento con la versión subida: así gana en todas las ventanas (D69)."""
    return {**e, "version": e.get("version", 0) + 1,
            "versionNonce": random.randint(1, 2 ** 31 - 1)}


def postit_height(text):
    """Alto estimado de la tarjeta; el frontend lo corrige al medir con la fuente real."""
    lines = (text or "").split("\n")
    n_lines = sum(1 + len(line) // _CHARS_PER_LINE for line in lines)
    return max(POSTIT_MIN_HEIGHT, 70 + 20 * n_lines)


def postit_element(postit, x, y):
    """El post-it como tarjeta (D71): un `embeddable` con todo lo suyo en `customData`.

    `postit` es `{text, kind, state, author, sources, estimate, anchor}` (para un agente, ya
    validado por validation.validate_postit). `kind` dice qué es el elemento; el tipo de
    post-it va en `postitKind`.
    """
    pid = uuid.uuid4().hex[:20]
    meta = {k: postit[k] for k in ("text", "state", "author", "sources", "estimate", "anchor")}
    return _base("embeddable", x, y, POSTIT_WIDTH, postit_height(postit["text"]), id=pid,
                 link=POSTIT_LINK + pid, strokeColor="transparent",
                 backgroundColor=POSTIT_FILL,
                 customData={"kind": "postit", "postitKind": postit["kind"], **meta,
                             "created": now_iso()})


def _r2_text(rect, txt):
    """El texto que escribió el autor dentro del texto ligado de R2, sin la cabecera del tipo
    ni la línea de fuentes que le añadía `postit_text`."""
    cd = rect.get("customData") or {}
    raw = (txt or {}).get("originalText") or (txt or {}).get("text") or ""
    lines = raw.split("\n")
    kind = str(cd.get("postitKind") or "").upper()
    if len(lines) > 1 and kind and lines[0].startswith(kind):
        lines = lines[1:]
    if len(lines) > 1 and cd.get("sources") and lines[-1].startswith("Fuente: "):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def migrate_postits(elements):
    """Convierte los post-its de R2 (rectángulo + texto ligado) en tarjetas (D71).

    Misma posición, ancho, `id`, `index` y `customData`; el texto pasa a `customData.text` y
    el texto ligado se borra (con la versión subida, para que una ventana vieja no lo
    resucite). Lo que ya es una tarjeta, o no es un post-it, no se toca: migrar dos veces da
    lo mismo. Devuelve `(elementos, si cambió algo)`.
    """
    by_id = {e.get("id"): e for e in elements}
    old = {e["id"] for e in elements
           if (e.get("customData") or {}).get("kind") == "postit"
           and e.get("type") != "embeddable"}
    if not old:
        return elements, False
    out = []
    for e in elements:
        if e.get("id") in old:
            texts = [b["id"] for b in e.get("boundElements") or [] if b.get("type") == "text"]
            txt = next((by_id[t] for t in texts if t in by_id), None)
            cd = dict(e.get("customData") or {})
            cd.setdefault("postitKind", "nota")
            cd.setdefault("state", "abierto")
            cd.setdefault("sources", [])
            cd.setdefault("estimate", False)
            cd.setdefault("anchor", None)
            cd["text"] = _r2_text(e, txt)
            if "created" not in cd and e.get("updated"):
                cd["created"] = datetime.fromtimestamp(
                    e["updated"] / 1000, timezone.utc).isoformat(timespec="seconds")
            bound = [b for b in e.get("boundElements") or [] if b.get("type") != "text"]
            out.append({**e, "type": "embeddable", "link": POSTIT_LINK + e["id"],
                        "backgroundColor": POSTIT_FILL, "strokeColor": "transparent",
                        "strokeStyle": "solid",
                        "roundness": None, "boundElements": bound or None,
                        "height": max(e.get("height", 0), POSTIT_MIN_HEIGHT),
                        "customData": cd, "version": e.get("version", 0) + 1,
                        "versionNonce": random.randint(1, 2 ** 31 - 1)})
        elif e.get("containerId") in old and not e.get("isDeleted"):
            out.append({**e, "isDeleted": True, "version": e.get("version", 0) + 1,
                        "versionNonce": random.randint(1, 2 ** 31 - 1)})
        else:
            out.append(e)
    return out, True


BLOCK_LINK = "https://pizarra.local/block/"
FILE_LINK = "https://pizarra.local/file/"
# La foto suelta y el enlace pegados (D137, D140) los crea la interfaz al pegar (así entran en
# deshacer); su prefijo hace falta aquí para que una copia pegada tenga su propio enlace.
IMAGE_LINK = "https://pizarra.local/image/"
LINK_LINK = "https://pizarra.local/link/"
CARD_LINKS = {"block": BLOCK_LINK, "postit": POSTIT_LINK, "file": FILE_LINK, "folder": FILE_LINK,
              "image": IMAGE_LINK, "link": LINK_LINK}
# Lo que se ancla a otro elemento con su cinta (D74, D140): post-its y fotos sueltas; y la tinta,
# a la tarjeta que marca, sin cinta (D192).
ANCHORED = {"postit", "image", "ink"}
# Tamaño de una tarjeta nueva (D139): el archivo es una etiqueta de una línea; la carpeta, tan
# estrecha como los tres papeles que asoman, con el nombre debajo. El frontend lo ajusta.
FILE_SIZE = (240, 40)
FOLDER_SIZE = (116, 150)


def adopt_pasted_card(e):
    """Un bloque o post-it pegado llega con el enlace del original y, si es un bloque, con sus
    parámetros en `customData.params` (D85). Devuelve `(elemento, parámetros)`: el elemento
    con su propio enlace y sin `params` (la versión subida), o `None` si no había nada que
    arreglar; los parámetros, o `None`. Los parámetros nunca se quedan en la escena: viven en
    el estado de los bloques."""
    cd = e.get("customData") or {}
    prefix = CARD_LINKS.get(cd.get("kind")) if e.get("type") == "embeddable" else None
    if prefix is None:
        return None, None
    params = cd.get("params")
    if e.get("link") == prefix + e["id"] and "params" not in cd:
        return None, None
    fixed = {**e, "link": prefix + e["id"],
             "customData": {k: v for k, v in cd.items() if k != "params"},
             "version": e.get("version", 0) + 1,
             "versionNonce": random.randint(1, 2 ** 31 - 1)}
    return fixed, params if isinstance(params, dict) else None


def block_element(block_type, x, y, author="user", width=280, height=220):
    bid = uuid.uuid4().hex[:20]
    return _base("embeddable", x, y, width, height, id=bid,
                 link=BLOCK_LINK + bid,
                 strokeColor="transparent", backgroundColor=CARD_FILL,
                 customData={"kind": "block", "blockType": block_type, "author": author,
                             "created": now_iso()})


def card_element(kind, path, x, y, author="user"):
    """Tarjeta de un archivo o una carpeta (D59, D131): un `embeddable` con la ruta guardada
    (`path`, relativa al workspace o absoluta, D138) en `customData`. No es un bloque: no tiene
    estado ni parámetros; lo que entra de una carpeta va en `content` (D142)."""
    w, h = FILE_SIZE if kind == "file" else FOLDER_SIZE
    cid = uuid.uuid4().hex[:20]
    cd = {"kind": kind, "path": path, "author": author, "created": now_iso()}
    if kind == "folder":
        cd["content"] = {"exclude": [], "patterns": []}
    return _base("embeddable", x, y, w, h, id=cid, link=FILE_LINK + cid,
                 strokeColor="transparent", backgroundColor=CARD_FILL, customData=cd)


def connection_element(src, dst, frm, to, author="user"):
    """Conexión de la salida `frm` de `src` a la entrada `to` de `dst` (D88), enganchada a los
    dos bloques. Sale recta, de borde a borde: la interfaz la convierte en la flecha en ángulo
    de enchufe a enchufe al recibirla (frontend/src/connections.ts, como las del spike)."""
    x0, y0 = src["x"] + src["width"] + 5, src["y"] + 18
    x1, y1 = dst["x"] - 5, dst["y"] + 18
    return _base("arrow", x0, y0, abs(x1 - x0), abs(y1 - y0),
                 points=[[0, 0], [x1 - x0, y1 - y0]], lastCommittedPoint=None,
                 startBinding={"elementId": src["id"], "focus": 0, "gap": 5},
                 endBinding={"elementId": dst["id"], "focus": 0, "gap": 5},
                 startArrowhead=None, endArrowhead="arrow", elbowed=False, roughness=0,
                 customData={"kind": "connection", "from": frm, "to": to, "author": author,
                             "created": now_iso()})


def ink_element(points, brush, size, color, author, shape=None, anchor=None, opacity=1):
    """Un trazo de tinta (D188): un `freedraw` con `opacity 0` (lo pinta la capa de la app, no
    Excalidraw) y sus datos en `customData.ink`. `points` son los puntos en la escena
    `[(x, y), ...]`: el elemento empieza en el primero y los guarda relativos, como Excalidraw."""
    ox, oy = points[0]
    rel = [[round(x - ox, 2), round(y - oy, 2)] for x, y in points]
    xs, ys = [p[0] for p in rel], [p[1] for p in rel]
    data = {"brush": brush, "size": size, "opacity": opacity, **({"shape": shape} if shape else {})}
    return _base("freedraw", ox, oy, max(xs) - min(xs), max(ys) - min(ys), opacity=0,
                 strokeColor=color, strokeWidth=size, roughness=0, points=rel, pressures=[],
                 simulatePressure=True, lastCommittedPoint=None,
                 customData={"kind": "ink", "ink": data, "author": author, "created": now_iso(),
                             **({"anchor": anchor} if anchor else {})})


LINE_TYPES = ("arrow", "line")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _good_points(pts):
    return (isinstance(pts, list) and len(pts) >= 2
            and all(isinstance(p, (list, tuple)) and len(p) >= 2 and _num(p[0]) and _num(p[1])
                    for p in pts))


def repair_line(e, by_id):
    """Una flecha o línea que Excalidraw no puede pintar (sin `points`, con menos de dos o con
    algo que no es un número, o sin `x`/`y`), arreglada; o None si está bien. Con una sola así,
    Excalidraw no restaura la escena y la pizarra sale en blanco (OP 4.1, PLAN_PAQUETES P88).
    Una conexión enganchada a dos elementos que existen se rehace de borde a borde, como
    `connection_element` (la interfaz la pone en ángulo); otra, una recta con su ancho y alto."""
    if e.get("type") not in LINE_TYPES or e.get("isDeleted"):
        return None
    if _good_points(e.get("points")) and _num(e.get("x")) and _num(e.get("y")):
        return None
    src = by_id.get((e.get("startBinding") or {}).get("elementId"))
    dst = by_id.get((e.get("endBinding") or {}).get("elementId"))
    if src is not None and dst is not None and all(_num(x.get(k)) for x in (src, dst)
                                                     for k in ("x", "y", "width")):
        x0, y0 = src["x"] + src["width"] + 5, src["y"] + 18
        x1, y1 = dst["x"] - 5, dst["y"] + 18
    else:
        x0 = e.get("x") if _num(e.get("x")) else 0
        y0 = e.get("y") if _num(e.get("y")) else 0
        w = e.get("width") if _num(e.get("width")) and e.get("width") else 100
        h = e.get("height") if _num(e.get("height")) else 0
        x1, y1 = x0 + w, y0 + h
    return bumped({**e, "x": x0, "y": y0, "width": abs(x1 - x0), "height": abs(y1 - y0),
                   "points": [[0, 0], [x1 - x0, y1 - y0]]})


def repair_lines(elements):
    """`repair_line` en toda la escena. Devuelve `(elementos, si cambió algo)`."""
    by_id = {e.get("id"): e for e in elements if not e.get("isDeleted")}
    out, changed = [], False
    for e in elements:
        fixed = repair_line(e, by_id)
        if fixed is not None:
            e, changed = fixed, True
        out.append(e)
    return out, changed


def migrate_kinds(elements, renamed):
    """Los bloques guardados con un id de antes (`{antes: ahora}`, `Registry.renamed`, P59)
    pasan al de ahora, con la versión subida; su estado, sus archivos y sus flechas van por el
    id del elemento y no cambian. Migrar dos veces da lo mismo. Devuelve `(elementos, si cambió
    algo)`."""
    out, changed = [], False
    for e in elements:
        cd = e.get("customData") or {}
        if cd.get("kind") == "block" and cd.get("blockType") in renamed:
            e = {**e, "customData": {**cd, "blockType": renamed[cd["blockType"]]},
                 "version": e.get("version", 0) + 1,
                 "versionNonce": random.randint(1, 2 ** 31 - 1)}
            changed = True
        out.append(e)
    return out, changed


def migrate_blocks(elements):
    """Quita a los bloques de antes de FF 4.3 el relleno blanco y el trazo de Excalidraw (D77):
    el papel lo pinta la tarjeta. Solo cambian esos dos colores (con la versión subida); el
    resto, igual. Migrar dos veces da lo mismo. Devuelve `(elementos, si cambió algo)`."""
    out, changed = [], False
    for e in elements:
        if (e.get("type") == "embeddable"
                and (e.get("customData") or {}).get("kind") == "block"
                and (e.get("strokeColor"), e.get("backgroundColor")) != ("transparent", CARD_FILL)):
            e = {**e, "strokeColor": "transparent", "backgroundColor": CARD_FILL,
                 "version": e.get("version", 0) + 1,
                 "versionNonce": random.randint(1, 2 ** 31 - 1)}
            changed = True
        out.append(e)
    return out, changed


def migrate_connections(elements, registry):
    """Pone sus puertos a las flechas del spike que unen dos bloques sin decir qué puertos
    (D88): `customData = {kind: "connection", from, to}` con la única pareja posible, y la
    versión subida. Si hay duda, o la flecha es de dibujo libre, no se toca. Migrar dos veces
    da lo mismo. Devuelve `(elementos, si cambió algo)`."""
    from pizarra import graph
    blocks = graph.blocks_in(elements, registry)
    out, changed = [], False
    for e in elements:
        ends = (graph.arrow_ends(e, blocks)
                if e.get("type") == "arrow" and not e.get("isDeleted") else None)
        if ends and ends[0] != ends[1] and graph.arrow_ports(e) == (None, None):
            ports, _ = graph.resolve_ports(e, registry[blocks[ends[0]]["customData"]["blockType"]],
                                           registry[blocks[ends[1]]["customData"]["blockType"]])
            if ports is not None:
                cd = {**(e.get("customData") or {}), "kind": "connection",
                      "from": ports[0], "to": ports[1]}
                out.append(bumped({**e, "customData": cd}))
                changed = True
                continue
        out.append(e)
    return out, changed


def summary(elements, statuses, state):
    """Lectura estructurada de la pizarra para un agente (`leer_pizarra`)."""
    out = {"blocks": [], "postits": [], "texts": [], "arrows": 0}
    for e in elements:
        if e.get("isDeleted"):
            continue
        cd = e.get("customData") or {}
        if cd.get("kind") == "block":
            st = state.get(e["id"]) or {}
            out["blocks"].append({"id": e["id"], "type": cd["blockType"],
                                  "status": statuses.get(e["id"]),
                                  "params": st.get("params"), "outputs": st.get("outputs")})
        elif cd.get("kind") == "postit":
            out["postits"].append({"id": e["id"], "kind": cd.get("postitKind"),
                                   **{k: cd.get(k) for k in ("text", "state", "author",
                                                             "sources", "anchor")}})
        elif e.get("type") == "arrow":
            out["arrows"] += 1
        elif e.get("type") == "text" and not e.get("containerId"):
            out["texts"].append({"id": e["id"], "text": e.get("text"),
                                 "author": cd.get("author", "user")})
    return out
