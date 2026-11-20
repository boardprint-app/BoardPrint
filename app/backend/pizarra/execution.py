"""Ejecución de bloques (plan §3, D89, D92, D93).

Una ejecución (`Job`) sale de *Ejecutar* en un bloque (la cadena de delante que no está al día
y el bloque) o de *Ejecutar lo desactualizado* (todo lo que no está al día). Va bloque a bloque:

    job = Job.plan(board, block_id)       # comprueba la cadena entera; si algo no se puede
    while (step := job.next()):           #   ejecutar, no empieza (ValidationError)
        outcome = <ejecutar step>         # ("ok", salidas) | ("error", texto) | ("cancelled", None)
        job.finish(step, outcome)         # guarda ese bloque al momento (o job.abort(step))
    job.close()

`Job` solo toca la pizarra; dónde corre el cálculo lo decide quien la recorre:
- `run_inline`: en este mismo proceso (tests y `Board.run`).
- `run_job` con un `ProcessWorker`: en un proceso aparte, uno por ejecución (D92). El servidor
  sigue atendiendo mientras tanto, y *Cancelar* mata el proceso.

Un paso lleva una **copia** de los parámetros y de las cargas de entrada, y el hash de lo que
entra en ese momento: si el usuario cambia un parámetro mientras corre, el resultado se guarda
con el hash de lo que se usó y el bloque sale desactualizado. Los archivos se escriben en una
carpeta de trabajo nueva (`ctx.workdir`) que solo pasa a ser la del bloque si termina bien:
cancelar o fallar nunca deja salidas ni archivos a medias.
"""
import asyncio
import copy
import hashlib
import json
import multiprocessing
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pizarra import files, graph, i18n, pack_data, validation
from pizarra.storage import StorageError

PROGRESS_EVERY = 0.1          # s: el proceso de cálculo no manda progreso más a menudo
POLL = 0.02                   # s: cada cuánto mira el servidor si ha llegado algo


@dataclass
class Step:
    """Un bloque a ejecutar, con todo lo que necesita (se manda tal cual al proceso)."""
    block_id: str
    kind: str
    params: dict
    inputs: dict              # {puerto: carga}; un campo con archivo lleva además su "path"
    input_hash: str
    workdir: str
    options: dict = None      # de una confirmación (D112): solo para este paso
    env: dict = None          # project_name, sync_file, connectors (configuración)


def _up(edges, blocks, *ids):
    """`graph.topo_upstream` sin las tarjetas de archivo (D131): no se ejecutan, solo dan
    su contenido."""
    return [b for b in graph.topo_upstream(edges, *ids) if b in blocks]


def _why_not(board, bid, status, blocks, reasons=None):
    """Por qué un bloque no se puede ejecutar, o None."""
    btype = board.registry[blocks[bid]["customData"]["blockType"]]
    if status == "incompleto":
        why = (reasons or {}).get(bid)       # un archivo que no está, con su motivo (D138)
        return f"{btype.title}: {why}" if why else i18n.t("ejecucion.faltan_entradas", bloque=btype.title)
    if status == "no_disponible":
        return i18n.t("ejecucion.conector_no_disponible", bloque=btype.title,
                      conectores=", ".join(sorted(set(btype.requires) - board.connectors)))
    return None


def _down(edges, blocks, ids):
    """Los bloques de detrás de `ids` (sin ellos), por cualquier entrada."""
    out, todo = set(), list(ids)
    while todo:
        n = todo.pop()
        for dst, ins in edges.items():
            if dst in blocks and dst not in out and any(src == n for src, _ in ins.values()):
                out.add(dst)
                todo.append(dst)
    return sorted(out)


def _order(board, edges, req, blocks, sts, roots):
    """Orden de ejecución de `roots`: lo que tienen delante por entradas obligatorias y, por
    cada entrada opcional (D122), la cadena de su bloque si se puede ejecutar entera; si no
    (p. ej. Fusion cerrado), esa cadena se omite y no para nada."""
    include, todo = set(), list(roots)
    while todo:
        for x in _up(req, blocks, todo.pop()):
            if x in include:
                continue
            include.add(x)
            for ip, (src, _) in edges.get(x, {}).items():
                if ip in req.get(x, {}) or src in include or src not in blocks:
                    continue
                if not any(_why_not(board, y, sts[y], blocks) for y in _up(req, blocks, src)):
                    todo.append(src)
    return [b for b in _up(edges, blocks, *roots) if b in include]


