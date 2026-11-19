"""Herramientas del agente que montan la pizarra (FF 4.6 paso 2; plan §4, D170, D171).

`crear_bloque`, `conectar`, `poner_plantilla`, `ejecutar_bloque`, `ver_zona`, y `marcar` y
`quitar_marca` (la tinta del agente, D194). Como las de
`agent.py`, son funciones normales que se prueban sin el SDK, y pasan por las mismas reglas
que la interfaz: el bloque solo de un tipo cargado y nunca encima de nada, la conexión por el
grafo (`Board.connect`), la plantilla en un sitio libre (`Board.add_template`). Lo que crea el
agente es suyo (`agent:design`): lo edita directamente con `proponer_cambio`; lo del ingeniero,
solo con propuesta (D20). Un rechazo vuelve como error de herramienta con el motivo.

`ejecutar_bloque` y `ver_zona` necesitan el servidor: la ejecución en segundo plano del botón
*Ejecutar* (`run_block`) y una ventana abierta que pinte la zona (`request_zone`, `zone.py`).
`DesignAgent` los recibe del servidor; sin ellos (la API REST, los tests) dan error.
"""
import json
import math

from pizarra import execution, graph, ink
from pizarra.agent import AGENT, PORT_CHARS, TOOL_CHARS, _digest, _error, _ok
from pizarra.validation import ValidationError
from pizarra.zone import MAX_SIDE

ID = {"type": "string", "description": "id de un elemento (de leer_pizarra)"}
SCHEMAS = {
    "crear_bloque": {"type": "object", "properties": {
        "tipo": {"type": "string", "description": "tipo de bloque: una clave de "
                                                  "`catalog.blocks` de leer_pizarra"},
        "params": {"type": "object", "description": "{nombre: valor}; lo que no se da, por "
                                                    "defecto"},
        "cerca_de": {**ID, "description": "id del elemento junto al que ponerlo"}},
        "required": ["tipo"]},
    "conectar": {"type": "object", "properties": {
        "desde": {"type": "string", "description": "«bloque:salida» (o «tarjeta» de archivo)"},
        "hasta": {"type": "string", "description": "«bloque:entrada»"}},
        "required": ["desde", "hasta"]},
    "poner_plantilla": {"type": "object", "properties": {
        "plantilla": {"type": "string", "description": "id, de `catalog.templates` de "
                                                       "leer_pizarra"},
        "cerca_de": {**ID, "description": "id del elemento junto al que ponerla"}},
        "required": ["plantilla"]},
    "ejecutar_bloque": {"type": "object", "properties": {
        "bloque": {**ID, "description": "id del bloque"}}, "required": ["bloque"]},
    "ver_zona": {"type": "object", "properties": {
        "x": {"type": "number"}, "y": {"type": "number"},
        "ancho": {"type": "number"}, "alto": {"type": "number"},
        "elementos": {"type": "array", "items": {"type": "string"},
                      "description": "ids; en vez del recuadro x, y, ancho, alto"}}},
    "marcar": {"type": "object", "properties": {
        "objetivo": {**ID, "description": "id del elemento que marcar"},
        "marca": {"type": "string", "enum": list(ink.MARKS)},
        "color": {"type": "string", "description": "negro, rojo, azul, verde, amarillo o "
                                                   "«#rrggbb»; por defecto rojo (amarillo al "
                                                   "resaltar)"}},
        "required": ["objetivo", "marca"]},
    "quitar_marca": {"type": "object", "properties": {
        "id": {**ID, "description": "id de una marca tuya (de `tinta` en leer_pizarra)"}},
        "required": ["id"]},
}
DESCRIPTIONS = {
    "crear_bloque": "Crea un bloque de un tipo cargado, tuyo, en un sitio libre (junto a "
                    "`cerca_de` si cabe). Devuelve su id y sus puertos.",
    "conectar": "Conecta la salida de un bloque con la entrada de otro, con las reglas de la "
                "interfaz: mismo tipo, entrada libre y sin ciclos.",
    "poner_plantilla": "Pone una plantilla de la bandeja (una cadena de bloques ya conectada) "
                       "en un sitio libre. Devuelve los ids.",
    "ejecutar_bloque": "Ejecuta un bloque, con lo de delante que no está al día, como el botón "
                       "Ejecutar; espera a que acabe y da su estado y sus salidas resumidas. "
                       "No cambia parámetros.",
    "ver_zona": "La imagen (PNG) de un recuadro de la pizarra en coordenadas de la escena, o "
                "de unos elementos: para ver croquis, flechas y lo dibujado a mano.",
    "marcar": "Marca un elemento con tinta, como lo haría el ingeniero a mano: rodear, "
              "subrayar, resaltar, una flecha que llega a él o tacharlo. La marca es tuya y "
              "sigue al elemento. Para señalar algo al responder, no para escribir.",
    "quitar_marca": "Quita una marca de tinta tuya; las del ingeniero no se pueden quitar.",
}
ZONE_NOTE = ("Los bloques, post-its y tarjetas salen como un recuadro con su título o su texto: "
             "sus datos, con leer_pizarra y leer_bloque.")
