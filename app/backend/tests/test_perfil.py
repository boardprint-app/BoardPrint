"""El perfil `.zip` del workspace (docs/PLAN_LIBRERIA.md §5, §6, L8-L10; PLAN_PIZARRA D26, D27).

Lo que protegen, regla a regla:
- el zip nunca lleva ajustes, sesiones, proyectos ni rutas del disco, y sin la casilla nunca
  lleva el stock (D26);
- exportar e importar deja el perfil igual (la métrica de §8: «se importa en otra máquina
  igual»);
- importar siempre escribe antes la copia, y la copia tiene el perfil de antes entero (L9);
- un zip con rutas fuera, un enlace o un `esquema` mayor no escribe nada (L10);
- una ficha que no vale no impide las demás y sale en el resumen (L10);
- aplicar con el zip cambiado da `Conflict` (409) y no escribe nada;
- importar sin stock en el zip deja el stock de ahora;
- hacia un workspace nuevo (PLAN_WORKSPACES W4), el nuevo tiene exactamente lo que trae el zip,
  sin copia previa, y el de antes no cambia; un token de otro fichero o de otro destino se
  rechaza, y un nombre que no vale al crear no gasta el token.
"""
import json
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from pizarra import pack_install, profile_zip
from pizarra.storage import Conflict, LocalWorkspace
from pizarra.validation import ValidationError

FICHA_RED = """[meta]
key = "RED-1"
type = "reducer"
kind = "planetary"
manufacturer = "Fabricante"
status = "verified"

[values]
ratio = { v = 50, src = "p. 1" }
"""
FICHA_MG = '[meta]\nkey = "MG-200"\ntype = "muelle_gas"\nstatus = "unverified"\n# comentario\n'
FICHA_ROTA = "[meta]\nkey = 'ROTA'\n"          # sin type ni status
FABRICACION = "# Máquinas\n- Fresadora 3 ejes ±0,05 mm\n"
STOCK = {"RED-1": {"cantidad": 4, "ubicacion": "A-3", "fecha": "2026-11-01", "nota": ""},
         "SOLO-STOCK": {"cantidad": None, "ubicacion": "", "fecha": "", "nota": "pedir"}}


def _perfil(ws):
    """Lo que es «el perfil» de un workspace: fabricación, fichas y stock."""
    return (ws.load_manufacturing_profile(), ws.list_library_fichas(), ws.load_stock())


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = self.tmp / "salida"
        self.out.mkdir()
        self.trashed = []

    def workspace(self, name):
        def trash(p):
            self.trashed.append(Path(p).name)
            Path(p).unlink()
        return LocalWorkspace.open(self.tmp / name, trash=trash)

    def lleno(self, name="Taller"):
        ws = self.workspace(name)
        ws.save_manufacturing_profile(FABRICACION)
        ws.save_library_ficha("RED-1", "reducer", FICHA_RED)
        ws.save_library_ficha("MG-200", "muelle_gas", FICHA_MG)
        ws.save_stock(STOCK)
        return ws

    def zip_a_mano(self, entries, name="a_mano.zip", links=()):
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as z:
            for rel, data in entries.items():
                zi = zipfile.ZipInfo(rel)
                if rel in links:
                    zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(zi, data)
        return path

    MANIFEST = 'esquema = 1\napp = "0.1.0"\nfecha = "2026-11-18"\n'


