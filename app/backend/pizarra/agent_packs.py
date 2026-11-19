"""Los paquetes que hace el agente (docs/PLAN_PAQUETES.md §8, P9, P99-P103).

El agente trabaja en su carpeta de borradores (`<ajustes>/packs-borradores/<id>/`) con estas
funciones, que son sus herramientas (`agent.py`) y se prueban sin él:

- `create`: un borrador desde la plantilla (`pack_template/`), con un bloque de ejemplo y su test.
- `list_files`, `read`, `write`: nunca fuera del borrador (P99).
- `duplicate`: una copia de un paquete instalado con otro id, y dónde sale el de antes (P103).
- `validate`: la validación estática (§1), la carga de prueba en un trabajador del entorno de
  los paquetes instalados más el borrador (P92) y sus tests en ese entorno (P101). El
  resultado se guarda con la huella del borrador.
- `propose`: el resumen para el chat, solo con la última validación en verde y sin cambios
  después (P102).
- `export`: el `.bppack` del borrador propuesto, para el resumen de instalar de siempre (§7).

El agente nunca instala: lo hace el ingeniero desde el resumen.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pizarra import i18n, pack_host, pack_install, packs

DRAFTS = "packs-borradores"
TEMPLATE = Path(__file__).resolve().parent / "pack_template"
GUIDE = Path(__file__).resolve().parent / "pack_guide.md"
REPORTS = ".validaciones"           # dentro de la carpeta de borradores: no es un paquete
MAX_FILE = 1_000_000                # bytes de un fichero que escribe el agente
MAX_READ = 60_000                   # caracteres que devuelve una lectura
TEST_TIMEOUT = 180                  # s de los tests de un borrador


class DraftError(ValueError):
    """Lo que el agente tiene que corregir, dicho para él."""


def guide():
    return GUIDE.read_text(encoding="utf-8")


def drafts_dir(settings_dir):
    return Path(settings_dir) / DRAFTS


def _draft(root, pack_id, must_exist=True):
    if not isinstance(pack_id, str) or not packs.ID_RE.match(pack_id):
        raise DraftError(f"{pack_id!r} no es un id de paquete: minúsculas, cifras y _, "
                         "empezando por una letra")
    folder = Path(root) / pack_id
    if must_exist and not (folder / "pack.toml").is_file():
        raise DraftError(i18n.t("borrador.no_existe", id=repr(pack_id)))
    return folder


def _inside(folder, rel):
    """`folder/rel` si `rel` es una ruta relativa que se queda dentro y no pasa por un enlace."""
    if not isinstance(rel, str) or not rel.strip():
        raise DraftError("falta la ruta del fichero")
    parts = rel.replace("\\", "/").split("/")
    if rel.startswith(("/", "\\")) or ":" in rel or any(p in ("", ".", "..") for p in parts):
        raise DraftError(f"{rel!r}: la ruta tiene que ser relativa y quedarse en el borrador")
    target = folder.joinpath(*parts)
    p = folder
    for part in parts:
        p = p / part
        if p.is_symlink():
            raise DraftError(f"{rel!r} pasa por un enlace")
    return target


def create(root, pack_id, name, description):
    """El borrador `pack_id` desde la plantilla. Devuelve sus ficheros."""
    folder = _draft(root, pack_id, must_exist=False)
    if folder.exists():
        raise DraftError(f"ya hay un borrador {pack_id!r}: sigue con él o usa otro id")
    if not isinstance(name, str) or not name.strip():
        raise DraftError("falta el nombre del paquete")
    if not isinstance(description, str) or not description.strip():
        raise DraftError("falta la descripción del paquete: qué hace, en una frase")
    marks = {"{id}": pack_id, "{name}": name.strip(),
             "{description}": (description or "").strip().replace('"', "'")}
    for src in sorted(TEMPLATE.rglob("*")):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        text = src.read_text(encoding="utf-8")
        for k, v in marks.items():
            text = text.replace(k, v)
        dst = folder / src.relative_to(TEMPLATE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
    return list_files(root, pack_id)


def list_files(root, pack_id):
    folder = _draft(root, pack_id)
    return [{"path": rel, "bytes": (folder / rel).stat().st_size}
            for rel in packs.pack_files(folder)]


def read(root, pack_id, rel):
    target = _inside(_draft(root, pack_id), rel)
    if not target.is_file():
        raise DraftError(f"{rel!r} no está en el borrador")
    text = target.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= MAX_READ else text[:MAX_READ] + "\n[… cortado]"


def write(root, pack_id, rel, content):
    """Escribe (o sustituye) un fichero de texto del borrador."""
    target = _inside(_draft(root, pack_id), rel)
    if not isinstance(content, str):
        raise DraftError("el contenido es texto")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE:
        raise DraftError(f"{rel!r}: más de {MAX_FILE // 1000} kB")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": rel, "bytes": len(data)}


def duplicate(root, origins, source, new_id):
    """Copia el paquete `source` que se usa (de `origins`) al borrador `new_id`, con ese id y la
    versión 0.1.0 en `pack.toml`. Devuelve dónde sale escrito `source`, para que el agente lo
    cambie (P103)."""
    folder = _draft(root, new_id, must_exist=False)
    if folder.exists():
        raise DraftError(f"ya hay un borrador {new_id!r}")
    found = packs.discover(packs._as_origins(origins)).get(source)
    if not found:
        raise DraftError(f"no hay ningún paquete instalado {source!r}")
    src = found[0][1]
    for rel in packs.pack_files(src):
        dst = folder / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / rel, dst)
    manifest = folder / "pack.toml"
    text = manifest.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^id\s*=\s*"[^"]*"', f'id = "{new_id}"', text, count=1)
    text = re.sub(r'(?m)^version\s*=\s*"[^"]*"', 'version = "0.1.0"', text, count=1)
    manifest.write_text(text, encoding="utf-8")
    pattern = re.compile(rf"\b{re.escape(source)}\b")
    places = []
    for rel in packs.pack_files(folder):
        try:
            lines = (folder / rel).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            if pattern.search(line) and not (rel == "pack.toml" and line.startswith("id")):
                places.append({"file": rel, "line": n, "text": line.strip()[:200]})
    return {"files": len(packs.pack_files(folder)), "replace": places[:200],
            "more": max(0, len(places) - 200)}


# ----------------------------------------------------------------------------- validar
def _report_path(root, pack_id):
    return Path(root) / REPORTS / f"{pack_id}.json"


def _spec_for(host, origins):
    """El trabajador para cargar y probar con `origins` (P92, P101): el del entorno de la app si
    lo hay; si no, el de este proceso (los tests y el desarrollo)."""
    env = getattr(host, "env", None)
    if env is not None:
        return env.spec(origins)
    if isinstance(host, pack_host.WorkerHost):
        return host.spec
    return pack_host.default_spec(stderr=subprocess.DEVNULL)


def _run_tests(spec, folder, extra_dirs):
    tests = folder / "tests"
    if not any(tests.glob("test*.py")):
        return {"ran": 0, "failures": 0, "ok": False, "output": "el borrador no tiene tests "
                "(tests/test_*.py): un paquete se propone con los tests de su regla"}
    from pizarra import pack_env
    env = pack_env.clean_env(cache_dir=spec.cache_dir,
                             extra_path=[p for p in (spec.worker_dir, spec.engine_dir) if p])
    env["BOARDPRINT_TEST_PACKS"] = os.pathsep.join(str(d) for d in extra_dirs)
    try:
        proc = subprocess.run([spec.python, "-m", "unittest", "discover", "-s", str(tests),
                               "-t", str(folder), "-v"], env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=TEST_TIMEOUT, cwd=str(folder),
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"ran": 0, "failures": 1, "ok": False,
                "output": f"los tests no acaban en {TEST_TIMEOUT} s"}
    out = proc.stderr or ""
    ran = re.search(r"Ran (\d+) tests?", out)
    fails = re.search(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?", out)
    n_fail = sum(int(x) for x in fails.groups() if x) if fails else 0
    tail = "\n".join(out.strip().splitlines()[-40:])
    return {"ran": int(ran.group(1)) if ran else 0, "failures": n_fail,
            "ok": proc.returncode == 0 and bool(ran) and int(ran.group(1)) > 0,
            "output": tail}


def validate(root, pack_id, origins, host=None, validated=None):
    """Valida el borrador `pack_id` (P101) y guarda el informe con su huella. Devuelve
    `{ok, digest, problems, blocks, ports, libraries, tests}`."""
    from pizarra import pack_validate
    folder = _draft(root, pack_id)
    origins = [(o, Path(d)) for o, d in packs._as_origins(origins)]
    report = {"id": pack_id, "ok": False, "digest": packs.digest(folder), "problems": [],
              "blocks": [], "libraries": [], "tests": None}
    try:
        m = packs.read_manifest(folder)
        report["libraries"] = list(m.dependencies)
    except ValueError as exc:
        report["problems"].append(str(exc))
        return _save(root, report)
    chosen = {pid: places[0][1] for pid, places in packs.discover(origins).items()}
    chosen[pack_id] = folder
    report["problems"] += pack_validate.validate(folder, find=chosen.get)
    # la carga de prueba, con el borrador por encima de todo (solo él, en una carpeta aparte)
    with tempfile.TemporaryDirectory(prefix="borrador-") as tmp:
        shutil.copytree(folder, Path(tmp) / pack_id,
                        ignore=shutil.ignore_patterns(*packs.SKIP_DIRS, "*.pyc"))
        trial_origins = [("borrador", Path(tmp))] + [(o, d) for o, d in origins]
        try:
            spec = _spec_for(host or packs.Registry().host, trial_origins)
            trial = pack_host.trial_with(spec)(trial_origins, validated)
        except Exception as exc:          # noqa: BLE001 EnvError, el trabajador que no arranca
            report["problems"].append(str(exc))
            return _save(root, report)
        got = trial.get(pack_id) or {"error": "no se carga"}
        if got.get("error"):
            report["problems"].append(got["error"])
        report["blocks"] = list(got.get("blocks") or [])
        if not report["problems"]:
            report["tests"] = _run_tests(spec, Path(tmp) / pack_id,
                                         [d for _, d in origins])
            if not report["tests"]["ok"]:
                report["problems"].append("los tests no pasan")
    report["ok"] = not report["problems"]
    return _save(root, report)


def _save(root, report):
    path = _report_path(root, report["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def last_report(root, pack_id):
    try:
        return json.loads(_report_path(root, pack_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------- proponer
def propose(root, pack_id):
    """El resumen de un borrador para el chat (P102): solo si la última validación está en
    verde y el borrador no ha cambiado desde entonces."""
    folder = _draft(root, pack_id)
    report = last_report(root, pack_id)
    if report is None:
        raise DraftError("primero valídalo con validar_paquete")
    if not report.get("ok"):
        raise DraftError("la última validación no está en verde: corrige lo que dice y vuelve "
                         "a validarlo")
    if report.get("digest") != packs.digest(folder):
        raise DraftError(i18n.t("borrador.cambiado"))
    m = packs.read_manifest(folder)
    tests = []
    for f in sorted((folder / "tests").glob("test*.py")):
        tests += re.findall(r"def (test_\w+)", f.read_text(encoding="utf-8", errors="replace"))
    return {"id": m.id, "name": m.name, "version": m.version, "description": m.description,
            "author": m.author, "blocks": report.get("blocks") or [],
            "libraries": list(m.dependencies), "requires": dict(m.requires),
            "tests": {"count": report["tests"]["ran"], "names": tests},
            "digest": report["digest"]}


def export(root, pack_id, out_dir, origins):
    """El `.bppack` de un borrador propuesto (solo si sigue igual que al validarlo), para el
    resumen de instalar."""
    summary = propose(root, pack_id)            # las mismas condiciones que proponer
    folder = _draft(root, pack_id)
    chosen = {pid: places[0][1] for pid, places in
              packs.discover(packs._as_origins(origins)).items()}
    path = pack_install.export(folder, out_dir, find=lambda p: folder if p == pack_id else chosen.get(p))
    return path, summary
