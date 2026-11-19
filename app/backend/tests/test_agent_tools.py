"""Herramientas del agente de diseño (plan §4): lo que el agente escribe pasa por las reglas.

No usan el SDK ni la red: son las funciones que el SDK llama (las que miran las opciones de un
mensaje se saltan sin `claude_agent_sdk`).

Reglas de FF 4.6 paso 2 (plan §10):
- **Animaciones** (D143, D144, D175): con «Animaciones automáticas» desactivado, el prompt lleva
  la orden de no hacerlas salvo que se pidan y **nunca** la guía; activado, la lleva; cambiar el
  ajuste cambia el prompt del siguiente mensaje. Desactivado, una animación sin
  `pedida_por_usuario` se rechaza y no crea nada; pedida, se crea. Se guarda en `board/files/` y
  la misma dos veces se guarda una; nunca hace de fuente de una cifra; una que pasa de 256 KB
  se rechaza sin crear nada.
- **Prompt** (D172): el `agent.md` de un paquete cargado entra; el de uno que no cargó, nunca;
  uno largo se corta en su tope.
- **Papeles propuestos** (D177): una propuesta de parámetros que la vista previa del bloque
  rechaza vuelve con el motivo y no deja propuesta; sin vista previa se guarda como siempre; si
  la vista previa tarda, se guarda con una nota.
"""
import asyncio
import hashlib
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pizarra import agent, agent_prompt, packs, scene
from pizarra.board import Board
from pizarra.settings import Settings
from pizarra.storage import NotFound
from tests.helpers import new_board, reopen, necesita_paquetes
from tests.test_pack_load import write

try:
    import claude_agent_sdk  # noqa: F401
    SDK = True
except ImportError:                     # job básico del CI
    SDK = False


def _board_con_cadena():
    b = new_board()
    t, v = scene.block_element("demo.tubo", 0, 0), scene.block_element("demo.voladizo", 400, 0)
    b.apply_client_elements([t, v, {"id": "a", "type": "arrow", "version": 1,
                                    "startBinding": {"elementId": t["id"]},
                                    "endBinding": {"elementId": v["id"]}}])
    b.run(v["id"])
    return b, t["id"], v["id"]