class Exportar(_Base):
    def test_el_zip_nunca_lleva_ajustes_sesiones_proyectos_ni_rutas(self):
        ws = self.lleno()
        p = ws.create_project("", "Brazo")
        ws.save_scene(p.id, [{"id": "a", "version": 1}])
        ws.append_agent_chat(p.id, [{"kind": "user", "text": "diseña"}])
        (ws.root / "settings.toml").write_text('api_key = "sk-ant-xxx"\n', encoding="utf-8")
        got = profile_zip.export(ws, self.out, con_stock=True, app="0.1.0")
        self.assertEqual(Path(got["file"]).name, got["nombre"])
        self.assertRegex(got["nombre"], r"^Taller-perfil-\d{4}-\d{2}-\d{2}\.zip$")
        with zipfile.ZipFile(got["file"]) as z:
            names = z.namelist()
            blobs = b"".join(z.read(n) for n in names)
        self.assertEqual(sorted(names), sorted([
            "perfil/manifest.toml", "perfil/fabricacion.md", "perfil/library/reducers/RED-1.toml",
            "perfil/library/muelle_gass/MG-200.toml", "perfil/library/stock.csv"]))
        for n in names:
            self.assertFalse(n.startswith("/") or ":" in n or "\\" in n, n)
        for secreto in (str(ws.root), str(self.tmp), "sk-ant", p.id, "Brazo", "diseña"):
            self.assertNotIn(secreto.encode("utf-8"), blobs, secreto)

    def test_sin_la_casilla_nunca_lleva_el_stock(self):
        ws = self.lleno()
        got = profile_zip.export(ws, self.out)
        with zipfile.ZipFile(got["file"]) as z:
            self.assertNotIn("perfil/library/stock.csv", z.namelist())
            manifest = z.read("perfil/manifest.toml").decode("utf-8")
        self.assertIsNone(got["stock"])
        self.assertIn("stock = false", manifest)

    def test_dos_veces_el_mismo_dia_da_los_mismos_bytes(self):
        ws = self.lleno()
        (self.out / "a").mkdir()
        (self.out / "b").mkdir()
        a = Path(profile_zip.export(ws, self.out / "a", True)["file"]).read_bytes()
        b = Path(profile_zip.export(ws, self.out / "b", True)["file"]).read_bytes()
        self.assertEqual(a, b)

    def test_una_ficha_que_no_vale_no_se_exporta_y_lo_dice(self):
        ws = self.lleno()
        ws.save_library_ficha("ROTA", "reducer", FICHA_ROTA)
        got = profile_zip.export(ws, self.out)
        self.assertEqual((got["fichas"], got["omitidas"]), (2, ["ROTA"]))

    def test_a_una_carpeta_que_no_existe_no_escribe(self):
        with self.assertRaises(ValidationError):
            profile_zip.export(self.lleno(), self.tmp / "no" / "existe")


