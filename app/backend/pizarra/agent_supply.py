"""El agente de proveedores: busca dónde comprar una ficha (docs/PLAN_APROVISIONAMIENTO.md §4, A1, A5,
A9, R1).

Una conversación nueva en cada búsqueda (sin `resume`), con tres herramientas:

- `WebSearch` y `WebFetch` de Claude Code, que **siempre pasan por `can_use_tool`** (no van en
  `allowed_tools`, así que el CLI pregunta cada vez): a `WebSearch` se le sobrescribe
  `allowed_domains` con los dominios de los proveedores de la búsqueda, pida lo que pida, y un
  `WebFetch` a un host que no es de ninguno se deniega. Cualquier otra herramienta, denegada.
- `apuntar_oferta` (MCP propio): valida la oferta con `supply.check_agent_offer` contra lo que
  devolvieron las herramientas en esta búsqueda (`supply.SearchLog`, R1). Si no vale, el agente
  recibe el motivo y no se guarda.

Lo que devuelve cada herramienta se lee del flujo (`ToolUseBlock` -> `ToolResultBlock` por
`tool_use_id`), no de lo que el agente diga que leyó. El modelo es el del agente
«proveedores» (Haiku por defecto, A5) y el tope, `search_limit_usd` (0,25 USD): el SDK corta, y
lo apuntado hasta entonces se queda.

El agente no escribe nada en disco: `run` devuelve lo apuntado, y quien lo lanza
(`supply_api`, o la herramienta del de diseño) lo guarda con `supply.replace_agent_offers`.
"""
import json
import logging
import warnings

from pizarra import api_key, supply
from pizarra.agent import agent_model
from pizarra.validation import ValidationError

log = logging.getLogger(__name__)

SUPPLY = "proveedores"          # el agente en los ajustes (modelo) y en usage.json (A11)
MAX_TURNS = 20
FICHA_CHARS = 2500              # lo que entra de la ficha en el mensaje
WEB_TOOLS = ("WebSearch", "WebFetch")

SYSTEM_PROMPT = """Eres el agente de proveedores de BoardPrint. Buscas dónde se compra un \
componente, solo en los proveedores que te dan y por su orden de preferencia, y apuntas cada \
oferta con `apuntar_oferta`.

Reglas:
- Busca la referencia del fabricante (y el fabricante) en cada proveedor por orden. Usa primero \
WebSearch; abre una página con WebFetch solo si la búsqueda no da el precio. Si una página da \
error (403, sin respuesta), no la reintentes: sigue con otra o con el buscador.
- Cuando un proveedor tenga una oferta exacta con precio, no hace falta seguir con los demás.
- `coincidencia`: «exacta» si es la misma referencia del fabricante de la ficha (un sufijo de \
embalaje como PBF o -ND cuenta como exacta si el resto es igual; dilo en `nota`). Un producto de \
otra marca o referencia que hace lo mismo es «equivalente»: apúntalo solo si no hay exacta en \
ninguno, y di en `nota` en qué difiere.
- `via`: «pagina» si el precio está en una página que abriste con WebFetch; «buscador» si sale \
en lo que devolvió WebSearch. La `url` es la del producto en ese proveedor.
- `cita`: copia literal, sin cambiar nada, la frase entera del texto que te devolvió la \
herramienta con el precio (o la disponibilidad), entre 20 y 200 caracteres: que se entienda \
sola, nunca un trozo cortado a media palabra. Nunca apuntes una cifra que no esté en lo que te \
devolvió una herramienta; si no hay precio, deja `precio` vacío y apunta la disponibilidad.
- `precio` es el unitario de la cantidad más pequeña que se puede pedir (`por_cantidad`), no el \
más barato de los tramos (los demás, en `nota`), y tiene que estar escrito en la `cita`. Si \
salen dos precios (con y sin IVA), el sin IVA. `moneda` en código ISO (EUR, GBP, \
USD). Una URL de categoría o de búsqueda no vale como `url` si hay la del producto.
- `disponibilidad`: pocas palabras («En stock: 1.250 uds.», «Bajo pedido»). `nota`: una frase \
como mucho (con o sin IVA, tramos, sufijo de la referencia).
- Si `apuntar_oferta` te devuelve un error, corrige lo que dice o déjala.
- Termina con una línea que resuma lo encontrado."""

