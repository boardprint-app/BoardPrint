"""Interfaz de un paquete en el backend (docs/PLAN_PAQUETES.md §5, §10 «Interfaz servida» y
«Protocolo de interfaz», P24, P40).

Reglas:
- Un fichero de `ui/` fuera de la carpeta del paquete **nunca se sirve** (ni lo de fuera de
  `ui/`, ni lo de otro paquete, ni lo de un paquete roto), y lo servido lleva **siempre** la
  CSP sin red, también la respuesta de lo que no se sirve.
- Un `action` solo llega a las acciones de **su** paquete: el del bloque desde cuya interfaz se
  llama. Un fallo de la acción, o una respuesta que no es JSON, es un error del paquete (422) y
  nunca tumba la app.
- Un `setParams` de la interfaz pasa por `Board.set_params`, como el de la tarjeta, y ahí cada
  valor **tiene el tipo del de por defecto** (P49): la interfaz de un paquete no manda
  necesariamente lo que mandaría la tarjeta. Un valor malo no deja guardado ninguno.
- Una vista o una acción mal declarada tumba el paquete entero, como cualquier declaración
  incoherente (D94).

Ejecutar desde app/backend:  python -m unittest tests.test_pack_ui -v
"""
import json
import os
import socket
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from pizarra import pack_ui, packs, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace
from pizarra.validation import ValidationError

PACKS_UI = Path(__file__).parent / "packs_ui"     # ui_prueba (con interfaz) y ui_otro

BODY = '''
from boardprint_sdk.packs import Param

def run(p, i, c):
    return {{"out": {{"x": {{"value": p["a"], "unit": "mm"}}}}}}

def accion(params, inputs, args, ctx):
    return {{"ok": True}}

def register(pack):
    pack.port("{id}.t", "t")
    pack.block("{id}.b", "B", run, params={{"a": Param(1, "mm")}}, outputs={{"out": "{id}.t"}})
{extra}
'''


def write(root, pack_id, extra="", toml=""):
    d = Path(root) / pack_id
    d.mkdir(parents=True)
    (d / "pack.toml").write_text(f'id = "{pack_id}"\nname = "{pack_id}"\nversion = "1.0.0"\n'
                                 'author = "Pruebas"\ndescription = "Paquete de prueba"\n'
                                 f'sdk = ">=1.1,<2"\n{toml}\n', encoding="utf-8")
    body = BODY.format(id=pack_id, extra=textwrap.indent(textwrap.dedent(extra), "    "))
    (d / "blocks.py").write_text(body, encoding="utf-8")
    return d


def load(*dirs):
    logs = []
    reg = packs.load([str(d) for d in dirs], log=logs.append)
    return reg, {p.id: p for p in reg.packs}


