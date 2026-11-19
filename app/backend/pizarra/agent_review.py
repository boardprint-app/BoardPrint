"""El agente revisor (FF 6.1; docs/PLAN_V020.md §3, V2-V8; PLAN_PIZARRA D16, D17, D19, D73).

Un segundo agente que **contradice con criterio** lo que hay en la pizarra. Es otra clase
(`ReviewAgent`), no el de diseño con otro prompt (V2): sus herramientas son solo
`leer_pizarra`, `leer_bloque`, `leer_archivo`, `ver_zona`, `calcular` y `crear_postit` de
riesgo, pregunta o sugerencia (`TOOLS`). Nunca `proponer_cambio`, bloques, paquetes ni Office:
el servidor MCP del revisor se monta aquí entero, así que lo que se añada al de diseño no le
llega. Las opciones del SDK son las del de diseño: sin herramientas propias de Claude Code,
`strict_mcp_config`, sin ajustes del usuario, `cwd` de la pizarra y `env` de `api_key`.

**Aislado de verdad** (D16, V3): su sesión del SDK es `"revisor"` en `sessions.json`, su
conversación `agent/review.jsonl` y su consumo el agente `"revisor"` de `usage.json`, que
cuenta en el tope del proyecto (V7). Nunca recibe el chat ni la sesión del de diseño, ni las
propuestas de este (sus motivos son su razonamiento): lee la pizarra con los post-its de todos
y su estado, también los descartados, para no repetirlos (D73).

- **Post-its** (`tool_crear_postit`): firmados `agent:review`, nacen abiertos, con la regla de
  los números (D19) y como mucho `MAX_POSTITS` por revisión (el sexto se rechaza).
- **`calcular`** (V4): la vista previa del bloque (`Board.preview_job`, D177) con otros
  parámetros. Da el resultado y no escribe nada: ni la escena, ni el estado del bloque ni sus
  salidas guardadas. Una cifra que sale de ahí se cita como `calculo`, nunca como `bloque`.
- **Intrusividad** (V5, `[agentes] intrusividad_revisor`): `apagado` (no revisa), `a_demanda`
  (por defecto: el botón *Revisar*, `review_ask`) o `hitos` (además, al guardar una versión con
  nombre revisa lo cambiado desde la anterior con nombre, `AgentReview.milestone`).
- **Uno a la vez** (V6): comparte `agent_busy` y la conversación de `agent_chat` con el de
  diseño (privacidad, tope, *Parar*, `MissingKey`). Un hito que llega con el de diseño
  trabajando espera a que acabe (`AgentChat.queued`); uno sin ventanas abiertas no empieza.

WebSocket (la lista corta, en `server.py`):
cliente -> servidor
    {"type": "review_ask", "foco"?, "once"?}    una revisión; `foco` (hasta `FOCO_MAX`), en
                                                qué fijarse; `once`, como en `agent_ask`
    {"type": "review_cancel"}                   parar la revisión en curso
    {"type": "review_history"}                  pedir su conversación guardada
servidor -> cliente
    {"type": "agent", "agent": "revisor", "kind", "at", ...}   los eventos, como los del de
                        diseño (user|text|tool|tool_result|done|error|stopped; privacy y limit
                        solo a quien preguntó, con `foco` para reenviarla); `user` lleva `foco`
                        o `milestone` {version, name, previous, changes}
    {"type": "review_history", "events", "state", "agent"}    a quien lo pidió; `agent` es el
                        agent_state del proyecto
    {"type": "review_state", "intrusiveness", "model", "running", "postits"}   al acabar cada
                        revisión, y en `init` como `review`; postits: {abierto, aceptado,
                        descartado, total} de los suyos (también los que el ingeniero editó)
"""
import asyncio
import copy
import json
import logging

from pizarra import agent as agent_mod
from pizarra import agent_prompt, api_key, graph, i18n
from pizarra.agent import BLOCK_SCHEMA, POSTIT_SCHEMA, READ_SCHEMA, TOOL_CHARS, _error, _ok
from pizarra.agent_chat import Conversation
from pizarra.validation import ValidationError, check_param

log = logging.getLogger(__name__)