def would_run(board, block_id):
    """Los bloques que ejecutaría *Ejecutar* de `block_id` ahora (D89): él y lo de delante que
    no está al día, con las cadenas opcionales que se pueden ejecutar (D122). No planea ni
    apunta nada en `board.job`: sirve para saber antes qué se va a lanzar (`ejecutar_bloque`
    del agente nunca lanza un bloque que pide un conector)."""
    edges, _ = graph.build(board.elements, board.registry)
    req = graph.required(edges, board.elements, board.registry)
    blocks = graph.blocks_in(board.elements, board.registry)
    if block_id not in blocks:
        return []
    sts, _ = board.explain()
    order = _order(board, edges, req, blocks, sts, [block_id])
    return [b for b in order if b == block_id or sts.get(b) != "al_dia"]


class Job:
    def __init__(self, board, targets, order, skipped=(), options=None):
        self.board = board
        self.options = dict(options or {})   # {bloque: {acción: True}}: solo esos bloques
        self.targets = set(targets)
        self.order = list(order)
        self.skipped = list(skipped)     # [(bloque, motivo)]: lo que no se ejecutó y por qué
        self.done = []                   # bloques que terminaron bien
        self.failed = []                 # bloques que dieron error
        self.cancelled = False
        self.current = None              # Step en curso
        self.progress = (None, "")       # (fracción | None, mensaje) del bloque en curso
        self._pos = 0

    # ------------------------------------------------------------------ plan
    @classmethod
    def plan(cls, board, block_id=None, options=None):
        """La ejecución de `block_id` (con lo de delante) o, sin él, la de todo lo que no
        está al día. Una por proyecto a la vez: se apunta en `board.job` hasta `close()`.
        `options` (de pulsar el botón de una confirmación, D112) va solo a `block_id`."""
        if board.job is not None:
            raise validation.ValidationError(i18n.t("ejecucion.ya_en_curso"))
        edges, _ = graph.build(board.elements, board.registry)
        req = graph.required(edges, board.elements, board.registry)
        blocks = graph.blocks_in(board.elements, board.registry)
        sts, reasons = board.explain()
        if block_id is not None:
            if block_id not in blocks:
                raise validation.ValidationError(i18n.t("bloque.no_existe", id=repr(block_id)))
            # Se comprueba la cadena entera antes de empezar: si algo no se puede ejecutar, no
            # se ejecuta nada (D89). Lo de delante de una entrada opcional no cuenta (D122).
            for bid in _up(req, blocks, block_id):
                why = _why_not(board, bid, sts[bid], blocks, reasons)
                if why:
                    raise validation.ValidationError(
                        why if bid == block_id else i18n.t("ejecucion.no_se_ejecuta_nada", motivo=why))
            job = cls(board, [block_id], _order(board, edges, req, blocks, sts, [block_id]),
                      options={block_id: dict(options)} if options else None)
        else:
            targets, skipped = [], []
            for bid in _up(edges, blocks, *sorted(blocks)):
                if sts[bid] not in ("nunca", "desactualizado", "error"):
                    continue
                why = next((w for b in _up(req, blocks, bid)
                            if (w := _why_not(board, b, sts[b], blocks, reasons))), None)
                if why:
                    skipped.append((bid, why))
                else:
                    targets.append(bid)
            if not targets:
                raise validation.ValidationError(
                    i18n.t("ejecucion.todo_al_dia") if not skipped
                    else i18n.t("ejecucion.nada_ejecutable",
                                motivos="; ".join(sorted({w for _, w in skipped}))))
            # Lo de detrás que ahora está al día también entra en el orden (e2e del 20/11): una
            # entrada opcional cuenta por su hash y no por el estado de su bloque (D122), así
            # que la lista que usa un Analizar en error sigue al día hasta que este da
            # resultado, y se desactualiza a mitad de la ejecución. `next` lo salta si sigue
            # al día.
            later = [b for b in _down(edges, blocks, targets) if b not in targets and not any(
                _why_not(board, u, sts[u], blocks, reasons) for u in _up(req, blocks, b))]
            job = cls(board, targets, _order(board, edges, req, blocks, sts, targets + later),
                      skipped)
        board.job = job
        return job

    # ------------------------------------------------------------- paso a paso
    def next(self):
        """El siguiente bloque a ejecutar, o None si no queda nada. Se decide ahora, no al
        planear: lo de delante puede haber dado la misma carga (y lo de detrás seguir al día) o
        haber fallado (y lo de detrás no se ejecuta)."""
        board = self.board
        while self._pos < len(self.order):
            bid = self.order[self._pos]
            self._pos += 1
            edges, _ = graph.build(board.elements, board.registry)
            blocks = graph.blocks_in(board.elements, board.registry)
            if bid not in blocks:
                continue                                   # lo borraron mientras corría
            sts, reasons = board.explain()
            req = graph.required(edges, board.elements, board.registry)
            ups = sorted({src for src, _ in req.get(bid, {}).values()   # una opcional no para,
                          if src in blocks})                            # ni una tarjeta (D131)
            if any(sts.get(u) != "al_dia" for u in ups):
                if bid in self.targets:
                    self.skipped.append((bid, i18n.t("ejecucion.delante_fallo")))
                continue
            why = _why_not(board, bid, sts[bid], blocks, reasons)
            if why:                                        # cambió mientras corría
                self.skipped.append((bid, why))
                continue
            if bid not in self.targets and sts[bid] == "al_dia":
                continue
            return self._step(bid, edges, blocks)
        return None

    def _step(self, bid, edges, blocks):
        board = self.board
        kind = blocks[bid]["customData"]["blockType"]
        st = board.state.setdefault(bid, {})
        params = copy.deepcopy(st.setdefault("params", board.default_params(kind)))
        inputs = {}
        optional = board.registry[kind].optional
        cards = graph.sources_in(board.elements)
        for ip, (src, op) in edges.get(bid, {}).items():
            if src in cards:                 # un archivo o una carpeta: sus rutas (D145)
                inputs[ip] = files.card_payload(cards[src]["customData"]["kind"],
                                                board.card_path(cards[src]), board.sources[src])
                continue
            if ip in optional and op not in ((board.state.get(src) or {}).get("outputs") or {}):
                continue                     # opcional sin resultado: el bloque va sin ella (D122)
            payload = copy.deepcopy(board.state[src]["outputs"][op])
            for f in payload.values():
                if isinstance(f, dict) and "file" in f:
                    f["path"] = str(board.ws.block_file(board.project_id, src, f["file"]))
            inputs[ip] = payload
        step = Step(block_id=bid, kind=kind, params=params, inputs=inputs,
                    input_hash=graph.input_hash(bid, params, edges, board.state, board.sources,
                                                board.param_files.get(bid)),
                    workdir=str(board.ws.block_scratch(board.project_id, bid)),
                    options=self.options.pop(bid, {}), env=board.run_env(bid))
        self.current, self.progress = step, (None, "")
        return step

    def finish(self, step, outcome):
        """Guarda lo que dio el bloque. Devuelve si terminó bien."""
        board, bid = self.board, step.block_id
        st = board.state.setdefault(bid, {})
        self.current = None
        committed = False
        if outcome[0] == "ok":
            try:
                btype = board.registry[step.kind]
                outputs = check_outputs(btype, outcome[1])
                board.ws.commit_block_files(board.project_id, bid, step.workdir)
                committed = True
                digests = {}

                def digest(name):
                    if name not in digests:
                        p = board.ws.block_file(board.project_id, bid, name)
                        digests[name] = hashlib.sha256(p.read_bytes()).hexdigest()
                    return digests[name]

                for payload in outputs.values():
                    for f in payload.values():
                        if "file" in f:
                            digest(f["file"])        # existe y está en su carpeta, o error
                        f["source"] = f"bloque:{bid}"
                hashes = graph.outputs_hash(outputs, digest)
            except (ValueError, TypeError, OSError, KeyError) as exc:   # StorageError incluido
                outcome = ("error", f"{type(exc).__name__}: {exc}")
            else:
                st.update(error=None, error_action=None, outputs=outputs, outputs_hash=hashes,
                          last_hash=step.input_hash)
                # con qué versión de su paquete (P25): con otra instalada, sale desactualizado
                info = board.registry.pack_of(step.kind) if hasattr(board.registry, "pack_of") else None
                if info is not None:
                    st["pack_version"] = info.version
                board.write_pack_lock()
                self.done.append(bid)
                # A las carpetas de sus flechas (D109): solo lo que termina bien, y una copia
                # que falla deja aviso en la carpeta, nunca error en el bloque.
                try:
                    board.copy_outputs(bid)
                except Exception as exc:      # noqa: BLE001 el bloque ya terminó bien
                    copies = graph.connections(board.elements, board.registry)[1]
                    for folder, links in copies.items():
                        if any(src == bid for src, _, _ in links):
                            board.copy_notices[folder] = i18n.t("ejecucion.copia_fallo", motivo=exc)
                return True
        # Error: el bloque se queda sin salidas ni archivos, y lo de detrás no se ejecuta.
        try:
            if not committed:
                board.ws.discard_block_scratch(step.workdir)
            board.ws.clear_block_files(board.project_id, bid)
        except (StorageError, OSError):
            pass
        # Un error que pide confirmación (D112) lleva su acción: la tarjeta pinta el botón.
        action = outcome[2] if len(outcome) > 2 else None
        st.update(error=outcome[1], error_action=action, last_hash=None, outputs=None,
                  outputs_hash=None)
        self.failed.append(bid)
        return False

    def abort(self, step):
        """Cancelado: el bloque en curso queda exactamente como estaba."""
        self.current = None
        self.cancelled = True
        try:
            self.board.ws.discard_block_scratch(step.workdir)
        except (StorageError, OSError):
            pass

    def close(self):
        if self.board.job is self:
            self.board.job = None

    # ------------------------------------------------------------- para la interfaz
    def view(self):
        """Lo que enseñan las tarjetas mientras dura (no se guarda): el bloque en curso con su
        progreso y lo que queda en cola."""
        sts = self.board.statuses()
        queued = [b for b in self.order[self._pos:]
                  if b in sts and (b in self.targets or sts[b] != "al_dia")]
        frac, msg = self.progress
        return {"block": self.current.block_id if self.current else None,
                "fraction": frac, "message": msg, "queued": queued}

    def summary(self):
        return {"done": list(self.done), "failed": list(self.failed),
                "cancelled": self.cancelled,
                "skipped": [{"block": b, "reason": r} for b, r in self.skipped]}


