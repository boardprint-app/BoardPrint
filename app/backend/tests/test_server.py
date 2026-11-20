"""Servidor real (uvicorn + WebSocket) contra los hallazgos de la revisión de FF 3.3 (R6).

Necesita fastapi, uvicorn y websockets (app/backend/requirements.txt); sin ellos se salta.
El agente se sustituye por uno falso: no se llama a Claude.
"""
import asyncio
import json
from urllib.parse import quote
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

try:
    import uvicorn
    from websockets.sync.client import connect
    from pizarra import agent as agent_mod
    from pizarra import desktop as desktop_mod
    from pizarra.server import create_app
    from pizarra.startup import bootstrap
    DEPS = True
except ImportError:                     # job básico del CI: solo biblioteca estándar
    DEPS = False

from tests.helpers import necesita_paquetes


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AgenteLento:
    """Sustituto de DesignAgent: tarda un poco y cuenta cuántas preguntas hay a la vez."""
    activos = 0
    maximo = 0

    def __init__(self, *a, **k):
        pass

    async def ask(self, message, emit):
        AgenteLento.activos += 1
        AgenteLento.maximo = max(AgenteLento.maximo, AgenteLento.activos)
        await asyncio.sleep(0.5)
        AgenteLento.activos -= 1
        await emit({"kind": "done", "turns": 1, "seconds": 0.5})


class AgenteConHerramientas:
    """Sustituto de DesignAgent que usa lo que el servidor le da para `ver_zona` y
    `ejecutar_bloque` (D170, D171): pide la zona de `bloque` a la ventana y lo ejecuta."""
    bloque = None

    def __init__(self, board, on_elements, **k):
        self.run_block, self.request_zone = k["run_block"], k["request_zone"]

    async def ask(self, message, emit):
        png = await self.request_zone({"elements": [self.bloque], "maxSide": 1568,
                                       "excludeImages": False})
        await emit({"kind": "text", "text": f"zona {len(png)}"})
        await emit({"kind": "text", "text": json.dumps(await self.run_block(self.bloque))})
        await emit({"kind": "done", "turns": 1, "seconds": 0.1})


