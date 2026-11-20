"""Recálculo bajo demanda de las fórmulas de un Excel sin valor guardado (docs/PLAN_EXCEL.md
§3.4, X7, R1, R3).

`excel_names.names(path, recalc)` pide el valor de las fórmulas que el archivo no guarda (un
libro escrito con openpyxl, no por Excel). `Calculator.recalc_for(huella)` da ese `recalc`,
que **nunca espera**:

- Si la caché (`<caché>/excel_calc/<huella>.json`) ya tiene las celdas, las da.
- Si no, lanza el cálculo en un hilo y no da nada: `excel_links` pone esos nombres en
  `calculando`. Al acabar llama a `on_done` (el servidor sondea las pizarras ya, sin esperar a
  que cambie el archivo) y el siguiente sondeo lee la caché.
- El cálculo copia el archivo, crea si hace falta el entorno de xlcalculator con `uv` y corre
  `excel_calc_worker.py` con su Python, sin ventana y como mucho `TIMEOUT` s. Una celda que
  xlcalculator no sabe calcular queda sin valor; las demás siguen.
- Sin entorno (sin el Python de la app, sin `uv`, sin red) o si el script falla, todo queda
  sin valor con el motivo (`failed`), y no se reintenta hasta que cambia el archivo (otra
  huella) o se reabre la app.

Un valor guardado por Excel nunca pasa por aquí (`excel_names` solo pide lo que falta).
"""
import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from pizarra import files, pack_env

REQS = ["xlcalculator==0.5.0"]
# yearfrac 0.4.8 (de xlcalculator) pide numpy<2, y numpy 1.26 no tiene ruedas para el Python
# 3.13 de la app: uv intentaría compilarlo. Con numpy 2 funciona (R3); el tope es el de scipy.
OVERRIDES = ["numpy>=2,<2.7"]
ENVS = "envs-excel"           # aparte de `<caché>/envs`, que limpia `PackEnvironment.cleanup`
TIMEOUT = 60                  # s del script
WORKER_SCRIPT = "pizarra/excel_calc_worker.py"   # relativo a `worker_dir` (recurso `worker/`)
CALCULANDO, ERROR = "calculando", "error"

digest = files.file_digest    # la huella de un archivo, la del sondeo (D134)


class CalcError(RuntimeError):
    """No se pudo recalcular el libro entero. `code` es la clave del motivo
    (`excel.calculo.*`) y `vars`, lo que el texto necesita."""

    def __init__(self, code, **vars):
        super().__init__(code)
        self.code, self.vars = code, vars


def ensure_env(pyenv, cache_dir):
    """La carpeta del entorno de xlcalculator, creado si no está (puede descargar)."""
    env_dir, _ = pack_env.ensure_env(pyenv, cache_dir, REQS, overrides=OVERRIDES, envs=ENVS)
    return env_dir


class Recalc:
    """El `recalc(path, celdas)` de un archivo con su huella para `excel_names.names`.
    Después de llamarlo, `state` es None (ya calculado o nada que calcular), `CALCULANDO` o
    `ERROR`, y `error`, `(código, vars)` del motivo."""

    def __init__(self, calc, digest):
        self.calc, self.digest = calc, digest
        self.state, self.error = None, None

    def __call__(self, path, cells):
        got = self.calc.cached(self.digest, cells)
        if got is not None:
            return got
        self.state, self.error = self.calc.start(path, self.digest, cells)
        return {}