@necesita_paquetes
class HerramientasDelAgente(unittest.TestCase):
    def test_leer_pizarra_da_las_salidas_resumidas_y_como_citarlas(self):
        b, _, v = _board_con_cadena()
        data = json.loads(agent.tool_leer_pizarra(b, {})["content"][0]["text"])
        vol = next(x for x in data["blocks"] if x["id"] == v)
        self.assertEqual(vol["cite"], f"bloque:{v}")
        sigma = b.state[v]["outputs"]["voladizo"]["sigma"]
        self.assertEqual(vol["outputs"]["voladizo"]["sigma"],
                         f"{sigma['value']:.6g} {sigma['unit']}".strip())

    def test_post_it_con_cifras_sin_fuente_vuelve_al_agente_como_error_y_no_se_guarda(self):
        b, _, _ = _board_con_cadena()
        n = len(b.elements)
        result, new = agent.tool_crear_postit(b, {"text": "La flecha es de 0.4 mm", "kind": "nota"})
        self.assertTrue(result["is_error"])
        self.assertIn("fuente", result["content"][0]["text"])
        self.assertEqual((new, len(b.elements)), ([], n))

    def test_post_it_con_fuente_de_bloque_se_crea_como_del_agente(self):
        b, _, v = _board_con_cadena()
        result, new = agent.tool_crear_postit(b, {
            "text": "La flecha es de 0.4 mm", "kind": "nota",
            "sources": [{"kind": "bloque", "ref": f"bloque:{v}"}]})
        self.assertNotIn("is_error", result)
        self.assertEqual(new[0]["customData"]["author"], "agent:design")

    def test_el_agente_no_puede_firmar_como_otro(self):
        b, _, _ = _board_con_cadena()
        _, new = agent.tool_crear_postit(b, {"text": "ok", "kind": "nota", "author": "user"})
        self.assertEqual(new[0]["customData"]["author"], "agent:design")

    def test_post_its_seguidos_se_apilan_sin_taparse(self):
        b, _, _ = _board_con_cadena()
        _, p1 = agent.tool_crear_postit(b, {"text": "uno", "kind": "nota"})
        _, p2 = agent.tool_crear_postit(b, {"text": "dos", "kind": "nota"})
        r1, r2 = p1[0], p2[0]
        self.assertEqual(r1["x"], r2["x"])
        self.assertGreaterEqual(r2["y"], r1["y"] + r1["height"])

    def test_post_it_anclado_va_junto_a_su_elemento_si_hay_hueco(self):
        b, _, v = _board_con_cadena()
        vol = next(e for e in b.elements if e["id"] == v)
        _, p = agent.tool_crear_postit(b, {"text": "ojo", "kind": "riesgo", "anchor": v})
        self.assertEqual((p[0]["x"], p[0]["y"]), (vol["x"] + vol["width"] + 40, vol["y"]))

    def test_un_post_it_nunca_tapa_otro_elemento_aunque_el_ancla_no_deje_hueco(self):
        # El Tubo tiene el Voladizo a 120 px a su derecha: no cabe un post-it de 260 px ahí.
        b, t, _ = _board_con_cadena()
        for i in range(6):
            agent.tool_crear_postit(b, {"text": f"observación {'x' * 20 * i}", "kind": "riesgo",
                                        "anchor": t})
        rects = [e for e in b.elements if e.get("type") != "text" and e.get("type") != "arrow"]
        for i, a in enumerate(rects):
            for c in rects[i + 1:]:
                solapan = not (a["x"] + a["width"] <= c["x"] or c["x"] + c["width"] <= a["x"]
                               or a["y"] + a["height"] <= c["y"] or c["y"] + c["height"] <= a["y"])
                self.assertFalse(solapan, f"{a['id']} tapa a {c['id']}")

    def test_la_fuente_guarda_la_referencia_completa_del_bloque(self):
        # Cómo se lee (el nombre del bloque) lo decide la tarjeta: frontend/src/postit.test.ts.
        b, _, v = _board_con_cadena()
        _, p = agent.tool_crear_postit(b, {"text": "Flecha 0.4 mm", "kind": "nota",
                                           "sources": [{"kind": "bloque", "ref": f"bloque:{v}"}]})
        self.assertEqual(p[0]["customData"]["sources"][0]["ref"], f"bloque:{v}")

    def test_tipo_de_post_it_desconocido_se_rechaza(self):
        b, _, _ = _board_con_cadena()
        result, new = agent.tool_crear_postit(b, {"text": "ok", "kind": "orden"})
        self.assertTrue(result["is_error"])
        self.assertEqual(new, [])


@necesita_paquetes
class ProponerCambio(unittest.TestCase):
    """`proponer_cambio` (D75): sobre lo del ingeniero deja una propuesta; nunca lo toca."""

    def test_sobre_lo_del_ingeniero_deja_una_propuesta_y_no_lo_toca(self):
        b, t, _ = _board_con_cadena()
        before = b.state[t]["params"]["L"]
        result, changed, proposed = agent.tool_proponer_cambio(
            b, {"target": t, "change": {"params": {"L": 250}}, "reason": "Más corto"})
        self.assertFalse(result.get("is_error"))
        self.assertEqual((changed, proposed), ([], True))
        self.assertEqual(b.state[t]["params"]["L"], before)
        self.assertEqual(len(reopen(b).proposals_view()), 1)

    def test_mover_o_cambiar_estilo_vuelve_como_error(self):
        b, t, _ = _board_con_cadena()
        result, _, proposed = agent.tool_proponer_cambio(
            b, {"target": t, "change": {"x": 10}, "reason": "Mejor aquí"})
        self.assertTrue(result["is_error"])
        self.assertFalse(proposed)


def _big_outputs(b, bid, n=400):
    """Muchos campos, como el Diseño de detalle del brazo (unos 250, 56 000 caracteres)."""
    fields = {f"campo_{i}": {"value": i * 1.25, "unit": "mm", "label": f"Una cota de prueba {i}",
                             "source": f"bloque:{bid}"} for i in range(n)}
    fields["tabla"] = {"value": [{"fila": i, "texto": "x" * 40} for i in range(30)],
                       "unit": "", "label": "Una lista", "source": f"bloque:{bid}"}
    b.state[bid]["outputs"] = {"detalle": fields}
    return fields


