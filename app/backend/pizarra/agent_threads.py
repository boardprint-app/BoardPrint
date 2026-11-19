"""Los hilos anclados (FF 4.6 paso 3; plan §4, D57, D165-D167).

Un hilo es una conversación aparte con el agente de diseño, anclada a uno o varios elementos
de la pizarra por su `id` (D166: no es un elemento de Excalidraw, sino una capa encima). Vive
en `agent/` del proyecto, por el almacenamiento, y las versiones no lo copian (D164):

- `threads.json`: `{"schema": 1, "threads": [hilo, ...]}`, con cada hilo
      {id, title, anchors: [id, ...], state: abierto | decidido | en_revision,
       decision: {text, sources, estimate, at} | null,
       proposed: {text, sources, estimate, at} | null,     lo último de `proponer_decision`
       layout: {size: min | window | full, x, y, w, h}, messages, created, updated}
  `messages` cuenta las preguntas y respuestas (eventos `user` y `text`); `updated` cambia
  con lo que se habla y se decide, no al mover la ventana. Al leerlo salen además
  `missing` (las anclas que ya no están en la escena) y `sin_anclaje` (ninguna está), que se
  calculan contra la escena y nunca se escriben: un hilo cuyas anclas se borran no se pierde
  y vuelve a estar anclado si se deshace el borrado.
- `threads/<id>.jsonl`: los eventos del hilo, como `chat.jsonl` (`user`, `text`, `tool`,
  `tool_result`, `done`, `error`, `stopped`) más `decision_proposal`, `closed` y `reopened`.

**Una sesión del SDK por hilo** (D165): `"hilo:<id>"` en `sessions.json`; nunca reanuda la
del chat ni la de otro hilo. El mensaje que empieza una sesión (el primero, o el siguiente si
el CLI la perdió) lleva delante lo que son las anclas, con el mismo tope que las herramientas.
El consumo va al agente de diseño por diferencia con su sesión (D168), y el tope, la
privacidad, *Parar* (`agent_stop`) y la regla de una pregunta a la vez por proyecto, contando
chat e hilos, son los de `agent_chat`.

**Cerrar** (D167): *Cerrar con decisión* (`thread_close_request`) pide al agente, con un
mensaje fijo, que llame a `proponer_decision`, que solo existe dentro de un hilo y no cierra
nada: deja la propuesta en el hilo. El usuario la edita y la guarda (`thread_close`). La
decisión pasa por la regla de los números (D19) en los dos casos: con cifras y sin fuentes ni
`estimate`, se rechaza con el motivo (al agente, como error de herramienta; al usuario, como
`error`), y la interfaz ofrece marcarla como estimación. Cerrar la deja `decidido` y
minimiza el hilo; reabrir (`thread_reopen`) la deja `en_revision` y conserva la decisión
hasta que se vuelve a cerrar. En un hilo `decidido` no se pregunta: hay que reabrirlo.

El chat principal nunca ve lo hablado en un hilo, solo sus decisiones, que `leer_pizarra`
devuelve con sus anclas (`decisions`).
"""
import json
import logging
import math
import uuid

from pizarra import i18n, ink, scene, validation
from pizarra.agent import PORT_CHARS, TOOL_CHARS, _digest, _error, _ok
from pizarra.agent_chat import HISTORY_MAX, Conversation
from pizarra.storage import StorageError
from pizarra.validation import ValidationError

log = logging.getLogger(__name__)

THREAD_KEY = "hilo:"           # la conversación de un hilo en sessions.json: "hilo:<id>"
STATES = ("abierto", "decidido", "en_revision")
SIZES = ("min", "window", "full")
MIN_SIZE = (260, 170)          # la mini ventana más pequeña que se lee (D60, el prototipo)
MAX_SIZE = 20_000              # px: nada razonable es más grande; más, se recorta
DEFAULT_LAYOUT = {"size": "window", "x": 0.0, "y": 0.0, "w": 340.0, "h": 220.0}
TITLE_MAX = 120
DECISION_MAX = 2000            # caracteres de una decisión
ANCHORS_MAX = 20
LABEL_CHARS = 40               # lo que entra de un post-it en el título por defecto