ZONE_EXCLUDED = (" Sin las imágenes pegadas: el ingeniero ha marcado «Excluir adjuntos» en este "
                 "proyecto.")


def _ports(board, kind):
    t = board.registry[kind]
    return {"entradas": dict(t.inputs), "opcionales": list(t.optional),
            "salidas": dict(t.outputs)}


def catalog(registry):
    """Los tipos de bloque cargados y las plantillas, para `leer_pizarra`: lo que se puede
    crear con `crear_bloque` y `poner_plantilla`, con los puertos para `conectar`."""
    return {"blocks": {k: {"title": t.title, "inputs": dict(t.inputs),
                           "outputs": dict(t.outputs),
                           **({"optional": list(t.optional)} if t.optional else {})}
                       for k, t in registry.items()},
            "templates": {t.id: t.title for t in registry.templates.values()}}


def tool_crear_bloque(board, args):
    """Devuelve (resultado para el agente, elementos nuevos o [])."""
    kind, params = args.get("tipo"), args.get("params") or {}
    if kind not in board.registry:
        return _error(f"Rechazado: no hay ningún tipo de bloque {kind!r} cargado; los que hay "
                      f"están en `catalog.blocks` de leer_pizarra"), []
    if not isinstance(params, dict):
        return _error("Rechazado: `params` tiene que ser un objeto {nombre: valor}"), []
    unknown = sorted(set(params) - set(board.registry[kind].params))
    if unknown:
        return _error(f"Rechazado: {kind} no tiene los parámetros {', '.join(unknown)}; tiene: "
                      f"{', '.join(board.registry[kind].params) or 'ninguno'}"), []
    try:
        el = board.add_block(kind, params, near=args.get("cerca_de"), author=AGENT)
    except ValidationError as exc:
        return _error(f"Rechazado: {exc}"), []
    board.save()
    return _ok({"creado": el["id"], "tipo": kind, **_ports(board, kind),
                "params": board.state[el["id"]]["params"],
                "estado": board.statuses().get(el["id"])}), [el]


def _end(text, what):
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(f"`{what}` tiene que ser «bloque:puerto»")
    node, _, port = text.strip().partition(":")
    return node, port or None


def tool_conectar(board, args):
    """Devuelve (resultado para el agente, elementos nuevos o cambiados o [])."""
    try:
        src, frm = _end(args.get("desde"), "desde")
        dst, to = _end(args.get("hasta"), "hasta")
        changed = board.connect(src, frm, dst, to, author=AGENT)
    except ValidationError as exc:
        return _error(f"Rechazado: {exc}"), []
    board.save()
    cd = changed[0]["customData"]
    return _ok({"conexion": changed[0]["id"], "desde": f"{src}:{cd.get('from') or ''}",
                "hasta": f"{dst}:{cd.get('to') or ''}"}), changed


def tool_poner_plantilla(board, args):
    """Devuelve (resultado para el agente, elementos nuevos o [])."""
    tid = args.get("plantilla")
    if tid not in board.registry.templates:
        return _error(f"Rechazado: no hay ninguna plantilla {tid!r}; las que hay están en "
                      "`catalog.templates` de leer_pizarra"), []
    try:
        new = board.add_template(tid, author=AGENT, near=args.get("cerca_de"))
    except ValidationError as exc:
        return _error(f"Rechazado: {exc}"), []
    board.save()
    blocks = [{"id": e["id"], "tipo": e["customData"]["blockType"]}
              for e in new if e["type"] == "embeddable"]
    return _ok({"bloques": blocks,
                "conexiones": [e["id"] for e in new if e["type"] == "arrow"]}), new


