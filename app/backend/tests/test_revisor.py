"""El agente revisor (FF 6.1; docs/PLAN_V020.md §3 y §7, V2-V8).

Reglas que protegen:
- **Revisor aislado** (V2, V3, D16): sus herramientas nunca incluyen una que escriba algo que
  no sea un post-it de riesgo, pregunta o sugerencia, aunque se añadan herramientas al de
  diseño; su prompt y su contexto nunca contienen el chat ni la sesión del de diseño.
- **Revisor y autoría** (D19): todo lo que crea lleva `agent:review` y nace `abierto`; con
  cifras, sin fuente, se rechaza; como mucho 5 post-its por revisión.
- **Calcular en consulta** (V4): `calcular` nunca cambia la escena, el estado de un bloque ni
  sus salidas guardadas.
- **No repetir lo descartado** (D73): lo que ve el revisor incluye los post-its descartados con
  su texto y estado.
- **Hitos** (V5): con intrusividad `hitos`, guardar una versión con nombre lanza una revisión;
  con `a_demanda` o `apagado`, nunca. Con el agente ocupado, espera (V6).
- **Consumo por agente** (V7): lo del revisor suma en `revisor` y cuenta para el tope.
- **Ajustes** (V5, V7): intrusividad y modelo de cada agente; uno que no vale es un 422 y no
  cambia el fichero. **Perfil de fabricación** (V8): lo leen los dos agentes; sin él, nada.

El agente se sustituye: nunca se llama a Claude. Los que pasan por el `ReviewAgent` de verdad
sustituyen el cliente del SDK y se saltan sin `claude_agent_sdk`.

Ejecutar desde app/backend:  python -m unittest tests.test_revisor -v
"""
import asyncio
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pizarra import agent as agent_mod
from pizarra import agent_board_tools, agent_prompt, agent_review, packs, scene, settings_api
from pizarra.agent_chat import DESIGN, AgentStore, message_usage
from pizarra.agent_review import (MAX_POSTITS, REVIEW, REVIEW_CHAT, REVIEWER, TOOLS,
                                  AgentReview)
from pizarra.board import Board
from pizarra.settings import Settings
from pizarra.validation import ValidationError
from tests.helpers import new_board, reopen
from tests.test_agent_chat import SDK, USO, ClienteFalso, VentanaFalsa, _Base
from tests.test_pack_load import write

if SDK:
    import claude_agent_sdk as sdk

SECRETO = "SECRETO-DEL-CHAT-DE-DISENO"

CALC_BODY = """
from boardprint_sdk.packs import Param

def run(p, i, c):
    return {"out": {"masa": {"value": p["L"] * 2, "unit": "g"}}}

def vista(p, i):
    return {"error": None, "masa": {"value": p["L"] * 2, "unit": "g"}}

def register(pack):
    pack.port("rv.t", "t")
    pack.block("rv.viga", "Viga", run, params={"L": Param(300, "mm", "Largo")},
               outputs={"out": "rv.t"}, preview=vista)
    pack.block("rv.sin", "Sin vista", run, params={"L": Param(300, "mm")}, outputs={"out": "rv.t"})
"""


def _data(result):
    return json.loads(result["content"][0]["text"])


def _board_con_calculo():
    root = Path(tempfile.mkdtemp())
    write(root, "rv", body=CALC_BODY)
    reg = packs.load([root], log=lambda m: None)
    base = new_board()
    b = Board(base.ws, base.project_id, registry=reg, connectors=frozenset())
    ids = {}
    for i, kind in enumerate(("rv.viga", "rv.sin")):
        el = scene.block_element(kind, i * 400, 0)
        b.apply_client_elements([el])
        ids[kind] = el["id"]
    b.run(ids["rv.viga"])
    b.save()
    return b, ids


def _postit_del_usuario(board, text, state, kind="riesgo"):
    el = board.user_add_postit(kind, 0, 600)
    cd = {**el["customData"], "text": text, "state": state}
    board.apply_client_elements([scene.bumped({**el, "customData": cd})])
    return el["id"]


