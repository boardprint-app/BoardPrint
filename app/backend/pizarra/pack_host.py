"""El anfitrión de los paquetes: quien corre su código (docs/PLAN_PAQUETES.md §4, P89-P91).

Cada registro tiene uno (`Registry.host`), y todo lo que el backend hace con el código de un
paquete pasa por él: la vista previa, las acciones (de un bloque o de un conector), los
conectores (`available`, `launch`, `open_file`) y el proceso de cada ejecución (D92).

- **`InProcessHost`**: las funciones del registro cargado en este proceso. Es el de los tests
  del backend y de los paquetes (P65), que abren una pizarra con su propio registro.
- **`WorkerHost`**: el de la app. Un *trabajador caliente* (`python -m boardprint_worker` en
  el entorno de paquetes) carga los paquetes y da el registro como datos (`pack_data`); la
  vista previa y las acciones van a él, una detrás de otra. Lo que habla con un programa
  externo (los conectores y las acciones del paquete de un conector) va a **otro** caliente,
  el del carril `EXTERNAL`, que arranca la primera vez que hace falta: un Fusion colgado o
  con un diálogo abierto solo hace esperar a lo suyo (e2e de v0.1.0). Cada ejecución, a un
  trabajador propio (`WorkerRun`) que *Cancelar* mata. Si un caliente muere, se vuelve a
  arrancar en la siguiente llamada.

En una acción, el trabajador pide a la pizarra lo de la API de P39 (`call`) y el anfitrión lo
resuelve con el `BoardAPI` que se le pasa, con la validación de siempre (P91).
"""
import asyncio
import json
import logging
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from pizarra import i18n, pack_data, packs

PROTOCOL_VERSION = 2
log = logging.getLogger(__name__)


class HostError(ValueError):
    """El motivo de un fallo de un paquete (o de su trabajador), para enseñarlo tal cual."""


class WorkerDied(HostError):
    """El trabajador terminó de golpe."""


class HostBusy(HostError):
    """El trabajador caliente está con otra petición y quien pregunta no puede esperar."""


# ------------------------------------------------------------------------- en proceso
class InProcessHost:
    def __init__(self, registry):
        self.registry = registry

    def preview(self, kind, params, inputs, env=None):
        """Lo que da la vista previa de `kind`. `ValueError`, `TypeError` o `KeyError` del
        paquete salen tal cual: son el motivo para el usuario. `env`, el de `Board.run_env`:
        de él sale la librería del workspace (`boardprint_sdk.library.current()`)."""
        with pack_data.using_library(pack_data.library_of(env)):
            return self.registry[kind].preview(params, inputs)

    def action(self, name, params, inputs, args, env, board=None, block_id=""):
        """Lo que devuelve la acción `name` (ya JSON). `HostError` con el motivo si falla."""
        act = self.registry.actions.get(name)
        if act is None:
            raise HostError(i18n.t("bloque.accion_no_existe", paquete=packs.pack_id_of(name),
                                    accion=repr(name)))
        ctx = pack_data.context(block_id, env)
        ctx._board = board
        try:
            with pack_data.using_library(ctx.library):
                result = act.run(params, inputs, args, ctx)
        except Exception as exc:        # noqa: BLE001 un paquete con un fallo no tumba la app
            raise HostError(packs.action_error(name, exc)) from None
        try:
            return pack_data.as_json(result)
        except (TypeError, ValueError) as exc:
            raise HostError(f"{name} no devuelve JSON: {exc}") from None

    def connector(self, cid, method, *args):
        c = self.registry.connectors[cid]
        if method == "available":
            return bool(c.available())
        fn = getattr(c, method)
        if fn is None:
            raise HostError(f"el conector {cid} no sabe {method}")
        return fn(*args)

    def run_worker(self):
        from pizarra import execution
        return execution.ProcessWorker(self.registry.dirs, self.registry.validated)

    def close(self):
        pass