class Importar(_Base):
    def exportado(self, con_stock=True):
        return profile_zip.export(self.lleno("Origen"), self.out, con_stock)["file"]

    def test_exportar_e_importar_deja_el_perfil_igual(self):
        origen = self.lleno("Origen")
        zip_ = profile_zip.export(origen, self.out, con_stock=True)["file"]
        destino = self.workspace("Destino")
        destino.save_manufacturing_profile("otro taller")
        destino.save_library_ficha("VIEJA", "reducer", FICHA_RED.replace("RED-1", "VIEJA"))
        destino.save_stock({"VIEJA": {"cantidad": 1, "ubicacion": "", "fecha": "", "nota": ""}})
        plan = profile_zip.plan(destino, zip_)
        self.assertEqual((plan["fichas"], plan["stock"], plan["fabricacion"], plan["invalid"]),
                         (2, 2, True, []))
        self.assertEqual(plan["sustituye"]["quitadas"], ["VIEJA"])
        done = profile_zip.apply(destino, plan["token"])
        self.assertEqual(_perfil(destino), _perfil(origen))
        self.assertEqual((done["fichas"], done["quitadas"]), (2, 1))

    def test_importar_siempre_escribe_antes_la_copia_con_el_perfil_de_antes(self):
        destino = self.lleno("Destino")
        destino.save_library_ficha("ROTA", "reducer", FICHA_ROTA)
        antes = _perfil(destino)
        zip_ = profile_zip.export(self.workspace("Vacio"), self.out)["file"]   # sin nada
        copias = destino.profile_copy_dir()
        visto = []
        for name in ("save_manufacturing_profile", "save_library_ficha", "save_stock",
                     "trash_library_ficha"):
            real = getattr(destino, name)

            def spy(*a, _real=real, **k):
                visto.append(any(copias.glob("*.zip")) if copias.is_dir() else False)
                return _real(*a, **k)
            setattr(destino, name, spy)
        done = profile_zip.apply(destino, profile_zip.plan(destino, zip_)["token"])
        self.assertTrue(visto and all(visto), visto)       # quitó las tres fichas
        copia = Path(done["copia"])
        self.assertEqual(copia.parent, copias)
        leido = profile_zip.read(copia)
        self.assertEqual(leido["fabricacion"], antes[0])
        self.assertEqual({k: t for k, (_, t) in leido["fichas"].items()},
                         {k: v for k, v in antes[1].items() if k != "ROTA"})
        self.assertEqual(leido["stock"], antes[2])
        self.assertEqual([i["clave"] for i in leido["invalid"]], ["ROTA"])  # también va, aparte
        # el perfil vacío no trae fabricación ni stock: se quedan; las fichas se van
        self.assertEqual(_perfil(destino), (antes[0], {}, antes[2]))

    def test_la_copia_no_sale_como_carpeta_ni_en_la_libreria(self):
        destino = self.lleno("Destino")
        profile_zip.apply(destino, profile_zip.plan(destino, self.exportado())["token"])
        self.assertEqual(destino.tree().children, [])
        self.assertEqual(set(destino.list_library_fichas()), {"RED-1", "MG-200"})

    def test_un_zip_con_rutas_fuera_un_enlace_o_un_esquema_mayor_no_escribe_nada(self):
        destino = self.lleno("Destino")
        antes = _perfil(destino)
        malos = {
            "ruta fuera": self.zip_a_mano({"perfil/manifest.toml": self.MANIFEST,
                                           "perfil/../../fuera.toml": FICHA_MG}, "fuera.zip"),
            "absoluta": self.zip_a_mano({"perfil/manifest.toml": self.MANIFEST,
                                         "/etc/fabricacion.md": "x"}, "abs.zip"),
            "enlace": self.zip_a_mano({"perfil/manifest.toml": self.MANIFEST,
                                       "perfil/library/reducers/RED-1.toml": "/etc/passwd"},
                                      "enlace.zip", links={"perfil/library/reducers/RED-1.toml"}),
            "esquema mayor": self.zip_a_mano({"perfil/manifest.toml": "esquema = 2\n",
                                              "perfil/fabricacion.md": "nuevo"}, "e2.zip"),
            "sin manifiesto": self.zip_a_mano({"perfil/fabricacion.md": "nuevo"}, "sin.zip"),
            "no es un zip": self.tmp / "texto.zip",
        }
        malos["no es un zip"].write_text("hola", encoding="utf-8")
        for caso, path in malos.items():
            with self.assertRaises(ValidationError, msg=caso):
                profile_zip.plan(destino, path)
        self.assertEqual(_perfil(destino), antes)
        self.assertFalse(destino.profile_copy_dir().exists())

    def test_una_ficha_que_no_vale_no_impide_las_demas_y_sale_en_el_resumen(self):
        destino = self.workspace("Destino")
        path = self.zip_a_mano({
            "perfil/manifest.toml": self.MANIFEST,
            "perfil/library/reducers/RED-1.toml": FICHA_RED,
            "perfil/library/reducers/ROTA.toml": FICHA_ROTA,
            "perfil/library/reducers/MG-200.toml": FICHA_MG,          # otro tipo en la carpeta
            "perfil/library/gears/red-1.toml": FICHA_RED.replace("RED-1", "red-1")
                                                        .replace("reducer", "gear"),
            "perfil/library/reducers/con espacio.toml": FICHA_RED,
            "perfil/otra_cosa.txt": "se ignora",
        })
        plan = profile_zip.plan(destino, path)
        self.assertEqual(plan["fichas"], 1)
        # una clave que viene dos veces (sin mirar mayúsculas): vale la primera por ruta
        self.assertEqual(sorted(i["clave"] for i in plan["invalid"]),
                         sorted(["ROTA", "MG-200", "RED-1", "con espacio"]))
        self.assertTrue(all(i["motivo"] for i in plan["invalid"]))
        self.assertEqual(plan["ignored"], ["otra_cosa.txt"])
        profile_zip.apply(destino, plan["token"])
        self.assertEqual(set(destino.list_library_fichas()), {"red-1"})

    def test_aplicar_con_el_zip_cambiado_da_conflict_y_no_escribe(self):
        destino = self.lleno("Destino")
        antes = _perfil(destino)
        zip_ = Path(self.exportado(con_stock=False))
        plan = profile_zip.plan(destino, zip_)
        otro = self.workspace("Otro")
        otro.save_manufacturing_profile("cambiado")
        shutil.copy(profile_zip.export(otro, self.tmp)["file"], zip_)
        with self.assertRaises(Conflict):
            profile_zip.apply(destino, plan["token"])
        self.assertEqual(_perfil(destino), antes)
        self.assertFalse(destino.profile_copy_dir().exists())
        with self.assertRaises(Conflict):            # un token se usa una vez
            profile_zip.apply(destino, plan["token"])

    def test_importar_sin_stock_en_el_zip_deja_el_stock_de_ahora(self):
        destino = self.workspace("Destino")
        mio = {"MIO": {"cantidad": 7, "ubicacion": "B", "fecha": "", "nota": ""}}
        destino.save_stock(mio)
        plan = profile_zip.plan(destino, self.exportado(con_stock=False))
        self.assertIsNone(plan["stock"])
        profile_zip.apply(destino, plan["token"])
        self.assertEqual(destino.load_stock(), mio)
        self.assertEqual(set(destino.list_library_fichas()), {"RED-1", "MG-200"})

    def test_una_clave_que_solo_cambia_de_mayusculas_queda_la_del_zip(self):
        # en Windows `abc.toml` y `ABC.toml` son el mismo fichero: nunca se pierde la que llega
        destino = self.workspace("Destino")
        destino.save_library_ficha("red-1", "reducer", FICHA_RED.replace("RED-1", "red-1"))
        profile_zip.apply(destino, profile_zip.plan(destino, self.exportado())["token"])
        self.assertEqual(set(destino.list_library_fichas()), {"RED-1", "MG-200"})
        self.assertEqual(destino.load_library_ficha("RED-1"), FICHA_RED)


