"""Las herramientas del agente de onboarding (docs/PLAN_ONBOARDING.md §4, N3, N4).

**Ninguna escribe** en el workspace (N4): las de proponer validan con las reglas de la
escritura (`onboarding.Proposals.check`) y, si vale, dejan una tarjeta en el chat con lo de
ahora y lo nuevo; quien guarda es el usuario con *Guardar*. Un rechazo vuelve al agente como
error con el motivo y no deja tarjeta.

- `leer_configuracion {}`: el perfil de fabricación (o la plantilla, si no hay), los
  proveedores, los tipos de la librería, las unidades con sus opciones y el estado de las
  propuestas.
- `proponer_perfil {texto, motivo, fuentes?}`: el `fabricacion.md` nuevo entero.
- `proponer_proveedores {proveedores, motivo}`: la lista entera en su orden.
- `proponer_unidades {unidades, motivo}`: las magnitudes que cambian.
- `proponer_importacion {hoja, tipo, mapeo, motivo}` (N7): solo con un Excel elegido antes
  (*Elegir Excel…*); el mapeo, con las reglas del importador. La tarjeta abre el importador.

Como las del agente de diseño, son funciones normales que se prueban sin el SDK.

El agente (`OnboardingAgent`) y su conversación (`OnboardingChat`, la que sirve
`/ws/onboarding` en `onboarding_api`) van al final (§6, paso 2).

**La web con cita** (N8, paso 5): `WebSearch` y `WebFetch` de Claude Code, que no van en
`allowed_tools` y por eso pasan siempre por `can_use_tool` (`OnboardingAgent.permit`): la
búsqueda pasa, una página solo si es `http(s)`, y cualquier otra herramienta se deniega. Lo que
devuelven se apunta del flujo (`on_tool_use`, `on_tool_result`), no de lo que diga el agente, en
un `supply.SearchLog` nuevo en cada mensaje; contra él se comprueba cada cita de una propuesta
(`onboarding.check_sources`).
"""
import asyncio
import json
import logging
import time
import warnings

from pizarra import agent as agent_mod
from pizarra import agent_chat, api_key, i18n, supply, units
from pizarra.agent import _error, _ok
from pizarra.onboarding import ONBOARDING, PENDING, Proposals
from pizarra.sessions import send_all
from pizarra.storage import StorageError
from pizarra.validation import ValidationError
from pizarra.workspace_api import PROFILE_MAX

log = logging.getLogger(__name__)

MOTIVO = {"type": "string", "description": "por qué, en una frase (lo lee el ingeniero en la tarjeta)"}
FUENTES = {"type": "array", "items": {"type": "object", "properties": {
    "url": {"type": "string"}, "cita": {"type": "string"}}, "required": ["url", "cita"]},
    "description": "de dónde sale cada cifra que no te dio el ingeniero: la URL que abriste y "
                   "la frase tal cual de esa página"}
