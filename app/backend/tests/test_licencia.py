"""La licencia del repo es Apache-2.0 en todas partes (PLAN_PUBLICACION.md O1, §6).

Regla: ningún manifiesto versionado del producto (shell, frontend, paquetes oficiales de
`packs/`) dice otra licencia que `Apache-2.0`, aunque se añada un paquete nuevo, y no queda
rastro de la BSL 1.1 de D160 fuera de los planes que cuentan su historia. La plantilla de
paquete y los paquetes de prueba no entran: un paquete de otro elige su licencia.
"""

import json
import os
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SPDX = "Apache-2.0"


class LicenciaTest(unittest.TestCase):
    def test_license_es_apache(self):
        texto = (REPO / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", texto)
        self.assertIn("Version 2.0, January 2004", texto)
        self.assertNotIn("Business Source", texto)

    def test_notice_con_el_autor(self):
        texto = (REPO / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("BoardPrint", texto)
        self.assertIn("Bernat Suarez i Domenech", texto)

    def test_cargo(self):
        cargo = tomllib.loads((REPO / "app/shell/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
        self.assertEqual(cargo["package"]["license"], SPDX)

    def test_package_json(self):
        for rel in ("app/shell/package.json", "app/frontend/package.json"):
            with self.subTest(rel):
                data = json.loads((REPO / rel).read_text(encoding="utf-8"))
                self.assertEqual(data.get("license"), SPDX)

    @unittest.skipUnless((REPO / "packs").is_dir(), "sin packs/: el repo público no lleva paquetes")
    def test_paquetes_oficiales(self):
        manifiestos = sorted((REPO / "packs").glob("*/pack.toml"))
        self.assertTrue(manifiestos)
        for p in manifiestos:
            with self.subTest(p.parent.name):
                data = tomllib.loads(p.read_text(encoding="utf-8"))
                self.assertEqual(data.get("license"), SPDX)

    def test_sin_rastro_de_bsl(self):
        # los planes y el ADR cuentan la historia de la licencia; el resto no la nombra
        fuera = {"docs", ".git", "node_modules", ".venv", "out", "dist", "target", "__pycache__"}
        hallados = []
        for raiz, dirs, ficheros in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in fuera and not d.startswith(".venv")]
            for nombre in ficheros:
                self._buscar(Path(raiz) / nombre, hallados)
        self.assertEqual(hallados, [])

    @staticmethod
    def _buscar(p, hallados):
        if p.suffix not in {".py", ".ts", ".tsx", ".toml", ".json", ".md", ".rs", ".yml"}:
            return
        if p.name in {"package-lock.json", "test_licencia.py"}:
            return
        try:
            texto = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return
        if "BUSL" in texto or "Business Source" in texto:
            hallados.append(str(p.relative_to(REPO)))


if __name__ == "__main__":
    unittest.main()
