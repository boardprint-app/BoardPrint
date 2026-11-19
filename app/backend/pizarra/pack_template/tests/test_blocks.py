"""Tests del paquete: prueban la regla del cálculo, no el código (guía, «Tests»).

Se ejecutan en el entorno de paquetes con `validar_paquete`: cargan el paquete con
`pizarra.packs` (y los paquetes que pida, de `BOARDPRINT_TEST_PACKS`) y llaman a sus bloques.
"""
import os
import unittest
from pathlib import Path

from pizarra import packs

ROOT = Path(__file__).resolve().parents[2]
EXTRA = [d for d in os.environ.get("BOARDPRINT_TEST_PACKS", "").split(os.pathsep) if d]
REG = packs.load([str(ROOT), *EXTRA], log=lambda m: None)


def run(kind, **params):
    return REG[kind].run({**REG.default_params(kind), **params}, {}, packs.RunContext(block_id="t"))


class Ejemplo(unittest.TestCase):
    def test_el_area_es_ancho_por_alto(self):
        got = run("{id}.ejemplo", ancho=4.0, alto=2.5)
        self.assertAlmostEqual(got["resultado"]["area"]["value"], 10.0)


if __name__ == "__main__":
    unittest.main()
