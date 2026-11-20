"""Servidor local de la pizarra.

Desarrollo (el frontend lo sirve Vite en :5173 con proxy a :8765, sin token):
    cd app/backend && ../../.venv/Scripts/python.exe -m pizarra.server

Empaquetado (lo arranca el shell de Tauri, plan §1, §8):
    pizarra-backend --port N --token T --settings FICHERO --documents DIR --engine-dir DIR
y la ventana carga http://127.0.0.1:N/?token=T. El backend sirve también la interfaz
compilada (`--web-dir`, por defecto la que va dentro del ejecutable). En desarrollo, sin
`--settings` ni `--documents`, todo vive en out/dev/ (D70).

Escucha solo en 127.0.0.1. Con `--token`, toda ruta /api y el WebSocket lo exigen
(cabecera `X-Token` o parámetro `token`): ningún otro proceso de la máquina maneja la app.

Protocolo del WebSocket `/ws?project=<id>` (JSON), uno por proyecto abierto (D69):
cliente -> servidor
    {"type": "scene", "elements": [...]}               elementos que cambiaron (versión)
    {"type": "set_params", "block": id, "params": {}}  edición de parámetros de un bloque
    {"type": "run", "block": id, "options"?}           ejecutar (con lo de delante, D89);
                                                       options: {acción: true} de una
                                                       confirmación, solo esta vez (D112)
    {"type": "run_stale"}                              ejecutar todo lo que no está al día
    {"type": "cancel"}                                 cancelar la ejecución en curso
    {"type": "proposal_accept", "id", "seen"}          aceptar una propuesta (D75); `seen`
                                                       es el «antes» que se enseñó
    {"type": "proposal_reject", "id"}                  rechazarla
    {"type": "agent_ask", "text", "once"?}             al agente de diseño; `once`: *Seguir solo
                                                       este mensaje* con el tope alcanzado (D168)
    {"type": "agent_stop"} | {"type": "agent_history"}   *Parar* | pedir el chat guardado (D164)
    {"type": "agent_privacy_ok"}                       *Entendido* del aviso (D169)
    {"type": "agent_settings", "limit"?, "exclude_attachments"?}   tope del proyecto en USD
                                                       (null: el de los ajustes) y adjuntos
    {"type": "zone_image", "id", "png" | "error"}      la respuesta a `zone_request`: el PNG en
                                                       base64 o el motivo (`zone.py`, D171)
  Hilos anclados (`agent_threads.py`, D165-D167). Una pregunta al agente a la vez por
  proyecto, contando chat e hilos; `agent_stop` para la que esté en curso, sea donde sea.
    {"type": "thread_create", "anchors": [id], "title"?, "text"?, "layout"?, "once"?}
                                                       crea el hilo (sin título, «Sobre …») y,
                                                       con `text`, le pregunta
    {"type": "thread_ask", "id", "text", "once"?}      pregunta en un hilo abierto o en revisión
    {"type": "thread_history", "id"}                   pedir sus mensajes
    {"type": "thread_layout", "id", "layout"}          {size: min|window|full, x, y, w, h}, sin
                                                       el agente; w y h nunca bajan del mínimo
    {"type": "thread_close_request", "id", "once"?}    *Cerrar con decisión*: el agente propone
    {"type": "thread_close", "id", "decision": {"text", "sources"?, "estimate"?}}
                                                       la guarda el usuario (D19: con cifras,
                                                       fuentes o estimate; si no, error)
    {"type": "thread_reopen", "id"} | {"type": "thread_delete", "id"}   en revisión | del todo
  Revisor (`agent_review.py`, FF 6.1). Comparte con el de diseño una pregunta a la vez por
  proyecto (`agent_busy`), la privacidad, el tope y `agent_stop`; nunca su chat ni su sesión.
    {"type": "review_ask", "foco"?, "once"?}           una revisión (con la intrusividad en
                                                       `apagado`, error); `foco`: en qué fijarse
    {"type": "review_cancel"}                          parar la revisión en curso
    {"type": "review_history"}                         pedir su conversación (agent/review.jsonl)
servidor -> cliente
    {"type": "init", "project", "elements", "blocks", "types", "agent", "review", "threads"}
                                                       `agent`: agent_state; `review`: review_state
                                                       sin `type`; `threads`, la lista
    {"type": "elements", "elements": [...]}            cambios de otra ventana del mismo
                                                       proyecto o del backend (agente, bloques)
    {"type": "saved", "at"}                            guardado (la píldora lo enseña)
    {"type": "blocks", "blocks", "problems", "run", "sources"}   estado de bloques y conexiones;
                                                       `run`, la ejecución en curso o null;
                                                       `sources`, el de las tarjetas de archivo
                                                       (`Board.sources_view`, sondeo cada ~5 s)
    {"type": "block_progress", "block", "fraction", "message"}   progreso del bloque en curso
    {"type": "run_finished", "done", "failed", "cancelled", "skipped", "error"?}
    {"type": "connectors", "connectors"}               Fusion abierto o no (D106): al cambiar
    {"type": "proposals", "proposals"}                 propuestas pendientes (D75)
    {"type": "versions"}                               la lista de versiones cambió (D76)
Restaurar una versión manda otra vez `init` (la escena entera) a todas las ventanas.
    {"type": "agent", "kind", "at", ...}               el chat, que se guarda (`agent_chat.py`):
                                                       user|text|tool|tool_result|done|error|
                                                       stopped|pack_proposal; sin guardar y solo
                                                       a quien preguntó, privacy y limit
    {"type": "agent_history", "events", "state"}       el chat guardado, a quien lo pidió
    {"type": "agent_state", ...}                       consumo, tope y ajustes (`agent_chat.state`);
                                                       `thread`: el hilo en curso o null;
                                                       `busy_agent`: diseno | revisor | null
    Los eventos `agent` del revisor llevan `"agent": "revisor"` (también sus tarjetas privacy y
    limit, con `foco` para reenviarlas con review_ask); su `user` lleva `foco` o `milestone`
    {version, name, previous: {id, name} | null, changes} si es de un hito.
    {"type": "review_history", "events", "state", "agent"}   a quien lo pidió (`state`: el
                                                       review_state; `agent`: el agent_state)
    {"type": "review_state", "intrusiveness", "model", "running", "postits"}   al acabar cada
                                                       revisión; postits: {abierto, aceptado,
                                                       descartado, total} de los del revisor
    Los eventos `agent` de un hilo llevan `"thread": <id>` (también sus tarjetas privacy y
    limit, que se reenvían con thread_ask o, con `close_request`, thread_close_request), y
    además: decision_proposal {decision} (`proponer_decision`), closed {decision}, reopened.
    {"type": "threads", "threads": [hilo]}             la lista, a todas, cuando cambia algo
                                                       (hilo: ver `agent_threads.py`, con
                                                       `missing` y `sin_anclaje` de la escena)
    {"type": "thread_created", "thread"}               a quien lo creó, antes de `threads`
    {"type": "thread_history", "id", "thread", "events"}   a quien lo pidió
    {"type": "thread_layout", "id", "layout"}          a las OTRAS ventanas del proyecto
    {"type": "zone_request", "id", "rect" | "elements", "maxSide", "excludeImages"}
                                                       `ver_zona` del agente (D171): a UNA
                                                       ventana, la que preguntó si sigue; sin
                                                       respuesta en 15 s, error al agente
    {"type": "project", "project"}                     renombrado o movido
    {"type": "project_closed", "reason"}               borrado: la ventana vuelve al inicio
    {"type": "error", "message"}
Un proyecto que no existe se contesta con `project_closed` y se cierra con el código 4404.

REST:
    GET    /api/health
    GET    /api/start                          qué abrir al arrancar (D63)
    GET|PUT /api/settings                      Ajustes (D179, `settings_api`): todo o nada;
                                               el cambio llega como {type: "settings"}
    GET|PUT /api/settings/panels {right}       ancho del panel derecho (D60, D174), nunca
                                               por debajo de `right_min` (320 px)
    GET    /api/workspace                      árbol, recientes y avisos
    POST   /api/folders {parent, name}         PATCH /api/folders {path, name | dest}
    DELETE /api/folders?path=…                 a la Papelera (D66)
    POST   /api/projects {folder, name}        PATCH /api/projects/<id> {name | dest}
    DELETE /api/projects/<id>                  a la Papelera (D66)
    DELETE /api/recent/<id>                    quitar de recientes
    POST   /api/reveal {project | folder}      abrir en el explorador del sistema
    GET|PUT /api/projects/<id>/thumbnail       miniatura PNG de la pantalla de inicio
    GET    /api/projects/<id>/board            lectura estructurada (`leer_pizarra`)
    GET    /api/projects/<id>/agent            consumo, tope y ajustes del agente (agent_state)
    POST   /api/projects/<id>/agent/postit     `crear_postit` validado (422 si incumple)
    POST   /api/projects/<id>/agent/proposal   `proponer_cambio` validado (422 si incumple)
    POST   /api/projects/<id>/blocks           crear un bloque {type, x, y}
    POST   /api/projects/<id>/blocks/<b>/open  abrir un archivo de salida {file} (D93)
    GET    /api/projects/<id>/blocks/<b>/files/<nombre>   un archivo de salida (miniatura, D114)
    POST   /api/projects/<id>/blocks/<b>/action {name, args}   acción de su paquete o de su
                                               conector (P40, P41): *Traer*, aplicar y fijar
                                               son `fusion.pull`, `fusion.apply`, `fusion.fix`
    GET    /packs/<id>/ui/<ruta>               interfaz propia de un paquete, sin token y con
                                               la CSP sin red (`pack_ui`, P24)
    POST   /api/projects/<id>/templates        poner una plantilla {template, x?, y?} (D91)
    GET|PUT /api/workspace/fabricacion          perfil de fabricación (V8): {texto, guardado,
                                               plantilla} | {texto} (422 si no vale)
    GET    /api/library…, POST /api/library/import/…   la librería del workspace y su stock
                                               (V14-V16): la lista, en `library_api`
    POST   /api/profile/export, /api/profile/import/…   exportar e importar el perfil .zip
                                               (PLAN_LIBRERIA L8-L10): en `profile_api`
    GET|PUT /api/supply/providers, /api/supply/offers…, /api/supply/search…   proveedores,
                                               ofertas y buscar (PLAN_APROVISIONAMIENTO): en
                                               `supply_api`
    GET|POST /api/projects/<id>/versions       versiones (D76): lista | guardar {name}; con la
                                               intrusividad en `hitos`, una con nombre lanza
                                               una revisión (V5)
    PATCH|DELETE /api/projects/<id>/versions/<v>   renombrar {name} | a la Papelera
    GET    /api/projects/<id>/versions/<v>/thumbnail
    POST   /api/projects/<id>/versions/<v>/restore   guarda antes la actual y restaura
    GET    /api/projects/<id>/compare?a=<v>&b=<v|now>  lista de cambios (pizarra/diff.py)
    GET    /api/connectors                     qué conectores hay y si están disponibles (D106)
    POST   /api/connectors/<c>/launch          *Abrir* su programa: {status: abierto | arrancando}
    GET|POST /api/connectors/<c>/<acción>      una acción de su paquete que no es de un bloque,
                                               sin el prefijo (`/api/connectors/fusion/destinations`
                                               es `fusion.destinations`): argumentos en la
                                               consulta o {args}; 502 si falla (P38)
    POST   /api/dialog/step                    diálogo del sistema para elegir un STEP (D129)
    /api/projects/<id>/cards…                  tarjetas de archivo y de carpeta (`files_api`)
    /api/projects/<id>/images…, …/links…       imágenes pegadas y enlaces (`files_api`)
    GET    /animations/<id>/<sha256>.html      la animación de un post-it (D175), sin token y
                                               con la CSP sin red (`files_api`)
Errores del almacenamiento: 422 nombre o ruta no válidos, 404 no existe, 409 choque.
"""
import argparse
from dataclasses import asdict
from urllib.parse import urlparse
import asyncio
import hmac
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pizarra import agent_chat, agent_review, agent_threads, blocks as blocks_mod
from pizarra import connectors as connectors_mod, desktop, execution, files_api, graph, scene, watchdog
from pizarra import agent_packs, pack_env, pack_host, pack_install, pack_install_api, pack_ui
from pizarra import (i18n, library_api, profile_api, settings_api, supply_api, update_api,
                     welcome, workspace_api)