class Declaraciones(unittest.TestCase):
    """`pack.view` y `pack.action` (SDK 1.1): lo mal declarado tumba el paquete."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assert_roto(self, extra, *texto, toml=""):
        write(self.root, "roto", extra, toml)
        reg, info = load(self.root)
        err = info["roto"].error
        self.assertIsNotNone(err)
        for t in texto:
            self.assertIn(t, err)
        self.assertNotIn("roto.b", reg, "nada del paquete roto")
        self.assertFalse([a for a in reg.actions if a.startswith("roto.")])

    def test_el_paquete_de_prueba_carga_con_su_vista_y_su_accion(self):
        reg, info = load(PACKS_UI)
        self.assertIsNone(info["ui_prueba"].error)
        self.assertIsNone(info["ui_otro"].error)
        d = reg.describe()
        self.assertEqual(d["blocks"]["ui_prueba.b"]["view"], {"card": "ui", "panel": "ui"})
        p = next(p for p in d["packs"] if p["id"] == "ui_prueba")
        self.assertEqual((p["ui"], p["actions"]), ("ui/index.html", ["ui_prueba.eco"]))

    def test_sin_pack_view_la_tarjeta_de_siempre_y_sin_panel(self):
        write(self.root, "simple")
        reg, _ = load(self.root)
        self.assertEqual(reg.describe()["blocks"]["simple.b"]["view"],
                         {"card": ["params", "results"], "panel": []})

    def test_controles_genericos(self):
        write(self.root, "gen", 'pack.view("gen.b", card=["results"], panel=("params", "results"))')
        reg, info = load(self.root)
        self.assertIsNone(info["gen"].error)
        self.assertEqual(reg.describe()["blocks"]["gen.b"]["view"],
                         {"card": ["results"], "panel": ["params", "results"]})

    def test_la_interfaz_propia_sin_ui_entry(self):
        self.assert_roto('pack.view("roto.b", panel="ui")', "[ui] entry")

    def test_la_vista_de_un_bloque_que_no_es_suyo_o_no_esta_declarado(self):
        self.assert_roto('pack.view("otro.b")', "no es un bloque de roto")

    def test_un_control_que_no_existe(self):
        self.assert_roto('pack.view("roto.b", card=["params", "grafica3d"])', "grafica3d")

    def test_un_texto_que_no_es_ui(self):
        self.assert_roto('pack.view("roto.b", card="params")', '"ui" o una lista')

    def test_un_control_repetido(self):
        self.assert_roto('pack.view("roto.b", card=["params", "params"])', "repite")

    def test_la_vista_repetida(self):
        self.assert_roto('pack.view("roto.b")\npack.view("roto.b")', "repetida")

    def test_una_accion_sin_el_prefijo_del_paquete(self):
        self.assert_roto('pack.action("otro.x", accion)', "no empieza por 'roto.'")

    def test_una_accion_que_no_es_una_funcion(self):
        self.assert_roto('pack.action("roto.x", 3)', "run no es una función")

    def test_una_accion_repetida(self):
        self.assert_roto('pack.action("roto.x", accion)\npack.action("roto.x", accion)',
                         "repetida")

    def test_el_entry_tiene_que_estar_en_ui(self):
        self.assert_roto("", "[ui] entry", toml='[ui]\nentry = "index.html"')


class InterfazServida(unittest.TestCase):
    """`pack_ui.resolve`: lo único que se sirve es un fichero de `ui/` de un paquete cargado."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.fuera = root / "secreto.txt"
        cls.fuera.write_text("secreto", encoding="utf-8")
        write(root / "packs", "conui", toml='[ui]\nentry = "ui/index.html"')
        ui = root / "packs" / "conui" / "ui"
        (ui / "sub").mkdir(parents=True)
        (ui / "index.html").write_text("<p>hola</p>", encoding="utf-8")
        (ui / "sub" / "app.js").write_text("1", encoding="utf-8")
        write(root / "packs", "sinui")
        write(root / "packs", "rotoui", 'pack.view("rotoui.nada")',
              toml='[ui]\nentry = "ui/index.html"')
        (root / "packs" / "rotoui" / "ui").mkdir()
        (root / "packs" / "rotoui" / "ui" / "index.html").write_text("x", encoding="utf-8")
        cls.reg, cls.info = load(root / "packs")
        # los enlaces, después de cargar: un paquete con enlaces no carga (la validación, P30),
        # pero uno puede aparecer con la app abierta y tampoco se sirve
        cls.links = True
        try:
            os.symlink(cls.fuera, ui / "enlace.txt")
            os.symlink(root / "packs" / "conui", ui / "enlace_dir", target_is_directory=True)
        except (OSError, NotImplementedError):
            cls.links = False                   # Windows sin modo desarrollador
        assert cls.info["rotoui"].error, "rotoui tiene que estar roto"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def no(self, pack_id, rel):
        with self.assertRaises(pack_ui.NotServed, msg=f"{pack_id}/{rel}"):
            pack_ui.resolve(self.reg, pack_id, rel)

    def test_sirve_lo_de_ui(self):
        self.assertEqual(pack_ui.resolve(self.reg, "conui", "index.html").read_text(), "<p>hola</p>")
        self.assertEqual(pack_ui.resolve(self.reg, "conui", "sub/app.js").read_text(), "1")

    def test_nada_fuera_de_ui_ni_del_paquete(self):
        for rel in ("../blocks.py", "../pack.toml", "sub/../../blocks.py", "../../secreto.txt",
                    "..", ".", "", "/etc/hosts", str(self.fuera), "sub\\..\\..\\blocks.py",
                    "C:/Windows/win.ini", "c:secreto.txt",
                    "index.html\0", "no-existe.js", "sub"):
            self.no("conui", rel)

    def test_un_enlace_que_sale_de_ui_no_se_sigue(self):
        if not self.links:
            self.skipTest("este sistema no deja crear enlaces simbólicos")
        self.no("conui", "enlace.txt")
        self.no("conui", "enlace_dir/blocks.py")

    def test_ni_de_un_paquete_sin_interfaz_roto_o_que_no_existe(self):
        self.no("sinui", "index.html")
        self.no("rotoui", "index.html")
        self.no("noexiste", "index.html")

    def test_la_csp_no_deja_salir_a_la_red(self):
        c = pack_ui.csp("http://127.0.0.1:8765", "conui")
        rules = dict(r.split(" ", 1) for r in c.split("; "))
        self.assertEqual(rules["default-src"], "'none'")
        self.assertEqual(rules["connect-src"], "'none'")
        self.assertEqual(rules["form-action"], "'none'")
        for d in ("script-src", "style-src", "img-src", "font-src"):
            srcs = rules[d].split()
            # solo su propia ui/, más lo que no sale de la página
            self.assertEqual([s for s in srcs if "://" in s],
                             ["http://127.0.0.1:8765/packs/conui/ui/"], d)
            self.assertFalse(set(srcs) - {"http://127.0.0.1:8765/packs/conui/ui/",
                                          "'unsafe-inline'", "data:", "blob:"}, d)


