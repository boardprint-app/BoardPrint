"""Controles genéricos `chart` y `view2d` (docs/PLAN_PAQUETES.md §5, P8, P52).

Reglas:
- Lo que dan `chart()` y `view2d()` es un campo de salida con `control`, y un dato roto (un
  número que no es finito, una curva de un punto, un elemento que no es caja, línea ni punto,
  un tono que no existe) es un **ValueError**: el bloque acaba en error con el motivo, nunca
  con un dibujo a medias.
- `pack.view` acepta los dos controles en la tarjeta y en el panel.
- En el `demo`, la gráfica dice lo mismo que los números: la elástica del voladizo **acaba en
  su flecha de punta** y empieza en cero en el empotramiento; la vista previa del panel da lo
  mismo que ejecutarlo.

Ejecutar desde app/backend:  python -m unittest tests.test_controles -v
"""
import math
import tempfile
import unittest
from pathlib import Path

from boardprint_sdk.packs import box, chart, line, point, view2d
from pizarra import scene
from tests.helpers import new_board, necesita_paquetes
from tests.test_pack_ui import load, write


class Grafica(unittest.TestCase):
    def test_un_campo_con_sus_ejes_y_sus_curvas(self):
        f = chart(("Posición", "mm"), ("Flecha", "mm"), {"a": [(0, 0), (1, 2)], "b": [[0, 1], [2, 3]]},
                  label="Elástica")
        self.assertEqual(f["control"], "chart")
        self.assertEqual(f["label"], "Elástica")
        v = f["value"]
        self.assertEqual(v["x"], {"label": "Posición", "unit": "mm"})
        self.assertEqual([c["label"] for c in v["curves"]], ["a", "b"])
        self.assertEqual(v["curves"][0]["points"], [[0, 0], [1, 2]])

    def test_un_eje_solo_con_nombre(self):
        self.assertEqual(chart("t", "n", {"a": [(0, 0), (1, 1)]})["value"]["y"], {"label": "n", "unit": ""})

    def test_datos_rotos(self):
        for curves in ({}, {"a": [(0, 0)]}, {"a": [(0, math.nan), (1, 1)]},
                       {"a": [(0, math.inf), (1, 1)]}, {"a": [(0, "1"), (1, 1)]},
                       {"a": [(0, True), (1, 1)]}, {"a": [(0, 0, 0), (1, 1)]}, {"a": "xy"},
                       [(0, 0), (1, 1)]):
            with self.subTest(curves=curves), self.assertRaises(ValueError):
                chart("x", "y", curves)

    def test_un_eje_que_no_es_nombre_y_unidad(self):
        with self.assertRaises(ValueError):
            chart(("x", "mm", "s"), "y", {"a": [(0, 0), (1, 1)]})


class Vista2D(unittest.TestCase):
    def test_cajas_lineas_y_puntos(self):
        f = view2d(("x", "mm"), ("z", "mm"), [box(10, 5, 0, 0, "A"), line([(0, 0), (1, 1)], tone="accent"),
                                               point(2, 3, "TCP", "warn")], y_down=True)
        self.assertEqual(f["control"], "view2d")
        v = f["value"]
        self.assertTrue(v["y_down"])
        self.assertEqual(v["items"][0], {"box": [0, 0, 10, 5], "label": "A", "tone": ""})
        self.assertEqual(v["items"][2]["point"], [2, 3])

    def test_un_elemento_hecho_a_mano_pasa_la_misma_comprobacion(self):
        self.assertEqual(view2d("x", "y", [{"point": [1, 2]}])["value"]["items"],
                         [{"point": [1, 2], "label": "", "tone": ""}])
        for items in ([], [{"circle": [0, 0, 1]}], [{"box": [0, 0, 1]}], [{"point": [0, math.nan]}],
                      [{"box": [0, 0, 1, 1], "point": [0, 0]}], [{"line": [(0, 0)]}], ["caja"],
                      [{"point": [0, 0], "tone": "rojo"}]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                view2d("x", "y", items)

    def test_un_tono_que_no_existe(self):
        with self.assertRaises(ValueError):
            point(0, 0, tone="rojo")


class Declaracion(unittest.TestCase):
    def test_pack_view_acepta_la_grafica_y_la_vista_2d(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp), "gen", 'pack.view("gen.b", card=["params", "chart"], panel=["view2d", "results"])')
            reg, info = load(Path(tmp))
            self.assertIsNone(info["gen"].error)
            self.assertEqual(reg.describe()["blocks"]["gen.b"]["view"],
                             {"card": ["params", "chart"], "panel": ["view2d", "results"]})


@necesita_paquetes
class Demo(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        t, v = scene.block_element("demo.tubo", 0, 0), scene.block_element("demo.voladizo", 400, 0)
        self.b.apply_client_elements([t, v, {"id": "a", "type": "arrow", "version": 1,
                                              "startBinding": {"elementId": t["id"]},
                                              "endBinding": {"elementId": v["id"]}}])
        self.t, self.v = t["id"], v["id"]
        self.b.run(self.v)

    def test_la_elastica_acaba_en_la_flecha_de_la_punta(self):
        out = self.b.state[self.v]["outputs"]["voladizo"]
        (curva,) = out["elastica"]["value"]["curves"]
        x0, y0 = curva["points"][0]
        xL, yL = curva["points"][-1]
        self.assertEqual((x0, y0), (0, 0))
        L = self.b.state[self.t]["outputs"]["tubo"]["L"]["value"]
        self.assertAlmostEqual(xL, L)
        self.assertAlmostEqual(yL, out["flecha"]["value"], places=3)

    def test_la_vista_lateral_del_tubo_mide_lo_que_sus_parametros(self):
        tubo = self.b.state[self.t]["outputs"]["tubo"]
        ext, hueco = tubo["vista"]["value"]["items"]
        od, t, L = (tubo[k]["value"] for k in ("od", "t", "L"))
        self.assertEqual(ext["box"], [0, -od / 2, L, od / 2])
        self.assertAlmostEqual(ext["box"][3] - hueco["box"][3], t)

    def test_la_vista_previa_da_lo_que_daria_ejecutarlo(self):
        pv = self.b.preview(self.v, {"F": 400})
        self.b.set_params(self.v, {"F": 400})
        self.b.run(self.v)
        out = self.b.state[self.v]["outputs"]["voladizo"]
        self.assertEqual(pv["voladizo"]["elastica"]["value"], out["elastica"]["value"])
        self.assertEqual(pv["voladizo"]["flecha"]["value"], out["flecha"]["value"])


if __name__ == "__main__":
    unittest.main()
