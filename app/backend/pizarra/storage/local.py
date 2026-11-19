"""Workspace en una carpeta del disco (docs/PLAN_PIZARRA.md §2, D64-D66).

    <workspace>/workspace.toml            id, nombre y unidades en pantalla (D182)
    <workspace>/.boardprint/index.json    índice id de proyecto → ruta (lo rehace si falla)
    <workspace>/<carpeta>/…/<proyecto>/project.toml

Una carpeta con `project.toml` es un proyecto y no se mira dentro; cualquier otra es una
carpeta del workspace, salvo las ocultas y, en la raíz, `profile/` y `packs/`. El usuario
puede renombrar, mover o copiar carpetas desde el Explorador: el id de `project.toml` sigue
al proyecto, y una copia (dos con el mismo id) recibe uno nuevo.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import time
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import tomli_w

from pizarra import i18n
from pizarra.config import APP_ID, LEGACY_INDEX_DIRS
from pizarra.pasted import ANIMATION_EXT, IMAGE_EXT
from pizarra.storage.base import (AGENT_FILES, Conflict, InvalidName, Node, NotFound, ProjectInfo,
                                  StorageError, Workspace, WorkspaceInfo)
from pizarra.storage.names import ROOT_RESERVED, check_name, split_rel

SCHEMA = 1
PROJECT_FILE = "project.toml"
WORKSPACE_FILE = "workspace.toml"
INDEX_DIR = f".{APP_ID}"
# Ids de bloque: los de Excalidraw (nanoid) y los de los tests. Nunca un separador ni un punto.
BLOCK_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# Archivos de la pizarra (imágenes pegadas, animaciones de los post-its): su sha256 y la
# extensión de su tipo. Solo esas extensiones: nada más se guarda ni se sirve de ahí.
BOARD_FILE_RE = re.compile(r"[0-9a-f]{64}\.([a-z]{3,4})")
BOARD_FILE_EXT = IMAGE_EXT | {ANIMATION_EXT}


def _new_id():
    return uuid.uuid4().hex


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _birth(path):
    """Cuándo se creó la carpeta: una copia hecha en el Explorador es más nueva."""
    st = path.stat()
    return getattr(st, "st_birthtime", st.st_ctime)


def atomic_write(path, data: bytes):
    """Escribe en un temporal y lo pone en su sitio. En Windows, OneDrive, el indexador o el
    antivirus pueden tener el fichero abierto un instante: se reintenta antes de fallar (R6)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    for intento in range(20):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if intento == 19:
                raise
            time.sleep(0.1)


def _rename(src, dst):
    """`rename` con los mismos reintentos que `atomic_write`: en Windows una carpeta con un
    archivo abierto un instante (indexador, antivirus) no se deja mover."""
    for intento in range(20):
        try:
            src.rename(dst)
            return
        except PermissionError:
            if intento == 19:
                raise
            time.sleep(0.1)


def _write_toml(path, data):
    atomic_write(path, tomli_w.dumps(data).encode("utf-8"))


def _hide(path):
    """En Windows, una carpeta que empieza por punto no queda oculta: se le pone el atributo."""
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)   # FILE_ATTRIBUTE_HIDDEN
        except (AttributeError, OSError):
            pass


def _send2trash(path):
    from send2trash import send2trash      # solo hace falta al borrar de verdad
    send2trash(path)


