"""El conector de un paquete y lo que hace en la pizarra (docs/PLAN_PAQUETES.md §6, §10 «API
del conector» y «Conector», P38, P39, P41; SDK 1.2).

Reglas:
- `pack.connector` declara **como mucho un** conector, con el id del paquete; lo mal declarado
  (funciones que no lo son, extensiones sin punto, `open_file` sin `accepts`, `card`/`panel`
  sin `[ui] entry`, un tipo que da y nadie registra) **tumba el paquete**, y los demás cargan.
- Un bloque con `connector=` usa el conector **de su paquete o de uno de su `[requires]`**, y
  ese paquete lo tiene que declarar; si no, su paquete no se carga. El conector va también en
  `requires`: sin él disponible, el bloque sale «no disponible».
- Una acción solo llega desde un bloque de **su** paquete o desde uno que declara **su**
  conector.
- API de P39: un cambio de parámetros que pide un paquete pasa **por la misma validación** que
  uno de la tarjeta (todo o nada), y un post-it de un paquete **nunca** se ancla a un bloque
  que no existe. Fuera de una acción (al ejecutar un bloque) no hay pizarra.

Ejecutar desde app/backend:  python -m unittest tests.test_pack_connector -v
"""
import tempfile
import textwrap
import unittest
from pathlib import Path

from boardprint_sdk.packs import RunContext
from pizarra import graph, packs, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace
from pizarra.validation import ValidationError

BODY = '''
from boardprint_sdk.packs import Param

def run(p, i, c):
    return {{"out": {{"x": {{"value": p["a"], "unit": "mm"}}}}}}

def register(pack):
    pack.port("{id}.t", "t")
{extra}
'''


def write(root, pack_id, extra="", toml=""):
    d = Path(root) / pack_id
    d.mkdir(parents=True)
    (d / "pack.toml").write_text(f'id = "{pack_id}"\nname = "{pack_id}"\nversion = "1.0.0"\n'
                                 'author = "Pruebas"\ndescription = "Paquete de prueba"\n'
                                 f'sdk = ">=1.2,<2"\n{toml}\n', encoding="utf-8")
    body = BODY.format(id=pack_id, extra=textwrap.indent(textwrap.dedent(extra), "    "))
    (d / "blocks.py").write_text(body, encoding="utf-8")
    return d


def load(root):
    reg = packs.load([str(root)], log=lambda m: None)
    return reg, {p.id: p for p in reg.packs}


# El conector de prueba: un programa que siempre está, con sus acciones.
CONECTOR = '''
pack.connector("Programa", available=lambda: True, launch=lambda: "abierto",
               open_file=lambda path: None, accepts=(".prg",), gives=("prog.t",),
               config={"url": "http://127.0.0.1:1"}, card=True)

def marca(params, inputs, args, ctx):
    return {"block": ctx.block_id, "args": args}

pack.action("prog.marca", marca)
'''
UI = '[ui]\nentry = "ui/index.html"'


def with_ui(d):
    (d / "ui").mkdir()
    (d / "ui" / "index.html").write_text("<!doctype html><title>p</title>", encoding="utf-8")
    return d


