"""Los paquetes que hace el agente (docs/PLAN_PAQUETES.md §8, §10, P99-P103).

Reglas:
- **Borrador**: el agente **nunca escribe fuera** de su borrador (ruta absoluta, con `..`, con
  unidad o por un enlace), y la plantilla da un paquete que **valida en verde**.
- **Validar** (P101): un test que falla, un import sin declarar o un `register` roto dejan la
  validación **en rojo**, con el motivo.
- **Proponer** (P102): `proponer_paquete` **se niega** si no hay validación, si la última no
  está en verde o si el borrador cambió después.
- **Duplicar** (P103): la copia lleva el id nuevo y la versión 0.1.0, y dice **dónde sale el id
  de antes**.

Ejecutar desde app/backend:  python -m unittest tests.test_agent_packs -v
"""
import os
import tempfile
import unittest
from pathlib import Path

from pizarra import agent_packs as ap, pack_install, packs
from tests.helpers import PACKS_PRUEBA

REPO = Path(__file__).resolve().parents[3]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ap.DRAFTS
        self.root.mkdir()
        self.origins = [("desarrollo", REPO / "packs")]

    def tearDown(self):
        self.tmp.cleanup()


class Borrador(Base):
    def test_la_plantilla_valida_en_verde(self):
        files = ap.create(self.root, "vigas", "Vigas", "Flecha de vigas")
        self.assertEqual(sorted(f["path"] for f in files),
                         ["blocks.py", "pack.toml", "tests/__init__.py", "tests/test_blocks.py"])
        self.assertIn('id = "vigas"', ap.read(self.root, "vigas", "pack.toml"))
        rep = ap.validate(self.root, "vigas", self.origins)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["blocks"], ["Ejemplo"])
        self.assertEqual((rep["tests"]["ran"], rep["tests"]["failures"]), (1, 0))

    def test_nunca_escribe_fuera_del_borrador(self):
        ap.create(self.root, "vigas", "Vigas", "Flecha")
        outside = Path(self.tmp.name) / "fuera.py"
        for rel in ("../fuera.py", "../../fuera.py", str(outside), "/fuera.py", "C:/fuera.py",
                    "tests/../../fuera.py", "", "a/./b.py"):
            with self.subTest(rel):
                with self.assertRaises(ap.DraftError):
                    ap.write(self.root, "vigas", rel, "x = 1\n")
        self.assertFalse(outside.exists())
        try:
            os.symlink(Path(self.tmp.name), self.root / "vigas" / "enlace", target_is_directory=True)
        except OSError:
            self.skipTest("sin permiso para crear enlaces")
        with self.assertRaisesRegex(ap.DraftError, "enlace"):
            ap.write(self.root, "vigas", "enlace/fuera.py", "x = 1\n")
        self.assertFalse(outside.exists())

    def test_ids_y_borradores_que_no_estan(self):
        for bad in ("Vigas", "1x", "a-b", "../x"):
            with self.assertRaises(ap.DraftError):
                ap.create(self.root, bad, "x", "y")
        with self.assertRaisesRegex(ap.DraftError, "no hay ningún borrador"):
            ap.list_files(self.root, "nada")
        ap.create(self.root, "vigas", "Vigas", "Flecha")
        with self.assertRaisesRegex(ap.DraftError, "ya hay"):
            ap.create(self.root, "vigas", "Vigas", "Flecha")
        with self.assertRaisesRegex(ap.DraftError, "falta la descripción"):
            ap.create(self.root, "otra", "Otra", " ")


class Validar(Base):
    def setUp(self):
        super().setUp()
        ap.create(self.root, "vigas", "Vigas", "Flecha de vigas")

    def test_un_test_que_falla(self):
        ap.write(self.root, "vigas", "tests/test_mal.py",
                 "import unittest\nclass M(unittest.TestCase):\n"
                 "    def test_falla(self):\n        self.assertEqual(1, 2)\n")
        rep = ap.validate(self.root, "vigas", self.origins)
        self.assertFalse(rep["ok"])
        self.assertIn("los tests no pasan", rep["problems"])
        self.assertEqual(rep["tests"]["failures"], 1)

    def test_un_import_sin_declarar(self):
        ap.write(self.root, "vigas", "blocks.py",
                 "import numpy\n" + ap.read(self.root, "vigas", "blocks.py"))
        rep = ap.validate(self.root, "vigas", self.origins)
        self.assertFalse(rep["ok"])
        self.assertTrue(any("numpy" in p for p in rep["problems"]), rep["problems"])

    def test_un_register_roto(self):
        ap.write(self.root, "vigas", "blocks.py", "def register(pack):\n    raise ValueError('mal')\n")
        rep = ap.validate(self.root, "vigas", self.origins)
        self.assertFalse(rep["ok"])
        self.assertTrue(any("mal" in p for p in rep["problems"]), rep["problems"])

    def test_sin_tests_no_vale(self):
        (self.root / "vigas" / "tests" / "test_blocks.py").unlink()
        rep = ap.validate(self.root, "vigas", self.origins)
        self.assertFalse(rep["ok"])


