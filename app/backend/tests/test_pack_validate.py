"""Validación estática de un paquete (docs/PLAN_PAQUETES.md §1, §10 «Imports» y «Código de
Fusion», P15, P23).

Reglas:
- Un paquete que importa otro **sin declararlo**, una librería **fuera de `[python]`** o a sí
  mismo en absoluto **no pasa la validación**.
- Un módulo de `fusion/` que alcanza, aunque sea de forma transitiva y a través de otro
  paquete, algo que no es stdlib, `adsk`, `pizarra_engine.core` o código (propio o de un
  paquete de `[requires]`) que cumpla lo mismo **no pasa la validación**; uno que usa un
  paquete que no declara, o que no se encuentra, tampoco (P37).
- Un enlace, algo fuera de la carpeta o un manifiesto incompleto tampoco.
- `tests/` puede abrir una pizarra con el backend y usar su ayuda por su nombre (P65), pero
  sigue sin `adsk` ni librerías sin declarar; fuera de `tests/`, ni lo uno ni lo otro.
- Los paquetes del repo la pasan enteros.

Ejecutar desde app/backend:  python -m unittest tests.test_pack_validate -v
"""
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from pizarra import pack_validate, packs
from tests.helpers import necesita_paquetes

MANIFEST = '''id = "p"
name = "P"
version = "0.1.0"
author = "Yo"
description = "Pruebas"
sdk = ">=1.0,<2"
{extra}
'''
REGISTER = '''
from boardprint_sdk.packs import Param

def register(pack):
    pack.block("p.b", "B", lambda p, i, c: {}, params={"a": Param(1)})
'''