# ------------------------------------------------------------------- herramientas puras
class LaAutoriaDelRevisor(unittest.TestCase):
    def test_lo_que_crea_lleva_agent_review_y_nace_abierto_aunque_pida_otro_autor(self):
        b = new_board()
        result, new = agent_review.tool_crear_postit(
            b, {"text": "¿Quién aprieta los tornillos?", "kind": "pregunta",
                "author": "agent:design", "state": "aceptado"})
        self.assertNotIn("is_error", result)
        cd = reopen(b).elements[-1]["customData"]
        self.assertEqual((cd["author"], cd["state"], cd["postitKind"]),
                         (REVIEWER, "abierto", "pregunta"))
        self.assertEqual(new[0]["id"], reopen(b).elements[-1]["id"])

    def test_con_cifras_y_sin_fuente_se_rechaza_y_no_crea_nada(self):
        b = new_board()
        result, new = agent_review.tool_crear_postit(
            b, {"text": "El margen es de 1,2 y es poco", "kind": "riesgo"})
        self.assertTrue(result["is_error"])
        self.assertIn("fuente", result["content"][0]["text"])
        self.assertEqual((new, reopen(b).elements), ([], []))

    def test_solo_deja_riesgos_preguntas_y_sugerencias_y_sin_animacion(self):
        b = new_board()
        for args in ({"text": "apunte", "kind": "nota"}, {"text": "apunte", "kind": "orden"},
                     {"text": "mira", "kind": "riesgo", "animacion": "<html></html>"}):
            result, new = agent_review.tool_crear_postit(b, args)
            self.assertTrue(result["is_error"], args)
            self.assertEqual(new, [])
        self.assertEqual(reopen(b).elements, [])
        props = agent_review.REVIEW_POSTIT_SCHEMA["properties"]
        self.assertEqual(props["kind"]["enum"], ["riesgo", "pregunta", "sugerencia"])
        self.assertNotIn("animacion", props)

    def test_como_mucho_cinco_post_its_por_revision(self):
        b = new_board()
        for i in range(MAX_POSTITS):
            result, _ = agent_review.tool_crear_postit(b, {"text": f"riesgo {chr(97 + i)}",
                                                           "kind": "riesgo"}, created=i)
            self.assertNotIn("is_error", result)
        result, new = agent_review.tool_crear_postit(b, {"text": "otro más", "kind": "riesgo"},
                                                     created=MAX_POSTITS)
        self.assertTrue(result["is_error"])
        self.assertEqual((new, len(reopen(b).elements)), ([], MAX_POSTITS))


class ElPerfilEnCadaRevision(unittest.TestCase):
    """Con perfil de fabricación, cada revisión pide contrastar con él piezas y procesos; sin
    perfil, el mensaje no lo menciona (e2e de FF 6.1: en el prompt de sistema solo, no lo usaba)."""

    def test_con_perfil_el_mensaje_pide_contrastar_con_el_y_sin_perfil_nada(self):
        con = agent_review.review_message("la transmisión de J2", None, True)
        self.assertIn(agent_review.PROFILE_CHECK, con)
        self.assertLess(con.index("la transmisión"), con.index(agent_review.PROFILE_CHECK))
        sin = agent_review.review_message("la transmisión de J2", None, False)
        self.assertNotIn("perfil", sin)


class NoRepetirLoDescartado(unittest.TestCase):
    def test_lo_que_ve_incluye_los_descartados_con_su_texto_y_estado(self):
        b = new_board()
        pid = _postit_del_usuario(b, "El tornillo M6 se afloja con la vibración", "descartado")
        data = _data(agent_mod.tool_leer_pizarra(b, {}, review=True))
        p = next(x for x in data["postits"] if x["id"] == pid)
        self.assertEqual((p["text"], p["state"]),
                         ("El tornillo M6 se afloja con la vibración", "descartado"))
        self.assertIn("descartado", data["note"])

    def test_no_ve_las_propuestas_ni_el_catalogo_del_de_diseno(self):
        b = new_board()
        nid = _postit_del_usuario(b, "Brida", "abierto", kind="nota")
        agent_mod.tool_proponer_cambio(b, {"target": nid, "change": {"text": "Brida de 6 mm"},
                                           "reason": "MOTIVO-DEL-DISENO",
                                           "estimate": True})
        text = agent_mod.tool_leer_pizarra(b, {}, review=True)["content"][0]["text"]
        self.assertNotIn("MOTIVO-DEL-DISENO", text)
        for clave in ("proposals", "my_proposals", "catalog"):
            self.assertNotIn(clave, json.loads(text))
        # y el de diseño los sigue viendo
        self.assertIn("MOTIVO-DEL-DISENO", agent_mod.tool_leer_pizarra(b, {})["content"][0]["text"])


