"""La conversación con el agente de diseño de un proyecto (FF 4.6 paso 1; plan §4, D164,
D168, D169).

Entre el WebSocket (`server.py`) y el agente (`agent.DesignAgent`):

- **En disco** (D164), por el almacenamiento: cada evento del chat principal va a
  `agent/chat.jsonl` según sale (salvo las tarjetas de *Entendido* y del tope, que piden una
  respuesta a quien preguntó y no son conversación); la sesión del SDK, a `agent/sessions.json`
  por conversación (`"chat"`, la principal; `"hilo:<id>"`, cada hilo, D165, que lleva
  `agent_threads.py`), para que reabrir el proyecto o reiniciar la app siga la misma
  conversación. Una conversación (`Conversation`) dice dónde van sus eventos y qué sesión
  sigue; el chat y los hilos comparten todo lo demás: las puertas, el consumo, *Parar* y
  **una sola pregunta a la vez por proyecto**, contando chat e hilos (`agent_busy`): el
  agente de un hilo trabaja sobre la misma pizarra, y dos a la vez se pisarían.
- **Consumo y tope** (D168): lo que da el `ResultMessage` de cada mensaje se suma en
  `agent/usage.json` por agente (`"diseno"`, y los hilos cuentan en él; `"revisor"`, el
  revisor, `agent_review.py`), y el proyecto es la suma de sus agentes. El tope es en
  dólares equivalentes, el del proyecto (`project.toml`) o el de los ajustes (`[agentes]
  tope_proyecto_usd`, 5). Con el consumo en el tope no empieza
  ningún mensaje; dentro de uno, `max_budget_usd` es lo que queda.
- **Parar**: corta el mensaje en curso con `interrupt()` del SDK; si el SDK no acaba en
  `STOP_GRACE` s, se cancela la tarea. Lo hecho (post-its, propuestas) se queda.
- **Privacidad** (D169): hasta que se pulsa *Entendido* (`[agentes] privacidad_vista` en
  `settings.toml`), ninguna pregunta llega al agente. *Excluir adjuntos* es del proyecto.

Las tarjetas de privacidad y del tope llevan el texto de la pregunta (`text`): el cliente,
tras *Entendido*, *Subir tope* o *Seguir solo este mensaje*, la vuelve a mandar. El backend
no guarda preguntas pendientes, así que dos ventanas no se pisan.

Lo que sale por el WebSocket (la lista corta está en `server.py`):
    {"type": "agent", "kind": "done", "at", "turns", "seconds", "reason", "usage", "total",
     "limit", "text"?}      reason: ok | limit (el SDK cortó por el tope) | stopped | max_turns
                            | error; usage: el mensaje, total: el proyecto, los dos
                            {input, output, cache_creation, cache_read, usd, messages}
    {"type": "agent", "kind": "stopped", "at", "text"}                  tras *Parar*
    {"type": "agent", "kind": "privacy", "text", "notice"}             sin *Entendido*
    {"type": "agent", "kind": "limit", "text", "used", "limit"}        tope alcanzado
    {"type": "agent_history", "events": [...], "state": {...}}         lo de `agent/chat.jsonl`
    {"type": "agent_state", "usage": {"agents": {"diseno": {...}}, "total": {...}}, "limit",
     "limit_own", "remaining", "exclude_attachments", "privacy_seen", "busy", "thread",
     "busy_agent"}          thread: el hilo con el que está el agente (null: el chat o nada);
                            busy_agent: diseno | revisor | null, el que trabaja (V6)
Los eventos de un hilo (y sus tarjetas de privacidad y tope) llevan además `"thread": <id>`;
los del revisor, `"agent": "revisor"` (`agent_review.py`).
"""
import asyncio
import logging
import math
import time

from pizarra import agent_prompt, api_key, i18n
from pizarra.settings import positive_usd
from pizarra.storage import StorageError
from pizarra.validation import ValidationError

log = logging.getLogger(__name__)

