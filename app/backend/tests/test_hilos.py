"""Los hilos anclados (FF 4.6 paso 3; plan §10, «Hilos (D165-D167)», la parte del backend).

Reglas que protegen:
- Cada hilo tiene su sesión del SDK: nunca reanuda la del chat ni la de otro hilo, y su consumo
  va al agente de diseño por diferencia con SU sesión (D168).
- El mensaje que empieza la sesión de un hilo lleva lo que son sus anclas (post-it, bloque,
  tarjeta de archivo, imagen), con el tope de las herramientas; los siguientes, no.
- Una decisión con cifras sin fuente ni `estimate` se rechaza, la proponga el agente o la
  guarde el usuario, y no deja nada; `proponer_decision` no cierra el hilo y solo existe en uno.
- Un hilo con sus anclas borradas sigue en `threads.json`, «sin anclaje», sin reescribirlo.
- El chat principal ve las decisiones de los hilos en `leer_pizarra`, nunca sus mensajes.
- Una pregunta al agente a la vez por proyecto, contando chat e hilos.
- Cerrar deja el hilo decidido y minimizado; reabrir, en revisión con la decisión; borrar no
  deja nada del hilo (salvo lo gastado).

El agente se sustituye: nunca se llama a Claude.
"""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pizarra import agent as agent_mod
from pizarra import agent_threads
from pizarra.agent_chat import DESIGN, AgentChat, AgentStore, message_usage
from pizarra.agent_threads import AgentThreads, ThreadStore
from pizarra.board import Board
from pizarra.sessions import Session
from pizarra.settings import Settings
from pizarra.storage import LocalWorkspace
from pizarra.validation import ValidationError
from tests.helpers import necesita_paquetes

try:
    import claude_agent_sdk as sdk
    SDK = True
except ImportError:
    SDK = False

USO = {"input_tokens": 10, "output_tokens": 5}


class VentanaFalsa:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


class AgenteFalso:
    """Como el SDK: sin `resume` abre una sesión nueva; con él, sigue esa. El coste que da es
    el acumulado de la sesión (`test.acumulado[sesión]`). Si el test lo pide, llama a
    `proponer_decision` (`decide`) con `test.decidir`."""
    def __init__(self, test):
        self.test = test
        self.session_id = None
        self.max_budget_usd = None
        self.decide = None

    async def ask(self, message, emit):
        t = self.test
        t.preguntas.append({"text": message, "resume": self.session_id,
                            "en_hilo": self.decide is not None})
        if self.session_id is None:
            t.sesiones += 1
            self.session_id = f"ses-{t.sesiones}"
        if t.decidir is not None and self.decide is not None:
            t.resultados.append(await self.decide(t.decidir))
        await emit({"kind": "text", "text": f"respuesta a {message[-20:]}"})
        sid = self.session_id
        t.acumulado[sid] = t.acumulado.get(sid, 0.0) + t.coste
        await emit({"kind": "done", "turns": 1, "seconds": 0.1, "subtype": "success",
                    "terminal_reason": "completed", "usage": USO, "cost_usd": t.acumulado[sid]})


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings = Settings.load(self.tmp / "settings.toml")
        self.settings.privacy_seen = True
        self.settings.save()
        self.ws = self.open_workspace()
        self.pid = self.ws.create_project("", "Proyecto").id
        self.preguntas, self.resultados, self.acumulado = [], [], {}
        self.sesiones, self.coste, self.decidir = 0, 0.1, None
        self.agent_factory = lambda session: AgenteFalso(self)
        self.abrir()
        b = self.board
        self.postit = agent_mod.tool_crear_postit(b, {"text": "La carga incluye la pinza",
                                                      "kind": "pregunta"})[1][0]["id"]
        f = self.tmp / "ficha motor.pdf"
        f.write_bytes(b"%PDF-1.4")
        self.card = b.add_cards([f])[0]["id"]
        self.block = b.add_block("demo.tubo", {"L": 250})["id"]
        b.elements = b.elements + [{"id": "foto", "type": "embeddable", "x": 900, "y": 900,
                                    "width": 100, "height": 80, "isDeleted": False,
                                    "customData": {"kind": "image", "image": {"file": "f.png"}}}]
        b.save()

    def open_workspace(self):
        return LocalWorkspace.open(self.tmp / "Personal", trash=lambda p: None)

    def abrir(self, ws=None):
        """Una sesión nueva del proyecto, como al abrirlo o al reiniciar la app."""
        ws = ws or self.ws
        session = Session(self.pid, Board(ws, self.pid, connectors=frozenset()))
        self.board = session.board
        self.broadcast = []

        async def broadcast(m, exclude=None):
            self.broadcast.append((m, exclude))

        async def saved():
            session.board.save()

        def finished():
            session.agent_busy = False

        self.chat = AgentChat(session, ws, self.settings,
                              make_agent=lambda: self.agent_factory(session),
                              broadcast=lambda m: broadcast(m), saved=saved, finished=finished)
        self.threads = AgentThreads(self.chat, broadcast)
        return self.threads

    async def send(self, msg, w=None):
        """Un mensaje `thread_*` (o `agent_*`) y espera a que acabe lo que lance."""
        w = w or VentanaFalsa()
        if msg["type"].startswith("thread_"):
            await self.threads.handle(w, msg)
        else:
            await self.chat.handle(w, msg)
        if self.chat._task is not None:
            await self.chat._task
        return w.sent

    async def crear(self, anchors=None, **kw):
        sent = await self.send({"type": "thread_create",
                                "anchors": anchors or [self.postit], **kw})
        return next(m for m in sent if m["type"] == "thread_created")["thread"]["id"]

    def sesiones_json(self):
        return self.ws.load_agent_file(self.pid, "sessions")

    def eventos(self, thread=None):
        return [m for m, _ in self.broadcast if m["type"] == "agent"
                and m.get("thread") == thread]


