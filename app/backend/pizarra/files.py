"""Archivos y carpetas de la pizarra (plan D109, D110, D131-D138): lógica pura, sin interfaz.

Una tarjeta de archivo o de carpeta guarda su ruta (`stored_path`): relativa al workspace si
está dentro, absoluta si no, para que un workspace movido o abierto en otra máquina no pierda
las rutas (D138). El tipo de lo que sale de ella va por la extensión (`port_type`): una
entrada `archivo` acepta cualquier `archivo.*` (D132, lo decide `graph.accepts`).

El hash es el del contenido (D110): en un archivo, el de sus bytes; en una carpeta, el de lo
marcado, con su ruta relativa (cambiar, añadir, quitar o renombrar uno marcado lo cambia; uno
desmarcado o fuera del patrón, no). Sin marcar nada entra todo, subcarpetas incluidas (D136).

`Prober` es el sondeo (D134): guarda la fecha y el tamaño de cada archivo leído y solo vuelve a
leer el que ha cambiado. Antes de ejecutar se le pide `fresh=True` y lee todo.

`copy_outputs` deja las salidas de un bloque en una carpeta del usuario (D109): por defecto, el
primer `_n` libre; solo pisa los archivos que se le dicen. Una copia que falla vuelve con su
error y nunca toca el origen.
"""
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

FILE = "archivo"
FOLDER = "carpeta"
BIG_FOLDER = 500 * 1024 ** 2       # por encima, la carpeta pide confirmar antes del hash (D136)

# Extensiones que son la misma cosa: `.stp` es un STEP (D132). El tipo usa siempre la de la
# derecha, así una entrada `archivo.step` acepta las dos.
EXT_ALIASES = {"stp": "step", "jpeg": "jpg", "tif": "tiff", "htm": "html", "yml": "yaml"}
_EXT_RE = re.compile(r"^[a-z0-9]+$")


def port_type(path):
    """Tipo de la salida de una tarjeta de archivo: `archivo.<ext>` en minúsculas, con la
    extensión normalizada (`.stp` → `archivo.step`); sin extensión, `archivo`."""
    ext = Path(str(path)).suffix[1:].lower()
    if not _EXT_RE.match(ext):
        return FILE
    return f"{FILE}.{EXT_ALIASES.get(ext, ext)}"


def is_file_port(type_):
    """¿Es un tipo de archivo (`archivo` o `archivo.<ext>`)? Un alias (`archivo.stp`) no lo es:
    nada sale con ese tipo, así que una entrada así nunca se conectaría."""
    if type_ == FILE:
        return True
    head, _, ext = str(type_).partition(".")
    return head == FILE and bool(_EXT_RE.match(ext)) and ext not in EXT_ALIASES


# --- rutas (D138) -------------------------------------------------------------------------

def stored_path(path, workspace_root):
    """La ruta que guarda la tarjeta: relativa al workspace (con `/`) si está dentro, absoluta
    si no."""
    p = Path(path).resolve()
    try:
        return p.relative_to(Path(workspace_root).resolve()).as_posix()
    except ValueError:
        return str(p)


def resolve(stored, workspace_root):
    """Ruta absoluta de lo que guarda una tarjeta."""
    p = Path(stored)
    return p if p.is_absolute() else Path(workspace_root) / p


# --- hash ---------------------------------------------------------------------------------