DESIGN = "diseno"              # el agente de diseño en usage.json (los hilos también, D168)
MAIN_CHAT = "chat"             # la conversación principal en sessions.json
CHAT_FILE = "chat"             # y en `agent/` (`chat.jsonl`); el revisor, `review` (V3)
TOKENS = {"input": "input_tokens", "output": "output_tokens",
          "cache_creation": "cache_creation_input_tokens",
          "cache_read": "cache_read_input_tokens"}       # nuestro nombre: el del SDK
# Lo que se puede gastar con *Seguir solo este mensaje*, como parte del tope: con el tope ya
# alcanzado no queda nada, y el SDK pararía el mensaje en la primera vuelta.
ONCE_SHARE = 0.2
STOP_GRACE = 5.0               # s que se espera al SDK tras *Parar* antes de cancelar
HISTORY_MAX = 2000             # eventos del chat que se mandan al abrir (los últimos)
NOT_KEPT = ("limit", "privacy")    # tarjetas para quien preguntó: ni a disco ni a las demás
REASONS = {"success": "ok", "error_max_budget_usd": "limit", "error_max_turns": "max_turns"}


def empty_usage():
    return {**{k: 0 for k in TOKENS}, "usd": 0.0, "messages": 0}


def message_usage(usage, cost_usd):
    """Lo que gastó un mensaje: los tokens del `usage` del SDK (lo que no es un entero cuenta
    0) y su coste en dólares equivalentes (`total_cost_usd`; None es 0)."""
    usage = usage if isinstance(usage, dict) else {}
    out = {k: _count(usage.get(sdk)) for k, sdk in TOKENS.items()}
    cost = cost_usd if isinstance(cost_usd, (int, float)) and not isinstance(cost_usd, bool) \
        and math.isfinite(cost_usd) and cost_usd > 0 else 0.0
    return {**out, "usd": float(cost), "messages": 1}


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _add(a, b):
    out = {k: _count(a.get(k)) + _count(b.get(k)) for k in (*TOKENS, "messages")}
    usd = sum(x.get("usd") if isinstance(x.get("usd"), (int, float)) else 0.0 for x in (a, b))
    return {**out, "usd": round(usd, 6)}