REVIEWER = "agent:review"      # el autor de lo que escribe (config.AGENT_AUTHORS)
REVIEW = "revisor"             # su sesión en sessions.json y su consumo en usage.json (V3)
REVIEW_CHAT = "review"         # su conversación: agent/review.jsonl
KINDS = ("riesgo", "pregunta", "sugerencia")
MAX_POSTITS = 5                # por revisión (§3 de PLAN_V020): el sexto se rechaza
FOCO_MAX = 500                 # caracteres del foco de una revisión
MILESTONE_CHARS = 4000         # lo cambiado desde la versión anterior, en el mensaje del hito
CALC_SECONDS = 30              # lo que puede tardar una vista previa de `calcular`
MAX_TURNS = 30
TOOLS = ("leer_pizarra", "leer_bloque", "leer_archivo", "ver_zona", "calcular", "buscar_libreria",
         "crear_postit")

SYSTEM_PROMPT = """Eres el revisor de una pizarra de ingeniería: un segundo par de ojos, \
aislado del agente de diseño. No ves su conversación ni la necesitas: juzgas el diseño por lo \
que hay en la pizarra (bloques con sus parámetros y salidas, post-its, textos, archivos y \
croquis).

Tu trabajo es contradecir con criterio: buscar lo que puede fallar (una hipótesis floja, un \
margen corto, un caso de carga olvidado, algo que no se puede fabricar con lo que hay, una \
cifra que no cuadra con otra) y decirlo en post-its. No diseñas ni cambias nada: no creas \
bloques, no conectas, no propones cambios ni ejecutas; solo lees, calculas en consulta y dejas \
post-its.

Reglas que no se pueden saltar:
- Como mucho 5 post-its por revisión, de tipo riesgo, pregunta o sugerencia: elige lo que más \
importa. Si no hay nada serio, no escribas ninguno y responde «Nada que objetar» con una \
frase de por qué: es una respuesta válida, y mejor que ruido.
- Ningún número sin fuente. Si un post-it lleva cifras, cita en `sources` de dónde salen: la \
salida de un bloque (kind "bloque", ref "bloque:<id>", su `cite` de leer_pizarra), una ficha \
de componente (kind "ficha"), un dato vivo con url y fecha (kind "dato_vivo"), un archivo de \
la pizarra leído con leer_archivo (kind "archivo", ref "archivo:<id de la tarjeta>", `file` si \
es de una carpeta y `where` con la página o la hoja y celda) o una cuenta tuya (kind \
"calculo", con `formula`, la cuenta escrita con sus valores, e `inputs`, las refs \
"bloque:<id>" de donde salen los datos). Si es una estimación tuya, estimate=true; nunca la \
presentes como dato.
- calcular da la vista previa de un bloque con otros parámetros y no guarda nada: úsalo para \
comprobar un «¿y si…?» (otra carga, otra longitud). Una cifra que salga de calcular se cita \
como kind "calculo", con `formula` diciendo el bloque, los parámetros que cambiaste y el \
resultado (te lo prepara su `cite_as`); nunca como "bloque", que es lo guardado.
- Los post-its descartados (`state` "descartado" en leer_pizarra) ya los rechazó el \
ingeniero: no los repitas, ni con otras palabras, salvo que tengas un motivo nuevo y lo digas. \
Tampoco repitas uno abierto que ya diga lo mismo, sea de quien sea.
- Ancla cada post-it (`anchor`) al elemento del que habla.
- Un post-it, una idea, concreta y breve: qué puede fallar, por qué y, si puedes, qué lo \
comprobaría.
- Las designaciones (6061-T6, M6, IP67, ISO 9409-1) no son cifras y no piden fuente.
- Si una herramienta rechaza tu post-it, lee el motivo y corrígelo; no lo repitas igual.

Antes de opinar, lee la pizarra con leer_pizarra; los campos enteros de un bloque, con \
leer_bloque; los archivos de la pizarra, con leer_archivo; lo dibujado, con ver_zona; los \
componentes de la librería y de los paquetes (con su stock), con buscar_libreria, cuya cifra se \
cita con su `cite_as` (kind "ficha"). Al \
acabar, responde con dos o tres líneas de lo que has dejado (o «Nada que objetar»)."""