class CalcularEnConsulta(unittest.TestCase):
    def setUp(self):
        self.b, self.ids = _board_con_calculo()
        self.viga = self.ids["rv.viga"]

    def calcular(self, args):
        return asyncio.run(agent_review.tool_calcular(self.b, args))

    def test_calcular_nunca_cambia_la_escena_ni_el_estado_ni_las_salidas(self):
        antes = (copy.deepcopy(self.b.elements), copy.deepcopy(self.b.state))
        disco = reopen(self.b)
        en_disco = (copy.deepcopy(disco.elements), copy.deepcopy(disco.state))
        result = self.calcular({"bloque": self.viga, "params": {"L": 1000}})
        self.assertNotIn("is_error", result)
        self.assertEqual(_data(result)["resultado"]["masa"]["value"], 2000)
        self.assertEqual((self.b.elements, self.b.state), antes)
        self.assertEqual(self.b.state[self.viga]["params"]["L"], 300)
        self.assertEqual(self.b.state[self.viga]["outputs"]["out"]["masa"]["value"], 600)
        disco = reopen(self.b)
        self.assertEqual((disco.elements, disco.state), en_disco)

    def test_lo_que_da_se_cita_como_calculo_nunca_como_bloque(self):
        data = _data(self.calcular({"bloque": self.viga, "params": {"L": 1000}}))
        self.assertEqual(data["cite_as"]["kind"], "calculo")
        self.assertIn(f"bloque:{self.viga}", data["cite_as"]["formula"])
        self.assertIn("L=1000", data["cite_as"]["formula"])

    def test_sin_vista_previa_o_con_parametros_que_no_valen_dice_por_que(self):
        for args, motivo in (({"bloque": self.ids["rv.sin"]}, "vista previa"),
                             ({"bloque": self.viga, "params": {"X": 1}}, "X"),
                             ({"bloque": self.viga, "params": {"L": "largo"}}, "L"),
                             ({"bloque": "no-existe"}, "no-existe")):
            result = self.calcular(args)
            self.assertTrue(result["is_error"], args)
            self.assertIn(motivo, result["content"][0]["text"])
        self.assertEqual(self.b.state[self.viga]["params"]["L"], 300)


# --------------------------------------------------- con el SDK sustituido (opciones)
def _herramientas(agent):
    """Las herramientas que monta `agent._options()` y sus opciones, sin el SDK de verdad."""
    tools = []

    def servidor(name, version, ts):
        tools[:] = ts
        return {"type": "sdk", "name": name, "instance": None}

    with mock.patch.object(sdk, "create_sdk_mcp_server", servidor):
        opts = agent._options()
    return {t.name: t for t in tools}, opts


@unittest.skipUnless(SDK, "falta claude_agent_sdk")
class ElRevisorAislado(unittest.TestCase):
    def setUp(self):
        self.b = new_board()

        async def nada(*a):
            pass
        self.nada = nada

    def test_sus_herramientas_son_las_suyas_aunque_el_de_diseno_tenga_mas(self):
        real = agent_board_tools.sdk_tools

        def con_una_mas(agent, tool):
            @tool("borrar_todo", "escribe", {})
            async def borrar(args):
                return agent_mod._ok("borrado")
            return real(agent, tool) + [borrar]

        with mock.patch.object(agent_board_tools, "sdk_tools", con_una_mas), \
                mock.patch.object(agent_board_tools, "NAMES",
                                  agent_board_tools.NAMES + ("borrar_todo",)):
            diseno, _ = _herramientas(agent_mod.DesignAgent(self.b, self.nada))
            revisor, opts = _herramientas(agent_review.ReviewAgent(self.b, self.nada))
        self.assertIn("borrar_todo", diseno)
        self.assertEqual(set(revisor), set(TOOLS))
        self.assertEqual(set(opts.allowed_tools), {f"mcp__pizarra__{n}" for n in TOOLS})
        for escritora in ("proponer_cambio", "crear_bloque", "conectar", "ejecutar_bloque",
                          "marcar", "crear_archivo", "editar_archivo", "crear_paquete",
                          "borrar_todo"):
            self.assertNotIn(escritora, revisor)
        self.assertEqual((opts.tools, opts.setting_sources, opts.strict_mcp_config),
                         ([], [], True))

    def test_su_crear_postit_firma_como_revisor_y_corta_en_cinco(self):
        revisor, _ = _herramientas(agent_review.ReviewAgent(self.b, self.nada))
        crear = revisor["crear_postit"]
        for i in range(MAX_POSTITS + 1):
            r = asyncio.run(crear.handler({"text": f"riesgo {chr(97 + i)}", "kind": "riesgo"}))
        self.assertTrue(r["is_error"])
        autores = [e["customData"]["author"] for e in reopen(self.b).elements]
        self.assertEqual(autores, [REVIEWER] * MAX_POSTITS)

    def test_el_modelo_de_cada_agente_sale_de_sus_ajustes_y_pizarra_model_manda(self):
        s = Settings.load(Path(tempfile.mkdtemp()) / "settings.toml")
        s.set_agent_model("revisor", "sonnet")
        with mock.patch.dict(os.environ, {"PIZARRA_MODEL": ""}):
            _, d = _herramientas(agent_mod.DesignAgent(self.b, self.nada, settings=s))
            _, r = _herramientas(agent_review.ReviewAgent(self.b, self.nada, settings=s))
            self.assertEqual((d.model, r.model), ("opus", "sonnet"))
        with mock.patch.dict(os.environ, {"PIZARRA_MODEL": "haiku"}):
            _, d = _herramientas(agent_mod.DesignAgent(self.b, self.nada, settings=s))
            _, r = _herramientas(agent_review.ReviewAgent(self.b, self.nada, settings=s))
            self.assertEqual((d.model, r.model), ("haiku", "haiku"))

    def test_los_dos_leen_el_perfil_de_fabricacion_y_sin_el_nada(self):
        _, d = _herramientas(agent_mod.DesignAgent(self.b, self.nada))
        _, r = _herramientas(agent_review.ReviewAgent(self.b, self.nada))
        for o in (d, r):
            self.assertNotIn(agent_prompt.PROFILE_HEAD, o.system_prompt)
        self.b.ws.save_manufacturing_profile("   \n")              # vacío: tampoco
        _, r = _herramientas(agent_review.ReviewAgent(self.b, self.nada))
        self.assertNotIn(agent_prompt.PROFILE_HEAD, r.system_prompt)
        self.b.ws.save_manufacturing_profile("## Máquinas\n- Fresadora CNC FRESA-XYZ")
        _, d = _herramientas(agent_mod.DesignAgent(self.b, self.nada))
        _, r = _herramientas(agent_review.ReviewAgent(self.b, self.nada))
        for o in (d, r):
            self.assertIn("FRESA-XYZ", o.system_prompt)