SCHEMAS = {
    "leer_configuracion": {"type": "object", "properties": {}},
    "proponer_perfil": {"type": "object", "properties": {
        "texto": {"type": "string", "description": f"el perfil de fabricación entero en "
                                                   f"Markdown (como mucho {PROFILE_MAX} caracteres)"},
        "motivo": MOTIVO, "fuentes": FUENTES}, "required": ["texto", "motivo"]},
    "proponer_proveedores": {"type": "object", "properties": {
        "proveedores": {"type": "array", "items": {"type": "object", "properties": {
            "nombre": {"type": "string"}, "dominio": {"type": "string"},
            "tipos": {"type": "array", "items": {"type": "string"}}},
            "required": ["nombre", "dominio"]},
            "description": "la lista entera, en el orden de preferencia; tipos vacío = todos"},
        "motivo": MOTIVO}, "required": ["proveedores", "motivo"]},
    "proponer_unidades": {"type": "object", "properties": {
        "unidades": {"type": "object", "description": "{magnitud: unidad}, solo las que "
                                                      "cambian; las opciones, en leer_configuracion"},
        "motivo": MOTIVO}, "required": ["unidades", "motivo"]},
    "proponer_importacion": {"type": "object", "properties": {
        "hoja": {"type": "string", "description": "la hoja del Excel (vacío: la elegida)"},
        "tipo": {"type": "string", "description": "el tipo de ficha (reducer, motor…); hace "
                                                  "falta si alguna columna va a manufacturer, "
                                                  "kind o values.<campo>"},
        "mapeo": {"type": "object", "description": "{columna: campo}; campos: key (obligatorio), "
                                                   "manufacturer, kind, cantidad, ubicacion, "
                                                   "fecha, nota o values.<campo>; las columnas "
                                                   "que no se importan no van"},
        "motivo": MOTIVO}, "required": ["mapeo", "motivo"]},
}
DESCRIPTIONS = {
    "leer_configuracion": "Lee cómo está configurado el workspace: perfil de fabricación, "
                          "proveedores, unidades y tipos de la librería, y tus propuestas.",
    "proponer_perfil": "Propone el perfil de fabricación nuevo entero. No guarda nada: deja una "
                       "tarjeta con el diff y el ingeniero pulsa Guardar o Descartar.",
    "proponer_proveedores": "Propone la lista de proveedores entera en su orden. No guarda "
                            "nada: deja una tarjeta y el ingeniero decide.",
    "proponer_unidades": "Propone las unidades por defecto del workspace. No guarda nada: deja "
                         "una tarjeta y el ingeniero decide.",
    "proponer_importacion": "Propone cómo importar a la librería el Excel que eligió el "
                            "ingeniero: a qué campo va cada columna. No importa nada: la tarjeta "
                            "abre el importador rellenado y el ingeniero pulsa Importar.",
}
NAMES = tuple(SCHEMAS)
PROPOSE = {"proponer_perfil": ("perfil", "texto"), "proponer_proveedores": ("proveedores", "proveedores"),
           "proponer_unidades": ("unidades", "unidades")}


class OnboardingTools:
    """Las herramientas sobre `proposals` (`onboarding.Proposals`). `log`, si se da, es lo
    que devolvió la web en este turno (N8); `on_card(evento)`, a quien se manda cada
    tarjeta nueva (el chat en directo, paso 2)."""

    def __init__(self, proposals: Proposals, log=None, on_card=None):
        self.proposals = proposals
        self.log = log
        self.on_card = on_card

    def call(self, name, args):
        args = args if isinstance(args, dict) else {}
        try:
            if name == "leer_configuracion":
                return _ok(self.read())
            if name in PROPOSE:
                que, field = PROPOSE[name]
                event = self.proposals.propose(que, args.get(field), args.get("motivo"),
                                               args.get("fuentes"), self.log)
                if self.on_card is not None:
                    self.on_card(event)
                return _ok({"propuesta": event["id"], "estado": PENDING,
                            "aviso": i18n.t("onboarding.tarjeta_dejada")})
            if name == "proponer_importacion":
                event = self.proposals.propose_import(args.get("hoja"), args.get("tipo"),
                                                      args.get("mapeo"), args.get("motivo"))
                if self.on_card is not None:
                    self.on_card(event)
                return _ok({"propuesta": event["id"], "estado": PENDING,
                            "aviso": i18n.t("onboarding.tarjeta_importacion")})
        except ValueError as exc:       # ValidationError y StorageError también lo son
            return _error(str(exc))
        return _error(i18n.t("onboarding.herramienta_desconocida", nombre=name))

    def read(self):
        p = self.proposals
        profile = p.current("perfil")
        out = {"perfil": {"texto": profile, "guardado": profile is not None, "max": PROFILE_MAX},
               "proveedores": p.current("proveedores"),
               "tipos_libreria": p.supply.library().types(),
               "unidades": {"ahora": p.current("unidades"),
                            "opciones": {m: list(u) for m, u in units.UNITS.items()},
                            "juegos": units.PRESETS},
               "propuestas": [{"id": x["id"], "que": x.get("que"), "estado": x.get("estado")}
                              for x in p.store.proposals().values()]}
        excel = p.store.excel()
        if excel is not None:                 # el Excel elegido, para proponer_importacion (N7)
            out["excel"] = {k: excel.get(k) for k in ("nombre", "sheets", "sheet", "columns",
                                                      "rows")}
        if profile is None:
            out["perfil"]["plantilla"] = i18n.t("perfil.plantilla")
        return out


