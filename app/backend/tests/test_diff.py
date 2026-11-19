"""Diff de escenas (docs/PLAN_PIZARRA.md §3, D76): lo que da *Comparar* entre versiones.

Dos escenas iguales dan un diff vacío; un borrado (`isDeleted`) cuenta como quitado; mover o
redimensionar nunca sale como cambio de contenido; un cambio de parámetros se ve con el valor
de antes y el de después.
Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import copy
import unittest

from pizarra import diff, scene


def postit(pid, text="Hola", kind="nota", state="abierto", **kw):
    return {"id": pid, "type": "embeddable", "x": 0, "y": 0, "width": 260, "height": 120,
            "version": 1, "customData": {"kind": "postit", "postitKind": kind, "state": state,
                                         "text": text, "author": "user"}, **kw}


def changes(d, kind):
    return [c for c in d if c["change"] == kind]


class Diff(unittest.TestCase):
    def setUp(self):
        self.tubo = scene.block_element("demo.tubo", 0, 0)
        self.p = postit("p1")
        self.txt = {"id": "t1", "type": "text", "x": 0, "y": 300, "width": 100, "height": 20,
                    "version": 1, "text": "Montaje"}
        self.scene = [self.tubo, self.p, self.txt]
        self.state = {self.tubo["id"]: {"params": {"L": 300, "od": 40}, "outputs": {"m": 1}}}

    def test_dos_escenas_iguales_dan_un_diff_vacio(self):
        self.assertEqual(diff.diff(self.scene, copy.deepcopy(self.scene), self.state,
                                   copy.deepcopy(self.state)), [])

    def test_anadido_y_quitado_con_un_borrado_como_quitado(self):
        after = [self.tubo, {**self.p, "isDeleted": True, "version": 2}, self.txt, postit("p2", "Nueva")]
        d = diff.diff(self.scene, after, self.state, self.state)
        self.assertEqual([c["id"] for c in changes(d, "added")], ["p2"])
        self.assertEqual([c["id"] for c in changes(d, "removed")], ["p1"])
        removed = changes(d, "removed")[0]
        self.assertEqual((removed["element"]["kind"], removed["element"]["text"]), ("postit", "Hola"))
        self.assertEqual(removed["element"]["width"], 260)

    def test_mover_o_redimensionar_nunca_es_cambio_de_contenido(self):
        after = [{**self.tubo, "x": 90, "version": 5}, {**self.p, "width": 300, "version": 3}, self.txt]
        d = diff.diff(self.scene, after, self.state, self.state)
        self.assertEqual(changes(d, "modified"), [])
        minor = {c["id"]: (c["moved"], c["resized"]) for c in changes(d, "minor")}
        self.assertEqual(minor, {self.tubo["id"]: (True, False), "p1": (False, True)})

    def test_parametros_con_el_valor_de_antes_y_el_de_despues(self):
        after_state = {self.tubo["id"]: {"params": {"L": 250, "od": 40}, "outputs": {"m": 2}}}
        d = diff.diff(self.scene, self.scene, self.state, after_state)
        (c,) = changes(d, "modified")
        self.assertEqual(c["fields"], {"params": {"L": [300, 250]}})

    def test_texto_tipo_y_estado_de_un_post_it_y_texto_suelto(self):
        p2 = {**self.p, "customData": {**self.p["customData"], "text": "Adiós", "postitKind": "riesgo",
                                       "state": "aceptado"}}
        after = [self.tubo, p2, {**self.txt, "text": "Montaje M6"}]
        d = {c["id"]: c["fields"] for c in changes(diff.diff(self.scene, after, self.state, self.state), "modified")}
        self.assertEqual(d["p1"], {"text": ["Hola", "Adiós"], "postitKind": ["nota", "riesgo"],
                                   "state": ["abierto", "aceptado"]})
        self.assertEqual(d["t1"], {"text": ["Montaje", "Montaje M6"]})

    def test_moverse_y_cambiar_sale_como_modificado_que_ademas_se_movio(self):
        p2 = {**self.p, "x": 50, "customData": {**self.p["customData"], "text": "Otro"}}
        (c,) = diff.diff([self.p], [p2], {}, {})
        self.assertEqual((c["change"], c["moved"]), ("modified", True))

    def test_el_texto_dentro_de_una_forma_no_sale_suelto(self):
        bound = {"id": "b1", "type": "text", "containerId": "r1", "x": 0, "y": 0, "width": 1,
                 "height": 1, "version": 1, "text": "x"}
        self.assertEqual(diff.diff([], [bound], {}, {}), [])


if __name__ == "__main__":
    unittest.main()