class PuenteDeLaRueda(unittest.TestCase):
    """P54: el puente va delante de todo lo de la página, sin sacarla del modo estándar."""

    B = pack_ui.BRIDGE.encode()

    def test_detras_de_head_y_delante_de_lo_suyo(self):
        html = b'<!doctype html><html><HEAD lang="es"><script src="app.js"></script></head></html>'
        out = pack_ui.with_bridge(html)
        self.assertEqual(out, html.replace(b'<HEAD lang="es">', b'<HEAD lang="es">' + self.B))

    def test_sin_head_detras_de_html_o_del_doctype(self):
        self.assertTrue(pack_ui.with_bridge(b"<html><p>x</p>").startswith(b"<html>" + self.B))
        self.assertTrue(pack_ui.with_bridge(b"<!DOCTYPE html><p>x</p>")
                        .startswith(b"<!DOCTYPE html>" + self.B))

    def test_sin_nada_al_principio_y_detras_de_la_marca_utf8(self):
        self.assertEqual(pack_ui.with_bridge(b"<p>x</p>"), self.B + b"<p>x</p>")
        self.assertEqual(pack_ui.with_bridge(b"\xef\xbb\xbf<p>x</p>"), b"\xef\xbb\xbf" + self.B + b"<p>x</p>")

    def test_solo_las_paginas(self):
        self.assertTrue(pack_ui.is_page("ui/index.html"))
        self.assertTrue(pack_ui.is_page("ui/OTRA.HTM"))
        self.assertFalse(pack_ui.is_page("ui/app.js"))
        self.assertFalse(pack_ui.is_page("ui/estilo.css"))

    def test_el_puente_no_sale_a_la_red_ni_toca_la_app(self):
        js = pack_ui.BRIDGE
        for nada in ("fetch", "XMLHttpRequest", "WebSocket", "location", "top.", "parent.document"):
            self.assertNotIn(nada, js)
        self.assertIn("parent.postMessage({v:1,type:'wheel'", js)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


try:
    import uvicorn
    from pizarra import blocks as blocks_mod
    from pizarra.server import create_app
    from pizarra.startup import bootstrap
except ImportError:                       # sin las dependencias del servidor
    uvicorn = None