PACKS_HEAD = ("Qué hacen los bloques de los paquetes cargados (para entenderlos; tú no creas "
              "ni cambias bloques):")


def system_prompt(settings=None, registry=None, profile=None):
    """El prompt del revisor: la base, el idioma de la interfaz en que responde (D180), el
    `agent.md` de los paquetes cargados (para entender sus bloques) y el perfil de fabricación
    del workspace (V8; sin él, nada). Nunca nada del agente de diseño (D16)."""
    from pizarra import blocks as blocks_mod
    language = "es" if settings is None else settings.language
    parts = [SYSTEM_PROMPT, "- " + i18n.t("agente.idioma", language)]
    packs = agent_prompt.pack_instructions(blocks_mod.REGISTRY if registry is None else registry)
    if packs:
        parts.append(PACKS_HEAD + "\n\n" + "\n\n".join(
            f"## {name} (`{pid}`)\n{text}" for pid, name, text in packs))
    parts += [p for p in (agent_prompt.profile_part(profile),) if p]
    return "\n\n".join(parts)


# ------------------------------------------------------------------ herramientas puras
REVIEW_POSTIT_SCHEMA = {
    **POSTIT_SCHEMA,
    "properties": {**{k: v for k, v in POSTIT_SCHEMA["properties"].items()
                      if k not in ("animacion", "pedida_por_usuario")},
                   "kind": {"type": "string", "enum": list(KINDS)}},
}
POSTIT_TOOL = ("Deja un post-it de riesgo, pregunta o sugerencia en la pizarra, anclado a lo que "
               "comenta. Si el texto lleva cifras, `sources` es obligatorio (o estimate=true). "
               f"Como mucho {MAX_POSTITS} por revisión.")
POSTIT_FIELDS = ("text", "kind", "sources", "estimate", "anchor")


def tool_crear_postit(board, args, created=0):
    """`crear_postit` del revisor: solo de `KINDS`, sin animación, firmado `agent:review` y,
    con `created` ya en `MAX_POSTITS`, rechazado. Devuelve (resultado, elementos nuevos o [])."""
    a = args if isinstance(args, dict) else {}
    if created >= MAX_POSTITS:
        return _error(f"Rechazado: ya has dejado {MAX_POSTITS} post-its en esta revisión, el "
                      "máximo. No dejes más: resume lo que has dejado."), []
    if a.get("kind") not in KINDS:
        return _error(f"Rechazado: el revisor solo deja post-its de {', '.join(KINDS)}; "
                      f"no {a.get('kind')!r}"), []
    if a.get("animacion") is not None:
        return _error("Rechazado: el revisor no pone animaciones; deja el post-it sin "
                      "`animacion`"), []
    clean = {k: a[k] for k in POSTIT_FIELDS if k in a}
    return agent_mod.tool_crear_postit(board, clean, auto_animations=False, author=REVIEWER)


CALC_SCHEMA = {
    "type": "object",
    "properties": {
        "bloque": {"type": "string", "description": "id del bloque (de leer_pizarra)"},
        "params": {"type": "object",
                   "description": "{nombre: valor} de los parámetros que cambian; los demás, "
                                  "como están"},
    },
    "required": ["bloque"],
}
CALC_TOOL = ("Calcula en consulta: la vista previa de un bloque con otros parámetros (y sus "
             "entradas de ahora). Da el resultado y no guarda nada en la pizarra. Solo en los "
             "bloques que tienen vista previa.")
CALC_NOTE = ("Consulta: no se ha guardado nada (ni los parámetros ni las salidas del bloque). "
             "Una cifra de aquí se cita como kind \"calculo\" con la `formula` de `cite_as`.")


