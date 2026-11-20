"""La unidad de un nombre del Excel sale de su sufijo (docs/PLAN_EXCEL.md §3.1, X4).

Reglas:
- `L_m` = 0,3 en un parámetro en mm da 300: se convierte siempre a la unidad del parámetro.
- Nunca se enlaza sin sufijo un parámetro con unidad, ni un sufijo de otra magnitud
  (`masa_kg` a un parámetro en mm), ni un parámetro con una unidad que la tabla no conoce:
  nunca se adivina.
- Un sufijo desconocido cuenta como sin sufijo.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import math
import unittest

from pizarra import excel_names
from pizarra.excel_names import UnitError, convert, suffix


class Sufijos(unittest.TestCase):
    def test_el_sufijo_es_el_ultimo_trozo_tras_el_guion_bajo(self):
        self.assertEqual(suffix("L_brazo_mm"), "mm")
        self.assertEqual(suffix("masa_kg"), "kg")
        self.assertEqual(suffix("par_Nm"), "Nm")
        self.assertEqual(suffix("Datos!L_m"), "m", "el de una hoja, por su nombre")

    def test_un_sufijo_desconocido_cuenta_como_sin_sufijo(self):
        self.assertEqual(suffix("L_brazo"), "")
        self.assertEqual(suffix("velocidad_rpm"), "")
        self.assertEqual(suffix("masa"), "")
        self.assertEqual(suffix("L_MM"), "", "las unidades distinguen mayúsculas: nunca se adivina")

    def test_la_tabla_tiene_las_magnitudes_del_plan(self):
        for s in ("mm", "cm", "m", "in", "ft", "g", "kg", "lb", "N", "kN", "lbf",
                  "Nm", "Nmm", "kNm", "deg", "rad", "s", "ms"):
            with self.subTest(s):
                self.assertEqual(suffix(f"x_{s}"), s)


class Conversion(unittest.TestCase):
    def test_metros_a_un_parametro_en_mm(self):
        self.assertAlmostEqual(convert(0.3, "m", "mm"), 300)

    def test_da_lo_mismo_que_escrito_a_mano(self):
        # e2e FF 7.2: 1,001 m daba 1000,9999999999999 mm, y el bloque no daba lo mismo que con
        # 1001 escrito a mano (§6 del plan). La conversión no deja el ruido del último bit.
        for v in [i / 1000 for i in range(1, 5000)]:
            with self.subTest(v):
                self.assertEqual(convert(v, "m", "mm"), round(v * 1000))
        self.assertEqual(convert(2.2, "lb", "kg"), 0.997903214)
        self.assertEqual(convert(4.03, "m", "mm"), 4030)

    def test_casos_a_mano(self):
        cases = [(1, "in", "mm", 25.4), (2, "ft", "m", 0.6096), (500, "g", "kg", 0.5),
                 (1, "lb", "kg", 0.45359237), (1.5, "kN", "N", 1500), (1, "kNm", "N·m", 1000),
                 (2000, "Nmm", "Nm", 2), (180, "deg", "rad", math.pi), (math.pi, "rad", "°", 180),
                 (250, "ms", "s", 0.25), (12, "mm", "mm", 12)]
        for v, s, unit, want in cases:
            with self.subTest(f"{v} {s} -> {unit}"):
                self.assertAlmostEqual(convert(v, s, unit), want)

    def test_las_unidades_que_se_eligen_en_pantalla_estan_todas_y_en_su_magnitud(self):
        from pizarra import units
        for magnitude, choices in units.UNITS.items():
            for u in choices:
                with self.subTest(u):
                    self.assertEqual(excel_names.UNITS[u][0], magnitude)
            self.assertEqual(excel_names.UNITS[units.SI[magnitude]][1], 1, "la base es la de SI")

    def test_sin_unidad_en_los_dos_lados_pasa_tal_cual(self):
        self.assertEqual(convert(3, "", ""), 3)
        self.assertEqual(convert("acero", "", ""), "acero", "un texto, a un parámetro de texto")


class LoQueSeNiega(unittest.TestCase):
    """X4: un enlace que daría una unidad equivocada se niega con su motivo."""

    def assertDenied(self, code, *args):
        with self.assertRaises(UnitError) as cm:
            convert(*args)
        self.assertEqual(cm.exception.code, code)

    def test_nunca_sin_sufijo_a_un_parametro_con_unidad(self):
        self.assertDenied("sin_sufijo", 0.3, "", "mm")

    def test_nunca_un_sufijo_de_otra_magnitud(self):
        self.assertDenied("otra_magnitud", 2.0, "kg", "mm")
        self.assertDenied("otra_magnitud", 2.0, "Nm", "N")

    def test_nunca_a_un_parametro_con_una_unidad_que_la_tabla_no_conoce(self):
        self.assertDenied("unidad_desconocida", 2.0, "mm", "MPa")
        self.assertDenied("unidad_desconocida", 2.0, "", "rpm")

    def test_nunca_un_valor_con_unidad_a_un_parametro_sin_unidad(self):
        self.assertDenied("con_sufijo_sin_unidad", 0.3, "m", "")

    def test_un_texto_no_se_convierte_a_una_unidad(self):
        self.assertDenied("no_es_numero", "largo", "m", "mm")
        self.assertDenied("no_es_numero", True, "m", "mm")

    def test_compatible_responde_sin_valor(self):
        self.assertTrue(excel_names.compatible("m", "mm"))
        self.assertFalse(excel_names.compatible("kg", "mm"))
        self.assertFalse(excel_names.compatible("", "mm"))
        self.assertTrue(excel_names.compatible("", ""))


if __name__ == "__main__":
    unittest.main()