PROVEEDORES = 'esquema = 1\n[[proveedor]]\nnombre = "Tienda"\ndominio = "tienda.example"\n'


class HaciaUnWorkspaceNuevo(_Base):
    """Destino «nuevo» (PLAN_WORKSPACES W4, §6): nada que sustituir y sin copia previa; el
    token se ata al fichero y al destino."""

    def origen(self):
        ws = self.lleno("Origen")
        ws.save_providers_text(PROVEEDORES)
        return ws

    def test_el_nuevo_tiene_exactamente_lo_del_zip_sin_copia_y_el_de_antes_no_cambia(self):
        origen = self.origen()
        zip_ = profile_zip.export(origen, self.out, con_stock=True)["file"]
        actual = self.workspace("Actual")
        actual.save_manufacturing_profile("el de ahora")
        antes = _perfil(actual)
        plan = profile_zip.plan(None, zip_, destino="nuevo")
        self.assertEqual(plan["sustituye"], {"fichas": 0, "quitadas": [], "fabricacion": False,
                                             "stock": 0})
        self.assertIsNone(plan["copia"])
        self.assertEqual((plan["destino"], plan["fichas"], plan["stock"]), ("nuevo", 2, 2))
        nuevo = self.workspace("Nuevo")
        done = profile_zip.apply(nuevo, plan["token"], destino="nuevo")
        self.assertIsNone(done["copia"])
        self.assertEqual(_perfil(nuevo), _perfil(origen))
        self.assertEqual(nuevo.load_providers_text(), PROVEEDORES)
        self.assertFalse(nuevo.profile_copy_dir().exists())
        self.assertEqual(_perfil(actual), antes)

    def test_sin_stock_en_el_zip_el_nuevo_no_tiene_stock(self):
        zip_ = profile_zip.export(self.origen(), self.out)["file"]
        nuevo = self.workspace("Nuevo")
        profile_zip.apply(nuevo, profile_zip.plan(None, zip_, "nuevo")["token"], "nuevo")
        self.assertEqual(nuevo.load_stock(), {})
        self.assertEqual(set(nuevo.list_library_fichas()), {"RED-1", "MG-200"})

    def test_un_token_de_otro_destino_se_rechaza(self):
        zip_ = profile_zip.export(self.origen(), self.out)["file"]
        actual = self.lleno("Actual")
        antes = _perfil(actual)
        nuevo = self.workspace("Nuevo")
        para_nuevo = profile_zip.plan(None, zip_, "nuevo")["token"]
        with self.assertRaises(Conflict):                 # el de «nuevo», sobre el actual
            profile_zip.apply(actual, para_nuevo)
        para_actual = profile_zip.plan(actual, zip_)["token"]
        with self.assertRaises(Conflict):                 # el del actual, hacia uno nuevo
            profile_zip.apply(nuevo, para_actual, "nuevo")
        otro = self.workspace("Otro")
        para_actual = profile_zip.plan(actual, zip_)["token"]
        with self.assertRaises(Conflict):                 # el de un workspace, en otro
            profile_zip.apply(otro, para_actual)
        self.assertEqual(_perfil(actual), antes)
        self.assertEqual(_perfil(nuevo), (None, {}, {}))
        self.assertEqual(_perfil(otro), (None, {}, {}))
        self.assertFalse(actual.profile_copy_dir().exists())

    def test_un_token_de_otro_fichero_se_rechaza(self):
        zip_ = Path(profile_zip.export(self.origen(), self.out)["file"])
        token = profile_zip.plan(None, zip_, "nuevo")["token"]
        otro = self.workspace("Cambiado")
        otro.save_manufacturing_profile("otro taller")
        shutil.copy(profile_zip.export(otro, self.tmp)["file"], zip_)
        nuevo = self.workspace("Nuevo")
        with self.assertRaises(Conflict):
            profile_zip.check_token(token, "nuevo")
        with self.assertRaises(Conflict):
            profile_zip.apply(nuevo, token, "nuevo")
        self.assertEqual(_perfil(nuevo), (None, {}, {}))

    def test_hacia_uno_nuevo_que_ya_tiene_perfil_no_sustituye_nada(self):
        zip_ = profile_zip.export(self.origen(), self.out)["file"]
        lleno = self.workspace("NoTanNuevo")
        lleno.save_manufacturing_profile("ya tenía")
        with self.assertRaises(Conflict):
            profile_zip.apply(lleno, profile_zip.plan(None, zip_, "nuevo")["token"], "nuevo")
        self.assertEqual(lleno.load_manufacturing_profile(), "ya tenía")

    def test_un_destino_que_no_existe_es_un_error(self):
        zip_ = profile_zip.export(self.origen(), self.out)["file"]
        with self.assertRaises(ValidationError):
            profile_zip.plan(None, zip_, "otro")

    def test_crear_un_workspace_desde_el_token_de_un_perfil(self):
        from pizarra import workspaces
        from pizarra.startup import bootstrap
        start = bootstrap(self.tmp / "settings.toml", self.tmp / "Docs" / "Personal", ())
        start.workspace.save_manufacturing_profile("el de Personal")
        origen = self.origen()
        zip_ = profile_zip.export(origen, self.out, con_stock=True)["file"]
        plan = profile_zip.plan(None, zip_, "nuevo")
        with self.assertRaises(Conflict):        # nombre repetido: no gasta el token
            workspaces.create(start.settings, "Personal", base=self.tmp / "Docs",
                              desde=plan["token"])
        info, done = workspaces.create(start.settings, "Trabajo", base=self.tmp / "Docs",
                                       desde=plan["token"])
        nuevo = LocalWorkspace.open(self.tmp / "Docs" / "Trabajo")
        self.assertEqual(nuevo.info().id, info.id)
        self.assertEqual(_perfil(nuevo), _perfil(origen))
        self.assertEqual((done["fichas"], done["stock"], done["copia"]), (2, 2, None))
        self.assertEqual(start.workspace.load_manufacturing_profile(), "el de Personal")
        self.assertEqual(start.settings.current_workspace()["id"], info.id)
        with self.assertRaises(Conflict):        # un token se usa una vez
            workspaces.create(start.settings, "Otro", base=self.tmp / "Docs", desde=plan["token"])
        self.assertFalse((self.tmp / "Docs" / "Otro").exists())