@necesita_paquetes
class UnaSesionPorHilo(_Base):
    async def test_cada_hilo_sigue_su_sesion_y_nunca_la_del_chat_ni_la_de_otro(self):
        await self.send({"type": "agent_ask", "text": "chat uno"})        # ses-1, el chat
        a = await self.crear(text="hilo a uno")                         # ses-2
        b = await self.crear([self.block], text="hilo b uno")           # ses-3
        await self.send({"type": "thread_ask", "id": a, "text": "hilo a dos"})
        await self.send({"type": "agent_ask", "text": "chat dos"})
        await self.send({"type": "thread_ask", "id": b, "text": "hilo b dos"})
        resume = [p["resume"] for p in self.preguntas]
        self.assertEqual(resume, [None, None, None, "ses-2", "ses-1", "ses-3"])
        s = self.sesiones_json()
        self.assertEqual((s["chat"]["session_id"], s[f"hilo:{a}"]["session_id"],
                          s[f"hilo:{b}"]["session_id"]), ("ses-1", "ses-2", "ses-3"))
        # el chat nunca guarda lo de un hilo, ni un hilo lo de otro
        self.assertEqual([e["text"] for e in self.chat.store.history() if e["kind"] == "user"],
                         ["chat uno", "chat dos"])
        self.assertEqual([e["text"] for e in ThreadStore(self.ws, self.pid).history(a)
                          if e["kind"] == "user"], ["hilo a uno", "hilo a dos"])

    async def test_tras_reiniciar_el_hilo_sigue_su_conversacion(self):
        a = await self.crear(text="uno")
        self.abrir(self.open_workspace())
        sent = await self.send({"type": "thread_history", "id": a})
        self.assertEqual([e["kind"] for e in sent[0]["events"]], ["user", "text", "done"])
        await self.send({"type": "thread_ask", "id": a, "text": "dos"})
        self.assertEqual(self.preguntas[-1]["resume"], "ses-1")

    async def test_el_consumo_del_hilo_va_al_de_diseno_por_diferencia_con_su_sesion(self):
        await self.send({"type": "agent_ask", "text": "chat"})          # chat: acumulado 0.1
        a = await self.crear(text="uno")                                # hilo: 0.1
        self.coste = 0.3
        await self.send({"type": "thread_ask", "id": a, "text": "dos"})  # hilo: 0.4, suma 0.3
        done = self.eventos(a)[-1]
        self.assertEqual((done["kind"], done["thread"]), ("done", a))
        self.assertAlmostEqual(done["usage"]["usd"], 0.3)
        u = self.chat.store.usage()
        self.assertEqual(list(u["agents"]), [DESIGN])
        self.assertAlmostEqual(u["agents"][DESIGN]["usd"], 0.5)
        self.assertEqual(u["agents"][DESIGN]["messages"], 3)

    async def test_una_pregunta_a_la_vez_contando_chat_e_hilos(self):
        a = await self.crear()
        go = asyncio.Event()
        test = self

        class Lento(AgenteFalso):
            async def ask(self, message, emit):
                await go.wait()
                await super().ask(message, emit)
        self.agent_factory = lambda session: Lento(test)
        await self.threads.handle(VentanaFalsa(), {"type": "thread_ask", "id": a, "text": "x"})
        self.assertEqual(self.chat.state()["thread"], a)
        for msg in ({"type": "agent_ask", "text": "y"},
                    {"type": "thread_ask", "id": a, "text": "z"},
                    {"type": "thread_create", "anchors": [self.block], "text": "w"}):
            with self.assertRaises(ValidationError, msg=msg["type"]):
                if msg["type"].startswith("thread_"):
                    await self.threads.handle(VentanaFalsa(), msg)
                else:
                    await self.chat.handle(VentanaFalsa(), msg)
        self.assertEqual(len(ThreadStore(self.ws, self.pid).all()), 1)   # ningún hilo a medias
        with self.assertRaises(ValidationError):                         # ni se borra en curso
            await self.threads.handle(VentanaFalsa(), {"type": "thread_delete", "id": a})
        go.set()
        await self.chat._task
        self.assertEqual(self.chat.state()["thread"], None)
        self.assertEqual(len(self.preguntas), 1)

    async def test_las_tarjetas_de_privacidad_y_tope_dicen_su_hilo(self):
        a = await self.crear()
        self.settings.privacy_seen = False
        sent = await self.send({"type": "thread_ask", "id": a, "text": "hola"})
        self.assertEqual((sent[0]["kind"], sent[0]["thread"], sent[0]["text"]),
                         ("privacy", a, "hola"))
        self.settings.privacy_seen = True
        AgentStore(self.ws, self.pid).add_usage(DESIGN, message_usage({}, 5.0))
        sent = await self.send({"type": "thread_close_request", "id": a})
        self.assertEqual((sent[0]["kind"], sent[0]["thread"], sent[0]["close_request"]),
                         ("limit", a, True))
        self.assertEqual(self.preguntas, [])