from pizarra import packs as packs_mod
from pizarra.board import Board
from pizarra.config import AGENT_AUTHORS, APP_NAME
from pizarra.sessions import Sessions, send_all
from pizarra.startup import (DEFAULT_WORKSPACE, StartState, app_data_dir, bootstrap,
                             legacy_settings, pack_environment)
from pizarra.storage import Conflict, InvalidName, NotFound, StorageError
from pizarra.validation import ValidationError

PROBE_EVERY = 5               # s entre sondeos de las tarjetas de archivo (D134)
log = logging.getLogger(__name__)

FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
REPO = None if FROZEN else Path(__file__).resolve().parents[3]


class PostitIn(BaseModel):
    text: str
    kind: str = "nota"
    author: str = "agent:design"
    sources: list[dict] = []
    estimate: bool = False
    anchor: str | None = None
    x: float | None = None
    y: float | None = None


class BlockIn(BaseModel):
    type: str
    x: float = 0
    y: float = 0


class OpenIn(BaseModel):
    file: str


class ConnectorArgsIn(BaseModel):
    args: dict = {}


# Lo que puede ir en la CSP como origen del backend (`Host`: 127.0.0.1:8765, [::1]:8765)
HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d+)?$|^\[[0-9A-Fa-f:]+\](:\d+)?$")


