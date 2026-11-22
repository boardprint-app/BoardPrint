"""La conversación del agente de onboarding (docs/PLAN_ONBOARDING.md §6, §7: N6, N8, N9, N10, N11).

Reglas que protegen:
- Tope (N6): con lo gastado ≥ el tope, preguntar se rechaza sin llamar al agente;
  `max_budget_usd` nunca pasa de lo que queda; el consumo de una sesión reanudada se cuenta
  por diferencia, no entero cada vez.
- Privacidad (N11): sin *Entendido*, ninguna pregunta llega al agente.
- Historial (N9): la conversación sigue tras cerrar y abrir; *Empezar de nuevo* borra charla y
  sesión y nunca lo guardado ni el consumo (N12).
- Propuestas (N5): el agente sabe una sola vez cómo acabó cada una; la tarjeta va a las
  ventanas sin escribirse dos veces en el chat.
- Aislamiento: el agente solo tiene sus herramientas, sin las de Claude Code ni ajustes; de
  las de Claude Code, solo `WebSearch` y `WebFetch`, y siempre por `can_use_tool`.
- Citas (N8): `WebFetch` a algo que no es `http(s)` se niega; una cita vale solo si está en lo
  que devolvió la web en ese mismo mensaje, leído del flujo.

El agente se sustituye: nunca se llama a Claude.

Ejecutar desde app/backend:  python -m unittest tests.test_onboarding_chat -v
"""
import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from pizarra import onboarding_api
from pizarra.agent_onboarding import ALLOWED, OnboardingAgent, OnboardingChat, OnboardingTools
from pizarra.library import WorkspaceLibrary
from pizarra.onboarding import ONBOARDING, OnboardingStore, Proposals
from pizarra.settings import Settings
from pizarra.storage import LocalWorkspace
from pizarra.supply_api import SupplyService
from pizarra.validation import ValidationError

try:
    import claude_agent_sdk as sdk
    SDK = True
except ImportError:
    SDK = False

PROFILE = "# Taller\n\n- Prusa MK4\n"
USO = {"input_tokens": 100, "output_tokens": 40}


class VentanaFalsa:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


class AgenteFalso:
    """Sustituto del `OnboardingAgent`: apunta con qué le preguntan; si el test lo pide,
    propone unas unidades con la herramienta de verdad; acaba con el acumulado de su sesión."""

    def __init__(self, test, on_card):
        self.test, self.on_card = test, on_card
        self.session_id = None
        self.max_budget_usd = None
        test.creados += 1

    async def ask(self, message, emit):
        t = self.test
        t.preguntas.append({"text": message, "budget": self.max_budget_usd,
                            "resume": self.session_id})
        if t.proponer:
            cards = []
            OnboardingTools(t.proposals, None, cards.append).call(
                "proponer_unidades", {"unidades": {"longitud": "cm"}, "motivo": "cm"})
            for c in cards:
                await self.on_card(c)
        await emit({"kind": "text", "text": f"respuesta a {message}"})
        if self.session_id is None:           # una sesión nueva acumula desde cero
            t.acumulado = 0.0
        self.session_id = "ses-1"
        t.acumulado += t.coste
        await emit({"kind": "done", "turns": 1, "seconds": 0.1, "subtype": "success",
                    "terminal_reason": "completed", "usage": USO, "cost_usd": t.acumulado})


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        self.ws.save_manufacturing_profile(PROFILE)
        self.settings = Settings.load(self.root / "settings.toml")
        self.settings.privacy_seen = True
        self.settings.onboarding_limit_usd = 1
        self.creados, self.preguntas = 0, []
        self.coste, self.acumulado, self.proponer = 0.25, 0.0, False
        self.chat = self.new_chat(self.ws)

    def new_chat(self, ws):
        lib = WorkspaceLibrary(ws, ())
        self.proposals = Proposals(ws, SupplyService(lambda: ws, None, lambda: lib), self.settings)
        chat = OnboardingChat(self.proposals, self.settings,
                              lambda on_card: AgenteFalso(self, on_card))
        self.ventana = VentanaFalsa()          # una ventana abierta, que recibe lo de todos
        chat.clients.add(self.ventana)
        return chat

    async def ask(self, text, chat=None):
        chat = chat or self.chat
        w = VentanaFalsa()
        await chat.handle(w, {"type": "agent_ask", "text": text})
        if chat._task is not None:
            await chat._task
        return w.sent

    def kinds(self):
        return [e["kind"] for e in self.chat.store.history()]