@necesita_paquetes
class ElPrimerMensaje(_Base):
    async def test_lleva_lo_que_son_las_anclas_y_los_siguientes_no(self):
        f = self.board.card(self.card)["customData"]["path"]
        a = await self.crear([self.postit, self.block, self.card, "foto"], text="¿Aguanta?")
        primero = self.preguntas[0]["text"]
        for trozo in ("La carga incluye la pinza", "pregunta", "abierto", "demo.tubo",
                      self.board.registry["demo.tubo"].title, '"L": 250', "ficha motor.pdf",
                      json.dumps(f, ensure_ascii=False), "imagen", "¿Aguanta?"):
            self.assertIn(trozo, primero)
        self.assertTrue(primero.endswith("¿Aguanta?"))
        # lo que se guarda y se enseña es la pregunta, no el preámbulo
        self.assertEqual(ThreadStore(self.ws, self.pid).history(a)[0]["text"], "¿Aguanta?")
        await self.send({"type": "thread_ask", "id": a, "text": "¿Y con 300?"})
        self.assertEqual(self.preguntas[1]["text"], "¿Y con 300?")

    async def test_si_la_sesion_se_pierde_vuelven_a_ir_las_anclas(self):
        a = await self.crear(text="uno")
        self.ws.save_agent_file(self.pid, "sessions", {})
        await self.send({"type": "thread_ask", "id": a, "text": "dos"})
        self.assertIn("La carga incluye la pinza", self.preguntas[-1]["text"])

    async def test_las_anclas_nunca_pasan_del_tope_de_las_herramientas(self):
        largo = agent_mod.tool_crear_postit(self.board, {"text": "x" * 4000, "kind": "nota"})
        ids = [largo[1][0]["id"]]
        for _ in range(9):
            ids.append(agent_mod.tool_crear_postit(self.board, {"text": "y" * 4000,
                                                                "kind": "nota"})[1][0]["id"])
        thread = {"title": "t", "anchors": ids}
        msg = agent_threads.first_message(self.board, thread, "?")
        self.assertLess(len(msg), agent_mod.TOOL_CHARS + 500)

    async def test_un_hilo_se_ancla_a_algo_que_existe(self):
        for anchors in ([], ["no-esta"], "p", [1]):
            with self.assertRaises(ValidationError, msg=anchors):
                await self.threads.handle(VentanaFalsa(), {"type": "thread_create",
                                                           "anchors": anchors})
        self.assertEqual(ThreadStore(self.ws, self.pid).all(), [])
        a = await self.crear([self.postit, self.postit])
        t = ThreadStore(self.ws, self.pid).get(a)
        self.assertEqual(t["anchors"], [self.postit])
        self.assertIn("La carga incluye la pinza", t["title"])        # «Sobre …» por defecto

    async def test_el_titulo_no_dobla_las_comillas_de_un_texto_que_ya_las_lleva(self):
        # Prueba de punta a punta de FF 4.6: un post-it del agente que empieza con «…» salía
        # ««TCP por encima del suelo» sale…» en el título del hilo.
        citado = agent_mod.tool_crear_postit(
            self.board, {"text": "«TCP por encima del suelo» sale por debajo", "kind": "pregunta"})
        a = await self.crear([citado[1][0]["id"]])
        title = ThreadStore(self.ws, self.pid).get(a)["title"]
        self.assertNotIn("««", title)        # dentro de «…», las comillas de segundo nivel
        self.assertTrue(title.startswith("Sobre «“TCP por encima del suelo” sale"), title)