class PreviewIn(BaseModel):
    params: dict = {}


class ActionIn(BaseModel):
    name: str
    args: dict = {}


class ProposalIn(BaseModel):
    target: str
    change: dict
    reason: str
    author: str = "agent:design"
    sources: list[dict] = []
    estimate: bool = False


class TemplateIn(BaseModel):
    template: str
    x: float | None = None
    y: float | None = None


class UserPostitIn(BaseModel):
    kind: str
    x: float = 0
    y: float = 0




def create_app(start: StartState, token=None, engine_dir=None, web_dir=None, claude_cli=None,
               worker_factory=None, worker_spec=None, restart=None):
    """`worker_factory(registry)` da el proceso de cálculo de cada ejecución (D92); por
    defecto, un `execution.ProcessWorker` que carga los mismos paquetes. `restart()` vuelve a
    arrancar el servidor en el mismo puerto (al cambiar de workspace, D186; `main`)."""
    settings, workspace = start.settings, start.workspace
    # Los mensajes del backend que ve el usuario, en el idioma de los ajustes (O16); al
    # cambiarlo, `settings_api` lo vuelve a poner.
    i18n.set_language(settings.language)
    # el de su anfitrión: en la app, un trabajador por ejecución (PLAN_PAQUETES P90)
    worker_factory = worker_factory or (lambda reg: reg.host.run_worker())
    sessions = Sessions(workspace) if workspace is not None else None
    connectors_mod.configure(engine_dir)        # el código de un conector lo importa en su programa
    if workspace is not None:                   # paquetes del usuario y del workspace (§3)
        is_env = isinstance(worker_spec, pack_env.PackEnvironment)
        reg = blocks_mod.configure(user_dir=Path(settings.path).parent / "packs",
                                   workspace_dir=workspace.root / packs_mod.WORKSPACE_PACKS,
                                   validated=Path(settings.path).parent / "cache"
                                   / "packs-validados.json",                       # P80
                                   worker=None if is_env else worker_spec,         # P89
                                   env=worker_spec if is_env else None)            # P92
        pack_install.clean(reg.origins)         # una instalación cortada (§7)
    # Sin /docs ni /openapi.json: no hacen falta y describen la API a cualquiera (R6).
    app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)

    def need_workspace():
        if workspace is None:
            raise HTTPException(503, start.problem or i18n.t("workspace.ninguno_abierto"))
        return workspace

    @app.exception_handler(StorageError)
    async def storage_error(_request, exc):
        code = {InvalidName: 422, NotFound: 404, Conflict: 409}.get(type(exc), 400)
        return JSONResponse({"detail": str(exc)}, status_code=code)

    def token_ok(value):
        return token is None or (value is not None and hmac.compare_digest(value, token))

    def origin_ok(origin):
        """Solo páginas servidas desde esta máquina. Sin esto, en desarrollo (sin token) cualquier
        web abierta en el navegador podría abrir el WebSocket y lanzar el agente (R6)."""
        if not origin:
            return True                       # clientes que no son un navegador
        return urlparse(origin).hostname in ("127.0.0.1", "localhost", "::1")

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            given = request.headers.get("X-Token") or request.query_params.get("token")
            if not token_ok(given):
                return JSONResponse({"detail": "token no válido"}, status_code=401)
        return await call_next(request)

    async def broadcast(session, msg, exclude=None):
        """A las ventanas de ese proyecto, y solo a ellas (D69); la que no lee, fuera."""
        await send_all(session.clients, msg, exclude)

    def blocks_msg(session):
        return {"type": "blocks", **session.board.blocks_view()}

    def proposals_msg(session):
        return {"type": "proposals", "proposals": session.board.proposals_view()}

    async def save_and_ack(session):
        session.board.save()
        await broadcast(session, {"type": "saved", "at": time.time()})

    async def close_sessions(project_ids, reason):
        """Antes de borrar: guarda, avisa a las ventanas y las cierra (D66)."""
        for s in sessions.close(project_ids):
            if s.worker is not None:          # el cálculo no sigue escribiendo en el proyecto
                s.worker.kill()
            for ws in list(s.clients):
                try:
                    await ws.send_json({"type": "project_closed", "reason": reason})
                    await ws.close(code=4410)
                except Exception:
                    pass
            s.clients.clear()

    def chat_for(session):
        """La conversación del agente de diseño del proyecto (`agent_chat`, D164)."""
        def make_agent():
            from pizarra.agent import DesignAgent

            async def on_elements(new):           # y el estado: puede ser un bloque nuevo
                await board_changed(session.board, session, new)
                if any((e.get("customData") or {}).get("animation") for e in new)                         and welcome.first_animation(workspace, session.project_id,
                                                    settings.animations_auto):
                    await broadcast(session, {"type": "animation_notice"})     # D187

            async def on_proposals():
                await broadcast(session, proposals_msg(session))

            async def run_block(block_id):
                """`ejecutar_bloque` (D170): la misma ejecución que el botón *Ejecutar*;
                espera a que acabe. *Parar* el agente no la corta: se cancela aparte."""
                await probe_now(session.board, session, fresh=True)
                task = start_run(session, block_id)
                await broadcast(session, blocks_msg(session))
                return await asyncio.shield(task)

            async def request_zone(payload):
                return await session.zones.request(session.clients, payload,
                                                   prefer=session.chat.asker)
            return DesignAgent(session.board, on_elements, cli_path=claude_cli,
                               on_proposals=on_proposals,
                               drafts=Path(settings.path).parent / agent_packs.DRAFTS,
                               run_block=run_block, request_zone=request_zone,
                               settings=settings)

        if session.chat is None:
            session.chat = agent_chat.AgentChat(
                session, workspace, settings, make_agent,
                broadcast=lambda m: broadcast(session, m), saved=lambda: save_and_ack(session),
                finished=lambda: sessions.agent_finished(session))
        return session.chat

    def review_for(session):
        """El revisor del proyecto (`agent_review`, FF 6.1), con la conversación de `chat_for`:
        comparte con el de diseño las puertas, el tope y `agent_busy` (V6), nunca su chat ni
        su sesión (V3)."""
        if session.review is None:
            def make_agent():
                async def on_elements(new):
                    await board_changed(session.board, session, new)

                async def request_zone(payload):
                    return await session.zones.request(session.clients, payload,
                                                       prefer=session.chat.asker)
                return agent_review.ReviewAgent(session.board, on_elements, cli_path=claude_cli,
                                                request_zone=request_zone, settings=settings)

            session.review = agent_review.AgentReview(
                chat_for(session), make_agent, lambda m: broadcast(session, m))
        return session.review

    async def version_saved(session, info):
        """Un hito (V5): guardar una versión con nombre con la intrusividad en `hitos` lanza
        una revisión. Un fallo aquí nunca deshace la versión: queda en el registro."""
        if session is None:
            return
        try:
            await review_for(session).milestone(info)
        except Exception as exc:              # noqa: BLE001 la versión ya está guardada
            log.warning("el hito de la versión %s no lanzó la revisión: %s", info.get("id"), exc)

    def threads_for(session):
        """Los hilos del proyecto (`agent_threads`, D165), con la conversación de `chat_for`."""
        if session.threads is None:
            session.threads = agent_threads.AgentThreads(
                chat_for(session), lambda m, exclude=None: broadcast(session, m, exclude))
        return session.threads

    async def probe_now(board, session, fresh=False):
        """Sondea las tarjetas en un hilo (leer un STEP grande tarda) y, si algo cambió, avisa a
        las ventanas del proyecto (D134)."""
        changed = await asyncio.get_running_loop().run_in_executor(None, board.probe, fresh)
        if changed and session is not None:
            await broadcast(session, blocks_msg(session))
        return changed

    def spawn(session, coro):
        task = asyncio.create_task(coro)
        session.tasks.add(task)
        task.add_done_callback(session.tasks.discard)

    def start_run(session, block_id, options=None):
        """Planea la ejecución (si algo de la cadena no se puede ejecutar, no empieza) y la
        lanza en segundo plano con su proceso de cálculo (D89, D92). `options`: el botón de una
        confirmación (D112), solo para `block_id` y solo esta vez. Devuelve la tarea."""
        job = execution.Job.plan(session.board, block_id, options)
        try:
            worker = worker_factory(session.board.registry)
        except Exception:
            job.close()
            raise
        session.worker = worker
        task = asyncio.create_task(run_blocks(session, job, worker))
        session.tasks.add(task)
        task.add_done_callback(session.tasks.discard)
        return task

    async def run_blocks(session, job, worker):
        """Recorre la ejecución. Cada bloque terminado se guarda al momento; el estado y el
        progreso llegan a todas las ventanas del proyecto. Devuelve el `run_finished`."""
        async def on_event(kind):
            if kind == "progress":
                v = job.view()
                await broadcast(session, {"type": "block_progress", "block": v["block"],
                                          "fraction": v["fraction"], "message": v["message"]})
                return
            if kind == "done":
                await save_and_ack(session)
            await broadcast(session, blocks_msg(session))

        try:
            msg = {"type": "run_finished", **await execution.run_job(job, worker, on_event)}
        except Exception as exc:              # se enseña, no se oculta
            msg = {"type": "run_finished", **job.summary(),
                   "error": f"{type(exc).__name__}: {exc}"}
        finally:
            session.worker = None
        try:
            await save_and_ack(session)
        except (StorageError, OSError) as exc:   # p. ej. el proyecto se borró mientras corría
            msg.setdefault("error", f"{type(exc).__name__}: {exc}")
        await broadcast(session, blocks_msg(session))
        await broadcast(session, proposals_msg(session))
        await broadcast(session, msg)
        sessions.run_finished(session)
        return msg

    def project_dict(pid):
        return asdict(workspace.project(pid))

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if not token_ok(ws.query_params.get("token")) or not origin_ok(ws.headers.get("origin")):
            await ws.close(code=4401)
            return
        await ws.accept()
        pid = ws.query_params.get("project") or ""
        try:
            if sessions is None:
                raise NotFound(start.problem or i18n.t("workspace.ninguno_abierto"))
            session = sessions.open(pid)
            info = project_dict(pid)
        except NotFound as exc:
            await ws.send_json({"type": "project_closed", "reason": "missing",
                                "message": str(exc)})
            await ws.close(code=4404)
            return
        session.clients.add(ws)
        # Abrir un proyecto lo pone el primero de recientes y como el último (D63).
        settings.touch_project(workspace.info().id, pid, info["name"])
        settings.save()
        board = session.board
        try:
            await ws.send_json(init_msg(pid, board))
            spawn(session, probe_now(board, session))     # sin esperarlo: init sale ya
            while True:
                raw = await ws.receive()
                if raw["type"] == "websocket.disconnect":
                    break
                # Un mensaje mal formado se contesta con un error; nunca cierra la conexión (R6).
                try:
                    msg = json.loads(raw.get("text") or "")
                    if not isinstance(msg, dict):
                        raise ValidationError("el mensaje tiene que ser un objeto JSON")
                    if msg.get("type") == "scene":
                        if not isinstance(msg.get("elements"), list) or not all(
                                isinstance(e, dict) and "id" in e for e in msg["elements"]):
                            raise ValidationError("`elements` tiene que ser una lista de elementos")
                        won, rewritten = board.apply_client_elements(msg["elements"])
                        if won:                   # a las demás ventanas del proyecto (D69)
                            await broadcast(session, {"type": "elements", "elements": won},
                                            exclude=ws)
                        if rewritten:             # y lo corregido, también a esta (D85)
                            await ws.send_json({"type": "elements", "elements": rewritten})
                        if any((e.get("customData") or {}).get("kind") in graph.SOURCE_PORT
                               for e in won):     # una tarjeta nueva, quitada o con otro marcado
                            spawn(session, probe_now(board, session))
                    elif msg["type"] == "set_params":
                        board.set_params(msg["block"], msg["params"])
                    elif msg["type"] == "run":
                        opts = msg.get("options")
                        if opts is not None and not (isinstance(opts, dict) and all(
                                isinstance(k, str) and v is True for k, v in opts.items())):
                            raise ValidationError("options tiene que ser {acción: true}")
                        await probe_now(board, session, fresh=True)   # el hash de ahora (D134)
                        start_run(session, str(msg["block"]), opts)
                    elif msg["type"] == "run_stale":
                        await probe_now(board, session, fresh=True)
                        start_run(session, None)
                    elif msg["type"] == "cancel":
                        if session.worker is None:
                            raise ValidationError(i18n.t("ejecucion.ninguna_en_curso"))
                        session.worker.kill()         # lo cuenta run_blocks al acabar
                        continue
                    elif msg["type"] == "proposal_accept":
                        changed = board.accept_proposal(str(msg["id"]), msg.get("seen"))
                        if changed:
                            await broadcast(session, {"type": "elements", "elements": changed})
                            await probe_now(board, session)   # una tarjeta que pasa a otro archivo (D176)
                    elif msg["type"] == "proposal_reject":
                        board.reject_proposal(str(msg["id"]))
                    elif str(msg["type"]).startswith("agent_"):
                        await chat_for(session).handle(ws, msg)
                        continue
                    elif str(msg["type"]).startswith("thread_"):
                        await threads_for(session).handle(ws, msg)
                        continue
                    elif str(msg["type"]).startswith("review_"):
                        await review_for(session).handle(ws, msg)
                        continue
                    elif msg["type"] == "zone_image":
                        session.zones.answer(msg)     # la que llega tarde se descarta
                        continue
                    else:
                        raise ValidationError(f"mensaje desconocido: {msg.get('type')!r}")
                    await save_and_ack(session)
                except (ValidationError, StorageError, KeyError, ValueError, TypeError,
                        AttributeError, OSError) as exc:
                    await ws.send_json({"type": "error",
                                        "message": f"{type(exc).__name__}: {exc}"})
                    continue
                await broadcast(session, blocks_msg(session))
                # Lo que cambia la escena puede dejar desfasada una propuesta (D75).
                await broadcast(session, proposals_msg(session))
        except (WebSocketDisconnect, RuntimeError):     # RuntimeError: cerrada desde aquí
            pass
        finally:
            sessions.leave(session, ws)

    def init_msg(pid, board):
        """La escena entera y todo lo que la acompaña: al abrir y al restaurar una versión."""
        cat = blocks_mod.describe()
        return {"type": "init", "project": project_dict(pid), "elements": board.elements,
                "thumbnail": workspace.load_thumbnail(pid) is not None,
                "types": cat["blocks"],
                "catalog": {k: cat[k] for k in ("ports", "templates", "packs", "connectors")},
                "connectors": connectors_mod.status(),
                **board.blocks_view(),
                "proposals": board.proposals_view(),
                "agent": chat_for(sessions.get(pid)).state(),
                "review": review_for(sessions.get(pid)).state(),
                "threads": threads_for(sessions.get(pid)).list()}

    def board_for(pid):
        """La pizarra abierta del proyecto (con sus ventanas) o una leída para la ocasión."""
        need_workspace()
        s = sessions.get(pid)
        if s is not None:
            return s.board, s
        workspace.project(pid)
        return Board(workspace, pid), None

    async def board_changed(board, session, new):
        if session is None:
            board.save()
            return
        await broadcast(session, {"type": "elements", "elements": new})
        await save_and_ack(session)
        await broadcast(session, blocks_msg(session))
        await broadcast(session, proposals_msg(session))

    files_api.register(app, board_for=board_for, board_changed=board_changed,
                       probe_now=probe_now,
                       mesh_dir=Path(settings.path).parent / "cache" / "meshes")

    async def packs_changed():
        """Tras instalar o desinstalar (§7): el registro nuevo en cada pizarra abierta, que
        vuelve a recibir la escena entera con el catálogo, como al restaurar una versión."""
        reg = blocks_mod.reload()
        for s in sessions.all() if sessions is not None else []:
            s.board.use_registry(reg)
            await broadcast(s, init_msg(s.project_id, s.board))

    workspace_api.register(app, start=start, settings=settings, workspace=workspace,
                           sessions=sessions, need_workspace=need_workspace, board_for=board_for,
                           broadcast=broadcast, close_sessions=close_sessions,
                           project_dict=project_dict, init_msg=init_msg,
                           version_saved=version_saved)
    settings_api.register(app, settings=settings, workspace=workspace, sessions=sessions,
                          broadcast=broadcast)
    update_api.register(app, settings=settings)   # el actualizador (PLAN_V020 §4)
    library_api.register(app, need_workspace=need_workspace,      # la librería (PLAN_V020 §5)
                         registry=lambda: blocks_mod.REGISTRY)
    profile_api.register(app, need_workspace=need_workspace,      # el perfil .zip (PLAN_LIBRERIA §5)
                         settings=settings)
    supply_api.register(app, need_workspace=need_workspace,       # proveedores (PLAN_APROVISIONAMIENTO)
                        settings=settings, registry=lambda: blocks_mod.REGISTRY,
                        cli_path=claude_cli)
    welcome.register(app, settings=settings, workspace=workspace, claude_cli=claude_cli,
                     restart=restart)
    agent_chat.register(app, need_workspace, settings, sessions)
    pack_install_api.register(app, drafts=Path(settings.path).parent / agent_packs.DRAFTS,
                              changed=packs_changed, busy=lambda: sessions is not None and any(
        s.board.job is not None for s in sessions.all()))

    @app.get("/api/health")
    def health():
        return {"ok": True, "app": APP_NAME, "frozen": FROZEN,
                "workspace": str(workspace.root) if workspace is not None else None,
                "packs": {p.id: p.error for p in blocks_mod.REGISTRY.packs}}

    # ------------------------------------------------------- pizarra de un proyecto
    @app.get("/api/projects/{pid}/board")
    def get_board(pid: str):
        return board_for(pid)[0].summary()

    # Lo mismo que la herramienta `proponer_cambio` del agente, para probarla sin él (D75).
    @app.post("/api/projects/{pid}/agent/proposal")
    async def post_proposal(pid: str, p: ProposalIn):
        board, session = board_for(pid)
        if p.author not in AGENT_AUTHORS:
            raise HTTPException(422, f"autor de agente desconocido: {p.author!r}")
        try:
            kind, out = board.agent_propose(p.author, p.target, p.change, p.reason,
                                            p.sources, p.estimate)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))
        changed = [out] if kind == "aplicado" and out else []
        await board_changed(board, session, changed)
        return {"kind": kind, "id": out["id"] if out else None}

    @app.post("/api/projects/{pid}/agent/postit")
    async def post_postit(pid: str, p: PostitIn):
        board, session = board_for(pid)
        data = p.model_dump()
        x, y = data.pop("x"), data.pop("y")
        try:
            new = board.agent_add_postit(data, x, y)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))
        await board_changed(board, session, new)
        return {"ids": [e["id"] for e in new]}

    # Post-it del usuario (D71): nace vacío y abierto; la interfaz lo abre para escribir.
    @app.post("/api/projects/{pid}/postits")
    async def post_user_postit(pid: str, p: UserPostitIn):
        board, session = board_for(pid)
        try:
            el = board.user_add_postit(p.kind, p.x, p.y)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))
        await board_changed(board, session, [el])
        return {"id": el["id"]}

    @app.post("/api/projects/{pid}/templates")
    async def post_template(pid: str, t: TemplateIn):
        """Pone una plantilla (la cadena ya conectada) en un sitio libre de la pizarra."""
        board, session = board_for(pid)
        try:
            new = board.add_template(t.template, t.x, t.y)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))
        await board_changed(board, session, new)
        return {"ids": [e["id"] for e in new]}

    @app.post("/api/projects/{pid}/blocks/{bid}/open")
    def open_block_file(pid: str, bid: str, o: OpenIn):
        """*Abrir* un archivo de salida (el informe) con el programa del sistema. La ruta la da
        el almacenamiento: nunca sale de la carpeta del bloque (D93)."""
        desktop.open_file(need_workspace().block_file(pid, bid, o.file))
        return {"ok": True}

    @app.get("/api/projects/{pid}/blocks/{bid}/files/{name}")
    def get_block_file(pid: str, bid: str, name: str):
        """Un archivo de salida del bloque (la miniatura de la captura, D114). La ruta la da el
        almacenamiento: nunca sale de la carpeta del bloque."""
        return FileResponse(need_workspace().block_file(pid, bid, name),
                            headers={"Cache-Control": "no-cache"})

    @app.post("/api/projects/{pid}/blocks")
    async def post_block(pid: str, b: BlockIn):
        if b.type not in blocks_mod.REGISTRY:
            raise HTTPException(422, i18n.t("bloque.tipo_desconocido", tipo=b.type))
        board, session = board_for(pid)
        el = scene.block_element(b.type, b.x, b.y)
        board.apply_client_elements([el])
        await board_changed(board, session, [el])
        return {"id": el["id"]}

    # Vigila los conectores (D106): cuando Fusion se abre o se cierra, los bloques que lo piden
    # cambian de estado en todas las ventanas, sin recargar nada.
    async def watch_connectors():
        loop = asyncio.get_running_loop()
        last = None
        while True:
            try:
                now = await loop.run_in_executor(None, connectors_mod.status)
                if sessions is not None and now != last:
                    for s in sessions.all():
                        await broadcast(s, {"type": "connectors", "connectors": now})
                        await broadcast(s, blocks_msg(s))
                last = now
            except Exception:             # noqa: BLE001 el vigilante no se para por un fallo suelto
                pass
            await asyncio.sleep(3)

    # Sondeo de las tarjetas de archivo (D134): un archivo cambiado fuera de la app desactualiza
    # lo de detrás casi en vivo. Solo lo que hay en las pizarras abiertas, nunca el disco.
    async def watch_sources():
        while True:
            await asyncio.sleep(PROBE_EVERY)
            for s in (sessions.all() if sessions is not None else []):
                try:
                    await probe_now(s.board, s)
                except Exception:         # noqa: BLE001 el vigilante no se para por un fallo suelto
                    pass

    @app.on_event("startup")
    async def start_watchers():
        app.state.watch = asyncio.create_task(watch_connectors())
        app.state.watch_sources = asyncio.create_task(watch_sources())

    @app.get("/api/connectors")
    def get_connectors():
        return connectors_mod.status()

    @app.post("/api/connectors/{cid}/launch")
    def launch_connector(cid: str):
        """*Abrir* el programa de un conector (D106): {status: abierto | arrancando}."""
        try:
            return {"status": connectors_mod.launch(cid)}
        except KeyError:
            raise HTTPException(404, i18n.t("conector.no_existe", id=repr(cid)))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    async def connector_action(cid, action, args):
        """Una acción del paquete de un conector que no es de ningún bloque (`<id>.<acción>`:
        listar destinos y documentos, la prueba; P38, P40). En un hilo, porque habla con el
        programa. Si falla, un 502 con el motivo: es el programa el que no ha podido (y la
        interfaz reintenta lo que depende de él, `retry.ts`)."""
        reg = blocks_mod.REGISTRY
        if cid not in reg.connectors:
            raise HTTPException(404, i18n.t("conector.no_existe", id=repr(cid)))
        name = f"{cid}.{action}"
        if name not in reg.actions:
            raise HTTPException(404, i18n.t("conector.sin_accion", id=cid, accion=repr(action)))
        env = {"connectors": connectors_mod.config(reg)}
        loop = asyncio.get_running_loop()
        try:                              # en el trabajador, en la app (PLAN_PAQUETES P89)
            return await loop.run_in_executor(
                None, lambda: reg.host.action(name, {}, {}, dict(args), env))
        except Exception as exc:          # noqa: BLE001 un paquete con un fallo no tumba la app
            raise HTTPException(502, str(exc) if isinstance(exc, pack_host.HostError)
                                else packs_mod.action_error(name, exc))

    @app.get("/api/connectors/{cid}/{action}")
    async def get_connector_action(cid: str, action: str, request: Request):
        return await connector_action(cid, action, request.query_params)

    @app.post("/api/connectors/{cid}/{action}")
    async def post_connector_action(cid: str, action: str, a: ConnectorArgsIn):
        return await connector_action(cid, action, a.args)

    @app.post("/api/dialog/step")
    def choose_step():
        """«Elegir archivo» del *STEP de referencia* (D129): el diálogo del sistema, abierto
        por el backend porque la interfaz no ve rutas. `path` es None si se cancela."""
        try:
            return {"path": desktop.choose_file(i18n.t("dialogo.elegir_step"), [("STEP", "*.step;*.stp")])}
        except OSError as exc:
            raise HTTPException(500, i18n.t("dialogo.no_abre", motivo=exc))

    @app.post("/api/projects/{pid}/blocks/{bid}/preview")
    def post_preview(pid: str, bid: str, p: PreviewIn):
        """La vista previa de un bloque (PLAN_TERMINALES T26: el editor del árbol de un
        terminal, lo que da la ficha de un robot) con los parámetros que se están editando. No
        guarda ni ejecuta: lo editado se envía con `set_params`, como cualquier campo."""
        board, _session = board_for(pid)
        try:
            return board.preview(bid, p.params)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/projects/{pid}/blocks/{bid}/action")
    async def post_action(pid: str, bid: str, a: ActionIn):
        """`action` desde la interfaz propia del bloque (docs/PLAN_PAQUETES.md §5, P40): una
        acción del paquete del bloque o de su conector, con respuesta. En un hilo, porque puede
        hablar con el programa del conector; lo que cambie en la pizarra (la API de P39) se
        guarda y se avisa a las ventanas, también si la acción falla a medias."""
        board, session = board_for(pid)
        effects = {}
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: board.action(bid, a.name, a.args, effects=effects))
        except ValidationError as exc:
            if effects.get("changed"):
                await board_changed(board, session, effects["new"])
            raise HTTPException(422, str(exc))
        if effects.get("changed"):
            await board_changed(board, session, effects["new"])
        return {"result": result}

    @app.get("/packs/{pack_id}/ui/{rel:path}")
    def get_pack_ui(pack_id: str, rel: str, request: Request):
        """Un fichero de `ui/` de un paquete cargado (P24): nunca de fuera, y siempre con la
        CSP sin red, también la respuesta de lo que no se sirve."""
        host = request.headers.get("host", "")
        origin = f"{request.url.scheme}://{host}" if HOST_RE.match(host) else None
        hdrs = pack_ui.headers(origin, pack_id if packs_mod.ID_RE.match(pack_id) else "_")
        try:
            path = pack_ui.resolve(blocks_mod.REGISTRY, pack_id, rel)
        except pack_ui.NotServed as exc:
            return JSONResponse({"detail": str(exc)}, status_code=404, headers=hdrs)
        if pack_ui.is_page(path):                       # con el puente de la rueda (P54)
            return Response(pack_ui.with_bridge(path.read_bytes()), media_type="text/html",
                            headers=hdrs)
        return FileResponse(path, headers=hdrs)

    if web_dir and Path(web_dir).is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    app.state.sessions = sessions
    app.state.settings = settings
    return app


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pizarra-backend")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PIZARRA_PORT", "8765")))
    ap.add_argument("--token", default=os.environ.get("PIZARRA_TOKEN"))
    ap.add_argument("--settings", default=os.environ.get("PIZARRA_SETTINGS"),
                    help="settings.toml de la app (el shell lo pone en su carpeta de datos)")
    ap.add_argument("--documents", default=os.environ.get("PIZARRA_DOCUMENTS"),
                    help="carpeta Documentos del usuario (la resuelve el shell: puede estar "
                         "en OneDrive); el workspace por defecto va en <Documentos>/<App>/")
    ap.add_argument("--engine-dir", default=None,
                    help="carpeta con el motor en .py (la que importa el Python de Fusion)")
    ap.add_argument("--web-dir", default=None, help="interfaz compilada a servir en /")
    ap.add_argument("--parent-pid", type=int, default=None,
                    help="PID del shell: si desaparece, el backend sale (watchdog)")
    ap.add_argument("--claude-cli", default=None,
                    help="CLI de Claude Code para el agente (empaquetado: recurso de la app)")
    ap.add_argument("--pyenv-dir", default=None,
                    help="Python y uv del entorno de paquetes (recurso pyenv/, PLAN_PAQUETES P93)")
    ap.add_argument("--worker-dir", default=None,
                    help="el trabajador de paquetes y lo que carga (recurso worker/)")
    ap.add_argument("--cache-dir", default=None,
                    help="caché de la app: entornos de paquetes, .pyc, registros")
    args = ap.parse_args(argv)

    # En desarrollo, los paquetes del repo (P26, P81): la carga ya no los conoce.
    if REPO and not os.environ.get(packs_mod.DEV_ENV, "").strip():
        os.environ[packs_mod.DEV_ENV] = str(REPO / "packs")
    # En desarrollo todo vive en out/dev/, sin tocar Documentos (D70).
    dev = REPO / "out" / "dev" if REPO else None
    documents = Path(args.documents) if args.documents else (
        dev / "Documentos" if dev else Path.home() / "Documents")
    settings_path = Path(args.settings) if args.settings else (
        dev / "settings.toml" if dev else app_data_dir() / "settings.toml")
    # Pizarras del spike de FF 3, que se copian una vez al workspace (D67).
    spikes = [REPO / "out" / "spike_pizarra"] if REPO else [documents / APP_NAME / "spike"]
    engine_dir = args.engine_dir or (str(REPO / "engine") if REPO else None)
    web_dir = args.web_dir or (BUNDLE / "web" if FROZEN else None)

    # Empaquetado, el padre inmediato es el lanzador de PyInstaller: si muere (o muere el
    # shell), el backend no puede quedarse huérfano con el puerto abierto (plan R5).
    watchdog.watch([os.getppid() if FROZEN else None, args.parent_pid])

    import uvicorn
    claude_cli = desktop.clean_path(args.claude_cli) if args.claude_cli else None
    worker_spec = pack_environment(args, engine_dir, dev, REPO, FROZEN, BUNDLE)
    # Cambiar de workspace (D186) rearranca el servidor aquí dentro, en el mismo puerto y con
    # el mismo token: la ventana solo tiene que recargar. Sin IPC con el shell (R3).
    restarted = False
    while True:
        start = bootstrap(settings_path, documents / APP_NAME / DEFAULT_WORKSPACE, spikes,
                          legacy=legacy_settings(settings_path))
        holder = {"again": False}

        def restart(holder=holder):
            holder["again"] = True
            asyncio.get_running_loop().call_later(0.3, setattr, holder["server"],
                                                  "should_exit", True)

        app = create_app(start, args.token, engine_dir, web_dir, claude_cli,
                         worker_spec=worker_spec, restart=restart)
        for attempt in range(20):           # el puerto puede tardar en soltarse al rearrancar
            server = holder["server"] = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=args.port, log_level="warning"))
            try:
                server.run()
                break
            except SystemExit:
                if not restarted or attempt == 19:
                    raise
                time.sleep(0.25)
        if not holder["again"]:
            break
        restarted = True


if __name__ == "__main__":
    main()