async def tool_ejecutar_bloque(board, args, run_block):
    """Lanza la ejecución con `run_block(bloque)` (la del servidor: el botón *Ejecutar*, D89),
    espera a que acabe y devuelve el estado y las salidas resumidas del bloque. Si no puede
    empezar (otra ejecución en el proyecto, algo de delante que no se puede ejecutar), error
    con el motivo. Un bloque que acaba en error no es un error de la herramienta: lo dice
    `estado`."""
    bid = args.get("bloque")
    if run_block is None:
        return _error("No se puede ejecutar desde aquí: solo con la pizarra abierta en la app")
    blocks = graph.blocks_in(board.elements, board.registry)
    if bid not in blocks:
        return _error(f"no hay ningún bloque {bid!r}: usa el `id` que devuelve leer_pizarra")
    # Nunca lanza nada que escriba fuera del proyecto (prueba de punta a punta de FF 4.6: una
    # lista de materiales lanzó *Construir en Fusion* y creó un proyecto en el hub). Un bloque
    # que pide un conector lo ejecuta el ingeniero; sus salidas ya al día sí valen.
    outside = [b for b in execution.would_run(board, bid)
               if board.registry[blocks[b]["customData"]["blockType"]].requires]
    if outside:
        kinds = [board.registry[blocks[b]["customData"]["blockType"]] for b in outside]
        where = ", ".join(sorted({c.capitalize() for k in kinds for c in k.requires}))
        return _error(f"No se ejecuta nada: esto escribe en {where}: pulsa Ejecutar tú. "
                      "Pídeselo al ingeniero. Bloques: "
                      + "; ".join(f"{k.title} ({b})" for k, b in zip(kinds, outside)))
    try:
        summary = await run_block(bid)
    except ValidationError as exc:
        return _error(f"No se ejecuta: {exc}")
    st = board.state.get(bid) or {}
    out = {"bloque": bid, "estado": board.statuses().get(bid),
           "ejecutados": summary.get("done", []), "fallidos": summary.get("failed", []),
           "cancelada": bool(summary.get("cancelled")),
           **({"saltados": summary["skipped"]} if summary.get("skipped") else {}),
           **({"error": summary["error"]} if summary.get("error") else {}),
           **({"error_bloque": st["error"]} if st.get("error") else {}),
           "salidas": _digest(st.get("outputs"), PORT_CHARS[1]),
           "cite": f"bloque:{bid}", "nota": "cada campo entero, con leer_bloque"}
    text = json.dumps(out, ensure_ascii=False)
    if len(text) > TOOL_CHARS:
        out["salidas"] = _digest(st.get("outputs"), PORT_CHARS[-1])
        text = json.dumps(out, ensure_ascii=False)
    return _ok(text)


def is_pasted_image(el):
    """Una imagen pegada (D84, D140): la foto suelta o una imagen de Excalidraw. Un post-it con
    foto no: se pinta su recuadro con el texto, nunca la foto."""
    return el.get("type") == "image" or (el.get("customData") or {}).get("kind") == "image"


def zone_payload(board, args, excluded=False):
    """Lo que se pide a la ventana (`zone.py`): el recuadro o los elementos, comprobados.
    Con *Excluir adjuntos* (D169) las imágenes pegadas no salen al agente: la ventana las quita
    del recuadro, y pedir solo imágenes es un error."""
    rect = [args.get(k) for k in ("x", "y", "ancho", "alto")]
    ids = args.get("elementos")
    if ids and any(v is not None for v in rect):
        raise ValidationError("da el recuadro (x, y, ancho, alto) o `elementos`, no los dos")
    if ids:
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValidationError("`elementos` tiene que ser una lista de ids")
        live = {e["id"]: e for e in board.elements if not e.get("isDeleted")}
        missing = [i for i in ids if i not in live]
        if missing:
            raise ValidationError(f"no hay ningún elemento {', '.join(map(repr, missing))}: "
                                  "usa los `id` de leer_pizarra")
        if excluded:
            ids = [i for i in ids if not is_pasted_image(live[i])]
            if not ids:
                raise ValidationError("esos elementos son imágenes pegadas y el ingeniero ha "
                                      "marcado «Excluir adjuntos»: no salen al agente")
        target = {"elements": list(dict.fromkeys(ids))}
    else:
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in rect):
            raise ValidationError("da el recuadro con x, y, ancho y alto (números) o `elementos`")
        if rect[2] <= 0 or rect[3] <= 0:
            raise ValidationError("el ancho y el alto del recuadro tienen que ser positivos")
        target = {"rect": dict(zip(("x", "y", "width", "height"), rect))}
    return {**target, "maxSide": MAX_SIDE, "excludeImages": bool(excluded)}