def valid_cost(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def session_cost(entry, session_id, cumulative):
    """(coste del mensaje, entrada nueva o None): el acumulado de la sesión (`cumulative`, el
    `total_cost_usd` del SDK) menos el último que se apuntó de esa misma sesión en `entry`
    (`session_id`, `cost_usd`). La entrada nueva lleva el acumulado de ahora; sin sesión, no
    hay nada que apuntar. Una sesión nueva, o un acumulado menor, empieza de cero."""
    last = entry.get("cost_usd") if entry.get("session_id") == session_id else None
    last = last if isinstance(last, (int, float)) and not isinstance(last, bool) else 0.0
    new = {**entry, "session_id": session_id, "at": time.time(),
           "cost_usd": float(cumulative)} if session_id else None
    return (cumulative - last if cumulative >= last else float(cumulative)), new


def close_done(event, stopping, used, total, limit):
    """El `done` del SDK como lo enseña el chat: cómo acabó (`reason`, de `subtype` y
    `terminal_reason`, que se quitan), lo del mensaje (`used`), el total y el tope, y el texto
    si no acabó bien. `stopping`: si se pulsó *Parar*."""
    subtype = event.pop("subtype", None)
    terminal = event.pop("terminal_reason", None)
    reason = "stopped" if stopping or str(terminal or "").startswith("aborted") \
        else REASONS.get(subtype, "error") if subtype is not None else "ok"
    out = {**event, "reason": reason, "usage": used, "total": total, "limit": limit}
    if reason == "limit":
        out["text"] = i18n.t("agente.parado_tope", usado=f"{total['usd']:.2f}",
                             tope=f"{limit:.2f}")
    elif reason == "max_turns":
        out["text"] = i18n.t("agente.parado_vueltas")
    elif reason == "error":
        out["text"] = i18n.t("agente.acabo_con_error", tipo=subtype)
    return out


class AgentStore:
    """`agent/` y `[agentes]` de un proyecto, siempre por el almacenamiento (D164)."""

    def __init__(self, workspace, project_id):
        self.ws, self.pid = workspace, project_id

    # ------------------------------------------------------------------ chat
    def history(self, name=CHAT_FILE):
        """Los últimos eventos de la conversación `name` (`chat`, el de diseño; `review`, el
        revisor: nunca se mezclan, PLAN_V020 V3)."""
        return self.ws.load_agent_chat(self.pid, name)[-HISTORY_MAX:]

    def append(self, event, name=CHAT_FILE):
        try:
            self.ws.append_agent_chat(self.pid, [event], name)
        except (StorageError, OSError) as exc:    # el chat sigue; se queda en el registro
            log.warning("no se pudo guardar el chat del proyecto %s: %s", self.pid, exc)

    # -------------------------------------------------------------- sesiones
    def session_id(self, conversation=MAIN_CHAT):
        sid = (self.ws.load_agent_file(self.pid, "sessions").get(conversation) or {})
        sid = sid.get("session_id") if isinstance(sid, dict) else None
        return sid if isinstance(sid, str) and sid else None

    def set_session_id(self, session_id, conversation=MAIN_CHAT):
        if not session_id or session_id == self.session_id(conversation):
            return
        data = self.ws.load_agent_file(self.pid, "sessions")
        entry = data.get(conversation) if isinstance(data.get(conversation), dict) else {}
        data[conversation] = {**entry, "session_id": session_id, "at": time.time()}
        self.ws.save_agent_file(self.pid, "sessions", data)

    def message_cost(self, session_id, cumulative, conversation=MAIN_CHAT):
        """El coste de un mensaje a partir del `total_cost_usd` del SDK, que es el acumulado de
        la sesión reanudada, no el del mensaje (medido con Claude de verdad): la diferencia con
        el último acumulado de esa misma sesión, que se guarda en `sessions.json`. Una sesión
        nueva, o un acumulado menor (el CLI perdió la sesión), empieza de cero."""
        if not valid_cost(cumulative):
            return None
        data = self.ws.load_agent_file(self.pid, "sessions")
        entry = data.get(conversation) if isinstance(data.get(conversation), dict) else {}
        cost, new = session_cost(entry, session_id, cumulative)
        if new is not None:
            data[conversation] = new
            self.ws.save_agent_file(self.pid, "sessions", data)
        return cost

    # --------------------------------------------------------------- consumo
    def usage(self):
        """{agents: {agente: consumo}, total}: el proyecto es la suma de sus agentes."""
        raw = self.ws.load_agent_file(self.pid, "usage").get("agents")
        agents = {k: _add(empty_usage(), v) for k, v in (raw or {}).items()
                  if isinstance(k, str) and isinstance(v, dict)} if isinstance(raw, dict) else {}
        total = empty_usage()
        for v in agents.values():
            total = _add(total, v)
        return {"agents": agents, "total": total}

    def add_usage(self, agent, used):
        """Suma lo de un mensaje a su agente, y solo a él. Devuelve el consumo nuevo."""
        data = self.ws.load_agent_file(self.pid, "usage")
        agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
        agents[agent] = _add(agents.get(agent) or empty_usage(), used)
        self.ws.save_agent_file(self.pid, "usage", {"schema": 1, "agents": agents})
        return self.usage()

    # ------------------------------------------------------ ajustes del proyecto
    def settings(self):
        return self.ws.load_project_agent_settings(self.pid)

    def update_settings(self, **changes):
        data = self.settings()
        for k, v in changes.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        self.ws.save_project_agent_settings(self.pid, data)


def limit_of(store, settings):
    """(tope, si es el del proyecto): el de `project.toml` o, si no, el de los ajustes."""
    own = positive_usd(store.settings().get("tope_usd"))
    return (own, True) if own else (settings.project_limit_usd, False)


def state(store, settings, busy=False):
    """Lo que enseña el panel: consumo, tope, lo que queda y los ajustes del agente."""
    usage = store.usage()
    limit, own = limit_of(store, settings)
    used = usage["total"]["usd"]
    return {"usage": usage, "limit": limit, "limit_own": own,
            "remaining": round(max(0.0, limit - used), 6),
            "exclude_attachments": store.settings().get("excluir_adjuntos") is True,
            "privacy_seen": settings.privacy_seen, "busy": busy}


def budget_for(used, limit, once=False):
    """El `max_budget_usd` de un mensaje: lo que queda del tope, nunca el tope entero (salvo
    sin nada gastado). Con *Seguir solo este mensaje*, al menos `ONCE_SHARE` del tope."""
    left = max(0.0, limit - used)
    return round(max(left, ONCE_SHARE * limit) if once else left, 6)


class Conversation:
    """Una conversación con el agente de diseño: dónde van sus eventos, qué sesión del SDK
    sigue (`key` en `sessions.json`) y qué agente la lleva. Esta es la principal; cada hilo
    es una `agent_threads.ThreadConversation` (D165), y la del revisor, una
    `agent_review.ReviewConversation` (PLAN_V020 V3)."""
    key = MAIN_CHAT
    thread = None                 # el id del hilo, que llevan sus eventos por el WebSocket
    usage_agent = DESIGN          # a quién se suma su consumo en usage.json (D168)
    animated = True               # su agente puede hacer animaciones (D144): el revisor, no

    def tag(self):
        return {"thread": self.thread} if self.thread else {}

    def append(self, chat, event):
        chat.store.append(event)

    def agent(self, chat):
        return chat.agent()

    def prompt(self, chat, text):
        """Lo que recibe el agente por la pregunta `text`."""
        return text

    async def finished(self, chat):
        """Tras cada mensaje, haya acabado como haya acabado."""


MAIN = Conversation()


class AgentChat:
    """La conversación principal de una sesión (un proyecto abierto). `make_agent()` da el
    agente (un `DesignAgent`); `broadcast(msg)` va a las ventanas del proyecto; `saved()` guarda
    la pizarra y lo avisa; `finished()` libera al agente (`Sessions.agent_finished`)."""

    def __init__(self, session, workspace, settings, make_agent, broadcast, saved, finished):
        self.session, self.settings = session, settings
        self.store = AgentStore(workspace, session.project_id)
        self.make_agent, self.broadcast = make_agent, broadcast
        self.saved, self.finished = saved, finished
        self.stop_grace = STOP_GRACE
        self._task = None
        self._stopping = False
        self._conv = None                     # la conversación del mensaje en curso
        self._agent = None                    # y su agente (para *Parar* y el consumo)
        self.asker = None                     # la ventana de la última pregunta
        # async () -> None que empieza cuando acaba el mensaje en curso (un hito del revisor
        # que llegó con el agente ocupado, V6); uno solo: el último que llega manda
        self.queued = None

    def state(self):
        busy = self.session.agent_busy
        conv = self._conv if busy else None
        return {**state(self.store, self.settings, busy),
                "thread": conv.thread if conv is not None else None,
                # qué agente trabaja (V6: uno a la vez por proyecto): diseno | revisor | null
                "busy_agent": conv.usage_agent if conv is not None else None}

    async def send_state(self):
        await self.broadcast({"type": "agent_state", **self.state()})

    async def emit(self, event, conv=None):
        """Un evento de una conversación (la del mensaje en curso o, sin ella, el chat): a
        disco (D164) y a las ventanas del proyecto, con el hilo si es de uno."""
        conv = conv or self._conv or MAIN
        event = {**event, "at": round(time.time(), 3)}
        if event.get("kind") not in NOT_KEPT:
            conv.append(self, event)
        await self.broadcast({"type": "agent", **conv.tag(), **event})

    # ------------------------------------------------------------ mensajes del WS
    async def handle(self, ws, msg):
        kind = msg["type"]
        if kind == "agent_ask":
            await self.ask(ws, str(msg["text"]), once=msg.get("once") is True)
        elif kind == "agent_stop":
            await self.stop()
        elif kind == "agent_history":
            await ws.send_json({"type": "agent_history", "events": self.store.history(),
                                "state": self.state()})
        elif kind == "agent_privacy_ok":
            self.settings.privacy_seen = True
            self.settings.save()
            await self.send_state()
        elif kind == "agent_settings":
            self.change_settings(msg)
            await self.send_state()
        else:
            raise ValidationError(f"mensaje desconocido: {kind!r}")

    def change_settings(self, msg):
        changes = {}
        if "limit" in msg:
            if msg["limit"] is not None and positive_usd(msg["limit"]) is None:
                raise ValidationError(i18n.t("agente.tope_no_valido"))
            changes["tope_usd"] = positive_usd(msg["limit"])       # None: el de los ajustes
        if "exclude_attachments" in msg:
            if not isinstance(msg["exclude_attachments"], bool):
                raise ValidationError("exclude_attachments tiene que ser true o false")
            changes["excluir_adjuntos"] = msg["exclude_attachments"]
        if not changes:
            raise ValidationError("agent_settings necesita `limit` o `exclude_attachments`")
        self.store.update_settings(**changes)

    async def ask(self, ws, text, once=False, conv=None, prompt=None, extra=None):
        """Una pregunta en `conv` (por defecto, el chat). No llega al agente sin *Entendido*
        (D169) ni con el tope alcanzado (D168, salvo `once`); entonces solo quien preguntó
        recibe la tarjeta, con su texto (y su hilo y `extra`, para volver a mandarla). El
        agente recibe `prompt` si se da (*Cerrar con decisión*, D167) o el de `conv`; el
        evento `user` lleva `text` y `extra`. Devuelve si ha empezado."""
        s = self.session
        conv = conv or MAIN
        if s.agent_busy:
            raise ValidationError(i18n.t("agente.ocupado"))
        card = {"type": "agent", **conv.tag(), **(extra or {}), "text": text}
        # sin ventana (un hito del revisor, V5), la tarjeta no va a nadie: no empieza y ya está
        if not self.settings.privacy_seen:
            if ws is not None:
                await ws.send_json({**card, "kind": "privacy",
                                    "notice": i18n.t("agente.privacidad", self.settings.language)})
            return False
        used = self.store.usage()["total"]["usd"]
        limit, _own = limit_of(self.store, self.settings)
        if used >= limit and not once:
            if ws is not None:
                await ws.send_json({**card, "kind": "limit", "used": used, "limit": limit})
            return False
        # Ocupado ANTES de crear la tarea: así no caben dos preguntas a la vez aunque lleguen
        # seguidas desde dos ventanas (R6).
        s.agent_busy = True
        self.asker = ws                       # la ventana a la que se pide `ver_zona` (D171)
        self._stopping = False
        self._conv = conv
        self._task = asyncio.create_task(self._run(conv, text, budget_for(used, limit, once),
                                                   prompt, extra))
        s.tasks.add(self._task)
        self._task.add_done_callback(s.tasks.discard)
        return True

    def agent(self):
        s = self.session
        if s.agent is None:
            s.agent = self.make_agent()
            s.agent.session_id = self.store.session_id()      # sigue la conversación (D164)
            s.agent.exclude_attachments = (
                lambda: self.store.settings().get("excluir_adjuntos") is True)
        return s.agent

    async def _run(self, conv, text, budget, prompt=None, extra=None):
        agent = None
        try:
            agent = self._agent = conv.agent(self)
            agent.max_budget_usd = budget
            message = prompt if prompt is not None else conv.prompt(self, text)
            if not self.settings.animations_auto and conv.animated:
                message = agent_prompt.ANIMATIONS_OFF_NOTE + "\n\n" + message
            await self.emit({"kind": "user", "text": text, **(extra or {})}, conv)
            await agent.ask(message, lambda ev: self._on_event(ev, conv))
        except asyncio.CancelledError:        # *Parar* sin respuesta del SDK
            pass
        except api_key.MissingKey:            # «api_key» sin clave: dice dónde ponerla (O9)
            await self.emit({"kind": "error",
                             "text": i18n.t("agente.sin_api_key", self.settings.language)}, conv)
        except Exception as exc:              # se enseña en el panel, no se oculta
            await self.emit({"kind": "error", "text": f"{type(exc).__name__}: {exc}"}, conv)
        finally:
            self._keep_session(agent, conv.key)
            stopped, self._stopping, self._task = self._stopping, False, None
            try:
                if stopped:
                    await self.emit({"kind": "stopped",
                                     "text": i18n.t("agente.parado")},
                                    conv)
                await conv.finished(self)
                await self.saved()
            except Exception as exc:          # noqa: BLE001 p. ej. el proyecto se borró
                log.warning("tras el agente en %s: %s", self.session.project_id, exc)
            self._conv = self._agent = None
            self.finished()
            try:
                await self.send_state()
            except Exception:                 # noqa: BLE001 sin ventanas a las que avisar
                pass
            await self._run_queued()

    async def _run_queued(self):
        """Lo que esperaba a que acabase este mensaje (un hito del revisor con el agente
        ocupado, V5, V6): empieza ahora si el proyecto sigue abierto en alguna ventana."""
        nxt, self.queued = self.queued, None
        if nxt is None or not self.session.clients or self.session.agent_busy:
            return
        try:
            await nxt()
        except Exception as exc:              # noqa: BLE001 lo de después no tumba este
            log.warning("lo que esperaba al agente en %s no empezó: %s",
                        self.session.project_id, exc)

    def _keep_session(self, agent, conversation=MAIN_CHAT):
        try:
            self.store.set_session_id(getattr(agent, "session_id", None), conversation)
        except (StorageError, OSError) as exc:
            log.warning("no se pudo guardar la sesión del agente: %s", exc)

    async def _on_event(self, event, conv=None):
        conv = conv or MAIN
        if event.get("kind") == "done":
            event = self._done(event, conv)
        await self.emit(event, conv)

    def _done(self, event, conv=MAIN):
        """El consumo del mensaje y el total, y cómo acabó (`reason`) en palabras del chat."""
        cumulative = event.pop("cost_usd", None)
        agent = self._agent or self.session.agent
        try:                                  # por diferencia con SU sesión (R41)
            cost = self.store.message_cost(getattr(agent, "session_id", None), cumulative,
                                           conv.key)
        except (StorageError, OSError) as exc:
            log.warning("no se pudo guardar la sesión del agente: %s", exc)
            cost = cumulative
        used = message_usage(event.pop("usage", None), cost)
        self._keep_session(agent, conv.key)
        try:                                  # los hilos, al de diseño (D168); el revisor, al suyo
            usage = self.store.add_usage(conv.usage_agent, used)
        except (StorageError, OSError) as exc:
            log.warning("no se pudo guardar el consumo: %s", exc)
            usage = self.store.usage()
        limit, _own = limit_of(self.store, self.settings)
        return close_done(event, self._stopping, used, usage["total"], limit)

    async def stop(self):
        """*Parar* (`agent_stop`): el SDK corta el mensaje y lo dice su `done`; si no contesta
        en `stop_grace` s o aún no había arrancado, se cancela la tarea."""
        task = self._task
        if not self.session.agent_busy or task is None or task.done():
            raise ValidationError(i18n.t("agente.sin_mensaje"))
        if self._stopping:
            return
        self._stopping = True
        interrupt = getattr(self._agent, "interrupt", None)
        try:
            if interrupt is None:
                raise RuntimeError("sin interrupt")
            await interrupt()
        except Exception:                     # noqa: BLE001 no hay con qué hablar: se cancela
            task.cancel()
            return
        asyncio.get_running_loop().call_later(
            self.stop_grace, lambda: None if task.done() else task.cancel())


def register(app, need_workspace, settings, sessions):
    """`GET /api/projects/<id>/agent`: el consumo, el tope y los ajustes del agente, también
    de un proyecto que no está abierto."""
    @app.get("/api/projects/{pid}/agent")
    def get_agent(pid: str):
        ws = need_workspace()
        ws.project(pid)
        s = sessions.get(pid)
        return state(AgentStore(ws, pid), settings, bool(s and s.agent_busy))