# ------------------------------------------------------------------ el agente (paso 2)
SYSTEM_PROMPT = """Eres el agente de onboarding de una aplicación de diseño de ingeniería. \
Ayudas a un ingeniero a configurar su workspace: el perfil de fabricación (qué máquinas y \
procesos tiene, con qué materiales, con qué precisión, qué hace fuera), los proveedores en su \
orden de preferencia y las unidades por defecto.

Reglas que no se pueden saltar:
- Empieza leyendo cómo está todo con leer_configuracion, y vuelve a leerla antes de proponer \
algo que el ingeniero haya podido cambiar.
- Una cosa cada vez: pregunta lo que te falta para una, propónla y pasa a la siguiente.
- Pregunta antes de suponer. Ninguna cifra (volumen de trabajo, precisión, espesores) sale \
de ti: es del ingeniero, o de una página que abriste, y entonces va en `fuentes` con la URL y \
la frase tal cual.
- No guardas nada. Las herramientas de proponer dejan una tarjeta con el cambio y el \
ingeniero pulsa Guardar o Descartar. Nunca digas que algo está guardado o configurado si su \
tarjeta no lo está: al principio de cada mensaje te llega cómo acabaron tus propuestas.
- Una propuesta caducada es que el ingeniero cambió eso a mano después: lee lo de ahora y, si \
aún hace falta, propón otra sobre eso.
- Si una herramienta rechaza la propuesta, lee el motivo y corrígela; no la repitas igual.
- El perfil se propone entero (es un Markdown corto): conserva lo que ya tenía y cambia solo \
lo que habéis hablado.
- Si el ingeniero elige un Excel para la librería, te llegan sus columnas y unas filas: \
propón con proponer_importacion a qué campo va cada columna (key, la referencia única de \
cada fila, es obligatoria). No importas nada: la tarjeta abre el importador ya rellenado y es \
el ingeniero quien pulsa Importar.
- Puedes buscar en la web (WebSearch) y abrir páginas (WebFetch) para la ficha de una \
máquina o de un proceso que el ingeniero nombre. Cada cifra que saques de ahí va en `fuentes` \
con la URL y la frase tal cual de lo que te devolvió la herramienta en este mismo mensaje: una \
cita que no esté ahí rechaza la propuesta. Si una página no se abre o no lo dice, pregúntaselo.
- Respuestas cortas: es una conversación de configuración, no un informe."""
ALLOWED = [f"mcp__onboarding__{n}" for n in NAMES]
WEB_TOOLS = ("WebSearch", "WebFetch")    # de Claude Code, siempre por `can_use_tool` (N8)
MAX_TURNS = 20