def check_outputs(btype, outputs):
    """Lo que devuelve `run` tiene que traer exactamente los puertos de salida del tipo, cada
    campo con `value`, y poder guardarse como JSON (plan D94). Si no, es un error del bloque."""
    if not isinstance(outputs, dict) or set(outputs) != set(btype.outputs):
        got = sorted(outputs) if isinstance(outputs, dict) else type(outputs).__name__
        raise ValueError(f"{btype.kind} devolvió {got}, se esperaban los puertos "
                         f"{sorted(btype.outputs)}")
    for port, payload in outputs.items():
        if not isinstance(payload, dict) or not all(
                isinstance(f, dict) and "value" in f for f in payload.values()):
            raise ValueError(f"{btype.kind}: la salida {port!r} no son campos con value")
        for name, f in payload.items():
            if "file" in f and not isinstance(f["file"], str):
                raise ValueError(f"{btype.kind}: {port}.{name} cita un archivo que no es un nombre")
    try:                       # lo mismo que se guardará; sin ∞ ni NaN, que el navegador no lee
        return json.loads(json.dumps(outputs, ensure_ascii=False, allow_nan=False))
    except ValueError:
        raise ValueError(f"{btype.kind}: una salida tiene un número infinito o NaN; "
                         "el bloque tiene que darlo como None") from None