# ------------------------------------------------- la conversación del revisor (agent_chat)
class AgenteRevisorFalso:
    """Sustituto de ReviewAgent: apunta lo que recibe y acaba como diga `done`."""
    def __init__(self, test):
        self.test = test
        self.session_id = None
        self.max_budget_usd = None
        test.revisores.append(self)

    async def ask(self, message, emit):
        self.test.revisiones.append({"text": message, "budget": self.max_budget_usd,
                                     "resume": self.session_id})
        await emit({"kind": "text", "text": "Nada que objetar."})
        self.session_id = "ses-revisor"
        await emit({"kind": "done", "turns": 1, "seconds": 0.1, "subtype": "success",
                    "terminal_reason": "completed", "usage": USO, "cost_usd": self.test.coste})


class _ConRevisor(_Base):
    def setUp(self):
        super().setUp()
        self.revisores, self.revisiones = [], []
        self.review_factory = lambda session: AgenteRevisorFalso(self)

    def review(self, **kw):
        c = self.chat(**kw)

        async def broadcast(m):
            self.broadcast.append(m)
        return c, AgentReview(c, lambda: self.review_factory(c.session), broadcast)

    async def revisar(self, r, foco=None, once=False):
        w = VentanaFalsa()
        await r.handle(w, {"type": "review_ask", **({"foco": foco} if foco else {}),
                           **({"once": True} if once else {})})
        if r.chat._task is not None:
            await r.chat._task
        return w.sent

    async def esperar(self, c):
        while c._task is not None:
            await c._task

    def eventos_revisor(self):
        return [m for m in self.broadcast if m["type"] == "agent" and m.get("agent") == REVIEW]


