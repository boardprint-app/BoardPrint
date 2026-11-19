"""Herramientas de Office del agente (FF 4.6 paso 7; plan D61, D176, §4).

- `crear_archivo {tipo, nombre, contenido, carpeta?, sources?, estimate?}`: un Word, un Excel
  o un PowerPoint nuevo (`office_write.create`) en `<proyecto>/archivos/` o, con `carpeta`, en
  la de una tarjeta de carpeta de la pizarra (nunca en una ruta que diga el agente, R5).
  **Nunca pisa** (`_n`) y deja su tarjeta, del agente. Las cifras del contenido siguen la
  regla de los números (D19), como un post-it: sin `sources` ni `estimate`, se rechaza.
- `editar_archivo {tarjeta, cambios, motivo, sources?, estimate?}`: escribe la copia
  `<nombre>_n.<ext>` con los cambios (`office_write.edit_copy`) y deja una **propuesta de
  archivo** sobre la tarjeta, `change = {file: {nuevo, diff}}`, con `nuevo` guardado como las
  rutas de las tarjetas (D138). El original **nunca** se toca, tampoco en una tarjeta del
  propio agente: aceptar pasa la tarjeta al archivo nuevo, rechazar lo manda a la papelera
  (`Board.accept_proposal` / `reject_proposal`). Las cifras que escribe, con fuente (D19).

*Excluir adjuntos* (D169): `editar_archivo` se rechaza (leería el archivo y su contenido
saldría al agente en el diff). `crear_archivo` no cuenta como adjunto: no lee nada del disco,
solo escribe lo que el agente ya tiene, así que sigue permitido.

Como las demás, son funciones normales que se prueban sin el SDK; un rechazo vuelve al agente
como error con el motivo y no deja nada escrito.
"""
import uuid

from pizarra import files, office_write, scene, validation
from pizarra.agent import AGENT, _error, _ok
from pizarra.validation import ValidationError

FOLDER = "archivos"             # dentro de la carpeta del proyecto
DIFF_SHOWN = 40                 # cambios del diff que vuelven al agente

EXCLUDED = ("No se puede editar: el ingeniero ha marcado «Excluir adjuntos» en este proyecto, "
            "así que ningún archivo sale al agente. Dile qué cambiar y que lo haga él.")

SOURCES = {"type": "array", "items": {"type": "object"},
           "description": "fuentes de las cifras que escribes (como en crear_postit); "
                          "obligatorio si hay cifras, o estimate=true"}
SCHEMAS = {
    "crear_archivo": {"type": "object", "properties": {
        "tipo": {"type": "string", "enum": list(office_write.TYPES)},
        "nombre": {"type": "string", "description": "nombre del archivo, sin carpeta (la "
                                                    "extensión se pone sola)"},
        "contenido": {"type": "object", "description":
                      "Word: " + office_write.CONTENT_HELP["docx"]
                      + ". Excel: " + office_write.CONTENT_HELP["xlsx"]
                      + " (un texto que empieza por = es una fórmula). PowerPoint: "
                      + office_write.CONTENT_HELP["pptx"] + " (vinetas y tabla, opcionales)"},
        "carpeta": {"type": "string", "description": "id de una tarjeta de carpeta de la "
                                                     "pizarra; sin ella, la del proyecto"},
        "sources": SOURCES,
        "estimate": {"type": "boolean"}},
        "required": ["tipo", "nombre", "contenido"]},
    "editar_archivo": {"type": "object", "properties": {
        "tarjeta": {"type": "string", "description": "id de la tarjeta del archivo (los "
                                                     "`files` de leer_pizarra)"},
        "cambios": {"type": "array", "items": {"type": "object"}, "description":
                    "Word: {parrafo: n, texto} | {tabla: n, fila: r, columna: c, texto} | "
                    "{antes: 'texto que hay', texto: 'por el nuevo'}. Excel: {celda: "
                    "'Hoja1!B4', valor}. PowerPoint: {diapositiva: n, forma: k, texto} | "
                    "{antes, texto, diapositiva?}. Números desde 1, como los `where` de "
                    "leer_archivo (forma: las que tienen texto, en el orden en que salen)"},
        "motivo": {"type": "string", "description": "por qué, en una frase"},
        "sources": SOURCES,
        "estimate": {"type": "boolean"}},
        "required": ["tarjeta", "cambios", "motivo"]},
}
DESCRIPTIONS = {
    "crear_archivo": "Crea un Word, un Excel o un PowerPoint nuevo con el contenido que das y "
                     "deja su tarjeta en la pizarra. Nunca pisa: si el nombre está, _1, _2…",
    "editar_archivo": "Propone cambios en un Word, un Excel o un PowerPoint de la pizarra: "
                      "escribe una copia <nombre>_n con ellos y deja una propuesta con el diff. "
                      "El original no se toca; el ingeniero acepta o rechaza.",
}
NAMES = tuple(SCHEMAS)


def _sources(board, args, written):
    """Las fuentes validadas de lo que escribe el agente (D19): con cifras en `written`, hacen
    falta `sources` o `estimate`."""
    sources = args.get("sources") or []
    if not isinstance(sources, list):
        raise ValidationError("`sources` tiene que ser una lista")
    for src in sources:
        validation.check_source(src)
    estimate = bool(args.get("estimate", False))
    if not sources and not estimate and any(validation.has_figures(t) for t in written):
        raise ValidationError(
            "lo que escribes lleva cifras y no lleva fuente: cita un bloque, una ficha, un "
            "archivo de la pizarra o un dato vivo en `sources`, o márcalo con estimate=true")
    board._check_block_sources(sources)
    return sources, estimate


