"""Flechas y líneas que Excalidraw no puede pintar (OP 4.1, docs/PLAN_PAQUETES.md P88).

Regla: una flecha o línea sin `points` válidos (escrita por un script, la API o el agente)
**nunca deja la pizarra en blanco**: al abrir el proyecto y al recibirla sale con dos puntos;
una conexión enganchada a dos bloques se rehace entre ellos, con sus puertos y su enganche
intactos, y una flecha buena **no se toca**.

Ejecutar desde app/backend:  python -m unittest tests.test_flechas -v
"""
import unittest

from pizarra import scene


def block(bid, x, y):
    return {"id": bid, "type": "embeddable", "x": x, "y": y, "width": 300, "height": 200,
            "customData": {"kind": "block", "blockType": "prueba.tubo"}, "version": 1}


def arrow(aid, **kw):
    return {"id": aid, "type": "arrow", "version": 3, **kw}


class Reparar(unittest.TestCase):
    def setUp(self):
        self.a, self.b = block("a", 0, 0), block("b", 600, 100)

    def test_una_conexion_sin_puntos_se_rehace_entre_sus_bloques(self):
        conn = arrow("c", startBinding={"elementId": "a"}, endBinding={"elementId": "b"},
                     customData={"kind": "connection", "from": "tubo", "to": "tubo"})
        out, changed = scene.repair_lines([self.a, self.b, conn])
        self.assertTrue(changed)
        c = out[2]
        self.assertEqual((c["x"], c["y"]), (305, 18))
        self.assertEqual(c["points"], [[0, 0], [290, 100]])
        self.assertEqual(c["customData"], conn["customData"])
        self.assertEqual(c["startBinding"], conn["startBinding"])
        self.assertGreater(c["version"], conn["version"])

    def test_sin_bloques_una_recta_con_su_ancho(self):
        for bad in (None, [], [[0, 0]], [[0, "x"], [1, 1]], "nada", [[0, 0], [float("nan"), 0]]):
            with self.subTest(bad=bad):
                e = arrow("d", x=10, y=20, width=50, height=5, points=bad)
                (fixed,), changed = scene.repair_lines([e])
                self.assertTrue(changed)
                self.assertEqual((fixed["x"], fixed["y"], fixed["points"]), (10, 20, [[0, 0], [50, 5]]))

    def test_sin_x_ni_y_tambien(self):
        (fixed,), _ = scene.repair_lines([{"id": "l", "type": "line", "points": [[0, 0], [5, 5]]}])
        self.assertEqual((fixed["x"], fixed["y"]), (0, 0))
        self.assertEqual(len(fixed["points"]), 2)

    def test_una_buena_no_se_toca(self):
        good = arrow("g", x=1, y=2, width=3, height=4, points=[[0, 0], [3, 4], [5, 5]])
        out, changed = scene.repair_lines([good, self.a])
        self.assertFalse(changed)
        self.assertIs(out[0], good)
        deleted = arrow("x", isDeleted=True)
        self.assertIsNone(scene.repair_line(deleted, {}))


if __name__ == "__main__":
    unittest.main()