class ElZipSeAbreComoUnBppack(unittest.TestCase):
    def test_open_archive_sin_parametros_sigue_pidiendo_el_id_de_un_paquete(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "x.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Con-Mayus/pack.toml", "x")
        with self.assertRaises(ValueError) as e:
            pack_install.open_archive(path, tmp / "a")
        self.assertIn("Con-Mayus", str(e.exception))
        got = pack_install.open_archive(path, tmp / "b", top_re=None)
        self.assertEqual(got.name, "Con-Mayus")


try:
    import uvicorn
    from pizarra.server import create_app
    from pizarra.startup import bootstrap
    DEPS = True
except ImportError:                     # job básico del CI: solo biblioteca estándar
    DEPS = False


@unittest.skipUnless(DEPS, "faltan fastapi/uvicorn")
class LasRutas(unittest.TestCase):
    """`profile_api`: exportar a una carpeta dada, inspeccionar una ruta dada y aplicar."""

    @classmethod
    def setUpClass(cls):
        import socket
        import threading
        import time
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.tmp = Path(tempfile.mkdtemp())
        start = bootstrap(cls.tmp / "settings.toml", cls.tmp / "Documentos" / "Personal", (),
                          trash=lambda p: Path(p).unlink())
        start.settings.language = "es"
        cls.ws = start.workspace
        cls.server = uvicorn.Server(uvicorn.Config(create_app(start), host="127.0.0.1",
                                                   port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        t0 = time.time()
        while not cls.server.started and time.time() - t0 < 10:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def api(self, method, path, body=None):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_exportar_importar_y_el_409(self):
        self.ws.save_manufacturing_profile(FABRICACION)
        self.ws.save_library_ficha("RED-1", "reducer", FICHA_RED)
        out = self.tmp / "salida"
        out.mkdir()
        code, got = self.api("POST", "/api/profile/export", {"carpeta": str(out)})
        self.assertEqual((code, got["fichas"], got["stock"]), (200, 1, None))
        self.assertEqual(self.api("POST", "/api/profile/export",
                                  {"carpeta": str(self.tmp / "no")})[0], 422)
        self.ws.save_manufacturing_profile("cambiado")
        code, plan = self.api("POST", "/api/profile/import/inspect", {"ruta": got["file"]})
        self.assertEqual((code, plan["fichas"], plan["sustituye"]["fabricacion"]), (200, 1, True))
        self.assertEqual(self.api("POST", "/api/profile/import/inspect",
                                  {"ruta": str(self.tmp / "nada.zip")})[0], 422)
        code, done = self.api("POST", "/api/profile/import/apply", {"token": plan["token"]})
        self.assertEqual(code, 200)
        self.assertTrue(Path(done["copia"]).is_file())
        self.assertEqual(self.ws.load_manufacturing_profile(), FABRICACION)
        self.assertEqual(self.api("POST", "/api/profile/import/apply",
                                  {"token": plan["token"]})[0], 409)


if __name__ == "__main__":
    unittest.main()