class Declaracion(unittest.TestCase):
    """`pack.connector` y `connector=` al cargar."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assert_roto(self, extra, *texto, toml=""):
        write(self.root, "sano", 'pack.block("sano.b", "B", run, params={"a": Param(1)}, '
                                 'outputs={"out": "sano.t"})')
        write(self.root, "roto", extra, toml)
        reg, info = load(self.root)
        err = info["roto"].error
        self.assertIsNotNone(err, "el paquete mal declarado no carga")
        for t in texto:
            self.assertIn(t, err)
        self.assertNotIn("roto", reg.connectors)
        self.assertIsNone(info["sano"].error, "los demás paquetes cargan")
        self.assertIn("sano.b", reg)

    def test_un_conector_bien_declarado_se_registra_y_se_describe(self):
        with_ui(write(self.root, "prog", CONECTOR, UI))
        write(self.root, "usa", '''
            pack.block("usa.b", "B", run, params={"a": Param(1)}, outputs={"out": "usa.t"},
                       connector="prog")
        ''', '[requires]\nprog = ">=1,<2"')
        reg, info = load(self.root)
        self.assertIsNone(info["prog"].error)
        self.assertIsNone(info["usa"].error)
        c = reg.connectors["prog"]
        self.assertEqual((c.id, c.pack, c.accepts, c.gives, c.card, c.panel),
                         ("prog", "prog", (".prg",), ("prog.t",), True, False))
        self.assertEqual(reg["usa.b"].connector, "prog")
        self.assertIn("prog", reg["usa.b"].requires, "el conector va también en requires")
        d = reg.describe()
        self.assertEqual(d["blocks"]["usa.b"]["connector"], "prog")
        self.assertEqual(d["connectors"]["prog"], {"title": "Programa", "accepts": [".prg"],
                                                   "gives": ["prog.t"], "launch": True,
                                                   "card": True, "panel": False})

    def test_sin_el_conector_disponible_el_bloque_sale_no_disponible(self):
        with_ui(write(self.root, "prog", CONECTOR, UI))
        write(self.root, "usa", 'pack.block("usa.b", "B", run, params={"a": Param(1)}, '
                                'outputs={"out": "usa.t"}, connector="prog")',
              '[requires]\nprog = ">=1,<2"')
        reg, _ = load(self.root)
        el = scene.block_element("usa.b", 0, 0)
        st, _ = graph.explain([el], reg, {}, frozenset())
        self.assertEqual(st[el["id"]], "no_disponible")
        st, _ = graph.explain([el], reg, {}, frozenset({"prog"}))
        self.assertNotEqual(st[el["id"]], "no_disponible")

    def test_el_conector_de_un_paquete_que_no_esta_en_requires(self):
        with_ui(write(self.root, "prog", CONECTOR, UI))
        self.assert_roto('pack.block("roto.b", "B", run, outputs={"out": "roto.t"}, '
                         'connector="prog")', "sin declarar su paquete en [requires]")

    def test_un_paquete_que_no_declara_conector(self):
        write(self.root, "nada", "")
        self.assert_roto('pack.block("roto.b", "B", run, outputs={"out": "roto.t"}, '
                         'connector="nada")', "no declara ningún conector",
                         toml='[requires]\nnada = ">=1,<2"')

    def test_el_conector_propio_no_necesita_requires(self):
        write(self.root, "solo", '''
            pack.connector("Solo", available=lambda: False)
            pack.block("solo.b", "B", run, outputs={"out": "solo.t"}, connector="solo")
        ''')
        reg, info = load(self.root)
        self.assertIsNone(info["solo"].error)
        self.assertEqual(reg["solo.b"].connector, "solo")

    def test_dos_conectores(self):
        self.assert_roto('pack.connector("A", available=lambda: True)\n'
                         'pack.connector("B", available=lambda: True)', "como mucho un conector")

    def test_funciones_que_no_lo_son(self):
        self.assert_roto('pack.connector("A", available=True)', "available no es una función")
        self.tearDown(); self.setUp()
        self.assert_roto('pack.connector("A", available=lambda: True, launch="sí")',
                         "launch no es una función")

    def test_extensiones_y_open_file(self):
        for extra, texto in (
                ('pack.connector("A", available=lambda: True, open_file=lambda p: 0, '
                 'accepts=("step",))', "extensiones en minúsculas"),
                ('pack.connector("A", available=lambda: True, open_file=lambda p: 0, '
                 'accepts=(".STEP",))', "extensiones en minúsculas"),
                ('pack.connector("A", available=lambda: True, open_file=lambda p: 0)',
                 "open_file y accepts van juntos"),
                ('pack.connector("A", available=lambda: True, accepts=(".step",))',
                 "open_file y accepts van juntos")):
            with self.subTest(extra=extra):
                self.assert_roto(extra, texto)
            self.tearDown(); self.setUp()

    def test_card_o_panel_sin_interfaz_propia(self):
        self.assert_roto('pack.connector("A", available=lambda: True, panel=True)',
                         "no tiene [ui] entry")

    def test_un_tipo_que_da_y_nadie_registra(self):
        self.assert_roto('pack.connector("A", available=lambda: True, gives=("otro.t",))',
                         "un tipo que nadie registra")

    def test_connector_que_no_es_un_texto(self):
        self.assert_roto('pack.block("roto.b", "B", run, outputs={"out": "roto.t"}, '
                         'connector=1)', "connector es el id")

    def test_un_control_de_su_conector_o_suyo_se_describe_tal_cual(self):
        # P41: la tarjeta de la app no pinta un control `<paquete>.<x>`; lo pinta la parte del
        # conector, que solo cambia esos parámetros (packui.ts, `connectorSetParams`)
        with_ui(write(self.root, "prog", CONECTOR, UI))
        write(self.root, "usa", '''
            pack.block("usa.b", "B", run, params={"a": Param(1), "d": Param(None, widget="prog.destino"),
                                               "m": Param(0, widget="usa.mio")},
                       outputs={"out": "usa.t"}, connector="prog")
        ''', '[requires]\nprog = ">=1,<2"')
        reg, info = load(self.root)
        self.assertIsNone(info["usa"].error)
        ps = reg.describe()["blocks"]["usa.b"]["params"]
        self.assertEqual((ps["d"]["widget"], ps["m"]["widget"]), ("prog.destino", "usa.mio"))

    def test_un_control_de_otro_paquete_que_no_es_su_conector(self):
        with_ui(write(self.root, "prog", CONECTOR, UI))
        self.assert_roto('pack.block("roto.b", "B", run, params={"d": Param(None, widget="prog.destino")}, '
                         'outputs={"out": "roto.t"})', "no es de este paquete ni de su conector",
                         toml='[requires]\nprog = ">=1,<2"')


class Acciones(unittest.TestCase):
    """`Board.action` con conectores: las del paquete del bloque y las de su conector."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        packs_dir = root / "packs"
        with_ui(write(packs_dir, "prog", CONECTOR, UI))
        req = '[requires]\nprog = ">=1,<2"'
        write(packs_dir, "usa", 'pack.block("usa.b", "B", run, params={"a": Param(1)}, '
                                'outputs={"out": "usa.t"}, connector="prog")', req)
        write(packs_dir, "sin", 'pack.block("sin.b", "B", run, params={"a": Param(1)}, '
                                'outputs={"out": "sin.t"})', req)
        self.reg, info = load(packs_dir)
        assert all(p.error is None for p in info.values()), info
        ws = LocalWorkspace.open(root / "ws", trash=lambda p: None)
        self.b = Board(ws, ws.create_project("", "P").id, registry=self.reg, connectors=frozenset())
        self.usa = scene.block_element("usa.b", 0, 0)
        self.sin = scene.block_element("sin.b", 400, 0)
        self.b.apply_client_elements([self.usa, self.sin])

    def tearDown(self):
        self.tmp.cleanup()

    def test_un_bloque_con_conector_llega_a_las_acciones_del_conector(self):
        r = self.b.action(self.usa["id"], "prog.marca", {"x": 1})
        self.assertEqual(r, {"block": self.usa["id"], "args": {"x": 1}})

    def test_un_bloque_sin_ese_conector_no_llega(self):
        # aunque su paquete tenga `prog` en [requires]: lo que cuenta es el bloque
        with self.assertRaisesRegex(ValidationError, "ni de su conector"):
            self.b.action(self.sin["id"], "prog.marca", {})