class LaConversacionDelRevisorVaAparte(_ConRevisor):
    async def test_sus_eventos_van_a_review_jsonl_con_su_sesion_y_nunca_al_chat(self):
        self.ws.append_agent_chat(self.pid, [{"kind": "user", "text": SECRETO}])
        self.ws.save_agent_file(self.pid, "sessions", {"chat": {"session_id": "ses-diseno"}})
        c, r = self.review()
        await self.revisar(r, foco="la transmisión de J2")
        self.assertEqual(self.revisiones[0]["resume"], None)       # nunca la del de diseño
        self.assertNotIn(SECRETO, self.revisiones[0]["text"])
        self.assertIn("la transmisión de J2", self.revisiones[0]["text"])
        self.assertEqual([e["kind"] for e in c.store.history(REVIEW_CHAT)], ["user", "text", "done"])
        self.assertEqual(c.store.history(REVIEW_CHAT)[0]["foco"], "la transmisión de J2")
        self.assertEqual([e["text"] for e in c.store.history()], [SECRETO])   # el chat, igual
        self.assertEqual((c.store.session_id(), c.store.session_id(REVIEW)),
                         ("ses-diseno", "ses-revisor"))
        self.assertTrue(all(m.get("agent") == REVIEW for m in self.broadcast
                            if m["type"] == "agent"))
        await self.revisar(r)                                       # sigue su propia sesión
        self.assertEqual(self.revisiones[1]["resume"], "ses-revisor")

    async def test_el_review_state_del_final_dice_que_ya_no_revisa(self):
        # e2e FF 6.1: al acabar, `review_state` salía con running = true (se mandaba antes de
        # soltar al agente)
        c, r = self.review()
        await self.revisar(r)
        states = [m for m in self.broadcast if m["type"] == "review_state"]
        self.assertTrue(states)
        self.assertFalse(states[-1]["running"])
        self.assertFalse(r.state()["running"])

    async def test_apagado_no_revisa(self):
        self.settings.review_intrusiveness = "apagado"
        _, r = self.review()
        with self.assertRaises(ValidationError):
            await self.revisar(r)
        self.assertEqual(self.revisores, [])

    async def test_un_foco_que_no_es_texto_o_demasiado_largo_se_rechaza(self):
        _, r = self.review()
        for malo in (3, "x" * (agent_review.FOCO_MAX + 1)):
            with self.assertRaises(ValidationError, msg=malo):
                await r.handle(VentanaFalsa(), {"type": "review_ask", "foco": malo})
        self.assertEqual(self.revisores, [])

    async def test_uno_a_la_vez_con_el_de_diseno(self):
        c, r = self.review()
        c.session.agent_busy = True
        with self.assertRaises(ValidationError):
            await self.revisar(r)
        self.assertEqual(self.revisores, [])

    async def test_cancelar_sin_revision_en_curso_es_un_error(self):
        _, r = self.review()
        with self.assertRaises(ValidationError):
            await r.handle(VentanaFalsa(), {"type": "review_cancel"})

    async def test_el_historial_es_el_suyo(self):
        self.ws.append_agent_chat(self.pid, [{"kind": "user", "text": SECRETO}])
        _, r = self.review()
        await self.revisar(r)
        w = VentanaFalsa()
        await r.handle(w, {"type": "review_history"})
        (msg,) = w.sent
        self.assertEqual(msg["type"], "review_history")
        self.assertEqual([e["kind"] for e in msg["events"]], ["user", "text", "done"])
        self.assertNotIn(SECRETO, json.dumps(msg, ensure_ascii=False))
        self.assertEqual(msg["state"]["intrusiveness"], "a_demanda")


class ElConsumoDelRevisor(_ConRevisor):
    async def test_lo_del_revisor_suma_en_revisor_y_cuenta_para_el_tope(self):
        AgentStore(self.ws, self.pid).add_usage(DESIGN, message_usage({}, 1.0))
        c, r = self.review()
        await self.revisar(r)
        u = c.store.usage()
        self.assertEqual((u["agents"]["revisor"]["usd"], u["agents"]["diseno"]["usd"]),
                         (0.25, 1.0))
        self.assertEqual(u["total"]["usd"], 1.25)
        self.assertEqual(self.revisiones[0]["budget"], 4.0)        # lo que queda del tope
        done = self.eventos_revisor()[-1]
        self.assertEqual((done["kind"], done["total"]["usd"]), ("done", 1.25))
        # y con el tope alcanzado entre los dos, ni el revisor ni el de diseño empiezan
        AgentStore(self.ws, self.pid).add_usage(DESIGN, message_usage({}, 3.75))
        sent = await self.revisar(r)
        self.assertEqual((sent[0]["kind"], sent[0]["agent"]), ("limit", REVIEW))
        self.assertEqual(len(self.revisiones), 1)
        sent = await self.ask(c, "hola")
        self.assertEqual(sent[0]["kind"], "limit")

    async def test_sin_entendido_sale_el_aviso_con_su_foco_y_no_revisa(self):
        settings = Settings.load(self.tmp / "nuevo.toml")
        c, r = self.review(settings=settings)
        sent = await self.revisar(r, foco="J2")
        self.assertEqual((sent[0]["kind"], sent[0]["agent"], sent[0]["foco"]),
                         ("privacy", REVIEW, "J2"))
        self.assertEqual((self.revisores, c.store.history(REVIEW_CHAT)), ([], []))

    async def test_sin_api_key_lo_dice_como_el_de_diseno(self):
        from pizarra import api_key

        class SinClave(AgenteRevisorFalso):
            async def ask(self, message, emit):
                raise api_key.MissingKey()
        self.review_factory = lambda session: SinClave(self)
        c, r = self.review()
        await self.revisar(r)
        err = self.eventos_revisor()[-1]
        self.assertEqual(err["kind"], "error")
        self.assertIn("API key", err["text"])
        self.assertFalse(c.session.agent_busy)