class OnboardingAgent(agent_mod.DesignAgent):
    """El agente de onboarding de un workspace (§6): aislado como el de diseño
    (`setting_sources=[]`, `strict_mcp_config`, sin las herramientas de Claude Code) y con
    las suyas y ninguna más. Del de diseño solo hereda cómo se habla con el SDK (`ask`,
    `interrupt`). `on_card(evento)` (async) recibe cada tarjeta de propuesta según sale."""

    def __init__(self, proposals, on_card, cli_path=None, model=None, settings=None):
        self.proposals, self.on_card, self.cli_path = proposals, on_card, cli_path
        self.model = model                      # si no, el de los ajustes (`modelo_onboarding`)
        self.settings = settings
        self.session_id = None                  # lo pone `OnboardingChat` (`session.json`)
        self.max_budget_usd = None              # y lo que queda del tope (N6)
        self.log = supply.SearchLog()           # lo que devolvió la web en este mensaje (N8)
        self._pending = {}                      # tool_use_id -> (herramienta, url o consulta)
        self._emit = None
        self._client = None

    # ----------------------------------------------------------- la web (N8)
    def permit(self, name, inp):
        """La entrada con la que se deja pasar una herramienta de Claude Code, o None si se
        deniega: la búsqueda tal cual, una página solo `http(s)`, nada más. Pura (§7, Citas)."""
        inp = dict(inp or {})
        if name == "WebSearch":
            return inp
        if name == "WebFetch":
            return inp if supply.host_of(inp.get("url")) else None
        return None

    async def can_use_tool(self, name, inp, _context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        allowed = self.permit(name, inp)
        if allowed is None:
            return PermissionResultDeny(message=i18n.t(
                "onboarding.web_no_http" if name == "WebFetch" else "onboarding.herramienta_no",
                nombre=name))
        return PermissionResultAllow(updated_input=allowed)

    def on_tool_use(self, block_id, name, inp):
        if name in WEB_TOOLS:
            key = "url" if name == "WebFetch" else "query"
            self._pending[block_id] = (name, str((inp or {}).get(key, "")))

    def on_tool_result(self, tool_use_id, text, is_error):
        kind, arg = self._pending.pop(tool_use_id, (None, None))
        if kind == "WebFetch":
            self.log.page(arg, text, is_error)
        elif kind == "WebSearch" and not is_error:
            self.log.search(arg, text)

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool
        from claude_agent_sdk.types import CanUseToolShadowedWarning

        cards = []
        self.log, self._pending = supply.SearchLog(), {}    # cada mensaje, su web (N8)
        tools = OnboardingTools(self.proposals, self.log, cards.append)
        agent = self

        def sdk_tool(name):
            @tool(name, DESCRIPTIONS[name], SCHEMAS[name])
            async def run(args):
                result = tools.call(name, args)
                while cards:                    # la tarjeta ya está en el chat: solo se enseña
                    await agent.on_card(cards.pop(0))
                return result
            return run

        # las nuestras van en allowed_tools a propósito (se validan dentro); el SDK avisa de
        # que no pasan por can_use_tool, y es lo que se quiere (como el de proveedores)
        warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)
        language = self.settings.language if self.settings is not None else "es"
        root = getattr(self.proposals.ws, "root", None)
        return ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT + "\n- " + i18n.t("agente.idioma", language),
            tools=list(WEB_TOOLS),
            can_use_tool=self.can_use_tool,
            mcp_servers={"onboarding": create_sdk_mcp_server(
                "onboarding", "0.0.1", [sdk_tool(n) for n in NAMES])},
            allowed_tools=list(ALLOWED),
            strict_mcp_config=True,
            setting_sources=[],
            cwd=str(root) if root is not None else None,    # `resume` busca la sesión aquí
            cli_path=self.cli_path,
            env=api_key.agent_env(self.settings),   # la clave, solo al proceso del agente (O9)
            model=agent_mod.agent_model(self.model, self.settings, ONBOARDING),
            resume=self.session_id,
            max_turns=MAX_TURNS,
            max_budget_usd=self.max_budget_usd,     # el SDK corta dentro del mensaje (N6)
        )