class ElTope(_Base):
    async def test_con_lo_gastado_en_el_tope_no_se_llama_al_agente(self):
        OnboardingStore(self.ws).add_usage({"usd": 1.0, "messages": 3})
        sent = await self.ask("configura el taller")
        self.assertEqual(self.creados, 0)
        self.assertEqual([m["kind"] for m in sent], ["limit"])
        self.assertEqual(sent[0]["text"], "configura el taller")    # para volver a mandarla
        self.assertEqual(self.kinds(), [])                           # ni al chat
        self.assertFalse(self.chat.busy)

    async def test_el_presupuesto_es_lo_que_queda_nunca_el_tope_entero(self):
        OnboardingStore(self.ws).add_usage({"usd": 0.3, "messages": 1})
        await self.ask("hola")
        self.assertAlmostEqual(self.preguntas[0]["budget"], 0.7)
        await self.ask("sigue")
        self.assertAlmostEqual(self.preguntas[1]["budget"], 0.45)   # 1 - 0,3 - 0,25

    async def test_la_sesion_reanudada_se_cuenta_por_diferencia(self):
        await self.ask("uno")
        await self.ask("dos")
        total = OnboardingStore(self.ws).usage()
        self.assertAlmostEqual(total["usd"], 0.5)        # 0,25 + 0,25, no 0,25 + 0,50
        self.assertEqual(total["messages"], 2)
        done = [e for e in self.chat.store.history() if e["kind"] == "done"]
        self.assertEqual([d["reason"] for d in done], ["ok", "ok"])
        self.assertAlmostEqual(done[-1]["total"]["usd"], 0.5)
        self.assertEqual(done[-1]["limit"], 1)
        state = self.chat.state()
        self.assertAlmostEqual(state["remaining"], 0.5)
        self.assertEqual(set(state["usage"]["agents"]), {ONBOARDING})


class LaPrivacidad(_Base):
    async def test_sin_entendido_no_llega_al_agente_y_con_el_si(self):
        self.settings.privacy_seen = False
        sent = await self.ask("hola")
        self.assertEqual([m["kind"] for m in sent], ["privacy"])
        self.assertTrue(sent[0]["notice"])
        self.assertEqual(self.creados, 0)
        await self.chat.handle(VentanaFalsa(), {"type": "agent_privacy_ok"})
        self.assertTrue(Settings.load(self.root / "settings.toml").privacy_seen)
        await self.ask("hola")
        self.assertEqual(self.creados, 1)