OFFER_TOOL = ("Apunta una oferta de un proveedor para la ficha. Se comprueba contra lo que "
              "devolvieron WebSearch y WebFetch en esta búsqueda: la cita tiene que estar tal "
              "cual, y la URL abierta (via pagina) o en los resultados (via buscador).")
OFFER_SCHEMA = {
    "type": "object",
    "properties": {
        "coincidencia": {"type": "string", "enum": list(supply.MATCHES)},
        "url": {"type": "string"},
        "via": {"type": "string", "enum": list(supply.VIAS)},
        "cita": {"type": "string"},
        "referencia": {"type": "string"},
        "fabricante": {"type": "string"},
        "precio": {"type": ["number", "null"]},
        "moneda": {"type": ["string", "null"]},
        "por_cantidad": {"type": ["integer", "null"]},
        "plazo_dias": {"type": ["integer", "null"]},
        "disponibilidad": {"type": "string"},
        "nota": {"type": "string"},
    },
    "required": ["coincidencia", "url", "via", "cita", "referencia"],
}


def ficha_text(clave, data):
    """Lo que el agente sabe de la ficha: `[meta]` y los valores, sin las fuentes largas."""
    meta = dict(data.get("meta") or {})
    meta.pop("notes", None)
    values = {k: (v.get("v") if isinstance(v, dict) else v)
              for k, v in (data.get("values") or {}).items()}
    text = json.dumps({"clave": clave, "meta": meta, "values": values}, ensure_ascii=False,
                      default=str)
    return text[:FICHA_CHARS]


def user_message(clave, data, providers):
    lines = [f"{i + 1}. {p['nombre']}: {p['dominio']}" for i, p in enumerate(providers)]
    return ("Busca dónde comprar esta ficha:\n" + ficha_text(clave, data) +
            "\n\nProveedores, por orden de preferencia:\n" + "\n".join(lines))


def _tool_text(block):
    c = block.content
    if isinstance(c, str):
        return c
    return "".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))