class LosHitos(_ConRevisor):
    def guardar(self, c, name, auto=False):
        return c.session.board.save_version(name, auto=auto)

    async def test_con_hitos_una_version_con_nombre_revisa_lo_cambiado_desde_la_anterior(self):
        self.settings.review_intrusiveness = "hitos"
        c, r = self.review()
        b = c.session.board
        self.guardar(c, "Primer encaje")
        self.guardar(c, "automática", auto=True)
        pid = _postit_del_usuario(b, "Falta el par de J2", "abierto")
        v = self.guardar(c, "Con la nota")
        self.assertEqual(await r.milestone(v), "started")
        await self.esperar(c)
        (msg,) = self.revisiones
        self.assertIn("Con la nota", msg["text"])
        self.assertIn("Primer encaje", msg["text"])
        self.assertIn(pid, msg["text"])
        self.assertIn("Falta el par de J2", msg["text"])
        user = c.store.history(REVIEW_CHAT)[0]
        self.assertEqual((user["milestone"]["name"], user["milestone"]["previous"]["name"]),
                         ("Con la nota", "Primer encaje"))

    async def test_la_primera_version_con_nombre_revisa_la_pizarra_entera(self):
        self.settings.review_intrusiveness = "hitos"
        c, r = self.review()
        await r.milestone(self.guardar(c, "Primera"))
        await self.esperar(c)
        self.assertIn("la primera con nombre", self.revisiones[0]["text"])

    async def test_con_a_demanda_o_apagado_nunca_y_una_automatica_tampoco(self):
        for modo in ("a_demanda", "apagado"):
            self.settings.review_intrusiveness = modo
            c, r = self.review()
            self.assertIsNone(await r.milestone(self.guardar(c, f"V {modo}")))
        self.settings.review_intrusiveness = "hitos"
        c, r = self.review()
        self.assertIsNone(await r.milestone(self.guardar(c, "auto", auto=True)))
        self.assertEqual(self.revisores, [])

    async def test_con_el_de_diseno_trabajando_el_hito_espera_a_que_acabe(self):
        self.settings.review_intrusiveness = "hitos"
        c, r = self.review()
        c.session.clients.add(object())             # el proyecto sigue abierto
        go = asyncio.Event()
        test = self

        class Lento:
            session_id, max_budget_usd = None, None

            async def ask(self, message, emit):
                await go.wait()
                await emit({"kind": "done", "turns": 1, "seconds": 1, "subtype": "success",
                            "terminal_reason": "completed", "usage": USO, "cost_usd": 0.1})
        self.agent_factory = lambda session: Lento()
        await c.handle(VentanaFalsa(), {"type": "agent_ask", "text": "diseña"})
        self.assertEqual(await r.milestone(self.guardar(c, "Hito")), "queued")
        self.assertEqual(test.revisiones, [])
        go.set()
        await self.esperar(c)
        self.assertEqual(len(self.revisiones), 1)
        self.assertEqual(c.store.usage()["agents"]["revisor"]["messages"], 1)

    async def test_las_cuentas_de_sus_post_its_por_estado(self):
        c, r = self.review()
        b = c.session.board
        _, (uno,) = agent_review.tool_crear_postit(b, {"text": "uno", "kind": "riesgo"})
        agent_review.tool_crear_postit(b, {"text": "dos", "kind": "pregunta"})
        agent_mod.tool_crear_postit(b, {"text": "del de diseño", "kind": "nota"})
        cd = {**uno["customData"], "state": "descartado"}
        b.apply_client_elements([scene.bumped({**uno, "customData": cd})])
        self.assertEqual(r.state()["postits"],
                         {"abierto": 1, "aceptado": 0, "descartado": 1, "total": 2})


