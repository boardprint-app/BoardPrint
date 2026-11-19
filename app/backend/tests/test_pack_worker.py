"""El trabajador de paquetes y su anfitrión (docs/PLAN_PAQUETES.md §4, §10, P89-P91).

Reglas:
- **Registro como datos**: el registro que arma el backend con los datos del trabajador
  (`pack_data`) describe **lo mismo** que el cargado en proceso, ids de antes incluidos.
- **Trabajador**: el registro, la ejecución, la vista previa, las acciones y los conectores
  dan **lo mismo** en el trabajador que en proceso; el progreso llega, una confirmación
  (`ConfirmRequired`) vuelve con su botón y *Cancelar* mata la ejecución y la deja como
  cancelada. Si el trabajador caliente muere, la siguiente llamada lo vuelve a arrancar.
- **Protocolo de acciones** (P91): lo que una acción pide a la pizarra pasa **por la misma
  validación** que una tarjeta (un valor de otro tipo es un error y no se guarda), solo llega
  a la API de P39 y `ctx.block_type` da el tipo con sus funciones. Una petición del backend que
  llega mientras el trabajador espera a la pizarra se atiende y la acción acaba (P109); una
  respuesta fuera de orden es un error, **nunca una espera sin fin**.

Ejecutar desde app/backend:  python -m unittest tests.test_pack_worker -v
"""
import asyncio
import json
import urllib.error
import subprocess
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

from pizarra import pack_data, pack_host, packs
from pizarra.execution import Step

REPO = Path(__file__).resolve().parents[3]
PACKS = REPO / "packs"
PACKS_UI = Path(__file__).resolve().parent / "packs_ui"

TEST_PACK = '''
import time
from boardprint_sdk.packs import ConfirmRequired, Param, Pull

def run(p, i, ctx):
    ctx.progress(0.5, "mitad")
    if p["modo"] == "confirmar" and not ctx.options.get("seguir"):
        raise ConfirmRequired("¿seguro?", "seguir", "Seguir")
    if p["modo"] == "dormir":
        time.sleep(30)
    return {"out": {"x": {"value": p["a"] * 2, "unit": "mm"}}}

def preview(p, i):
    if p["a"] < 0:
        raise ValueError("a no puede ser negativo")
    return {"doble": p["a"] * 2}

def fijar(params, inputs, args, ctx):
    ctx.set_params(ctx.block_id, {"a": args["a"]})
    return {"params": ctx.block(ctx.block_id)["params"],
            "tipo": ctx.block_type(ctx.block_id).title,
            "clasifica": ctx.block_type(ctx.block_id).pull.classify(None)}

def roto(params, inputs, args, ctx):
    raise KeyError("x")

def register(pack):
    pack.port("w.t", "t")
    pack.block("w.b", "Bloque W", run, outputs={"out": "w.t"},
               params={"a": Param(1.0, "mm"), "modo": Param("normal", choices=("normal", "confirmar", "dormir"))},
               preview=preview, pull=Pull(classify=lambda archivo: "desde el trabajador"),
               formerly=("w.viejo",))
    pack.action("w.fijar", fijar)
    pack.action("w.roto", roto)
    pack.connector("Programa W", available=lambda: True, open_file=lambda path: f"abierto {path}",
                   accepts=(".w",), config={"url": "http://w"})
'''


def write_test_pack(root):
    d = Path(root) / "w"
    d.mkdir(parents=True)
    (d / "pack.toml").write_text(textwrap.dedent('''\
        id = "w"
        name = "W"
        version = "1.0.0"
        author = "Pruebas"
        description = "Paquete de prueba del trabajador"
        sdk = ">=1.0,<2"
        '''), encoding="utf-8")
    (d / "blocks.py").write_text(TEST_PACK, encoding="utf-8")
    return d


class FakeBoard:
    """La API de P39 con una pizarra de un bloque, y la validación de una tarjeta: `a` es un
    número (como `validation.check_param`)."""

    def __init__(self, registry):
        self.registry = registry
        self.params = {"a": 1.0, "modo": "normal"}

    def block(self, block_id):
        return {"id": block_id, "type": "w.b", "params": dict(self.params), "outputs": None,
                "status": "nunca", "error": None, "busy": False}

    def set_params(self, block_id, params):
        if not isinstance(params.get("a"), (int, float)):
            raise ValueError("a tiene que ser un número")
        self.params.update(params)

    def block_type(self, block_id):           # nunca se llama: lo resuelve el trabajador
        raise AssertionError("block_type no cruza el canal")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_test_pack(cls.tmp.name)
        cls.origins = [("desarrollo", PACKS), ("pruebas", cls.tmp.name)]
        cls.here = packs.load(cls.origins, log=lambda m: None)
        cls.host = pack_host.WorkerHost(pack_host.default_spec(stderr=subprocess.DEVNULL),
                                        cls.origins)
        cls.remote = cls.host.load()

    @classmethod
    def tearDownClass(cls):
        cls.host.close()
        cls.tmp.cleanup()