class SupplyAgent:
    def __init__(self, clave, data, providers, settings=None, cli_path=None, model=None,
                 budget_usd=None, now=None):
        if not providers:
            raise ValueError("sin proveedores")
        self.clave, self.data = clave, data
        self.providers = providers
        self.domains = [p["dominio"] for p in providers]
        self.settings = settings
        self.cli_path = cli_path
        self.model = model
        self.budget_usd = budget_usd or (settings.search_limit_usd if settings is not None
                                         else supply.DEFAULT_SEARCH_BUDGET_USD)
        self.now = now
        self.log = supply.SearchLog()
        self.found = []                 # ofertas validadas
        self.rejected = []              # (motivo) de las que no valieron
        self._pending = {}              # tool_use_id -> (herramienta, url o consulta)
        self._client = None

    # ---------------------------------------------------------------- permisos (A1)
    async def can_use_tool(self, name, inp, _context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        decision = self.decide(name, inp)
        if decision is None:
            return PermissionResultDeny(message=self.denied_message(name))
        return PermissionResultAllow(updated_input=decision)

    def decide(self, name, inp):
        """La entrada con la que se deja pasar una herramienta, o None si se deniega. Pura: es
        lo que fijan los tests (§6, «Dominios»)."""
        inp = dict(inp or {})
        if name == "WebSearch":
            inp["allowed_domains"] = list(self.domains)
            inp.pop("blocked_domains", None)
            return inp
        if name == "WebFetch":
            return inp if supply.domain_of(inp.get("url"), self.domains) else None
        return None

    def denied_message(self, name):
        if name == "WebFetch":
            return ("Ese dominio no es de ninguno de los proveedores: " +
                    ", ".join(self.domains))
        return "Herramienta no permitida."

    # ---------------------------------------------------------------- apuntar (R1)
    def note_offer(self, args):
        """La oferta que manda el agente: validada y apuntada, o el motivo."""
        try:
            offer = supply.check_agent_offer(args, self.clave, self.providers, self.log, self.now)
        except ValidationError as exc:
            self.rejected.append(str(exc))
            return False, str(exc)
        self.found.append(offer)
        return True, offer

    def _options(self):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool
        from claude_agent_sdk.types import CanUseToolShadowedWarning

        @tool("apuntar_oferta", OFFER_TOOL, OFFER_SCHEMA)
        async def apuntar(args):
            ok, result = self.note_offer(args)
            text = (json.dumps({"apuntada": result["id"], "proveedor": result["proveedor"]},
                               ensure_ascii=False) if ok else "No se apunta: " + result)
            return {"content": [{"type": "text", "text": text}], **({} if ok else {"is_error": True})}

        server = create_sdk_mcp_server(SUPPLY, "0.0.1", [apuntar])
        # `apuntar_oferta` va en allowed_tools a propósito: es nuestra y se valida dentro; el
        # SDK avisa de que no pasa por can_use_tool, y es lo que se quiere
        warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)
        return ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            tools=list(WEB_TOOLS),
            mcp_servers={SUPPLY: server},
            allowed_tools=[f"mcp__{SUPPLY}__apuntar_oferta"],
            can_use_tool=self.can_use_tool,
            strict_mcp_config=True,
            setting_sources=[],
            cli_path=self.cli_path,
            env=api_key.agent_env(self.settings) if self.settings is not None else {},
            model=agent_model(self.model, self.settings, SUPPLY),
            max_turns=MAX_TURNS,
            max_budget_usd=self.budget_usd,
        )

    # ---------------------------------------------------------------- el flujo
    def on_tool_use(self, block_id, name, inp):
        if name == "WebFetch":
            self._pending[block_id] = ("WebFetch", (inp or {}).get("url", ""))
        elif name == "WebSearch":
            self._pending[block_id] = ("WebSearch", (inp or {}).get("query", ""))

    def on_tool_result(self, tool_use_id, text, is_error):
        kind, arg = self._pending.pop(tool_use_id, (None, None))
        if kind == "WebFetch":
            self.log.page(arg, text, bool(is_error))
        elif kind == "WebSearch" and not is_error:
            self.log.search(arg, text)
        return kind, arg

    async def run(self, emit=None):
        """La búsqueda entera. `emit({kind, ...})` va diciendo lo que hace: `search` (consulta),
        `fetch` (url, ok), `offer` (la oferta), `rejected` (motivo), `text`. Devuelve
        {ofertas, consultas, abiertas, fallidas, rechazadas, cost_usd, subtype, texto}."""
        from claude_agent_sdk import (AssistantMessage, ClaudeSDKClient, ResultMessage,
                                      TextBlock, ToolResultBlock, ToolUseBlock, UserMessage)

        async def say(event):
            if emit is not None:
                await emit(event)

        result = {"cost_usd": 0.0, "subtype": None, "texto": ""}
        async with ClaudeSDKClient(options=self._options()) as client:
            self._client = client
            try:
                await client.query(user_message(self.clave, self.data, self.providers))
                async for m in client.receive_response():
                    if isinstance(m, AssistantMessage):
                        for b in m.content:
                            if isinstance(b, ToolUseBlock):
                                self.on_tool_use(b.id, b.name, b.input)
                                if b.name == "WebSearch":
                                    await say({"kind": "search", "query": b.input.get("query")})
                            elif isinstance(b, TextBlock) and b.text.strip():
                                result["texto"] = b.text.strip()
                                await say({"kind": "text", "text": b.text.strip()})
                    elif isinstance(m, UserMessage) and isinstance(m.content, list):
                        for b in m.content:
                            if isinstance(b, ToolResultBlock):
                                n_found, n_rej = len(self.found), len(self.rejected)
                                kind, arg = self.on_tool_result(b.tool_use_id, _tool_text(b),
                                                                b.is_error)
                                if kind == "WebFetch":
                                    await say({"kind": "fetch", "url": arg,
                                               "ok": arg in self.log.pages})
                                if len(self.found) > n_found:
                                    await say({"kind": "offer", "offer": self.found[-1]})
                                if len(self.rejected) > n_rej:
                                    await say({"kind": "rejected", "reason": self.rejected[-1]})
                    elif isinstance(m, ResultMessage):
                        result.update(cost_usd=float(m.total_cost_usd or 0.0),
                                      subtype=m.subtype, usage=m.usage)
            finally:
                self._client = None
        result.update(ofertas=list(self.found), consultas=list(self.log.queries),
                      abiertas=sorted(self.log.pages), fallidas=sorted(self.log.failed),
                      rechazadas=list(self.rejected))
        return result

    async def interrupt(self):
        if self._client is not None:
            await self._client.interrupt()