class Calculator:
    """El recálculo de la app. `run(path, celdas) -> {"values", "errors"}` sustituye al de
    verdad (entorno + script) en los tests; sin `run` ni `pyenv`, no hay entorno."""

    def __init__(self, cache_dir, pyenv=None, worker_dir=None, run=None, on_done=None,
                 timeout=TIMEOUT):
        self.dir = Path(cache_dir) / "excel_calc"
        self.cache_dir, self.pyenv = Path(cache_dir), pyenv
        self.script = Path(worker_dir) / WORKER_SCRIPT if worker_dir else None
        self.run = run
        self.on_done, self.timeout = on_done, timeout
        self._lock = threading.Lock()
        self._running = {}        # {huella: hilo}
        self._failed = {}         # {huella: (código, vars)}: no se reintenta (§3.4)

    @classmethod
    def for_app(cls, worker_spec):
        """El de la app con el entorno de paquetes (`pack_env.PackEnvironment`): su caché, su
        pyenv (None en desarrollo sin `fetch_pyenv.py`: sin entorno) y su `worker_dir`. Sin
        caché, None: sin recálculo."""
        if not isinstance(worker_spec, pack_env.PackEnvironment) or not worker_spec.cache_dir:
            return None
        return cls(worker_spec.cache_dir, worker_spec.pyenv, worker_spec.worker_dir)

    def recalc_for(self, digest):
        return Recalc(self, digest)

    def running(self, digest):
        with self._lock:
            return digest in self._running

    def failed(self, digest):
        with self._lock:
            return self._failed.get(digest)

    def join(self, timeout=10):
        """Espera a los cálculos en curso (tests)."""
        for t in list(self._running.values()):
            t.join(timeout)

    # ------------------------------------------------------------------ caché
    def _cache_file(self, digest):
        return self.dir / f"{digest}.json"

    def cached(self, digest, cells):
        """`{celda: valor}` de la caché si tiene todas las `cells` (las que fallaron, sin
        valor), o None si hay que calcular."""
        try:
            data = json.loads(self._cache_file(digest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        known = data.get("values") or {}
        if any(c not in known for c in cells):
            return None
        return {c: known[c] for c in cells if known[c] is not None}

    def _store(self, digest, cells, result):
        values = result.get("values") or {}
        data = {"values": {c: values.get(c) for c in cells},
                "errors": {c: e for c, e in (result.get("errors") or {}).items() if c in cells}}
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_file(digest).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._cache_file(digest))

    # ------------------------------------------------------------------ cálculo
    def start(self, path, digest, cells):
        """Lanza el cálculo de `cells` si no está en marcha ni falló: `(estado, motivo)`."""
        with self._lock:
            if digest in self._failed:
                return ERROR, self._failed[digest]
            if digest in self._running:
                return CALCULANDO, None
            if self.run is None and self.pyenv is None:
                self._failed[digest] = ("excel.calculo.sin_entorno", {})
                return ERROR, self._failed[digest]
            t = threading.Thread(target=self._job, args=(Path(path), digest, list(cells)),
                                 name=f"excel_calc-{digest[:8]}", daemon=True)
            self._running[digest] = t
            t.start()
        return CALCULANDO, None

    def _job(self, path, digest, cells):
        work = Path(tempfile.mkdtemp(prefix="excel_calc-"))
        try:
            copy = work / f"libro{path.suffix.lower()}"
            shutil.copyfile(path, copy)                 # el del usuario se puede guardar mientras
            if files.file_digest(copy) != digest:
                return                                  # ya cambió: lo pedirá su nueva huella
            result = (self.run or self._run)(copy, cells)
            self._store(digest, cells, result)
        except CalcError as exc:
            with self._lock:
                self._failed[digest] = (exc.code, exc.vars)
        except Exception as exc:                        # noqa: BLE001 nunca tumba el sondeo
            with self._lock:
                self._failed[digest] = ("excel.calculo.fallo",
                                        {"motivo": f"{type(exc).__name__}: {exc}"})
        finally:
            shutil.rmtree(work, ignore_errors=True)
            with self._lock:
                self._running.pop(digest, None)
            if self.on_done is not None:
                try:
                    self.on_done()
                except Exception:                       # noqa: BLE001 el aviso es un extra
                    pass

    def _run(self, path, cells):
        """El de verdad: el entorno de xlcalculator y `excel_calc_worker.py` con su Python."""
        if self.pyenv is None:
            raise CalcError("excel.calculo.sin_entorno")
        try:
            env_dir = ensure_env(self.pyenv, self.cache_dir)
        except (pack_env.EnvError, OSError) as exc:
            raise CalcError("excel.calculo.no_se_instala", motivo=str(exc)) from None
        if self.script is None or not self.script.is_file():
            raise CalcError("excel.calculo.sin_script", ruta=str(self.script))
        try:
            # -P: sin la carpeta del script en sys.path (lleva módulos de `pizarra`)
            proc = subprocess.run(
                [str(pack_env.env_python(env_dir)), "-P", str(self.script)],
                input=json.dumps({"path": str(path), "cells": cells}), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=self.timeout,
                env=pack_env.clean_env(cache_dir=self.cache_dir),
                creationflags=pack_env.NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise CalcError("excel.calculo.tiempo", s=self.timeout) from None
        lines = (proc.stdout or "").strip().splitlines()
        try:
            result = json.loads(lines[-1]) if lines else None
        except ValueError:
            result = None
        if proc.returncode or not isinstance(result, dict) or "error" in result:
            tail = (result or {}).get("error") if isinstance(result, dict) else None
            tail = tail or "\n".join((proc.stderr or "").strip().splitlines()[-5:])
            raise CalcError("excel.calculo.fallo", motivo=tail or f"código {proc.returncode}")
        return result


_APP = None


def configure(calculator):
    """El recálculo de la app (`server.create_app`); None, sin recálculo."""
    global _APP
    _APP = calculator


def current():
    return _APP