class RegistroComoDatos(Base):
    def test_describe_lo_mismo_que_en_proceso(self):
        again = pack_data.from_data(json.loads(json.dumps(pack_data.to_data(self.here))))
        self.assertEqual(again.describe(), self.here.describe())
        self.assertEqual(again.renamed(), self.here.renamed())
        self.assertEqual(again.renamed()["w.viejo"], "w.b")

    def test_el_del_trabajador_tambien(self):
        self.assertEqual(self.remote.describe(), self.here.describe())
        self.assertIs(self.remote.host, self.host)
        self.assertEqual([p.digest for p in self.remote.packs], [p.digest for p in self.here.packs])

    def test_sin_funciones_en_el_backend(self):
        with self.assertRaisesRegex(RuntimeError, "corre en el trabajador"):
            self.remote["w.b"].run({}, {}, None)
        self.assertIsNotNone(self.remote["w.b"].pull.classify)   # la marca: el bloque trae
        self.assertIsNotNone(self.remote["w.b"].preview)


class Trabajador(Base):
    def test_vista_previa_igual_y_su_error(self):
        self.assertEqual(self.host.preview("w.b", {"a": 3.0}, {}),
                         self.here.host.preview("w.b", {"a": 3.0}, {}))
        with self.assertRaisesRegex(ValueError, "a no puede ser negativo"):
            self.host.preview("w.b", {"a": -1.0}, {})

    def test_conectores(self):
        self.assertIs(self.host.connector("w", "available"), True)
        self.assertEqual(self.host.connector("w", "open_file", "C:/x.w"), "abierto C:/x.w")
        self.assertEqual(self.remote.connectors["w"].config, {"url": "http://w"})

    def run_step(self, worker, **params):
        step = Step(block_id="b1", kind="w.b", params={"a": 2.0, "modo": "normal", **params},
                    inputs={}, input_hash="", workdir=self.tmp.name)
        seen = []

        async def go():
            async def progress(fraction, message):
                seen.append((fraction, message))
            return await worker.run(step, progress)

        return asyncio.run(go()), seen

    def test_ejecuta_igual_con_progreso(self):
        w = self.host.run_worker()
        try:
            got, seen = self.run_step(w)
        finally:
            w.close()
        here = pack_data.run_step(self.here, {"block_id": "b1", "kind": "w.b",
                                              "params": {"a": 2.0, "modo": "normal"},
                                              "inputs": {}, "workdir": self.tmp.name})
        self.assertEqual(got, tuple(here))
        self.assertEqual(got, ("ok", {"out": {"x": {"value": 4.0, "unit": "mm"}}}))
        self.assertIn((0.5, "mitad"), seen)

    def test_confirmacion_vuelve_con_su_boton(self):
        w = self.host.run_worker()
        try:
            got, _ = self.run_step(w, modo="confirmar")
        finally:
            w.close()
        self.assertEqual(got, ("error", "¿seguro?", {"action": "seguir", "label": "Seguir"}))

    def test_cancelar_mata_la_ejecucion(self):
        w = self.host.run_worker()

        async def go():
            step = Step(block_id="b1", kind="w.b", params={"a": 1.0, "modo": "dormir"},
                        inputs={}, input_hash="", workdir=self.tmp.name)

            async def progress(fraction, message):
                w.kill()                       # en cuanto empieza, Cancelar

            return await w.run(step, progress)

        self.assertEqual(asyncio.run(go()), ("cancelled", None))
        self.assertFalse(w._proc.alive())
        w.close()

    def test_si_el_caliente_muere_vuelve_a_arrancar(self):
        self.host._proc.kill()
        self.assertEqual(self.host.preview("w.b", {"a": 1.0}, {}), {"doble": 2.0})


