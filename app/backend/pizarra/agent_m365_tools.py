"""Herramientas de Microsoft 365 del agente (docs/PLAN_M365.md §7: M5, M10, M11).

- `buscar_microsoft365 {fuente, texto?, carpeta?}`: archivos de OneDrive (por nombre y
  contenido) o correos (los últimos de una carpeta o los que coinciden con `texto`).
- `traer_de_microsoft365 {fuente, id, drive_id?, adjuntos?}`: un resultado a una tarjeta de la
  pizarra, del agente, como los botones del panel (M6, M10). Luego se lee con `leer_archivo`.
- `redactar_correo {para, cc?, asunto, cuerpo, adjuntos?}`: un **borrador** en *Borradores* con
  tarjetas de archivo de la pizarra adjuntas. **No se envía**: lo envía el usuario desde Outlook
  (M5), y la app no tiene el permiso para enviar.

Ninguna envía, borra ni sube nada a la nube (M9, M11). Sin sesión de Microsoft, cada una dice
cómo iniciarla sin llamar a Graph. Con *Excluir adjuntos* (D169), `buscar_microsoft365` no da
el principio de los correos.
"""
from pizarra import m365_files, m365_mail
from pizarra.agent import AGENT, _error, _ok
from pizarra.m365_api import graph_for, message
from pizarra.m365_auth import M365Error, NotConfigured, NotSignedIn
from pizarra.validation import ValidationError

_AUTH = None                    # la cuenta de la app (`use`, desde el servidor)
RESULTS_MAX = 20

FUENTE = {"type": "string", "enum": ["archivos", "correo"],
          "description": "archivos: OneDrive (y lo compartido contigo); correo: Outlook"}
SCHEMAS = {
    "buscar_microsoft365": {"type": "object", "properties": {
        "fuente": FUENTE,
        "texto": {"type": "string", "description": "qué buscar; en correo, sin texto da los "
                                                   "últimos de la carpeta"},
        "carpeta": {"type": "string", "description": "correo: id de la carpeta (por defecto, "
                                                     "inbox)"}},
        "required": ["fuente"]},
    "traer_de_microsoft365": {"type": "object", "properties": {
        "fuente": FUENTE,
        "id": {"type": "string", "description": "el `id` que dio buscar_microsoft365"},
        "drive_id": {"type": "string", "description": "archivos: el `drive_id` del resultado"},
        "adjuntos": {"type": "boolean", "description": "correo: traer también sus adjuntos"}},
        "required": ["fuente", "id"]},
    "redactar_correo": {"type": "object", "properties": {
        "para": {"type": "array", "items": {"type": "string"}},
        "cc": {"type": "array", "items": {"type": "string"}},
        "asunto": {"type": "string"},
        "cuerpo": {"type": "string", "description": "texto plano; los párrafos, separados por "
                                                   "una línea en blanco"},
        "adjuntos": {"type": "array", "items": {"type": "string"},
                     "description": "ids de tarjetas de archivo de la pizarra"}},
        "required": ["para", "asunto", "cuerpo"]},
}
DESCRIPTIONS = {
    "buscar_microsoft365": "Busca en el OneDrive o en el correo de Outlook del ingeniero. "
                           "Devuelve ids para traer_de_microsoft365.",
    "traer_de_microsoft365": "Trae a la pizarra un archivo de OneDrive o un correo (como .eml, y "
                             "con adjuntos=true también sus adjuntos) como tarjetas de archivo. "
                             "Después léelo con leer_archivo.",
    "redactar_correo": "Deja un BORRADOR en la carpeta Borradores de Outlook, con tarjetas de "
                       "archivo de la pizarra adjuntas. No lo envía ni puede enviarlo: el "
                       "ingeniero lo revisa y lo envía desde Outlook. Da al ingeniero el enlace "
                       "`web_link` que devuelve para abrirlo.",
}
NAMES = tuple(SCHEMAS)


def use(auth):
    global _AUTH
    _AUTH = auth


def _graph():
    """El cliente de Graph, o el texto de por qué no hay (sin llamar a Graph)."""
    if _AUTH is None or not _AUTH.configured():
        return None, message(NotConfigured())
    if _AUTH.account() is None:
        return None, message(NotSignedIn())
    return graph_for(_AUTH), None


