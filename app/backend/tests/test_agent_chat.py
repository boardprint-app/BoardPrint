"""La conversación con el agente de diseño (FF 4.6 paso 1; plan §10, «Conversación y consumo
(D164, D168)» y «Privacidad (D169)»).

Reglas que protegen:
- El chat y la sesión siguen tras reiniciar el backend; restaurar una versión nunca toca
  `agent/`.
- El consumo suma cada mensaje en su agente y su proyecto, nunca en otro.
- Con el tope alcanzado ningún mensaje empieza; *Seguir solo este mensaje* deja pasar uno solo;
  `max_budget_usd` es siempre lo que queda, nunca el tope entero.
- *Parar* deja lo hecho y libera al agente.
- Con *Excluir adjuntos*, `leer_archivo` nunca lee y el agente recibe el motivo; el aviso de
  privacidad sale solo hasta que se pulsa *Entendido*.

El agente se sustituye: nunca se llama a Claude. Los que pasan por el `DesignAgent` de verdad
sustituyen el cliente del SDK y se saltan sin `claude_agent_sdk` (el job básico del CI).
"""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pizarra import agent as agent_mod
from pizarra import agent_chat
from pizarra.agent_chat import DESIGN, AgentChat, AgentStore, message_usage
from pizarra.board import Board
from pizarra.sessions import Session
from pizarra.settings import Settings
from pizarra.storage import InvalidName, LocalWorkspace
from pizarra.validation import ValidationError

try:
    import claude_agent_sdk as sdk
    SDK = True
except ImportError:
    SDK = False

USO = {"input_tokens": 100, "output_tokens": 40, "cache_creation_input_tokens": 10,
       "cache_read_input_tokens": 3000, "service_tier": "standard"}


class VentanaFalsa:
    """Lo que el servidor llama de un WebSocket: lo apunta."""
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


class AgenteFalso:
    """Sustituto de DesignAgent: apunta con qué le preguntan y acaba como diga `done`."""
    def __init__(self, test):
        self.test = test
        self.session_id = None
        self.max_budget_usd = None
        test.creados.append(self)

    async def ask(self, message, emit):
        self.test.preguntas.append({"text": message, "budget": self.max_budget_usd,
                                    "resume": self.session_id})
        await emit({"kind": "text", "text": f"respuesta a {message}"})
        self.session_id = "ses-1"
        await emit({"kind": "done", "turns": 1, "seconds": 0.1, "subtype": self.test.subtype,
                    "terminal_reason": "completed", "usage": USO, "cost_usd": self.test.coste})


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings_path = self.tmp / "settings.toml"
        self.settings = Settings.load(self.settings_path)
        self.settings.privacy_seen = True       # el aviso lo prueba LaPrivacidad
        self.settings.save()
        self.ws = self.open_workspace()
        self.pid = self.ws.create_project("", "Proyecto").id
        self.creados, self.preguntas = [], []
        self.subtype, self.coste = "success", 0.25
        self.agent_factory = lambda session: AgenteFalso(self)

    def open_workspace(self):
        return LocalWorkspace.open(self.tmp / "Personal", trash=lambda p: None)

    def chat(self, pid=None, ws=None, settings=None):
        """Una sesión nueva del proyecto, como al abrirlo (o al reiniciar la app)."""
        ws = ws or self.ws
        session = Session(pid or self.pid, Board(ws, pid or self.pid, connectors=frozenset()))
        self.broadcast = []

        async def broadcast(m):
            self.broadcast.append(m)

        async def saved():
            session.board.save()

        def finished():
            session.agent_busy = False

        return AgentChat(session, ws, settings or self.settings,
                         make_agent=lambda: self.agent_factory(session), broadcast=broadcast,
                         saved=saved, finished=finished)

    async def ask(self, chat, text, once=False):
        """Manda `agent_ask` y espera a que acabe. Devuelve lo que recibió quien preguntó."""
        w = VentanaFalsa()
        await chat.handle(w, {"type": "agent_ask", "text": text, **({"once": True} if once
                                                                  else {})})
        if chat._task is not None:
            await chat._task
        return w.sent

    def agent_events(self):
        return [m for m in self.broadcast if m["type"] == "agent"]

    def gastado(self, usd, pid=None):
        AgentStore(self.ws, pid or self.pid).add_usage(DESIGN, message_usage({}, usd))


