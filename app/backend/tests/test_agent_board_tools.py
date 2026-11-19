"""Herramientas del agente que montan la pizarra (FF 4.6 paso 2; plan §10, «Herramientas que
montan la pizarra (D170, D171)»).

Reglas que protegen:
- `crear_bloque` solo crea tipos cargados, con autor agente y nunca encima de otro elemento; unos
  parámetros que no valen no dejan nada.
- `conectar` acepta y rechaza lo mismo que una flecha de la interfaz (mismo tipo, entrada
  libre, puerto que existe, sin ciclos); un rechazo no deja nada.
- `poner_plantilla` nunca cae encima de lo que hay.
- El agente nunca cambia los parámetros de un bloque del ingeniero sin propuesta; los de uno
  suyo, sí, directamente (D20).
- `ejecutar_bloque` nunca corre a la vez que otra ejecución del proyecto y no cambia parámetros.
- `ver_zona` sin ventana, pasado el plazo o con una respuesta mala da error con el motivo, nunca
  una imagen vacía; con *Excluir adjuntos*, las imágenes pegadas no salen al agente.

No usan el SDK ni la red: son las funciones que el SDK llama.
"""
import asyncio
import base64
import json
import struct
import unittest
import zlib

from pizarra import agent, agent_board_tools as abt, execution, graph, scene, zone
from tests.helpers import new_board, necesita_paquetes


def _data(result):
    return json.loads(result["content"][0]["text"])