class ProtocoloDeAcciones(Base):
    def test_la_accion_pasa_por_la_pizarra_y_block_type_va_en_el_trabajador(self):
        board = FakeBoard(self.remote)
        got = self.host.action("w.fijar", {}, {}, {"a": 5.0}, {}, board=board, block_id="b1")
        self.assertEqual(got, {"params": {"a": 5.0, "modo": "normal"}, "tipo": "Bloque W",
                               "clasifica": "desde el trabajador"})
        self.assertEqual(board.params["a"], 5.0)

    def test_un_valor_de_otro_tipo_no_se_guarda(self):
        board = FakeBoard(self.remote)
        with self.assertRaisesRegex(pack_host.HostError, "a tiene que ser un número"):
            self.host.action("w.fijar", {}, {}, {"a": "cinco"}, {}, board=board, block_id="b1")
        self.assertEqual(board.params["a"], 1.0)

    def test_el_motivo_de_un_fallo_como_en_proceso(self):
        with self.assertRaises(pack_host.HostError) as remote:
            self.host.action("w.roto", {}, {}, {}, {})
        with self.assertRaises(pack_host.HostError) as here:
            self.here.host.action("w.roto", {}, {}, {}, {})
        self.assertEqual(str(remote.exception), str(here.exception))

    def test_solo_la_api_de_p39(self):
        # lo que no es de la API de P39 vuelve al paquete como error, sin tocar la pizarra
        board = FakeBoard(self.remote)
        self.assertEqual(pack_host.BOARD_METHODS, {"block", "upstream", "set_params", "postits",
                                                   "add_postit", "clear_error", "block_file"})
        got = pack_host.WorkerProcess._answer({"call": "_board", "args": [], "cid": 1},
                                             lambda m, a: (_ for _ in ()).throw(
                                                 pack_host.HostError(f"la pizarra no tiene {m!r}")))
        self.assertEqual(got, {"reply_to": 1, "ok": False, "error": "la pizarra no tiene '_board'"})
        self.assertEqual(board.params["a"], 1.0)

    def test_una_peticion_mientras_espera_a_la_pizarra_se_atiende(self):
        # P109: contestando a la acción, el backend vuelve a pedir al mismo trabajador (en la
        # app, si un conector responde, con la caché vacía tras instalar). El cerrojo del
        # anfitrión es reentrante: el trabajador la atiende y la acción acaba, nunca se cuelga
        host, seen = self.host, []

        class Nested(FakeBoard):
            def block(self, block_id):
                seen.append((host.connector("w", "available"),
                             host.preview("w.b", {"a": 2.0, "modo": "normal"}, {})))
                return super().block(block_id)

        got = {}
        t = threading.Thread(target=lambda: got.setdefault("r", host.action(
            "w.fijar", {}, {}, {"a": 5.0}, {}, board=Nested(self.remote), block_id="b1")),
            daemon=True)
        t.start()
        t.join(timeout=30)
        if t.is_alive():
            host.close()                    # libera el hilo colgado
            self.fail("la acción se quedó colgada")
        self.assertEqual(got["r"]["params"]["a"], 5.0)
        self.assertTrue(seen)               # una por cada vez que pide el bloque
        self.assertEqual(set(map(repr, seen)), {repr((True, {"doble": 4.0}))})
        self.assertIs(host.connector("w", "available"), True)       # el canal sigue en orden

    def test_una_respuesta_de_otra_peticion_es_un_error_no_una_espera(self):
        import io

        class Proc:
            stdin = io.StringIO()
            stdout = io.StringIO('{"id": 7, "ok": true}\n')

            killed = False

            def poll(self):
                return 9 if self.killed else None

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                return 9

        w = pack_host.WorkerProcess.__new__(pack_host.WorkerProcess)
        w.proc, w.next_id, w.killed = Proc(), 0, False
        with self.assertRaisesRegex(pack_host.HostError, "fuera de orden"):
            w.request("connector", connector="w", method="available")
        self.assertFalse(w.alive())          # desordenado no sirve: el siguiente arranca otro


try:
    import socket
    import threading
    import time
    import urllib.request
    import uvicorn
    from websockets.sync.client import connect
    from unittest import mock
    from pizarra import blocks as blocks_mod
    from pizarra.server import create_app
    from pizarra.startup import bootstrap
    DEPS = True
except ImportError:                     # job básico del CI: solo biblioteca estándar
    DEPS = False


@unittest.skipUnless(DEPS, "faltan fastapi/uvicorn/websockets")
class _ProcesoLento:
    """Un trabajador caliente falso: `action` espera a `suelta`; `connector` contesta al momento."""
    def __init__(self):
        self.suelta = threading.Event()
        self.dentro = threading.Event()

    def alive(self):
        return True

    def request(self, op, **fields):
        if op == "action":
            self.dentro.set()
            self.suelta.wait(10)
            return {"ok": True, "result": None}
        return {"ok": True, "result": True}

    def close(self):
        pass