class LaConversacionVaAlDisco(_Base):
    async def test_el_chat_y_la_sesion_siguen_tras_reiniciar(self):
        c = self.chat()
        await self.ask(c, "revisa la pizarra")
        kinds = [e["kind"] for e in c.store.history()]
        self.assertEqual(kinds, ["user", "text", "done"])
        # se reinicia el backend: otro workspace, otros ajustes y otra sesión, del mismo disco
        c2 = self.chat(ws=self.open_workspace(), settings=Settings.load(self.settings_path))
        w = VentanaFalsa()
        await c2.handle(w, {"type": "agent_history"})
        self.assertEqual([e["kind"] for e in w.sent[0]["events"]], kinds)
        self.assertEqual(w.sent[0]["events"][0]["text"], "revisa la pizarra")
        await self.ask(c2, "sigue")
        self.assertEqual(self.preguntas[-1]["resume"], "ses-1")    # la misma conversación

    async def test_restaurar_una_version_nunca_toca_agent(self):
        c = self.chat()
        board = c.session.board
        vid = board.save_version("antes de hablar")["id"]
        await self.ask(c, "uno")
        antes = (c.store.history(), c.store.usage(), c.store.session_id())
        board.restore_version(vid)
        self.assertEqual((c.store.history(), c.store.usage(), c.store.session_id()), antes)
        self.assertEqual(len(antes[0]), 3)
        # y la versión no se lleva nada de la conversación
        vdir = self.ws.workdir(self.pid) / "board" / "versions"
        self.assertEqual([p for p in vdir.rglob("*") if "agent" in p.name or
                          p.suffix == ".jsonl"], [])

    async def test_una_linea_cortada_del_chat_se_salta_y_lo_demas_se_lee(self):
        c = self.chat()
        await self.ask(c, "uno")
        f = self.ws.workdir(self.pid) / "agent" / "chat.jsonl"
        with open(f, "a", encoding="utf-8") as fh:
            fh.write('{"kind": "text", "te')               # un apagón a mitad de línea
        self.assertEqual(len(c.store.history()), 3)

    def test_un_fichero_del_agente_que_no_es_de_agent_no_se_nombra(self):
        for malo in ("../board/scene", "chat", "otro"):
            with self.assertRaises(InvalidName):
                self.ws.save_agent_file(self.pid, malo, {})

    async def test_los_ajustes_del_agente_no_tocan_el_resto_del_project_toml(self):
        c = self.chat()
        await c.handle(VentanaFalsa(), {"type": "agent_settings", "limit": 8,
                                        "exclude_attachments": True})
        self.assertEqual(self.open_workspace().project(self.pid).id, self.pid)
        self.assertEqual(self.ws.load_project_agent_settings(self.pid),
                         {"tope_usd": 8.0, "excluir_adjuntos": True})


