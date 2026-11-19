"""Agente de diseño (spike FF 3.3, plan §4).

Corre con el Claude Agent SDK y la sesión de Claude Code del usuario (plan R4): sin API key.
Está aislado: no carga ajustes ni servidores MCP del usuario ni del repo
(`setting_sources=[]`, `strict_mcp_config`), no tiene las herramientas propias de Claude
Code (`tools=[]`) y solo ve las de la pizarra.

Las herramientas son funciones normales (`tool_leer_pizarra`, `tool_leer_archivo`,
`tool_crear_postit`, `tool_proponer_cambio`) que se pueden probar sin el SDK. `leer_archivo`
solo lee lo que hay en la pizarra (R5, R36). Las que montan la pizarra (`crear_bloque`,
`conectar`, `poner_plantilla`, `ejecutar_bloque`, `ver_zona`) están en `agent_board_tools`; las de Office
(`crear_archivo`, `editar_archivo`, D176), en `agent_office_tools`;
`proponer_decision`, que solo tiene el agente de un hilo (`decide`), en `agent_threads`. Una escritura que incumple una regla (D19, D20) no se guarda: el
motivo vuelve al agente como error de herramienta para que la corrija.

El prompt de sistema se construye al empezar cada mensaje (`system_prompt`, `agent_prompt`):
con «Animaciones automáticas» (D144) y el `agent.md` de los paquetes cargados (D172). Una
propuesta de parámetros sobre un bloque con vista previa pasa antes por ella (D177,
`check_proposal_preview`).
"""
import asyncio
import json
import os

from pizarra import agent_prompt, api_key, graph, i18n, read_files, validation
from pizarra.validation import ValidationError

AGENT = "agent:design"
FOLDER_LIST = 500           # archivos de una carpeta que se listan como mucho
# Lo más largo que devuelve una herramienta. Claude Code no pasa al agente un resultado grande:
# ~58 kB lo aparta a un fichero que el agente no puede abrir y ~100 kB lo rechaza (prueba de
# punta a punta de FF 4.8). Con margen, y sin llenarle el contexto.
TOOL_CHARS = 25_000
PORT_CHARS = (1500, 600, 0)  # lo que ocupa una salida en leer_pizarra; baja si no cabe entera
BLOCK_PAGE = 20_000         # un tramo de leer_bloque
SHORT_TEXT = 80             # un texto de salida en leer_pizarra, recortado
BOARD_NOTE = ("Las salidas de cada bloque van resumidas como «valor unidad», con las listas "
              "contadas y sin todos los campos si no caben: leer_bloque(block, port) da cada "
              "campo con su etiqueta y las listas enteras. Las cifras de un bloque se citan con "
              "su `cite`. `decisions` son las decisiones que el ingeniero tomó en los hilos "
              "anclados a esos elementos: tenlas en cuenta como memoria del proyecto. "
              "`connectors` dice si Fusion (y cada conector) está disponible ahora; "
              "`my_proposals`, cómo acabaron tus últimas propuestas.")