@unittest.skipUnless(SDK, "falta claude_agent_sdk")
class ConElRevisorDeVerdad(_ConRevisor):
    def setUp(self):
        super().setUp()

        async def nada(*a):
            pass
        self.review_factory = lambda session: agent_review.ReviewAgent(session.board, nada)
        ClienteFalso.script = [
            sdk.AssistantMessage(content=[sdk.TextBlock("Nada que objetar.")], model="opus"),
            sdk.ResultMessage(subtype="success", duration_ms=1200, duration_api_ms=1000,
                              is_error=False, num_turns=2, session_id="ses-sdk-revisor",
                              total_cost_usd=0.3, usage=USO, terminal_reason="completed")]
        p = mock.patch.object(sdk, "ClaudeSDKClient", ClienteFalso)
        p.start()
        self.addCleanup(p.stop)

    async def test_su_prompt_y_su_contexto_nunca_tienen_el_chat_ni_la_sesion_del_de_diseno(self):
        self.ws.append_agent_chat(self.pid, [{"kind": "user", "text": SECRETO},
                                             {"kind": "text", "text": SECRETO + "-respuesta"}])
        self.ws.save_agent_file(self.pid, "sessions", {"chat": {"session_id": "ses-diseno"}})
        c, r = self.review()
        await self.revisar(r)
        cliente = ClienteFalso.ultimo
        self.assertIsNone(cliente.options.resume)
        for texto in (cliente.options.system_prompt, cliente.message):
            self.assertNotIn(SECRETO, texto)
            self.assertNotIn("ses-diseno", texto)
        self.assertEqual((c.store.session_id(), c.store.session_id(REVIEW)),
                         ("ses-diseno", "ses-sdk-revisor"))
        await self.revisar(r)
        self.assertEqual(ClienteFalso.ultimo.options.resume, "ses-sdk-revisor")
        u = c.store.usage()["agents"]
        self.assertEqual((list(u), u["revisor"]["messages"]), (["revisor"], 2))


