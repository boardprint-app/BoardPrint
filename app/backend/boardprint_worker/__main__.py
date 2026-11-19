"""`python -m boardprint_worker`: ver el docstring del paquete.

Protocolo v2 (docs/PLAN_PAQUETES.md §4, P90, P91): un JSON por línea en cada sentido.

- El backend pide `{"id", "op", ...}`; el trabajador contesta `{"id", "ok": true, ...}` o
  `{"id", "ok": false, "error"}`. Una petición a la vez.
- Antes de contestar, puede mandar `{"id", "progress": [fracción, mensaje]}` (al ejecutar) y, en
  una acción, `{"id", "call": método, "args": [...], "cid"}`: una llamada a la pizarra (la API
  de P39) que el backend contesta con `{"reply_to": cid, "ok": true, "result"}` o
  `{"reply_to": cid, "ok": false, "error"}`.
- Mientras espera esa respuesta, el backend puede pedir otra cosa (`{"id", "op", ...}`, con su
  propio id): la pide desde dentro de la llamada, en el mismo hilo (su cerrojo es reentrante;
  p. ej. si un conector responde). Se atiende entera y se sigue esperando (P109).

Operaciones: `register {dirs, validated}`, `run {step}`, `preview {kind, params, inputs}`,
`action {name, block_id, params, inputs, args, env, board}`, `connector {connector, method, args}` y
`exit`.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

PROGRESS_EVERY = 0.1      # s: el progreso no satura el canal (como el proceso de cálculo, D92)


def _protocol_channel():
    """Se queda con el stdout de verdad para el protocolo y manda a stderr todo lo demás,
    también lo que se escriba en el descriptor 1 por debajo de Python."""
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


class Channel:
    def __init__(self, out, inp):
        self.out, self.inp = out, inp
        self.cid = 0
        self.serve = None           # atiende una petición que llega esperando (P109)

    def send(self, obj):
        self.out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.out.flush()

    def call(self, rid, method, args):
        """Una llamada a la pizarra durante la petición `rid`: espera su respuesta."""
        self.cid += 1
        self.send({"id": rid, "call": method, "args": args, "cid": self.cid})
        while True:
            line = self.inp.readline()
            if not line:
                raise EOFError("el backend cerró el canal")
            if not line.strip():
                continue
            msg = json.loads(line)
            if "op" in msg and "reply_to" not in msg and self.serve is not None:
                self.serve(msg)     # una petición del backend dentro de esta llamada (P109)
                continue
            if msg.get("reply_to") != self.cid:
                raise RuntimeError(f"respuesta inesperada del backend: {line.strip()[:200]}")
            if not msg.get("ok"):
                raise ValueError(msg.get("error") or "la pizarra no lo admite")
            return msg.get("result")


class RemoteBoard:
    """La API de P39 de una acción, con la pizarra al otro lado. `block_type` se resuelve aquí:
    el tipo del bloque sale de la pizarra y su `BlockType`, con sus funciones, del registro de
    este proceso (P91)."""

    def __init__(self, channel, rid, registry):
        self._ch, self._rid, self._reg = channel, rid, registry

    def _call(self, method, *args):
        return self._ch.call(self._rid, method, list(args))

    def block(self, block_id):
        return self._call("block", block_id)

    def upstream(self, block_id, port):
        return self._call("upstream", block_id, port)

    def set_params(self, block_id, params):
        self._call("set_params", block_id, params)

    def postits(self, block_id):
        return self._call("postits", block_id)

    def add_postit(self, block_id, text, kind="nota", keys=()):
        return self._call("add_postit", block_id, text, kind, list(keys) if not isinstance(keys, str) else keys)

    def clear_error(self, block_id, action):
        return self._call("clear_error", block_id, action)

    def block_file(self, block_id, name):
        got = self._call("block_file", block_id, name)
        return Path(got) if got is not None else None

    def block_type(self, block_id):
        info = self.block(block_id)
        return None if not info else self._reg.get(info.get("type"))


def _need(registry):
    if registry is None:
        raise ValueError("primero hay que registrar los paquetes")
    return registry


def _run(ch, rid, registry, msg):
    from pizarra import pack_data
    last = [0.0]

    def progress(fraction=None, message=""):
        now = time.monotonic()
        if now - last[0] >= PROGRESS_EVERY or fraction == 1:
            last[0] = now
            ch.send({"id": rid, "progress": [fraction, str(message)]})

    outcome = pack_data.run_step(registry, msg["step"], progress)
    if outcome[0] == "ok":
        try:
            outcome = ("ok", pack_data.as_json(outcome[1]))
        except (TypeError, ValueError) as exc:
            outcome = ("error", f"la salida no se puede enviar: {exc}")
    return {"outcome": list(outcome)}


def _preview(registry, msg):
    from pizarra import pack_data
    btype = registry.get(msg["kind"])
    if btype is None or btype.preview is None:
        raise ValueError(f"el bloque {msg['kind']!r} no tiene vista previa")
    try:
        result = btype.preview(msg.get("params") or {}, msg.get("inputs") or {})
    except (ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"result": pack_data.as_json(result)}


def _action(ch, rid, registry, msg):
    from pizarra import pack_data, packs
    name = msg["name"]
    act = registry.actions.get(name)
    if act is None:
        return {"ok": False, "error": f"el paquete {packs.pack_id_of(name)} no tiene la acción {name!r}"}
    ctx = pack_data.context(msg.get("block_id", ""), msg.get("env"))
    if msg.get("board"):
        ctx._board = RemoteBoard(ch, rid, registry)
    try:
        result = act.run(msg.get("params") or {}, msg.get("inputs") or {}, msg.get("args") or {}, ctx)
    except Exception as exc:          # noqa: BLE001 el motivo vuelve al backend
        traceback.print_exc(file=sys.stderr)
        return {"ok": False, "error": packs.action_error(name, exc)}
    try:
        return {"result": pack_data.as_json(result)}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"{name} no devuelve JSON: {exc}"}


def _connector(registry, msg):
    c = registry.connectors.get(msg["connector"])
    if c is None:
        raise ValueError(f"no hay ningún conector {msg['connector']!r}")
    method = msg["method"]
    if method == "available":
        return {"result": bool(c.available())}
    if method in ("launch", "open_file"):
        fn = getattr(c, method)
        if fn is None:
            raise ValueError(f"el conector {c.id} no sabe {method}")
        return {"result": fn(*(msg.get("args") or []))}
    raise ValueError(f"método de conector desconocido: {method!r}")


class Exit(Exception):
    """`exit`: el backend cierra el trabajador."""


class Worker:
    """Atiende las peticiones del backend, también las que llegan dentro de una llamada a la
    pizarra (`Channel.serve`, P109)."""

    def __init__(self, ch):
        self.ch = ch
        self.registry = None
        ch.serve = self.handle

    def handle(self, msg):
        from pizarra import pack_data, packs
        t0 = time.perf_counter()
        rid = msg.get("id")
        op = msg.get("op")
        if op == "exit":
            raise Exit()
        try:
            if op == "register":
                self.registry = packs.load(msg.get("dirs") or [], validated=msg.get("validated"),
                                           log=lambda m: print(m, file=sys.stderr))
                body = {"registry": pack_data.to_data(self.registry)}
            elif op == "run":
                body = _run(self.ch, rid, _need(self.registry), msg)
            elif op == "preview":
                body = _preview(_need(self.registry), msg)
            elif op == "action":
                body = _action(self.ch, rid, _need(self.registry), msg)
            elif op == "connector":
                body = _connector(_need(self.registry), msg)
            else:
                raise ValueError(f"operación desconocida: {op!r}")
        except (EOFError, Exit):
            raise
        except Exception as exc:          # noqa: BLE001 el error vuelve al backend
            traceback.print_exc(file=sys.stderr)
            self.ch.send({"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self.ch.send({"id": rid, "ok": True, **body, "seconds": time.perf_counter() - t0})


def main():
    out = _protocol_channel()
    worker = Worker(Channel(out, sys.stdin))
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError as exc:
            traceback.print_exc(file=sys.stderr)
            worker.ch.send({"id": None, "ok": False, "error": f"ValueError: {exc}"})
            continue
        try:
            worker.handle(msg)
        except (EOFError, Exit):
            return


if __name__ == "__main__":
    main()