class ElConsumo(_Base):
    async def test_cada_mensaje_suma_en_su_agente_y_su_proyecto_y_nunca_en_otro(self):
        otro = self.ws.create_project("", "Otro").id
        # un agente que no es el de diseño (el revisor, FF 4.9) ya tenía lo suyo
        self.ws.save_agent_file(self.pid, "usage", {"agents": {"revisor": {
            "input": 7, "output": 0, "cache_creation": 0, "cache_read": 0, "usd": 1.0,
            "messages": 1}}})
        c = self.chat()
        await self.ask(c, "uno")
        self.coste = 0.75             # el SDK da el acumulado de la sesión: 0.25 + 0.5
        await self.ask(c, "dos")
        u = c.store.usage()
        self.assertEqual(u["agents"]["diseno"], {"input": 200, "output": 80,
                                                 "cache_creation": 20, "cache_read": 6000,
                                                 "usd": 0.75, "messages": 2})
        self.assertEqual(u["agents"]["revisor"]["usd"], 1.0)
        self.assertEqual((u["total"]["usd"], u["total"]["input"]), (1.75, 207))
        self.assertEqual(AgentStore(self.ws, otro).usage()["total"]["usd"], 0.0)

    async def test_done_lleva_el_consumo_del_mensaje_y_el_total(self):
        self.gastado(1.0)
        c = self.chat()
        await self.ask(c, "uno")
        done = self.agent_events()[-1]
        self.assertEqual((done["kind"], done["reason"]), ("done", "ok"))
        self.assertEqual((done["usage"]["usd"], done["usage"]["cache_read"]), (0.25, 3000))
        self.assertEqual((done["total"]["usd"], done["limit"]), (1.25, 5.0))
        self.assertNotIn("cost_usd", done)
        state = [m for m in self.broadcast if m["type"] == "agent_state"][-1]
        self.assertEqual((state["remaining"], state["busy"]), (3.75, False))

    async def test_un_mensaje_reanudado_cuenta_solo_lo_suyo_aunque_el_sdk_de_el_acumulado(self):
        # medido con Claude de verdad: total_cost_usd es el de la sesión reanudada entera
        c = self.chat()
        await self.ask(c, "uno")                   # acumulado 0.25
        self.coste = 0.40
        await self.ask(c, "dos")                   # acumulado 0.40: este mensaje, 0.15
        self.assertAlmostEqual(self.agent_events()[-1]["usage"]["usd"], 0.15)
        # tras reiniciar el backend, la misma sesión sigue restando lo que ya se contó
        c2 = self.chat(ws=self.open_workspace(), settings=Settings.load(self.settings_path))
        self.coste = 0.50
        await self.ask(c2, "tres")
        self.assertAlmostEqual(c2.store.usage()["total"]["usd"], 0.50)

    def test_una_sesion_nueva_o_un_acumulado_menor_empieza_de_cero(self):
        s = AgentStore(self.ws, self.pid)
        self.assertAlmostEqual(s.message_cost("ses-a", 0.3), 0.3)
        self.assertAlmostEqual(s.message_cost("ses-b", 0.1), 0.1)      # otra sesión
        self.assertAlmostEqual(s.message_cost("ses-b", 0.05), 0.05)    # el CLI la perdió
        self.assertIsNone(s.message_cost("ses-b", float("nan")))

    def test_un_uso_raro_del_sdk_cuenta_cero_y_nunca_resta(self):
        u = message_usage({"input_tokens": -5, "output_tokens": "x", "cache_read_input_tokens":
                           True}, float("nan"))
        self.assertEqual(u, {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0,
                             "usd": 0.0, "messages": 1})