@unittest.skipUnless(DEPS, "faltan fastapi/uvicorn/websockets")
class ServidorReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._real_agent = agent_mod.DesignAgent
        agent_mod.DesignAgent = AgenteLento
        cls.port = _free_port()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.trashed = []
        start = bootstrap(cls.tmp / "settings.toml", cls.tmp / "Documentos" / "Personal", (),
                          trash=cls.trashed.append)
        cls.workspace = start.workspace
        start.settings.privacy_seen = True      # el aviso (D169) lo prueba test_agent_chat.py
        cls.project = start.workspace.create_project("", "Proyecto").id
        cls.otro = start.workspace.create_project("", "Otro").id
        start.settings.language = "es"        # los mensajes que se comprueban, en español (O16)
        app = create_app(start)
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
        agent_mod.DesignAgent = cls._real_agent

    def ws(self, origin=None, project=None):
        headers = {"Origin": origin} if origin else None
        c = connect(f"ws://127.0.0.1:{self.port}/ws?project={project or self.project}",
                    additional_headers=headers, open_timeout=5)
        self.assertEqual(json.loads(c.recv(timeout=5))["type"], "init")
        return c

    def api(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None
                                            else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def quiet(self, c, kind, timeout=0.6):
        """Comprueba que NO llega ningún mensaje de ese tipo en un rato."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                msg = json.loads(c.recv(timeout=timeout))
            except TimeoutError:
                return
            self.assertNotEqual(msg["type"], kind, msg)

    # ---------------------------------------------------- WebSocket por proyecto (D69)
    def test_un_cambio_llega_a_las_ventanas_del_mismo_proyecto_y_nunca_a_otro(self):
        a, b, c = self.ws(), self.ws(), self.ws(project=self.otro)
        el = {"id": "nota-1", "type": "text", "version": 1, "text": "hola"}
        a.send(json.dumps({"type": "scene", "elements": [el]}))
        self.assertEqual(self.recv_type(b, "elements")["elements"], [el])
        self.recv_type(a, "saved")
        self.quiet(a, "elements")                 # sin eco a quien lo mandó
        self.quiet(c, "elements")
        for x in (a, b, c):
            x.close()

    def test_un_proyecto_que_no_existe_se_contesta_y_se_cierra(self):
        c = connect(f"ws://127.0.0.1:{self.port}/ws?project=no-existe", open_timeout=5)
        msg = json.loads(c.recv(timeout=5))
        self.assertEqual((msg["type"], msg["reason"]), ("project_closed", "missing"))
        with self.assertRaises(Exception):
            c.recv(timeout=5)

    def test_abrir_un_proyecto_lo_deja_como_el_ultimo(self):
        self.ws(project=self.otro).close()
        status, body = self.api("GET", "/api/start")
        self.assertEqual(json.loads(body)["project"], self.otro)

    def test_borrar_un_proyecto_abierto_avisa_a_su_ventana_y_va_a_la_papelera(self):
        pid = self.workspace.create_project("", "Para borrar").id
        c = self.ws(project=pid)
        status, _ = self.api("DELETE", f"/api/projects/{pid}")
        self.assertEqual(status, 200)
        self.assertEqual(self.recv_type(c, "project_closed")["reason"], "trashed")
        self.assertTrue(any(str(p).endswith("Para borrar") for p in self.trashed))

    # ------------------------------------------------------ REST de carpetas y proyectos
    def test_errores_del_almacenamiento_con_su_codigo(self):
        self.assertEqual(self.api("POST", "/api/folders", {"name": "a:b"})[0], 422)
        self.assertEqual(self.api("POST", "/api/folders", {"name": "Carpeta REST"})[0], 200)
        self.assertEqual(self.api("POST", "/api/folders", {"name": "carpeta rest"})[0], 409)
        self.assertEqual(self.api("POST", "/api/projects",
                                  {"folder": "no-existe", "name": "X"})[0], 404)
        self.assertEqual(self.api("POST", "/api/folders",
                                  {"parent": "../..", "name": "X"})[0], 422)

    def test_abrir_en_el_explorador_nunca_sale_del_workspace(self):
        abiertas = []
        real = desktop_mod.reveal
        desktop_mod.reveal = abiertas.append
        self.addCleanup(setattr, desktop_mod, "reveal", real)
        self.assertEqual(self.api("POST", "/api/reveal", {"project": self.project})[0], 200)
        self.assertEqual(self.api("POST", "/api/reveal", {"folder": ""})[0], 200)
        self.assertEqual(self.api("POST", "/api/reveal", {"folder": "../.."})[0], 422)
        self.assertEqual(self.api("POST", "/api/reveal", {"project": "no-existe"})[0], 404)
        self.assertEqual([Path(p).name for p in abiertas], ["Proyecto", "Personal"])

    def test_los_recientes_traen_su_fecha_para_la_pantalla_de_inicio(self):
        self.ws().close()
        recent = json.loads(self.api("GET", "/api/workspace")[1])["recent"]
        self.assertGreater(next(r for r in recent if r["id"] == self.project)["modified"], 0)

    def test_el_skin_se_elige_y_nunca_se_guarda_uno_que_no_existe(self):
        self.assertEqual(self.api("PUT", "/api/settings/skin", {"skin": "neon"})[0], 422)
        self.assertEqual(json.loads(self.api("GET", "/api/start")[1])["skin"], "escuela")
        self.assertEqual(self.api("PUT", "/api/settings/skin", {"skin": "cad"})[0], 200)
        self.assertEqual(json.loads(self.api("GET", "/api/start")[1])["skin"], "cad")
        self.api("PUT", "/api/settings/skin", {"skin": "escuela"})

    def test_los_ajustes_son_todo_o_nada_y_llegan_a_las_demas_ventanas(self):
        # D179: una clave que no vale rechaza todo el cambio, también la que sí valía
        settings = Path(self.tmp / "settings.toml")
        before = settings.read_bytes() if settings.exists() else b""
        status, body = self.api("PUT", "/api/settings",
                                {"ventana": {"modo": "ventana", "escala": 999}})
        self.assertEqual(status, 422)
        self.assertIn("escala", json.loads(body)["detail"])
        self.assertEqual(settings.read_bytes() if settings.exists() else b"", before)
        self.assertEqual(json.loads(self.api("GET", "/api/settings")[1])["ventana"]["modo"],
                         "maximizada")
        c = self.ws()
        try:
            status, body = self.api("PUT", "/api/settings", {"ventana": {"escala": 120}})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["ventana"]["escala"], 120)
            deadline = time.time() + 5
            while time.time() < deadline:
                if json.loads(c.recv(timeout=5)).get("type") == "settings":
                    break
            else:
                self.fail("no llegó el aviso de ajustes")
        finally:
            c.close()
            self.api("PUT", "/api/settings", {"ventana": {"escala": 100}})

    def test_el_ancho_del_panel_derecho_nunca_se_guarda_bajo_el_minimo(self):
        # D60, D174: arrastrar el borde por debajo de 320 px guarda 320
        status, body = self.api("PUT", "/api/settings/panels", {"right": 200})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["right"], 320)
        self.assertEqual(json.loads(self.api("GET", "/api/settings/panels")[1])["right"], 320)
        self.assertEqual(self.api("PUT", "/api/settings/panels", {"right": "ancho"})[0], 422)
        self.assertEqual(json.loads(self.api("PUT", "/api/settings/panels", {"right": 480})[1])["right"], 480)
        self.assertEqual(json.loads(self.api("GET", "/api/settings/panels")[1]),
                         {"right": 480, "right_min": 320})

    def test_el_usuario_crea_un_post_it_y_llega_a_su_ventana(self):
        with self.ws() as c:
            self.assertEqual(self.api("POST", f"/api/projects/{self.project}/postits",
                                      {"kind": "chiste"})[0], 422)
            code, body = self.api("POST", f"/api/projects/{self.project}/postits",
                                  {"kind": "riesgo", "x": 5, "y": 6})
            self.assertEqual(code, 200)
            pid = json.loads(body)["id"]
            els = self.recv_type(c, "elements")["elements"]
            self.assertEqual([(e["id"], e["customData"]["author"]) for e in els],
                             [(pid, "user")])

    def test_una_propuesta_del_agente_llega_y_se_acepta_por_el_websocket(self):
        with self.ws() as c:
            code, body = self.api("POST", f"/api/projects/{self.project}/postits", {"kind": "nota"})
            nid = json.loads(body)["id"]
            self.recv_type(c, "elements")
            self.assertEqual(self.api("POST", f"/api/projects/{self.project}/agent/proposal",
                                      {"target": nid, "change": {"x": 1}, "reason": "x"})[0], 422)
            code, body = self.api("POST", f"/api/projects/{self.project}/agent/proposal",
                                  {"target": nid, "change": {"text": "Concreta la brida"},
                                   "reason": "Para el bloque de montaje"})
            self.assertEqual(code, 200)
            pid = json.loads(body)["id"]
            props = []
            while not props:                    # antes llega el de la creación del post-it
                props = self.recv_type(c, "proposals")["proposals"]
            (v,) = props
            self.assertEqual((v["id"], v["stale"], v["current"]), (pid, False, {"text": ""}))
            c.send(json.dumps({"type": "proposal_accept", "id": pid, "seen": {"text": "otro"}}))
            self.assertIn("ha cambiado", self.recv_type(c, "error")["message"])
            c.send(json.dumps({"type": "proposal_accept", "id": pid, "seen": v["current"]}))
            (el,) = self.recv_type(c, "elements")["elements"]
            self.assertEqual((el["customData"]["text"], el["customData"]["author"]),
                             ("Concreta la brida", "user"))
            self.assertEqual(self.recv_type(c, "proposals")["proposals"], [])

    def test_guardar_restaurar_y_comparar_versiones(self):
        base = f"/api/projects/{self.project}"
        with self.ws() as c:
            self.assertEqual(self.api("POST", f"{base}/versions", {"name": "a/b"})[0], 422)
            code, body = self.api("POST", f"{base}/versions", {"name": "Antes de la nota"})
            self.assertEqual(code, 200)
            vid = quote(json.loads(body)["id"])
            self.recv_type(c, "versions")
            nid = json.loads(self.api("POST", f"{base}/postits", {"kind": "nota"})[1])["id"]
            code, body = self.api("GET", f"{base}/compare?a={vid}&b=now")
            self.assertEqual([(x["change"], x["id"]) for x in json.loads(body)["changes"]],
                             [("added", nid)])
            code, body = self.api("POST", f"{base}/versions/{vid}/restore")
            self.assertEqual(json.loads(body)["auto"]["name"], "antes de restaurar «Antes de la nota»")
            init = self.recv_type(c, "init")
            self.assertNotIn(nid, [e["id"] for e in init["elements"] if not e.get("isDeleted")])
            names = [v["name"] for v in json.loads(self.api("GET", f"{base}/versions")[1])["versions"]]
            self.assertEqual(names, ["antes de restaurar «Antes de la nota»", "Antes de la nota"])
            self.assertEqual(self.api("POST", f"{base}/versions/no-existe/restore")[0], 404)

    def test_la_miniatura_solo_acepta_png(self):
        self.assertEqual(self.api("PUT", f"/api/projects/{self.project}/thumbnail",
                                  raw=b"<svg/>")[0], 422)
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        self.assertEqual(self.api("PUT", f"/api/projects/{self.project}/thumbnail",
                                  raw=png)[0], 200)
        self.assertEqual(self.api("GET", f"/api/projects/{self.project}/thumbnail"),
                         (200, png))

    def recv_type(self, c, kind, timeout=5):
        t0 = time.time()
        while time.time() - t0 < timeout:
            msg = json.loads(c.recv(timeout=timeout))
            if msg["type"] == kind:
                return msg
        self.fail(f"no llegó ningún mensaje {kind}")

    # ------------------------------------------------- ejecución en segundo plano (D92)
    def test_ejecutar_va_en_un_proceso_aparte_y_llega_bloque_a_bloque_a_las_ventanas(self):
        pid = self.workspace.create_project("", "Ejecutar").id
        with self.ws(project=pid) as a, self.ws(project=pid) as b:
            code, body = self.api("POST", f"/api/projects/{pid}/blocks", {"type": "prueba.tubo"})
            bid = json.loads(body)["id"]
            a.send(json.dumps({"type": "run", "block": bid}))
            seen = set()
            while True:                          # en cola o ejecutando, y luego al día
                msg = self.recv_type(b, "blocks", timeout=20)
                seen.add(msg["blocks"][bid]["status"])
                if msg["run"] is None and msg["blocks"][bid]["status"] == "al_dia":
                    break
            self.assertTrue(seen & {"en_cola", "ejecutando"}, seen)
            out = msg["blocks"][bid]["outputs"]["tubo"]
            self.assertGreater(out["masa"]["value"], 0)
            done = self.recv_type(a, "run_finished", timeout=10)
            self.assertEqual((done["done"], done["cancelled"]), ([bid], False))
            self.assertEqual(self.workspace.load_block_state(pid)[bid]["outputs"]["tubo"]["od"]
                             ["value"], 40, "guardado en disco")

    def test_cancelar_sin_ejecucion_y_dos_ejecuciones_a_la_vez_se_rechazan(self):
        pid = self.workspace.create_project("", "Una a la vez").id
        with self.ws(project=pid) as c:
            c.send(json.dumps({"type": "cancel"}))
            self.assertIn("ninguna ejecución", self.recv_type(c, "error")["message"])
            code, body = self.api("POST", f"/api/projects/{pid}/blocks", {"type": "prueba.tubo"})
            bid = json.loads(body)["id"]
            c.send(json.dumps({"type": "run", "block": bid}))
            c.send(json.dumps({"type": "run", "block": bid}))
            self.assertIn("en curso", self.recv_type(c, "error", timeout=10)["message"])
            self.recv_type(c, "run_finished", timeout=20)

    def test_traer_y_aplicar_contestan_con_su_motivo(self):
        # D116: un bloque que no existe, o aplicar sin haber traído, es un 4xx con el motivo
        # Son las acciones del conector del bloque (PLAN_PAQUETES P57)
        base = f"/api/projects/{self.project}/blocks"
        code, body = self.api("POST", f"{base}/no_existe/action", {"name": "fusion.pull"})
        self.assertEqual(code, 422)
        self.assertIn("no_existe", json.loads(body)["detail"])
        code, body = self.api("POST", f"{base}/no_existe/action",
                              {"name": "fusion.apply", "args": {"decisions": {}}})
        self.assertEqual(code, 422)

    @necesita_paquetes
    def test_un_conector_o_una_accion_que_no_existe_es_un_404(self):
        # P38: el núcleo solo enruta lo que declara un paquete
        self.assertIn("fusion", json.loads(self.api("GET", "/api/connectors")[1]))
        for method, path in (("GET", "/api/connectors/no_existe/destinations"),
                             ("GET", "/api/connectors/fusion/no_existe"),
                             ("POST", "/api/connectors/no_existe/launch")):
            with self.subTest(path=path):
                self.assertEqual(self.api(method, path)[0], 404)

    def test_abrir_un_archivo_de_salida_nunca_sale_del_bloque(self):
        abiertos = []
        real = desktop_mod.open_file
        desktop_mod.open_file = abiertos.append
        self.addCleanup(setattr, desktop_mod, "open_file", real)
        d = self.workspace.block_scratch(self.project, "b1")
        (d / "informe.html").write_text("<p>", encoding="utf-8")
        self.workspace.commit_block_files(self.project, "b1", d)
        base = f"/api/projects/{self.project}/blocks"
        self.assertEqual(self.api("POST", f"{base}/b1/open", {"file": "informe.html"})[0], 200)
        self.assertEqual(self.api("POST", f"{base}/b1/open", {"file": "../state.json"})[0], 422)
        self.assertEqual(self.api("POST", f"{base}/b1/open", {"file": "no.html"})[0], 404)
        self.assertEqual(self.api("POST", f"{base}/..%2F..%2Fx/open", {"file": "a"})[0] // 100, 4)
        self.assertEqual([Path(p).name for p in abiertos], ["informe.html"])

    def test_los_archivos_de_un_bloque_nunca_se_sirven_fuera_de_su_carpeta(self):
        d = self.workspace.block_scratch(self.project, "b1")
        (d / "captura.png").write_bytes(b"\x89PNG")
        self.workspace.commit_block_files(self.project, "b1", d)
        base = f"/api/projects/{self.project}/blocks"
        self.assertEqual(self.api("GET", f"{base}/b1/files/captura.png"), (200, b"\x89PNG"))
        self.assertEqual(self.api("GET", f"{base}/b1/files/..%2Fstate.json")[0] // 100, 4)
        self.assertEqual(self.api("GET", f"{base}/b1/files/..%5C..%5Cproject.toml")[0] // 100, 4)
        self.assertEqual(self.api("GET", f"{base}/b1/files/no.png")[0], 404)
        self.assertEqual(self.api("GET", f"{base}/..%2F..%2Fx/files/a")[0] // 100, 4)

    def test_mensajes_mal_formados_no_cierran_la_conexion(self):
        c = self.ws()
        for malo in ("no es json", "[1]", json.dumps({"type": "scene", "elements": [1]}),
                     json.dumps({"type": "set_params", "block": "x", "params": [1]}),
                     json.dumps({"type": "desconocido"})):
            c.send(malo)
            self.assertEqual(self.recv_type(c, "error")["type"], "error", malo)
        c.send(b"\x00\x01binario")
        self.recv_type(c, "error")
        c.send(json.dumps({"type": "scene", "elements": []}))
        self.recv_type(c, "blocks")             # sigue viva y atendiendo
        c.close()

    def test_una_web_de_otro_origen_no_puede_abrir_el_websocket(self):
        with self.assertRaises(Exception):
            self.ws(origin="https://web-maliciosa.example")
        self.ws(origin="http://localhost:5173").close()

    def test_nunca_hay_dos_preguntas_al_agente_a_la_vez(self):
        AgenteLento.maximo = 0
        a, b = self.ws(), self.ws()
        a.send(json.dumps({"type": "agent_ask", "text": "uno"}))
        b.send(json.dumps({"type": "agent_ask", "text": "dos"}))
        time.sleep(1.2)
        self.assertEqual(AgenteLento.maximo, 1)
        a.close()
        b.close()

    def test_el_agente_ve_la_zona_que_pinta_una_ventana_y_ejecuta_como_el_boton(self):
        from tests.test_agent_board_tools import png
        pid = self.workspace.create_project("", "Herramientas").id
        code, body = self.api("POST", f"/api/projects/{pid}/blocks", {"type": "prueba.tubo"})
        AgenteConHerramientas.bloque = bid = json.loads(body)["id"]
        agent_mod.DesignAgent = AgenteConHerramientas
        try:
            texts = []
            with self.ws(project=pid) as a:
                a.send(json.dumps({"type": "agent_ask", "text": "mira y ejecuta"}))
                req = self.recv_type(a, "zone_request")
                self.assertEqual(req["elements"], [bid])
                a.send(json.dumps({"type": "zone_image", "id": req["id"], "png": png(8, 8)}))
                while (msg := self.recv_type(a, "agent", timeout=30))["kind"] != "done":
                    self.assertNotEqual(msg["kind"], "error", msg)
                    if msg["kind"] == "text":
                        texts.append(msg["text"])
        finally:
            agent_mod.DesignAgent = AgenteLento
        self.assertEqual(texts[0], f"zona {len(png(8, 8))}")
        done = json.loads(texts[1])
        self.assertEqual((done["type"], done["done"], done["cancelled"]),
                         ("run_finished", [bid], False))
        self.assertIsNotNone(self.workspace.load_block_state(pid)[bid].get("outputs"))

    def test_el_chat_del_agente_se_guarda_y_otra_ventana_lo_pide(self):
        # D164: init trae el consumo y el tope; el chat se pide con agent_history
        pid = self.workspace.create_project("", "Con chat").id
        with connect(f"ws://127.0.0.1:{self.port}/ws?project={pid}", open_timeout=5) as a:
            init = json.loads(a.recv(timeout=5))
            self.assertEqual((init["agent"]["limit"], init["agent"]["busy"]), (5.0, False))
            a.send(json.dumps({"type": "agent_ask", "text": "hola"}))
            while self.recv_type(a, "agent")["kind"] != "done":
                pass
        with self.ws(project=pid) as b:
            b.send(json.dumps({"type": "agent_history"}))
            events = self.recv_type(b, "agent_history")["events"]
        self.assertEqual([(e["kind"], e.get("text")) for e in events],
                         [("user", "hola"), ("done", None)])
        status, body = self.api("GET", f"/api/projects/{pid}/agent")
        self.assertEqual((status, json.loads(body)["usage"]["total"]["messages"]), (200, 1))

    def test_un_hilo_por_el_websocket_llega_a_las_ventanas_y_sigue_en_init(self):
        # D165, D166: los eventos del hilo llevan su id; el tamaño va solo a las otras
        pid = self.workspace.create_project("", "Con hilos").id
        code, body = self.api("POST", f"/api/projects/{pid}/postits", {"kind": "nota"})
        postit = json.loads(body)["id"]
        with self.ws(project=pid) as a, self.ws(project=pid) as b:
            a.send(json.dumps({"type": "thread_create", "anchors": [postit], "text": "¿y esto?"}))
            tid = self.recv_type(a, "thread_created")["thread"]["id"]
            ev = self.recv_type(b, "agent")
            self.assertEqual((ev["kind"], ev["thread"], ev["text"]), ("user", tid, "¿y esto?"))
            while self.recv_type(b, "agent")["kind"] != "done":
                pass
            a.send(json.dumps({"type": "thread_layout", "id": tid, "layout": {"size": "min"}}))
            self.assertEqual(self.recv_type(b, "thread_layout")["layout"]["size"], "min")
            self.quiet(a, "thread_layout")
        with self.ws(project=pid) as c:
            c.send(json.dumps({"type": "thread_history", "id": tid}))
            msg = self.recv_type(c, "thread_history")
        self.assertEqual([e["kind"] for e in msg["events"]], ["user", "done"])
        self.assertEqual((msg["thread"]["layout"]["size"], msg["thread"]["sin_anclaje"]),
                         ("min", False))
        with connect(f"ws://127.0.0.1:{self.port}/ws?project={pid}", open_timeout=5) as d:
            init = json.loads(d.recv(timeout=5))
        self.assertEqual([t["id"] for t in init["threads"]], [tid])

    def test_sin_documentacion_publica_de_la_api(self):
        for path in ("/docs", "/openapi.json"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=3)
            self.assertEqual(cm.exception.code, 404)

    # ------------------------------------------------- tarjetas de archivo (FF 4.8, D59)
    def test_tarjetas_de_archivo_se_anaden_se_sondean_y_se_abren(self):
        pid = self.workspace.create_project("", "Archivos").id
        d = Path(tempfile.mkdtemp())
        (d / "sub").mkdir()
        doc = d / "motor.pdf"
        doc.write_bytes(b"%PDF")
        (d / "sub" / "ficha.pdf").write_bytes(b"%PDF")
        c = self.ws(project=pid)
        status, body = self.api("POST", f"/api/projects/{pid}/cards",
                                {"paths": [str(doc), str(d)], "x": 10, "y": 20})
        self.assertEqual(status, 200, body)
        fid, did = json.loads(body)["ids"]
        msg = self.recv_type(c, "blocks")
        while not msg["sources"].get(fid, {}).get("checked"):
            msg = self.recv_type(c, "blocks")
        self.assertTrue(msg["sources"][fid]["ok"])
        self.assertEqual(msg["sources"][did]["files"], 2)

        status, body = self.api("GET", f"/api/projects/{pid}/cards/{fid}")
        info = json.loads(body)
        self.assertEqual((info["name"], info["type"], Path(info["path"])),
                         ("motor.pdf", "archivo.pdf", doc))
        status, body = self.api("GET", f"/api/projects/{pid}/cards/{did}/content")
        self.assertEqual([e["path"] for e in json.loads(body)["entries"]],
                         ["sub", "motor.pdf", "sub/ficha.pdf"])

        abiertos, real = [], desktop_mod.open_file
        desktop_mod.open_file = abiertos.append
        try:
            status, _ = self.api("POST", f"/api/projects/{pid}/cards/{fid}/open", {})
        finally:
            desktop_mod.open_file = real
        self.assertEqual((status, abiertos), (200, [doc]))
        status, _ = self.api("GET", f"/api/projects/{pid}/cards/no-existe")
        self.assertEqual(status, 404)
        c.close()

    def test_previsualizar_sirve_solo_el_archivo_de_una_tarjeta(self):
        pid = self.workspace.create_project("", "Vista previa").id
        d = Path(tempfile.mkdtemp())
        (d / "ficha.pdf").write_bytes(b"%PDF-1.4 hola")
        (d / "informe.html").write_text("<script>alert(1)</script>", encoding="utf-8")
        status, body = self.api("POST", f"/api/projects/{pid}/cards",
                                {"paths": [str(d / "ficha.pdf"), str(d / "informe.html"), str(d)]})
        pdf, html, folder = json.loads(body)["ids"]
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/projects/{pid}/cards/{pdf}/raw",
                                    timeout=5) as r:
            self.assertEqual((r.read(), r.headers["Content-Type"]), (b"%PDF-1.4 hola", "application/pdf"))
            self.assertEqual(r.headers["Content-Disposition"], "inline")
            self.assertIsNone(r.headers["Content-Security-Policy"], "el visor de PDF necesita su plugin")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/projects/{pid}/cards/{html}/raw",
                                    timeout=5) as r:
            self.assertEqual(r.headers["Content-Security-Policy"], "sandbox", "un HTML nunca ejecuta nada")
        self.assertEqual(self.api("GET", f"/api/projects/{pid}/cards/{folder}/raw")[0], 422)
        self.assertEqual(self.api("GET", f"/api/projects/{pid}/cards/no-existe/raw")[0], 404)
        (d / "ficha.pdf").unlink()
        self.assertEqual(self.api("GET", f"/api/projects/{pid}/cards/{pdf}/raw")[0], 404)

    def test_tomar_de_excel_enlaza_un_parametro_y_quitarlo_conserva_el_valor(self):
        # PLAN_EXCEL §3.2: la API de los enlaces, con el mismo motivo que la pizarra
        import openpyxl
        from openpyxl.workbook.defined_name import DefinedName
        pid = self.workspace.create_project("", "Excel").id
        path = Path(tempfile.mkdtemp()) / "datos.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Datos"
        wb["Datos"]["B3"], wb["Datos"]["B4"] = 0.3, 2.5
        wb.defined_names["L_m"] = DefinedName("L_m", attr_text="Datos!$B$3")
        wb.defined_names["masa_kg"] = DefinedName("masa_kg", attr_text="Datos!$B$4")
        wb.save(path)
        bid = json.loads(self.api("POST", f"/api/projects/{pid}/blocks", {"type": "prueba.tubo"})[1])["id"]
        cid = json.loads(self.api("POST", f"/api/projects/{pid}/cards", {"paths": [str(path)]})[1])["ids"][0]
        url = f"/api/projects/{pid}/blocks/{bid}/links"
        status, body = self.api("POST", url, {"param": "L", "card": cid, "name": "L_m"})
        self.assertEqual(status, 200, body)
        link = json.loads(body)["links"]["L"]
        self.assertEqual((link["value"], link["where"]), (300, "Datos!B3"))
        self.assertEqual(self.workspace.load_block_state(pid)[bid]["links"],
                         {"L": {"card": cid, "name": "L_m"}}, "guardado")
        status, body = self.api("POST", url, {"param": "t", "card": cid, "name": "masa_kg"})
        self.assertEqual(status, 422)
        self.assertIn("kg", json.loads(body)["detail"])
        status, body = self.api("POST", url, {"param": "L"})
        self.assertEqual((status, json.loads(body)["links"]), (200, {}))
        self.assertEqual(self.workspace.load_block_state(pid)[bid]["params"]["L"], 300)

    def test_la_cache_de_mallas_guarda_por_hash_y_nada_mas(self):
        digest = "ab" * 32
        self.assertEqual(self.api("GET", f"/api/mesh/{digest}")[0], 204, "no estar no es un error")
        status, _ = self.api("PUT", f"/api/mesh/{digest}", raw=b"\x01\x02malla")
        self.assertEqual(status, 200)
        self.assertEqual(self.api("GET", f"/api/mesh/{digest}"), (200, b"\x01\x02malla"))
        for bad in ("..%2F..%2Fsettings", "AB" * 32, "ab" * 31, "zz" * 32):
            try:
                status = self.api("PUT", f"/api/mesh/{bad}", raw=b"x")[0]
            except (ConnectionAbortedError, ConnectionResetError):
                # el servidor rechaza sin leer el cuerpo y cierra: en Windows el cliente a
                # veces ve la conexión cortada antes de leer el 404 (también es un rechazo)
                status = 404
            self.assertIn(status, (404, 422), bad)
        self.assertEqual(self.api("PUT", f"/api/mesh/{'cd' * 32}", raw=b"")[0], 422)

    def test_una_imagen_pegada_se_guarda_una_vez_y_sigue_al_reabrir(self):
        pid = self.workspace.create_project("", "Imágenes").id
        base = f"/api/projects/{pid}"
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        status, body = self.api("POST", f"{base}/images", raw=png)
        self.assertEqual(status, 200)
        name = json.loads(body)["file"]
        self.assertEqual(json.loads(self.api("POST", f"{base}/images", raw=png)[1])["file"], name)
        self.assertEqual(len(list(self.workspace.board_file(pid, name).parent.iterdir())), 1,
                         "la misma imagen pegada dos veces se guarda una vez")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{base}/images/{name}",
                                    timeout=5) as r:
            self.assertEqual((r.read(), r.headers["Content-Type"]), (png, "image/png"))
        # En un post-it (D140): llega por la escena y vuelve igual al reabrir el proyecto.
        c = self.ws(project=pid)
        el = {"id": "nota-img", "type": "embeddable", "version": 1,
              "link": "https://pizarra.local/postit/nota-img",
              "customData": {"kind": "postit", "postitKind": "nota", "state": "abierto",
                             "text": "La pinza de ahora", "author": "user",
                             "image": {"file": name, "width": 800, "height": 600}}}
        c.send(json.dumps({"type": "scene", "elements": [el]}))
        self.recv_type(c, "saved")
        c.close()
        again = self.ws(project=pid)
        again.close()
        saved = next(e for e in self.workspace.load_scene(pid) if e["id"] == "nota-img")
        self.assertEqual(saved["customData"]["image"]["file"], name)
        self.assertEqual(saved["customData"]["text"], "La pinza de ahora")
        self.assertTrue(self.workspace.board_file(pid, name).is_file())

    def test_lo_que_no_es_una_imagen_o_no_esta_no_se_guarda_ni_se_sirve(self):
        base = f"/api/projects/{self.project}"
        for data in (b"<svg onload='alert(1)'/>", b"%PDF-1.4", b""):
            self.assertEqual(self.api("POST", f"{base}/images", raw=data)[0], 422, data)
        for bad in ("..%2Fscene.json", "AB" * 32 + ".png", "ab" * 32 + ".svg"):
            self.assertIn(self.api("GET", f"{base}/images/{bad}")[0], (404, 422), bad)
        self.assertEqual(self.api("GET", f"{base}/images/{'cd' * 32}.png")[0], 404)

    def test_una_animacion_se_sirve_aislada_y_sin_red(self):
        # D143, D175: la CSP va como cabecera (un `srcdoc` no la lleva), sin red, solo lo en
        # línea e imágenes data:, y con sandbox: su origen es opaco aunque se abra a mano.
        pid = self.workspace.create_project("", "Animaciones").id
        html = b"<!doctype html><script>1</script>"
        name = self.workspace.save_board_file(pid, html, "html")
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/animations/{pid}/{name}",
                                    timeout=5) as r:
            self.assertEqual(r.read(), html)
            self.assertTrue(r.headers["Content-Type"].startswith("text/html"))
            csp = r.headers["Content-Security-Policy"]
        for regla in ("default-src 'none'", "script-src 'unsafe-inline'",
                      "style-src 'unsafe-inline'", "img-src data:", "sandbox allow-scripts"):
            self.assertIn(regla, csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertNotIn("connect-src", csp, "connect-src cae en default-src 'none'")
        # Nunca por la ruta de las imágenes, ni otra cosa por la de las animaciones
        self.assertEqual(self.api("GET", f"/api/projects/{pid}/images/{name}")[0], 404)
        png = self.workspace.save_board_file(pid, b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "png")
        for bad in (png, "..%2Fscene.json", "AB" * 32 + ".html", "cd" * 32 + ".html"):
            self.assertEqual(self.api("GET", f"/animations/{pid}/{bad}")[0], 404, bad)
        self.assertEqual(self.api("GET", f"/animations/{'0' * 32}/{name}")[0], 404)

    def test_abrir_un_enlace_usa_la_url_de_la_escena_y_solo_http(self):
        pid = self.workspace.create_project("", "Enlaces").id
        c = self.ws(project=pid)
        links = [{"id": i, "type": "embeddable", "version": 1, "link": f"https://pizarra.local/link/{i}",
                  "customData": {"kind": "link", "url": url, "title": "x"}}
                 for i, url in (("bueno", "https://docs.google.com/d/1"), ("malo", "file:///C:/x.exe"))]
        c.send(json.dumps({"type": "scene", "elements": links}))
        self.recv_type(c, "saved")
        abiertos, real = [], desktop_mod.open_url
        desktop_mod.open_url = abiertos.append
        try:
            ok = self.api("POST", f"/api/projects/{pid}/links/bueno/open", {})[0]
            malo = self.api("POST", f"/api/projects/{pid}/links/malo/open", {})[0]
            nada = self.api("POST", f"/api/projects/{pid}/links/no-existe/open", {})[0]
        finally:
            desktop_mod.open_url = real
        self.assertEqual((ok, malo, nada), (200, 422, 422))
        self.assertEqual(abiertos, ["https://docs.google.com/d/1"])
        c.close()

    def test_cancelar_el_dialogo_no_anade_nada(self):
        real = desktop_mod.choose_files
        desktop_mod.choose_files = lambda *a, **k: []
        try:
            status, body = self.api("POST", f"/api/projects/{self.project}/cards", {"kind": "file"})
        finally:
            desktop_mod.choose_files = real
        self.assertEqual((status, json.loads(body)), (200, {"ids": [], "existing": []}))

    def test_anadir_otra_vez_un_archivo_que_ya_esta_nunca_crea_otra_tarjeta(self):
        doc = Path(tempfile.mkdtemp()) / "motor.pdf"
        doc.write_bytes(b"%PDF")
        status, body = self.api("POST", f"/api/projects/{self.project}/cards", {"paths": [str(doc)]})
        (fid,) = json.loads(body)["ids"]
        otro = doc.parent / "otro.pdf"
        otro.write_bytes(b"%PDF")
        status, body = self.api("POST", f"/api/projects/{self.project}/cards",
                                {"paths": [str(doc), str(otro), str(otro)]})
        got = json.loads(body)
        self.assertEqual(status, 200, body)
        self.assertEqual(got["existing"], [fid], "la que ya estaba vuelve para seleccionarla")
        self.assertEqual(len(got["ids"]), 1, "la nueva, una sola vez aunque llegue repetida")

    def test_una_ruta_arrastrada_que_no_existe_se_rechaza(self):
        status, _ = self.api("POST", f"/api/projects/{self.project}/cards",
                             {"paths": [str(Path(tempfile.mkdtemp()) / "no.pdf")]})
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()