SYSTEM_PROMPT = """Eres el agente de diseño de una pizarra de ingeniería. Trabajas con un \
ingeniero que organiza su diseño en la pizarra: bloques de cálculo conectados con flechas, \
post-its, croquis y notas.

Reglas que no se pueden saltar:
- Ningún número sin fuente. Si un post-it lleva cifras, cita en `sources` de dónde salen: \
la salida de un bloque (kind "bloque", ref "bloque:<id>", tal como aparece en el `cite` de \
cada bloque que devuelve leer_pizarra), una ficha de componente (kind "ficha") o \
un dato vivo con url y fecha (kind "dato_vivo") o un archivo de la pizarra leído con \
leer_archivo (kind "archivo", ref "archivo:<id de la tarjeta>", `file` si es de una carpeta, y \
`where` con la página, la diapositiva o la hoja y celda del trozo de donde sale). Si es una \
estimación tuya, márcala con estimate=true; nunca la presentes como dato.
- Cita un bloque solo para las salidas que da tal cual. Si haces tú una cuenta sencilla con \
esas salidas (un límite L/500, un porcentaje, un cociente), la fuente es kind "calculo" con \
`formula` (la cuenta escrita con sus valores, p. ej. "L/500 = 600 mm / 500 = 1,2 mm") e \
`inputs` (las refs "bloque:<id>" de donde salen los datos).
- Los resultados de ingeniería los calculan los bloques: no los inventes. Si falta un \
cálculo de verdad, dilo y propón qué bloque haría falta.
- Las designaciones (6061-T6, M6, IP67, ISO 9409-1) no son cifras y no piden fuente.
- Si una herramienta rechaza tu escritura, lee el motivo y corrígela; no la repitas igual.
- No modificas lo que ha hecho el ingeniero. Si quieres cambiar algo suyo (el texto o el \
tipo de un post-it o un texto, los parámetros de un bloque, o borrar algo), usa \
proponer_cambio con el motivo: él lo acepta o lo rechaza. Nunca propones mover, redimensionar \
ni cambiar estilos. Lo tuyo lo cambias con la misma herramienta y se aplica directamente.
- Puedes montar parte del diseño cuando te lo pidan o cuando falte un cálculo: crear_bloque (un tipo de `catalog.blocks` de leer_pizarra), poner_plantilla (una de `catalog.templates`) y conectar ("bloque:salida" a "bloque:entrada", del mismo tipo). Lo que creas es tuyo; los parámetros de un bloque del ingeniero solo los cambias con proponer_cambio.
- ejecutar_bloque ejecuta un bloque (y lo de delante que no está al día) y espera el resultado; no cambia parámetros. Úsalo cuando necesites sus salidas para responder.
- ver_zona te da la imagen de un recuadro o de unos elementos: úsala para lo que no sale en leer_pizarra (croquis, dibujo a mano, cómo están colocadas las cosas), no para leer datos.
- `tinta` de leer_pizarra son los trazos a mano del ingeniero (y los tuyos) con lo que marcan (`apunta`: rodea, señala, subraya, tacha, resalta, toca): lo marcado es de lo que te habla. Para señalar tú algo de la pizarra, marcar; quitar_marca quita solo las tuyas.

Antes de opinar, lee la pizarra con leer_pizarra. Da las salidas de los bloques resumidas: \
para un campo con su etiqueta, una lista entera o lo que no cabe, usa leer_bloque. Sus `files` son los archivos y carpetas \
que el ingeniero ha puesto en ella (datasheets, documentos, hojas de cálculo): léelos con \
leer_archivo cuando hagan falta; no puedes leer nada que no esté en la pizarra. Deja tus observaciones como post-its con \
crear_postit, eligiendo el tipo: nota, sugerencia, riesgo o pregunta. Sé concreto y breve: \
un post-it, una idea.
- Si te piden bloques de un dominio que la pizarra no tiene, puedes hacer un paquete: lee \nguia_paquetes y sigue su flujo (borrador, validar, proponer). Nunca lo instalas tú."""


def system_prompt(settings=None, registry=None):
    """El prompt de sistema de un mensaje (D144, D172): `SYSTEM_PROMPT` con lo de las
    animaciones según `settings` (sin ajustes, activadas) y el `agent.md` de los paquetes
    cargados de `registry` (por defecto, el de la app)."""
    from pizarra import blocks as blocks_mod
    auto = True if settings is None else settings.animations_auto
    return agent_prompt.build(SYSTEM_PROMPT, auto,
                              blocks_mod.REGISTRY if registry is None else registry,
                              "es" if settings is None else settings.language)


def _ok(data):
    return {"content": [{"type": "text", "text": data if isinstance(data, str)
                         else json.dumps(data, ensure_ascii=False)}]}


def _error(message):
    return {"content": [{"type": "text", "text": message}], "is_error": True}


# ------------------------------------------- paquetes del agente (PLAN_PAQUETES §8, P99-P103)
PACK_ID = {"type": "string", "description": "id del paquete (borrador): minúsculas, cifras y _"}
PACK_SCHEMAS = {
    "guia_paquetes": {},
    "crear_paquete": {"type": "object", "properties": {
        "id": PACK_ID, "nombre": {"type": "string"}, "descripcion": {"type": "string"}},
        "required": ["id", "nombre", "descripcion"]},
    "listar_paquete": {"type": "object", "properties": {"id": PACK_ID}, "required": ["id"]},
    "leer_archivo_paquete": {"type": "object", "properties": {
        "id": PACK_ID, "ruta": {"type": "string", "description": "relativa al paquete"}},
        "required": ["id", "ruta"]},
    "escribir_archivo_paquete": {"type": "object", "properties": {
        "id": PACK_ID, "ruta": {"type": "string", "description": "relativa al paquete"},
        "contenido": {"type": "string", "description": "el fichero entero"}},
        "required": ["id", "ruta", "contenido"]},
    "validar_paquete": {"type": "object", "properties": {"id": PACK_ID}, "required": ["id"]},
    "proponer_paquete": {"type": "object", "properties": {"id": PACK_ID}, "required": ["id"]},
    "duplicar_paquete": {"type": "object", "properties": {
        "origen": {"type": "string", "description": "id del paquete instalado"},
        "nuevo": PACK_ID}, "required": ["origen", "nuevo"]},
}
PACK_TOOLS = {
    "guia_paquetes": "La guía para hacer un paquete de bloques: léela antes de crear uno.",
    "crear_paquete": "Crea un borrador de paquete desde la plantilla (un bloque de ejemplo y su test).",
    "listar_paquete": "Los ficheros de un borrador.",
    "leer_archivo_paquete": "Lee un fichero de un borrador.",
    "escribir_archivo_paquete": "Escribe (o sustituye entero) un fichero de un borrador.",
    "validar_paquete": "Valida un borrador: manifiesto, imports, que carga y que sus tests pasan.",
    "proponer_paquete": "Propone al ingeniero un borrador validado: le sale una tarjeta para instalarlo.",
    "duplicar_paquete": "Copia un paquete instalado a un borrador con otro id, para cambiarlo.",
}


