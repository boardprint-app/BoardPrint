"""Regla de los números, decisiones del usuario tras el spike del agente (plan R7, D51-D52).

- Una designación (material, rosca, norma, protección) no es una cifra de diseño: no pide
  fuente. Un número con unidad o suelto, sí.
- Una cuenta del propio agente sobre salidas de bloques se cita como "cálculo del agente",
  con la fórmula a la vista, y se pinta como lo no verificado (borde discontinuo).
"""
import tempfile
import unittest

from pizarra import agent, scene, validation
from tests.helpers import new_board, reopen
from pizarra.validation import ValidationError


def _board_con_cadena():
    b = new_board()
    t, v = scene.block_element("prueba.tubo", 0, 0), scene.block_element("prueba.voladizo", 400, 0)
    b.apply_client_elements([t, v, {"id": "a", "type": "arrow", "version": 1,
                                    "startBinding": {"elementId": t["id"]},
                                    "endBinding": {"elementId": v["id"]}}])
    b.run(v["id"])
    return b, t["id"], v["id"]


class Designaciones(unittest.TestCase):
    def test_las_designaciones_no_cuentan_como_cifras(self):
        for texto in ("Aluminio 6061-T6 soldado", "Tornillos M6 DIN 912", "Motor NEMA 17",
                      "Brida ISO 9409-1-50-4-M6", "Chapa EN AW-6082-T6", "Conector IP67",
                      "Acero S235JR", "Agujero con ajuste H7", "Tornillo M6x20"):
            self.assertFalse(validation.has_figures(texto), texto)

    def test_un_numero_con_unidad_o_suelto_sigue_pidiendo_fuente(self):
        for texto in ("Tubo Ø30 mm", "M6 de 20 mm", "Aluminio 6061", "Flecha de 0,6 mm",
                      "Límite L/500", "Tensión 120MPa", "Factor x2", "Aprovecha el 73 %",
                      "6061-T6 de 2 kg", "Masa ½ kg"):
            self.assertTrue(validation.has_figures(texto), texto)

    def test_post_it_que_solo_cita_el_material_no_necesita_fuente(self):
        p = validation.validate_postit({"text": "El 6061-T6 pierde resistencia al soldarlo",
                                        "kind": "riesgo", "author": "agent:design"})
        self.assertEqual(p["sources"], [])


class CalculoDelAgente(unittest.TestCase):
    def base(self, **kw):
        return {"text": "Flecha admisible L/500 = 1,2 mm", "kind": "nota",
                "author": "agent:design", **kw}

    def test_un_calculo_con_su_formula_vale_como_fuente(self):
        p = validation.validate_postit(self.base(
            sources=[{"kind": "calculo", "formula": "L/500 = 600 mm / 500 = 1,2 mm"}]))
        self.assertEqual(p["sources"][0]["kind"], "calculo")

    def test_un_calculo_sin_formula_se_rechaza(self):
        for src in ({"kind": "calculo"}, {"kind": "calculo", "formula": "  "},
                    {"kind": "calculo", "formula": "L/500", "inputs": "bloque:x"}):
            with self.assertRaises(ValidationError, msg=src):
                validation.validate_postit(self.base(sources=[src]))

    def test_las_entradas_de_un_calculo_tienen_que_ser_bloques_con_resultados(self):
        b, _, _ = _board_con_cadena()
        with self.assertRaises(ValidationError):
            b.agent_add_postit(self.base(sources=[{
                "kind": "calculo", "formula": "L/500", "inputs": ["bloque:noexiste"]}]))

    def test_el_post_it_guarda_la_cuenta_entera(self):
        # Cómo se pinta (no verificado, con la cuenta) lo decide la tarjeta:
        # frontend/src/postit.test.ts.
        b, _, v = _board_con_cadena()
        result, new = agent.tool_crear_postit(b, {
            "text": "Flecha admisible L/500 = 1,2 mm", "kind": "nota",
            "sources": [{"kind": "calculo", "formula": "L/500 = 600 mm / 500 = 1,2 mm",
                         "inputs": [f"bloque:{v}"]}]})
        self.assertNotIn("is_error", result)
        src = new[0]["customData"]["sources"][0]
        self.assertEqual((src["formula"], src["inputs"]),
                         ("L/500 = 600 mm / 500 = 1,2 mm", [f"bloque:{v}"]))

    def test_una_fuente_de_bloque_no_es_una_estimacion(self):
        b, _, v = _board_con_cadena()
        _, new = agent.tool_crear_postit(b, {
            "text": "La flecha es de 0.4 mm", "kind": "nota",
            "sources": [{"kind": "bloque", "ref": f"bloque:{v}"}]})
        self.assertFalse(new[0]["customData"]["estimate"])


if __name__ == "__main__":
    unittest.main()