class ElTope(_Base):
    async def test_con_el_tope_alcanzado_ningun_mensaje_empieza(self):
        self.gastado(5.0)
        c = self.chat()
        sent = await self.ask(c, "uno")
        self.assertEqual(sent, [{"type": "agent", "kind": "limit", "text": "uno", "used": 5.0,
                                 "limit": 5.0}])
        self.assertEqual((self.creados, c.store.history()), ([], []))
        self.assertFalse(c.session.agent_busy)

    async def test_seguir_solo_este_mensaje_deja_pasar_uno_solo(self):
        self.gastado(6.0)
        c = self.chat()
        await self.ask(c, "uno", once=True)
        self.assertEqual([p["text"] for p in self.preguntas], ["uno"])
        sent = await self.ask(c, "dos")
        self.assertEqual(sent[0]["kind"], "limit")
        self.assertEqual(len(self.preguntas), 1)

    async def test_max_budget_es_lo_que_queda_y_nunca_el_tope_entero(self):
        self.gastado(1.5)
        c = self.chat()
        await self.ask(c, "uno")
        self.assertEqual(self.preguntas[-1]["budget"], 3.5)
        await c.handle(VentanaFalsa(), {"type": "agent_settings", "limit": 10})   # Subir tope
        await self.ask(c, "dos")
        self.assertEqual(self.preguntas[-1]["budget"], 10 - 1.75)
        self.gastado(20.0)
        await self.ask(c, "tres", once=True)
        self.assertGreater(self.preguntas[-1]["budget"], 0)
        self.assertLess(self.preguntas[-1]["budget"], 10)

    async def test_subir_tope_es_del_proyecto_y_null_vuelve_al_de_los_ajustes(self):
        otro = self.ws.create_project("", "Otro").id
        self.gastado(5.0)
        c = self.chat()
        await c.handle(VentanaFalsa(), {"type": "agent_settings", "limit": 8})
        self.assertEqual(c.state()["limit"], 8.0)
        self.assertEqual(agent_chat.state(AgentStore(self.ws, otro), self.settings)["limit"], 5.0)
        await self.ask(c, "uno")
        self.assertEqual(len(self.preguntas), 1)
        await c.handle(VentanaFalsa(), {"type": "agent_settings", "limit": None})
        self.assertEqual((c.state()["limit"], c.state()["limit_own"]), (5.0, False))

    async def test_un_tope_que_no_es_un_importe_se_rechaza(self):
        c = self.chat()
        for malo in (0, -1, "5", True, float("inf")):
            with self.assertRaises(ValidationError, msg=malo):
                await c.handle(VentanaFalsa(), {"type": "agent_settings", "limit": malo})
        self.assertEqual(self.ws.load_project_agent_settings(self.pid), {})

    async def test_si_el_sdk_corta_por_el_tope_el_chat_lo_dice(self):
        self.subtype = "error_max_budget_usd"
        c = self.chat()
        await self.ask(c, "uno")
        done = self.agent_events()[-1]
        self.assertEqual(done["reason"], "limit")
        self.assertIn("tope", done["text"])

    def test_el_tope_por_defecto_es_5_y_uno_que_no_es_un_importe_tambien(self):
        self.assertEqual(self.settings.project_limit_usd, 5.0)
        for valor, tope in ((8, 8.0), ("mucho", 5.0), (-2, 5.0)):
            self.settings.data["agentes"]["tope_proyecto_usd"] = valor
            self.assertEqual(self.settings.project_limit_usd, tope)


class Parar(_Base):
    def agente_que_espera(self, obedece=True):
        test = self

        class Agente:
            def __init__(self, session):
                self.board, self.session_id, self.max_budget_usd = session.board, None, None
                self.go = asyncio.Event()
                test.agente = self

            async def ask(self, message, emit):
                agent_mod.tool_crear_postit(self.board, {"text": "hecho antes de parar",
                                                         "kind": "nota"})
                await emit({"kind": "text", "text": "empiezo"})
                await self.go.wait()
                await emit({"kind": "done", "turns": 1, "seconds": 1, "subtype":
                            "error_during_execution", "terminal_reason": "aborted_tools",
                            "usage": USO, "cost_usd": 0.1})

            async def interrupt(self):
                if obedece:
                    self.go.set()
        self.agent_factory = Agente

    async def empezar(self, c):
        await c.handle(VentanaFalsa(), {"type": "agent_ask", "text": "haz mucho"})
        while not any(e.get("kind") == "text" for e in self.agent_events()):
            await asyncio.sleep(0.01)

    async def test_parar_deja_lo_hecho_y_libera_al_agente(self):
        self.agente_que_espera()
        c = self.chat()
        await self.empezar(c)
        with self.assertRaises(ValidationError):               # una pregunta a la vez (R6)
            await c.handle(VentanaFalsa(), {"type": "agent_ask", "text": "otra"})
        await c.handle(VentanaFalsa(), {"type": "agent_stop"})
        await c._task if c._task else None
        self.assertFalse(c.session.agent_busy)
        kinds = [e["kind"] for e in self.agent_events()]
        self.assertEqual(kinds[-2:], ["done", "stopped"])
        self.assertEqual(self.agent_events()[-2]["reason"], "stopped")
        textos = [e.get("customData", {}).get("text") or e.get("text")
                  for e in Board(self.ws, self.pid).elements]
        self.assertTrue(any("hecho antes de parar" in (t or "") for t in textos))
        self.assertEqual(c.store.usage()["total"]["usd"], 0.1)    # lo gastado cuenta
        await self.ask(c, "la siguiente")                       # y ya atiende otra
        self.assertEqual([e["kind"] for e in c.store.history()][-1], "done")

    async def test_si_el_sdk_no_para_se_cancela_igual(self):
        self.agente_que_espera(obedece=False)
        c = self.chat()
        c.stop_grace = 0.05
        await self.empezar(c)
        await c.handle(VentanaFalsa(), {"type": "agent_stop"})
        await asyncio.wait_for(c._task, 2) if c._task else None
        self.assertFalse(c.session.agent_busy)
        self.assertEqual(self.agent_events()[-1]["kind"], "stopped")
        self.assertEqual([e["kind"] for e in c.store.history()][-1], "stopped")

    async def test_parar_sin_nada_en_curso_es_un_error(self):
        with self.assertRaises(ValidationError):
            await self.chat().handle(VentanaFalsa(), {"type": "agent_stop"})