class Proponer(Base):
    def setUp(self):
        super().setUp()
        ap.create(self.root, "vigas", "Vigas", "Flecha de vigas")

    def test_sin_validar_se_niega(self):
        with self.assertRaisesRegex(ap.DraftError, "primero valídalo"):
            ap.propose(self.root, "vigas")

    def test_en_rojo_se_niega(self):
        ap.write(self.root, "vigas", "blocks.py", "def register(pack):\n    raise ValueError('mal')\n")
        ap.validate(self.root, "vigas", self.origins)
        with self.assertRaisesRegex(ap.DraftError, "no está en verde"):
            ap.propose(self.root, "vigas")

    def test_si_cambia_despues_se_niega(self):
        ap.validate(self.root, "vigas", self.origins)
        ap.write(self.root, "vigas", "notas.md", "un cambio\n")
        with self.assertRaisesRegex(ap.DraftError, "ha cambiado"):
            ap.propose(self.root, "vigas")
        ap.validate(self.root, "vigas", self.origins)
        got = ap.propose(self.root, "vigas")
        self.assertEqual((got["id"], got["blocks"], got["tests"]["count"]), ("vigas", ["Ejemplo"], 1))
        self.assertEqual(got["tests"]["names"], ["test_el_area_es_ancho_por_alto"])

    def test_exportar_lo_propuesto_se_instala(self):
        ap.validate(self.root, "vigas", self.origins)
        path, _ = ap.export(self.root, "vigas", Path(self.tmp.name) / "out", self.origins)
        self.assertEqual(path.name, "vigas-0.1.0.bppack")
        user = Path(self.tmp.name) / "user"
        user.mkdir()
        plan = pack_install.inspect([path], "usuario", [("usuario", user)], loaded=[],
                                    trial=pack_install._trial)
        self.assertTrue(plan.ok, plan.view())


class Duplicar(Base):
    def setUp(self):
        super().setUp()
        self.origins = [("desarrollo", PACKS_PRUEBA)]       # también en el repo público

    def test_copia_con_el_id_nuevo_y_dice_donde_sale_el_viejo(self):
        got = ap.duplicate(self.root, self.origins, "prueba", "mi_prueba")
        toml = ap.read(self.root, "mi_prueba", "pack.toml")
        self.assertIn('id = "mi_prueba"', toml)
        self.assertIn('version = "0.1.0"', toml)
        self.assertTrue(any(p["file"] == "blocks.py" and "prueba.tubo" in p["text"]
                            for p in got["replace"]), got)
        self.assertFalse(any(p["file"] == "pack.toml" and p["text"].startswith("id")
                             for p in got["replace"]))
        with self.assertRaisesRegex(ap.DraftError, "no hay ningún paquete instalado"):
            ap.duplicate(self.root, self.origins, "nada", "otra")


class HerramientasDelAgente(Base):
    """Lo mismo, como lo ve el agente (`agent.tool_paquete`): un fallo vuelve como error de
    herramienta para que lo corrija, y solo proponer da la tarjeta del chat."""

    def call(self, name, **args):
        from pizarra import agent
        result, proposal = agent.tool_paquete(self.root, name, args)
        return result, proposal

    def test_de_la_guia_a_la_tarjeta(self):
        guide, _ = self.call("guia_paquetes")
        self.assertIn("Cómo se hace un paquete", guide["content"][0]["text"])
        res, _ = self.call("crear_paquete", id="vigas", nombre="Vigas", descripcion="Flecha")
        self.assertFalse(res.get("is_error"))
        res, card = self.call("proponer_paquete", id="vigas")
        self.assertTrue(res.get("is_error"))
        self.assertIsNone(card)
        res, _ = self.call("validar_paquete", id="vigas")
        self.assertFalse(res.get("is_error"), res)
        res, card = self.call("proponer_paquete", id="vigas")
        self.assertFalse(res.get("is_error"))
        self.assertEqual((card["id"], card["blocks"]), ("vigas", ["Ejemplo"]))

    def test_fuera_del_borrador_es_un_error_de_herramienta(self):
        self.call("crear_paquete", id="vigas", nombre="Vigas", descripcion="Flecha")
        res, _ = self.call("escribir_archivo_paquete", id="vigas", ruta="../fuera.py", contenido="x")
        self.assertTrue(res.get("is_error"))
        self.assertIn("quedarse en el borrador", res["content"][0]["text"])
        self.assertFalse((self.root / "fuera.py").exists())

    def test_una_validacion_en_rojo_vuelve_como_error(self):
        self.call("crear_paquete", id="vigas", nombre="Vigas", descripcion="Flecha")
        self.call("escribir_archivo_paquete", id="vigas", ruta="blocks.py",
                  contenido="def register(pack):\n    raise ValueError('mal')\n")
        res, _ = self.call("validar_paquete", id="vigas")
        self.assertTrue(res.get("is_error"))
        self.assertIn("mal", res["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
