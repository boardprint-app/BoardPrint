"""Instalar, exportar y desinstalar paquetes (docs/PLAN_PAQUETES.md §7, P75, P79, P83, P84).

**El `.bppack`** es un zip con una sola carpeta `<id>/` y los ficheros de `packs.pack_files`
(sin `ui-src/`, `__pycache__` ni `.pyc`), con fecha fija: exportar dos veces lo mismo da los
mismos bytes, y exportar e instalar, la misma huella. Se llama `<id>-<versión>.bppack`.

**Instalar** va en dos tiempos, como lo ve el usuario:

1. `inspect(archivos, destino, orígenes)` abre cada archivo en `<destino>/.instalando/<id>/`
   (el mismo disco: luego basta un renombrado), lo comprueba y prueba la carga con lo ya
   instalado en un proceso aparte (`trial_load`: el backend no importa código que el usuario
   aún no ha aceptado). Devuelve un `Plan` con el resumen de cada paquete y sus problemas.
2. `install(plan)` mueve las carpetas a su sitio, todo o nada. Si alguno tiene un problema, no
   se mueve ninguno.

Lo que no se instala, aunque esté bien hecho:
- un paquete que pide librerías de Python que no cuadran con las de los demás, o que no se
  pueden descargar (P20, P92): `resolve` crea el entorno con el paquete nuevo antes de mover
  nada y, si no puede, lo dice. Sin `resolve` (un Python que no instala librerías, los tests
  en proceso), uno que pide librerías no se instala (P75);
- uno cuya dependencia no está instalada ni viene en otro archivo elegido a la vez.

Instalar uno que ya está en ese origen sustituye su carpeta (P79). Los tests del paquete no
corren al instalar hasta FF 10.4, en el trabajador (P83).

**Desinstalar** (P84) quita la carpeta de su origen (usuario o workspace). Se niega si otro
paquete cargado lo pide.

La carpeta de trabajo `.instalando/` no tiene `pack.toml`: la carga (`packs.discover`) no la
ve. Lo que quede de una instalación cortada se borra al arrancar (`clean`).
"""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
import multiprocessing
import os
import secrets
import shutil
import stat
import zipfile
from pathlib import Path

from pizarra import i18n, packs
from pizarra.pack_versions import parse_version, satisfies

SUFFIX = ".bppack"
WORK = ".instalando"              # dentro de cada origen (§3)
TARGETS = ("usuario", "workspace")
MAX_ENTRIES = 20000
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # la fecha de todos los ficheros: el archivo no depende del día
TRIAL_TIMEOUT = 180               # s: la prueba de carga de un paquete que se cuelga


def archive_name(manifest):
    return f"{manifest.id}-{manifest.version}{SUFFIX}"


# ------------------------------------------------------------------------- exportar
def export(folder, dest_dir, find=None):
    """Escribe `<dest_dir>/<id>-<versión>.bppack` con el paquete de `folder` y devuelve su
    ruta. Solo exporta un paquete que pasa la validación (§1) y con su interfaz compilada:
    otro no lo podría instalar nadie. `find(id)`: dónde está otro paquete (por defecto, junto a
    este). `ValueError` con lo que falla."""
    from pizarra import pack_validate
    folder = Path(folder)
    m = packs.read_manifest(folder)
    if m.ui and not (folder / m.ui).is_file():
        raise ValueError(i18n.t("paquete.ui_sin_compilar", id=m.id, ui=m.ui))
    problems = pack_validate.validate(folder, find)
    if problems:
        raise ValueError(i18n.t("paquete.no_valida", id=m.id,
                                problemas="; ".join(problems[:packs.MAX_SHOWN])))
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / archive_name(m)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in packs.pack_files(folder):
                zi = zipfile.ZipInfo(f"{m.id}/{rel}", date_time=ZIP_DATE)
                zi.external_attr = 0o644 << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, (folder / rel).read_bytes())
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


# -------------------------------------------------------------------- abrir un archivo
def _skipped(rel):
    """Lo que no es del paquete (`packs.SKIP_DIRS`, `.pyc`) no se saca del archivo: un `.pyc`
    con la fecha de su `.py` se ejecutaría en lugar del código que se ve."""
    return any(p in packs.SKIP_DIRS for p in rel[:-1]) or rel[-1].endswith((".pyc", ".pyo"))