class LaPrivacidad(_Base):
    async def test_el_aviso_sale_hasta_que_se_pulsa_entendido(self):
        settings = Settings.load(self.tmp / "nuevo.toml")
        settings.language = "es"            # el aviso va en el idioma de la app (O11)
        c = self.chat(settings=settings)
        sent = await self.ask(c, "hola")
        self.assertEqual((sent[0]["kind"], sent[0]["text"]), ("privacy", "hola"))
        for palabra in ("Anthropic", "telemetría", "archivos", "imágenes", "Excluir adjuntos"):
            self.assertIn(palabra, sent[0]["notice"])
        self.assertEqual((self.creados, c.store.history()), ([], []))
        await c.handle(VentanaFalsa(), {"type": "agent_privacy_ok"})
        self.assertTrue(Settings.load(self.tmp / "nuevo.toml").privacy_seen)   # en disco
        await self.ask(c, "hola")
        self.assertEqual(len(self.preguntas), 1)
        # y tras reiniciar ya no sale
        c2 = self.chat(settings=Settings.load(self.tmp / "nuevo.toml"))
        sent = await self.ask(c2, "otra")
        self.assertEqual(sent, [])
        self.assertEqual(len(self.preguntas), 2)

    def test_guardar_el_aviso_conserva_lo_que_esta_version_no_conoce(self):
        p = self.tmp / "con_mas.toml"
        p.write_text('modo_ventana = "max"\n[agentes]\notra = 1\n', encoding="utf-8")
        s = Settings.load(p)
        self.assertFalse(s.privacy_seen)
        s.privacy_seen = True
        s.save()
        s = Settings.load(p)
        self.assertEqual((s.data["modo_ventana"], s.data["agentes"]["otra"], s.privacy_seen),
                         ("max", 1, True))

    def test_con_excluir_adjuntos_leer_archivo_no_lee_y_dice_por_que(self):
        board = Board(self.ws, self.pid, connectors=frozenset())
        f = self.tmp / "ficha.txt"
        f.write_text("Par 1.2 Nm", encoding="utf-8")
        card = board.add_cards([f])[0]["id"]
        self.assertNotIn("is_error", agent_mod.tool_leer_archivo(board, {"card": card}))
        r = agent_mod.tool_leer_archivo(board, {"card": card}, excluded=True)
        self.assertTrue(r["is_error"])
        self.assertIn("Excluir adjuntos", r["content"][0]["text"])
        self.assertNotIn("Par 1.2", r["content"][0]["text"])


# ------------------------------------------- con el DesignAgent de verdad y el SDK sustituido
class ClienteFalso:
    """Sustituto de `ClaudeSDKClient`: apunta las opciones y devuelve `script`."""
    ultimo = None
    script = []

    def __init__(self, options):
        self.options = options
        ClienteFalso.ultimo = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, message):
        self.message = message

    async def receive_response(self):
        for m in ClienteFalso.script:
            yield m