class ElHistorial(_Base):
    async def test_sigue_tras_cerrar_y_abrir(self):
        await self.ask("configura el taller")
        chat = self.new_chat(LocalWorkspace.open(self.root / "ws"))    # se reinicia la app
        w = VentanaFalsa()
        await chat.handle(w, {"type": "agent_history"})
        self.assertEqual([e["kind"] for e in w.sent[0]["events"]], ["user", "text", "done"])
        await self.ask("sigue", chat)
        self.assertEqual(self.preguntas[-1]["resume"], "ses-1")

    async def test_empezar_de_nuevo_borra_charla_y_sesion_y_nunca_el_consumo_ni_lo_guardado(self):
        await self.ask("configura el taller")
        await self.chat.handle(VentanaFalsa(), {"type": "agent_reset"})
        self.assertEqual(self.kinds(), [])
        last = self.ventana.sent[-1]                                  # a todas las ventanas
        self.assertEqual((last["type"], last["events"]), ("agent_history", []))
        self.assertAlmostEqual(OnboardingStore(self.ws).usage()["usd"], 0.25)
        self.assertEqual(self.ws.load_manufacturing_profile(), PROFILE)
        await self.ask("otra vez")
        self.assertIsNone(self.preguntas[-1]["resume"])              # conversación nueva
        self.assertAlmostEqual(OnboardingStore(self.ws).usage()["usd"], 0.5)

    async def test_ni_empezar_de_nuevo_ni_otra_pregunta_con_el_agente_ocupado(self):
        self.chat.busy = True
        with self.assertRaises(ValidationError):
            await self.chat.handle(VentanaFalsa(), {"type": "agent_reset"})
        with self.assertRaises(ValidationError):
            await self.chat.handle(VentanaFalsa(), {"type": "agent_ask", "text": "x"})