THREAD_PROMPT = (
    "Ahora estás en un hilo: una conversación aparte del chat principal, anclada a unos "
    "elementos de la pizarra. El mensaje que la empieza dice qué son. Céntrate en ellos. "
    "Cuando el ingeniero pida cerrar el hilo, resume lo decidido en una frase con "
    "proponer_decision (con `sources` si lleva cifras, o estimate=true si es una estimación "
    "tuya): no cierra nada, él la edita y la guarda.")
# lo que enseña el hilo como pregunta del usuario: `hilo.cerrar_con_decision` (i18n)
CLOSE_PROMPT = (
    "Quiero cerrar este hilo con una decisión. Llama a proponer_decision con una sola frase "
    "que resuma lo decidido en este hilo, con `sources` si lleva cifras (o estimate=true si "
    "son una estimación tuya). Si aún no hay nada decidido, propón la frase que mejor recoja "
    "en qué ha quedado. No hagas nada más.")
DECISION_TOOL = ("Propone la decisión con la que se cierra este hilo, en una frase. No lo "
                 "cierra: el ingeniero la edita y la guarda. Con cifras, `sources` (como en "
                 "crear_postit) o estimate=true.")
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "texto": {"type": "string", "description": "la decisión, en una frase"},
        "sources": {"type": "array", "items": {"type": "object"},
                    "description": "fuentes de las cifras (como en crear_postit)"},
        "estimate": {"type": "boolean",
                     "description": "true si las cifras son una estimación tuya sin verificar"},
    },
    "required": ["texto"],
}


# ------------------------------------------------------------------------ reglas puras
def check_decision(decision, board=None):
    """La decisión de un hilo (D167), normalizada a `{text, sources, estimate}`. Cumple la
    regla de los números (D19): con cifras, `sources` o `estimate`. Con `board` (la del
    agente), una fuente de bloque o de archivo tiene que estar en la pizarra, como en un
    post-it."""
    if not isinstance(decision, dict):
        raise ValidationError("la decisión tiene que ser un objeto {text, sources?, estimate?}")
    text = decision.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(i18n.t("hilo.decision_vacia"))
    text = text.strip()
    if len(text) > DECISION_MAX:
        raise ValidationError(i18n.t("hilo.decision_larga", max=DECISION_MAX))
    sources = decision.get("sources") or []
    if not isinstance(sources, list):
        raise ValidationError("`sources` tiene que ser una lista")
    for src in sources:
        validation.check_source(src)
    estimate = decision.get("estimate", False)
    if not isinstance(estimate, bool):
        raise ValidationError("`estimate` tiene que ser true o false")
    if validation.has_figures(text) and not sources and not estimate:
        raise ValidationError(i18n.t("hilo.decision_sin_fuente"))
    if board is not None:
        board._check_block_sources(sources)
    return {"text": text, "sources": sources, "estimate": estimate}