def execute(registry, step, progress=None):
    """Ejecuta un paso con el `run` de su tipo. Nunca lanza: el error vuelve como resultado
    (`pack_data.run_step`, el mismo que usa el trabajador)."""
    return pack_data.run_step(registry, asdict(step), progress)


def run_inline(job, registry=None):
    """Recorre la ejecución en este proceso. Devuelve `job.summary()`."""
    registry = registry if registry is not None else job.board.registry
    try:
        while (step := job.next()) is not None:
            job.finish(step, execute(registry, step))
    finally:
        job.close()
    return job.summary()


async def run_job(job, worker, on_event):
    """Recorre la ejecución con `worker` (un `ProcessWorker`) sin bloquear el servidor.

    `on_event(kind)` (async) avisa: "step" al empezar un bloque, "progress" cuando llega
    progreso (en `job.progress`) y "done" cuando un bloque ha terminado y hay que guardarlo.
    Devuelve `job.summary()`."""
    async def on_progress(fraction, message):
        job.progress = (fraction, message)
        await on_event("progress")

    try:
        while (step := job.next()) is not None:
            await on_event("step")
            outcome = await worker.run(step, on_progress)
            if outcome[0] == "cancelled":
                job.abort(step)
                break
            job.finish(step, outcome)
            await on_event("done")
    finally:
        job.close()
        worker.close()
    return job.summary()