@unittest.skipIf(uvicorn is None, "faltan las dependencias del servidor")
class RutaDeLaInterfaz(unittest.TestCase):
    """`GET /packs/<id>/ui/<ruta>` por HTTP de verdad: la URL decodificada tampoco sale, y
    cada respuesta lleva la CSP."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.tmp = Path(tempfile.mkdtemp())
        start = bootstrap(cls.tmp / "settings.toml", cls.tmp / "Documentos" / "Personal", (),
                          trash=lambda p: None)
        start.settings.language = "es"        # los mensajes que se comprueban, en español (O16)
        app = create_app(start)
        cls._registry = blocks_mod.REGISTRY
        blocks_mod.REGISTRY = packs.load([PACKS_UI], log=lambda m: None)
        cls.project = start.workspace.create_project("", "P").id
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
        blocks_mod.REGISTRY = cls._registry

    def get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_sirve_con_la_csp_y_sin_token(self):
        for rel in ("index.html", "app.js", "estilo.css"):
            code, h, body = self.get(f"/packs/ui_prueba/ui/{rel}")
            self.assertEqual(code, 200, rel)
            self.assertIn("default-src 'none'", h["Content-Security-Policy"])
            self.assertIn(f"script-src http://127.0.0.1:{self.port}/packs/ui_prueba/ui/",
                          h["Content-Security-Policy"])
            self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertIn("javascript", self.get("/packs/ui_prueba/ui/app.js")[1]["Content-Type"])

    def test_la_pagina_lleva_el_puente_y_lo_demas_va_tal_cual(self):
        code, h, body = self.get("/packs/ui_prueba/ui/index.html")
        self.assertIn("text/html", h["Content-Type"])
        self.assertIn(pack_ui.BRIDGE.encode(), body)
        self.assertLess(body.index(pack_ui.BRIDGE.encode()), body.index(b'<script src="app.js">'))
        self.assertEqual(body.count(b"<script>/* BoardPrint"), 1)
        disk = PACKS_UI / "ui_prueba" / "ui"
        self.assertEqual(self.get("/packs/ui_prueba/ui/app.js")[2], (disk / "app.js").read_bytes())
        self.assertNotIn(b"BoardPrint", (disk / "index.html").read_bytes())     # el disco, intacto

    def test_lo_que_sale_de_ui_es_404_y_tambien_lleva_la_csp(self):
        for path in ("/packs/ui_prueba/ui/%2e%2e/blocks.py", "/packs/ui_prueba/ui/..%2fpack.toml",
                     "/packs/ui_prueba/ui/..%5cblocks.py", "/packs/ui_prueba/ui/%2e%2e%2f%2e%2e%2fpack_ui.py",
                     "/packs/ui_otro/ui/index.html", "/packs/no_existe/ui/index.html",
                     "/packs/ui_prueba/ui/C:%2fWindows%2fwin.ini"):
            code, h, body = self.get(path)
            self.assertEqual(code, 404, path)
            self.assertIn("connect-src 'none'", h["Content-Security-Policy"], path)
            self.assertNotIn(b"register", body, path)

    def test_un_host_raro_no_entra_en_la_csp(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/packs/ui_prueba/ui/index.html",
                                     headers={"Host": "x; script-src *"})
        with urllib.request.urlopen(req, timeout=5) as r:
            c = r.headers["Content-Security-Policy"]
        self.assertNotIn("*", c)
        self.assertIn("script-src 'none'", c)

    def test_una_accion_de_un_bloque_que_no_existe_es_422(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/projects/{self.project}/blocks/nada/action",
            data=json.dumps({"name": "ui_prueba.eco", "args": {}}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 422)


class Acciones(unittest.TestCase):
    """`Board.action`: solo las del paquete del bloque, con lo que el bloque tiene."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        extra = root / "extra"
        write(extra, "malo", '''
            def cambia(params, inputs, args, ctx):   # lo que toque es una copia
                params["a"] = 99
                inputs.clear()
                return {}
            pack.action("malo.nan", lambda p, i, a, c: {"x": float("nan")})
            pack.action("malo.set", lambda p, i, a, c: {1, 2})
            pack.action("malo.cambia", cambia)
        ''')
        self.reg = packs.load([PACKS_UI, extra], log=lambda m: None)
        ws = LocalWorkspace.open(root / "ws", trash=lambda p: None)
        self.b = Board(ws, ws.create_project("", "P").id, registry=self.reg, connectors=frozenset())
        self.el = scene.block_element("ui_prueba.b", 0, 0)
        self.malo = scene.block_element("malo.b", 300, 0)
        self.b.apply_client_elements([self.el, self.malo])
        self.b.set_params(self.el["id"], {"a": 4.0})

    def tearDown(self):
        self.tmp.cleanup()

    def test_llama_a_la_de_su_paquete_con_sus_parametros(self):
        r = self.b.action(self.el["id"], "ui_prueba.eco", {"hola": [1, 2]})
        self.assertEqual(r, {"block": self.el["id"], "a": 4.0, "args": {"hola": [1, 2]},
                             "inputs": []})

    def test_nunca_llega_a_la_de_otro_paquete(self):
        for name in ("ui_otro.secreto", "malo.nan", "secreto", "", None, "ui_prueba"):
            with self.assertRaises(ValidationError, msg=name):
                self.b.action(self.el["id"], name, {})

    def test_una_accion_que_no_existe_en_su_paquete(self):
        with self.assertRaisesRegex(ValidationError, "no tiene la acción"):
            self.b.action(self.el["id"], "ui_prueba.no_existe", {})

    def test_un_bloque_que_no_existe(self):
        with self.assertRaisesRegex(ValidationError, "no hay ningún bloque"):
            self.b.action("nada", "ui_prueba.eco", {})

    def test_los_args_son_un_objeto(self):
        with self.assertRaisesRegex(ValidationError, "objeto"):
            self.b.action(self.el["id"], "ui_prueba.eco", [1])

    def test_un_fallo_de_la_accion_es_un_error_con_el_motivo(self):
        with self.assertRaisesRegex(ValidationError, "me han pedido fallar"):
            self.b.action(self.el["id"], "ui_prueba.eco", {"falla": True})

    def test_lo_que_no_es_json_es_un_error(self):
        for name in ("malo.nan", "malo.set"):
            with self.assertRaisesRegex(ValidationError, "no devuelve JSON", msg=name):
                self.b.action(self.malo["id"], name, {})

    def test_la_accion_no_toca_el_estado_del_bloque(self):
        before = json.dumps(self.b.state, sort_keys=True)
        self.b.action(self.malo["id"], "malo.cambia", {})
        self.assertEqual(json.dumps(self.b.state, sort_keys=True), before)
        self.assertEqual(self.b._live(self.malo["id"])[1]["a"], 1)