def check_layout(layout, base=None):
    """El tamaño y la posición de un hilo (D166), sobre `base` (lo que tenía): `size` uno de
    `SIZES`; `x`, `y`, `w` y `h` números finitos (las coordenadas que use la interfaz). El
    ancho y el alto nunca bajan de `MIN_SIZE` (D60): se suben, no se rechazan."""
    if not isinstance(layout, dict):
        raise ValidationError("`layout` tiene que ser un objeto {size, x, y, w, h}")
    out = {**DEFAULT_LAYOUT, **(base or {})}
    if "size" in layout:
        if layout["size"] not in SIZES:
            raise ValidationError(f"tamaño de hilo desconocido: {layout['size']!r} "
                                  f"(válidos: {', '.join(SIZES)})")
        out["size"] = layout["size"]
    for k in ("x", "y", "w", "h"):
        if k not in layout:
            continue
        v = layout[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            raise ValidationError(f"`layout.{k}` tiene que ser un número")
        out[k] = float(v)
    out["w"] = min(max(out["w"], MIN_SIZE[0]), MAX_SIZE)
    out["h"] = min(max(out["h"], MIN_SIZE[1]), MAX_SIZE)
    return out


def live_ids(board):
    return {e["id"] for e in board.elements if not e.get("isDeleted")}


def check_anchors(anchors, board):
    """Uno o varios elementos que están en la escena, sin repetir (D57)."""
    if not isinstance(anchors, list) or not anchors \
            or not all(isinstance(a, str) and a for a in anchors):
        raise ValidationError("un hilo se ancla a uno o varios elementos: `anchors` es una "
                              "lista de sus ids")
    anchors = list(dict.fromkeys(anchors))
    if len(anchors) > ANCHORS_MAX:
        raise ValidationError(i18n.t("hilo.demasiados_anclajes", max=ANCHORS_MAX))
    live = live_ids(board)
    for a in anchors:
        if a not in live:
            raise ValidationError(i18n.t("hilo.anclaje_no_existe", id=repr(a)))
    return anchors


def view(thread, live):
    """El hilo para la interfaz: lo guardado con `missing` y `sin_anclaje` contra la escena."""
    missing = [a for a in thread.get("anchors") or [] if a not in live]
    return {**thread, "missing": missing,
            "sin_anclaje": len(missing) == len(thread.get("anchors") or [])}


def _element(board, eid):
    return next((e for e in board.elements if e["id"] == eid and not e.get("isDeleted")), None)


def _cut(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _quoted(text):
    """El texto entre «…»; las comillas angulares que ya lleve pasan a “…” (las de segundo
    nivel), para no dejar «««…» en el título."""
    inner = _cut(text, LABEL_CHARS).replace("«", "“").replace("»", "”")
    return f"«{inner}»"


def label(board, eid):
    """Cómo se nombra un elemento en el título por defecto de un hilo."""
    el = _element(board, eid)
    cd = (el or {}).get("customData") or {}
    kind = cd.get("kind")
    if kind == "postit":
        return _quoted(cd.get("text")) if cd.get("text") else i18n.t("hilo.un_postit")
    if kind == "block":
        btype = board.registry.get(cd.get("blockType"))
        return btype.title if btype is not None else str(cd.get("blockType"))
    if kind in ("file", "folder"):
        return str(cd.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1] or i18n.t("hilo.un_archivo")
    if kind == "image":
        return i18n.t("hilo.una_imagen")
    if kind == "link":
        return i18n.t("hilo.un_enlace")
    if kind == "ink":
        return i18n.t("hilo.una_marca")
    if el is not None and el.get("type") == "text":
        return _quoted(el.get("text"))
    return i18n.t("hilo.un_dibujo")


def default_title(board, anchors):
    return _cut(i18n.t("hilo.titulo", elementos=i18n.t("hilo.y").join(label(board, a) for a in anchors)),
                TITLE_MAX)


def anchor_brief(board, eid, cap):
    """Lo que es un elemento anclado, para el primer mensaje del hilo: post-it con su tipo,
    estado, texto y fuentes; bloque con su tipo, título, parámetros, estado y salidas
    resumidas (las de `leer_pizarra`, con `cap` por salida); tarjeta con su nombre y ruta;
    imagen, que lo es; tinta, con lo que marca (`ink.describe_stroke`)."""
    el = _element(board, eid)
    if el is None:
        return {"id": eid, "es": "borrado", "nota": "ya no está en la pizarra"}
    cd = el.get("customData") or {}
    kind = cd.get("kind")
    if kind == "postit":
        out = {"id": eid, "es": "post-it", "tipo": cd.get("postitKind"),
               "estado": cd.get("state"), "autor": cd.get("author", "user"),
               "texto": cd.get("text"), "fuentes": cd.get("sources") or []}
        if cd.get("estimate"):
            out["estimacion"] = True
        if cd.get("image") or cd.get("animation"):
            out["nota"] = "lleva una imagen o una animación encima: mírala con ver_zona"
        return out
    if kind == "block":
        bid, st = eid, board.state.get(eid) or {}
        btype = board.registry.get(cd.get("blockType"))
        return {"id": bid, "es": "bloque", "tipo": cd.get("blockType"),
                "titulo": btype.title if btype is not None else None,
                "estado": board.statuses().get(bid), "parametros": st.get("params"),
                "salidas": _digest(st.get("outputs"), cap), "cite": f"bloque:{bid}"}
    if kind in ("file", "folder"):
        path = str(cd.get("path") or "")
        return {"id": eid, "es": "carpeta" if kind == "folder" else "tarjeta de archivo",
                "nombre": path.replace("\\", "/").rsplit("/", 1)[-1], "ruta": path,
                "nota": "léelo con leer_archivo(card)"}
    if kind == "image":
        return {"id": eid, "es": "imagen", "nota": "es una imagen pegada: mírala con ver_zona"}
    if kind == "link":
        return {"id": eid, "es": "enlace", "url": cd.get("url")}
    if kind == "ink":           # lo que marca, con lo mismo que `tinta` de leer_pizarra (D193)
        return {**ink.describe_stroke(el, board.elements, board.registry), "es": "tinta",
                "nota": "un trazo de tinta: míralo con ver_zona si hace falta"}
    if el.get("type") == "text":
        return {"id": eid, "es": "texto", "texto": el.get("text")}
    return {"id": eid, "es": f"dibujo ({el.get('type')})",
            "nota": "un elemento de dibujo: míralo con ver_zona si hace falta"}


def first_message(board, thread, text):
    """El mensaje que empieza la sesión de un hilo (D165): lo que son sus anclas ahora y la
    pregunta. Las anclas, hasta `TOOL_CHARS` caracteres, como una herramienta."""
    for cap in PORT_CHARS:
        brief = json.dumps([anchor_brief(board, a, cap) for a in thread["anchors"]],
                           ensure_ascii=False)
        if len(brief) <= TOOL_CHARS:
            break
    if len(brief) > TOOL_CHARS:
        brief = brief[:TOOL_CHARS] + "… (recortado: el resto, con leer_pizarra y leer_bloque)"
    return (f"[Hilo «{thread['title']}»] Esta conversación es aparte del chat principal y va "
            f"sobre estos elementos de la pizarra, tal como están ahora:\n{brief}\n\n{text}")


class ThreadStore:
    """`agent/threads.json` y los mensajes de cada hilo, siempre por el almacenamiento."""

    def __init__(self, workspace, project_id):
        self.ws, self.pid = workspace, project_id

    def all(self):
        raw = self.ws.load_agent_file(self.pid, "threads").get("threads")
        return [t for t in raw if isinstance(t, dict) and isinstance(t.get("id"), str)] \
            if isinstance(raw, list) else []

    def get(self, tid):
        t = next((t for t in self.all() if t["id"] == tid), None)
        if t is None:
            raise ValidationError(i18n.t("hilo.no_existe", id=repr(tid)))
        return t

    def _save(self, threads):
        self.ws.save_agent_file(self.pid, "threads", {"schema": 1, "threads": threads})

    def put(self, thread):
        threads = self.all()
        i = next((i for i, t in enumerate(threads) if t["id"] == thread["id"]), None)
        if i is None:
            threads.append(thread)
        else:
            threads[i] = thread
        self._save(threads)
        return thread

    def remove(self, tid):
        """Del todo: el hilo, sus mensajes y su sesión. Lo gastado sigue contando (D168)."""
        self._save([t for t in self.all() if t["id"] != tid])
        self.ws.delete_agent_thread(self.pid, tid)
        sessions = self.ws.load_agent_file(self.pid, "sessions")
        if sessions.pop(THREAD_KEY + tid, None) is not None:
            self.ws.save_agent_file(self.pid, "sessions", sessions)

    def history(self, tid):
        return self.ws.load_agent_thread(self.pid, tid)[-HISTORY_MAX:]

    def append(self, tid, event):
        try:
            self.ws.append_agent_thread(self.pid, tid, [event])
        except (StorageError, OSError) as exc:    # el hilo sigue; se queda en el registro
            log.warning("no se pudo guardar el hilo %s del proyecto %s: %s", tid, self.pid, exc)


def decisions(board):
    """Las decisiones de los hilos para `leer_pizarra` (D165): título, decisión, anclas y
    estado, nunca sus mensajes. Las de un hilo reabierto salen con `en_revision`."""
    try:
        threads = ThreadStore(board.ws, board.project_id).all()
    except (StorageError, OSError, AttributeError):
        return []
    live = live_ids(board)
    out = []
    for t in threads:
        d = t.get("decision")
        if not isinstance(d, dict):
            continue
        v = view(t, live)
        out.append({"thread": t["id"], "title": t.get("title"), "state": t.get("state"),
                    "decision": {k: d.get(k) for k in ("text", "sources", "estimate")},
                    "anchors": t.get("anchors"), "sin_anclaje": v["sin_anclaje"]})
    return out


# ------------------------------------------------------------------ la conversación
class ThreadConversation(Conversation):
    """La conversación de un hilo: sus eventos a `threads/<id>.jsonl`, su sesión aparte
    (`"hilo:<id>"`) y un agente con `proponer_decision`."""

    def __init__(self, threads, tid):
        self.threads, self.thread = threads, tid
        self.key = THREAD_KEY + tid

    def append(self, chat, event):
        self.threads.store.append(self.thread, event)

    def agent(self, chat):
        """Un agente nuevo para cada mensaje, con la sesión de este hilo y nunca otra."""
        agent = chat.make_agent()
        agent.session_id = chat.store.session_id(self.key)
        agent.exclude_attachments = (
            lambda: chat.store.settings().get("excluir_adjuntos") is True)
        agent.decide = lambda args: self.threads.propose(self, args)
        return agent

    def prompt(self, chat, text):
        if chat.store.session_id(self.key):       # la sesión ya sabe qué son las anclas
            return text
        return first_message(self.threads.board, self.threads.store.get(self.thread), text)

    async def finished(self, chat):
        try:
            t = self.threads.store.get(self.thread)
        except ValidationError:
            return                                # borrado mientras tanto: nada que contar
        events = self.threads.store.history(self.thread)
        t["messages"] = sum(1 for e in events if e.get("kind") in ("user", "text"))
        t["updated"] = scene.now_iso()
        self.threads.store.put(t)
        await self.threads.send_list()


class AgentThreads:
    """Los mensajes `thread_*` del WebSocket de un proyecto abierto. `chat` es su
    `AgentChat`; `broadcast(msg, exclude=None)` va a sus ventanas."""

    def __init__(self, chat, broadcast):
        self.chat, self.broadcast = chat, broadcast
        self.store = ThreadStore(chat.store.ws, chat.session.project_id)

    @property
    def board(self):
        return self.chat.session.board

    def list(self):
        live = live_ids(self.board)
        return [view(t, live) for t in self.store.all()]

    def view(self, tid):
        return view(self.store.get(tid), live_ids(self.board))

    async def send_list(self):
        await self.broadcast({"type": "threads", "threads": self.list()})

    def _running(self, tid):
        conv = self.chat._conv
        return self.chat.session.agent_busy and conv is not None and conv.thread == tid

    def _not_running(self, tid, what):
        if self._running(tid):
            raise ValidationError(i18n.t(what))

    def _open(self, tid):
        """El hilo, si se puede hablar en él: uno decidido hay que reabrirlo antes."""
        t = self.store.get(tid)
        if t.get("state") == "decidido":
            raise ValidationError(i18n.t("hilo.cerrado"))
        return t

    async def _ask(self, ws, tid, text, once=False):
        if not isinstance(text, str) or not text.strip():
            raise ValidationError(i18n.t("hilo.pregunta_vacia"))
        self._open(tid)
        await self.chat.ask(ws, text, once=once, conv=ThreadConversation(self, tid))

    async def propose(self, conv, args):
        """`proponer_decision` (D167): valida la decisión (D19, con las fuentes en la
        pizarra), la deja en el hilo y la manda a las ventanas. No cierra nada."""
        a = args if isinstance(args, dict) else {}
        try:
            d = check_decision({"text": a.get("texto"), "sources": a.get("sources"),
                                "estimate": bool(a.get("estimate", False))}, self.board)
            t = self.store.get(conv.thread)
        except ValidationError as exc:
            return _error(f"Rechazado: {exc}")
        d["at"] = scene.now_iso()
        self.store.put({**t, "proposed": d})
        await self.chat.emit({"kind": "decision_proposal", "decision": d}, conv)
        await self.send_list()
        return _ok({"propuesta": d["text"], "nota": "el hilo sigue abierto: el ingeniero edita "
                    "la decisión y la guarda al cerrarlo"})

    # ------------------------------------------------------------------ mensajes
    async def handle(self, ws, msg):
        kind = msg["type"]
        if kind == "thread_create":
            await self.create(ws, msg)
            return
        tid = msg.get("id")
        if not isinstance(tid, str):
            raise ValidationError(f"{kind} necesita el `id` del hilo")
        if kind == "thread_ask":
            await self._ask(ws, tid, msg.get("text"), once=msg.get("once") is True)
        elif kind == "thread_history":
            await ws.send_json({"type": "thread_history", "id": tid, "thread": self.view(tid),
                                "events": self.store.history(tid)})
        elif kind == "thread_layout":
            t = self.store.get(tid)
            t = self.store.put({**t, "layout": check_layout(msg.get("layout"), t.get("layout"))})
            await self.broadcast({"type": "thread_layout", "id": tid, "layout": t["layout"]},
                                 exclude=ws)
        elif kind == "thread_close_request":
            self._open(tid)
            await self.chat.ask(ws, i18n.t("hilo.cerrar_con_decision"), once=msg.get("once") is True,
                                conv=ThreadConversation(self, tid), prompt=CLOSE_PROMPT,
                                extra={"close_request": True})
        elif kind == "thread_close":
            await self.close(tid, msg.get("decision"))
        elif kind == "thread_reopen":
            t = self.store.get(tid)
            if t.get("state") != "decidido":
                raise ValidationError(i18n.t("hilo.reabrir_solo_decidido"))
            self.store.put({**t, "state": "en_revision", "updated": scene.now_iso()})
            await self.chat.emit({"kind": "reopened"}, ThreadConversation(self, tid))
            await self.send_list()
        elif kind == "thread_delete":
            self.store.get(tid)
            self._not_running(tid, "hilo.ocupado_borrar")
            self.store.remove(tid)
            await self.send_list()
        else:
            raise ValidationError(f"mensaje desconocido: {kind!r}")

    async def create(self, ws, msg):
        """`thread_create`: lo crea y, con `text`, le pregunta. Con el agente ocupado y una
        pregunta, no crea nada: así nunca queda un hilo a medias."""
        text = msg.get("text")
        if text is not None and (not isinstance(text, str) or not text.strip()):
            raise ValidationError(i18n.t("hilo.pregunta_vacia"))
        if text is not None and self.chat.session.agent_busy:
            raise ValidationError(i18n.t("agente.ocupado"))
        anchors = check_anchors(msg.get("anchors"), self.board)
        title = msg.get("title")
        if title is not None and not isinstance(title, str):
            raise ValidationError("el título tiene que ser un texto")
        title = _cut(title, TITLE_MAX) if title and title.strip() else \
            default_title(self.board, anchors)
        layout = check_layout(msg.get("layout") if msg.get("layout") is not None else {})
        now = scene.now_iso()
        t = self.store.put({"id": "h_" + uuid.uuid4().hex[:12], "title": title,
                            "anchors": anchors, "state": "abierto", "decision": None,
                            "proposed": None, "layout": layout, "messages": 0,
                            "created": now, "updated": now})
        await ws.send_json({"type": "thread_created", "thread": self.view(t["id"])})
        await self.send_list()
        if text is not None:
            await self._ask(ws, t["id"], text, once=msg.get("once") is True)

    async def close(self, tid, decision):
        """`thread_close` (D167): la decisión que guarda el usuario, con la regla de los
        números (D19). El hilo queda `decidido` y minimizado, con la decisión a la vista."""
        t = self.store.get(tid)
        if t.get("state") == "decidido":
            raise ValidationError(i18n.t("hilo.ya_cerrado"))
        self._not_running(tid, "hilo.ocupado_cerrar")
        d = {**check_decision(decision), "at": scene.now_iso()}
        self.store.put({**t, "state": "decidido", "decision": d, "proposed": None,
                        "layout": {**check_layout({}, t.get("layout")), "size": "min"},
                        "updated": d["at"]})
        await self.chat.emit({"kind": "closed", "decision": d}, ThreadConversation(self, tid))
        await self.send_list()