class Validar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "p"
        self.d.mkdir()
        self.manifest()
        self.file("blocks.py", REGISTER)

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, extra=""):
        (self.d / "pack.toml").write_text(MANIFEST.format(extra=textwrap.dedent(extra)),
                                          encoding="utf-8")

    def file(self, rel, text=""):
        p = self.d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")

    def problems(self):
        return packs.validate(self.d)

    def assert_problem(self, *texts):
        probs = self.problems()
        self.assertTrue(probs, "tenía que fallar")
        joined = "\n".join(probs)
        for t in texts:
            self.assertIn(t, joined)
        return probs

    # ----------------------------------------------------------------- lo que vale
    def test_un_paquete_correcto_pasa(self):
        self.manifest('[requires]\nbase = ">=0.1"\n[python]\ndependencies = ["numpy>=2,<3", '
                      '"scikit-learn"]\nmodules = ["sklearn"]')
        self.file("calc/__init__.py")
        self.file("calc/perfil.py", "import math\nimport numpy as np\nfrom sklearn import tree\n")
        self.file("calc/util.py", "from . import perfil\nfrom .perfil import np\nfrom .. import blocks\n")
        self.file("vistas.py", "from .calc import perfil\nfrom .calc.util import perfil as p2\n"
                               "from pizarra_packs.base import flange\n"
                               "import pizarra_packs.base.flange\n"
                               "from boardprint_sdk.packs import Param\n"
                               "from pizarra_engine.core import params\n"
                               "from pizarra_engine import core\n")
        self.file("fusion/__init__.py")
        self.file("fusion/build.py", "import adsk.core, adsk.fusion\nimport json\n"
                                     "from pizarra_engine.core import fusion_io\nfrom . import geo\n")
        self.file("fusion/geo.py", "import math\nfrom ..calc import puro\n")
        self.file("calc/puro.py", "import math\n")
        self.file("tests/test_p.py", "import unittest\nfrom pizarra_packs.p.calc import perfil\n")
        self.assertEqual(self.problems(), [])

    def test_los_nombres_de_libreria_se_comparan_normalizados(self):
        self.manifest('[python]\ndependencies = ["PyYAML>=6", "ruamel.yaml"]\nmodules = ["yaml"]')
        self.file("x.py", "import yaml\nimport ruamel_yaml\n")
        self.assertEqual(self.problems(), [])

    # ----------------------------------------------------------------- imports
    def test_otro_paquete_sin_declararlo_no_pasa(self):
        self.file("x.py", "from pizarra_packs.robotica_base import flange\n")
        self.assert_problem("x.py:1", "usa el paquete robotica_base sin declararlo en [requires]")

    def test_otro_paquete_con_from_sin_declararlo_no_pasa(self):
        self.file("x.py", "from pizarra_packs import robotica_base\n")
        self.assert_problem("robotica_base sin declararlo")

    def test_una_libreria_fuera_de_python_no_pasa(self):
        self.manifest('[python]\ndependencies = ["numpy>=2"]')
        self.file("x.py", "import numpy\nimport scipy.optimize\n")
        probs = self.assert_problem("la librería scipy no está en [python] dependencies")
        self.assertNotIn("numpy", "\n".join(probs))

    def test_un_import_dentro_de_una_funcion_tambien_cuenta(self):
        self.file("x.py", "def f():\n    import scipy\n")
        self.assert_problem("x.py:2", "scipy")

    def test_a_si_mismo_en_absoluto_no_pasa(self):
        self.file("calc.py", "X = 1\n")
        self.file("x.py", "from pizarra_packs.p import calc\n")
        self.assert_problem("se importa a sí mismo en absoluto")

    def test_una_carpeta_propia_por_su_nombre_no_pasa(self):
        self.file("robotarm/__init__.py")
        self.file("robotarm/model.py", "X = 1\n")
        self.file("x.py", "from robotarm import model\n")
        self.assert_problem("es código del paquete; impórtalo en relativo")

    def test_el_backend_no_se_importa(self):
        self.file("x.py", "from pizarra import fusion_mcp\n")
        self.assert_problem("importa el backend de la app")

    def test_los_tests_pueden_abrir_una_pizarra_y_usar_su_ayuda(self):
        # P65: tests/ no lo carga la app; unittest pone tests/ en el path, así que su ayuda
        # se importa por su nombre, también desde una subcarpeta
        self.file("tests/paquete.py", "from pizarra import board, packs\nREG = packs.load([])\n")
        self.file("tests/brazo/__init__.py")
        self.file("tests/brazo/test_a.py", "import paquete\nfrom pizarra.board import Board\n"
                                          "from pizarra_packs.p import blocks\n")
        self.file("tests/test_b.py", "import paquete\nfrom brazo import test_a\nimport pizarra.storage\n")
        self.assertEqual(self.problems(), [])

    def test_los_tests_siguen_sin_adsk_ni_librerias_sin_declarar(self):
        self.file("tests/test_a.py", "import adsk.core\nimport numpy\n")
        self.assert_problem("tests/test_a.py:1: adsk.core: adsk solo en fusion/",
                            "tests/test_a.py:2: numpy: la librería numpy no está")

    def test_la_ayuda_de_tests_no_vale_fuera_de_tests(self):
        self.file("tests/paquete.py", "")
        self.file("x.py", "import paquete\nfrom pizarra import board\n")
        self.assert_problem("x.py:1: paquete: la librería paquete no está",
                            "x.py:2: pizarra: importa el backend de la app")

    def test_del_motor_solo_core(self):
        self.file("x.py", "from pizarra_engine.robotarm import catalog\nfrom pizarra_engine import terminals\n")
        probs = self.assert_problem("x.py:1", "x.py:2", "solo se usa pizarra_engine.core")
        self.assertEqual(len(probs), 2)

    def test_adsk_fuera_de_fusion_no_pasa(self):
        self.file("x.py", "import adsk.core\n")
        self.assert_problem("adsk solo en fusion/")

    def test_un_relativo_que_sale_del_paquete_no_pasa(self):
        self.file("x.py", "from .. import otro\n")
        self.assert_problem("sale del paquete")

    def test_un_relativo_a_algo_que_no_existe_no_pasa(self):
        self.file("x.py", "from .nada import y\n")
        self.assert_problem("no encuentra nada en el paquete")

    def test_un_py_que_no_se_lee_no_pasa(self):
        self.file("x.py", "def (:\n")
        self.assert_problem("x.py: no se puede leer")

    # ----------------------------------------------------------------- Fusion (P15)
    def test_fusion_con_una_libreria_no_pasa_aunque_este_declarada(self):
        self.manifest('[python]\ndependencies = ["numpy>=2"]')
        self.file("fusion/build.py", "import numpy\n")
        self.assert_problem("fusion/build.py:1", "lo que corre en Fusion solo usa")

    def test_fusion_con_el_sdk_de_la_app_no_pasa(self):
        self.file("fusion/build.py", "from boardprint_sdk.packs import Param\n")
        self.assert_problem("lo que corre en Fusion solo usa")

    def test_fusion_que_alcanza_una_libreria_de_forma_transitiva_no_pasa(self):
        self.manifest('[python]\ndependencies = ["numpy>=2"]')
        self.file("calc/__init__.py")
        self.file("calc/geo.py", "from . import malla\n")
        self.file("calc/malla.py", "import numpy as np\n")
        self.file("fusion/build.py", "from ..calc import geo\n")
        probs = self.assert_problem("fusion/build.py alcanza calc/malla.py", "numpy")
        # fuera de Fusion, calc/malla.py está bien: numpy está declarado
        self.assertEqual(len(probs), 1, probs)

    # P37: lo de fusion/ puede usar un paquete de [requires] si lo que alcanza de él cumple
    def base(self, files, extra="", where=None):
        """El paquete `base` (junto a `p`, o en `where`) con sus `files` {ruta: texto}."""
        d = Path(where or self.d.parent) / "base"
        d.mkdir(parents=True)
        (d / "pack.toml").write_text(MANIFEST.replace('id = "p"', 'id = "base"')
                                     .format(extra=textwrap.dedent(extra)), encoding="utf-8")
        for rel, text in {"blocks.py": "def register(pack):\n    pass\n", **files}.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(textwrap.dedent(text), encoding="utf-8")
        return d

    def test_fusion_que_usa_un_paquete_de_requires_que_cumple_pasa(self):
        self.manifest('[requires]\nbase = ">=0.1"')
        self.base({"flange.py": "import math\nfrom . import iso\n", "iso.py": "X = 1\n"})
        self.file("calc.py", "from pizarra_packs.base import flange\n")
        self.file("fusion/build.py", "from .. import calc\nfrom pizarra_packs.base.iso import X\n")
        self.assertEqual(self.problems(), [])

    def test_fusion_que_alcanza_una_libreria_a_traves_de_otro_paquete_no_pasa(self):
        self.manifest('[requires]\nbase = ">=0.1"')
        self.base({"flange.py": "from . import malla\n", "malla.py": "import numpy\n"},
                  '[python]\ndependencies = ["numpy>=2"]')
        self.file("calc.py", "from pizarra_packs.base import flange\n")
        self.file("fusion/build.py", "from .. import calc\n")
        probs = self.assert_problem("fusion/build.py alcanza base/malla.py", "numpy")
        self.assertEqual(len(probs), 1, probs)     # fuera de Fusion, calc.py está bien

    def test_fusion_que_alcanza_un_paquete_que_el_otro_no_declara_no_pasa(self):
        self.manifest('[requires]\nbase = ">=0.1"')
        self.base({"flange.py": "from pizarra_packs.otro import x\n"})
        self.file("fusion/build.py", "from pizarra_packs.base import flange\n")
        self.assert_problem("fusion/build.py alcanza base/flange.py", "otro sin declararlo")

    def test_fusion_con_un_paquete_que_no_esta_no_pasa(self):
        self.manifest('[requires]\nbase = ">=0.1"')
        self.file("calc.py", "from pizarra_packs.base import flange\n")
        self.file("fusion/build.py", "from .. import calc\n")
        self.assert_problem("fusion/build.py alcanza calc.py", "no se encuentra el paquete base")

    def test_fusion_con_un_modulo_que_el_otro_paquete_no_tiene_no_pasa(self):
        self.manifest('[requires]\nbase = ">=0.1"')
        self.base({})
        self.file("fusion/build.py", "from pizarra_packs.base.flange import x\n")
        self.assert_problem("fusion/build.py:1", "no está en el paquete base")

    def test_fusion_con_otro_paquete_sin_declararlo_no_pasa(self):
        self.base({"flange.py": "X = 1\n"})
        self.file("fusion/build.py", "from pizarra_packs.base import flange\n")
        self.assert_problem("fusion/build.py:1", "base sin declararlo")

    def test_el_otro_paquete_se_busca_donde_diga_find(self):
        self.manifest('[requires]\nbase = ">=0.1"')
        other = self.base({"flange.py": "import numpy\n"}, '[python]\ndependencies = ["numpy"]',
                          where=Path(self.tmp.name) / "instalados")
        self.file("fusion/build.py", "from pizarra_packs.base import flange\n")
        self.assert_problem("no se encuentra el paquete base")      # junto a p no está
        probs = packs.validate(self.d, find={"base": other}.get)
        self.assertTrue(any("alcanza base/flange.py" in p for p in probs), probs)

    def test_un_ciclo_de_imports_propios_no_cuelga_la_validacion(self):
        self.file("fusion/a.py", "from . import b\n")
        self.file("fusion/b.py", "from . import a\n")
        self.assertEqual(self.problems(), [])

    # ----------------------------------------------------------------- ficheros y manifiesto
    def test_un_manifiesto_incompleto_no_pasa(self):
        (self.d / "pack.toml").write_text('id = "p"\nversion = "0.1.0"\nsdk = ">=1.0,<2"\n',
                                          encoding="utf-8")
        self.assert_problem("falta name", "falta author", "falta description")

    def test_un_manifiesto_roto_no_pasa(self):
        (self.d / "pack.toml").write_text('id = "p"\nversion = "1"\n', encoding="utf-8")
        self.assert_problem("pack.toml: la versión", "pack.toml: falta sdk")

    def test_sin_el_modulo_de_register_no_pasa(self):
        (self.d / "blocks.py").unlink()
        self.assert_problem("falta blocks.py")

    def test_una_ui_que_no_esta_no_pasa(self):
        self.manifest('[ui]\nentry = "ui/index.html"')
        self.assert_problem("no está ui/index.html")

    def test_un_enlace_no_pasa(self):
        fuera = Path(self.tmp.name) / "fuera"
        fuera.mkdir()
        (fuera / "secreto.py").write_text("X = 1\n", encoding="utf-8")
        link = self.d / "datos"
        try:
            os.symlink(fuera, link, target_is_directory=True)
        except OSError:
            try:
                import _winapi
                _winapi.CreateJunction(str(fuera), str(link))
            except (ImportError, OSError):
                self.skipTest("no se pueden crear enlaces en esta máquina")
        self.assert_problem("datos: es un enlace")

    def test_demasiado_grande_no_pasa(self):
        self.file("library/ficha.json", "x" * 2048)
        with mock.patch.object(pack_validate, "MAX_BYTES", 1024):
            self.assert_problem("el paquete ocupa")

    def test_ui_src_no_cuenta_para_el_tamano(self):
        self.file("ui-src/node_modules_falso.js", "x" * 4096)
        with mock.patch.object(pack_validate, "MAX_BYTES", 2048):
            self.assertEqual(self.problems(), [])


@necesita_paquetes
class LosPaquetesDelRepo(unittest.TestCase):
    """Todos los paquetes de `packs/` pasan la validación entera, `tests/` incluido (P65):
    desde FF 10.2 la carga la aplica, y uno que no la pase no se carga. `fusion` necesita su
    `ui/` compilada (`scripts/build-packs.mjs`, P61), que no se versiona."""

    def test_los_paquetes_del_repo_pasan_la_validacion(self):
        root = Path(packs.__file__).resolve().parents[3] / "packs"
        found = sorted(p.name for p in root.iterdir() if (p / "pack.toml").is_file())
        self.assertGreaterEqual(set(found), {"demo", "fusion", "robotica", "robotica_base",
                                             "terminales"})
        for pack_id in found:
            with self.subTest(pack_id):
                self.assertEqual(packs.validate(root / pack_id), [])


if __name__ == "__main__":
    unittest.main()