def file_digest(path, chunk=1 << 20):
    """sha256 de los bytes de un archivo, leído a trozos (un STEP de robot pasa de 100 MB)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class Content:
    """Qué entra de una carpeta (D110, D136). `exclude`: rutas relativas (con `/`) de archivos
    o subcarpetas desmarcados; una subcarpeta desmarcada quita todo lo suyo. `patterns`:
    si hay alguno, solo entra lo que cumple uno (`*.pdf`), por el nombre y sin distinguir
    mayúsculas. Sin nada, entra todo."""
    exclude: tuple = ()
    patterns: tuple = ()

    @classmethod
    def from_card(cls, data):
        data = data or {}
        return cls(tuple(str(x).strip("/") for x in data.get("exclude") or ()),
                   tuple(str(x) for x in data.get("patterns") or () if str(x).strip()))

    @property
    def everything(self):
        """¿Entra todo? Si no, la tarjeta lleva el chip con lo que entra (D139)."""
        return not self.exclude and not self.patterns

    def marks(self, rel):
        """¿Entra el archivo de ruta relativa `rel` (con `/`)?"""
        for x in self.exclude:
            if rel == x or rel.startswith(x + "/"):
                return False
        if self.patterns:
            name = rel.rsplit("/", 1)[-1].lower()
            return any(fnmatch.fnmatchcase(name, p.lower()) for p in self.patterns)
        return True


def marked(folder, content=Content()):
    """`[(ruta relativa, stat)]` de los archivos marcados de una carpeta, subcarpetas
    incluidas, en orden. Un archivo que desaparece mientras se recorre no cuenta."""
    return _walk(folder, content)[0]


def _walk(folder, content):
    """`(marcados, total)`: lo de `marked` y cuántos archivos hay en la carpeta, marcados o no
    (el «9 de 14» del chip de la tarjeta, D139)."""
    folder = Path(folder)
    out, total = [], 0
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        base = Path(root).relative_to(folder).as_posix()
        for n in sorted(names):
            total += 1
            rel = n if base == "." else f"{base}/{n}"
            if not content.marks(rel):
                continue
            try:
                out.append((rel, os.stat(Path(root) / n)))
            except OSError:
                continue
    return out, total


def folder_digest(entries):
    """Hash de una carpeta a partir de `[(ruta relativa, hash del archivo)]`: cuenta el nombre
    y el contenido de cada uno, no el orden en que se leyeron."""
    return hashlib.sha256(json.dumps(sorted(entries), ensure_ascii=False).encode()).hexdigest()


# --- sondeo (D134) ------------------------------------------------------------------------

@dataclass(frozen=True)
class FileState:
    """Lo que se sabe de una tarjeta. `hash` None: no se puede usar, y `reason` dice por qué
    (lo de detrás queda incompleto con ese motivo, nunca con el hash viejo, D138). `files`, en
    una carpeta: las rutas relativas de lo marcado. `big`: pasa de `BIG_FOLDER` y espera a que
    el usuario confirme. `total`, en una carpeta: cuántos archivos tiene, marcados o no."""
    hash: str | None
    reason: str | None = None
    size: int = 0
    mtime_ns: int = 0
    files: tuple = ()
    big: bool = False
    total: int = 0


def _mb(n):
    return f"{n / 1024 ** 2:.0f} MB"


def _t(key, **vars):
    """`i18n.t`, importado al usarlo: el trabajador de paquetes lleva este módulo sin
    `i18n.py` (tauri.conf.json), y lo que traduce aquí solo corre en el backend."""
    from pizarra import i18n
    return i18n.t(key, **vars)


# «no encontrado» y «no encontrada» son a la vez el motivo y la marca con la que la interfaz
# reconoce una tarjeta perdida (`FileCard.tsx`): se guardan tal cual y se traducen al enseñarlos
LOST_REASONS = {"no encontrado": "tarjeta.no_encontrado", "no encontrada": "tarjeta.no_encontrada"}


def reason_text(reason):
    """El motivo de un `FileState` para un mensaje al usuario, en el idioma de la app."""
    return _t(LOST_REASONS[reason]) if reason in LOST_REASONS else reason


class Prober:
    """Sondeo de las tarjetas: la caché guarda, por archivo, fecha, tamaño y hash, y un archivo
    con la misma fecha y tamaño nunca se vuelve a leer (salvo con `fresh`)."""

    def __init__(self, digest=file_digest):
        self._digest = digest
        self._cache = {}          # ruta absoluta -> (mtime_ns, tamaño, hash)

    def _hash(self, path, st, fresh):
        key = str(path)
        sig = (st.st_mtime_ns, st.st_size)
        hit = self._cache.get(key)
        if hit is not None and hit[:2] == sig and not fresh:
            return hit[2]
        h = self._digest(path)
        self._cache[key] = (*sig, h)
        return h

    def probe_file(self, path, fresh=False):
        path = Path(path)
        try:
            st = os.stat(path)
        except OSError:
            return FileState(None, "no encontrado")
        if not path.is_file():
            return FileState(None, _t("tarjeta.no_es_un_archivo"))
        try:
            h = self._hash(path, st, fresh)
        except OSError as e:
            return FileState(None, _t("tarjeta.ilegible", motivo=e.strerror or e))
        return FileState(h, size=st.st_size, mtime_ns=st.st_mtime_ns)

    def probe_folder(self, path, content=Content(), fresh=False, allow_big=False):
        path = Path(path)
        if not path.exists():
            return FileState(None, "no encontrada")
        if not path.is_dir():
            return FileState(None, _t("tarjeta.no_es_una_carpeta"))
        entries, total = _walk(path, content)
        size = sum(st.st_size for _, st in entries)
        rels = tuple(rel for rel, _ in entries)
        newest = max((st.st_mtime_ns for _, st in entries), default=0)
        if size > BIG_FOLDER and not allow_big:
            return FileState(None, _t("tarjeta.carpeta_grande", tam=_mb(size)),
                             size=size, mtime_ns=newest, files=rels, big=True, total=total)
        hashes = []
        for rel, st in entries:
            try:
                hashes.append((rel, self._hash(path / rel, st, fresh)))
            except OSError:
                continue          # desaparece o no se deja leer: no entra (y el hash cambia)
        return FileState(folder_digest(hashes), size=size, mtime_ns=newest,
                         files=tuple(rel for rel, _ in hashes), total=total)

    def forget(self, keep):
        """Quita de la caché lo que no está debajo de ninguna de las rutas `keep` (las de las
        tarjetas que siguen en la pizarra)."""
        keep = [str(Path(k)) for k in keep]
        self._cache = {p: v for p, v in self._cache.items()
                       if any(p == k or p.startswith(k.rstrip("\\/") + os.sep) for k in keep)}


# --- lo que recibe un bloque (D145) -------------------------------------------------------

def card_payload(kind, path, state):
    """La carga de la salida de una tarjeta, como la de un bloque (campos con `value`), con las
    rutas absolutas para leerlas. Un archivo: `archivo` (nombre, `path`, `size`, `hash`). Una
    carpeta: `carpeta` (nombre, `path`) y `archivos` (rutas relativas de lo marcado, y sus
    absolutas en `paths`). Solo se llama con `state.hash` puesto (si no, el bloque está
    incompleto y no se ejecuta)."""
    path = Path(path)
    if kind == "file":
        return {"archivo": {"value": path.name, "unit": "", "label": "Archivo",
                            "path": str(path), "size": state.size, "hash": state.hash}}
    return {"carpeta": {"value": path.name, "unit": "", "label": "Carpeta", "path": str(path),
                        "hash": state.hash},
            "archivos": {"value": list(state.files), "unit": "", "label": "Archivos",
                         "paths": [str(path / rel) for rel in state.files]}}


# --- vista de una carpeta (D139) ----------------------------------------------------------

TREE_LIMIT = 5000      # entradas que se enseñan como mucho; una carpeta con más lo dice


def tree(folder, content=Content(), limit=TREE_LIMIT):
    """Lo que hay en una carpeta, para su vista: `(entradas, cortada)`. Cada entrada es
    `{path, kind: file|dir, size, mtime, marked}` en orden de recorrido (una subcarpeta antes que lo
    suyo). `marked` de una subcarpeta: `all`, `none` o `some` (la casilla de tres estados)."""
    folder = Path(folder)
    out, cut = [], False
    dirs_at = {}                        # ruta relativa de subcarpeta -> índice en `out`
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        base = Path(root).relative_to(folder).as_posix()
        for d in dirs:
            rel = d if base == "." else f"{base}/{d}"
            dirs_at[rel] = len(out)
            out.append({"path": rel, "kind": "dir", "size": 0, "mtime": 0, "marked": None,
                        "_n": [0, 0]})
        for n in sorted(names):
            rel = n if base == "." else f"{base}/{n}"
            try:
                st = os.stat(Path(root) / n)
            except OSError:
                continue
            size, m = st.st_size, content.marks(rel)
            out.append({"path": rel, "kind": "file", "size": size, "mtime": st.st_mtime, "marked": m})
            parent = base
            while parent != ".":         # cuenta en cada subcarpeta de encima
                i = dirs_at.get(parent)
                if i is not None:
                    out[i]["size"] += size
                    out[i]["mtime"] = max(out[i]["mtime"], st.st_mtime)
                    out[i]["_n"][0 if m else 1] += 1
                parent = parent.rsplit("/", 1)[0] if "/" in parent else "."
        if len(out) >= limit:
            cut = True
            break
    for e in out:
        if e["kind"] == "dir":
            yes, no = e.pop("_n")
            excluded = any(e["path"] == x or e["path"].startswith(x + "/") for x in content.exclude)
            e["marked"] = ("none" if excluded or (no and not yes)
                           else "some" if yes and no else "all")
    return out[:limit], cut


# --- salidas a una carpeta (D109) ---------------------------------------------------------

def first_free(folder, name):
    """`name` si no está en `folder`; si no, el primer `<nombre>_<n><ext>` libre (n desde 1)."""
    folder = Path(folder)
    if not (folder / name).exists():
        return folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while (folder / f"{stem}_{n}{suffix}").exists():
        n += 1
    return folder / f"{stem}_{n}{suffix}"


@dataclass
class Copied:
    source: Path
    dest: Path | None = None
    error: str | None = None


def copy_outputs(sources, folder, overwrite=()):
    """Copia cada archivo de `sources` a `folder`. Los de nombre en `overwrite` pisan el que
    haya; el resto va al primer `_n` libre (D109). Nunca crea la carpeta ni toca los de
    `sources`; un fallo vuelve en `error` y no para las demás copias."""
    folder = Path(folder)
    overwrite = set(overwrite)
    out = []
    for src in map(Path, sources):
        r = Copied(src)
        if not folder.is_dir():
            r.error = _t("tarjeta.carpeta_no_existe")
        else:
            try:
                r.dest = folder / src.name if src.name in overwrite else first_free(folder, src.name)
                shutil.copy2(src, r.dest)
            except OSError as e:
                r.dest, r.error = None, _t("ejecucion.copia_fallo", motivo=e.strerror or e)
        out.append(r)
    return out