class TiposDeParametros(unittest.TestCase):
    """`set_params` (tarjeta, interfaz propia, agente, *Traer*): el tipo del de por defecto (P49)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        write(root / "extra", "tipos", '''
            pack.block("tipos.t", "T", run, params={
                "n": Param(1.0), "i": Param(3), "opt": Param(None), "s": Param(""),
                "c": Param("a", choices=("a", "b")), "f": Param(True), "d": Param({}),
                "l": Param([]), "w": Param(None, widget="cad_destino"),
                "wc": Param("x", choices=("x",), widget="robot_comercial")})
        ''')
        self.reg = packs.load([root / "extra"], log=lambda m: None)
        ws = LocalWorkspace.open(root / "ws", trash=lambda p: None)
        self.b = Board(ws, ws.create_project("", "P").id, registry=self.reg, connectors=frozenset())
        self.el = scene.block_element("tipos.t", 0, 0)
        self.b.apply_client_elements([self.el])

    def tearDown(self):
        self.tmp.cleanup()

    def test_lo_del_tipo_de_por_defecto_se_guarda(self):
        good = {"n": 2, "i": 4.5, "opt": None, "s": "hola", "c": "b", "f": False, "d": {"k": 1},
                "l": [1], "w": {"hub": "h"}, "wc": "otro de la librería"}
        self.b.set_params(self.el["id"], good)
        self.assertEqual({k: self.b.state[self.el["id"]]["params"][k] for k in good}, good)
        self.b.set_params(self.el["id"], {"opt": 7.5})
        self.assertEqual(self.b.state[self.el["id"]]["params"]["opt"], 7.5)

    def test_lo_de_otro_tipo_nunca_se_guarda_ni_deja_pasar_lo_demas(self):
        before = json.dumps(self.b.state, sort_keys=True)
        for bad in ({"n": "no es un número"}, {"n": None}, {"n": True}, {"n": float("nan")},
                    {"i": "3"}, {"opt": "1"}, {"s": 5}, {"c": "z"}, {"f": 1}, {"d": []},
                    {"l": {}}, {"n": 5, "s": 5}):
            with self.assertRaises(ValidationError, msg=bad):
                self.b.set_params(self.el["id"], bad)
        self.assertEqual(json.dumps(self.b.state, sort_keys=True), before)

    def test_lo_que_no_es_del_bloque_se_ignora(self):
        self.b.set_params(self.el["id"], {"otro": "lo que sea", "n": 9})
        self.assertNotIn("otro", self.b.state[self.el["id"]]["params"])
        self.assertEqual(self.b.state[self.el["id"]]["params"]["n"], 9)

if __name__ == "__main__":
    unittest.main()
