"""El entorno de paquetes de verdad, con `uv` y numpy (docs/PLAN_PAQUETES.md P92, P96).

Regla: un paquete que pide numpy **se registra, se ejecuta y da lo que calcula numpy** en el
trabajador del entorno que crea `PackEnvironment`, y el backend nunca lo importa.

Necesita `uv` e internet (o numpy en la caché de `uv`): sin `uv`, se salta. En local usa el
Python y el `uv` de la app (`app/shell/src-tauri/pyenv`, de `fetch_pyenv.py`); en el CI, el
Python del runner y el `uv` de pip.

Ejecutar desde app/backend:  python -m unittest tests.test_entorno_real -v
"""
import asyncio
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pizarra import pack_env, pack_host
from pizarra.execution import Step

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
LOCAL = pack_env.Pyenv(REPO / "app" / "shell" / "src-tauri" / "pyenv")
NUMPY = Path(__file__).resolve().parent / "packs_numpy"


def pyenv():
    """El de la app si está descargado; si no, el Python de los tests con el `uv` del PATH."""
    if LOCAL.python.is_file():
        return LOCAL
    uv = shutil.which("uv")
    if not uv:
        return None
    env = pack_env.Pyenv(Path(tempfile.mkdtemp()), uv=[uv])
    env.python = Path(sys.executable)
    env.meta = {"python": sys.version.split()[0], "uv": "path", "triple": sys.platform}
    return env


PYENV = pyenv()


@unittest.skipIf(PYENV is None, "sin uv: ni el pyenv de la app ni uv en el PATH")
class EntornoConNumpy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = Path(tempfile.mkdtemp())
        cls.env = pack_env.PackEnvironment(BACKEND, REPO / "engine", cls.cache, pyenv=PYENV,
                                           stderr=subprocess.DEVNULL)
        cls.origins = [("pruebas", NUMPY)]
        cls.spec = cls.env.spec(cls.origins)            # crea el entorno: puede descargar
        cls.host = pack_host.WorkerHost(cls.spec, cls.origins)
        cls.reg = cls.host.load()

    @classmethod
    def tearDownClass(cls):
        cls.host.close()
        shutil.rmtree(cls.cache, ignore_errors=True)

    def test_el_entorno_tiene_numpy_y_carga(self):
        self.assertTrue(Path(self.spec.python).is_relative_to(self.cache / "envs"))
        self.assertIsNone(self.reg.pack("numpy_demo").error)
        self.assertIn("numpy_demo.seno", self.reg)

    def test_ejecuta_con_numpy_en_su_trabajador(self):
        w = self.host.run_worker()
        step = Step(block_id="b", kind="numpy_demo.seno", params={"L": 10.0, "n": 1000},
                    inputs={}, input_hash="", workdir=str(self.cache))

        async def go():
            async def progress(*_):
                pass
            return await w.run(step, progress)

        try:
            got = asyncio.run(go())
        finally:
            w.close()
        self.assertEqual(got[0], "ok", got)
        serie = got[1]["serie"]
        self.assertEqual(serie["n"]["value"], 1000)
        # la media de sin(x) en [0, 10] con 1000 puntos: (1 - cos 10) / 10, aproximada
        self.assertAlmostEqual(serie["media"]["value"], (1 - math.cos(10)) / 10, places=2)
        self.assertTrue(serie["numpy"]["value"].startswith("2."))


if __name__ == "__main__":
    unittest.main()
