"""Instalar, exportar y desinstalar paquetes (docs/PLAN_PAQUETES.md §7, §10, P75-P84).

Reglas:
- **Archivo**: un `.bppack` con rutas fuera de su carpeta, enlaces, más de una carpeta o un
  manifiesto roto **no deja nada en disco**; exportar e instalar da **siempre la misma huella**,
  y lo exportado **nunca** lleva `ui-src/`, `__pycache__` ni un `.pyc` (P83).
- **Instalar**: un paquete con librerías **no se instala** hasta FF 10.4 (P75); con varios
  archivos, si uno falla **no se instala ninguno**; una dependencia que no está ni en otro
  archivo elegido **nunca** se da por buena; instalar uno que ya está **sustituye** su carpeta y
  nunca deja las dos (P79); si un renombrado falla, **no cambia nada**.
- **Desinstalar** (P84): un paquete que otro cargado pide **nunca se desinstala**; desarrollo
  **no se desinstala**.
- **Validación por huella** (P80): la misma clave **no se vuelve a validar**; si cambia un
  fichero suyo o de un paquete que pide, **siempre** se valida; uno que no pasó **nunca** se
  carga por estar en la caché.

Ejecutar desde app/backend:  python -m unittest tests.test_pack_install -v
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

import subprocess

from pizarra import pack_host, pack_install, pack_validate, packs
from tests.test_pack_load import write

try:
    import uvicorn
    from websockets.sync.client import connect
    from pizarra import blocks as blocks_mod
    from pizarra.server import create_app
    from pizarra.startup import bootstrap
    DEPS = True
except ImportError:                     # job básico del CI: solo biblioteca estándar
    DEPS = False


def trial_here(origins, validated):
    """La carga de prueba en este proceso: en los tests da igual que importe los paquetes."""
    return pack_install._trial(origins, validated)


def bad_zip(path, names, link=None):
    """Un zip a mano: `names` {ruta: contenido}; `link`: una ruta que es un enlace."""
    with zipfile.ZipFile(path, "w") as z:
        for name, data in names.items():
            z.writestr(name, data)
        if link:
            zi = zipfile.ZipInfo(link)
            zi.external_attr = (0o120777) << 16
            z.writestr(zi, "../../fuera")
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src, self.out = root / "src", root / "out"
        self.user, self.ws, self.dev = root / "user", root / "ws", root / "dev"
        for d in (self.src, self.out, self.user, self.ws):
            d.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def origins(self, dev=False):
        return ([("desarrollo", self.dev)] if dev else []) + [("workspace", self.ws),
                                                              ("usuario", self.user)]

    def loaded(self):
        return packs.load(self.origins(), log=lambda m: None).packs

    def pack(self, pack_id, **kw):
        """Escribe el paquete en una carpeta nueva y lo exporta: la ruta del `.bppack`."""
        root = Path(tempfile.mkdtemp(dir=self.src))
        folder = write(root, pack_id, **kw)
        return pack_install.export(folder, self.out, find=lambda p: root / p)

    def inspect(self, archives, target="usuario", trial=trial_here):
        return pack_install.inspect(archives, target, self.origins(), loaded=self.loaded(),
                                    trial=trial)

    def installed(self):
        """Lo que hay en la carpeta del usuario, sin la de trabajo."""
        return sorted(p.name for p in self.user.iterdir() if p.name != pack_install.WORK)


class Archivo(Base):
    def test_exportar_e_instalar_da_la_misma_huella_y_nunca_lleva_ui_src_ni_pycache(self):
        folder = write(self.src / "x", "p")
        for rel in ("ui-src/main.ts", "__pycache__/blocks.cpython-313.pyc", "datos/x.pyc"):
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_text("no", encoding="utf-8")
        (folder / "datos" / "tabla.csv").write_text("a,b\n", encoding="utf-8")
        arch = pack_install.export(folder, self.out)
        self.assertEqual(arch.name, "p-1.0.0.bppack")
        with zipfile.ZipFile(arch) as z:
            self.assertEqual(sorted(z.namelist()),
                             ["p/blocks.py", "p/datos/tabla.csv", "p/pack.toml"])
        plan = self.inspect([arch])
        self.assertTrue(plan.ok, plan.view())
        pack_install.install(plan)
        self.assertEqual(packs.digest(self.user / "p"), packs.digest(folder))

    def test_el_agent_md_va_en_el_archivo_y_la_validacion_lo_deja(self):
        # D172: las instrucciones del agente son del paquete, como su código
        folder = write(self.src / "x", "p")
        (folder / "agent.md").write_text("Cómo montar los bloques de p", encoding="utf-8")
        self.assertEqual(pack_validate.validate(folder), [])
        arch = pack_install.export(folder, self.out)
        with zipfile.ZipFile(arch) as z:
            self.assertIn("p/agent.md", z.namelist())
        plan = self.inspect([arch])
        self.assertTrue(plan.ok, plan.view())
        pack_install.install(plan)
        self.assertEqual((self.user / "p" / "agent.md").read_text(encoding="utf-8"),
                         "Cómo montar los bloques de p")

    def test_exportar_dos_veces_da_los_mismos_bytes(self):
        folder = write(self.src / "x", "p")
        a = pack_install.export(folder, self.out / "a").read_bytes()
        os.utime(folder / "blocks.py", (1, 1))
        b = pack_install.export(folder, self.out / "b").read_bytes()
        self.assertEqual(a, b)

    def test_exportar_se_niega_si_no_pasa_la_validacion_o_falta_su_interfaz(self):
        folder = write(self.src / "x", "p", body="import numpy\ndef register(pack):\n    pass\n")
        with self.assertRaisesRegex(ValueError, "no pasa la validación"):
            pack_install.export(folder, self.out)
        folder = write(self.src / "x", "q", extra='[ui]\nentry = "ui/index.html"')
        with self.assertRaisesRegex(ValueError, "no está compilada"):
            pack_install.export(folder, self.out)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_un_archivo_malo_nunca_deja_nada_en_disco(self):
        good = 'id = "p"\nname = "p"\nversion = "1.0.0"\nsdk = ">=1.0,<2"\n'
        cases = {
            "absoluta": {"/p/pack.toml": good},
            "sube": {"p/pack.toml": good, "p/../../fuera.py": "x"},
            "barra": {"p/pack.toml": good, "p\\..\\fuera.py": "x"},
            "unidad": {"p/pack.toml": good, "C:/fuera.py": "x"},
            "dos carpetas": {"p/pack.toml": good, "q/pack.toml": good},
            "suelto": {"p/pack.toml": good, "suelto.py": "x"},
            "repetido": {"p/pack.toml": good, "p/A.py": "x", "p/a.py": "y"},
            "manifiesto": {"p/pack.toml": "id = 'otro'\n"},
            "id malo": {"P-x/pack.toml": good},
        }
        archives = [bad_zip(self.out / f"{i}.bppack", names) for i, names in enumerate(cases.values())]
        archives.append(bad_zip(self.out / "enlace.bppack", {"p/pack.toml": good}, link="p/x"))
        archives.append(self.out / "no-es-zip.bppack")
        archives[-1].write_text("hola", encoding="utf-8")
        for arch in archives:
            with self.subTest(arch.name):
                plan = self.inspect([arch])
                self.assertFalse(plan.ok)
                self.assertTrue(plan.items[0].problems)
                with self.assertRaises(ValueError):
                    pack_install.install(plan)
                plan.discard()
                self.assertEqual(self.installed(), [])
                self.assertEqual(list(self.user.rglob("*.py")) + list(self.user.rglob("*.toml")), [])

    def test_un_pyc_del_archivo_nunca_se_saca(self):
        arch = self.pack("p")
        with zipfile.ZipFile(arch, "a") as z:
            z.writestr("p/__pycache__/blocks.cpython-313.pyc", b"malo")
            z.writestr("p/otro.pyc", b"malo")
        pack_install.install(self.inspect([arch]))
        self.assertEqual(sorted(packs.pack_files(self.user / "p")), ["blocks.py", "pack.toml"])
        # el __pycache__ que haya es el de Python al importar blocks.py, nunca el del archivo
        self.assertFalse((self.user / "p" / "otro.pyc").exists())
        self.assertNotIn(b"malo", [f.read_bytes() for f in (self.user / "p").rglob("*.pyc")])


class Instalar(Base):
    def test_instala_en_el_usuario_y_carga(self):
        plan = self.inspect([self.pack("p", title="Bloque P")])
        self.assertEqual(plan.items[0].blocks, ["Bloque P"])
        self.assertIsNone(plan.items[0].replaces)
        self.assertEqual(pack_install.install(plan), ["p"])
        reg = packs.load(self.origins(), log=lambda m: None)
        self.assertIn("p.b", reg)
        self.assertEqual(reg.pack("p").origin, "usuario")
        self.assertFalse((self.user / pack_install.WORK).exists()
                         and any((self.user / pack_install.WORK).iterdir()))

    def test_en_el_workspace(self):
        pack_install.install(self.inspect([self.pack("p")], target="workspace"))
        self.assertTrue((self.ws / "p" / "pack.toml").is_file())
        with self.assertRaisesRegex(ValueError, "no se puede instalar en 'desarrollo'"):
            self.inspect([self.pack("q")], target="desarrollo")

    def test_con_librerias_nunca_se_instala(self):
        folder = write(self.src / "x", "p", extra='[python]\ndependencies = ["numpy>=2,<3"]',
                       body="import numpy\ndef register(pack):\n    pass\n")
        arch = self.out / "p.bppack"
        with zipfile.ZipFile(arch, "w") as z:
            for rel in packs.pack_files(folder):
                z.write(folder / rel, f"p/{rel}")
        plan = self.inspect([arch])
        self.assertFalse(plan.ok)
        self.assertIn("librerías de Python (numpy>=2,<3)", plan.items[0].problems[0])
        self.assertEqual(plan.items[0].libraries, ["numpy>=2,<3"])
        with self.assertRaises(ValueError):
            pack_install.install(plan)
        self.assertEqual(self.installed(), [])

    def lib_pack(self, reqs='["numpy>=2,<3"]'):
        folder = write(self.src / "lib", "p", extra=f"[python]\ndependencies = {reqs}",
                       body="import numpy\ndef register(pack):\n    pass\n")
        arch = self.out / "p-lib.bppack"
        with zipfile.ZipFile(arch, "w") as z:
            for rel in packs.pack_files(folder):
                z.write(folder / rel, f"p/{rel}")
        return arch

    def test_con_entorno_un_paquete_con_librerias_se_instala(self):
        # P92: con quien resuelva el entorno, ya no vale la regla de P75
        seen = []

        def resolve(origins):
            seen.append([o for o, _ in origins])
            return lambda origins, validated: {"p": {"error": None, "version": "1.0.0", "blocks": []}}

        plan = pack_install.inspect([self.lib_pack()], "usuario", self.origins(),
                                    loaded=self.loaded(), trial=trial_here, resolve=resolve)
        self.assertTrue(plan.ok, plan.view())
        self.assertEqual(seen, [["workspace", "nuevo", "usuario"]])
        pack_install.install(plan)
        self.assertEqual(self.installed(), ["p"])

    def test_si_las_librerias_no_cuadran_no_se_instala_nada(self):
        from pizarra.pack_env import EnvError

        def resolve(origins):
            raise EnvError("las librerías no se pueden instalar juntas:\n- p: numpy>=99")

        plan = pack_install.inspect([self.lib_pack('["numpy>=99"]')], "usuario", self.origins(),
                                    loaded=self.loaded(), trial=trial_here, resolve=resolve)
        self.assertFalse(plan.ok)
        self.assertIn("- p: numpy>=99", plan.items[0].problems[0])
        with self.assertRaises(ValueError):
            pack_install.install(plan)
        self.assertEqual(self.installed(), [])

    def test_una_dependencia_que_falta_nunca_se_da_por_buena(self):
        self.pack("base")
        plan = self.inspect([self.pack("p", requires={"base": ">=1.0,<2"})])
        self.assertFalse(plan.ok)
        self.assertEqual(plan.items[0].requires[0]["state"], "falta")
        self.assertIn("elige también su archivo", plan.items[0].problems[0])

    def test_con_la_dependencia_en_otro_archivo_se_instalan_juntos(self):
        base = self.pack("base")
        p = self.pack("p", requires={"base": ">=1.0,<2"})
        plan = self.inspect([p, base])
        self.assertTrue(plan.ok, plan.view())
        self.assertEqual(plan.items[0].requires[0]["state"], "en otro archivo")
        pack_install.install(plan)
        reg = packs.load(self.origins(), log=lambda m: None)
        self.assertEqual(sorted(reg), ["base.b", "p.b"])

    def test_una_dependencia_instalada_de_otra_version_no_vale(self):
        pack_install.install(self.inspect([self.pack("base", version="2.0.0")]))
        plan = self.inspect([self.pack("p", requires={"base": ">=1.0,<2"})])
        self.assertFalse(plan.ok)
        self.assertEqual(plan.items[0].requires[0], {"id": "base", "spec": ">=1.0,<2",
                                                     "state": "instalado", "version": "2.0.0"})

    def test_si_uno_falla_no_se_instala_ninguno(self):
        malo = bad_zip(self.out / "malo.bppack", {"q/../x": "x"})
        plan = self.inspect([self.pack("p"), malo])
        self.assertFalse(plan.ok)
        self.assertEqual(plan.items[0].problems, [])
        with self.assertRaises(ValueError):
            pack_install.install(plan)
        self.assertEqual(self.installed(), [])

    def test_sustituye_y_nunca_deja_las_dos(self):
        pack_install.install(self.inspect([self.pack("p", version="1.0.0", title="Viejo")]))
        plan = self.inspect([self.pack("p", version="1.1.0", title="Nuevo")])
        self.assertEqual((plan.items[0].replaces, plan.items[0].older), ("1.0.0", False))
        pack_install.install(plan)
        self.assertEqual(self.installed(), ["p"])
        self.assertEqual(packs.read_manifest(self.user / "p").version, "1.1.0")
        # y volver a la de antes se puede, avisando (P79)
        viejo = self.out / "p-1.0.0.bppack"
        plan = self.inspect([viejo])
        self.assertEqual((plan.items[0].replaces, plan.items[0].older), ("1.1.0", True))
        pack_install.install(plan)
        self.assertEqual(packs.read_manifest(self.user / "p").version, "1.0.0")
        self.assertEqual(self.installed(), ["p"])

    def test_si_falla_un_renombrado_no_cambia_nada(self):
        pack_install.install(self.inspect([self.pack("a", title="A de antes")]))
        before = packs.digest(self.user / "a")
        plan = self.inspect([self.pack("a", version="1.1.0"), self.pack("b")])
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 3:            # a aparte, a nuevo, y al mover b: falla
                raise OSError("disco ocupado")
            return real(src, dst)

        with mock.patch.object(pack_install.os, "replace", flaky):
            with self.assertRaisesRegex(ValueError, "no se ha cambiado nada"):
                pack_install.install(plan)
        self.assertEqual(self.installed(), ["a"])
        self.assertEqual(packs.digest(self.user / "a"), before)

    def test_un_register_que_falla_no_se_instala(self):
        arch = self.pack("p", body="def register(pack):\n    raise RuntimeError('roto')\n")
        plan = self.inspect([arch])
        self.assertFalse(plan.ok)
        self.assertIn("roto", plan.items[0].problems[0])

    def test_avisa_de_lo_que_dejaria_de_cargar(self):
        pack_install.install(self.inspect([self.pack("base")]))
        pack_install.install(self.inspect([self.pack("p", requires={"base": ">=1.0,<2"})]))
        plan = self.inspect([self.pack("base", version="2.0.0")])
        self.assertTrue(plan.ok)              # se puede, pero se dice
        self.assertIn("p", plan.breaks)

    def test_si_el_workspace_lo_tiene_se_dice_que_manda_ese(self):
        pack_install.install(self.inspect([self.pack("p")], target="workspace"))
        plan = self.inspect([self.out / "p-1.0.0.bppack"], target="usuario")
        self.assertEqual(plan.items[0].shadowed_by, "workspace")

    def test_la_prueba_de_carga_va_en_otro_proceso(self):
        plan = self.inspect([self.pack("aparte", title="En otro proceso")],
                            trial=pack_install.trial_load)
        self.assertTrue(plan.ok, plan.view())
        self.assertEqual(plan.items[0].blocks, ["En otro proceso"])
        self.assertNotIn("pizarra_packs.aparte", sys.modules)
        plan.discard()


class Desinstalar(Base):
    def setUp(self):
        super().setUp()
        pack_install.install(self.inspect([self.pack("base")]))
        pack_install.install(self.inspect([self.pack("p", requires={"base": ">=1.0,<2"})]))

    def test_nunca_si_otro_cargado_lo_pide(self):
        with self.assertRaisesRegex(ValueError, "lo pide p"):
            pack_install.uninstall("base", "usuario", self.origins(), self.loaded())
        self.assertEqual(self.installed(), ["base", "p"])

    def test_quita_la_carpeta_y_luego_ya_se_puede_la_base(self):
        pack_install.uninstall("p", "usuario", self.origins(), self.loaded())
        pack_install.uninstall("base", "usuario", self.origins(), self.loaded())
        self.assertEqual(self.installed(), [])

    def test_la_copia_que_no_se_usa_si_aunque_la_pidan(self):
        pack_install.install(self.inspect([self.out / "base-1.0.0.bppack"], target="workspace"))
        pack_install.uninstall("base", "usuario", self.origins(), self.loaded())
        self.assertEqual(self.installed(), ["p"])

    def test_desarrollo_nunca_y_lo_que_no_esta_tampoco(self):
        write(self.dev, "d")
        loaded = packs.load(self.origins(dev=True), log=lambda m: None).packs
        with self.assertRaisesRegex(ValueError, "es de desarrollo"):
            pack_install.uninstall("d", "desarrollo", self.origins(dev=True), loaded)
        with self.assertRaisesRegex(ValueError, "no está instalado en workspace"):
            pack_install.uninstall("p", "workspace", self.origins(), self.loaded())
        with self.assertRaisesRegex(ValueError, "no está instalado"):
            pack_install.uninstall("../user", "usuario", self.origins(), self.loaded())


class ValidacionPorHuella(Base):
    def setUp(self):
        super().setUp()
        self.cache = Path(self.tmp.name) / "cache" / "packs-validados.json"
        write(self.user, "base")
        write(self.user, "p", requires={"base": ">=1.0,<2"})
        self.seen = []
        real = pack_validate.validate

        def counting(folder, find=None, scans=None, **kw):
            self.seen.append(Path(folder).name)
            return real(folder, find, scans, **kw)

        patcher = mock.patch.object(pack_validate, "validate", counting)
        patcher.start()
        self.addCleanup(patcher.stop)

    def load(self):
        self.seen.clear()
        return packs.load([("usuario", self.user)], log=lambda m: None, validated=self.cache)

    def test_la_misma_clave_no_se_vuelve_a_validar(self):
        self.assertEqual(sorted(self.load()), ["base.b", "p.b"])
        self.assertEqual(sorted(self.seen), ["base", "p"])
        self.assertEqual(sorted(self.load()), ["base.b", "p.b"])
        self.assertEqual(self.seen, [])

    def test_si_cambia_un_fichero_suyo_o_de_lo_que_pide_se_valida(self):
        self.load()
        with open(self.user / "p" / "blocks.py", "a", encoding="utf-8") as f:
            f.write("\n# cambio\n")
        self.load()
        self.assertEqual(self.seen, ["p"])
        with open(self.user / "base" / "blocks.py", "a", encoding="utf-8") as f:
            f.write("\n# cambio\n")
        self.load()
        self.assertEqual(sorted(self.seen), ["base", "p"])

    def test_uno_que_no_paso_nunca_se_carga_por_la_cache(self):
        (self.user / "p" / "blocks.py").write_text(
            "import numpy\ndef register(pack):\n    pass\n", encoding="utf-8")
        for _ in range(2):
            reg = self.load()
            self.assertNotIn("p.b", reg)
            self.assertIn("p", self.seen)
            self.assertIn("no pasa la validación", reg.packs[1].error)

    def test_otra_version_de_las_reglas_vuelve_a_validar(self):
        self.load()
        with mock.patch.object(packs, "_rules", ["otras reglas"]):
            self.load()
        self.assertEqual(sorted(self.seen), ["base", "p"])

    def test_una_cache_rota_es_una_cache_vacia(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text("{no es json", encoding="utf-8")
        self.assertEqual(sorted(self.load()), ["base.b", "p.b"])
        self.assertEqual(len(json.loads(self.cache.read_text(encoding="utf-8"))["ok"]), 2)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(DEPS, "faltan fastapi/uvicorn/websockets")
class Rutas(unittest.TestCase):
    """Las rutas de *Ajustes → Paquetes* con el servidor de verdad: instalar recarga el registro
    y las pizarras abiertas reciben el catálogo nuevo."""

    @classmethod
    def setUpClass(cls):
        cls.saved = blocks_mod.REGISTRY
        cls.tmp = Path(tempfile.mkdtemp())
        cls.src, cls.out = cls.tmp / "src", cls.tmp / "out"
        cls.src.mkdir()
        cls.archive = pack_install.export(write(cls.src, "nuevo", title="Recién llegado"),
                                          cls.out)
        start = bootstrap(cls.tmp / "settings.toml", cls.tmp / "Documentos" / "Personal", ())
        cls.project = start.workspace.create_project("", "Proyecto").id
        start.settings.language = "es"        # los mensajes que se comprueban, en español (O16)
        with mock.patch.dict(os.environ, {packs.DEV_ENV: ""}):     # con el trabajador (P89)
            app = create_app(start, worker_spec=pack_host.default_spec(stderr=subprocess.DEVNULL))
        cls.port = _free_port()
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port,
                                                   log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        t0 = time.time()
        while not cls.server.started and time.time() - t0 < 10:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        blocks_mod.REGISTRY.host.close()
        blocks_mod.REGISTRY = cls.saved

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def test_subir_resumen_instalar_y_la_pizarra_lo_recibe(self):
        st, got = self.call("GET", "/api/packs")
        self.assertEqual(st, 200)
        self.assertEqual(set(got["targets"]), {"usuario", "workspace"})
        self.assertNotIn("nuevo", [p["id"] for p in got["packs"]])
        with connect(f"ws://127.0.0.1:{self.port}/ws?project={self.project}",
                     open_timeout=5) as ws:
            json.loads(ws.recv(timeout=10))                       # init
            st, up = self.call("POST", "/api/packs/uploads?name=nuevo-1.0.0.bppack",
                               raw=self.archive.read_bytes())
            self.assertEqual(st, 200)
            st, plan = self.call("POST", "/api/packs/inspect",
                                 {"paths": [up["path"]], "target": "usuario"})
            self.assertEqual(st, 200)
            self.assertTrue(plan["ok"], plan)
            self.assertEqual(plan["items"][0]["blocks"], ["Recién llegado"])
            st, done = self.call("POST", "/api/packs/install", {"token": plan["token"]})
            self.assertEqual(st, 200)
            self.assertEqual(done["installed"], ["nuevo"])
            mine = next(p for p in done["packs"] if p["id"] == "nuevo")
            self.assertEqual((mine["origin"], mine["removable"], mine["code"]),
                             ("usuario", True, True))
            t0 = time.time()
            while time.time() - t0 < 10:
                msg = json.loads(ws.recv(timeout=10))
                if msg.get("type") == "init":
                    break
            self.assertIn("nuevo.b", msg["types"])
        # el mismo resumen no se instala dos veces
        st, _ = self.call("POST", "/api/packs/install", {"token": plan["token"]})
        self.assertEqual(st, 404)
        # exportar lo instalado da la misma huella
        dest = self.tmp / "exportado"
        st, got = self.call("POST", "/api/packs/nuevo/export", {"folder": str(dest)})
        self.assertEqual(st, 200)
        self.assertEqual(Path(got["path"]).name, "nuevo-1.0.0.bppack")
        self.assertEqual(Path(got["path"]).read_bytes(), self.archive.read_bytes())
        st, _ = self.call("POST", "/api/packs/nuevo/uninstall", {"origin": "usuario"})
        self.assertEqual(st, 200)
        self.assertNotIn("nuevo.b", blocks_mod.REGISTRY)

    def test_un_paquete_que_no_esta_no_se_exporta(self):
        st, _ = self.call("POST", "/api/packs/nada/export", {"folder": str(self.out)})
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