class DisponibleNuncaEspera(unittest.TestCase):
    """`available` se pregunta desde el bucle del servidor: con el trabajador ocupado en otra
    petición (una acción contra un Fusion con un diálogo abierto tarda un minuto) contesta al
    momento con lo último que se supo. Antes la app entera se paraba (e2e de v0.1.0)."""

    def test_con_el_trabajador_ocupado_contesta_al_momento_con_lo_ultimo(self):
        from types import SimpleNamespace
        from pizarra import connectors
        host = pack_host.WorkerHost(pack_host.WorkerSpec(python="x", worker_dir="x"), [])
        host._proc = lento = _ProcesoLento()
        reg = SimpleNamespace(connectors={"fusion": SimpleNamespace(id="fusion")}, host=host)
        connectors._cache.update(at=-1e9, value=frozenset(), registry=None)
        self.addCleanup(connectors._cache.update, at=-1e9, value=frozenset(), registry=None)
        self.assertEqual(connectors.available(reg, ttl=0), {"fusion"})
        hilo = threading.Thread(target=host.action, args=("a.b", {}, {}, {}, {}))
        hilo.start()
        self.addCleanup(hilo.join, 10)
        self.addCleanup(lento.suelta.set)
        self.assertTrue(lento.dentro.wait(5))
        with self.assertRaises(pack_host.HostBusy):
            host.connector("fusion", "available")
        t0 = time.monotonic()
        self.assertEqual(connectors.available(reg, ttl=0), {"fusion"})   # no «no disponible»
        self.assertLess(time.monotonic() - t0, 0.5)
        lento.suelta.set()
        hilo.join(10)
        self.assertEqual(connectors.available(reg, ttl=0), {"fusion"})


class AppConTrabajador(unittest.TestCase):
    """La app entera con los paquetes en el trabajador (P89): el backend no importa ninguno y
    ejecutar, la vista previa, una acción y los conectores van al trabajador."""

    @classmethod
    def setUpClass(cls):
        cls.saved = blocks_mod.REGISTRY
        cls.tmp = Path(tempfile.mkdtemp())
        write_test_pack(cls.tmp / "packs")
        start = bootstrap(cls.tmp / "settings.toml", cls.tmp / "Documentos" / "Personal", ())
        cls.project = start.workspace.create_project("", "Proyecto").id
        start.settings.language = "es"        # los mensajes que se comprueban, en español (O16)
        with mock.patch.dict("os.environ", {packs.DEV_ENV: str(cls.tmp / "packs")}):
            app = create_app(start, worker_spec=pack_host.default_spec(stderr=subprocess.DEVNULL))
        cls.reg = blocks_mod.REGISTRY
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
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
        cls.reg.host.close()
        blocks_mod.REGISTRY = cls.saved

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_el_registro_es_del_trabajador(self):
        self.assertIsInstance(self.reg.host, pack_host.WorkerHost)
        self.assertIn("w.b", self.reg)
        self.assertIs(self.reg["w.b"].run, pack_data.REMOTE)   # el backend no tiene su código

    def test_ejecutar_vista_previa_accion_y_conector(self):
        st, got = self.post(f"/api/projects/{self.project}/blocks", {"type": "w.b", "x": 0, "y": 0})
        self.assertEqual(st, 200)
        bid = got["id"]
        with connect(f"ws://127.0.0.1:{self.port}/ws?project={self.project}", open_timeout=5) as ws:
            json.loads(ws.recv(timeout=10))                       # init
            ws.send(json.dumps({"type": "run", "block": bid}))
            while True:
                msg = json.loads(ws.recv(timeout=60))
                if msg["type"] == "run_finished":
                    break
        self.assertEqual(msg["done"], [bid], msg)
        st, got = self.post(f"/api/projects/{self.project}/blocks/{bid}/preview", {"params": {"a": 4}})
        self.assertEqual((st, got), (200, {"doble": 8}))
        st, got = self.post(f"/api/projects/{self.project}/blocks/{bid}/preview", {"params": {"a": -1}})
        self.assertEqual((st, got["detail"]), (422, "a no puede ser negativo"))
        st, got = self.post(f"/api/projects/{self.project}/blocks/{bid}/action",
                            {"name": "w.fijar", "args": {"a": 6.0}})
        self.assertEqual(st, 200, got)
        self.assertEqual(got["result"]["params"]["a"], 6.0)
        st, got = self.post(f"/api/projects/{self.project}/blocks/{bid}/action",
                            {"name": "w.fijar", "args": {"a": "seis"}})
        self.assertEqual(st, 422)                                  # la validación de la tarjeta
        from pizarra import connectors as connectors_mod
        self.assertIn("w", connectors_mod.available(self.reg, ttl=0))


if __name__ == "__main__":
    unittest.main()