class LocalWorkspace(Workspace):
    def __init__(self, root, info, trash=None):
        self.root = Path(root).resolve()
        self._info = info
        self._trash_fn = trash or _send2trash
        self._adopt_legacy_index()
        self._index = self._load_index()

    @classmethod
    def open(cls, root, name=None, trash=None):
        """Abre la carpeta como workspace, creándola (y su `workspace.toml`) si hace falta."""
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        wf = root / WORKSPACE_FILE
        if wf.exists():
            try:
                data = tomllib.loads(wf.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
                raise StorageError(i18n.t("workspace.ilegible", fichero=wf, motivo=exc)) from exc
            if not data.get("id"):
                data["id"] = _new_id()
                _write_toml(wf, data)
        else:
            data = {"schema": SCHEMA, "id": _new_id(), "name": name or root.name}
            _write_toml(wf, data)
        return cls(root, WorkspaceInfo(str(data["id"]), str(data.get("name") or root.name)),
                   trash)

    # ------------------------------------------------------------------ índice
    def _adopt_legacy_index(self):
        """Un workspace de antes de D158 tiene el índice en `.cad-llm/`: se renombra. Si no se
        deja (Windows con algo abierto dentro), da igual: el índice se rehace."""
        new = self.root / INDEX_DIR
        for name in LEGACY_INDEX_DIRS:
            old = self.root / name
            if old.is_dir() and not new.exists():
                try:
                    _rename(old, new)
                except OSError:
                    pass

    def _index_path(self):
        return self.root / INDEX_DIR / "index.json"

    def _load_index(self):
        try:
            data = json.loads(self._index_path().read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_index(self):
        d = self.root / INDEX_DIR
        new = not d.exists()
        atomic_write(self._index_path(),
                     json.dumps(self._index, ensure_ascii=False, indent=1).encode("utf-8"))
        if new:
            _hide(d)

    def _reindex_prefix(self, old, new):
        for pid, rel in list(self._index.items()):
            if rel == old or rel.startswith(old + "/"):
                self._index[pid] = new + rel[len(old):]
        self._save_index()

    # ------------------------------------------------------------------ rutas
    def _rel(self, p):
        return p.relative_to(self.root).as_posix() if p != self.root else ""

    def _folder_dir(self, path):
        """Carpeta del workspace (resuelta, con las mayúsculas reales) o `NotFound`."""
        parts = split_rel(path)
        missing = NotFound(i18n.t("carpeta.no_existe_workspace", ruta=repr(path)))
        if parts and parts[0].casefold() in ROOT_RESERVED:
            raise missing
        d = self.root
        for part in parts:
            d = d / part
            if not d.is_dir() or (d / PROJECT_FILE).exists():
                raise missing
        d = d.resolve()
        if d != self.root and self.root not in d.parents:      # un enlace que sale fuera
            raise missing
        return d

    def _check_free(self, parent, name, same=None):
        for e in parent.iterdir():
            if e.name.casefold() == name.casefold() and (same is None or e != same):
                raise Conflict(i18n.t("carpeta.nombre_ocupado", nombre=e.name))

    def _info_for(self, pid, rel):
        parts = rel.split("/")
        return ProjectInfo(id=pid, name=parts[-1], path=rel, folder="/".join(parts[:-1]))

    def _read_project_toml(self, d):
        return tomllib.loads((d / PROJECT_FILE).read_text(encoding="utf-8"))

    def _dir_of(self, project_id):
        return self.root.joinpath(*self.project(project_id).path.split("/"))

    # ------------------------------------------------------------------- árbol
    def info(self):
        return self._info

    def _scan(self):
        """Recorre el workspace, arregla ids repetidos y rehace el índice."""
        projects = []                                       # (node, dir, data)

        def walk(d, parts):
            node = Node("folder", d.name if parts else self._info.name, "/".join(parts))
            try:
                entries = list(os.scandir(d))
            except OSError:
                return node
            for e in entries:
                if e.name.startswith("."):
                    continue
                try:
                    if not e.is_dir(follow_symlinks=False) or e.is_junction():
                        continue
                except OSError:
                    continue
                if not parts and e.name.casefold() in ROOT_RESERVED:
                    continue
                p, sub = Path(e.path), parts + [e.name]
                if (p / PROJECT_FILE).is_file():
                    child = self._project_node(p, sub, projects)
                else:
                    child = walk(p, sub)
                node.children.append(child)
            node.children.sort(key=lambda c: (c.kind != "folder", c.name.casefold()))
            node.modified = max([c.modified for c in node.children], default=_mtime(d))
            return node

        tree = walk(self.root, [])
        self._dedupe(projects)
        self._index = {n.id: n.path for n, _, _ in projects if n.id}
        self._save_index()
        return tree

    def _project_node(self, d, parts, projects):
        # La miniatura cuenta: su fecha sirve a la interfaz para no enseñar una vieja en caché.
        thumb = d / "board" / "thumbnail.png"
        node = Node("project", d.name, "/".join(parts),
                    modified=max(_mtime(d / PROJECT_FILE), _mtime(d / "board" / "scene.json"),
                                 _mtime(thumb)),
                    thumbnail=thumb.is_file())
        try:
            data = self._read_project_toml(d)
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            # Nunca se sobrescribe: el usuario puede querer arreglarlo a mano.
            node.error = f"no se puede leer {PROJECT_FILE}: {exc}"
            return node
        if not isinstance(data.get("id"), str) or not data["id"]:
            data["id"] = _new_id()
            _write_toml(d / PROJECT_FILE, data)
        node.id = data["id"]
        projects.append((node, d, data))
        return node

    def _dedupe(self, projects):
        """Dos proyectos con el mismo id (una carpeta copiada a mano): se queda el id el que
        está en la ruta del índice; si ninguno, el más antiguo. Los demás reciben uno nuevo."""
        by_id = {}
        for item in projects:
            by_id.setdefault(item[0].id, []).append(item)
        for pid, items in by_id.items():
            if len(items) < 2:
                continue
            known = self._index.get(pid)
            items.sort(key=lambda it: (it[0].path != known, _birth(it[1]), it[0].path))
            for node, d, data in items[1:]:
                data["id"] = node.id = _new_id()
                _write_toml(d / PROJECT_FILE, data)

    def tree(self):
        return self._scan()

    def project(self, project_id):
        rel = self._index.get(project_id)
        for attempt in range(2):
            if rel is not None:
                d = self.root.joinpath(*rel.split("/"))
                try:
                    if self._read_project_toml(d).get("id") == project_id:
                        return self._info_for(project_id, rel)
                except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
                    pass
            if attempt == 0:                     # movido o renombrado fuera de la app
                self._scan()
                rel = self._index.get(project_id)
        raise NotFound(i18n.t("proyecto.no_existe", id=repr(project_id)))

    def projects_under(self, folder):
        rel = self._rel(self._folder_dir(folder))
        self._scan()
        return [pid for pid, p in self._index.items()
                if rel == "" or p == rel or p.startswith(rel + "/")]

    # ----------------------------------------------------------- crear y mover
    def create_folder(self, parent, name):
        d = self._folder_dir(parent)
        name = check_name(name, at_root=d == self.root)
        self._check_free(d, name)
        (d / name).mkdir()
        return self._rel(d / name)

    def create_project(self, folder, name):
        d = self._folder_dir(folder)
        name = check_name(name, at_root=d == self.root)
        self._check_free(d, name)
        p = d / name
        p.mkdir()
        pid = _new_id()
        _write_toml(p / PROJECT_FILE, {"schema": SCHEMA, "id": pid, "created": _now_iso()})
        self._index[pid] = self._rel(p)
        self._save_index()
        return self._info_for(pid, self._rel(p))

    def rename_folder(self, path, name):
        if path == "":
            raise InvalidName(i18n.t("workspace.raiz_renombrar"))
        d = self._folder_dir(path)
        name = check_name(name, at_root=d.parent == self.root)
        self._check_free(d.parent, name, same=d)
        old, new = self._rel(d), self._rel(d.parent / name)
        d.rename(d.parent / name)
        self._reindex_prefix(old, new)
        return new

    def rename_project(self, project_id, name):
        d = self._dir_of(project_id)
        name = check_name(name, at_root=d.parent == self.root)
        self._check_free(d.parent, name, same=d)
        d.rename(d.parent / name)
        self._index[project_id] = self._rel(d.parent / name)
        self._save_index()
        return self.project(project_id)

    def move_folder(self, path, dest):
        if path == "":
            raise InvalidName(i18n.t("workspace.raiz_mover"))
        src, dst = self._folder_dir(path), self._folder_dir(dest)
        if dst == src or src in dst.parents:
            raise Conflict(i18n.t("carpeta.dentro_de_si"))
        if src.parent == dst:
            return self._rel(src)
        check_name(src.name, at_root=dst == self.root)
        self._check_free(dst, src.name)
        old, new = self._rel(src), self._rel(dst / src.name)
        src.rename(dst / src.name)
        self._reindex_prefix(old, new)
        return new

    def move_project(self, project_id, dest):
        src, dst = self._dir_of(project_id), self._folder_dir(dest)
        if src.parent == dst:
            return self.project(project_id)
        check_name(src.name, at_root=dst == self.root)
        self._check_free(dst, src.name)
        src.rename(dst / src.name)
        self._index[project_id] = self._rel(dst / src.name)
        self._save_index()
        return self.project(project_id)

    # ------------------------------------------------------------ borrar (D66)
    def trash_folder(self, path):
        if path == "":
            raise InvalidName(i18n.t("workspace.raiz_borrar"))
        ids = self.projects_under(path)
        self._trash_fn(str(self._folder_dir(path)))
        for pid in ids:
            self._index.pop(pid, None)
        self._save_index()
        return ids

    def trash_project(self, project_id):
        self._trash_fn(str(self._dir_of(project_id)))
        self._index.pop(project_id, None)
        self._save_index()

    def trash_file(self, path):
        self._trash_fn(str(path))

    # ---------------------------------------------------- contenido del proyecto
    def load_scene(self, project_id):
        p = self._dir_of(project_id) / "board" / "scene.json"
        return json.loads(p.read_text(encoding="utf-8"))["elements"] if p.exists() else []

    def save_scene(self, project_id, elements):
        data = {"type": "excalidraw", "version": 2, "elements": elements}
        atomic_write(self._dir_of(project_id) / "board" / "scene.json",
                     json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))

    def _backup_path(self, project_id, name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name or ""):
            raise InvalidName(f"nombre de respaldo no válido: {name!r}")
        return self._dir_of(project_id) / "board" / f"scene.{name}.json"

    def backup_scene_once(self, project_id, name, elements):
        p = self._backup_path(project_id, name)
        if p.exists():
            return False
        data = {"type": "excalidraw", "version": 2, "elements": elements}
        atomic_write(p, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
        return True

    def load_scene_backup(self, project_id, name):
        p = self._backup_path(project_id, name)
        return json.loads(p.read_text(encoding="utf-8"))["elements"] if p.exists() else None

    def load_block_state(self, project_id):
        p = self._dir_of(project_id) / "blocks" / "state.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def save_block_state(self, project_id, state):
        atomic_write(self._dir_of(project_id) / "blocks" / "state.json",
                     json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8"))

    # ------------------------------------------- archivos de salida de los bloques (D93)
    def _block_dir(self, project_id, block_id):
        if not isinstance(block_id, str) or not BLOCK_ID_RE.fullmatch(block_id):
            raise InvalidName(f"id de bloque no válido: {block_id!r}")
        return self._dir_of(project_id) / "blocks" / block_id

    def _own_scratch(self, scratch):
        """Una carpeta de trabajo de este workspace (`blocks/.run-*`), nunca otra ruta."""
        p = Path(scratch).resolve()
        if not (p.name.startswith(".run-") and p.parent.name == "blocks"
                and p.is_relative_to(self.root)):
            raise InvalidName(f"{scratch} no es una carpeta de trabajo de un bloque")
        return p

    def block_scratch(self, project_id, block_id):
        base = self._block_dir(project_id, block_id).parent
        base.mkdir(parents=True, exist_ok=True)
        d = base / f".run-{block_id}-{_new_id()}"
        d.mkdir()
        return d

    def commit_block_files(self, project_id, block_id, scratch):
        dest = self._block_dir(project_id, block_id)
        scratch = self._own_scratch(scratch)
        old = None
        if dest.exists():
            old = dest.with_name(f".old-{block_id}-{_new_id()}")
            _rename(dest, old)
        if any(scratch.iterdir()):
            _rename(scratch, dest)
        else:                                      # sin archivos: sin carpeta
            scratch.rmdir()
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)

    def discard_block_scratch(self, scratch):
        shutil.rmtree(self._own_scratch(scratch), ignore_errors=True)

    def clear_block_files(self, project_id, block_id):
        dest = self._block_dir(project_id, block_id)
        if dest.exists():
            shutil.rmtree(dest)

    def block_file(self, project_id, block_id, name):
        base = self._block_dir(project_id, block_id).resolve()
        if not isinstance(name, str) or not name.strip() or Path(name).is_absolute() \
                or ":" in name:
            raise InvalidName(i18n.t("bloque.archivo_no_valido", nombre=repr(name)))
        p = (base / name).resolve()
        if p == base or not p.is_relative_to(base):
            raise InvalidName(i18n.t("bloque.archivo_fuera", nombre=repr(name)))
        if not p.is_file():
            raise NotFound(i18n.t("bloque.archivo_no_existe", nombre=repr(name)))
        return p

    # ------------------------------------- archivos de la pizarra (D84, D140, D175)
    def save_board_file(self, project_id, data, ext):
        if ext not in BOARD_FILE_EXT:
            raise InvalidName(f"extensión no válida para la pizarra: {ext!r}")
        name = f"{hashlib.sha256(data).hexdigest()}.{ext}"
        p = self._dir_of(project_id) / "board" / "files" / name
        if not p.is_file():
            atomic_write(p, bytes(data))
        return name

    def board_file(self, project_id, name):
        m = BOARD_FILE_RE.fullmatch(name) if isinstance(name, str) else None
        if not m or m.group(1) not in BOARD_FILE_EXT:
            raise InvalidName(f"nombre de archivo de la pizarra no válido: {name!r}")
        p = self._dir_of(project_id) / "board" / "files" / name
        if not p.is_file():
            raise NotFound(i18n.t("pizarra.archivo_no_existe", nombre=name))
        return p

    def sync_file(self, project_id, block_id):
        self._block_dir(project_id, block_id)           # valida el id
        return self._dir_of(project_id) / "sync" / f"{block_id}.json"

    # ---------------------------------------------------------------- versiones (D76)
    def _versions_dir(self, project_id):
        return self._dir_of(project_id) / "board" / "versions"

    def _version_dir(self, project_id, version_id):
        base = self._versions_dir(project_id)
        if not isinstance(version_id, str) or not version_id or version_id in (".", "..") \
                or any(c in version_id for c in "/\\:") or version_id.startswith("."):
            raise NotFound(i18n.t("version.no_existe", id=repr(version_id)))
        d = base / version_id
        if not (d / "version.toml").is_file():
            raise NotFound(i18n.t("version.no_existe", id=repr(version_id)))
        return d

    @staticmethod
    def _version_info(d):
        data = tomllib.loads((d / "version.toml").read_text(encoding="utf-8"))
        return {"id": d.name, "name": data.get("name", d.name), "created": data.get("created", ""),
                "auto": bool(data.get("auto", False))}

    def list_versions(self, project_id):
        base = self._versions_dir(project_id)
        if not base.is_dir():
            return []
        out = []
        for d in base.iterdir():
            if d.is_dir() and (d / "version.toml").is_file():
                try:
                    out.append(self._version_info(d))
                except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
                    continue
        return sorted(out, key=lambda v: (v["created"], v["id"]), reverse=True)

    def save_version(self, project_id, name, elements, block_state, thumbnail, auto=False):
        name = check_name(name)
        base = self._versions_dir(project_id)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        folder = check_name(f"{stamp}-{name}"[:120])
        d, n = base / folder, 2
        while d.exists():                              # nunca se pisa otra versión
            d, n = base / f"{folder}-{n}", n + 1
        tmp = base / f".tmp-{_new_id()}"
        tmp.mkdir(parents=True)
        (tmp / "scene.json").write_text(json.dumps(
            {"type": "excalidraw", "version": 2, "elements": elements}, ensure_ascii=False),
            encoding="utf-8")
        (tmp / "blocks.json").write_text(json.dumps(block_state, ensure_ascii=False), encoding="utf-8")
        if thumbnail:
            (tmp / "thumbnail.png").write_bytes(thumbnail)
        for bd in self._block_dirs(project_id):    # archivos de salida de los bloques (D93)
            shutil.copytree(bd, tmp / "files" / bd.name)
        _write_toml(tmp / "version.toml", {"name": name, "created": _now_iso(), "auto": bool(auto)})
        tmp.rename(d)                                  # aparece entera o no aparece
        return self._version_info(d)

    def load_version(self, project_id, version_id):
        d = self._version_dir(project_id, version_id)
        return {"elements": json.loads((d / "scene.json").read_text(encoding="utf-8"))["elements"],
                "blocks": json.loads((d / "blocks.json").read_text(encoding="utf-8")),
                "info": self._version_info(d)}

    def _block_dirs(self, project_id):
        """Las carpetas de archivos de los bloques (sin las de trabajo, que empiezan por punto)."""
        base = self._dir_of(project_id) / "blocks"
        return [d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")] \
            if base.is_dir() else []

    def restore_block_files(self, project_id, version_id):
        src = self._version_dir(project_id, version_id) / "files"
        base = self._dir_of(project_id) / "blocks"
        for d in self._block_dirs(project_id):
            shutil.rmtree(d)
        if src.is_dir():
            for d in src.iterdir():
                if d.is_dir() and BLOCK_ID_RE.fullmatch(d.name):
                    shutil.copytree(d, base / d.name)

    def load_version_thumbnail(self, project_id, version_id):
        p = self._version_dir(project_id, version_id) / "thumbnail.png"
        return p.read_bytes() if p.exists() else None

    def rename_version(self, project_id, version_id, name):
        d = self._version_dir(project_id, version_id)
        data = tomllib.loads((d / "version.toml").read_text(encoding="utf-8"))
        data["name"] = check_name(name)
        _write_toml(d / "version.toml", data)
        return self._version_info(d)

    def trash_version(self, project_id, version_id):
        self._trash_fn(str(self._version_dir(project_id, version_id)))

    def load_proposals(self, project_id):
        p = self._dir_of(project_id) / "board" / "proposals.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def save_proposals(self, project_id, proposals):
        atomic_write(self._dir_of(project_id) / "board" / "proposals.json",
                     json.dumps(proposals, ensure_ascii=False, indent=1).encode("utf-8"))

    def load_pack_lock(self, project_id):
        p = self._dir_of(project_id) / "board" / "packs.lock"
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (ValueError, OSError):
            return {}                       # un lock ilegible es como no tenerlo: se reescribe
        packs = data.get("packs") if isinstance(data, dict) else None
        return packs if isinstance(packs, dict) else {}

    def save_pack_lock(self, project_id, lock):
        atomic_write(self._dir_of(project_id) / "board" / "packs.lock",
                     json.dumps({"packs": lock}, ensure_ascii=False, indent=1,
                                sort_keys=True).encode("utf-8"))

    # ------------------------------------------- la conversación con los agentes (D164)
    def _agent_path(self, project_id, name):
        if name not in AGENT_FILES:
            raise InvalidName(f"fichero del agente desconocido: {name!r}")
        return self._dir_of(project_id) / "agent" / f"{name}.json"

    def load_agent_chat(self, project_id):
        return self._load_jsonl(self._dir_of(project_id) / "agent" / "chat.jsonl")

    def append_agent_chat(self, project_id, events):
        self._append_jsonl(self._dir_of(project_id) / "agent" / "chat.jsonl", events)

    def _thread_path(self, project_id, thread_id):
        """`agent/threads/<id>.jsonl` (D165): el id, como uno de bloque; nunca una ruta."""
        if not isinstance(thread_id, str) or not BLOCK_ID_RE.fullmatch(thread_id):
            raise InvalidName(f"id de hilo no válido: {thread_id!r}")
        return self._dir_of(project_id) / "agent" / "threads" / f"{thread_id}.jsonl"

    def load_agent_thread(self, project_id, thread_id):
        return self._load_jsonl(self._thread_path(project_id, thread_id))

    def append_agent_thread(self, project_id, thread_id, events):
        self._append_jsonl(self._thread_path(project_id, thread_id), events)

    def delete_agent_thread(self, project_id, thread_id):
        self._thread_path(project_id, thread_id).unlink(missing_ok=True)

    @staticmethod
    def _load_jsonl(p):
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue                        # cortada a mitad: se salta
            if isinstance(ev, dict):
                out.append(ev)
        return out

    @staticmethod
    def _append_jsonl(p, events):
        """Añade al final (una escritura por llamada) en vez de reescribir el fichero entero en
        cada evento; una línea cortada la salta `_load_jsonl`. Con los mismos reintentos
        que `atomic_write` si otro programa lo tiene abierto un instante."""
        if not events:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        data = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
        for intento in range(20):
            try:
                with open(p, "a", encoding="utf-8", newline="\n") as f:
                    f.write(data)
                return
            except PermissionError:
                if intento == 19:
                    raise
                time.sleep(0.1)

    def load_agent_file(self, project_id, name):
        p = self._agent_path(project_id, name)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_agent_file(self, project_id, name, data):
        atomic_write(self._agent_path(project_id, name),
                     json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))

    def load_project_agent_settings(self, project_id):
        data = self._read_project_toml(self._dir_of(project_id))
        agents = data.get("agentes")
        return dict(agents) if isinstance(agents, dict) else {}

    def save_project_agent_settings(self, project_id, settings):
        d = self._dir_of(project_id)
        data = self._read_project_toml(d)
        data["agentes"] = dict(settings)
        _write_toml(d / PROJECT_FILE, data)

    # ------------------------------------------------------------ unidades (D182)
    def _workspace_toml(self):
        try:
            return tomllib.loads((self.root / WORKSPACE_FILE).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            return None

    def load_units(self):
        data = self._workspace_toml() or {}
        units = data.get("unidades")
        return dict(units) if isinstance(units, dict) else {}

    def save_units(self, units):
        data = self._workspace_toml()
        if data is None:                    # nunca se pisa uno que no se puede leer
            raise StorageError(i18n.t("workspace.ilegible_sin_motivo", fichero=self.root / WORKSPACE_FILE))
        data["unidades"] = dict(units)
        _write_toml(self.root / WORKSPACE_FILE, data)

    def load_thumbnail(self, project_id):
        p = self._dir_of(project_id) / "board" / "thumbnail.png"
        return p.read_bytes() if p.exists() else None

    def save_thumbnail(self, project_id, png):
        atomic_write(self._dir_of(project_id) / "board" / "thumbnail.png", bytes(png))

    def workdir(self, project_id):
        return self._dir_of(project_id)

    def folder_dir(self, path):
        """Carpeta local de una carpeta del workspace, para abrirla en el explorador. Solo
        existe en el almacenamiento local: en un servidor no hay explorador que abrir."""
        return self._folder_dir(path)
