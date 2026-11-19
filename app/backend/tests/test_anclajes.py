"""Anclajes (docs/PLAN_PIZARRA.md §3, D74): un anclaje a sí mismo, a algo que no existe o que
cierre un ciclo se rechaza; borrar el elemento anclado nunca borra el post-it.

Lo de seguir al elemento lo hace la interfaz (frontend/src/anchors.test.ts).
Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import unittest

from pizarra import scene, validation
from tests.helpers import new_board, reopen

AGENT = "agent:design"


def current(board, eid):
    return next(e for e in board.elements if e["id"] == eid)


def anchored(el, anchor, up=1):
    return {**el, "version": el["version"] + up, "customData": {**el["customData"], "anchor": anchor}}


class AnclajeDesdeElCliente(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.tubo = scene.block_element("demo.tubo", 0, 0)
        self.b.apply_client_elements([self.tubo])
        self.p1 = self.b.user_add_postit("nota", 0, 300)
        self.p2 = self.b.user_add_postit("nota", 300, 300)

    def anchor_of(self, eid):
        return current(self.b, eid)["customData"]["anchor"]

    def test_anclar_a_un_elemento_que_existe_se_guarda(self):
        _, rewritten = self.b.apply_client_elements([anchored(self.p1, self.tubo["id"])])
        self.assertEqual(self.anchor_of(self.p1["id"]), self.tubo["id"])
        self.assertEqual(rewritten, [])

    def test_a_si_mismo_a_algo_que_no_existe_o_en_ciclo_se_rechaza(self):
        for bad in (self.p1["id"], "no-existe"):
            _, rewritten = self.b.apply_client_elements([anchored(current(self.b, self.p1["id"]), bad)])
            self.assertIsNone(self.anchor_of(self.p1["id"]))
            self.assertEqual(len(rewritten), 1)
        self.b.apply_client_elements([anchored(self.p2, self.p1["id"])])
        self.b.apply_client_elements([anchored(current(self.b, self.p1["id"]), self.p2["id"])])
        self.assertIsNone(self.anchor_of(self.p1["id"]))

    def test_un_anclaje_rechazado_vuelve_al_que_tenia(self):
        self.b.apply_client_elements([anchored(self.p1, self.tubo["id"])])
        self.b.apply_client_elements([anchored(current(self.b, self.p1["id"]), "no-existe")])
        self.assertEqual(self.anchor_of(self.p1["id"]), self.tubo["id"])

    def test_desanclar_siempre_se_puede(self):
        self.b.apply_client_elements([anchored(self.p1, self.tubo["id"])])
        self.b.apply_client_elements([anchored(current(self.b, self.p1["id"]), None)])
        self.assertIsNone(self.anchor_of(self.p1["id"]))

    def test_borrar_el_elemento_anclado_nunca_borra_el_post_it_y_conserva_el_id(self):
        self.b.apply_client_elements([anchored(self.p1, self.tubo["id"])])
        self.b.apply_client_elements([{**self.tubo, "isDeleted": True, "version": 9}])
        p = current(self.b, self.p1["id"])
        self.assertFalse(p.get("isDeleted"))
        self.assertEqual(p["customData"]["anchor"], self.tubo["id"])
        # Moverlo con el ancla «sin anclaje» no la pierde (no es un anclaje nuevo).
        self.b.apply_client_elements([{**p, "x": 50, "version": p["version"] + 1}])
        self.assertEqual(self.anchor_of(self.p1["id"]), self.tubo["id"])
        self.b.save()
        self.assertEqual(current(reopen(self.b), self.p1["id"])["customData"]["anchor"], self.tubo["id"])


class AnclajeDelAgente(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.tubo = scene.block_element("demo.tubo", 0, 0)
        self.b.apply_client_elements([self.tubo])

    def test_el_agente_ancla_a_un_elemento_que_existe(self):
        (p,) = self.b.agent_add_postit({"text": "Revisa la unión", "kind": "riesgo",
                                        "author": AGENT, "anchor": self.tubo["id"]})
        self.assertEqual(p["customData"]["anchor"], self.tubo["id"])

    def test_anclar_a_algo_que_no_existe_vuelve_al_agente_como_error(self):
        with self.assertRaises(validation.ValidationError):
            self.b.agent_add_postit({"text": "Revisa la unión", "kind": "riesgo",
                                     "author": AGENT, "anchor": "no-existe"})
        self.assertEqual(len(self.b.elements), 1)


def ink_stroke(x, y):
    """Un trazo de tinta del usuario como lo manda la interfaz (D188)."""
    return scene._base("freedraw", x, y, 60, 20, opacity=0, points=[[0, 0], [30, 20], [60, 0]],
                       customData={"kind": "ink", "ink": {"brush": "rotulador", "size": 4,
                                                          "opacity": 1}, "author": "user"})


class AnclajeDeLaTinta(unittest.TestCase):
    """La tinta se ancla a la tarjeta que marca con las mismas reglas que un post-it (D192)."""

    def setUp(self):
        self.b = new_board()
        self.tubo = scene.block_element("demo.tubo", 0, 0)
        self.p = self.b.user_add_postit("nota", 0, 300)
        self.ink = ink_stroke(20, 20)
        self.b.apply_client_elements([self.tubo, self.ink])

    def anchor_of(self, eid):
        return current(self.b, eid)["customData"].get("anchor")

    def test_un_ink_anclado_a_una_tarjeta_se_acepta(self):
        _, rewritten = self.b.apply_client_elements([anchored(self.ink, self.tubo["id"])])
        self.assertEqual(self.anchor_of(self.ink["id"]), self.tubo["id"])
        self.assertEqual(rewritten, [])
        # también nuevo, ya anclado
        other = anchored(ink_stroke(40, 40), self.tubo["id"], up=0)
        _, rewritten = self.b.apply_client_elements([other])
        self.assertEqual(self.anchor_of(other["id"]), self.tubo["id"])

    def test_a_si_mismo_a_algo_que_no_existe_o_en_ciclo_se_revierte(self):
        for bad in (self.ink["id"], "no-existe"):
            _, rewritten = self.b.apply_client_elements([anchored(current(self.b, self.ink["id"]), bad)])
            self.assertIsNone(self.anchor_of(self.ink["id"]))
            self.assertEqual(len(rewritten), 1)
        self.b.apply_client_elements([anchored(self.p, self.ink["id"])])
        self.b.apply_client_elements([anchored(current(self.b, self.ink["id"]), self.p["id"])])
        self.assertIsNone(self.anchor_of(self.ink["id"]))

    def test_borrar_la_tarjeta_nunca_borra_la_tinta(self):
        self.b.apply_client_elements([anchored(self.ink, self.tubo["id"])])
        self.b.apply_client_elements([{**self.tubo, "isDeleted": True, "version": 9}])
        e = current(self.b, self.ink["id"])
        self.assertFalse(e.get("isDeleted"))
        self.assertEqual(e["customData"]["anchor"], self.tubo["id"])


if __name__ == "__main__":
    unittest.main()
