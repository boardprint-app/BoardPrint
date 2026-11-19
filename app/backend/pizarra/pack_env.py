"""Entorno de paquetes y trabajador (docs/PLAN_PAQUETES.md P19-P21, §4): la prueba de FF 10.1
paso 1, que FF 10.4 convierte en el de verdad.

- El *pyenv* de la app (recursos, `app/shell/fetch_pyenv.py`): un Python standalone sin
  librerías y `uv`.
- El *entorno de paquetes*: un venv en `<caché>/envs/<huella>/` con las librerías de los
  paquetes (`[python] dependencies` de su `pack.toml`), hecho con `uv` contra ese Python. La
  caché de `uv` (`<caché>/uv`) guarda cada librería una vez y la enlaza en cada entorno.
- El *trabajador* (`boardprint_worker`): un proceso en ese entorno que registra los paquetes y
  ejecuta bloques, hablando por stdin/stdout (ver su docstring).

Python puro (stdlib): se testea en `tests/test_pack_env.py`. La prueba de punta a punta en la
app instalada es `python -m pizarra.pack_env --probe ...` (o el sidecar con
`--probe-pack-env`), que lanza `app/shell/smoke_pack_env.py` en el CI.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from pizarra import i18n

EXE = ".exe" if sys.platform == "win32" else ""
OK_MARK = ".boardprint-ok"          # un entorno sin esta marca está a medias y no vale
# Lo que el ejecutable de PyInstaller (o el Python del backend) deja en el entorno y que otro
# Python no debe heredar: le cambiaría la stdlib o el sys.path.
INHERITED = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "PYTHONUSERBASE",
             "VIRTUAL_ENV", "CONDA_PREFIX", "_MEIPASS2", "TCL_LIBRARY", "TK_LIBRARY",
             "UV_PYTHON", "UV_PROJECT_ENVIRONMENT", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL")
# Sin ventana de consola: el backend corre sin consola y un python.exe abriría una.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EnvError(RuntimeError):
    """No se pudo crear el entorno de paquetes; el mensaje dice por qué."""


class Pyenv:
    """El Python y el `uv` que trae la app (P21)."""

    def __init__(self, root, uv=None):
        self.root = Path(root)
        self.python = self.root / "python" / ("python.exe" if EXE else "bin/python3")
        # `uv` puede ser un comando entero (los tests le pasan uno de mentira).
        self.uv = list(uv) if uv else [str(self.root / f"uv{EXE}")]
        meta = self.root / "pyenv.json"
        self.meta = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}

    def check(self):
        if not self.python.is_file():
            raise EnvError(i18n.t("entorno.sin_python", ruta=self.python))


def clean_env(base=None, cache_dir=None, extra_path=()):
    """El entorno de un proceso del Python de paquetes o de `uv`: sin nada del Python que lo
    lanza, `uv` sin descargar Pythons ni leer configuración del usuario, y en UTF-8.

    Los `.pyc` van a `<caché>/pycache`: los recursos de la app y las carpetas de los paquetes
    no traen `__pycache__`, y sin él cada proceso (uno por ejecución) recompilaría todo."""
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if k.upper() not in INHERITED and not k.upper().startswith("_PYI")
           and k.upper() not in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
    env.update(PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               UV_PYTHON_DOWNLOADS="never", UV_NO_CONFIG="1", UV_NO_PROGRESS="1")
    if cache_dir is not None:
        env["UV_CACHE_DIR"] = str(Path(cache_dir).resolve() / "uv")
        env["PYTHONPYCACHEPREFIX"] = str(Path(cache_dir).resolve() / "pycache")
    if extra_path:
        env["PYTHONPATH"] = os.pathsep.join(str(p) for p in extra_path)
    return env


def _norm(req):
    return " ".join(str(req).split()).lower()


def requirements(pack_dirs):
    """Las librerías que piden los paquetes de `pack_dirs` (`[python] dependencies`)."""
    reqs = []
    for d in pack_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for manifest in sorted(d.glob("*/pack.toml")):
            try:
                data = tomllib.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue                  # el paquete roto lo dirá la carga
            reqs.extend(str(r) for r in (data.get("python") or {}).get("dependencies") or [])
    return reqs


def env_hash(reqs, pyenv_meta):
    """La huella de un entorno: las librerías (sin orden ni repetidas) y el Python de la app."""
    key = json.dumps({"reqs": sorted({_norm(r) for r in reqs}),
                      "pyenv": {k: pyenv_meta.get(k) for k in ("python", "uv", "triple")}},
                     sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def env_python(env_dir):
    env_dir = Path(env_dir)
    return env_dir / ("Scripts/python.exe" if EXE else "bin/python")


def _uv(pyenv, args, cache_dir):
    proc = subprocess.run(pyenv.uv + args, env=clean_env(cache_dir=cache_dir),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=NO_WINDOW)
    if proc.returncode:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-15:])
        raise EnvError(f"uv {args[0]} {args[1] if len(args) > 1 else ''} falló "
                       f"(código {proc.returncode}):\n{tail}")
    return proc


def _compile(env_dir, cache_dir):
    """Los `.pyc` de las librerías, al instalar y no en el primer import (numpy tarda ~1,5 s
    en compilarse). Van a `<caché>/pycache` como los demás (`clean_env`): por eso no vale
    `uv pip install --compile-bytecode`, que los deja junto a los fuentes y Python, con
    `PYTHONPYCACHEPREFIX`, no los mira. Es una optimización: si falla, se compilan al usarse."""
    py = env_python(env_dir)
    if not py.is_file():
        return
    for site in Path(env_dir).glob("[Ll]ib/**/site-packages"):
        try:
            subprocess.run([str(py), "-m", "compileall", "-q", "-j", "0", str(site)],
                           env=clean_env(cache_dir=cache_dir), capture_output=True,
                           creationflags=NO_WINDOW, timeout=600)
        except (OSError, subprocess.TimeoutExpired):
            pass


def ensure_env(pyenv, cache_dir, reqs):
    """El entorno de `reqs` en `<cache_dir>/envs/<huella>/`, creado si no está. Devuelve
    `(carpeta, creado)`. Si `uv` falla no deja nada (ni a medias) y lanza `EnvError`."""
    pyenv.check()
    cache_dir = Path(cache_dir)
    env_dir = cache_dir / "envs" / env_hash(reqs, pyenv.meta)
    if (env_dir / OK_MARK).is_file():
        return env_dir, False
    if env_dir.exists():
        shutil.rmtree(env_dir, ignore_errors=True)         # uno a medias de otra vez
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        _uv(pyenv, ["venv", "--python", str(pyenv.python), "--no-project", "--quiet",
                    str(env_dir)], cache_dir)
        if reqs:
            _uv(pyenv, ["pip", "install", "--python", str(env_python(env_dir)), "--quiet",
                        *sorted({_norm(r) for r in reqs})], cache_dir)
            _compile(env_dir, cache_dir)
        (env_dir / OK_MARK).write_text(json.dumps({"reqs": sorted(reqs), "pyenv": pyenv.meta}),
                                       encoding="utf-8")
    except BaseException:
        shutil.rmtree(env_dir, ignore_errors=True)
        raise
    return env_dir, True


def _pack_reqs(folder):
    """`[python] dependencies` de un paquete, tolerante: el paquete roto lo dirá la carga."""
    try:
        data = tomllib.loads((Path(folder) / "pack.toml").read_text(encoding="utf-8"))
        return [str(r) for r in (data.get("python") or {}).get("dependencies") or []]
    except (OSError, tomllib.TOMLDecodeError, AttributeError, TypeError):
        return []


class PackEnvironment:
    """El entorno de paquetes de la app (docs/PLAN_PAQUETES.md §4, P20, P92, P93): da el
    trabajador (`pack_host.WorkerSpec`) para unos orígenes.

    - Las librerías son las de los paquetes **que se usan** (el de más prioridad de cada id,
      §3), resueltas juntas por `uv` en `<caché>/envs/<huella>/` (`ensure_env`). Sin ninguna,
      el Python de la app tal cual.
    - Si no cuadran (o no hay internet y no están en la caché), `EnvError` con qué paquete pide
      qué y lo que dice `uv`.
    - Con `pyenv=None` (desarrollo sin `fetch_pyenv.py`) el Python es `python` y no se instala
      ninguna librería: un paquete que pida alguna da `EnvError`."""

    def __init__(self, worker_dir, engine_dir=None, cache_dir=None, pyenv=None, python=None,
                 stderr=None):
        self.worker_dir, self.engine_dir = str(worker_dir), engine_dir and str(engine_dir)
        self.cache_dir = cache_dir and str(cache_dir)
        self.pyenv = pyenv
        self.python = str(pyenv.python) if pyenv is not None else str(python or sys.executable)
        self.stderr = stderr

    def requirements(self, origins):
        """`{paquete: [librerías]}` de los paquetes que se usan con `origins`."""
        from pizarra import packs
        found = packs.discover(packs._as_origins(origins))
        out = {}
        for pid, places in sorted(found.items()):
            reqs = _pack_reqs(places[0][1])
            if reqs:
                out[pid] = reqs
        return out

    def _spec(self, python):
        from pizarra.pack_host import WorkerSpec
        return WorkerSpec(python=str(python), worker_dir=self.worker_dir,
                          engine_dir=self.engine_dir, cache_dir=self.cache_dir,
                          stderr=self.stderr)

    def base_spec(self):
        """El trabajador sin librerías: el Python de la app."""
        return self._spec(self.python)

    def spec(self, origins):
        """El trabajador con las librerías de los paquetes de `origins`, creando su entorno si
        hace falta (puede descargar). `EnvError` si no se puede."""
        by_pack = self.requirements(origins)
        if not by_pack:
            return self.base_spec()
        who = "\n".join(f"- {pid}: {', '.join(r)}" for pid, r in by_pack.items())
        if self.pyenv is None or not self.cache_dir:
            raise EnvError(i18n.t("entorno.sin_entorno", quien=who))
        reqs = [r for rs in by_pack.values() for r in rs]
        try:
            env_dir, _ = ensure_env(self.pyenv, self.cache_dir, reqs)
        except EnvError as exc:
            raise EnvError(i18n.t("entorno.no_se_instalan", quien=who, motivo=exc)) from None
        return self._spec(env_python(env_dir))

    def cleanup(self, keep):
        """Borra de `<caché>/envs` los entornos que no son `keep` (el `WorkerSpec` de ahora):
        cambiar de paquetes deja el de antes sin nadie que lo use."""
        if not self.cache_dir:
            return
        envs = Path(self.cache_dir) / "envs"
        current = Path(keep.python).resolve() if keep else None
        for d in envs.glob("*") if envs.is_dir() else []:
            if current is None or not current.is_relative_to(d.resolve()):
                shutil.rmtree(d, ignore_errors=True)


class PackWorker:
    """Un trabajador de paquetes: `python -m boardprint_worker` en el entorno de paquetes."""

    def __init__(self, python, worker_dir, engine_dir, cache_dir=None, stderr=None):
        self.started = time.perf_counter()
        self.proc = subprocess.Popen(
            [str(python), "-m", "boardprint_worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            env=clean_env(cache_dir=cache_dir, extra_path=[worker_dir, engine_dir]),
            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)

    def request(self, msg):
        try:
            self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        except (BrokenPipeError, OSError):
            line = ""
        if not line:
            code = self.proc.wait(timeout=5)
            raise RuntimeError(f"el trabajador de paquetes terminó de golpe (código {code})")
        return json.loads(line)

    def close(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write('{"op": "exit"}\n')
                self.proc.stdin.flush()
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait(timeout=5)
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ----------------------------------------------------------------- prueba (FF 10.1 paso 1)
def _probe_run(w, dirs, kind):
    """Registra `dirs` y ejecuta `kind` con sus parámetros por defecto (protocolo v2 del
    trabajador). Deja la respuesta en `w.last` y devuelve cuándo empezó a ejecutar."""
    reg = w.request({"op": "register", "dirs": dirs})
    params = {n: v[0] for n, v in reg["registry"]["blocks"][kind]["params"].items()}
    t1 = time.perf_counter()
    w.last = w.request({"op": "run", "step": {"block_id": "probe", "kind": kind,
                                              "params": params, "inputs": {}}})
    return t1


def probe(pyenv_dir, cache_dir, worker_dir, engine_dir, pack_dirs, run_kind, uv=None,
          baseline_kind=None):
    """Crea el entorno de los paquetes de `pack_dirs`, arranca trabajadores y mide (§12):
    crear el entorno, registrar en frío y en caliente y una ejecución (un proceso por
    ejecución, D92: arrancar, registrar y ejecutar). Con `baseline_kind`, además ese bloque
    en el trabajador y como se ejecuta hoy, para restar."""
    pyenv = Pyenv(pyenv_dir, uv)
    cache_dir = Path(cache_dir)
    log = (cache_dir / "logs").resolve()
    log.mkdir(parents=True, exist_ok=True)
    reqs = requirements(pack_dirs)
    m = {"pyenv": pyenv.meta, "requirements": reqs, "cache_dir": str(cache_dir.resolve())}

    t0 = time.perf_counter()
    env_dir, created = ensure_env(pyenv, cache_dir, reqs)
    m["env_seconds"], m["env_created"], m["env_dir"] = time.perf_counter() - t0, created, str(env_dir)
    t0 = time.perf_counter()
    ensure_env(pyenv, cache_dir, reqs)
    m["env_reuse_seconds"] = time.perf_counter() - t0
    py = env_python(env_dir)
    dirs = [str(Path(d).resolve()) for d in pack_dirs]

    with open(log / "worker.log", "a", encoding="utf-8") as err:
        for label in ("register_cold", "register_warm"):
            t0 = time.perf_counter()
            with PackWorker(py, worker_dir, engine_dir, cache_dir, stderr=err) as w:
                r = w.request({"op": "register", "dirs": dirs})
            m[f"{label}_seconds"] = time.perf_counter() - t0
            if not r.get("ok"):
                raise RuntimeError(f"registrar: {r.get('error')}")
        m["packs"] = r["registry"]["packs"]
        m["blocks"] = sorted(r["registry"]["blocks"])
        broken = [p for p in m["packs"] if p["error"]]
        if broken:
            raise RuntimeError(f"paquetes que no cargan en el trabajador: {broken}")

        t0 = time.perf_counter()
        with PackWorker(py, worker_dir, engine_dir, cache_dir, stderr=err) as w:
            t1 = _probe_run(w, dirs, run_kind)
            r = w.last
        m["run_seconds"] = time.perf_counter() - t0
        m["run_only_seconds"] = time.perf_counter() - t1
        if not r.get("ok") or r["outcome"][0] != "ok":
            raise RuntimeError(f"ejecutar {run_kind}: {r.get('error') or r['outcome'][1]}")
        m["run_outputs"] = r["outcome"][1]

        if baseline_kind:
            # Lo mismo que hoy (D92): el proceso de cálculo del backend con sus paquetes,
            # contra el trabajador con el mismo bloque. La diferencia es lo que suma (§12).
            t0 = time.perf_counter()
            with PackWorker(py, worker_dir, engine_dir, cache_dir, stderr=err) as w:
                _probe_run(w, dirs, baseline_kind)
                r = w.last
            m["run_worker_baseline_seconds"] = time.perf_counter() - t0
            if not r.get("ok") or r["outcome"][0] != "ok":
                raise RuntimeError(f"ejecutar {baseline_kind}: {r.get('error')}")
            m["run_today_seconds"] = _run_today(baseline_kind, cache_dir)
    m["env_mb"] = sum(f.stat().st_size for f in Path(env_dir).rglob("*") if f.is_file()) / 1e6
    return m


def _run_today(kind, cache_dir):
    """Una ejecución de `kind` como hoy: `execution.ProcessWorker` con los paquetes de la app."""
    import asyncio
    from pizarra import execution, packs
    dirs = packs.default_dirs()
    reg = packs.load(dirs, log=lambda _m: None)
    workdir = Path(cache_dir) / "probe-today"
    workdir.mkdir(parents=True, exist_ok=True)
    step = execution.Step(block_id="probe", kind=kind, params=reg.default_params(kind),
                          inputs={}, input_hash="", workdir=str(workdir))

    async def go():
        async def on_progress(*_):
            pass
        w = execution.ProcessWorker(dirs)
        try:
            return await w.run(step, on_progress)
        finally:
            w.close()

    t0 = time.perf_counter()
    out = asyncio.run(go())
    if out[0] != "ok":
        raise RuntimeError(f"ejecutar {kind} como hoy: {out[1]}")
    return time.perf_counter() - t0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prueba del entorno de paquetes (FF 10.1 paso 1)")
    ap.add_argument("--probe", "--probe-pack-env", dest="out", required=True,
                    help="fichero JSON donde se dejan las medidas")
    ap.add_argument("--pyenv-dir", required=True)
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--worker-dir", required=True,
                    help="carpeta con boardprint_worker/ y pizarra/ (packs.py, files.py)")
    ap.add_argument("--engine-dir", required=True)
    ap.add_argument("--packs", action="append", default=[],
                    help="carpeta con paquetes (se repite)")
    ap.add_argument("--run", required=True, help="tipo de bloque a ejecutar")
    ap.add_argument("--baseline", default=None,
                    help="tipo de bloque a ejecutar también como hoy (D92), para comparar")
    args, _ = ap.parse_known_args(argv)
    try:
        m = probe(args.pyenv_dir, args.cache_dir, args.worker_dir, args.engine_dir,
                  args.packs, args.run, baseline_kind=args.baseline)
    except Exception as exc:              # noqa: BLE001 el CI enseña el motivo
        m = {"error": f"{type(exc).__name__}: {exc}"}
    Path(args.out).write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(m, indent=2, ensure_ascii=False))
    return 1 if "error" in m else 0


if __name__ == "__main__":
    sys.exit(main())