def calc_job(board, args):
    """`(bloque, parámetros, función que calcula)` de `calcular`, comprobado: el bloque existe
    y tiene vista previa, y cada parámetro es suyo y de su tipo. `ValidationError` si no."""
    bid, params = args.get("bloque"), args.get("params") or {}
    if not isinstance(params, dict):
        raise ValidationError("`params` tiene que ser un objeto {nombre: valor}")
    el = graph.blocks_in(board.elements, board.registry).get(bid)
    if el is None:
        raise ValidationError(f"no hay ningún bloque {bid!r}: usa el `id` que devuelve "
                              "leer_pizarra")
    btype = board.registry.get(el["customData"]["blockType"])
    if btype is None:
        raise ValidationError(f"el bloque {bid!r} es de un tipo que no está cargado")
    if btype.preview is None:
        raise ValidationError(f"«{btype.title}» no tiene vista previa, así que no se calcula "
                              "en consulta: sus salidas guardadas, con leer_bloque")
    unknown = sorted(set(params) - set(btype.params))
    if unknown:
        raise ValidationError(f"{btype.title} no tiene los parámetros {', '.join(unknown)}; "
                              f"tiene: {', '.join(btype.params) or 'ninguno'}")
    for k, v in params.items():
        check_param(k, btype.params[k], v)
    params = copy.deepcopy(params)
    return bid, params, board.preview_job(bid, params)


def _formula(bid, params):
    changed = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in params.items())
    return (f"vista previa de bloque:{bid}" + (f" con {changed}" if changed else "")
            + ": <campo> = <valor>")