def tool_paquete(drafts, name, args):
    """Una herramienta de paquetes (`PACK_TOOLS`). Devuelve `(resultado, propuesta | None)`:
    la propuesta es el resumen que va al chat como tarjeta."""
    from pizarra import agent_packs as ap
    from pizarra import blocks as blocks_mod
    if name == "guia_paquetes":
        return _ok(ap.guide()), None
    if drafts is None:
        return _error("esta pizarra no tiene carpeta de borradores de paquetes"), None
    reg = blocks_mod.REGISTRY
    a = args or {}
    try:
        if name == "crear_paquete":
            return _ok({"ficheros": ap.create(drafts, a.get("id"), a.get("nombre"),
                                              a.get("descripcion", ""))}), None
        if name == "listar_paquete":
            return _ok(ap.list_files(drafts, a.get("id"))), None
        if name == "leer_archivo_paquete":
            return _ok(ap.read(drafts, a.get("id"), a.get("ruta"))), None
        if name == "escribir_archivo_paquete":
            return _ok(ap.write(drafts, a.get("id"), a.get("ruta"), a.get("contenido"))), None
        if name == "duplicar_paquete":
            return _ok(ap.duplicate(drafts, reg.origins, a.get("origen"), a.get("nuevo"))), None
        if name == "validar_paquete":
            rep = ap.validate(drafts, a.get("id"), reg.origins, host=reg.host,
                              validated=reg.validated)
            return (_ok(rep) if rep["ok"] else _error(json.dumps(rep, ensure_ascii=False))), None
        if name == "proponer_paquete":
            summary = ap.propose(drafts, a.get("id"))
            return _ok({"propuesto": summary["id"], "nota": "el ingeniero ve una tarjeta con "
                        "Instalar; tú no lo instalas"}), summary
    except ap.DraftError as exc:
        return _error(str(exc)), None
    return _error(f"herramienta desconocida: {name}"), None


def _short(field):
    """Un campo de salida como «valor unidad»; una lista o una tabla, solo su tamaño."""
    v = field.get("value") if isinstance(field, dict) else field
    unit = (field.get("unit") or "") if isinstance(field, dict) else ""
    if isinstance(v, list):
        return f"lista de {len(v)}"
    if isinstance(v, dict):
        return f"{len(v)} campos"
    if isinstance(v, bool):
        s = "sí" if v else "no"
    elif isinstance(v, float):
        s = f"{v:.6g}"
    elif v is None:
        s = "—"
    else:
        s = str(v)
        s = s if len(s) <= SHORT_TEXT else s[:SHORT_TEXT - 1] + "…"
    return f"{s} {unit}".strip()


def _digest(outputs, cap):
    """Las salidas de un bloque para `leer_pizarra`: hasta `cap` caracteres por salida, en el
    orden del bloque; lo que no cabe se cuenta para pedirlo con `leer_bloque`."""
    out = {}
    for port, fields in (outputs or {}).items():
        if not isinstance(fields, dict):
            out[port] = _short(fields)
            continue
        shown, size = {}, 0
        for key, field in fields.items():
            s = _short(field)
            n = len(key) + len(s) + 6
            if size + n > cap:
                break
            shown[key] = s
            size += n
        if len(shown) < len(fields):
            shown["…"] = f"{len(fields) - len(shown)} campos más: leer_bloque"
        out[port] = shown
    return out


MY_PROPOSALS = 10            # las últimas propuestas del agente que ve leer_pizarra


def connectors_now(board):
    """{conector: "disponible" | "no disponible"} de los que piden los bloques cargados (Fusion
    abierto o no): el agente lo decía de memoria (prueba de punta a punta de FF 4.6)."""
    known = {c for kind in board.registry for c in board.registry[kind].requires}
    return {c: "disponible" if c in board.connectors else "no disponible" for c in sorted(known)}


