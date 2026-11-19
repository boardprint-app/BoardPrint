"""Plantillas de un paquete en la pizarra (plan D91, §10).

Reglas:
- Una plantilla deja sus bloques y sus conexiones, con sus puertos, y el grafo las acepta todas.
- Nunca cae encima de lo que ya hay en la pizarra.
- Una plantilla que no existe es un error, y no deja nada.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import unittest

from pizarra import graph, scene
from pizarra.validation import ValidationError
from tests.helpers import new_board, necesita_paquetes


def overlaps(a, b):
    ax0, ay0, ax1, ay1 = scene.bbox(a)
    bx0, by0, bx1, by1 = scene.bbox(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


class Plantillas(unittest.TestCase):
    def setUp(self):
        self.b = new_board()

    @necesita_paquetes
    def test_deja_bloques_y_conexiones_que_el_grafo_acepta(self):
        t = self.b.registry.templates["robotica.brazo"]
        new = self.b.add_template("robotica.brazo")
        blocks = [e for e in new if e["type"] == "embeddable"]
        arrows = [e for e in new if e["type"] == "arrow"]
        self.assertEqual((len(blocks), len(arrows)), (len(t.blocks), len(t.links)))
        edges, problems = graph.build(self.b.elements, self.b.registry)
        self.assertEqual(problems, [])
        self.assertEqual(sum(len(v) for v in edges.values()), len(t.links))
        for a in arrows:
            self.assertEqual(a["customData"]["kind"], "connection")
            src = next(e for e in blocks if e["id"] == a["startBinding"]["elementId"])
            self.assertIn({"id": a["id"], "type": "arrow"}, src["boundElements"])
        sts = self.b.statuses()
        self.assertEqual({sts[e["id"]] for e in blocks}, {"nunca", "no_disponible"})

    @necesita_paquetes
    def test_nunca_cae_encima_de_lo_que_ya_hay(self):
        tubo = scene.block_element("demo.tubo", 300, 100)
        self.b.apply_client_elements([tubo])
        new = self.b.add_template("robotica.brazo", x=0, y=0)       # pedida encima del tubo
        for e in new:
            if e["type"] == "embeddable":
                self.assertFalse(overlaps(e, tubo), e["customData"]["blockType"])

    @necesita_paquetes
    def test_donde_se_pide_si_cabe(self):
        new = self.b.add_template("demo.cadena", x=500, y=-200)
        self.assertEqual(min(e["x"] for e in new if e["type"] == "embeddable"), 500)

    def test_una_que_no_existe_es_un_error_y_no_deja_nada(self):
        with self.assertRaises(ValidationError):
            self.b.add_template("robotica.no_existe")
        self.assertEqual(self.b.elements, [])


if __name__ == "__main__":
    unittest.main()
