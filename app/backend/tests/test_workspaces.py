"""La lista de workspaces: crear, abrir y quitar (docs/PLAN_WORKSPACES.md §3, §6, W3, W7).

Lo que protegen, regla a regla:
- la lista enseña todos los de `settings.toml`, marca el abierto y el que no se encuentra;
- quitar uno de la lista nunca borra su carpeta, y el abierto no se puede quitar (W7);
- abrir una carpeta movida con el mismo id la reconoce y no duplica la entrada; abrir una
  copia (el mismo id con la otra en su sitio) se rechaza: mezclaría sus recientes;
- abrir una carpeta que no existe, o que no es un workspace, se rechaza con el motivo;
- crear uno vacío crea la carpeta con su `workspace.toml`, lo añade a la lista como el actual
  y no toca el workspace de antes;
- un nombre vacío o repetido, o una carpeta que ya es otro workspace (o está dentro de uno),
  se rechazan con el motivo y sin escribir nada;
- las rutas contestan antes de rearrancar (W3): primero la respuesta, después `restart()`;
- por la API se crea desde una plantilla o desde el token de un perfil inspeccionado hacia
  un workspace nuevo (W4), y ese token no sustituye el perfil del abierto.

Ejecutar desde app/backend:  python -m unittest tests.test_workspaces -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pizarra import workspaces
from pizarra.settings import Settings
from pizarra.startup import bootstrap
from pizarra.storage import Conflict, InvalidName, LocalWorkspace, NotFound


def _tree(root):
    return sorted((str(p.relative_to(root)), p.read_bytes() if p.is_file() else b"")
                  for p in Path(root).rglob("*"))


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings_path = self.tmp / "settings.toml"
        self.docs = self.tmp / "Documentos" / "BoardPrint"
        self.start = bootstrap(self.settings_path, self.docs / "Personal", ())
        self.settings = self.start.settings
        self.ws = self.start.workspace             # el abierto: «Personal»

    def otro(self, name, path=None):
        """Un workspace más en la lista, como si se hubiera abierto antes."""
        ws = LocalWorkspace.open(path or self.tmp / name, name=name)
        self.settings.add_workspace(ws.info().id, name, ws.root)
        return ws

    def ids(self):
        return [w["id"] for w in self.settings.workspaces()]


class LaLista(_Tmp):
    def test_ensena_todos_marca_el_abierto_y_el_que_no_se_encuentra(self):
        trabajo = self.otro("Trabajo")
        perdido = self.otro("Perdido")
        shutil.rmtree(perdido.root)
        got = {w["id"]: w for w in workspaces.listing(self.settings, self.ws)}
        self.assertEqual(set(got), {self.ws.info().id, trabajo.info().id, perdido.info().id})
        self.assertEqual({k for k, w in got.items() if w["abierto"]}, {self.ws.info().id})
        self.assertEqual({k for k, w in got.items() if w["falta"]}, {perdido.info().id})
        t = got[trabajo.info().id]
        self.assertEqual((t["nombre"], Path(t["ruta"])), ("Trabajo", trabajo.root))

    def test_sin_workspace_abierto_ninguno_sale_abierto(self):
        self.otro("Trabajo")
        self.assertFalse(any(w["abierto"] for w in workspaces.listing(self.settings, None)))


class Quitar(_Tmp):
    def test_quitar_nunca_borra_su_carpeta(self):
        trabajo = self.otro("Trabajo")
        trabajo.create_project("", "Pinza")
        antes = _tree(trabajo.root)
        workspaces.remove(self.settings, trabajo.info().id, self.ws)
        self.assertNotIn(trabajo.info().id, self.ids())
        self.assertEqual(_tree(trabajo.root), antes)

    def test_el_abierto_no_se_puede_quitar(self):
        with self.assertRaises(Conflict):
            workspaces.remove(self.settings, self.ws.info().id, self.ws)
        self.assertIn(self.ws.info().id, self.ids())

    def test_uno_que_no_se_encuentra_se_quita(self):
        perdido = self.otro("Perdido")
        shutil.rmtree(perdido.root)
        workspaces.remove(self.settings, perdido.info().id, self.ws)
        self.assertNotIn(perdido.info().id, self.ids())

    def test_uno_que_no_esta_en_la_lista_es_not_found(self):
        with self.assertRaises(NotFound):
            workspaces.remove(self.settings, "no-existe", self.ws)

    def test_quitar_el_actual_sin_abierto_no_deja_un_actual_que_no_esta(self):
        # la carpeta del actual falta al arrancar (sin workspace abierto): se puede quitar
        trabajo = self.otro("Trabajo")
        actual = self.settings.current_workspace()["id"]
        workspaces.remove(self.settings, actual, None)
        self.assertEqual(self.settings.current_workspace()["id"], trabajo.info().id)
        self.assertNotEqual(self.settings.data.get("current_workspace"), actual)


class Abrir(_Tmp):
    def test_por_id_lo_deja_como_el_actual(self):
        trabajo = self.otro("Trabajo")
        info = workspaces.open_existing(self.settings, ws_id=trabajo.info().id)
        self.assertEqual(info.id, trabajo.info().id)
        self.assertEqual(self.settings.current_workspace()["id"], trabajo.info().id)

    def test_una_carpeta_movida_con_el_mismo_id_se_reconoce_y_no_se_duplica(self):
        trabajo = self.otro("Trabajo")
        nueva = self.tmp / "Movida" / "Trabajo"
        nueva.parent.mkdir()
        shutil.move(str(trabajo.root), str(nueva))
        info = workspaces.open_existing(self.settings, ruta=str(nueva))
        self.assertEqual(info.id, trabajo.info().id)
        self.assertEqual(self.ids().count(trabajo.info().id), 1)
        self.assertEqual(len(self.ids()), 2)
        self.assertEqual(Path(self.settings.workspace(info.id)["path"]), nueva)

    def test_una_carpeta_que_ya_es_workspace_y_no_estaba_se_anade(self):
        equipo = LocalWorkspace.open(self.tmp / "Equipo", name="Equipo")
        info = workspaces.open_existing(self.settings, ruta=str(equipo.root))
        self.assertEqual((info.id, info.name), (equipo.info().id, "Equipo"))
        self.assertIn(equipo.info().id, self.ids())
        self.assertEqual(self.settings.current_workspace()["id"], equipo.info().id)

    def test_una_copia_con_el_mismo_id_y_la_otra_en_su_sitio_se_rechaza(self):
        trabajo = self.otro("Trabajo")
        copia = self.tmp / "Copia de Trabajo"
        shutil.copytree(trabajo.root, copia)
        with self.assertRaises(Conflict):
            workspaces.open_existing(self.settings, ruta=str(copia))
        self.assertEqual(Path(self.settings.workspace(trabajo.info().id)["path"]), trabajo.root)

    def test_una_carpeta_que_no_existe_o_no_es_workspace_se_rechaza(self):
        vacia = self.tmp / "Vacia"
        vacia.mkdir()
        antes = list(self.settings.workspaces())
        for ruta in (str(self.tmp / "No existe"), str(vacia), "relativa"):
            with self.assertRaises(InvalidName, msg=ruta):
                workspaces.open_existing(self.settings, ruta=ruta)
        self.assertFalse((vacia / "workspace.toml").exists())
        self.assertFalse((self.tmp / "No existe").exists())
        self.assertEqual(self.settings.workspaces(), antes)

    def test_un_id_que_no_esta_o_cuya_carpeta_falta_se_rechaza(self):
        with self.assertRaises(NotFound):
            workspaces.open_existing(self.settings, ws_id="no-existe")
        perdido = self.otro("Perdido")
        shutil.rmtree(perdido.root)
        with self.assertRaises(Conflict):
            workspaces.open_existing(self.settings, ws_id=perdido.info().id)
        self.assertFalse(perdido.root.exists())       # nunca se recrea vacía


class CrearVacio(_Tmp):
    def test_crea_la_carpeta_lo_anade_como_el_actual_y_no_toca_el_de_antes(self):
        self.ws.create_project("", "Brazo")
        antes = _tree(self.ws.root)
        info, perfil = workspaces.create(self.settings, "Trabajo", base=self.docs)
        root = self.docs / "Trabajo"
        self.assertIsNone(perfil)
        self.assertTrue((root / "workspace.toml").is_file())
        self.assertEqual(LocalWorkspace.open(root).info(), info)
        self.assertEqual(info.name, "Trabajo")
        self.assertEqual(_tree(self.ws.root), antes)
        s = Settings.load(self.settings_path)       # ya guardado
        self.assertEqual(s.current_workspace()["id"], info.id)
        self.assertEqual(len(s.workspaces()), 2)

    def test_en_la_carpeta_que_se_elige(self):
        info, _ = workspaces.create(self.settings, "Equipo", ruta=str(self.tmp / "D" / "Equipo"))
        self.assertTrue((self.tmp / "D" / "Equipo" / "workspace.toml").is_file())
        self.assertEqual(Path(self.settings.workspace(info.id)["path"]), self.tmp / "D" / "Equipo")

    def test_un_nombre_vacio_o_repetido_se_rechaza_sin_escribir(self):
        for nombre, exc in (("", InvalidName), ("   ", InvalidName),
                            ("personal", Conflict), ("Personal ", Conflict)):
            with self.assertRaises(exc, msg=repr(nombre)) as e:
                workspaces.create(self.settings, nombre, ruta=str(self.tmp / "X"))
            self.assertTrue(str(e.exception))
        self.assertFalse((self.tmp / "X").exists())
        self.assertEqual(len(self.ids()), 1)

    def test_una_carpeta_que_ya_es_otro_workspace_se_rechaza(self):
        suelto = LocalWorkspace.open(self.tmp / "Suelto", name="Suelto")   # no está en la lista
        for ruta in (self.ws.root, suelto.root):
            antes = _tree(ruta)
            with self.assertRaises(Conflict, msg=ruta):
                workspaces.create(self.settings, "Nuevo", ruta=str(ruta))
            self.assertEqual(_tree(ruta), antes)
        self.assertEqual(len(self.ids()), 1)

    def test_dentro_de_otro_workspace_o_conteniendolo_se_rechaza(self):
        for ruta in (self.ws.root / "Sub", self.docs):
            with self.assertRaises(Conflict, msg=ruta):
                workspaces.create(self.settings, "Nuevo", ruta=str(ruta))
        self.assertFalse((self.ws.root / "Sub").exists())

    def test_sin_carpeta_ni_carpeta_base_se_rechaza(self):
        with self.assertRaises(InvalidName):
            workspaces.create(self.settings, "Trabajo")

    def test_desde_algo_que_no_se_entiende_se_rechaza(self):
        with self.assertRaises(InvalidName):
            workspaces.create(self.settings, "Trabajo", base=self.docs, desde="cualquier cosa")
        self.assertFalse((self.docs / "Trabajo").exists())


try:
    import uvicorn
    from pizarra.server import create_app
    DEPS = True
except ImportError:                     # job básico del CI: solo biblioteca estándar
    DEPS = False


@unittest.skipUnless(DEPS, "faltan fastapi/uvicorn")
class LasRutas(unittest.TestCase):
    """`/api/workspaces`: la lista, crear, abrir y quitar, con el rearranque después de contestar."""

    def setUp(self):
        import socket
        import threading
        import time
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.tmp = Path(tempfile.mkdtemp())
        self.docs = self.tmp / "Documentos" / "BoardPrint"
        start = bootstrap(self.tmp / "settings.toml", self.docs / "Personal", ())
        start.settings.language = "es"
        self.ws, self.settings = start.workspace, start.settings
        self.restarts = []
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(start, restart=lambda: self.restarts.append(1)), host="127.0.0.1",
            port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        t0 = time.time()
        while not self.server.started and time.time() - t0 < 10:
            time.sleep(0.05)

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        shutil.rmtree(self.tmp, ignore_errors=True)

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

    def test_la_lista_y_la_carpeta_base(self):
        code, got = self.api("GET", "/api/workspaces")
        self.assertEqual(code, 200)
        self.assertEqual(Path(got["carpeta_base"]), self.docs)
        self.assertEqual([(w["nombre"], w["abierto"], w["falta"]) for w in got["workspaces"]],
                         [("Personal", True, False)])

    def test_crear_contesta_y_luego_rearranca(self):
        code, got = self.api("POST", "/api/workspaces", {"nombre": "Trabajo"})
        self.assertEqual(code, 200, got)
        self.assertEqual((got["reinicio"], got["workspace"]["nombre"]), (True, "Trabajo"))
        self.assertEqual(Path(got["workspace"]["ruta"]), self.docs / "Trabajo")
        self.assertEqual(self.restarts, [1])
        self.assertEqual(Settings.load(self.tmp / "settings.toml").current_workspace()["id"],
                         got["workspace"]["id"])
        code, err = self.api("POST", "/api/workspaces", {"nombre": "trabajo"})
        self.assertEqual(code, 409)
        self.assertIn("trabajo", err["detail"].lower())
        self.assertEqual(self.api("POST", "/api/workspaces", {"nombre": ""})[0], 422)
        self.assertEqual(self.restarts, [1])

    def test_abrir_por_id_o_por_carpeta_y_el_abierto_no_rearranca(self):
        otro = LocalWorkspace.open(self.tmp / "Equipo", name="Equipo")
        code, got = self.api("POST", "/api/workspaces/abrir", {"ruta": str(otro.root)})
        self.assertEqual((code, got["reinicio"], got["workspace"]["id"]),
                         (200, True, otro.info().id))
        code, got = self.api("POST", "/api/workspaces/abrir", {"id": self.ws.info().id})
        self.assertEqual((code, got["reinicio"]), (200, False))      # ya es el abierto
        self.assertEqual(self.restarts, [1])
        self.assertEqual(self.api("POST", "/api/workspaces/abrir",
                                  {"ruta": str(self.tmp / "No existe")})[0], 422)
        self.assertEqual(self.api("POST", "/api/workspaces/abrir", {"id": "no-existe"})[0], 404)
        self.assertEqual(self.api("POST", "/api/workspaces/abrir", {})[0], 422)

    def test_crear_desde_una_plantilla_o_desde_un_perfil_inspeccionado(self):
        code, got = self.api("GET", "/api/profile/templates")
        self.assertEqual(code, 200)
        rob = next(t for t in got["plantillas"] if t["id"] == "robotica")
        self.assertTrue(rob["generica"])
        self.assertEqual(rob["titulo"], "Robótica: terminales y brazos")
        code, got = self.api("POST", "/api/workspaces",
                             {"nombre": "Taller", "desde": "plantilla:robotica"})
        self.assertEqual(code, 200, got)
        self.assertEqual((got["perfil"]["fabricacion"], got["perfil"]["copia"]), (True, None))
        self.assertIsNotNone(LocalWorkspace.open(self.docs / "Taller").load_manufacturing_profile())
        # un perfil: exportar el de Personal, inspeccionarlo hacia uno nuevo y crear con su token
        self.ws.save_manufacturing_profile("# Personal\n")
        out = self.tmp / "salida"
        out.mkdir()
        exp = self.api("POST", "/api/profile/export", {"carpeta": str(out)})[1]
        inspect = {"ruta": exp["file"], "destino": "nuevo"}
        code, plan = self.api("POST", "/api/profile/import/inspect", inspect)
        self.assertEqual((code, plan["copia"], plan["destino"]), (200, None, "nuevo"))
        # el de «nuevo» no vale para sustituir el perfil del abierto
        self.assertEqual(self.api("POST", "/api/profile/import/apply",
                                  {"token": plan["token"]})[0], 409)
        self.assertEqual(self.ws.load_manufacturing_profile(), "# Personal\n")
        plan = self.api("POST", "/api/profile/import/inspect", inspect)[1]
        code, got = self.api("POST", "/api/workspaces", {"nombre": "Copia", "desde": plan["token"]})
        self.assertEqual(code, 200, got)
        self.assertEqual(LocalWorkspace.open(self.docs / "Copia").load_manufacturing_profile(),
                         "# Personal\n")
        self.assertEqual(self.api("POST", "/api/workspaces",
                                  {"nombre": "X", "desde": "plantilla:no_existe"})[0], 422)
        self.assertEqual(self.api("POST", "/api/workspaces",
                                  {"nombre": "Y", "desde": plan["token"]})[0], 409)   # gastado
        self.assertEqual(self.api("POST", "/api/profile/import/inspect",
                                  {**inspect, "destino": "otro"})[0], 422)
        self.assertFalse((self.docs / "X").exists() or (self.docs / "Y").exists())

    def test_quitar_nunca_el_abierto(self):
        otro = LocalWorkspace.open(self.tmp / "Equipo", name="Equipo")
        self.settings.add_workspace(otro.info().id, "Equipo", otro.root)
        self.assertEqual(self.api("DELETE", f"/api/workspaces/{self.ws.info().id}")[0], 409)
        code, got = self.api("DELETE", f"/api/workspaces/{otro.info().id}")
        self.assertEqual(code, 200)
        self.assertEqual([w["nombre"] for w in got["workspaces"]], ["Personal"])
        self.assertTrue((otro.root / "workspace.toml").is_file())
        self.assertEqual(self.api("DELETE", f"/api/workspaces/{otro.info().id}")[0], 404)


if __name__ == "__main__":
    unittest.main()