# ------------------------------------------------------------------------------ ajustes
class LosAjustesDeLosAgentes(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "settings.toml"

    def test_por_defecto_a_demanda_y_opus_y_un_valor_ilegible_tambien(self):
        s = Settings.load(self.path)
        self.assertEqual((s.review_intrusiveness, s.saved_model("diseno"),
                          s.saved_model("revisor")), ("a_demanda", "opus", "opus"))
        self.path.write_text('[agentes]\nintrusividad_revisor = "continuo"\nmodelo_revisor = 3\n',
                             encoding="utf-8")
        s = Settings.load(self.path)
        self.assertEqual((s.review_intrusiveness, s.saved_model("revisor")), ("a_demanda", "opus"))

    def test_la_api_los_da_con_sus_opciones_y_los_guarda(self):
        s = Settings.load(self.path)
        settings_api.apply(s, None, {"agentes": {"intrusividad_revisor": "hitos",
                                                 "modelo_diseno": "sonnet",
                                                 "modelo_revisor": "opus"}})
        s.save()
        v = settings_api.view(Settings.load(self.path), None)
        self.assertEqual((v["agentes"]["intrusividad_revisor"], v["agentes"]["modelo_diseno"],
                          v["agentes"]["modelo_revisor"]), ("hitos", "sonnet", "opus"))
        self.assertEqual(v["opciones"]["intrusividades_revisor"], ["apagado", "a_demanda", "hitos"])
        self.assertEqual(v["opciones"]["modelos"], ["opus", "sonnet"])

    def test_uno_que_no_vale_se_rechaza_con_su_motivo(self):
        s = Settings.load(self.path)
        for changes, palabra in (({"agentes": {"intrusividad_revisor": "continuo"}}, "intrusividad"),
                                 ({"agentes": {"modelo_diseno": "gpt"}}, "modelo_diseno"),
                                 ({"agentes": {"modelo_revisor": None}}, "modelo_revisor")):
            with self.assertRaises(ValueError, msg=changes) as cm:
                settings_api.apply(s, None, changes)
            self.assertIn(palabra, str(cm.exception))


# ------------------------------------------------------------- el servidor de verdad
try:
    import uvicorn
    from websockets.sync.client import connect
    from pizarra.server import create_app
    from pizarra.startup import bootstrap
    from tests.test_server import _free_port
    DEPS = True
except ImportError:                     # job básico del CI
    DEPS = False


class RevisorDelServidor:
    """Sustituto de ReviewAgent en el servidor: deja un post-it suyo y acaba."""
    mensajes = []

    def __init__(self, board, on_elements, **k):
        self.board, self.on_elements = board, on_elements
        self.session_id = self.max_budget_usd = None

    async def ask(self, message, emit):
        RevisorDelServidor.mensajes.append(message)
        _, new = agent_review.tool_crear_postit(self.board, {"text": "¿Y la fatiga?",
                                                             "kind": "pregunta"})
        await self.on_elements(new)
        await emit({"kind": "done", "turns": 1, "seconds": 0.1})


@unittest.skipUnless(DEPS, "faltan fastapi/uvicorn/websockets")
class ElRevisorEnElServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._real = agent_review.ReviewAgent
        agent_review.ReviewAgent = RevisorDelServidor
        cls.port = _free_port()
        cls.tmp = Path(tempfile.mkdtemp())
        start = bootstrap(cls.tmp / "settings.toml", cls.tmp / "Documentos" / "Personal", ())
        cls.workspace = start.workspace
        start.settings.privacy_seen = True
        start.settings.language = "es"
        start.settings.save()
        cls.project = start.workspace.create_project("", "Proyecto").id
        cls.server = uvicorn.Server(uvicorn.Config(create_app(start), host="127.0.0.1",
                                                   port=cls.port, log_level="error"))
        import threading
        import time
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        t0 = time.time()
        while not cls.server.started and time.time() - t0 < 10:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        agent_review.ReviewAgent = cls._real

    def setUp(self):
        RevisorDelServidor.mensajes = []

    def api(self, method, path, body=None):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def ws(self):
        c = connect(f"ws://127.0.0.1:{self.port}/ws?project={self.project}", open_timeout=5)
        init = json.loads(c.recv(timeout=5))
        self.assertEqual(init["type"], "init")
        return c, init

    def recv_until(self, c, pred, timeout=5):
        import time
        t0 = time.time()
        while time.time() - t0 < timeout:
            msg = json.loads(c.recv(timeout=timeout))
            if pred(msg):
                return msg
        self.fail("no llegó")

    def test_review_ask_revisa_y_sus_eventos_llegan_marcados(self):
        c, init = self.ws()
        try:
            self.assertEqual(init["review"]["intrusiveness"], "a_demanda")
            c.send(json.dumps({"type": "review_ask", "foco": "J2"}))
            user = self.recv_until(c, lambda m: m["type"] == "agent" and m["kind"] == "user")
            self.assertEqual((user["agent"], user["foco"]), (REVIEW, "J2"))
            done = self.recv_until(c, lambda m: m["type"] == "agent" and m["kind"] == "done")
            self.assertEqual(done["agent"], REVIEW)
            st = self.recv_until(c, lambda m: m["type"] == "review_state")
            self.assertGreaterEqual(st["postits"]["abierto"], 1)
        finally:
            c.close()
        self.assertIn("J2", RevisorDelServidor.mensajes[0])

    def test_guardar_una_version_con_nombre_revisa_solo_con_hitos(self):
        base = f"/api/projects/{self.project}"
        c, _ = self.ws()
        try:
            self.assertEqual(self.api("POST", f"{base}/versions", {"name": "Sin hito"})[0], 200)
            self.recv_until(c, lambda m: m["type"] == "versions")
            self.assertEqual(self.api("PUT", "/api/settings",
                                      {"agentes": {"intrusividad_revisor": "hitos"}})[0], 200)
            self.assertEqual(self.api("POST", f"{base}/versions", {"name": "Con hito"})[0], 200)
            user = self.recv_until(c, lambda m: m["type"] == "agent" and m["kind"] == "user")
            self.assertEqual((user["agent"], user["milestone"]["name"],
                              user["milestone"]["previous"]["name"]),
                             (REVIEW, "Con hito", "Sin hito"))
            self.recv_until(c, lambda m: m["type"] == "agent" and m["kind"] == "done")
        finally:
            c.close()
            self.api("PUT", "/api/settings", {"agentes": {"intrusividad_revisor": "a_demanda"}})
        self.assertEqual(len(RevisorDelServidor.mensajes), 1)

    def test_un_ajuste_del_revisor_que_no_vale_es_un_422_y_no_cambia_el_fichero(self):
        f = self.tmp / "settings.toml"
        antes = f.read_bytes()
        for malo in ({"intrusividad_revisor": "continuo"}, {"modelo_revisor": "gpt"},
                     {"modelo_diseno": "sonnet", "modelo_revisor": "x"}):
            code, body = self.api("PUT", "/api/settings", {"agentes": malo})
            self.assertEqual(code, 422, malo)
        self.assertEqual(f.read_bytes(), antes)
        code, body = self.api("GET", "/api/settings")
        self.assertEqual(body["agentes"]["modelo_diseno"], "opus")

    def test_el_perfil_de_fabricacion_se_lee_con_su_plantilla_y_se_guarda(self):
        code, body = self.api("GET", "/api/workspace/fabricacion")
        self.assertEqual((code, body["guardado"]), (200, False))
        self.assertIn("# Perfil de fabricación", body["texto"])
        self.assertEqual(self.api("PUT", "/api/workspace/fabricacion", {"texto": 3})[0], 422)
        self.assertEqual(self.api("PUT", "/api/workspace/fabricacion",
                                  {"texto": "x" * 20_001})[0], 422)
        self.assertIsNone(self.workspace.load_manufacturing_profile())
        code, body = self.api("PUT", "/api/workspace/fabricacion", {"texto": "- Torno"})
        self.assertEqual((code, body["guardado"], body["texto"]), (200, True, "- Torno"))
        self.assertEqual((self.workspace.root / "profile" / "fabricacion.md")
                         .read_text(encoding="utf-8"), "- Torno")


if __name__ == "__main__":
    unittest.main()