# ------------------------------------------------------------------- el trabajador
@dataclass(frozen=True)
class WorkerSpec:
    """Cómo arrancar un trabajador (P93): su Python, la carpeta con `boardprint_worker`, el SDK
    y la carga (`worker/`), el motor común (`engine/`) y la caché (`.pyc`, P28)."""
    python: str
    worker_dir: str
    engine_dir: str | None = None
    cache_dir: str | None = None
    stderr: object = None           # a dónde va su salida de error (por defecto, la nuestra)

    def start(self):
        return WorkerProcess(self)


class WorkerProcess:
    """Un `python -m boardprint_worker` con su canal: una petición a la vez."""

    def __init__(self, spec):
        from pizarra import pack_env
        extra = [p for p in (spec.worker_dir, spec.engine_dir) if p]
        self.proc = subprocess.Popen(
            [spec.python, "-m", "boardprint_worker"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=spec.stderr, text=True, encoding="utf-8",
            env=pack_env.clean_env(cache_dir=spec.cache_dir, extra_path=extra),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.next_id = 0
        self.killed = False

    def alive(self):
        return self.proc.poll() is None

    def request(self, op, on_call=None, on_progress=None, **fields):
        """Manda `op` y devuelve su respuesta final (`{"ok", ...}`). Por el camino atiende el
        progreso y las llamadas a la pizarra (`on_call(método, args) -> resultado`)."""
        self.next_id += 1
        rid = self.next_id
        self._send({"id": rid, "op": op, **fields})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise WorkerDied(i18n.t("trabajador.muerto", codigo=self.proc.poll()))
            msg = json.loads(line)
            if "progress" in msg:
                if on_progress:
                    on_progress(*msg["progress"])
            elif "call" in msg:
                self._send(self._answer(msg, on_call))
            elif msg.get("id") == rid:
                return msg
            else:                   # el canal se ha desordenado: nunca esperar para siempre
                self.kill()
                raise HostError(f"respuesta fuera de orden del trabajador (esperaba {rid}): "
                                f"{line.strip()[:200]}")

    @staticmethod
    def _answer(msg, on_call):
        try:
            if on_call is None:
                raise HostError("aquí no hay pizarra (solo en una acción de un bloque)")
            result = on_call(msg["call"], msg.get("args") or [])
            if isinstance(result, Path):
                result = str(result)
            return {"reply_to": msg["cid"], "ok": True, "result": pack_data.as_json(result)}
        except Exception as exc:        # noqa: BLE001 vuelve al paquete como ValueError
            return {"reply_to": msg["cid"], "ok": False, "error": str(exc)}

    def _send(self, obj):
        try:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise WorkerDied(i18n.t("trabajador.no_esta")) from None

    def kill(self):
        self.killed = True
        if self.alive():
            self.proc.kill()
        self.proc.wait(timeout=5)

    def close(self):
        if self.alive():
            try:
                self._send({"id": 0, "op": "exit"})
                self.proc.wait(timeout=2)
            except (WorkerDied, subprocess.TimeoutExpired):
                pass
        if self.alive():
            self.proc.kill()
            self.proc.wait(timeout=5)
        for f in (self.proc.stdin, self.proc.stdout):
            try:
                f.close()
            except OSError:
                pass


def _origins(origins):
    return [[str(o), str(d)] for o, d in origins]


LOCAL = "local"                         # vista previa y acciones de los paquetes
EXTERNAL = "externo"                    # lo que habla con un programa (conectores)


class _Lane:
    """Un trabajador caliente con su cerrojo: sus peticiones van una detrás de otra."""

    def __init__(self):
        self.lock = threading.RLock()
        self.proc = None


class WorkerHost:
    """El anfitrión de la app: dos trabajadores calientes (el local y el de los conectores)
    para todo menos las ejecuciones."""

    def __init__(self, spec, origins, validated=None):
        self.spec = spec
        self.origins = [(str(o), str(d)) for o, d in packs._as_origins(origins)]
        self.validated = str(validated) if validated else None
        self._lanes = {LOCAL: _Lane(), EXTERNAL: _Lane()}
        self.registry = None
        self.env = None                 # pack_env.PackEnvironment, si lo da (P92)
        self.env_problem = None         # por qué no tiene las librerías que piden

    def load(self):
        """Arranca el trabajador, carga los paquetes y devuelve el registro (datos, con este
        anfitrión). Si no arranca, `HostError`. El del carril externo se cierra también y, si
        hay conectores, vuelve a arrancar con los paquetes nuevos en segundo plano."""
        lane = self._lanes[LOCAL]
        with lane.lock:
            self.close()
            reg = pack_data.from_data(self._start(lane)["registry"])
            reg.host = self
            self.registry = reg
        if reg.connectors:
            self._warm_external()
        return reg

    def _warm_external(self):
        """Arranca el trabajador del carril externo en un hilo: quien pregunta `available`
        (el bucle del servidor) nunca espera a que cargue los paquetes."""
        def warm():
            lane = self._lanes[EXTERNAL]
            with lane.lock:
                if lane.proc is not None and lane.proc.alive():
                    return
                try:
                    self._start(lane)
                except Exception as exc:   # noqa: BLE001 la siguiente llamada lo reintenta
                    log.warning("el trabajador de los conectores no arranca: %s", exc)
                    if lane.proc is not None:
                        lane.proc.close()
                    lane.proc = None
        threading.Thread(target=warm, name="trabajador-conectores", daemon=True).start()

    def _start(self, lane):
        lane.proc = self.spec.start()
        got = lane.proc.request("register", dirs=_origins(self.origins), validated=self.validated)
        if not got.get("ok"):
            raise HostError(got.get("error") or i18n.t("trabajador.no_carga"))
        return got

    def _request(self, op, lane=None, **fields):
        lane = lane or self._lanes[LOCAL]
        with lane.lock:
            if lane.proc is None or not lane.proc.alive():
                self._start(lane)        # solo el suyo: el otro puede estar esperando a Fusion
            return lane.proc.request(op, **fields)

    def _lane_for_action(self, name):
        """El carril de la acción `name`: el externo si es del paquete de un conector."""
        reg = self.registry
        act = reg.actions.get(name) if reg is not None else None
        talks = act is not None and any(c.pack == act.pack for c in reg.connectors.values())
        return self._lanes[EXTERNAL if talks else LOCAL]

    def preview(self, kind, params, inputs, env=None):
        got = self._request("preview", kind=kind, params=params, inputs=inputs, env=env or {})
        if not got.get("ok"):
            raise HostError(got.get("error") or i18n.t("trabajador.vista_previa_fallo"))
        return got["result"]

    def action(self, name, params, inputs, args, env, board=None, block_id=""):
        def on_call(method, call_args):
            if method not in BOARD_METHODS:
                raise HostError(f"la pizarra no tiene {method!r}")
            return getattr(board, method)(*call_args)

        got = self._request("action", lane=self._lane_for_action(name),
                            on_call=on_call if board is not None else None,
                            name=name, block_id=block_id, params=params, inputs=inputs,
                            args=args, env=env, board=board is not None)
        if not got.get("ok"):
            raise HostError(got.get("error") or i18n.t("trabajador.accion_fallo", accion=name))
        return got["result"]

    def connector(self, cid, method, *args):
        # `available` se pregunta desde el bucle del servidor (cada estado de la pizarra): nunca
        # espera a que el trabajador acabe otra petición, que puede tardar un minuto (una
        # acción contra un Fusion con un diálogo abierto). Si está ocupado, `HostBusy` y
        # `connectors.available` se queda con lo último que supo (e2e de v0.1.0: la app entera
        # se paraba mientras tanto).
        lane = self._lanes[EXTERNAL]
        if method == "available":
            if not lane.lock.acquire(blocking=False):
                raise HostBusy(i18n.t("trabajador.ocupado"))
            try:
                if lane.proc is None or not lane.proc.alive():   # arrancarlo carga los paquetes
                    self._warm_external()
                    raise HostBusy(i18n.t("trabajador.ocupado"))
                return self._connector(cid, method, *args)
            finally:
                lane.lock.release()
        return self._connector(cid, method, *args)

    def _connector(self, cid, method, *args):
        got = self._request("connector", lane=self._lanes[EXTERNAL], connector=cid,
                            method=method, args=[str(a) for a in args])
        if not got.get("ok"):
            raise HostError(got.get("error") or i18n.t("trabajador.conector_fallo", id=cid))
        return got["result"]

    def run_worker(self):
        return WorkerRun(self.spec, self.origins, self.validated)

    def close(self):
        for lane in self._lanes.values():
            with lane.lock:
                if lane.proc is not None:
                    lane.proc.close()
                    lane.proc = None


# La API de P39 que el trabajador puede pedir (la de `pack_api.BoardAPI`, sin `block_type`,
# que se resuelve en el trabajador).
BOARD_METHODS = frozenset({"block", "upstream", "set_params", "postits", "add_postit",
                           "clear_error", "block_file"})


class WorkerRun:
    """El trabajador de una ejecución (D92, P90), con la interfaz de `ProcessWorker`: `run`
    (asíncrono), `kill` (es *Cancelar*) y `close`."""

    def __init__(self, spec, origins, validated=None):
        self._proc = spec.start()
        self._origins = _origins(origins)
        self._validated = validated
        self._registered = False
        self.killed = False

    def _blocking_run(self, step, progress):
        if not self._registered:
            got = self._proc.request("register", dirs=self._origins, validated=self._validated)
            if not got.get("ok"):
                return ("error", got.get("error") or "el trabajador no carga los paquetes")
            self._registered = True
        got = self._proc.request("run", on_progress=progress, step=step)
        if not got.get("ok"):
            return ("error", got.get("error") or "la ejecución falló")
        return tuple(got["outcome"])

    async def run(self, step, on_progress):
        from dataclasses import asdict
        loop = asyncio.get_running_loop()

        def progress(fraction, message):
            asyncio.run_coroutine_threadsafe(on_progress(fraction, message), loop)

        try:
            return await loop.run_in_executor(None, self._blocking_run, asdict(step), progress)
        except WorkerDied as exc:
            if self.killed:
                return ("cancelled", None)
            return ("error", str(exc))

    def kill(self):
        self.killed = True
        self._proc.kill()

    def close(self):
        self._proc.close()


def trial_with(spec):
    """La carga de prueba de instalar (`pack_install.inspect(trial=...)`, P83) en un
    trabajador nuevo: el backend no importa el código que el usuario aún no ha aceptado (P95).
    Devuelve `{id: {error, version, blocks}}`, como `pack_install._trial`."""
    def trial(origins, validated=None):
        proc = spec.start()
        try:
            got = proc.request("register", dirs=_origins(packs._as_origins(origins)),
                               validated=validated)
        finally:
            proc.close()
        if not got.get("ok"):
            raise HostError(got.get("error") or "el trabajador no carga los paquetes")
        data = got["registry"]
        return {p["id"]: {"error": p["error"], "version": p["version"],
                          "blocks": [b["title"] for k, b in sorted(data["blocks"].items())
                                     if packs.pack_id_of(k) == p["id"]]}
                for p in data["packs"]}
    return trial


def default_spec(python=None, worker_dir=None, engine_dir=None, cache_dir=None, stderr=None):
    """El trabajador de desarrollo (P93): este Python, `app/backend` y `engine/` del repo."""
    backend = Path(__file__).resolve().parents[1]
    return WorkerSpec(python=python or sys.executable, worker_dir=str(worker_dir or backend),
                      engine_dir=str(engine_dir or backend.parents[1] / "engine"),
                      cache_dir=str(cache_dir) if cache_dir else None, stderr=stderr)