def _data(result):
    return json.loads(result["content"][0]["text"])


@necesita_paquetes
class LoQueLeeElAgenteCabe(unittest.TestCase):
    """Prueba de punta a punta de FF 4.8: con el brazo ejecutado, leer_pizarra daba ~100 000
    caracteres y Claude Code no se los pasaba al agente; un tramo de leer_archivo de 60 000,
    tampoco. Ningún resultado de herramienta pasa de `agent.TOOL_CHARS`."""

    def setUp(self):
        self.b, _, self.v = _board_con_cadena()
        self.fields = _big_outputs(self.b, self.v)

    def test_leer_pizarra_cabe_y_dice_cuanto_falta(self):
        r = agent.tool_leer_pizarra(self.b, {})
        self.assertLessEqual(len(r["content"][0]["text"]), agent.TOOL_CHARS)
        port = next(x for x in _data(r)["blocks"] if x["id"] == self.v)["outputs"]["detalle"]
        shown = [k for k in port if k != "…"]
        self.assertTrue(shown)
        self.assertIn(f"{len(self.fields) - len(shown)} campos más", port["…"])

    def test_una_lista_se_resume_con_su_tamano(self):
        b, _, v = _board_con_cadena()
        b.state[v]["outputs"] = {"p": {"tabla": {"value": [1, 2, 3], "unit": "", "label": "T"}}}
        port = next(x for x in _data(agent.tool_leer_pizarra(b, {}))["blocks"] if x["id"] == v)
        self.assertEqual(port["outputs"]["p"]["tabla"], "lista de 3")

    def test_con_muchos_bloques_grandes_aprieta_hasta_caber(self):
        for bid in list(self.b.state):
            _big_outputs(self.b, bid)
        r = agent.tool_leer_pizarra(self.b, {})
        self.assertLessEqual(len(r["content"][0]["text"]), agent.TOOL_CHARS)

    def test_leer_bloque_da_cada_campo_con_su_etiqueta_por_tramos_sin_perder_ninguno(self):
        seen, start = {}, 0
        while start is not None:
            r = agent.tool_leer_bloque(self.b, {"block": self.v, "port": "detalle", "from": start})
            self.assertNotIn("is_error", r)
            self.assertLessEqual(len(r["content"][0]["text"]), agent.TOOL_CHARS)
            d = _data(r)
            self.assertEqual(d["cite_as"], {"kind": "bloque", "ref": f"bloque:{self.v}"})
            seen.update(d["outputs"]["detalle"])
            start = d.get("next")
        self.assertEqual(list(seen), list(self.fields))
        self.assertEqual(seen["campo_3"], {"value": 3.75, "unit": "mm", "label": "Una cota de prueba 3"})
        self.assertEqual(len(seen["tabla"]["value"]), 30)

    def test_leer_bloque_con_un_bloque_o_una_salida_que_no_existen_da_error(self):
        for args in ({"block": "nada"}, {"block": self.v, "port": "nada"}):
            r = agent.tool_leer_bloque(self.b, args)
            self.assertTrue(r.get("is_error"), args)

    def test_un_tramo_de_leer_archivo_cabe(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        txt = d / "largo.txt"
        txt.write_text("\n".join(f"línea {i} " + "y" * 90 for i in range(3000)), encoding="utf-8")
        card = self.b.add_cards([txt])[0]["id"]
        self.b.probe(True)
        r = agent.tool_leer_archivo(self.b, {"card": card})
        self.assertNotIn("is_error", r)
        self.assertLessEqual(len(r["content"][0]["text"]), agent.TOOL_CHARS)
        self.assertIn("next", _data(r))



# ------------------------------------------------------------ animaciones (D143, D144, D175)
ANIM = "<!doctype html><svg viewBox='0 0 10 10'><circle cx='5' cy='5' r='4'/></svg>"


def _ajustes(auto=None):
    s = Settings(Path(tempfile.mkdtemp()) / "settings.toml", {"schema": 1})
    if auto is not None:
        s.animations_auto = auto
    return s


def _guardada(b, html):
    """¿Está la animación en `board/files/`? Por su nombre, que es su hash."""
    try:
        b.ws.board_file(b.project_id, hashlib.sha256(html.encode()).hexdigest() + ".html")
        return True
    except NotFound:
        return False


class ElAjusteDeAnimaciones(unittest.TestCase):
    def test_por_defecto_activado_y_solo_un_false_lo_apaga(self):
        self.assertTrue(_ajustes().animations_auto)
        s = _ajustes()
        for valor, auto in ((False, False), (True, True), ("no", True), (0, True)):
            s.data["agentes"] = {"animaciones_automaticas": valor, "otra": 1}
            self.assertEqual(s.animations_auto, auto, valor)

    def test_se_guarda_en_disco_sin_perder_lo_desconocido(self):
        s = _ajustes()
        s.data["agentes"] = {"otra": "x"}
        s.animations_auto = False
        s.save()
        again = Settings.load(s.path)
        self.assertEqual((again.animations_auto, again.data["agentes"]["otra"]), (False, "x"))


class ElPromptDeLasAnimaciones(unittest.TestCase):
    def setUp(self):
        self.reg = packs.load([], log=lambda m: None)

    def test_activadas_lleva_el_criterio_y_la_guia(self):
        text = agent.system_prompt(_ajustes(True), self.reg)
        self.assertIn(agent_prompt.ANIMATIONS_ON, text)
        self.assertIn(agent_prompt.ANIMATION_GUIDE, text)

    def test_desactivadas_lleva_la_orden_y_nunca_la_guia(self):
        text = agent.system_prompt(_ajustes(False), self.reg)
        self.assertIn(agent_prompt.ANIMATIONS_OFF, text)
        self.assertNotIn(agent_prompt.ANIMATION_GUIDE, text)
        self.assertNotIn(agent_prompt.ANIMATIONS_ON, text)
        for trozo in ("postMessage", "requestAnimationFrame", "--bp-fg"):
            self.assertNotIn(trozo, text, "ni un trozo de la guía")

    @unittest.skipUnless(SDK, "falta claude_agent_sdk")
    def test_cambiar_el_ajuste_cambia_el_prompt_del_siguiente_mensaje(self):
        async def nada(*a):
            pass
        s = _ajustes()
        a = agent.DesignAgent(new_board(), nada, settings=s)
        primero = a._options()
        s.animations_auto = False
        segundo = a._options()
        self.assertIn(agent_prompt.ANIMATION_GUIDE, primero.system_prompt)
        self.assertNotIn(agent_prompt.ANIMATION_GUIDE, segundo.system_prompt)
        # La guía, desactivadas, solo bajo demanda: con su herramienta
        self.assertNotIn("mcp__pizarra__guia_animacion", primero.allowed_tools)
        self.assertIn("mcp__pizarra__guia_animacion", segundo.allowed_tools)


class AnimacionEnUnPostit(unittest.TestCase):
    def test_se_guarda_en_board_files_y_el_postit_la_nombra(self):
        b = new_board()
        result, new = agent.tool_crear_postit(b, {"text": "Así gira la leva", "kind": "nota",
                                                  "animacion": ANIM})
        self.assertNotIn("is_error", result)
        anim = new[0]["customData"]["animation"]
        self.assertRegex(anim["file"], r"^[0-9a-f]{64}\.html$")
        self.assertEqual(b.ws.board_file(b.project_id, anim["file"]).read_text(encoding="utf-8"),
                         ANIM)
        self.assertEqual(next(e for e in reopen(b).elements if e["id"] == new[0]["id"])
                         ["customData"]["animation"], anim)

    def test_la_misma_dos_veces_se_guarda_una(self):
        b = new_board()
        _, p1 = agent.tool_crear_postit(b, {"text": "uno", "kind": "nota", "animacion": ANIM})
        _, p2 = agent.tool_crear_postit(b, {"text": "dos", "kind": "nota", "animacion": ANIM})
        f1, f2 = (p[0]["customData"]["animation"]["file"] for p in (p1, p2))
        self.assertEqual(f1, f2)
        self.assertEqual(len(list(b.ws.board_file(b.project_id, f1).parent.iterdir())), 1)

    def test_desactivadas_sin_pedirla_se_rechaza_y_no_crea_nada(self):
        b = new_board()
        n = len(b.elements)
        result, new = agent.tool_crear_postit(b, {"text": "La leva", "kind": "nota",
                                                  "animacion": ANIM}, auto_animations=False)
        self.assertTrue(result["is_error"])
        self.assertIn("desactivado", result["content"][0]["text"])
        self.assertEqual((new, len(b.elements), _guardada(b, ANIM)), ([], n, False))

    def test_desactivadas_y_pedida_se_crea_igual(self):
        b = new_board()
        result, new = agent.tool_crear_postit(b, {"text": "La leva", "kind": "nota",
                                                  "animacion": ANIM, "pedida_por_usuario": True},
                                              auto_animations=False)
        self.assertNotIn("is_error", result)
        self.assertTrue(_guardada(b, ANIM))
        self.assertIn("animation", new[0]["customData"])

    def test_desactivadas_un_postit_sin_animacion_se_crea_como_siempre(self):
        b = new_board()
        result, new = agent.tool_crear_postit(b, {"text": "ojo", "kind": "nota"},
                                              auto_animations=False)
        self.assertNotIn("is_error", result)
        self.assertNotIn("animation", new[0]["customData"])

    def test_nunca_hace_de_fuente_de_una_cifra(self):
        b = new_board()
        n = len(b.elements)
        result, new = agent.tool_crear_postit(b, {"text": "Gira a 30 rpm", "kind": "nota",
                                                  "animacion": ANIM})
        self.assertTrue(result["is_error"])
        self.assertIn("fuente", result["content"][0]["text"])
        self.assertEqual((new, len(b.elements), _guardada(b, ANIM)), ([], n, False))
        result, _ = agent.tool_crear_postit(b, {"text": "Gira a 30 rpm", "kind": "nota",
                                                "animacion": ANIM,
                                                "sources": [{"kind": "animacion"}]})
        self.assertTrue(result["is_error"], "la animación no es un tipo de fuente")

    def test_una_que_pasa_del_tope_se_rechaza_sin_crear_nada(self):
        b = new_board()
        n = len(b.elements)
        grande = "<!doctype html>" + "x" * (256 * 1024)
        result, new = agent.tool_crear_postit(b, {"text": "La leva", "kind": "nota",
                                                  "animacion": grande})
        self.assertTrue(result["is_error"])
        self.assertIn("256 KB", result["content"][0]["text"])
        self.assertEqual((new, len(b.elements), _guardada(b, grande)), ([], n, False))
        justa = "x" * (256 * 1024)
        self.assertNotIn("is_error", agent.tool_crear_postit(
            b, {"text": "La leva", "kind": "nota", "animacion": justa})[0])

    def test_el_postit_deja_sitio_para_la_animacion(self):
        b = new_board()
        _, con = agent.tool_crear_postit(b, {"text": "uno", "kind": "nota", "animacion": ANIM})
        _, sin = agent.tool_crear_postit(b, {"text": "uno", "kind": "nota"})
        self.assertEqual(con[0]["height"], sin[0]["height"] + scene.ANIMATION_SIZE[1])
        a, c = con[0], sin[0]
        self.assertTrue(a["x"] + a["width"] <= c["x"] or c["x"] + c["width"] <= a["x"]
                        or a["y"] + a["height"] <= c["y"] or c["y"] + c["height"] <= a["y"],
                        "el de después no tapa la animación")


# --------------------------------------------------------------- agent.md (D172)
class ElAgentMdDeLosPaquetes(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _load(self):
        return packs.load([self.root], log=lambda m: None)

    def test_el_de_un_paquete_cargado_entra_y_el_de_uno_que_no_cargo_nunca(self):
        bien = write(self.root, "bien")
        (bien / "agent.md").write_text("Monta la cadena con bien.b", encoding="utf-8")
        roto = write(self.root, "roto", body="import os\nraise ValueError('no')\n")
        (roto / "agent.md").write_text("Instrucciones del roto", encoding="utf-8")
        reg = self._load()
        self.assertIsNotNone(next(p for p in reg.packs if p.id == "roto").error)
        text = agent.system_prompt(_ajustes(), reg)
        self.assertIn("Monta la cadena con bien.b", text)
        self.assertNotIn("Instrucciones del roto", text)

    def test_sin_agent_md_no_entra_nada_del_paquete(self):
        write(self.root, "solo")
        text = agent.system_prompt(_ajustes(), self._load())
        self.assertEqual(text, agent.system_prompt(_ajustes(), packs.load([], log=lambda m: None)))

    def test_uno_largo_se_corta_en_su_tope_y_queda_en_el_registro(self):
        d = write(self.root, "largo")
        texto = "a" * agent_prompt.AGENT_MD_CHARS + "FINAL"
        (d / "agent.md").write_text(texto, encoding="utf-8")
        with self.assertLogs("pizarra.agent_prompt", logging.WARNING) as logs:
            text = agent.system_prompt(_ajustes(), self._load())
        self.assertIn("a" * agent_prompt.AGENT_MD_CHARS, text)
        self.assertNotIn("FINAL", text)
        self.assertIn("largo", logs.output[0])

    @necesita_paquetes
    def test_los_de_robotica_y_terminales_caben_en_su_tope(self):
        repo = Path(__file__).resolve().parents[3] / "packs"
        for pid in ("robotica", "terminales"):
            text = (repo / pid / "agent.md").read_text(encoding="utf-8")
            self.assertLessEqual(len(text.strip()), agent_prompt.AGENT_MD_CHARS, pid)


# ------------------------------------------------------- papeles propuestos (D177)
PREVIEW_BODY = """
import time
from boardprint_sdk.packs import Param

def run(p, i, c):
    return {"out": {"x": {"value": len(p["arbol"]), "unit": ""}}}

def vista(p, i):
    # como la del Diseño del terminal: el fallo va en el resultado, nunca se lanza
    nodos = p["arbol"]
    res = {"error": None, "modelo": {"error": None}, "errores": {}}
    if any(n.get("ruta") == "no-existe" for n in nodos):
        res["modelo"]["error"] = "la ruta no-existe no está en el modelo"
    for n in nodos:
        if n.get("roto"):
            res["errores"][n["id"]] = "no se puede montar"
    return res

def lenta(p, i):
    time.sleep(p["espera"])
    return {"error": None}

def register(pack):
    pack.port("pv.t", "t")
    pack.block("pv.arbol", "Árbol", run, params={"arbol": Param([], "", "Árbol")},
               outputs={"out": "pv.t"}, preview=vista)
    pack.block("pv.lento", "Lento", run, params={"arbol": Param([], ""), "espera": Param(0.0, "s")},
               outputs={"out": "pv.t"}, preview=lenta)
    pack.block("pv.sin", "Sin vista", run, params={"arbol": Param([], "")}, outputs={"out": "pv.t"})
"""


class PapelesPropuestos(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        write(root, "pv", body=PREVIEW_BODY)
        reg = packs.load([root], log=lambda m: None)
        self.assertIsNone(next(p for p in reg.packs if p.id == "pv").error)
        base = new_board()
        self.b = Board(base.ws, base.project_id, registry=reg, connectors=frozenset())
        self.ids = {}
        for i, kind in enumerate(("pv.arbol", "pv.lento", "pv.sin")):
            el = scene.block_element(kind, i * 400, 0)
            self.b.apply_client_elements([el])
            self.ids[kind] = el["id"]

    def proponer(self, kind, arbol, seconds=agent.PREVIEW_SECONDS, **params):
        args = {"target": self.ids[kind], "change": {"params": {"arbol": arbol, **params}},
                "reason": "Papeles del .f3d"}
        return asyncio.run(agent.tool_proponer_cambio_validado(self.b, args, seconds))

    def test_un_arbol_que_la_vista_previa_rechaza_vuelve_con_el_motivo_y_no_deja_propuesta(self):
        for arbol, motivo in (([{"id": "a", "ruta": "no-existe"}], "la ruta no-existe"),
                              ([{"id": "a"}, {"id": "b", "roto": True}], "b: no se puede montar")):
            result, _, proposed = self.proponer("pv.arbol", arbol)
            self.assertTrue(result["is_error"], arbol)
            self.assertIn(motivo, result["content"][0]["text"])
            self.assertFalse(proposed)
            self.assertEqual(reopen(self.b).proposals_view(), [])

    def test_un_arbol_que_la_vista_previa_da_por_bueno_queda_propuesto(self):
        result, _, proposed = self.proponer("pv.arbol", [{"id": "a", "ruta": "brida:1"}])
        self.assertNotIn("is_error", result)
        self.assertTrue(proposed)
        self.assertEqual(len(reopen(self.b).proposals_view()), 1)

    def test_un_bloque_sin_vista_previa_se_propone_como_siempre(self):
        result, _, proposed = self.proponer("pv.sin", [{"id": "a", "ruta": "no-existe"}])
        self.assertNotIn("is_error", result)
        self.assertTrue(proposed)

    def test_si_la_vista_previa_tarda_se_guarda_con_una_nota(self):
        result, _, proposed = self.proponer("pv.lento", [], seconds=0.2, espera=1.0)
        self.assertNotIn("is_error", result)
        self.assertTrue(proposed)
        self.assertIn("sin validar", _data(result)["vista_previa"])

    def test_lo_que_no_son_parametros_no_pasa_por_la_vista_previa(self):
        job = mock.Mock(side_effect=AssertionError("no tenía que llamarse"))
        with mock.patch.object(Board, "preview_job", job):
            result, _, _ = asyncio.run(agent.tool_proponer_cambio_validado(
                self.b, {"target": self.ids["pv.arbol"], "change": {"delete": True},
                         "reason": "Sobra"}))
        self.assertNotIn("is_error", result)
        job.assert_not_called()

    def test_los_fallos_de_una_vista_previa_se_leen_a_cualquier_profundidad(self):
        self.assertEqual(agent.preview_errors(
            {"error": None, "aviso": "no es un fallo", "modelo": {"error": "ruta"},
             "errores": {"n1": "roto", "n2": ""}, "errores_estados": {"0": "mal"},
             "nodos": {"a": {"error": "hondo"}}}),
            ["ruta", "n1: roto", "0: mal", "hondo"])
        self.assertEqual(agent.preview_errors({"error": "", "errores": {}}), [])


if __name__ == "__main__":
    unittest.main()


class LoQueElAgenteNoSabia(unittest.TestCase):
    """Prueba de punta a punta de FF 4.6: el agente dijo que Fusion estaba cerrado (estaba
    abierto) y dio por pendiente una propuesta ya aceptada. leer_pizarra dice qué conectores
    hay ahora y cómo acabaron sus propuestas."""

    @necesita_paquetes
    def test_leer_pizarra_dice_que_conectores_hay_ahora(self):
        b, _, _ = _board_con_cadena()
        b._connectors = frozenset({"fusion"})
        data = _data(agent.tool_leer_pizarra(b, {}))
        self.assertEqual(data["connectors"]["fusion"], "disponible")
        b._connectors = frozenset()
        data = _data(agent.tool_leer_pizarra(b, {}))
        self.assertEqual(data["connectors"]["fusion"], "no disponible")

    @necesita_paquetes
    def test_leer_pizarra_da_el_estado_de_las_propuestas_del_agente(self):
        b, t, _ = _board_con_cadena()
        ids = []
        for largo, decide in ((250, "aceptar"), (260, "rechazar"), (270, None)):
            result, _, _ = agent.tool_proponer_cambio(
                b, {"target": t, "change": {"params": {"L": largo}}, "reason": "Más corto"})
            ids.append(_data(result)["propuesta"])
            if decide == "aceptar":
                b.accept_proposal(ids[-1], b.proposals_view()[0]["current"])
            elif decide == "rechazar":
                b.reject_proposal(ids[-1])
        data = _data(agent.tool_leer_pizarra(b, {}))
        estados = {p["id"]: p["state"] for p in data["my_proposals"]}
        self.assertEqual([estados[i] for i in ids], ["aceptada", "rechazada", "pendiente"])

    def test_el_prompt_pide_calculo_para_lo_derivado_y_castellano(self):
        ajustes = _ajustes()
        ajustes.language = "es"
        text = agent.system_prompt(ajustes, packs.load([], log=lambda m: None))
        self.assertIn(agent_prompt.RULES, text)
        for trozo in ("calculo", "castellano", "pulse Ejecutar"):
            self.assertIn(trozo, text)      # el idioma va aparte, del ajuste (D180)
        # en inglés, una sola orden de idioma: la base no fija ninguno (O11)
        ajustes.language = "en"
        text = agent.system_prompt(ajustes, packs.load([], log=lambda m: None))
        self.assertIn("Always answer in English", text)
        self.assertNotIn("castellano", text)
        self.assertNotIn("Responde siempre en", text)