async def tool_ver_zona(board, args, request_zone, excluded=False):
    """La imagen de la zona que pinta una ventana (D171), como contenido de imagen del MCP.
    Sin ventana, pasado el plazo o con la respuesta mal, error con el motivo (`zone.py`)."""
    if request_zone is None:
        return _error("No se puede ver la zona: solo con la pizarra abierta en la app")
    try:
        payload = zone_payload(board, args, excluded)
        png = await request_zone(payload)
    except ValidationError as exc:
        return _error(f"No se puede ver la zona: {exc}")
    note = {"zona": payload.get("rect") or {"elementos": payload["elements"]},
            "nota": ZONE_NOTE + (ZONE_EXCLUDED if excluded else "")}
    return {"content": [{"type": "image", "data": png, "mimeType": "image/png"},
                        {"type": "text", "text": json.dumps(note, ensure_ascii=False)}]}


def tool_marcar(board, args):
    """Devuelve (resultado para el agente, elementos nuevos o [])."""
    try:
        new = board.agent_add_ink(AGENT, args.get("objetivo"), args.get("marca"),
                                  args.get("color"))
    except ValidationError as exc:
        return _error(f"Rechazado: {exc}"), []
    board.save()
    d = ink.describe_stroke(new[0], board.elements, board.registry)
    return _ok({"marca": new[0]["id"], "forma": d["forma"], "apunta": d["apunta"]}), new


def tool_quitar_marca(board, args):
    """Devuelve (resultado para el agente, elementos cambiados o [])."""
    try:
        gone = board.agent_remove_ink(AGENT, args.get("id"))
    except ValidationError as exc:
        return _error(f"Rechazado: {exc}"), []
    board.save()
    return _ok({"quitada": gone[0]["id"]}), gone


NAMES = tuple(SCHEMAS)


def sdk_tools(agent, tool):
    """Las herramientas para el servidor MCP del agente (`DesignAgent._options`), con `tool`
    el decorador del SDK. Lo que cambia la pizarra se pinta con `agent.on_elements`."""
    board = agent.board

    async def painted(result, changed):
        if changed:
            await agent.on_elements(changed)
        return result

    @tool("crear_bloque", DESCRIPTIONS["crear_bloque"], SCHEMAS["crear_bloque"])
    async def crear_bloque(args):
        return await painted(*tool_crear_bloque(board, args))

    @tool("conectar", DESCRIPTIONS["conectar"], SCHEMAS["conectar"])
    async def conectar(args):
        return await painted(*tool_conectar(board, args))

    @tool("poner_plantilla", DESCRIPTIONS["poner_plantilla"], SCHEMAS["poner_plantilla"])
    async def poner_plantilla(args):
        return await painted(*tool_poner_plantilla(board, args))

    @tool("ejecutar_bloque", DESCRIPTIONS["ejecutar_bloque"], SCHEMAS["ejecutar_bloque"])
    async def ejecutar_bloque(args):
        return await tool_ejecutar_bloque(board, args, agent.run_block)

    @tool("ver_zona", DESCRIPTIONS["ver_zona"], SCHEMAS["ver_zona"])
    async def ver_zona(args):
        return await tool_ver_zona(board, args, agent.request_zone,
                                   bool(agent.exclude_attachments()))

    @tool("marcar", DESCRIPTIONS["marcar"], SCHEMAS["marcar"])
    async def marcar(args):
        return await painted(*tool_marcar(board, args))

    @tool("quitar_marca", DESCRIPTIONS["quitar_marca"], SCHEMAS["quitar_marca"])
    async def quitar_marca(args):
        return await painted(*tool_quitar_marca(board, args))

    return [crear_bloque, conectar, poner_plantilla, ejecutar_bloque, ver_zona, marcar,
            quitar_marca]