def target_folder(board, carpeta):
    """Dónde escribe `crear_archivo`: la carpeta de una tarjeta de carpeta, o
    `<proyecto>/archivos/` (se crea)."""
    if carpeta:
        el = board.card(carpeta)
        if el["customData"]["kind"] != "folder":
            raise ValidationError(f"{carpeta!r} es un archivo: `carpeta` es el id de una "
                                  "tarjeta de carpeta")
        path = board.card_path(el)
        if not path.is_dir():
            raise ValidationError(f"{path.name}: carpeta no encontrada en {path.parent}")
        return path, carpeta
    path = board.dir / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path, None


def tool_crear_archivo(board, args, excluded=False):
    """Devuelve (resultado para el agente, elementos nuevos o []). `excluded` no cambia nada
    (crear no lee ningún adjunto, ver arriba): se recibe para que las dos herramientas se
    llamen igual."""
    del excluded
    tipo = args.get("tipo")
    try:
        content = office_write.check_content(tipo, args.get("contenido"))
        office_write.check_name(args.get("nombre"), tipo)
        sources, estimate = _sources(board, args, office_write.texts(tipo, content))
        folder, near = target_folder(board, args.get("carpeta"))
        path = office_write.create(tipo, content, folder, args.get("nombre"))
    except (ValidationError, office_write.OfficeError, OSError) as exc:
        return _error(f"Rechazado: {exc}"), []
    x, y = board._free_spot(*scene.FILE_SIZE, near)
    el = board.add_cards([path], x, y, author=AGENT)[0]
    el["customData"].update(sources=sources, estimate=estimate)
    board.save()
    return _ok({"creado": el["id"], "archivo": path.name,
                "ruta": el["customData"]["path"],
                "nota": "su tarjeta ya está en la pizarra; " + (
                    "el nombre estaba cogido y se ha llamado así" if path.name !=
                    office_write.check_name(args.get("nombre"), tipo) else "es tuya")}), [el]


def tool_editar_archivo(board, args, excluded=False):
    """Devuelve (resultado para el agente, si hay propuesta nueva). Con un rechazo no queda
    ni la copia ni la propuesta."""
    if excluded:
        return _error(EXCLUDED), False
    card, reason = args.get("tarjeta"), args.get("motivo")
    try:
        el = board.card(card)
        if el["customData"]["kind"] != "file":
            raise ValidationError("es una carpeta: edita un archivo con su propia tarjeta")
        if not isinstance(reason, str) or not reason.strip():
            raise ValidationError("una propuesta lleva siempre su motivo (`motivo`)")
        if any(p["target"] == card and p["state"] == "pendiente" for p in board.proposals):
            raise ValidationError(f"ya hay una propuesta pendiente sobre {card!r}: espera a "
                                  "que el ingeniero la acepte o la rechace")
        src = board.card_path(el)
        office_write.kind_of(src)
        changes = args.get("cambios")
        written = [str(c.get("texto", c.get("valor", ""))) for c in changes or ()
                   if isinstance(c, dict) and not isinstance(c.get("valor"), bool)]
        sources, estimate = _sources(board, args, written)
        dest, diff = office_write.edit_copy(src, changes)
    except (ValidationError, office_write.OfficeError, OSError) as exc:
        return _error(f"Rechazado: {exc}"), False
    change = {"file": {"nuevo": files.stored_path(dest, board.ws.root), "diff": diff}}
    from pizarra import proposals as props
    p = {"id": uuid.uuid4().hex[:12], "author": AGENT, "target": card,
         "base_version": el.get("version"), "base": props.content(el, board.state, change),
         "change": change, "reason": reason.strip(), "sources": sources,
         "estimate": estimate, "state": "pendiente", "created": scene.now_iso()}
    board.proposals = board.proposals + [p]
    board.save()
    return _ok({"propuesta": p["id"], "estado": "pendiente", "nuevo": dest.name,
                "diff": diff[:DIFF_SHOWN],
                **({"diff_total": len(diff)} if len(diff) > DIFF_SHOWN else {}),
                "nota": f"el original no se ha tocado: los cambios están en {dest.name}. El "
                        "ingeniero ve el diff y acepta (la tarjeta pasa a la copia) o rechaza "
                        "(la copia se borra)"}), True


def sdk_tools(agent, tool):
    """Las dos herramientas para el servidor MCP del agente (`DesignAgent._options`). Leen y
    escriben archivos: corren en un hilo, como `leer_archivo`."""
    import asyncio
    board = agent.board

    @tool("crear_archivo", DESCRIPTIONS["crear_archivo"], SCHEMAS["crear_archivo"])
    async def crear_archivo(args):
        result, new = await asyncio.to_thread(tool_crear_archivo, board, args)
        if new:
            await agent.on_elements(new)
        return result

    @tool("editar_archivo", DESCRIPTIONS["editar_archivo"], SCHEMAS["editar_archivo"])
    async def editar_archivo(args):
        result, proposed = await asyncio.to_thread(tool_editar_archivo, board, args,
                                                   bool(agent.exclude_attachments()))
        if proposed and agent.on_proposals:
            await agent.on_proposals()
        return result

    return [crear_archivo, editar_archivo]