# ------------------------------------------------------------- la conversación (paso 2)
class OnboardingChat:
    """La conversación del onboarding de un workspace, entre `/ws/onboarding`
    (`onboarding_api`) y el agente: las mismas puertas que el chat de diseño (N11), con los
    ayudantes de `agent_chat`.

    - **Privacidad** (D169): sin *Entendido*, ninguna pregunta llega al agente.
    - **Tope** (N6): `tope_onboarding_usd` de los ajustes contra `.onboarding/usage.json`. Con
      lo gastado en el tope no empieza ningún mensaje (no hay *Seguir solo este mensaje*: se
      sube en *Ajustes → Agentes*, N13); dentro de uno, `max_budget_usd` es lo que queda.
    - **Una pregunta a la vez** por workspace, y *Parar* como en el de diseño.
    - **Empezar de nuevo** (`agent_reset`, N9, N12): la charla y la sesión fuera; el consumo y
      lo guardado se quedan.

    Las tarjetas de propuesta ya las escribe `Proposals.propose` en el chat: aquí solo se
    mandan a las ventanas. `make_agent(on_card)` da el agente (un `OnboardingAgent`)."""

    def __init__(self, proposals, settings, make_agent):
        self.proposals, self.store = proposals, proposals.store
        self.settings, self.make_agent = settings, make_agent
        self.clients = set()                  # las ventanas con `/ws/onboarding` abierto
        self.busy = False
        self.stop_grace = agent_chat.STOP_GRACE
        self._task = None
        self._agent = None
        self._stopping = False

    # ------------------------------------------------------------------ estado
    def state(self):
        total = self.store.usage()
        limit = self.settings.onboarding_limit_usd
        return {"usage": {"agents": {ONBOARDING: total}, "total": total}, "limit": limit,
                "remaining": round(max(0.0, limit - total["usd"]), 6),
                "privacy_seen": self.settings.privacy_seen, "busy": self.busy}

    def history_msg(self):
        return {"type": "agent_history", "events": self.store.history(), "state": self.state()}

    async def broadcast(self, msg):
        await send_all(self.clients, msg)

    async def send_state(self):
        await self.broadcast({"type": "agent_state", **self.state()})

    async def emit(self, event, keep=True):
        """Un evento del chat: a `chat.jsonl` (si `keep`) y a las ventanas."""
        event = {**event, "at": event.get("at") or round(time.time(), 3)}
        if keep:
            try:
                self.store.append(event)
            except (StorageError, OSError) as exc:    # el chat sigue; queda en el registro
                log.warning("no se pudo guardar el chat del onboarding: %s", exc)
        await self.broadcast({"type": "agent", **event})

    async def card(self, event):
        """Una tarjeta de propuesta recién hecha: ya está en el chat."""
        await self.emit(event, keep=False)

    async def proposal_changed(self, proposal_id):
        """Tras *Guardar* o *Descartar* (`onboarding_api`): el estado nuevo, a las ventanas."""
        try:
            p = self.store.proposals().get(proposal_id)
        except (StorageError, OSError):
            return
        if p is not None:
            await self.broadcast({"type": "agent", "kind": "proposal_state", "id": proposal_id,
                                  "estado": p.get("estado"), "at": round(time.time(), 3)})

    # ------------------------------------------------------------ mensajes del WS
    async def handle(self, ws, msg):
        kind = msg["type"]
        if kind == "agent_ask":
            await self.ask(ws, str(msg["text"]))
        elif kind == "agent_stop":
            await self.stop()
        elif kind == "agent_history":
            await ws.send_json(self.history_msg())
        elif kind == "agent_privacy_ok":
            self.settings.privacy_seen = True
            self.settings.save()
            await self.send_state()
        elif kind == "agent_reset":
            self.reset()
            await self.broadcast(self.history_msg())
        else:
            raise ValidationError(f"mensaje desconocido: {kind!r}")

    def reset(self):
        if self.busy:
            raise ValidationError(i18n.t("agente.ocupado"))
        self.store.reset()

    async def ask(self, ws, text):
        """Una pregunta. Sin *Entendido* o con el tope alcanzado no llega al agente: quien
        preguntó recibe la tarjeta con su texto, para volver a mandarla. Devuelve si empezó."""
        if self.busy:
            raise ValidationError(i18n.t("agente.ocupado"))
        card = {"type": "agent", "text": text}
        if not self.settings.privacy_seen:
            await ws.send_json({**card, "kind": "privacy",
                                "notice": i18n.t("agente.privacidad", self.settings.language)})
            return False
        used = self.store.usage()["usd"]
        limit = self.settings.onboarding_limit_usd
        if used >= limit:
            await ws.send_json({**card, "kind": "limit", "used": used, "limit": limit})
            return False
        self.busy = True                      # antes de crear la tarea: dos a la vez, no
        self._stopping = False
        self._task = asyncio.create_task(self._run(text, agent_chat.budget_for(used, limit)))
        return True

    def prompt(self, text):
        """Lo que recibe el agente: cómo acabaron sus propuestas desde su último mensaje (N5),
        una sola vez cada una, el Excel recién elegido (N7), también una vez, y la pregunta."""
        try:
            notes = self.store.take_notes()
        except (StorageError, OSError) as exc:
            log.warning("no se pudieron leer las propuestas del onboarding: %s", exc)
            notes = []
        try:
            excel = self.store.take_excel()     # el Excel recién elegido, una sola vez (N7)
        except (StorageError, OSError) as exc:
            log.warning("no se pudo leer el Excel del onboarding: %s", exc)
            excel = None
        parts = []
        if notes:
            lines = "\n".join(f"- {n['que']} ({n['id']}): {n['estado']}" for n in notes)
            parts.append(i18n.t("onboarding.notas", lineas=lines))
        if excel is not None:
            parts.append(excel_note(excel))
        return "\n\n".join(parts + [text])

    async def _run(self, text, budget):
        agent = None
        try:
            agent = self._agent = self.make_agent(self.card)
            agent.session_id = self.store.session_id()    # sigue la conversación (N9)
            agent.max_budget_usd = budget
            await self.emit({"kind": "user", "text": text})
            await agent.ask(self.prompt(text), self._on_event)
        except asyncio.CancelledError:        # *Parar* sin respuesta del SDK
            pass
        except api_key.MissingKey:            # «api_key» sin clave: dice dónde ponerla (O9)
            await self.emit({"kind": "error",
                             "text": i18n.t("agente.sin_api_key", self.settings.language)})
        except Exception as exc:              # noqa: BLE001 se enseña en el chat
            await self.emit({"kind": "error", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            self._keep_session(agent)
            stopped, self._stopping = self._stopping, False
            self._task = self._agent = None
            self.busy = False
            try:
                if stopped:
                    await self.emit({"kind": "stopped", "text": i18n.t("agente.parado")})
                await self.send_state()
            except Exception:                 # noqa: BLE001 sin ventanas a las que avisar
                pass

    def _keep_session(self, agent):
        try:
            self.store.set_session_id(getattr(agent, "session_id", None))
        except (StorageError, OSError) as exc:
            log.warning("no se pudo guardar la sesión del onboarding: %s", exc)

    async def _on_event(self, event):
        if event.get("kind") == "done":
            event = self._done(event)
        await self.emit(event)

    def _done(self, event):
        cumulative = event.pop("cost_usd", None)
        try:
            cost = self.store.message_cost(getattr(self._agent, "session_id", None), cumulative)
        except (StorageError, OSError) as exc:
            log.warning("no se pudo guardar la sesión del onboarding: %s", exc)
            cost = cumulative
        used = agent_chat.message_usage(event.pop("usage", None), cost)
        self._keep_session(self._agent)
        try:
            total = self.store.add_usage(used)
        except (StorageError, OSError) as exc:
            log.warning("no se pudo guardar el consumo del onboarding: %s", exc)
            total = self.store.usage()
        return agent_chat.close_done(event, self._stopping, used, total,
                                     self.settings.onboarding_limit_usd)

    async def stop(self):
        """*Parar*: el SDK corta el mensaje y lo dice su `done`; si no contesta en
        `stop_grace` s, o aún no había arrancado, se cancela la tarea."""
        task = self._task
        if not self.busy or task is None or task.done():
            raise ValidationError(i18n.t("agente.sin_mensaje"))
        if self._stopping:
            return
        self._stopping = True
        try:
            await self._agent.interrupt()
        except Exception:                     # noqa: BLE001 no hay con qué hablar: se cancela
            task.cancel()
            return
        asyncio.get_running_loop().call_later(
            self.stop_grace, lambda: None if task.done() else task.cancel())


def excel_note(excel):
    """El Excel elegido para el agente (N7): nombre, hojas, filas, columnas y la muestra."""
    sample = {"columnas": excel.get("columns") or [], "filas": excel.get("sample") or []}
    return i18n.t("onboarding.excel", nombre=excel.get("nombre") or excel.get("file"),
                  hoja=repr(excel.get("sheet") or ""), hojas=excel.get("sheets") or [],
                  filas=excel.get("rows"),
                  muestra=json.dumps(sample, ensure_ascii=False, default=str)[:6000])