@necesita_paquetes
class LaDecision(_Base):
    async def test_proponer_decision_deja_la_propuesta_y_no_cierra(self):
        a = await self.crear(text="uno")
        self.decidir = {"texto": "Atornillado a la brida ISO 9409-1-50-4-M6"}   # designaciones
        await self.send({"type": "thread_close_request", "id": a})
        self.assertEqual(self.preguntas[-1]["text"], agent_threads.CLOSE_PROMPT)
        self.assertNotIn("is_error", self.resultados[-1])
        t = ThreadStore(self.ws, self.pid).get(a)
        self.assertEqual((t["state"], t["decision"]), ("abierto", None))
        self.assertEqual(t["proposed"]["text"], "Atornillado a la brida ISO 9409-1-50-4-M6")
        kinds = [e["kind"] for e in self.eventos(a)]
        self.assertIn("decision_proposal", kinds)
        user = [e for e in ThreadStore(self.ws, self.pid).history(a) if e["kind"] == "user"][-1]
        self.assertTrue(user["close_request"])

    async def test_el_agente_con_cifras_sin_fuente_recibe_el_motivo_y_no_queda_nada(self):
        a = await self.crear()
        self.decidir = {"texto": "Tubo de 30 mm"}
        await self.send({"type": "thread_close_request", "id": a})
        r = self.resultados[-1]
        self.assertTrue(r["is_error"])
        self.assertIn("fuente", r["content"][0]["text"])
        self.assertIsNone(ThreadStore(self.ws, self.pid).get(a)["proposed"])
        # una fuente de bloque tiene que ser un bloque de la pizarra con resultados
        self.decidir = {"texto": "Tubo de 30 mm", "sources": [{"kind": "bloque",
                                                                  "ref": "bloque:otro"}]}
        await self.send({"type": "thread_close_request", "id": a})
        self.assertTrue(self.resultados[-1]["is_error"])
        self.decidir = {"texto": "Tubo de 30 mm", "estimate": True}
        await self.send({"type": "thread_close_request", "id": a})
        self.assertNotIn("is_error", self.resultados[-1])

    async def test_el_usuario_con_cifras_sin_fuente_ve_el_motivo_y_el_hilo_sigue_abierto(self):
        a = await self.crear()
        with self.assertRaises(ValidationError):
            await self.send({"type": "thread_close", "id": a,
                             "decision": {"text": "Carga de 50 N"}})
        self.assertEqual(ThreadStore(self.ws, self.pid).get(a)["state"], "abierto")
        for malo in ({"text": ""}, "texto", {"text": "ok", "estimate": "sí"},
                     {"text": "50 N", "sources": [{"kind": "inventada", "ref": "x"}]}):
            with self.assertRaises(ValidationError, msg=malo):
                await self.send({"type": "thread_close", "id": a, "decision": malo})
        await self.send({"type": "thread_close", "id": a, "decision": {
            "text": "Carga de 50 N", "sources": [{"kind": "ficha", "ref": "ficha:pinza"}]}})
        self.assertEqual(ThreadStore(self.ws, self.pid).get(a)["state"], "decidido")

    async def test_cerrar_reabrir_y_volver_a_cerrar(self):
        a = await self.crear(text="uno")
        self.decidir = {"texto": "Atornillado"}
        await self.send({"type": "thread_close_request", "id": a})
        await self.send({"type": "thread_close", "id": a,
                         "decision": {"text": "Atornillado, nunca soldado"}})
        t = ThreadStore(self.ws, self.pid).get(a)
        self.assertEqual((t["state"], t["decision"]["text"], t["proposed"], t["layout"]["size"]),
                         ("decidido", "Atornillado, nunca soldado", None, "min"))
        n = len(self.preguntas)
        for msg in ({"type": "thread_ask", "id": a, "text": "¿seguro?"},
                    {"type": "thread_close_request", "id": a},
                    {"type": "thread_close", "id": a, "decision": {"text": "otra"}}):
            with self.assertRaises(ValidationError, msg=msg["type"]):     # cerrado: reabrir
                await self.send(msg)
        self.assertEqual(len(self.preguntas), n)
        await self.send({"type": "thread_reopen", "id": a})
        t = ThreadStore(self.ws, self.pid).get(a)
        self.assertEqual((t["state"], t["decision"]["text"]),
                         ("en_revision", "Atornillado, nunca soldado"))
        with self.assertRaises(ValidationError):
            await self.send({"type": "thread_reopen", "id": a})
        await self.send({"type": "thread_ask", "id": a, "text": "¿seguro?"})
        await self.send({"type": "thread_close", "id": a, "decision": {"text": "Soldado"}})
        t = ThreadStore(self.ws, self.pid).get(a)
        self.assertEqual((t["state"], t["decision"]["text"]), ("decidido", "Soldado"))
        kinds = [e["kind"] for e in ThreadStore(self.ws, self.pid).history(a)]
        self.assertEqual([k for k in kinds if k in ("closed", "reopened")],
                         ["closed", "reopened", "closed"])
        self.assertEqual(t["messages"], 6)       # 3 preguntas (con *Cerrar*) y 3 respuestas