@unittest.skipUnless(SDK, "falta claude_agent_sdk")
class ConElAgenteDeVerdad(_Base):
    def setUp(self):
        super().setUp()

        async def nada(*a):
            pass

        self.agent_factory = lambda session: agent_mod.DesignAgent(session.board, nada)
        ClienteFalso.script = [
            sdk.AssistantMessage(content=[sdk.TextBlock("Hecho.")], model="opus"),
            sdk.ResultMessage(subtype="success", duration_ms=1200, duration_api_ms=1000,
                              is_error=False, num_turns=2, session_id="ses-sdk",
                              total_cost_usd=0.4, usage=USO, terminal_reason="completed")]
        p = mock.patch.object(sdk, "ClaudeSDKClient", ClienteFalso)
        p.start()
        self.addCleanup(p.stop)

    async def test_el_sdk_recibe_lo_que_queda_del_tope_y_la_sesion_guardada(self):
        self.ws.save_agent_file(self.pid, "sessions", {"chat": {"session_id": "ses-vieja"}})
        self.gastado(2.0)
        c = self.chat()
        await self.ask(c, "hola")
        opts = ClienteFalso.ultimo.options
        self.assertEqual((opts.max_budget_usd, opts.resume), (3.0, "ses-vieja"))
        self.assertEqual(c.store.session_id(), "ses-sdk")
        done = self.agent_events()[-1]
        self.assertEqual((done["reason"], done["usage"]["usd"], done["total"]["usd"]),
                         ("ok", 0.4, 2.4))

    async def test_excluir_adjuntos_llega_a_la_herramienta_del_agente(self):
        board = Board(self.ws, self.pid, connectors=frozenset())
        f = self.tmp / "ficha.txt"
        f.write_text("Par 1.2 Nm", encoding="utf-8")
        card = board.add_cards([f])[0]["id"]
        board.save()
        c = self.chat()
        tools = []

        def servidor(name, version, ts):
            tools[:] = ts
            return {"type": "sdk", "name": name, "instance": None}

        agent = c.agent()
        with mock.patch.object(sdk, "create_sdk_mcp_server", servidor):
            agent._options()
            leer = next(t for t in tools if t.name == "leer_archivo")
            self.assertIn("Par 1.2", (await leer.handler({"card": card}))["content"][0]["text"])
            await c.handle(VentanaFalsa(), {"type": "agent_settings",
                                            "exclude_attachments": True})
            r = await leer.handler({"card": card})
        self.assertTrue(r["is_error"])
        self.assertIn("Excluir adjuntos", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()


class LasAnimacionesDesactivadasEnCadaMensaje(_Base):
    """Prueba de punta a punta de FF 4.6: con el ajuste desactivado a mitad de una conversación
    que ya había hecho una animación, el agente escribió otra (el backend la rechazó): el prompt
    de sistema no basta frente a lo que ya hizo en la sesión. Desactivadas, el mensaje que va
    al agente (no el que se guarda) lo recuerda."""

    async def test_desactivadas_el_mensaje_al_agente_lo_recuerda_y_el_del_chat_no(self):
        from pizarra import agent_prompt
        self.settings.animations_auto = False
        c = self.chat()
        await self.ask(c, "explícame el cuatro barras")
        self.assertTrue(self.preguntas[-1]["text"].startswith(agent_prompt.ANIMATIONS_OFF_NOTE))
        self.assertTrue(self.preguntas[-1]["text"].endswith("explícame el cuatro barras"))
        self.assertEqual(c.store.history()[0]["text"], "explícame el cuatro barras")

    async def test_activadas_el_mensaje_va_tal_cual(self):
        self.settings.animations_auto = True
        c = self.chat()
        await self.ask(c, "hola")
        self.assertEqual(self.preguntas[-1]["text"], "hola")