def my_proposals(board):
    """Las últimas propuestas del agente con su estado (pendiente, aceptada, rechazada): daba
    por pendiente una que el ingeniero ya había aceptado (prueba de punta a punta de FF 4.6)."""
    mine = [p for p in board.proposals if str(p.get("author", "")).startswith("agent:")]
    return [{"id": p["id"], "target": p["target"], "state": p["state"], "reason": p.get("reason")}
            for p in mine[-MY_PROPOSALS:]]


def tool_leer_pizarra(board, _args):
    """La pizarra con las salidas resumidas (FF 4.8, prueba de punta a punta): entera, el brazo
    pasaba de 100 000 caracteres y Claude Code no se la daba al agente. Aprieta hasta caber en
    `TOOL_CHARS`; lo de cada bloque, entero, con `leer_bloque`. Lleva las decisiones de los
    hilos con sus anclas (D165), nunca lo hablado en ellos."""
    from pizarra.agent_board_tools import catalog
    from pizarra.agent_threads import decisions
    full = {**board.summary(), "decisions": decisions(board), "catalog": catalog(board.registry),
            "connectors": connectors_now(board), "my_proposals": my_proposals(board)}
    for cap in PORT_CHARS:
        out = {**full, "blocks": [
            {**{k: b[k] for k in ("id", "type", "status", "params")}, "cite": f"bloque:{b['id']}",
             "outputs": _digest(b["outputs"], cap)} for b in full["blocks"]],
            "note": BOARD_NOTE}
        text = json.dumps(out, ensure_ascii=False)
        if len(text) <= TOOL_CHARS:
            break
    return _ok(text)


def tool_leer_bloque(board, args):
    """Las salidas de un bloque enteras: cada campo con su valor, unidad y etiqueta, y las listas
    completas, por tramos de `BLOCK_PAGE` caracteres. `port` se queda con una salida."""
    bid, port = args.get("block"), args.get("port")
    blk = next((b for b in board.summary()["blocks"] if b["id"] == bid), None)
    if blk is None:
        return _error(f"no hay ningún bloque {bid!r}: usa el `id` que devuelve leer_pizarra")
    outs = blk["outputs"] or {}
    if not outs:
        return _error(f"el bloque {bid!r} no tiene resultados: hay que ejecutarlo")
    if port and port not in outs:
        return _error(f"el bloque {bid!r} no tiene la salida {port!r}; tiene: {', '.join(outs)}")
    items = [(p, k, {kk: vv for kk, vv in f.items() if kk != "source"} if isinstance(f, dict) else f)
             for p in ([port] if port else outs) for k, f in (outs[p] or {}).items()]
    page, size, i = {}, 0, max(0, int(args.get("from") or 0))
    while i < len(items):
        p, k, f = items[i]
        n = len(json.dumps({k: f}, ensure_ascii=False))
        if page and size + n > BLOCK_PAGE:
            break
        page.setdefault(p, {})[k] = f
        size += n
        i += 1
    out = {"block": bid, "type": blk["type"], "status": blk["status"], "outputs": page,
           "cite_as": {"kind": "bloque", "ref": f"bloque:{bid}"}}
    if i < len(items):
        out["next"] = i
        out["note"] = (f"quedan {len(items) - i} campos: vuelve a llamar con from={i}"
                       + (f" y port={port!r}" if port else ""))
    return _ok(out)


# Lo que recibe el agente si el proyecto tiene *Excluir adjuntos* (D169).
ATTACHMENTS_EXCLUDED = ("No se puede leer: el ingeniero ha marcado «Excluir adjuntos» en este "
                        "proyecto, así que ningún archivo ni imagen pegada sale al agente. "
                        "Trabaja con lo que hay escrito en la pizarra y, si hace falta un "
                        "archivo, díselo.")


def tool_leer_archivo(board, args, excluded=False):
    """Lee un archivo de la pizarra (R36): el de una tarjeta de archivo o uno de lo marcado de
    una carpeta. Sin `file`, en una carpeta, da la lista de lo que entra. Nunca otra ruta (R5).
    Con `excluded` (*Excluir adjuntos*, D169) no lee nada, tampoco la lista de una carpeta.
    Bloquea mientras lee: el SDK la llama en un hilo."""
    if excluded:
        return _error(ATTACHMENTS_EXCLUDED)
    card = args.get("card")
    try:
        el = board.card(card)
        if el["customData"]["kind"] == "folder" and not args.get("file"):
            rels = board.folder_files(card)
            return _ok({"card": card, "folder": board.card_path(el).name, "files": [
                {"file": r, "readable": read_files.readable(r)} for r in rels[:FOLDER_LIST]],
                "total": len(rels),
                "note": "léelos con leer_archivo(card, file); los que no son legibles "
                        f"(readable=false) no se leen: solo {read_files.KNOWN}"})
        path = board.readable_file(card, args.get("file"))
        chunks, nxt, count = read_files.read_part(path, args.get("from") or 0,
                                                  pages=args.get("pages") or None)
    except (ValidationError, read_files.ReadError) as exc:
        return _error(f"No se puede leer: {exc}")
    out = {"card": card, "file": args.get("file") or path.name,
           "chunks": [c.as_dict() for c in chunks],
           **({"pages": count} if path.suffix.lower() == ".pdf" else {}),
           "cite_as": {"kind": "archivo", "ref": f"archivo:{card}",
                       **({"file": args["file"]} if args.get("file") else {}),
                       "where": "<el where del trozo>"}}
    if nxt is not None:
        out["next"] = nxt
        out["note"] = (f"queda más: vuelve a llamar con from={nxt} (y los mismos `pages`, si "
                       "los diste) para seguir; en un PDF largo, `pages` salta a lo que digan "
                       "su índice o sus títulos")
    return _ok(out)