@necesita_paquetes
@unittest.skipUnless(SDK, "falta claude_agent_sdk")
class ProponerDecisionSoloEnUnHilo(_Base):
    def herramientas(self, agent):
        tools = []

        def servidor(name, version, ts):
            tools[:] = ts
            return {"type": "sdk", "name": name, "instance": None}
        with mock.patch.object(sdk, "create_sdk_mcp_server", servidor):
            opts = agent._options()
        return [t.name for t in tools], opts

    async def test_el_chat_no_la_tiene_y_el_hilo_si(self):
        async def nada(*a):
            pass
        self.agent_factory = lambda session: agent_mod.DesignAgent(session.board, nada)
        nombres, opts = self.herramientas(self.chat.agent())
        self.assertNotIn("proponer_decision", nombres)
        self.assertNotIn("mcp__pizarra__proponer_decision", opts.allowed_tools)
        a = await self.crear()
        conv = agent_threads.ThreadConversation(self.threads, a)
        nombres, opts = self.herramientas(conv.agent(self.chat))
        self.assertIn("proponer_decision", nombres)
        self.assertIn("mcp__pizarra__proponer_decision", opts.allowed_tools)
        self.assertIn(agent_threads.THREAD_PROMPT, opts.system_prompt)


@necesita_paquetes
class SinAnclaje(_Base):
    async def test_un_hilo_con_sus_anclas_borradas_sigue_y_sale_sin_anclaje(self):
        a = await self.crear([self.postit, "foto"])
        f = self.ws.workdir(self.pid) / "agent" / "threads.json"
        antes = f.read_bytes()
        self.board.elements = [{**e, "isDeleted": True} if e["id"] == "foto" else e
                               for e in self.board.elements]
        v = next(t for t in self.threads.list() if t["id"] == a)
        self.assertEqual((v["missing"], v["sin_anclaje"]), (["foto"], False))
        self.board.elements = [{**e, "isDeleted": True} if e["id"] == self.postit else e
                               for e in self.board.elements]
        v = next(t for t in self.threads.list() if t["id"] == a)
        self.assertTrue(v["sin_anclaje"])
        self.assertEqual(f.read_bytes(), antes)                       # nunca se reescribe
        sent = await self.send({"type": "thread_history", "id": a})
        self.assertTrue(sent[0]["thread"]["sin_anclaje"])
        # deshacer el borrado lo vuelve a anclar
        self.board.elements = [{**e, "isDeleted": False} for e in self.board.elements]
        self.assertFalse(next(t for t in self.threads.list() if t["id"] == a)["sin_anclaje"])