def open_archive(archive, into):
    """Saca el paquete de `archive` en `<into>/<id>/` y devuelve esa carpeta. `ValueError`, sin
    escribir nada, si el archivo no es un zip, lleva una ruta que sale de su carpeta (absoluta,
    con `..`, `\\` o `:`), un enlace, más de una carpeta, una ruta repetida (también sin mirar
    mayúsculas: Windows las juntaría) o más de `pack_validate.MAX_BYTES`."""
    from pizarra import pack_validate
    archive = Path(archive)
    try:
        z = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(i18n.t("paquete.no_es_bppack", archivo=archive.name, motivo=exc)) from None
    with z:
        entries = z.infolist()
        if len(entries) > MAX_ENTRIES:
            raise ValueError(i18n.t("paquete.demasiados_ficheros", archivo=archive.name, max=MAX_ENTRIES))
        tops, seen, size, todo = set(), set(), 0, []
        for zi in entries:
            name = zi.filename
            parts = name.rstrip("/").split("/") if zi.is_dir() else name.split("/")
            if (not name or name.startswith("/") or "\\" in name or ":" in name
                    or any(p in ("", ".", "..") for p in parts)):
                raise ValueError(i18n.t("paquete.ruta_fuera", archivo=archive.name, ruta=repr(name)))
            if stat.S_ISLNK(zi.external_attr >> 16):
                raise ValueError(i18n.t("paquete.enlace", archivo=archive.name, ruta=repr(name)))
            tops.add(parts[0])
            if zi.is_dir():
                continue
            if len(parts) == 1:
                raise ValueError(i18n.t("paquete.fuera_de_carpeta", archivo=archive.name, ruta=repr(name)))
            rel = parts[1:]
            if _skipped(rel):
                continue
            low = name.lower()
            if low in seen:
                raise ValueError(i18n.t("paquete.repetido", archivo=archive.name, ruta=repr(name)))
            seen.add(low)
            size += zi.file_size
            if size > pack_validate.MAX_BYTES:
                raise ValueError(i18n.t("paquete.demasiado_grande", archivo=archive.name,
                                        mb=pack_validate.MAX_BYTES // 2**20))
            todo.append((zi, rel))
        if len(tops) != 1:
            raise ValueError(i18n.t("paquete.una_carpeta", archivo=archive.name,
                                    carpetas=", ".join(sorted(tops)) or i18n.t("paquete.ninguna")))
        top = tops.pop()
        if not packs.ID_RE.match(top):
            raise ValueError(i18n.t("paquete.id_no_valido", archivo=archive.name, id=repr(top)))
        dest = Path(into) / top
        dest.mkdir(parents=True)
        for zi, rel in todo:
            target = dest.joinpath(*rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            # ZipExtFile no da más bytes de los que dice el índice, y comprueba el CRC
            with z.open(zi) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return dest


# ---------------------------------------------------------------------------- resumen
@dataclass
class Item:
    """Un paquete del resumen de instalar (§7)."""
    archive: str
    id: str = ""
    name: str = ""
    version: str = ""
    author: str = ""
    description: str = ""
    requires: list = field(default_factory=list)    # [{id, spec, state, version}]
    libraries: list = field(default_factory=list)   # [python] dependencies
    blocks: list = field(default_factory=list)      # títulos de sus bloques
    replaces: str | None = None    # versión que sustituye en el destino (P79)
    older: bool = False            # la del archivo es anterior a la instalada
    shadowed_by: str | None = None  # origen de más prioridad que ya lo tiene: ese se usa (§3)
    problems: list = field(default_factory=list)

    def view(self):
        return dict(self.__dict__)


@dataclass
class Plan:
    token: str
    target: str
    target_dir: Path
    work: Path
    items: list
    breaks: dict = field(default_factory=dict)   # {id: error}: dejarían de cargar

    @property
    def ok(self):
        return bool(self.items) and not any(i.problems for i in self.items)

    def view(self):
        return {"token": self.token, "target": self.target, "target_dir": str(self.target_dir),
                "ok": self.ok, "items": [i.view() for i in self.items],
                "breaks": dict(self.breaks)}

    def discard(self):
        shutil.rmtree(self.work, ignore_errors=True)


def _trial(origins, validated):
    """En un proceso aparte: carga `origins` y devuelve `{id: {error, version, blocks}}`."""
    reg = packs.load(origins, log=lambda _m: None, validated=validated)
    return {p.id: {"error": p.error, "version": p.version,
                   "blocks": [b.title for k, b in sorted(reg.items())
                              if packs.pack_id_of(k) == p.id]}
            for p in reg.packs}


def trial_load(origins, validated=None):
    """La carga de prueba (P83), en un proceso nuevo como el de cálculo (D92): importar el
    paquete y llamar a su `register` no toca los módulos del backend. Congelado vale igual:
    `run_backend.py` llama a `freeze_support`."""
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        return ex.submit(_trial, [(o, str(d)) for o, d in origins],
                         validated).result(timeout=TRIAL_TIMEOUT)


def _version_of(folder):
    try:
        return packs.read_manifest(folder).version
    except ValueError:
        return None


def _later(a, b):
    """`a` es posterior a `b` (dos semver); si no se pueden comparar, no."""
    try:
        return parse_version(a) > parse_version(b)
    except ValueError:
        return False


def inspect(archives, target, origins, loaded=None, trial=trial_load, validated=None,
            resolve=None):
    """El `Plan` de instalar `archives` en el origen `target` ("usuario" o "workspace").
    `origins`: `[(origen, carpeta)]` de la app, de más a menos prioridad; `loaded`: los
    `PackInfo` de lo cargado ahora (para avisar de lo que dejaría de cargar). Nunca deja nada
    fuera de `<destino>/.instalando/`; `Plan.discard()` lo borra."""
    origins = [(o, Path(d)) for o, d in origins]
    dirs = dict(origins)
    if target not in TARGETS or target not in dirs:
        raise ValueError(i18n.t("paquete.destino_no_valido", destino=repr(target),
                                destinos=", ".join(o for o in TARGETS if o in dirs)))
    target_dir = dirs[target]
    token = secrets.token_hex(8)
    work = target_dir / WORK / token
    staging = work / "nuevos"
    staging.mkdir(parents=True)
    items, manifests, staged = [], {}, {}       # staged: {id: el Item que lo trae}
    for i, archive in enumerate(archives):
        item = Item(archive=str(archive))
        items.append(item)
        box = work / f"a{i}"
        try:
            folder = open_archive(archive, box)
            m = packs.read_manifest(folder)
        except (ValueError, OSError) as exc:
            item.problems.append(str(exc))
            shutil.rmtree(box, ignore_errors=True)
            continue
        item.id, item.name, item.version = m.id, m.name, m.version
        item.author, item.description, item.libraries = m.author, m.description, list(m.dependencies)
        if m.id in manifests:
            item.problems.append(i18n.t("paquete.en_otro_archivo", id=m.id))
            shutil.rmtree(box, ignore_errors=True)
            continue
        os.replace(folder, staging / m.id)
        shutil.rmtree(box, ignore_errors=True)
        manifests[m.id], staged[m.id] = m, item
        if m.dependencies and resolve is None:
            item.problems.append(i18n.t("paquete.sin_librerias",
                                        librerias=", ".join(m.dependencies)))
        old = target_dir / m.id
        if (old / "pack.toml").is_file():
            item.replaces = _version_of(old) or "?"
            item.older = item.replaces != "?" and _later(item.replaces, m.version)
        above = [o for o, d in origins[:[o for o, _ in origins].index(target)]
                 if (d / m.id / "pack.toml").is_file()]
        item.shadowed_by = above[0] if above else None

    loaded = {p.id: p for p in (loaded or [])}
    for pid, item in staged.items():
        m = manifests[pid]
        for dep, spec in sorted(m.requires.items()):
            if dep in manifests:
                state, version = "en otro archivo", manifests[dep].version
            elif dep in loaded and loaded[dep].error is None:
                state, version = "instalado", loaded[dep].version
            else:
                state, version = "falta", None
            item.requires.append({"id": dep, "spec": spec, "state": state, "version": version})
            if state == "falta":
                item.problems.append(i18n.t("paquete.falta_dependencia", dep=dep, spec=spec))
            elif not satisfies(version, spec):
                key = ("paquete.dependencia_instalada" if state == "instalado"
                       else "paquete.dependencia_otro_archivo")
                item.problems.append(i18n.t(key, dep=dep, spec=spec, version=version))

    if manifests:
        at = [o for o, _ in origins].index(target)
        trial_origins = origins[:at] + [("nuevo", staging)] + origins[at:]
        if resolve is not None:
            # el entorno con las librerías de todos, el paquete nuevo incluido (P92): si no
            # cuadran o no se descargan, no se instala nada
            try:
                trial = resolve(trial_origins)
            except Exception as exc:          # noqa: BLE001 EnvError, con qué pide cada uno
                for pid, item in staged.items():
                    if manifests[pid].dependencies or not any(
                            manifests[q].dependencies for q in staged):
                        item.problems.append(str(exc))
                trial = None
        try:
            if trial is None:
                raise RuntimeError("sin entorno")
            result = trial(trial_origins, validated)
        except Exception as exc:              # noqa: BLE001 un proceso que muere o se cuelga
            result = {pid: {"error": i18n.t("paquete.prueba_fallo", tipo=type(exc).__name__, motivo=exc),
                            "blocks": []} for pid in manifests}
        for pid, item in staged.items():
            got = result.get(pid)
            if got is None:
                continue
            item.blocks = list(got.get("blocks") or [])
            if got.get("error") and not item.problems:
                item.problems.append(got["error"])
        plan_breaks = {pid: r["error"] for pid, r in result.items()
                       if pid not in manifests and r.get("error")
                       and pid in loaded and loaded[pid].error is None}
    else:
        plan_breaks = {}
    return Plan(token=token, target=target, target_dir=target_dir, work=work, items=items,
                breaks=plan_breaks)


# --------------------------------------------------------------------------- instalar
def install(plan):
    """Mueve los paquetes del plan a su sitio, todo o nada: si un renombrado falla, deshace los
    que ya hizo. El que ya estaba se aparta y se borra al final (P79). Devuelve los ids."""
    if not plan.ok:
        raise ValueError(i18n.t("paquete.no_instalable", problemas="; ".join(
            f"{i.id or Path(i.archive).name}: {p}" for i in plan.items for p in i.problems)))
    staging, before = plan.work / "nuevos", plan.work / "antes"
    before.mkdir(parents=True, exist_ok=True)
    done = []                                  # [(desde, hasta)] ya hechos, para deshacerlos
    try:
        for item in plan.items:
            dest = plan.target_dir / item.id
            if dest.exists():
                os.replace(dest, before / item.id)
                done.append((dest, before / item.id))
            os.replace(staging / item.id, dest)
            done.append((staging / item.id, dest))
    except OSError as exc:
        undone = True
        for src, dst in reversed(done):
            try:
                os.replace(dst, src)
            except OSError:
                undone = False
        if not undone:            # no se borra nada: lo de antes sigue en `antes/`
            raise ValueError(i18n.t("paquete.instalar_sin_deshacer", motivo=exc,
                                    carpeta=before)) from None
        plan.discard()
        raise ValueError(i18n.t("paquete.instalar_fallo", motivo=exc)) from None
    plan.discard()
    return [i.id for i in plan.items]


# ------------------------------------------------------------------------ desinstalar
def dependents(pack_id, loaded):
    """Los paquetes cargados que piden `pack_id` en su `[requires]`."""
    return sorted(p.id for p in loaded if p.error is None and p.id != pack_id
                  and pack_id in p.requires)


def uninstall(pack_id, origin, origins, loaded):
    """Quita `pack_id` del origen `origin` ("usuario" o "workspace", P84). `ValueError` si es
    de desarrollo, si no está ahí o si otro paquete cargado lo pide y esta copia es la que se
    usa."""
    dirs = {o: Path(d) for o, d in origins}
    if origin not in TARGETS:
        raise ValueError(i18n.t("paquete.no_desinstalable", id=pack_id, origen=origin,
                                carpeta=dirs.get(origin, "")))
    if origin not in dirs:
        raise ValueError(i18n.t("paquete.sin_origen", origen=repr(origin)))
    folder = dirs[origin] / pack_id
    if not packs.ID_RE.match(pack_id or "") or not (folder / "pack.toml").is_file():
        raise ValueError(i18n.t("paquete.no_instalado", id=pack_id, origen=origin))
    used = next((p for p in loaded if p.id == pack_id), None)
    if used is not None and Path(used.path) == folder:
        need = dependents(pack_id, loaded)
        if need:
            raise ValueError(i18n.t("paquete.lo_piden" if len(need) > 1 else "paquete.lo_pide",
                                    id=pack_id, otros=", ".join(need)))
    trash = dirs[origin] / WORK / f"quitar-{secrets.token_hex(6)}"
    trash.mkdir(parents=True)
    try:
        os.replace(folder, trash / pack_id)
    except OSError as exc:
        shutil.rmtree(trash, ignore_errors=True)
        raise ValueError(i18n.t("paquete.desinstalar_fallo", id=pack_id, motivo=exc)) from None
    shutil.rmtree(trash, ignore_errors=True)


def clean(origins):
    """Borra lo que quede en `.instalando/` de cada origen instalable (una instalación cortada,
    archivos subidos de otra sesión)."""
    for o, d in origins:
        if o in TARGETS:
            shutil.rmtree(Path(d) / WORK, ignore_errors=True)