# Lo que recibe el agente si pone una animación sin que se la pidan con el ajuste apagado (D144).
ANIMATION_NOT_ASKED = ("Rechazado: el ingeniero ha desactivado las animaciones automáticas. Crea "
                       "el post-it sin `animacion`; solo lleva una si te la pide en su mensaje, "
                       "y entonces con pedida_por_usuario=true.")


def tool_crear_postit(board, args, auto_animations=True):
    """Devuelve (resultado para el agente, elementos nuevos o []). Con `animacion` (D143,
    D175) el post-it la lleva encima de su texto; con `auto_animations` apagado (D144), solo si
    va `pedida_por_usuario`. Un rechazo no crea nada: ni el post-it ni el archivo."""
    animation = args.get("animacion")
    if animation is not None and not auto_animations \
            and args.get("pedida_por_usuario") is not True:
        return _error(ANIMATION_NOT_ASKED), []
    postit = {
        "text": args.get("text", ""),
        "kind": args.get("kind", "nota"),
        "author": AGENT,
        "sources": args.get("sources") or [],
        "estimate": bool(args.get("estimate", False)),
        "anchor": args.get("anchor"),
    }
    try:
        new = board.agent_add_postit(postit, animation=animation)
    except ValidationError as exc:
        return _error(f"Rechazado: {exc}"), []
    board.save()
    return _ok({"creado": new[0]["id"]}), new


# Lo que tarda como mucho la vista previa de una propuesta (D177): pasado, se guarda sin ella.
PREVIEW_SECONDS = 20


def preview_errors(result):
    """Los fallos que da una vista previa (D177), con la convención de `pack_guide.md`: el
    texto de cada `error` y los motivos de cada `errores…` (`{clave: motivo}` o una lista), a
    cualquier profundidad de sus objetos. Un `aviso` no es un fallo."""
    out = []
    if isinstance(result, dict):
        for k, v in result.items():
            plural = isinstance(k, str) and k.startswith("errores")
            if k == "error" and isinstance(v, str) and v.strip():
                out.append(v.strip())
            elif plural and isinstance(v, dict):
                out += [f"{kk}: {vv}" for kk, vv in v.items() if vv]
            elif plural and isinstance(v, list):
                out += [str(vv) for vv in v if vv]
            elif isinstance(v, dict):
                out += preview_errors(v)
    return out


def proposal_preview_job(board, args):
    """La vista previa que tiene que pasar `proponer_cambio` antes de dejar su propuesta
    (D177), o None si no hace falta: solo con `change.params` sobre un bloque del ingeniero
    que tiene vista previa. Se lee ya (el bloque y sus entradas, con los parámetros
    propuestos); la función que devuelve corre en un hilo."""
    change, target = args.get("change"), args.get("target")
    params = change.get("params") if isinstance(change, dict) else None
    if not isinstance(params, dict) or not params:
        return None
    el = graph.blocks_in(board.elements, board.registry).get(target)
    if el is None or validation.element_author(el) == AGENT:
        return None                     # no es un bloque (lo dice agent_propose) o es suyo
    btype = board.registry.get(el["customData"]["blockType"])
    if btype is None or btype.preview is None:
        return None
    return board.preview_job(target, params)


async def check_proposal_preview(board, args, seconds=PREVIEW_SECONDS):
    """`(motivo del fallo | None, nota | None)` de la vista previa de una propuesta (D177).
    Con fallo, la propuesta no se guarda; si tarda más de `seconds`, se guarda con la nota."""
    try:
        job = proposal_preview_job(board, args)
    except ValidationError:
        return None, None               # el bloque no está bien: lo dirá agent_propose
    if job is None:
        return None, None
    try:
        result = await asyncio.wait_for(asyncio.to_thread(job), seconds)
    except asyncio.TimeoutError:
        return None, (f"sin validar: la vista previa del bloque tardó más de {seconds} s; el "
                      "ingeniero la verá al abrir el bloque")
    except ValidationError as exc:
        return str(exc), None
    problems = preview_errors(result)
    return ("; ".join(problems) if problems else None), None


