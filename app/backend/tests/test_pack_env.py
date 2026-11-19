"""Entorno de paquetes y trabajador (docs/PLAN_PAQUETES.md P19-P21, §10 «Trabajador» e
«Instalar»; FF 10.1 paso 1).

Reglas:
- El registro que da el trabajador es **el mismo** que la carga en proceso.
- Lo que un paquete escriba en stdout **nunca rompe** el canal del trabajador.
- El trabajador y `uv` **nunca heredan** el Python que los lanza (el del ejecutable de
  PyInstaller), y `uv` nunca descarga un Python.
- Si `uv` falla al crear un entorno, **no queda nada** (ni a medias) y el error dice por qué.
- La huella de un entorno no depende del orden de las librerías, y cambia con el Python.

El trabajador corre aquí con el Python de los tests (`sys.executable`); con el Python
standalone y numpy lo prueba el CI en la app instalada (`app/shell/smoke_pack_env.py`).

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from pizarra import pack_data, pack_env, packs
from tests.helpers import PACKS_PRUEBA

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
ENGINE = REPO / "engine"


def worker():
    return pack_env.PackWorker(sys.executable, BACKEND, ENGINE, stderr=subprocess.DEVNULL)


def write_pack(root, pack_id, body, extra_toml=""):
    d = Path(root) / pack_id
    d.mkdir(parents=True)
    (d / "pack.toml").write_text(f'id = "{pack_id}"\nname = "{pack_id}"\nversion = "1.0.0"\n'
                                 'author = "Pruebas"\ndescription = "Paquete de prueba"\n'
                                 f'sdk = ">=1.0,<2"\nmodule = "blocks"\n{extra_toml}',
                                 encoding="utf-8")
    (d / "blocks.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return d


class TestTrabajador(unittest.TestCase):
    def test_registro_igual_que_en_proceso(self):
        dirs = [str(PACKS_PRUEBA)]
        with worker() as w:
            r = w.request({"op": "register", "dirs": dirs})
        self.assertTrue(r["ok"], r)
        here = json.loads(json.dumps(packs.load(dirs, log=lambda _m: None).describe()))
        self.assertEqual(pack_data.from_data(r["registry"]).describe(), here)
        self.assertIn("prueba.tubo", r["registry"]["blocks"])

    def test_ejecuta_un_bloque_como_en_proceso(self):
        dirs = [str(PACKS_PRUEBA)]
        with worker() as w:
            w.request({"op": "register", "dirs": dirs})
            reg = packs.load(dirs, log=lambda _m: None)
            params = {**reg.default_params("prueba.tubo"), "od": 50}
            r = w.request({"op": "run", "step": {"block_id": "b", "kind": "prueba.tubo",
                                                 "params": params, "inputs": {}}})
        here = reg["prueba.tubo"].run(params, {}, packs.RunContext(block_id="b"))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["outcome"], ["ok", json.loads(json.dumps(here))])

    def test_lo_que_imprime_un_paquete_no_rompe_el_canal(self):
        with tempfile.TemporaryDirectory() as root:
            write_pack(root, "ruidoso", '''
                import os
                from boardprint_sdk.packs import Param
                print("hola al registrarse")
                os.write(1, b"basura por debajo de Python\\n")

                def run(p, i, c):
                    print("hola al ejecutar")
                    os.write(1, b"{no es json\\n")
                    return {"out": {"x": {"value": p["a"], "unit": "mm"}}}

                def register(pack):
                    print("dentro de register")
                    pack.port("ruidoso.t", "t")
                    pack.block("ruidoso.b", "B", run, params={"a": Param(3, "mm")},
                               outputs={"out": "ruidoso.t"})
                ''')
            with worker() as w:
                reg = w.request({"op": "register", "dirs": [root]})
                run = w.request({"op": "run", "step": {"block_id": "b", "kind": "ruidoso.b",
                                                       "params": {"a": 3}, "inputs": {}}})
        self.assertTrue(reg["ok"], reg)
        self.assertEqual(reg["registry"]["packs"][0]["error"], None)
        self.assertEqual(run, {**run, "ok": True,
                               "outcome": ["ok", {"out": {"x": {"value": 3, "unit": "mm"}}}]})

    def test_un_error_vuelve_y_el_trabajador_sigue(self):
        with worker() as w:
            bad = w.request({"op": "run", "step": {"kind": "prueba.tubo"}})    # sin registrar
            unknown = w.request({"op": "nada"})
            ok = w.request({"op": "register", "dirs": [str(REPO / "packs")]})
        self.assertFalse(bad["ok"])
        self.assertIn("registrar", bad["error"])
        self.assertFalse(unknown["ok"])
        self.assertTrue(ok["ok"])


class TestEntornoLimpio(unittest.TestCase):
    BASE = {"PATH": "C:\\bin", "PYTHONPATH": "C:\\_MEI123", "PYTHONHOME": "C:\\_MEI123",
            "_MEIPASS2": "C:\\_MEI123", "_PYI_ARCHIVE_FILE": "x.exe", "_PYI_PARENT_PROCESS_LEVEL": "1",
            "VIRTUAL_ENV": "C:\\venv", "PYTHONDONTWRITEBYTECODE": "1", "UV_PYTHON": "3.9",
            "TCL_LIBRARY": "C:\\_MEI123\\tcl"}

    def test_no_hereda_el_python_que_lo_lanza(self):
        env = pack_env.clean_env(self.BASE)
        self.assertEqual(env["PATH"], "C:\\bin")
        for k in self.BASE:
            if k != "PATH":
                self.assertNotIn(k, env, k)
        self.assertEqual(env["UV_PYTHON_DOWNLOADS"], "never")
        self.assertEqual(env["UV_NO_CONFIG"], "1")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")

    def test_solo_el_sys_path_que_se_le_da(self):
        env = pack_env.clean_env(self.BASE, cache_dir="cache", extra_path=["w", "e"])
        self.assertEqual(env["PYTHONPATH"].split(pack_env.os.pathsep), ["w", "e"])
        self.assertEqual(Path(env["UV_CACHE_DIR"]), (Path("cache") / "uv").resolve())
        self.assertEqual(Path(env["PYTHONPYCACHEPREFIX"]), (Path("cache") / "pycache").resolve())


class TestHuella(unittest.TestCase):
    META = {"python": "3.13.18+20261026", "uv": "0.13.6", "triple": "x86_64-pc-windows-msvc"}

    def test_no_depende_del_orden_ni_de_repetidas(self):
        a = pack_env.env_hash(["numpy>=2,<3", "scipy"], self.META)
        self.assertEqual(a, pack_env.env_hash(["SciPy", "numpy>=2,<3", " scipy "], self.META))
        self.assertNotEqual(a, pack_env.env_hash(["numpy>=2,<3"], self.META))

    def test_cambia_con_el_python_de_la_app(self):
        self.assertNotEqual(pack_env.env_hash([], self.META),
                            pack_env.env_hash([], {**self.META, "python": "3.13.19+20261201"}))

    def test_librerias_de_los_paquetes(self):
        with tempfile.TemporaryDirectory() as root:
            write_pack(root, "a", "", '[python]\ndependencies = ["numpy>=2,<3"]\n')
            write_pack(root, "b", "")
            (Path(root) / "roto").mkdir()
            (Path(root) / "roto" / "pack.toml").write_text("id = = 3", encoding="utf-8")
            self.assertEqual(pack_env.requirements([root, Path(root) / "no-existe"]),
                             ["numpy>=2,<3"])


# `uv` de mentira: `venv <carpeta>` crea la carpeta; `pip install` falla si se pide numpy>=99.
FAKE_UV = '''
import sys
from pathlib import Path
args = sys.argv[1:]
with open(sys.argv[0] + ".log", "a") as f:
    f.write(" ".join(args[:2]) + "\\n")
if args[0] == "venv":
    d = Path(args[-1]); d.mkdir(parents=True); (d / "pyvenv.cfg").write_text("home = x")
elif args[:2] == ["pip", "install"]:
    if "numpy>=99" in args:
        print("No solution found when resolving dependencies: numpy>=99", file=sys.stderr)
        sys.exit(1)
'''


class TestCrearEntorno(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cache = root / "cache"
        py = root / "pyenv" / "python" / ("python.exe" if pack_env.EXE else "bin/python3")
        py.parent.mkdir(parents=True)
        py.write_text("")
        (root / "pyenv" / "pyenv.json").write_text(json.dumps(TestHuella.META))
        self.uv = root / "uv.py"
        self.uv.write_text(textwrap.dedent(FAKE_UV))
        self.pyenv = pack_env.Pyenv(root / "pyenv", uv=[sys.executable, str(self.uv)])

    def tearDown(self):
        self.tmp.cleanup()

    def calls(self):
        log = Path(str(self.uv) + ".log")
        return log.read_text().splitlines() if log.is_file() else []

    def test_si_uv_falla_no_queda_nada(self):
        with self.assertRaises(pack_env.EnvError) as cm:
            pack_env.ensure_env(self.pyenv, self.cache, ["numpy>=99"])
        self.assertIn("No solution found", str(cm.exception))
        self.assertEqual(list((self.cache / "envs").iterdir()), [])

    def test_se_crea_una_vez_y_se_reutiliza(self):
        env, created = pack_env.ensure_env(self.pyenv, self.cache, ["numpy>=2,<3"])
        self.assertTrue(created)
        self.assertTrue((env / pack_env.OK_MARK).is_file())
        self.assertEqual(self.calls(), ["venv --python", "pip install"])
        again, created = pack_env.ensure_env(self.pyenv, self.cache, ["numpy>=2,<3"])
        self.assertEqual((again, created), (env, False))
        self.assertEqual(len(self.calls()), 2)

    def test_uno_a_medias_se_rehace(self):
        env, _ = pack_env.ensure_env(self.pyenv, self.cache, [])
        (env / pack_env.OK_MARK).unlink()                  # como si se cortara la luz
        again, created = pack_env.ensure_env(self.pyenv, self.cache, [])
        self.assertTrue(created)
        self.assertTrue((again / pack_env.OK_MARK).is_file())

    def test_sin_el_python_de_la_app_lo_dice(self):
        bad = pack_env.Pyenv(Path(self.tmp.name) / "no-hay", uv=[sys.executable, str(self.uv)])
        with self.assertRaises(pack_env.EnvError):
            pack_env.ensure_env(bad, self.cache, [])
        self.assertEqual(self.calls(), [])


class TestEntornoDeLaApp(TestCrearEntorno):
    """`PackEnvironment` (P92, P93): las librerías de los paquetes **que se usan** (nunca las de
    una copia tapada por otra de más prioridad); sin librerías, el Python de la app; si no
    cuadran, el error dice **qué paquete pide qué**; un Python que no instala librerías
    **nunca** da un trabajador para un paquete que las pide; limpiar **nunca** borra el
    entorno de ahora."""

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.user, self.ws = root / "user", root / "ws"
        self.env = pack_env.PackEnvironment(BACKEND, ENGINE, self.cache, pyenv=self.pyenv)

    def origins(self):
        return [("workspace", self.ws), ("usuario", self.user)]

    def test_solo_las_librerias_de_los_paquetes_que_se_usan(self):
        write_pack(self.user, "a", "", '[python]\ndependencies = ["numpy>=2,<3"]\n')
        write_pack(self.ws, "a", "")                      # manda la del workspace: sin librerías
        write_pack(self.user, "b", "", '[python]\ndependencies = ["scipy>=1"]\n')
        self.assertEqual(self.env.requirements(self.origins()), {"b": ["scipy>=1"]})

    def test_sin_librerias_el_python_de_la_app(self):
        write_pack(self.user, "a", "")
        spec = self.env.spec(self.origins())
        self.assertEqual(spec.python, str(self.pyenv.python))
        self.assertEqual(self.calls(), [])

    def test_con_librerias_su_entorno(self):
        write_pack(self.user, "a", "", '[python]\ndependencies = ["numpy>=2,<3"]\n')
        spec = self.env.spec(self.origins())
        self.assertTrue(Path(spec.python).is_relative_to(self.cache / "envs"))
        self.assertEqual(self.calls(), ["venv --python", "pip install"])

    def test_si_no_cuadran_dice_que_pide_cada_uno(self):
        write_pack(self.user, "a", "", '[python]\ndependencies = ["numpy>=2,<3"]\n')
        write_pack(self.user, "b", "", '[python]\ndependencies = ["numpy>=99"]\n')
        with self.assertRaises(pack_env.EnvError) as cm:
            self.env.spec(self.origins())
        msg = str(cm.exception)
        self.assertIn("- a: numpy>=2,<3", msg)
        self.assertIn("- b: numpy>=99", msg)
        self.assertIn("No solution found", msg)

    def test_un_python_que_no_instala_librerias(self):
        write_pack(self.user, "a", "", '[python]\ndependencies = ["numpy>=2,<3"]\n')
        env = pack_env.PackEnvironment(BACKEND, ENGINE, self.cache, pyenv=None)
        with self.assertRaisesRegex(pack_env.EnvError, "no instala librerías"):
            env.spec(self.origins())
        self.assertEqual(env.base_spec().python, sys.executable)

    def test_limpiar_deja_el_de_ahora(self):
        write_pack(self.user, "a", "", '[python]\ndependencies = ["numpy>=2,<3"]\n')
        old = Path(self.env.spec(self.origins()).python)
        (self.user / "a" / "pack.toml").write_text(
            (self.user / "a" / "pack.toml").read_text().replace("numpy>=2,<3", "numpy>=2.1,<3"))
        spec = self.env.spec(self.origins())
        self.env.cleanup(spec)
        envs = list((self.cache / "envs").iterdir())
        self.assertEqual(len(envs), 1)
        self.assertTrue(Path(spec.python).is_relative_to(envs[0]))
        self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