async def tool_calcular(board, args, seconds=CALC_SECONDS):
    """`calcular` (V4): la vista previa con otros parámetros, en un hilo y con plazo. Nunca
    escribe: `preview_job` lee copias del bloque y de sus entradas."""
    a = args if isinstance(args, dict) else {}
    try:
        bid, params, job = calc_job(board, a)
    except ValidationError as exc:
        return _error(f"No se calcula: {exc}")
    try:
        result = await asyncio.wait_for(asyncio.to_thread(job), seconds)
    except asyncio.TimeoutError:
        return _error(f"No se calcula: la vista previa tardó más de {seconds} s")
    except ValidationError as exc:
        return _error(f"No se calcula: {exc}")
    except Exception as exc:          # noqa: BLE001 un paquete con un fallo no tumba al revisor
        return _error(f"No se calcula: {type(exc).__name__}: {exc}")
    out = {"bloque": bid, "params": params, "resultado": result, "nota": CALC_NOTE,
           "cite_as": {"kind": "calculo", "formula": _formula(bid, params), "inputs": []}}
    text = json.dumps(out, ensure_ascii=False, default=str)
    if len(text) > TOOL_CHARS:
        cut = json.dumps(result, ensure_ascii=False, default=str)[:TOOL_CHARS // 2]
        out["resultado"] = cut + "… (recortado)"
        text = json.dumps(out, ensure_ascii=False, default=str)
    return _ok(text)


def review_stats(board):
    """Cómo acabaron los post-its del revisor (la métrica de §9 de PLAN_V020): los suyos y
    los que el ingeniero editó (que pasan a él con `origin`), por estado."""
    out = {"abierto": 0, "aceptado": 0, "descartado": 0}
    for e in board.elements:
        cd = e.get("customData") or {}
        if e.get("isDeleted") or cd.get("kind") != "postit" \
                or REVIEWER not in (cd.get("author"), cd.get("origin")):
            continue
        state = cd.get("state") if cd.get("state") in out else "abierto"
        out[state] += 1
    return {**out, "total": sum(out.values())}


# --------------------------------------------------------------------------- el agente
class ReviewAgent(agent_mod.DesignAgent):
    """El revisor de una pizarra. Del de diseño solo hereda cómo se habla con el SDK (`ask`,
    `interrupt`); sus opciones, y con ellas sus herramientas, son estas y ninguna más (V2)."""

    def __init__(self, board, on_elements, cli_path=None, model=None, request_zone=None,
                 settings=None):
        self.board, self.on_elements, self.cli_path = board, on_elements, cli_path
        self.settings = settings
        self.model = model                      # si no, el de los ajustes (`modelo_revisor`)
        self.request_zone = request_zone        # async (petición) -> PNG de una ventana (D171)
        self.session_id = None
        self.max_budget_usd = None              # lo pone `agent_chat` antes de cada revisión
        self.exclude_attachments = lambda: False
        self.created = 0                        # post-its de la revisión en curso
        self.decide = None
        self._emit = None
        self._client = None

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool
        from pizarra import agent_board_tools as abt

        board, agent = self.board, self
        self.created = 0                        # cada revisión empieza de cero

        @tool("leer_pizarra", "Lee la pizarra: bloques con parámetros, estado, salidas "
              "resumidas y cómo citarlos (`cite`), post-its de todos con su estado, textos y "
              "archivos.", {})
        async def leer(args):
            return agent_mod.tool_leer_pizarra(board, args, review=True)

        @tool("leer_bloque", "Las salidas de un bloque enteras: cada campo con su valor, unidad "
              "y etiqueta, y las listas completas, por tramos.", BLOCK_SCHEMA)
        async def leer_blq(args):
            return agent_mod.tool_leer_bloque(board, args)

        @tool("leer_archivo", "Lee un archivo de la pizarra (PDF, Word, Excel, PowerPoint o "
              "texto) en trozos con su página, diapositiva u hoja y celda (`where`), para "
              "citarlos. En una carpeta, sin `file`, da la lista de lo que entra.", READ_SCHEMA)
        async def leer_arch(args):
            return await asyncio.to_thread(agent_mod.tool_leer_archivo, board, args,
                                           bool(agent.exclude_attachments()))

        @tool("ver_zona", abt.DESCRIPTIONS["ver_zona"], abt.SCHEMAS["ver_zona"])
        async def ver_zona(args):
            return await abt.tool_ver_zona(board, args, agent.request_zone,
                                           bool(agent.exclude_attachments()))

        @tool("calcular", CALC_TOOL, CALC_SCHEMA)
        async def calcular(args):
            return await tool_calcular(board, args)

        @tool("buscar_libreria", agent_mod.LIBRARY_TOOL, agent_mod.LIBRARY_SCHEMA)
        async def buscar_lib(args):          # solo lee (V17)
            return await asyncio.to_thread(agent_mod.tool_buscar_libreria, board, args)

        @tool("crear_postit", POSTIT_TOOL, REVIEW_POSTIT_SCHEMA)
        async def crear(args):
            result, new = tool_crear_postit(board, args, agent.created)
            if new:
                agent.created += 1
                await agent.on_elements(new)
            return result

        server = create_sdk_mcp_server("pizarra", "0.0.1",
                                       [leer, leer_blq, leer_arch, ver_zona, calcular,
                                        buscar_lib, crear])
        return ClaudeAgentOptions(
            system_prompt=system_prompt(self.settings, board.registry,
                                        agent_mod.manufacturing_profile(board)),
            tools=[],
            mcp_servers={"pizarra": server},
            allowed_tools=[f"mcp__pizarra__{n}" for n in TOOLS],
            strict_mcp_config=True,
            setting_sources=[],
            cwd=str(board.dir),
            cli_path=self.cli_path,
            env=api_key.agent_env(self.settings),   # la clave, solo al proceso del agente (O9)
            model=agent_mod.agent_model(self.model, self.settings, REVIEW),
            resume=self.session_id,
            max_turns=MAX_TURNS,
            max_budget_usd=self.max_budget_usd,
        )


# ----------------------------------------------------------------- hitos (V5) y mensajes
def check_foco(foco):
    """El foco de una revisión: None o un texto de hasta `FOCO_MAX` caracteres."""
    if foco is None:
        return None
    if not isinstance(foco, str):
        raise ValidationError(i18n.t("revisor.foco_no_texto"))
    foco = " ".join(foco.split())
    if len(foco) > FOCO_MAX:
        raise ValidationError(i18n.t("revisor.foco_largo", max=FOCO_MAX))
    return foco or None


def _label(el):
    kind = el.get("kind")
    if kind == "postit":
        return f"post-it {el.get('postitKind') or ''} «{_short(el.get('text'))}»".replace("  ", " ")
    if kind == "block":
        return f"bloque {el.get('blockType')}"
    if kind == "text":
        return f"texto «{_short(el.get('text'))}»"
    return {"arrow": "flecha", "ink": "trazo de tinta", "image": "imagen"}.get(kind, kind or "dibujo")


def _short(text, n=80):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def change_lines(changes):
    """Lo cambiado entre dos versiones (`Board.compare`, `diff.py`) en una línea por cambio,
    sin lo que solo se movió o se estiró, hasta `MILESTONE_CHARS` caracteres."""
    out, size = [], 0
    verbs = {"added": "añadido", "removed": "quitado", "modified": "cambiado"}
    relevant = [c for c in changes or [] if c.get("change") in verbs]
    for i, c in enumerate(relevant):
        line = f"- {verbs[c['change']]} {_label(c.get('element') or {})} ({c.get('id')})"
        fields = c.get("fields") or {}
        parts = []
        for k, v in fields.items():
            if k == "params" and isinstance(v, dict):
                parts += [f"{p} {json.dumps(ab[0], ensure_ascii=False)} → "
                          f"{json.dumps(ab[1], ensure_ascii=False)}" for p, ab in v.items()]
            elif isinstance(v, list) and len(v) == 2:
                parts.append(f"{k} «{_short(v[0], 40)}» → «{_short(v[1], 40)}»")
        if parts:
            line += ": " + "; ".join(parts)
        if size + len(line) > MILESTONE_CHARS:
            out.append(f"- … y {len(relevant) - i} cambios más")
            break
        out.append(line)
        size += len(line) + 1
    return out


def milestone_of(board, version):
    """El hito de guardar `version` (V5): la versión, la anterior con nombre (o None) y lo
    cambiado desde ella, en líneas."""
    # `version` se acaba de guardar: la anterior es la más nueva de las demás con nombre (las
    # fechas van al segundo, así que no se busca su sitio en la lista)
    prev = next((v for v in board.list_versions()
                 if not v.get("auto") and v["id"] != version["id"]), None)
    lines = change_lines(board.compare(prev["id"], version["id"])) if prev else None
    return {"version": version["id"], "name": version.get("name"),
            "previous": {"id": prev["id"], "name": prev.get("name")} if prev else None,
            "lines": lines}


# Con perfil de fabricación, recordado en el mensaje de cada revisión: en el prompt de sistema
# solo, el revisor no lo usaba (e2e de FF 6.1: preguntó por máquinas que el perfil ya decía).
PROFILE_CHECK = ("Hay un perfil de fabricación del workspace en tus instrucciones. Contrasta con "
                 "él cada pieza y cada proceso de la pizarra: qué se puede hacer con sus máquinas "
                 "y materiales y qué habría que externalizar. Lo que choque con el perfil es un "
                 "riesgo; cítalo como estimación del perfil (estimate=true) y no preguntes lo que "
                 "el perfil ya contesta.")


def review_message(foco=None, milestone=None, profile=False):
    """Lo que recibe el revisor al empezar una revisión."""
    parts = ["Revisa la pizarra."]
    if milestone is not None:
        if milestone["previous"] is None:
            parts.append(f"Es un hito: el ingeniero ha guardado la versión «{milestone['name']}», "
                         "la primera con nombre. Revisa la pizarra entera.")
        else:
            changed = "\n".join(milestone["lines"]) or "- nada de contenido (solo se movió o se estiró algo)"
            parts.append(f"Es un hito: el ingeniero ha guardado la versión «{milestone['name']}». "
                         f"Lo cambiado desde la versión con nombre anterior "
                         f"(«{milestone['previous']['name']}»):\n{changed}\n"
                         "Revisa sobre todo eso, con el resto de la pizarra como contexto.")
    if foco:
        parts.append(f"El ingeniero pide que te fijes en esto: {foco}")
    if profile:
        parts.append(PROFILE_CHECK)
    parts.append(f"Como mucho {MAX_POSTITS} post-its; «Nada que objetar» es una respuesta válida.")
    return "\n\n".join(parts)


# ----------------------------------------------------------------------- conversación
class ReviewConversation(Conversation):
    """La conversación del revisor: sus eventos a `agent/review.jsonl`, su sesión (`revisor`),
    su consumo (`revisor`) y un `ReviewAgent` nuevo en cada revisión con su sesión y nunca otra."""
    key = REVIEW
    usage_agent = REVIEW
    animated = False

    def __init__(self, review):
        self.review = review

    def tag(self):
        return {"agent": REVIEW}

    def append(self, chat, event):
        chat.store.append(event, REVIEW_CHAT)

    def agent(self, chat):
        agent = self.review.make_agent()
        agent.session_id = chat.store.session_id(self.key)
        agent.exclude_attachments = (
            lambda: chat.store.settings().get("excluir_adjuntos") is True)
        return agent

    async def finished(self, chat):
        # Se llama con `agent_busy` aún puesto (antes de soltar al agente): la revisión ya ha
        # acabado, así que `running` va en falso (si no, `review_state` diría que sigue).
        await self.review.send_state(running=False)


class AgentReview:
    """Los mensajes `review_*` del WebSocket de un proyecto abierto y sus hitos. `chat` es su
    `AgentChat` (el de diseño: comparten puertas, tope y `agent_busy`, V6); `make_agent()` da
    un `ReviewAgent`; `broadcast(msg)` va a las ventanas del proyecto."""

    def __init__(self, chat, make_agent, broadcast):
        self.chat, self.make_agent, self.broadcast = chat, make_agent, broadcast
        self.conv = ReviewConversation(self)

    @property
    def board(self):
        return self.chat.session.board

    def running(self):
        return self.chat.session.agent_busy and self.chat._conv is self.conv

    def state(self, running=None):
        s = self.chat.settings
        return {"intrusiveness": s.review_intrusiveness, "model": s.agent_model(REVIEW),
                "running": self.running() if running is None else running,
                "postits": review_stats(self.board)}

    async def send_state(self, running=None):
        await self.broadcast({"type": "review_state", **self.state(running)})

    async def handle(self, ws, msg):
        kind = msg["type"]
        if kind == "review_ask":
            await self.ask(ws, msg.get("foco"), once=msg.get("once") is True)
        elif kind == "review_cancel":
            if not self.running():
                raise ValidationError(i18n.t("revisor.sin_revision"))
            await self.chat.stop()
        elif kind == "review_history":
            await ws.send_json({"type": "review_history",
                                "events": self.chat.store.history(REVIEW_CHAT),
                                "state": self.state(), "agent": self.chat.state()})
        else:
            raise ValidationError(f"mensaje desconocido: {kind!r}")

    async def ask(self, ws, foco=None, once=False, milestone=None):
        """Una revisión, a demanda (`ws`, la ventana que la pide) o de un hito (sin ventana).
        Apagado, no hay revisión. Devuelve si ha empezado."""
        if self.chat.settings.review_intrusiveness == "apagado":
            raise ValidationError(i18n.t("revisor.apagado"))
        foco = check_foco(foco)
        if milestone is not None:
            text = i18n.t("revisor.hito", nombre=milestone["name"])
        else:
            text = i18n.t("revisor.revisar_foco", foco=foco) if foco else i18n.t("revisor.revisar")
        extra = {**({"foco": foco} if foco else {}),
                 **({"milestone": {"version": milestone["version"], "name": milestone["name"],
                                   "previous": milestone["previous"],
                                   "changes": len(milestone["lines"] or [])}}
                    if milestone is not None else {})}
        return await self.chat.ask(ws, text, once=once, conv=self.conv,
                                   prompt=review_message(foco, milestone, self._has_profile()),
                                   extra=extra)

    def _has_profile(self):
        board = self.board
        return board is not None and bool((agent_mod.manufacturing_profile(board) or "").strip())

    async def milestone(self, version):
        """Al guardar una versión (V5): con `hitos` y una versión con nombre, una revisión de
        lo cambiado desde la anterior con nombre. Con el agente ocupado espera a que acabe.
        Devuelve "started", "queued" o None (no toca)."""
        if version.get("auto") or self.chat.settings.review_intrusiveness != "hitos":
            return None
        ms = milestone_of(self.board, version)

        async def start():
            if self.chat.settings.review_intrusiveness == "hitos":   # puede haber cambiado
                await self.ask(None, milestone=ms)

        if self.chat.session.agent_busy:
            self.chat.queued = start
            return "queued"
        return "started" if await self.ask(None, milestone=ms) else None