async def tool_proponer_cambio_validado(board, args, seconds=PREVIEW_SECONDS):
    """`tool_proponer_cambio` con la vista previa delante (D177): si con los parámetros
    propuestos da error, vuelve al agente con el motivo y no queda propuesta."""
    problem, note = await check_proposal_preview(board, args, seconds)
    if problem:
        return _error("Rechazado: con esos parámetros la vista previa del bloque da error, así "
                      f"que no queda propuesta. Corrígelo y vuelve a proponer: {problem}"), [], False
    result, changed, proposed = tool_proponer_cambio(board, args)
    if note and proposed:
        data = json.loads(result["content"][0]["text"])
        result = _ok({**data, "vista_previa": note})
    return result, changed, proposed


def tool_proponer_cambio(board, args):
    """Devuelve (resultado para el agente, elementos cambiados, si hay propuesta nueva)."""
    try:
        kind, out = board.agent_propose(AGENT, args.get("target"), args.get("change"),
                                        args.get("reason"), args.get("sources"),
                                        bool(args.get("estimate", False)))
    except ValidationError as exc:
        return _error(f"Rechazado: {exc}"), [], False
    board.save()
    if kind == "aplicado":
        return _ok({"aplicado": args.get("target"),
                    "nota": "es tuyo: se ha cambiado directamente"}), [out] if out else [], False
    return _ok({"propuesta": out["id"], "estado": "pendiente",
                "nota": "el ingeniero la verá en la pizarra y la aceptará o la rechazará"}), [], True


PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "description": "id del elemento (de leer_pizarra)"},
        "change": {
            "type": "object",
            "description": "solo contenido o borrar: text (post-it o texto), postitKind "
                           "(post-it), params (bloque, {nombre: valor}) o delete=true (solo)",
            "properties": {
                "text": {"type": "string"},
                "postitKind": {"type": "string", "enum": ["nota", "sugerencia", "riesgo", "pregunta"]},
                "params": {"type": "object"},
                "delete": {"type": "boolean"},
            },
        },
        "reason": {"type": "string", "description": "por qué, en una frase"},
        "sources": {"type": "array", "items": {"type": "object"},
                    "description": "fuentes de las cifras del texto propuesto (como en crear_postit)"},
        "estimate": {"type": "boolean"},
    },
    "required": ["target", "change", "reason"],
}


POSTIT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Texto del post-it, breve"},
        "kind": {"type": "string", "enum": ["nota", "sugerencia", "riesgo", "pregunta"]},
        "sources": {
            "type": "array",
            "description": "Fuentes de las cifras del texto (obligatorio si hay cifras)",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["bloque", "ficha", "dato_vivo", "calculo", "archivo"]},
                    "ref": {"type": "string",
                            "description": "p. ej. bloque:<id> o archivo:<id> (no hace falta "
                                           "en un calculo)"},
                    "file": {"type": "string",
                             "description": "solo archivo de una carpeta: su ruta relativa"},
                    "where": {"type": "string",
                              "description": "solo archivo: el `where` del trozo (página 3, "
                                             "Hoja1!B4...)"},
                    "url": {"type": "string"},
                    "date": {"type": "string"},
                    "formula": {"type": "string",
                                "description": "solo calculo: la cuenta con sus valores"},
                    "inputs": {"type": "array", "items": {"type": "string"},
                               "description": "solo calculo: refs bloque:<id> de los datos"},
                },
                "required": ["kind"],
            },
        },
        "estimate": {"type": "boolean",
                     "description": "true si las cifras son una estimación tuya sin verificar"},
        "anchor": {"type": "string", "description": "id del elemento al que se refiere"},
        "animacion": {"type": "string",
                      "description": "HTML autocontenido de una animación que va encima del "
                                     "texto (hasta 256 KB, sin red); ilustra, no es fuente"},
        "pedida_por_usuario": {"type": "boolean",
                               "description": "true si el ingeniero ha pedido la animación "
                                              "en su mensaje"},
    },
    "required": ["text", "kind"],
}


READ_SCHEMA = {
    "type": "object",
    "properties": {
        "card": {"type": "string", "description": "id de la tarjeta (los `files` de leer_pizarra)"},
        "file": {"type": "string", "description": "solo en una carpeta: la ruta relativa de uno "
                                                  "de sus archivos; sin ella, la lista"},
        "from": {"type": "integer", "description": "el `next` de la llamada anterior, para seguir"},
        "pages": {"type": "string", "description": "solo en un PDF: una página o un rango, "
                                                   "como '7' o '45-50'"},
    },
    "required": ["card"],
}