def tool_buscar(board, args, excluded=False, graph=None):
    del board
    if graph is None:
        graph, why = _graph()
        if graph is None:
            return _error(why)
    fuente, texto = args.get("fuente"), str(args.get("texto") or "").strip()
    try:
        if fuente == "archivos":
            if not texto:
                return _error("en archivos hace falta `texto`")
            items = [{k: v[k] for k in ("id", "drive_id", "name", "folder", "size", "modified")}
                     for v in m365_files.search(graph, texto)[:RESULTS_MAX]]
        elif fuente == "correo":
            items = m365_mail.messages(graph, args.get("carpeta") or "inbox", texto)[:RESULTS_MAX]
            for m in items:
                m.pop("web_link", None)
                if excluded:
                    m.pop("preview", None)
        else:
            return _error("`fuente` es archivos o correo")
    except M365Error as exc:
        return _error(message(exc))
    return _ok({"resultados": items, "nota": "trae uno con traer_de_microsoft365"})


def tool_traer(board, args, graph=None):
    """Devuelve (resultado, tarjetas nuevas)."""
    if graph is None:
        graph, why = _graph()
        if graph is None:
            return _error(why), []
    fuente, item = args.get("fuente"), str(args.get("id") or "")
    try:
        if fuente == "archivos":
            el, new = m365_files.bring(board, graph, str(args.get("drive_id") or ""), item,
                                       author=AGENT)
            news, notes = ([el] if new else []), []
            cards = [el]
        elif fuente == "correo":
            news, notes, mail = m365_mail.bring_message(board, graph, item,
                                                        bool(args.get("adjuntos")), author=AGENT)
            cards = [mail] + [e for e in news if e["id"] != mail["id"]]
        else:
            return _error("`fuente` es archivos o correo"), []
    except M365Error as exc:
        return _error(message(exc)), []
    except (ValidationError, OSError) as exc:
        return _error(f"Rechazado: {exc}"), []
    return _ok({"tarjetas": [{"id": e["id"], "archivo": board.card_path(e).name} for e in cards],
                "ya_estaba": not news, "avisos": notes,
                "nota": "léelas con leer_archivo"}), news


def tool_redactar(board, args, graph=None):
    if graph is None:
        graph, why = _graph()
        if graph is None:
            return _error(why)
    try:
        paths = []
        for cid in args.get("adjuntos") or []:
            el = board.card(cid)
            if el["customData"].get("kind") != "file":
                raise ValidationError(f"{cid!r} es una carpeta: adjunta archivos")
            paths.append(board.readable_file(cid))
        got = m365_mail.draft(graph, args.get("para"), args.get("cc"), args.get("asunto"),
                              args.get("cuerpo"), paths)
    except M365Error as exc:
        return _error(message(exc))
    except (ValidationError, OSError) as exc:
        return _error(f"Rechazado: {exc}")
    return _ok({"borrador": got["id"], "web_link": got["web_link"],
                "nota": "está en Borradores, sin enviar: da al ingeniero el enlace para "
                        "abrirlo en Outlook, revisarlo y enviarlo"})


def sdk_tools(agent, tool):
    """Las tres herramientas para el servidor MCP del agente (`DesignAgent._options`). Llaman a
    Graph: corren en un hilo."""
    import asyncio
    board = agent.board

    @tool("buscar_microsoft365", DESCRIPTIONS["buscar_microsoft365"], SCHEMAS["buscar_microsoft365"])
    async def buscar(args):
        return await asyncio.to_thread(tool_buscar, board, args, bool(agent.exclude_attachments()))

    @tool("traer_de_microsoft365", DESCRIPTIONS["traer_de_microsoft365"],
          SCHEMAS["traer_de_microsoft365"])
    async def traer(args):
        result, new = await asyncio.to_thread(tool_traer, board, args)
        if new:
            await agent.on_elements(new)
        return result

    @tool("redactar_correo", DESCRIPTIONS["redactar_correo"], SCHEMAS["redactar_correo"])
    async def redactar(args):
        return await asyncio.to_thread(tool_redactar, board, args)

    return [buscar, traer, redactar]