class ApiDeLaPizarra(unittest.TestCase):
    """Los métodos de pizarra de `RunContext` (P39) desde una acción."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        packs_dir = root / "packs"
        # `api.call` llama al método de ctx que digan los args: así cada test prueba uno
        write(packs_dir, "api", '''
            pack.port("api.c", "c")
            pack.block("api.cad", "Diseño", run, outputs={"out": "api.t"},
                       params={"a": Param(1.0, "mm"), "locks": Param({}),
                               "modo": Param("x", choices=("x", "y"))})
            pack.block("api.build", "Construir", run, inputs={"d": "api.t"},
                       outputs={"out": "api.c"})

            def call(params, inputs, args, ctx):
                r = getattr(ctx, args["m"])(*args.get("a", []))
                if args.get("luego_falla"):
                    raise RuntimeError("falla después")
                return r if not hasattr(r, "as_posix") else r.as_posix()

            pack.action("api.call", call)
        ''')
        self.reg, info = load(packs_dir)
        assert info["api"].error is None, info["api"].error
        ws = LocalWorkspace.open(root / "ws", trash=lambda p: None)
        self.b = Board(ws, ws.create_project("", "P").id, registry=self.reg, connectors=frozenset())
        self.cad = scene.block_element("api.cad", 0, 0)
        self.build = scene.block_element("api.build", 500, 0)
        arrow = scene.connection_element(self.cad, self.build, "out", "d")
        self.b.apply_client_elements([self.cad, self.build, arrow])
        self.b.set_params(self.cad["id"], {"a": 2.0})

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, m, *a, effects=None, **kw):
        return self.b.action(self.build["id"], "api.call", {"m": m, "a": list(a), **kw},
                             effects=effects)

    def params(self, bid):
        return self.b.state[bid]["params"]

    # ------------------------------------------------------------- leer
    def test_lee_el_estado_de_un_bloque_y_su_entrada(self):
        st = self.call("block", self.cad["id"])
        self.assertEqual((st["type"], st["params"]["a"], st["params"]["modo"], st["busy"]),
                         ("api.cad", 2.0, "x", False))
        self.assertEqual(st["status"], self.b.statuses()[self.cad["id"]])
        self.assertIsNone(self.call("block", "no_existe"))
        self.assertEqual(self.call("upstream", self.build["id"], "d"), self.cad["id"])
        self.assertIsNone(self.call("upstream", self.cad["id"], "d"))

    def test_lo_leido_es_una_copia(self):
        st = self.call("block", self.cad["id"])
        st["params"]["a"] = 99
        self.assertEqual(self.params(self.cad["id"])["a"], 2.0)

    # --------------------------------------------- parámetros: la validación de la tarjeta
    def test_un_cambio_de_parametros_pasa_por_la_validacion_de_la_tarjeta(self):
        fx = {}
        self.call("set_params", self.cad["id"], {"locks": {"L1": 120.0}, "a": 3.0}, effects=fx)
        self.assertEqual(self.params(self.cad["id"])["locks"], {"L1": 120.0})
        self.assertTrue(fx["changed"])
        for bad in ({"a": "no es un número"}, {"modo": "z"}, {"locks": 5},
                    {"a": float("nan")}, {"a": True}):
            with self.subTest(bad=bad):
                before = dict(self.params(self.cad["id"]))
                good = {"modo": "y"} if "a" in bad else {"a": 5.0}   # uno bueno al lado
                with self.assertRaises(ValidationError):
                    self.call("set_params", self.cad["id"], {**good, **bad})
                self.assertEqual(self.params(self.cad["id"]), before, "todo o nada")

    def test_lo_que_rechaza_la_api_lo_rechaza_la_tarjeta(self):
        # la misma regla, por los dos caminos: lo que no pasa por uno no pasa por el otro
        for bad in ({"a": "x"}, {"modo": "z"}, {"locks": [1]}):
            with self.assertRaises(ValidationError):
                self.b.set_params(self.cad["id"], bad)
            with self.assertRaises(ValidationError):
                self.call("set_params", self.cad["id"], bad)

    def test_un_parametro_que_no_es_suyo_se_ignora_y_un_bloque_que_no_existe_no(self):
        self.call("set_params", self.cad["id"], {"no_es_suyo": 1})
        self.assertNotIn("no_es_suyo", self.params(self.cad["id"]))
        with self.assertRaisesRegex(ValidationError, "no hay ningún bloque"):
            self.call("set_params", "no_existe", {"a": 1.0})

    # ------------------------------------------------------------- post-its
    def test_un_post_it_se_ancla_a_su_bloque_con_el_como_fuente(self):
        fx = {}
        pid = self.call("add_postit", self.cad["id"], "Cambio a mano: +12 g", "riesgo",
                        ["dim|L1"], effects=fx)
        el = next(e for e in self.b.elements if e["id"] == pid)
        cd = el["customData"]
        self.assertEqual((cd["anchor"], cd["postitKind"], cd["state"]),
                         (self.cad["id"], "riesgo", "abierto"))
        self.assertEqual(cd["sources"], [{"kind": "bloque", "ref": f"bloque:{self.cad['id']}"}])
        self.assertEqual([e["id"] for e in fx["new"]], [pid])
        self.assertEqual(self.call("postits", self.cad["id"]),
                         [{"id": pid, "text": "Cambio a mano: +12 g", "kind": "riesgo",
                           "state": "abierto", "keys": ["dim|L1"]}])
        self.assertEqual(self.call("postits", self.build["id"]), [])

    def test_un_post_it_nunca_se_ancla_a_un_bloque_que_no_existe(self):
        n = len(self.b.elements)
        postit = scene.postit_element({"text": "x", "kind": "nota", "state": "abierto",
                                       "author": "user", "sources": [], "estimate": False,
                                       "anchor": None}, 0, 600)
        self.b.apply_client_elements([postit])       # ni a un elemento que no es un bloque
        for target in ("no_existe", "", None, postit["id"]):
            with self.subTest(target=target), self.assertRaises(ValidationError):
                self.call("add_postit", target, "texto")
        self.assertEqual(len(self.b.elements), n + 1, "no queda nada a medias")

    def test_un_post_it_vacio_o_de_un_tipo_que_no_existe(self):
        for a in (("  ",), ("texto", "chisme"), ("texto", "nota", [1])):
            with self.subTest(a=a), self.assertRaises(ValidationError):
                self.call("add_postit", self.cad["id"], *a)

    # ----------------------------------------------------------- el resto
    def test_quita_solo_el_error_de_esa_confirmacion(self):
        st = self.b.state.setdefault(self.build["id"], {})
        st.update(error="cambiado en el programa", error_action={"action": "otra"})
        self.assertFalse(self.call("clear_error", self.build["id"], "pull"))
        self.assertEqual(st["error"], "cambiado en el programa")
        st["error_action"] = {"action": "pull"}
        self.assertTrue(self.call("clear_error", self.build["id"], "pull"))
        self.assertIsNone(st["error"])

    def test_un_archivo_de_un_bloque_y_nunca_de_fuera(self):
        d = self.b.ws._block_dir(self.b.project_id, self.cad["id"])
        d.mkdir(parents=True)
        (d / "a.json").write_text("{}", encoding="utf-8")
        (d.parent / "fuera.json").write_text("{}", encoding="utf-8")
        self.assertEqual(Path(self.call("block_file", self.cad["id"], "a.json")),
                         (d / "a.json").resolve())
        for name in ("../fuera.json", "no_esta.json"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.call("block_file", self.cad["id"], name)

    def test_lo_hecho_antes_de_un_fallo_tambien_se_avisa(self):
        fx = {}
        with self.assertRaisesRegex(ValidationError, "falla después"):
            self.call("add_postit", self.cad["id"], "uno", effects=fx, luego_falla=True)
        self.assertTrue(fx["changed"])
        self.assertEqual(len(fx["new"]), 1)

    def test_sin_cambios_no_hay_nada_que_guardar(self):
        fx = {}
        self.call("block", self.cad["id"], effects=fx)
        self.assertEqual(fx, {"changed": False, "new": []})

    def test_al_ejecutar_un_bloque_no_hay_pizarra(self):
        ctx = RunContext(block_id="b")
        with self.assertRaisesRegex(RuntimeError, "solo está a mano en una acción"):
            ctx.set_params("b", {})


if __name__ == "__main__":
    unittest.main()