BLOCK_SCHEMA = {
    "type": "object",
    "properties": {
        "block": {"type": "string", "description": "id del bloque (de leer_pizarra)"},
        "port": {"type": "string", "description": "solo esa salida; sin él, todas"},
        "from": {"type": "integer", "description": "el `next` de la llamada anterior, para seguir"},
    },
    "required": ["block"],
}


class DesignAgent:
    """Una conversación con el agente de diseño sobre una pizarra."""

    def __init__(self, board, on_elements, cli_path=None, model=None, on_proposals=None,
                 drafts=None, run_block=None, request_zone=None, settings=None):
        self.board = board
        # Los ajustes de la app (`settings.Settings`): se leen al empezar cada mensaje (D144),
        # así que cambiarlos vale desde el siguiente. Sin ellos, los de por defecto.
        self.settings = settings
        self.auto_animations = True             # el del mensaje en curso
        self.on_elements = on_elements          # async (elementos) -> None: los pinta
        self.on_proposals = on_proposals        # async () -> None: avisa de una propuesta nueva
        self.cli_path = cli_path
        self.model = model or os.environ.get("PIZARRA_MODEL", "opus")
        self.session_id = None                  # se reanuda la conversación entre mensajes
        self.drafts = drafts                    # carpeta de borradores de paquetes (P99)
        # Del servidor (`agent_board_tools`): async (bloque) -> resumen de la ejecución, y
        # async (petición) -> PNG en base64 de una ventana abierta (D171). Sin ellos, error.
        self.run_block = run_block
        self.request_zone = request_zone
        self._emit = None                       # el de la pregunta en curso: la tarjeta (P102)
        # Lo que pone la conversación (`agent_chat`) antes de cada mensaje (D168, D169):
        self.max_budget_usd = None              # lo que queda del tope del proyecto
        self.exclude_attachments = lambda: False    # *Excluir adjuntos*: se mira en cada lectura
        # y en cada `ver_zona` (sin las imágenes pegadas)
        # Solo en un hilo (`agent_threads`, D167): async (args) -> resultado de
        # `proponer_decision`. Con él, el agente tiene esa herramienta y sabe que está en un hilo.
        self.decide = None
        self._client = None                     # el del mensaje en curso, para *Parar*

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

        board, on_elements, on_proposals = self.board, self.on_elements, self.on_proposals
        # Al empezar el mensaje: el prompt y la red de seguridad de `crear_postit` usan el mismo
        auto = self.auto_animations = (self.settings is None or self.settings.animations_auto)

        @tool("leer_pizarra", "Lee la pizarra: bloques con parámetros, estado, salidas "
              "resumidas y cómo citarlos (`cite`), post-its, textos y archivos.", {})
        async def leer(args):
            return tool_leer_pizarra(board, args)

        @tool("leer_bloque", "Las salidas de un bloque enteras: cada campo con su valor, unidad "
              "y etiqueta, y las listas completas, por tramos.", BLOCK_SCHEMA)
        async def leer_blq(args):
            return tool_leer_bloque(board, args)

        @tool("crear_postit", "Crea un post-it en la pizarra. Si el texto lleva cifras, "
              "`sources` es obligatorio (o estimate=true).", POSTIT_SCHEMA)
        async def crear(args):
            result, new = tool_crear_postit(board, args, auto)
            if new:
                await on_elements(new)
            return result

        @tool("proponer_cambio", "Propone cambiar el contenido de un elemento del ingeniero "
              "(texto, tipo, parámetros) o borrarlo, con el motivo. No lo toca: él decide. "
              "Sobre algo tuyo, lo cambia directamente.", PROPOSAL_SCHEMA)
        async def proponer(args):
            result, changed, proposed = await tool_proponer_cambio_validado(board, args)
            if changed:
                await on_elements(changed)
            if proposed and on_proposals:
                await on_proposals()
            return result

        agent = self

        @tool("leer_archivo", "Lee un archivo de la pizarra (PDF, Word, Excel, PowerPoint o "
              "texto) en trozos con su página, diapositiva u hoja y celda (`where`), para "
              "citarlos. En una carpeta, sin `file`, da la lista de lo que entra.", READ_SCHEMA)
        async def leer_arch(args):
            return await asyncio.to_thread(tool_leer_archivo, board, args,
                                           bool(agent.exclude_attachments()))

        drafts = self.drafts

        def pack_tool(name):
            @tool(name, PACK_TOOLS[name], PACK_SCHEMAS[name])
            async def run(args):
                result, proposal = await asyncio.to_thread(tool_paquete, drafts, name, args)
                if proposal is not None and agent._emit is not None:
                    await agent._emit({"kind": "pack_proposal", "pack": proposal})
                return result
            return run

        pack_tools = [pack_tool(n) for n in PACK_TOOLS]
        # Con las animaciones automáticas apagadas, la guía no va en el prompt: se pide (D144)
        guide_tools = []
        if not auto:
            @tool("guia_animacion", agent_prompt.GUIDE_TOOL, {})
            async def guia_anim(_args):
                return _ok(agent_prompt.ANIMATION_GUIDE)
            guide_tools = [guia_anim]
        from pizarra import agent_board_tools, agent_office_tools, agent_threads
        board_tools = agent_board_tools.sdk_tools(self, tool) + agent_office_tools.sdk_tools(self, tool)
        thread_tools, in_thread = [], self.decide is not None
        if in_thread:                   # solo dentro de un hilo (D167)
            @tool("proponer_decision", agent_threads.DECISION_TOOL, agent_threads.DECISION_SCHEMA)
            async def decidir(args):
                return await agent.decide(args)
            thread_tools = [decidir]
        server = create_sdk_mcp_server("pizarra", "0.0.1",
                                       [leer, leer_blq, leer_arch, crear, proponer, *board_tools,
                                        *pack_tools, *guide_tools, *thread_tools])
        return ClaudeAgentOptions(
            system_prompt=system_prompt(self.settings, board.registry)
            + ("\n\n" + agent_threads.THREAD_PROMPT if in_thread else ""),
            tools=[],
            mcp_servers={"pizarra": server},
            allowed_tools=["mcp__pizarra__leer_pizarra", "mcp__pizarra__leer_bloque",
                           "mcp__pizarra__leer_archivo",
                           "mcp__pizarra__crear_postit", "mcp__pizarra__proponer_cambio",
                           *(f"mcp__pizarra__{n}" for n in agent_board_tools.NAMES),
                           *(f"mcp__pizarra__{n}" for n in agent_office_tools.NAMES),
                           *(f"mcp__pizarra__{n}" for n in PACK_TOOLS),
                           *([] if auto else ["mcp__pizarra__guia_animacion"]),
                           *(["mcp__pizarra__proponer_decision"] if in_thread else [])],
            strict_mcp_config=True,
            setting_sources=[],
            cwd=str(board.dir),
            cli_path=self.cli_path,
            env=api_key.agent_env(self.settings),   # la clave, solo al proceso del agente (O9)
            model=self.model,
            resume=self.session_id,
            max_turns=40,               # hacer un paquete lleva más vueltas (P99)
            max_budget_usd=self.max_budget_usd,     # el SDK corta dentro del mensaje (D168)
        )

    async def interrupt(self):
        """*Parar*: corta el mensaje en curso; lo que ya hizo se queda. `RuntimeError` si aún
        no hay con qué hablar (el CLI no ha arrancado): entonces se cancela la tarea."""
        if self._client is None:
            raise RuntimeError("el agente aún no ha arrancado")
        await self._client.interrupt()

    async def ask(self, message, emit):
        """Envía un mensaje y va emitiendo eventos {kind: text|tool|tool_result|done|error}.
        `done` lleva lo que da el SDK del consumo (`usage`, `cost_usd`) y cómo acabó
        (`subtype`, `terminal_reason`); `agent_chat` lo suma y lo traduce para el chat."""
        from claude_agent_sdk import (AssistantMessage, ClaudeSDKClient, ResultMessage,
                                      TextBlock, ToolResultBlock, ToolUseBlock, UserMessage)

        self._emit = emit
        async with ClaudeSDKClient(options=self._options()) as client:
            self._client = client
            try:
                await client.query(message)
                async for m in client.receive_response():
                    if isinstance(m, AssistantMessage):
                        for b in m.content:
                            if isinstance(b, TextBlock) and b.text.strip():
                                await emit({"kind": "text", "text": b.text})
                            elif isinstance(b, ToolUseBlock):
                                await emit({"kind": "tool", "name": b.name.split("__")[-1],
                                            "input": b.input})
                    elif isinstance(m, UserMessage) and isinstance(m.content, list):
                        for b in m.content:
                            if isinstance(b, ToolResultBlock):
                                text = b.content if isinstance(b.content, str) else "".join(
                                    c.get("text", "") for c in (b.content or []))
                                await emit({"kind": "tool_result", "error": bool(b.is_error),
                                            "text": text[:400]})
                    elif isinstance(m, ResultMessage):
                        self.session_id = m.session_id
                        await emit({"kind": "done", "turns": m.num_turns,
                                    "seconds": round((m.duration_ms or 0) / 1000, 1),
                                    "subtype": m.subtype, "terminal_reason": m.terminal_reason,
                                    "usage": m.usage, "cost_usd": m.total_cost_usd})
            finally:
                self._client = None