def _overlap(a, b):
    ax0, ay0, ax1, ay1 = scene.bbox(a)
    bx0, by0, bx1, by1 = scene.bbox(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _no_overlaps(test, elements):
    boxes = [e for e in elements if e.get("type") not in ("arrow", "text") and not e.get("isDeleted")]
    for i, a in enumerate(boxes):
        for c in boxes[i + 1:]:
            test.assertFalse(_overlap(a, c), f"{a['id']} tapa a {c['id']}")


def png(w, h):
    """Un PNG de verdad de w × h, en base64."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(
            ">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    data = (zone.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return base64.b64encode(data).decode()


class CrearBloque(unittest.TestCase):
    def setUp(self):
        self.b = new_board()

    @necesita_paquetes
    def test_crea_un_tipo_cargado_suyo_y_devuelve_sus_puertos(self):
        result, new = abt.tool_crear_bloque(self.b, {"tipo": "demo.voladizo"})
        d = _data(result)
        el = new[0]
        self.assertEqual(d["creado"], el["id"])
        self.assertEqual((d["entradas"], d["salidas"]),
                         ({"tubo": "demo.tubo"}, {"voladizo": "demo.voladizo"}))
        self.assertEqual(el["customData"]["author"], agent.AGENT)
        self.assertIn(el["id"], graph.blocks_in(self.b.elements, self.b.registry))

    def test_un_tipo_que_no_esta_cargado_se_rechaza_y_no_deja_nada(self):
        n = len(self.b.elements)
        result, new = abt.tool_crear_bloque(self.b, {"tipo": "demo.no_existe"})
        self.assertTrue(result["is_error"])
        self.assertEqual((new, len(self.b.elements)), ([], n))

    def test_unos_parametros_que_no_valen_no_dejan_nada(self):
        for params in ({"no_existe": 1}, {"L": "mucho"}):
            result, new = abt.tool_crear_bloque(self.b, {"tipo": "demo.tubo", "params": params})
            self.assertTrue(result["is_error"], params)
            self.assertEqual((new, self.b.elements, self.b.state), ([], [], {}))

    @necesita_paquetes
    def test_con_parametros_los_lleva_y_el_resto_por_defecto(self):
        _, new = abt.tool_crear_bloque(self.b, {"tipo": "demo.tubo", "params": {"L": 250}})
        params = self.b.state[new[0]["id"]]["params"]
        self.assertEqual(params, {**self.b.default_params("demo.tubo"), "L": 250})

    @necesita_paquetes
    def test_nunca_cae_encima_de_otro_elemento_ni_junto_a_un_ancla_sin_hueco(self):
        t = scene.block_element("demo.tubo", 0, 0)
        v = scene.block_element("demo.voladizo", 300, 0)        # 20 px a la derecha del tubo
        self.b.apply_client_elements([t, v])
        for _ in range(4):
            result, _ = abt.tool_crear_bloque(self.b, {"tipo": "demo.tubo", "cerca_de": t["id"]})
            self.assertNotIn("is_error", result)
        _no_overlaps(self, self.b.elements)

    def test_cerca_de_un_elemento_que_no_existe_se_rechaza(self):
        result, new = abt.tool_crear_bloque(self.b, {"tipo": "demo.tubo", "cerca_de": "nada"})
        self.assertTrue(result["is_error"])
        self.assertEqual(new, [])


class Conectar(unittest.TestCase):
    """Cada caso se prueba dos veces: con `conectar` y con la flecha que dibujaría la interfaz
    (enganchada a los dos bloques, con sus puertos). Las dos dicen lo mismo."""

    def _board(self):
        b = new_board()
        t1, t2 = scene.block_element("demo.tubo", 0, 0), scene.block_element("demo.tubo", 0, 400)
        v1, v2 = (scene.block_element("demo.voladizo", 400, 0),
                  scene.block_element("demo.voladizo", 400, 400))
        b.apply_client_elements([t1, t2, v1, v2])
        return b, t1["id"], t2["id"], v1["id"], v2["id"]

    def _ui_accepts(self, b, src, frm, dst, to):
        arrow = {"id": "flecha-ui", "type": "arrow", "version": 1, "x": 0, "y": 0,
                 "points": [[0, 0], [10, 0]],
                 "startBinding": {"elementId": src}, "endBinding": {"elementId": dst},
                 "customData": {"kind": "connection", "from": frm, "to": to}}
        _, _, problems = graph.connections(b.elements + [arrow], b.registry)
        return not problems

    def _agent_accepts(self, b, src, frm, dst, to):
        before = list(b.elements)
        result, changed = abt.tool_conectar(b, {"desde": f"{src}:{frm}", "hasta": f"{dst}:{to}"})
        if result.get("is_error"):
            self.assertIn("Rechazado", result["content"][0]["text"])
            self.assertEqual((changed, b.elements), ([], before), "un rechazo no deja nada")
            return False
        return True

    @necesita_paquetes
    def test_acepta_y_rechaza_lo_mismo_que_una_flecha_de_la_interfaz(self):
        cases = {
            "salida con su entrada": lambda t1, t2, v1, v2: (t1, "tubo", v1, "tubo"),
            "tipos distintos": lambda t1, t2, v1, v2: (v1, "voladizo", v2, "tubo"),
            "puerto que no existe": lambda t1, t2, v1, v2: (t1, "tubo", v1, "nada"),
            "consigo mismo": lambda t1, t2, v1, v2: (t1, "tubo", t1, "tubo"),
            "a una salida": lambda t1, t2, v1, v2: (t1, "tubo", t2, "tubo"),
        }
        for name, case in cases.items():
            with self.subTest(name):
                b_ui, *ids = self._board()
                b_ag = new_board()
                b_ag.apply_client_elements(b_ui.elements)
                args = case(*ids)
                self.assertEqual(self._agent_accepts(b_ag, *args), self._ui_accepts(b_ui, *args))
        b, t1, _, v1, _ = self._board()
        self.assertTrue(self._agent_accepts(b, t1, "tubo", v1, "tubo"))

    @necesita_paquetes
    def test_la_conexion_aceptada_entra_en_el_grafo_suya_y_enganchada(self):
        b, t1, _, v1, _ = self._board()
        result, changed = abt.tool_conectar(b, {"desde": f"{t1}:tubo", "hasta": f"{v1}:tubo"})
        arrow = changed[0]
        edges, problems = graph.build(b.elements, b.registry)
        self.assertEqual((edges[v1]["tubo"], problems), ((t1, "tubo"), []))
        self.assertEqual(arrow["customData"]["author"], agent.AGENT)
        for e in b.elements:
            if e["id"] in (t1, v1):
                self.assertIn({"id": arrow["id"], "type": "arrow"}, e["boundElements"])

    @necesita_paquetes
    def test_una_entrada_ocupada_se_rechaza_aunque_la_flecha_nueva_ordene_antes(self):
        # El grafo recorre las flechas por id: una nueva con un id menor le quitaría la entrada
        # a la de antes. Nunca: la de antes sigue y la nueva se rechaza.
        b, t1, t2, v1, _ = self._board()
        old = {**scene.connection_element(next(e for e in b.elements if e["id"] == t1),
                                          next(e for e in b.elements if e["id"] == v1),
                                          "tubo", "tubo"), "id": "z" * 20}
        b.apply_client_elements([old])
        self.assertFalse(self._agent_accepts(b, t2, "tubo", v1, "tubo"))
        self.assertEqual(graph.build(b.elements, b.registry)[0][v1]["tubo"], (t1, "tubo"))

    @necesita_paquetes
    def test_una_salida_alimenta_a_varias_entradas(self):
        b, t1, _, v1, v2 = self._board()
        self.assertTrue(self._agent_accepts(b, t1, "tubo", v1, "tubo"))
        self.assertTrue(self._agent_accepts(b, t1, "tubo", v2, "tubo"))

    @necesita_paquetes
    def test_sin_puertos_elige_el_unico_posible_y_lo_escribe_en_la_flecha(self):
        b, t1, _, v1, _ = self._board()
        _, changed = abt.tool_conectar(b, {"desde": t1, "hasta": v1})
        cd = changed[0]["customData"]
        self.assertEqual((cd["from"], cd["to"]), ("tubo", "tubo"))

    def test_un_bloque_que_no_existe_se_rechaza(self):
        b, t1, *_ = self._board()
        result, _ = abt.tool_conectar(b, {"desde": f"{t1}:tubo", "hasta": "nada:tubo"})
        self.assertTrue(result["is_error"])


class PonerPlantilla(unittest.TestCase):
    @necesita_paquetes
    def test_nunca_cae_encima_de_lo_que_hay_y_es_del_agente(self):
        b = new_board()
        t = scene.block_element("demo.tubo", 0, 0)
        b.apply_client_elements([t])
        for near in (None, t["id"]):
            result, new = abt.tool_poner_plantilla(b, {"plantilla": "demo.cadena",
                                                       "cerca_de": near})
            d = _data(result)
            self.assertEqual(len(d["bloques"]) + len(d["conexiones"]), len(new))
            self.assertTrue(all(e["customData"]["author"] == agent.AGENT for e in new))
        _no_overlaps(self, b.elements)
        self.assertEqual(graph.build(b.elements, b.registry)[1], [])

    def test_una_plantilla_que_no_existe_se_rechaza_y_no_deja_nada(self):
        b = new_board()
        result, new = abt.tool_poner_plantilla(b, {"plantilla": "demo.nada"})
        self.assertTrue(result["is_error"])
        self.assertEqual((new, b.elements), ([], []))


@necesita_paquetes
class ParametrosYAutoria(unittest.TestCase):
    """D20: lo suyo lo edita directamente; lo del ingeniero, con propuesta."""

    def test_los_parametros_de_un_bloque_suyo_se_cambian_directamente(self):
        b = new_board()
        _, new = abt.tool_crear_bloque(b, {"tipo": "demo.tubo"})
        bid = new[0]["id"]
        result, _, proposed = agent.tool_proponer_cambio(
            b, {"target": bid, "change": {"params": {"L": 250}}, "reason": "Más corto"})
        self.assertNotIn("is_error", result)
        self.assertFalse(proposed)
        self.assertEqual(b.state[bid]["params"]["L"], 250)
        self.assertEqual(b.proposals, [])

    def test_los_de_un_bloque_del_ingeniero_nunca_sin_propuesta(self):
        b = new_board()
        t = scene.block_element("demo.tubo", 0, 0)
        b.apply_client_elements([t])
        before = dict(b.state[t["id"]]["params"])
        _, _, proposed = agent.tool_proponer_cambio(
            b, {"target": t["id"], "change": {"params": {"L": 250}}, "reason": "Más corto"})
        self.assertTrue(proposed)
        self.assertEqual(b.state[t["id"]]["params"], before)


def _inline(board):
    """La ejecución del servidor, en este proceso: planea con las mismas reglas (`Job.plan`)."""
    async def run_block(bid):
        return await asyncio.to_thread(board.run, bid)
    return run_block


@necesita_paquetes
class EjecutarBloque(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.b = new_board()
        _, new = abt.tool_crear_bloque(self.b, {"tipo": "demo.tubo"})
        self.bid = new[0]["id"]

    async def test_ejecuta_espera_y_da_estado_y_salidas_sin_cambiar_parametros(self):
        before = dict(self.b.state[self.bid]["params"])
        d = _data(await abt.tool_ejecutar_bloque(self.b, {"bloque": self.bid}, _inline(self.b)))
        self.assertEqual((d["estado"], d["ejecutados"], d["cite"]),
                         ("al_dia", [self.bid], f"bloque:{self.bid}"))
        self.assertIn("masa", d["salidas"]["tubo"])
        self.assertEqual(self.b.state[self.bid]["params"], before)

    async def test_nunca_a_la_vez_que_otra_ejecucion_del_proyecto(self):
        job = execution.Job.plan(self.b, self.bid)          # otra, en curso
        ran = []

        async def run_block(bid):
            ran.append(bid)
            return await _inline(self.b)(bid)
        result = await abt.tool_ejecutar_bloque(self.b, {"bloque": self.bid}, run_block)
        self.assertTrue(result["is_error"])
        self.assertIn("en curso", result["content"][0]["text"])
        self.assertIs(self.b.job, job)
        self.assertIsNone(self.b.state[self.bid].get("outputs"))

    async def test_sin_el_servidor_o_con_un_bloque_que_no_existe_da_error(self):
        self.assertTrue((await abt.tool_ejecutar_bloque(self.b, {"bloque": self.bid},
                                                        None))["is_error"])
        self.assertTrue((await abt.tool_ejecutar_bloque(self.b, {"bloque": "nada"},
                                                        _inline(self.b)))["is_error"])


class VentanaFalsa:
    """Lo que el servidor llama de un WebSocket. `reply(msg)` da la respuesta (o None: nunca
    contesta)."""
    def __init__(self, zones, reply):
        self.zones, self.reply, self.sent = zones, reply, []

    async def send_json(self, msg):
        self.sent.append(msg)
        answer = self.reply(msg)
        if answer is not None:
            asyncio.get_running_loop().call_soon(self.zones.answer, {"id": msg["id"], **answer})


class VerZona(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.b = new_board()
        self.t = scene.block_element("demo.tubo", 0, 0)
        self.foto = {"id": "foto", "type": "embeddable", "version": 1, "x": 400, "y": 0,
                     "width": 200, "height": 150,
                     "customData": {"kind": "image", "author": "user",
                                    "image": {"file": "a.png", "width": 200, "height": 150}}}
        self.b.apply_client_elements([self.t, self.foto])
        self.zones = zone.ZoneRequests()

    def _ask(self, windows, args, excluded=False, timeout=0.1):
        async def request_zone(payload):
            return await self.zones.request(windows, payload, timeout=timeout)
        return abt.tool_ver_zona(self.b, args, request_zone, excluded)

    async def test_devuelve_la_imagen_de_la_ventana_como_imagen_del_mcp(self):
        w = VentanaFalsa(self.zones, lambda m: {"png": png(40, 30)})
        result = await self._ask([w], {"x": 0, "y": 0, "ancho": 300, "alto": 200})
        self.assertNotIn("is_error", result)
        img = result["content"][0]
        self.assertEqual((img["type"], img["mimeType"]), ("image", "image/png"))
        self.assertEqual(w.sent[0]["rect"], {"x": 0, "y": 0, "width": 300, "height": 200})
        self.assertEqual(w.sent[0]["maxSide"], zone.MAX_SIDE)

    async def test_sin_ventana_o_pasado_el_plazo_error_nunca_imagen_vacia(self):
        args = {"elementos": [self.t["id"]]}
        for windows in ([], [VentanaFalsa(self.zones, lambda m: None)]):
            result = await self._ask(windows, args)
            self.assertTrue(result["is_error"])
            self.assertFalse(any(c["type"] == "image" for c in result["content"]))
        self.assertEqual(self.zones._pending, {}, "nada se queda esperando")

    async def test_una_respuesta_mala_es_un_error_con_el_motivo(self):
        for answer in ({"error": "no hay lienzo"}, {"png": ""}, {"png": "no es base64!"},
                       {"png": base64.b64encode(b"GIF89a....").decode()},
                       {"png": png(zone.MAX_SIDE + 1, 2)}):
            with self.subTest(answer=str(answer)[:40]):
                w = VentanaFalsa(self.zones, lambda m, a=answer: a)
                result = await self._ask([w], {"elementos": [self.t["id"]]})
                self.assertTrue(result["is_error"])
                self.assertFalse(any(c["type"] == "image" for c in result["content"]))
        w = VentanaFalsa(self.zones, lambda m: {"error": "no hay lienzo"})
        result = await self._ask([w], {"elementos": [self.t["id"]]})
        self.assertIn("no hay lienzo", result["content"][0]["text"])

    async def test_se_pide_a_una_sola_ventana_la_que_pregunto_si_sigue(self):
        a = VentanaFalsa(self.zones, lambda m: {"png": png(4, 4)})
        b = VentanaFalsa(self.zones, lambda m: {"png": png(4, 4)})
        await self.zones.request([a, b], {"elements": [self.t["id"]]}, prefer=b, timeout=0.1)
        self.assertEqual((len(a.sent), len(b.sent)), (0, 1))

    async def test_una_respuesta_que_llega_tarde_se_descarta(self):
        self.assertFalse(self.zones.answer({"id": "vieja", "png": png(4, 4)}))

    async def test_con_excluir_adjuntos_las_imagenes_pegadas_no_salen(self):
        w = VentanaFalsa(self.zones, lambda m: {"png": png(4, 4)})
        result = await self._ask([w], {"elementos": [self.foto["id"]]}, excluded=True)
        self.assertTrue(result["is_error"])
        self.assertIn("Excluir adjuntos", result["content"][0]["text"])
        self.assertEqual(w.sent, [], "ni se pide")
        result = await self._ask([w], {"elementos": [self.t["id"], self.foto["id"]]}, excluded=True)
        self.assertNotIn("is_error", result)
        self.assertEqual((w.sent[-1]["elements"], w.sent[-1]["excludeImages"]), ([self.t["id"]], True))
        await self._ask([w], {"x": 0, "y": 0, "ancho": 900, "alto": 300}, excluded=True)
        self.assertTrue(w.sent[-1]["excludeImages"])

    async def test_un_recuadro_o_unos_elementos_que_no_valen_se_rechazan_sin_pedir(self):
        w = VentanaFalsa(self.zones, lambda m: {"png": png(4, 4)})
        for args in ({}, {"x": 0, "y": 0, "ancho": 0, "alto": 10}, {"x": 0, "y": 0, "ancho": "a",
                     "alto": 1}, {"elementos": ["nada"]},
                     {"elementos": [self.t["id"]], "x": 0, "y": 0, "ancho": 1, "alto": 1}):
            with self.subTest(args=args):
                self.assertTrue((await self._ask([w], args))["is_error"])
        self.assertEqual(w.sent, [])


@necesita_paquetes
class LeerPizarraTraeElCatalogo(unittest.TestCase):
    def test_los_tipos_y_las_plantillas_que_se_pueden_poner(self):
        d = _data(agent.tool_leer_pizarra(new_board(), {}))
        self.assertEqual(d["catalog"]["blocks"]["demo.voladizo"]["inputs"], {"tubo": "demo.tubo"})
        self.assertIn("demo.cadena", d["catalog"]["templates"])


if __name__ == "__main__":
    unittest.main()


class EjecutarNuncaEscribeFuera(unittest.IsolatedAsyncioTestCase):
    """Prueba de punta a punta de FF 4.6: con Fusion abierto, `ejecutar_bloque` de una lista de
    materiales lanzó *Construir en Fusion* (lo de delante, D89) y creó un proyecto en el hub.
    El agente nunca lanza nada que escriba fuera del proyecto: un bloque que pide un conector
    se ejecuta solo con *Ejecutar* del ingeniero; sus salidas ya al día sí se usan."""

    def setUp(self):
        from tests import test_graph as tg
        self.tg = tg
        self.reg, self.calls = tg.registry()
        P = tg.packs.Param
        self.reg["p.lista"] = tg.packs.BlockType(
            "p.lista", "Lista", {}, {"in": "p.a", "med": "cad.modelo"}, {"out": "p.b"},
            lambda p, i, c: self.calls.append(c.block_id) or {"out": {"n": tg._v(1)}},
            optional=("med",))
        self.b = tg.board(self.reg, frozenset({"cad"}))          # Fusion abierto
        els, (self.f, self.cad, self.l) = tg.blocks("p.fuente", "p.cad", "p.lista")
        self.b.apply_client_elements(els + [tg.arrow("1", self.f, self.cad, "x", "in"),
                                            tg.arrow("2", self.f, self.l, "y", "in"),
                                            tg.arrow("3", self.cad, self.l, "m", "med")])

    async def test_con_un_bloque_de_conector_delante_sin_ejecutar_no_ejecuta_nada_y_lo_dice(self):
        ran = []

        async def run_block(bid):
            ran.append(bid)
            return await _inline(self.b)(bid)
        result = await abt.tool_ejecutar_bloque(self.b, {"bloque": self.l}, run_block)
        self.assertTrue(result["is_error"])
        text = result["content"][0]["text"]
        self.assertIn("pulsa Ejecutar tú", text)
        self.assertIn("Construir", text)
        self.assertIn(self.cad, text)
        self.assertEqual((ran, self.calls), ([], []))
        self.assertIsNone(self.b.job)

    async def test_ni_el_propio_bloque_de_conector(self):
        result = await abt.tool_ejecutar_bloque(self.b, {"bloque": self.cad}, _inline(self.b))
        self.assertTrue(result["is_error"])
        self.assertEqual(self.calls, [])

    async def test_con_el_de_conector_ya_al_dia_usa_su_salida(self):
        self.b.run(self.cad)                                      # lo pulsó el ingeniero
        self.calls.clear()
        d = _data(await abt.tool_ejecutar_bloque(self.b, {"bloque": self.l}, _inline(self.b)))
        self.assertEqual(d["estado"], "al_dia")
        self.assertNotIn(self.cad, self.calls)

    async def test_sin_fusion_la_cadena_opcional_se_omite_y_se_ejecuta(self):
        self.b._connectors = frozenset()
        d = _data(await abt.tool_ejecutar_bloque(self.b, {"bloque": self.l}, _inline(self.b)))
        self.assertEqual(d["estado"], "al_dia")
        self.assertNotIn(self.cad, self.calls)