# --------------------------------------------------------------- proceso de cálculo
def _child_main(conn, pack_dirs, validated=None):
    """Proceso de cálculo: carga los paquetes y ejecuta los pasos que le llegan, de uno en uno.
    Sale cuando se le dice o cuando el servidor desaparece (la tubería se cierra)."""
    from pizarra import packs
    # con las validaciones guardadas del backend (P80): lo que él ya validó no se repite
    registry = packs.load(pack_dirs, log=lambda _msg: None, validated=validated)
    last = [0.0]

    def progress(fraction=None, message=""):
        now = time.monotonic()
        if now - last[0] >= PROGRESS_EVERY or fraction == 1:
            last[0] = now
            conn.send(("progress", fraction, str(message)))

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg[0] != "run":
            return
        out = execute(registry, Step(**msg[1]), progress)
        try:
            conn.send(("result", out))
        except Exception as exc:      # noqa: BLE001 p. ej. una salida que no se puede enviar
            conn.send(("result", ("error", f"la salida no se puede enviar: {exc}")))


class ProcessWorker:
    """Un proceso de cálculo para una ejecución (D92): el motor es Python puro y, en un hilo,
    ocuparía el GIL del servidor (el WebSocket y las demás ventanas se congelarían), y un
    cálculo atascado no se podría parar. `kill()` lo mata: es *Cancelar*."""

    def __init__(self, pack_dirs, validated=None):
        mp = multiprocessing.get_context("spawn")
        self._conn, child = mp.Pipe()
        self._proc = mp.Process(target=_child_main,
                                args=(child, [str(d) for d in pack_dirs], validated),
                                daemon=True, name="pizarra-calculo")
        self._proc.start()
        child.close()
        self.killed = False

    async def run(self, step, on_progress):
        try:
            self._conn.send(("run", asdict(step)))
        except (OSError, ValueError):
            return self._dead()
        while True:
            try:
                ready = self._conn.poll()
                msg = self._conn.recv() if ready else None
            except (EOFError, OSError):
                return self._dead()
            if msg is not None:
                if msg[0] == "progress":
                    await on_progress(msg[1], msg[2])
                    continue
                return tuple(msg[1])
            if not self._proc.is_alive():
                return self._dead()
            await asyncio.sleep(POLL)

    def _dead(self):
        if self.killed:
            return ("cancelled", None)
        return ("error", i18n.t("ejecucion.proceso_muerto", codigo=self._proc.exitcode))

    def kill(self):
        self.killed = True
        if self._proc.is_alive():
            self._proc.kill()
            # Muerto de verdad antes de seguir: si se va a borrar el proyecto, ya no tiene
            # abierta su carpeta de trabajo.
            self._proc.join(timeout=2)

    def close(self):
        try:
            if self._proc.is_alive() and not self.killed:
                self._conn.send(("stop",))
            self._proc.join(timeout=2)
        except (OSError, ValueError):
            pass
        if self._proc.is_alive():
            self._proc.kill()
            self._proc.join(timeout=2)
        self._conn.close()