@necesita_paquetes
class ElChatVeLasDecisiones(_Base):
    async def test_leer_pizarra_da_las_decisiones_y_nunca_los_mensajes(self):
        a = await self.crear(text="secreto del hilo")
        await self.crear([self.block])                                  # sin decisión
        await self.send({"type": "thread_close", "id": a, "decision": {
            "text": "Atornillado", "sources": [], "estimate": False}})
        r = agent_mod.tool_leer_pizarra(self.board, {})["content"][0]["text"]
        data = json.loads(r)
        self.assertEqual(data["decisions"], [{
            "thread": a, "title": ThreadStore(self.ws, self.pid).get(a)["title"],
            "state": "decidido", "decision": {"text": "Atornillado", "sources": [],
                                              "estimate": False},
            "anchors": [self.postit], "sin_anclaje": False}])
        self.assertNotIn("secreto del hilo", r)
        self.assertNotIn("respuesta a", r)
        await self.send({"type": "thread_reopen", "id": a})
        data = json.loads(agent_mod.tool_leer_pizarra(self.board, {})["content"][0]["text"])
        self.assertEqual(data["decisions"][0]["state"], "en_revision")


@necesita_paquetes
class TamañoYBorrado(_Base):
    async def test_el_tamano_nunca_baja_del_minimo_y_va_a_las_otras_ventanas(self):
        a = await self.crear(layout={"size": "window", "x": 10, "y": 20, "w": 50, "h": 40})
        t = ThreadStore(self.ws, self.pid).get(a)
        self.assertEqual((t["layout"]["w"], t["layout"]["h"]), agent_threads.MIN_SIZE)
        updated = t["updated"]
        w = VentanaFalsa()
        self.broadcast.clear()
        await self.send({"type": "thread_layout", "id": a, "layout": {"size": "full",
                                                                       "w": 500}}, w)
        msg, exclude = self.broadcast[-1]
        self.assertEqual((msg["type"], msg["layout"]["size"], msg["layout"]["w"],
                          msg["layout"]["x"]), ("thread_layout", "full", 500.0, 10.0))
        self.assertIs(exclude, w)                                       # a las otras
        self.assertEqual(ThreadStore(self.ws, self.pid).get(a)["updated"], updated)
        for malo in ({"size": "grande"}, {"x": "1"}, {"w": float("inf")}, {"h": True}, []):
            with self.assertRaises(ValidationError, msg=malo):
                await self.send({"type": "thread_layout", "id": a, "layout": malo})
        self.assertEqual(self.preguntas, [])                            # sin el agente

    async def test_borrar_no_deja_nada_del_hilo_salvo_lo_gastado(self):
        a = await self.crear(text="uno")
        b = await self.crear([self.block], text="otro")
        await self.send({"type": "thread_delete", "id": a})
        self.assertEqual([t["id"] for t in ThreadStore(self.ws, self.pid).all()], [b])
        self.assertFalse((self.ws.workdir(self.pid) / "agent" / "threads" / f"{a}.jsonl")
                         .exists())
        self.assertNotIn(f"hilo:{a}", self.sesiones_json())
        self.assertIn(f"hilo:{b}", self.sesiones_json())
        self.assertAlmostEqual(self.chat.store.usage()["total"]["usd"], 0.2)
        self.assertEqual(self.broadcast[-1][0], {"type": "threads",
                                                 "threads": self.threads.list()})
        with self.assertRaises(ValidationError):
            await self.send({"type": "thread_history", "id": a})

    async def test_restaurar_una_version_nunca_toca_los_hilos(self):
        vid = self.board.save_version("antes")["id"]
        a = await self.crear(text="uno")
        antes = (ThreadStore(self.ws, self.pid).all(), ThreadStore(self.ws, self.pid).history(a))
        self.board.restore_version(vid)
        self.assertEqual((ThreadStore(self.ws, self.pid).all(),
                          ThreadStore(self.ws, self.pid).history(a)), antes)


if __name__ == "__main__":
    unittest.main()


@necesita_paquetes
class LasAnimacionesDesactivadasEnUnHilo(_Base):
    async def test_desactivadas_cada_pregunta_del_hilo_lo_recuerda(self):
        from pizarra import agent_prompt
        self.settings.animations_auto = False
        a = await self.crear(text="uno")
        await self.send({"type": "thread_ask", "id": a, "text": "dos"})
        for p in self.preguntas:
            self.assertTrue(p["text"].startswith(agent_prompt.ANIMATIONS_OFF_NOTE), p["text"][:80])
        self.assertEqual([e["text"] for e in ThreadStore(self.ws, self.pid).history(a)
                          if e["kind"] == "user"], ["uno", "dos"])
