"""Una sesión por proyecto abierto (docs/PLAN_PIZARRA.md §2, D69).

La sesión tiene la pizarra del proyecto, las ventanas conectadas a él y su agente de diseño.
Se abre al conectarse la primera ventana y se guarda y se suelta al irse la última, salvo si
el agente o una ejecución de bloques siguen trabajando: entonces se suelta cuando acaban.
"""
import asyncio
import logging

from pizarra.board import Board
from pizarra.zone import ZoneRequests
from pizarra.storage import StorageError

log = logging.getLogger(__name__)

# Lo que se espera a que una ventana acepte un mensaje (en 127.0.0.1 tarda milisegundos).
SEND_TIMEOUT = 10.0
CLOSE_TIMEOUT = 60.0
_closing = set()                       # cierres en segundo plano: que el GC no los recoja


async def send_all(clients, msg, exclude=None, timeout=SEND_TIMEOUT):
    """Manda `msg` a la vez a cada ventana de `clients` (menos `exclude`). La que falla, o no
    lo acepta en `timeout` segundos, sale de `clients`: una ventana que deja de leer (una
    pestaña congelada, un proceso parado) llena su búfer y el envío esperaba para siempre;
    con él, la ejecución, *Cancelar* y las demás ventanas (e2e de v0.1.0). A la que no
    contesta se le cierra la conexión en segundo plano: si vuelve, se reconecta y recibe el
    estado entero (`init`)."""
    async def one(ws):
        try:
            await asyncio.wait_for(ws.send_json(msg), timeout)
        except Exception as exc:        # noqa: BLE001 incluido TimeoutError
            clients.discard(ws)
            if isinstance(exc, TimeoutError):
                log.warning("una ventana no lee en %.0f s: deja de recibir y se cierra", timeout)
                task = asyncio.ensure_future(_close(ws))
                _closing.add(task)
                task.add_done_callback(_closing.discard)

    await asyncio.gather(*(one(ws) for ws in list(clients) if ws is not exclude))


async def _close(ws):
    try:
        await asyncio.wait_for(ws.close(code=1013), CLOSE_TIMEOUT)
    except Exception:                   # noqa: BLE001 ya no está, o sigue sin leer
        pass


class Session:
    def __init__(self, project_id, board):
        self.project_id = project_id
        self.board = board
        self.clients = set()           # WebSockets (o lo que use quien la gestione)
        self.agent = None              # DesignAgent, se crea con la primera pregunta
        self.chat = None               # agent_chat.AgentChat: su conversación en disco (D164)
        self.threads = None            # agent_threads.AgentThreads: sus hilos (D165)
        self.agent_busy = False        # nunca dos preguntas a la vez (R6)
        self.tasks = set()             # tareas del agente y de la ejecución: que el GC no las recoja
        self.worker = None             # proceso de cálculo de la ejecución en curso (D92)
        self.zones = ZoneRequests()    # `ver_zona` esperando la imagen de una ventana (D171)


class Sessions:
    def __init__(self, workspace):
        self.ws = workspace
        self._open = {}

    def open(self, project_id):
        """La sesión del proyecto, abriéndola si hace falta; `NotFound` si no existe."""
        s = self._open.get(project_id)
        if s is None:
            self.ws.project(project_id)
            s = self._open[project_id] = Session(project_id, Board(self.ws, project_id))
        return s

    def get(self, project_id):
        return self._open.get(project_id)

    def all(self):
        """Las sesiones abiertas (para avisar a todas, p. ej. al abrirse Fusion)."""
        return list(self._open.values())

    def open_ids(self):
        return list(self._open)

    def leave(self, session, client):
        session.clients.discard(client)
        self._release_if_idle(session)

    def agent_finished(self, session):
        session.agent_busy = False
        self._release_if_idle(session)

    def close(self, project_ids):
        """Guarda y suelta las sesiones de esos proyectos (antes de borrarlos, D66) y las
        devuelve para avisar a sus ventanas."""
        out = []
        for pid in project_ids:
            s = self._open.pop(pid, None)
            if s is not None:
                self._save(s)
                out.append(s)
        return out

    def run_finished(self, session):
        self._release_if_idle(session)

    def _release_if_idle(self, s):
        """Sin ventanas, la sesión se suelta, salvo si el agente o una ejecución siguen
        trabajando: entonces, cuando acaban."""
        if not s.clients and not s.agent_busy and s.board.job is None \
                and self._open.get(s.project_id) is s:
            del self._open[s.project_id]
            self._save(s)

    def _save(self, s):
        try:
            s.board.save()
        except (StorageError, OSError) as exc:     # p. ej. la carpeta se borró a mano
            log.warning("no se pudo guardar el proyecto %s: %s", s.project_id, exc)
