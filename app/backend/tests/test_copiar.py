"""Copiar y pegar un bloque (docs/PLAN_PIZARRA.md §3, D85): la copia lleva sus parámetros.

La interfaz pone los parámetros del bloque en `customData.params` del elemento que va al
portapapeles; al pegarlo (en la misma pizarra o en otro proyecto) llega con un id nuevo y el
enlace del original. Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import copy
import unittest

from pizarra import scene
from pizarra.blocks import default_params
from tests.helpers import new_board, reopen, necesita_paquetes


def pasted(original, new_id="pegado01", params=None):
    """El elemento tal como lo pega Excalidraw: id nuevo, enlace y customData del original."""
    cd = dict(original["customData"])
    if params is not None:
        cd["params"] = params
    return {**copy.deepcopy(original), "id": new_id, "customData": cd, "version": 1,
            "index": None, "x": original["x"] + 50}


@necesita_paquetes
class PegarBloque(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.tubo = scene.block_element("demo.tubo", 0, 0)
        self.b.apply_client_elements([self.tubo])
        self.b.set_params(self.tubo["id"], {"L": 450, "od": 50})

    def test_la_copia_nace_con_los_parametros_que_lleva(self):
        params = dict(self.b.state[self.tubo["id"]]["params"])
        self.b.apply_client_elements([pasted(self.tubo, params=params)])
        self.assertEqual(self.b.state["pegado01"]["params"], params)

    def test_la_copia_no_hereda_salidas_ni_estado_del_original(self):
        self.b.run(self.tubo["id"])
        self.b.apply_client_elements([pasted(self.tubo, params={"L": 450})])
        self.assertEqual(set(self.b.state["pegado01"]), {"params"})
        self.assertEqual(self.b.statuses()["pegado01"], "nunca")

    def test_la_copia_nunca_se_lleva_los_archivos_del_original(self):
        bid = self.tubo["id"]
        d = self.b.ws.block_scratch(self.b.project_id, bid)       # como si lo hubiera escrito
        (d / "informe.html").write_text("<p>", encoding="utf-8")  # una ejecución (D93)
        self.b.ws.commit_block_files(self.b.project_id, bid, d)
        self.b.apply_client_elements([pasted(self.tubo, params={"L": 450})])
        self.assertFalse((self.b.dir / "blocks" / "pegado01").exists())

    def test_parametros_que_el_tipo_no_tiene_se_ignoran_y_los_que_faltan_van_por_defecto(self):
        self.b.apply_client_elements([pasted(self.tubo, params={"L": 999, "inventado": 1})])
        p = self.b.state["pegado01"]["params"]
        self.assertEqual(p["L"], 999)
        self.assertNotIn("inventado", p)
        self.assertEqual(p["od"], default_params("demo.tubo")["od"])
        self.assertEqual(set(p), set(self.b.registry["demo.tubo"].params))

    def test_los_parametros_no_se_quedan_en_la_escena_y_el_enlace_es_el_suyo(self):
        _, rewritten = self.b.apply_client_elements([pasted(self.tubo, params={"L": 1})])
        el = next(e for e in self.b.elements if e["id"] == "pegado01")
        self.assertNotIn("params", el["customData"])
        self.assertEqual(el["link"], "https://pizarra.local/block/pegado01")
        self.assertGreater(el["version"], 1)
        self.assertEqual([e["id"] for e in rewritten], ["pegado01"])
        self.b.save()
        self.assertNotIn("params", reopen(self.b).elements[-1]["customData"])

    def test_unos_parametros_en_un_bloque_que_ya_existe_nunca_pisan_los_suyos(self):
        mine = dict(self.b.state[self.tubo["id"]]["params"])
        again = {**self.tubo, "version": 5,
                 "customData": {**self.tubo["customData"], "params": {"L": 1}}}
        self.b.apply_client_elements([again])
        self.assertEqual(self.b.state[self.tubo["id"]]["params"], mine)
        self.assertNotIn("params", self.b.elements[0]["customData"])

    def test_pegar_en_otro_proyecto_lleva_los_parametros(self):
        other = new_board("Otro")
        other.apply_client_elements([pasted(self.tubo, params={"L": 450, "od": 50})])
        self.assertEqual(other.state["pegado01"]["params"]["L"], 450)

    def test_un_envio_normal_no_reescribe_nada(self):
        moved = {**self.tubo, "x": 300, "version": 5}
        won, rewritten = self.b.apply_client_elements([moved])
        self.assertEqual(rewritten, [])
        self.assertEqual(won, [moved])

    def test_un_post_it_pegado_corrige_su_enlace(self):
        p = scene.postit_element({"text": "hola", "kind": "nota", "state": "abierto",
                                  "author": "user", "sources": [], "estimate": False,
                                  "anchor": None}, 0, 0)
        self.b.apply_client_elements([p])
        _, rewritten = self.b.apply_client_elements([pasted(p, new_id="copia02")])
        self.assertEqual(rewritten[0]["link"], scene.POSTIT_LINK + "copia02")
        self.assertEqual(rewritten[0]["customData"]["text"], "hola")


if __name__ == "__main__":
    unittest.main()