class LasPropuestas(_Base):
    async def test_la_tarjeta_va_a_las_ventanas_y_al_chat_una_sola_vez(self):
        self.proponer = True
        await self.ask("trabajo en cm")
        cards = [m for m in self.ventana.sent if m.get("kind") == "proposal"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(self.kinds().count("proposal"), 1)

    async def test_el_agente_sabe_una_sola_vez_como_acabo_cada_propuesta(self):
        self.proponer = True
        await self.ask("trabajo en cm")
        pid = next(iter(self.proposals.store.proposals()))
        await self.proposals.discard(pid)
        self.proponer = False
        await self.ask("¿y ahora?")
        self.assertIn(pid, self.preguntas[-1]["text"])
        self.assertIn("descartada", self.preguntas[-1]["text"])
        self.assertTrue(self.preguntas[-1]["text"].endswith("¿y ahora?"))
        await self.ask("otra")
        self.assertEqual(self.preguntas[-1]["text"], "otra")
        # lo que ve el usuario en el chat es su pregunta, no la nota
        users = [e["text"] for e in self.chat.store.history() if e["kind"] == "user"]
        self.assertEqual(users, ["trabajo en cm", "¿y ahora?", "otra"])


class ElWebSocket(unittest.TestCase):
    """N10: `/ws/onboarding` da la charla al abrir, contesta lo que no vale sin cerrarse, y
    sin workspace avisa y cierra; guardar por REST avisa a las ventanas del chat."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        self.settings = Settings.load(self.root / "settings.toml")
        lib = WorkspaceLibrary(self.ws, ())
        self.supply = SupplyService(lambda: self.ws, None, lambda: lib)
        self.workspace = self.ws

    def client(self, ok=True):
        app = FastAPI()

        def need():
            if self.workspace is None:
                raise HTTPException(503, "ningún workspace abierto")
            return self.workspace
        onboarding_api.register(app, need_workspace=need, settings=self.settings,
                                sessions=None, broadcast=None, supply=self.supply,
                                ws_ok=lambda w: ok)
        return TestClient(app)

    def test_al_abrir_da_la_charla_y_un_mensaje_malo_no_la_cierra(self):
        Proposals(self.ws, self.supply).propose("unidades", {"longitud": "cm"}, "cm")
        with self.client().websocket_connect("/ws/onboarding") as w:
            first = w.receive_json()
            self.assertEqual(first["type"], "agent_history")
            self.assertEqual([e["kind"] for e in first["events"]], ["proposal"])
            self.assertIn("remaining", first["state"])
            w.send_text("esto no es json")
            self.assertEqual(w.receive_json()["type"], "error")
            w.send_json({"type": "scene"})
            self.assertEqual(w.receive_json()["type"], "error")
            w.send_json({"type": "agent_history"})
            self.assertEqual(w.receive_json()["type"], "agent_history")

    def test_guardar_avisa_a_las_ventanas_del_chat(self):
        event = Proposals(self.ws, self.supply).propose("unidades", {"longitud": "cm"}, "cm")
        c = self.client()
        with c.websocket_connect("/ws/onboarding") as w:
            w.receive_json()
            self.assertEqual(c.post(f"/api/onboarding/proposals/{event['id']}/discard").status_code,
                             200)
            msg = w.receive_json()
            self.assertEqual((msg["kind"], msg["id"], msg["estado"]),
                             ("proposal_state", event["id"], "descartada"))

    def test_sin_workspace_avisa_y_cierra(self):
        self.workspace = None
        with self.client().websocket_connect("/ws/onboarding") as w:
            self.assertEqual(w.receive_json()["type"], "error")

    def test_sin_token_no_se_abre(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.client(ok=False).websocket_connect("/ws/onboarding") as w:
                w.receive_json()


@unittest.skipUnless(SDK, "falta claude_agent_sdk")
class ElAgenteAislado(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        lib = WorkspaceLibrary(self.ws, ())
        self.proposals = Proposals(self.ws, SupplyService(lambda: self.ws, None, lambda: lib))
        self.settings = Settings.load(self.root / "settings.toml")

    def options(self, agent):
        tools = []

        def servidor(name, version, ts):
            tools[:] = ts
            return {"type": "sdk", "name": name, "instance": None}
        with mock.patch.object(sdk, "create_sdk_mcp_server", servidor):
            opts = agent._options()
        return {t.name: t for t in tools}, opts

    def test_solo_sus_herramientas_sin_ajustes_y_con_su_modelo_y_lo_que_queda(self):
        cards = []

        async def on_card(ev):
            cards.append(ev)
        agent = OnboardingAgent(self.proposals, on_card, settings=self.settings)
        agent.session_id, agent.max_budget_usd = "ses-9", 0.4
        with mock.patch.dict("os.environ", {"PIZARRA_MODEL": ""}):
            tools, opts = self.options(agent)
        self.assertEqual(set(tools), {"leer_configuracion", "proponer_perfil",
                                      "proponer_proveedores", "proponer_unidades",
                                      "proponer_importacion"})
        self.assertEqual(opts.allowed_tools, ALLOWED)
        self.assertEqual(opts.tools, ["WebSearch", "WebFetch"])
        self.assertEqual(opts.can_use_tool, agent.can_use_tool)
        self.assertFalse(set(opts.tools) & set(opts.allowed_tools))    # nunca sin preguntar
        self.assertEqual(opts.setting_sources, [])
        self.assertTrue(opts.strict_mcp_config)
        self.assertEqual(list(opts.mcp_servers), ["onboarding"])
        self.assertEqual(opts.model, "sonnet")
        self.assertEqual((opts.resume, opts.max_budget_usd), ("ses-9", 0.4))
        self.assertEqual(opts.cwd, str(self.ws.root))
        r = asyncio.run(tools["proponer_unidades"].handler(
            {"unidades": {"longitud": "cm"}, "motivo": "cm"}))
        self.assertFalse(r.get("is_error"), r)
        self.assertEqual([c["kind"] for c in cards], ["proposal"])


    def test_cada_mensaje_empieza_sin_web_y_sus_herramientas_leen_la_de_ese_mensaje(self):
        async def on_card(ev):
            pass
        agent = OnboardingAgent(self.proposals, on_card, settings=self.settings)
        self.ws.save_manufacturing_profile(PROFILE)
        agent.on_tool_use("viejo", "WebFetch", {"url": PAGE})
        agent.on_tool_result("viejo", FICHA_WEB, False)
        tools, _ = self.options(agent)                    # un mensaje nuevo
        self.assertEqual(agent.log.pages, {})
        args = {"texto": PROFILE + "- Haas Mini Mill\n", "motivo": "x",
                "fuentes": [{"url": PAGE, "cita": "Husillo 6000 rpm"}]}
        r = asyncio.run(tools["proponer_perfil"].handler(args))
        self.assertTrue(r.get("is_error"))                # la página era del mensaje anterior
        agent.on_tool_use("t1", "WebFetch", {"url": PAGE})
        agent.on_tool_result("t1", FICHA_WEB, False)
        r = asyncio.run(tools["proponer_perfil"].handler(args))
        self.assertFalse(r.get("is_error"), r)

PAGE = "https://www.ejemplo-maquinas.com/haas-mini-mill"
FICHA_WEB = "Haas Mini Mill. Recorridos X/Y/Z: 406 x 305 x 254 mm. Husillo 6000 rpm."


class LaWebConCita(unittest.TestCase):
    """N8: lo que puede abrir el agente y de dónde sale una cita que vale."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        self.ws.save_manufacturing_profile(PROFILE)
        lib = WorkspaceLibrary(self.ws, ())
        self.proposals = Proposals(self.ws, SupplyService(lambda: self.ws, None, lambda: lib))

        async def on_card(ev):
            pass
        self.agent = OnboardingAgent(self.proposals, on_card)

    def test_solo_paginas_http_y_ninguna_otra_herramienta_de_claude_code(self):
        permit = self.agent.permit
        self.assertEqual(permit("WebSearch", {"query": "Haas Mini Mill recorridos"}),
                         {"query": "Haas Mini Mill recorridos"})
        self.assertEqual(permit("WebFetch", {"url": PAGE, "prompt": "x"}), {"url": PAGE, "prompt": "x"})
        for url in ("file:///C:/Windows/win.ini", "ftp://ejemplo.com/a", "javascript:alert(1)",
                    "ejemplo.com/sin-esquema", ""):
            self.assertIsNone(permit("WebFetch", {"url": url}), url)
        for name in ("Bash", "Read", "Write", "Edit", "Glob", "Task"):
            self.assertIsNone(permit(name, {}), name)

    def propose(self, cita):
        tools = OnboardingTools(self.proposals, self.agent.log)
        out = tools.call("proponer_perfil", {
            "texto": PROFILE + "- Haas Mini Mill: 406 x 305 x 254 mm\n", "motivo": "la fresadora",
            "fuentes": [{"url": PAGE, "cita": cita}]})
        return out.get("is_error", False), out["content"][0]["text"]

    def test_una_cita_vale_si_esta_en_la_pagina_que_devolvio_el_flujo(self):
        self.agent.on_tool_use("t1", "WebFetch", {"url": PAGE})
        self.agent.on_tool_result("t1", FICHA_WEB, False)
        bad, text = self.propose("Recorridos X/Y/Z: 406 x 305 x 254 mm")
        self.assertFalse(bad, text)

    def test_una_cita_que_no_esta_o_de_una_pagina_que_fallo_rechaza_la_propuesta(self):
        self.agent.on_tool_use("t1", "WebFetch", {"url": PAGE})
        self.agent.on_tool_result("t1", FICHA_WEB, False)
        bad, _ = self.propose("Recorridos X/Y/Z: 762 x 406 x 508 mm")     # inventada
        self.assertTrue(bad)
        self.agent.on_tool_use("t2", "WebFetch", {"url": PAGE + "-2"})
        self.agent.on_tool_result("t2", "403 Forbidden " + FICHA_WEB, True)
        self.assertNotIn(PAGE + "-2", self.agent.log.pages)
        self.assertEqual(self.ws.load_onboarding_chat(), [])              # ninguna tarjeta

    def test_lo_que_no_es_la_web_no_entra_en_el_registro(self):
        self.agent.on_tool_use("t1", "mcp__onboarding__leer_configuracion", {})
        self.agent.on_tool_result("t1", FICHA_WEB, False)
        self.assertEqual((self.agent.log.pages, self.agent.log.searches), ({}, []))
        bad, _ = self.propose("Recorridos X/Y/Z: 406 x 305 x 254 mm")
        self.assertTrue(bad)


if __name__ == "__main__":
    unittest.main()
