"""Validación estática de un paquete (docs/PLAN_PAQUETES.md §1, P15, P23): lo que se mira sin
ejecutar nada. La usan la carga (desde FF 10.2: un paquete que no pasa no se carga, y los
demás sí, D94), instalar (FF 10.3) y el agente (`validar_paquete`, FF 10.6). `validate(folder)`
devuelve la lista de problemas, vacía si está bien.

- **Manifiesto** completo (`id`, `name`, `version`, `author`, `description`, `sdk`) y coherente
  (`packs.read_manifest`), con el módulo de `register` presente.
- **Catálogos de traducción** (`locales/<idioma>.toml`, O15): una tabla plana de textos, y en
  cada entrada los mismos marcadores `{nombre}` en el texto y en la traducción
  (`pack_locales`). La carga no los pide: allí son avisos y el paquete carga igual.
- **Ficheros**: ningún enlace (ni simbólico ni *junction*), nada fuera de su carpeta y un
  tamaño máximo (`MAX_BYTES`, sin `ui-src/` ni `__pycache__`).
- **Imports** (con `ast`, de todos los `.py`):
  - lo propio, en relativo (`from .robotarm import model`): un import absoluto de sí mismo
    (`pizarra_packs.<id>` o una carpeta propia por su nombre) no vale, salvo en `tests/`;
  - `tests/` es código de desarrollo, que la app nunca carga: allí valen también el backend
    (`pizarra`, para abrir una pizarra) y sus módulos de ayuda por su nombre (`import
    paquete`, como los ve `unittest`, P65);
  - otro paquete, solo como `pizarra_packs.<id>` y si está en `[requires]`;
  - una librería, solo si está en `[python] dependencies` (por su nombre, o en
    `[python] modules` si se importa con otro, P30);
  - de la app, solo `boardprint_sdk` y `pizarra_engine.core`; nunca el backend (`pizarra`);
  - `adsk` solo en `fusion/`.
- **Código de Fusion** (P15, P37): lo de `fusion/` y todo lo que alcance, aunque sea de forma
  transitiva, solo importa stdlib, `adsk`, `pizarra_engine.core` y código propio o de un
  paquete de `[requires]` que cumpla lo mismo; lo de otro paquete se sigue en su carpeta
  (`find`, por defecto junto a este), y si no está, no pasa.

Un import dinámico (`importlib.import_module`) no se ve: lo cubren el registro y los tests del
paquete en el entorno de paquetes.
"""
import ast
import os
import re
import sys
import tomllib
from pathlib import Path

from pizarra import pack_locales, packs

MAX_BYTES = 50 * 1024 * 1024        # sin ui-src/ (P30): un paquete lleva código y fichas
REQUIRED = ("name", "author", "description")
FUSION_DIR = "fusion"
TESTS_DIR = "tests"
ALWAYS = frozenset(sys.stdlib_module_names) | {"__future__"}
_DIST_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _norm(name):
    return re.sub(r"[-_.]+", "_", name).lower()


def _is_link(path):
    p = Path(path)
    return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())


def _files_problems(folder):
    problems, size = [], 0
    root = folder.resolve()
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        for name in list(dirnames) + filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(folder).as_posix()
            if _is_link(p):
                problems.append(f"{rel}: es un enlace; un paquete solo lleva ficheros y carpetas")
                if name in dirnames:
                    dirnames.remove(name)
            elif not p.resolve().is_relative_to(root):
                problems.append(f"{rel}: sale de la carpeta del paquete")
        dirnames[:] = [d for d in dirnames if d not in packs.SKIP_DIRS]
    for rel in packs.pack_files(folder):
        try:
            size += (folder / rel).stat().st_size
        except OSError:
            pass
    if size > MAX_BYTES:
        problems.append(f"el paquete ocupa {size / 2**20:.1f} MB y el máximo es "
                        f"{MAX_BYTES / 2**20:.0f} MB (sin ui-src/)")
    return problems


def _module_of(files, rel_parts):
    """El fichero propio del módulo `rel_parts` (relativo a la raíz del paquete), o None.
    `files`: los ficheros del paquete (`packs.pack_files`), para no preguntar al disco por
    cada import."""
    base = "/".join(rel_parts)
    for cand in ((base + ".py") if rel_parts else None, (base + "/" if base else "") + "__init__.py"):
        if cand is not None and cand in files:
            return cand
    return None


def _tops(files):
    """Los nombres de la raíz del paquete que son código suyo: carpetas y módulos `.py`."""
    return {rel.split("/")[0] if "/" in rel else rel[:-3] for rel in files
            if "/" in rel or rel.endswith(".py")}


def _package_parts(rel):
    parts = rel.split("/")
    return parts[:-1]          # blocks.py → []; fusion/build.py → ["fusion"]; x/__init__.py → ["x"]


class _Module:
    def __init__(self, rel):
        self.rel = rel
        self.absolute = []     # (nombre completo, [nombres importados de él], línea)
        self.local = set()     # ficheros propios que importa en relativo
        self.problems = []


_BODIES = ("body", "orelse", "finalbody", "handlers", "cases")


def _statements(tree):
    """Todas las sentencias de `tree`, también las de dentro de una función, un `if` o un
    `try`. Un import es siempre una sentencia: no hace falta bajar a las expresiones, que son
    casi todo el árbol (la carga valida cada paquete en cada arranque, P30)."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        inner = [n for name in _BODIES for n in (getattr(node, name, ()) or ())]
        stack.extend(reversed(inner))           # en el orden del fichero


def _scan(folder, rel, files):
    mod = _Module(rel)
    try:
        tree = ast.parse((folder / rel).read_text(encoding="utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        mod.problems.append(f"{rel}: no se puede leer ({type(exc).__name__}: {exc})")
        return mod
    pkg = _package_parts(rel)
    for node in _statements(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mod.absolute.append((a.name, [], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names]
            if node.level == 0:
                mod.absolute.append((node.module, names, node.lineno))
                continue
            up = node.level - 1
            if up > len(pkg):
                mod.problems.append(f"{rel}:{node.lineno}: el import relativo sale del paquete")
                continue
            base = pkg[:len(pkg) - up] + (node.module.split(".") if node.module else [])
            found = []
            target = _module_of(files, base)
            if target:
                found.append(target)
            for n in names:
                sub = _module_of(files, base + [n]) if n != "*" else None
                if sub:
                    found.append(sub)
            if not found:
                where = ".".join(base) or "la raíz del paquete"
                mod.problems.append(f"{rel}:{node.lineno}: el import relativo no encuentra "
                                    f"{where} en el paquete")
            mod.local.update(found)
    return mod


def _check_absolute(manifest, files, mod, in_fusion):
    """Problemas de los imports absolutos de un módulo; `in_fusion`: con las reglas de P15.
    En `tests/` (código de desarrollo, que la app nunca carga) valen además el paquete en
    absoluto (P30), el backend y los módulos de ayuda de `tests/` por su nombre (P65)."""
    out = []
    declared = {_norm(_DIST_RE.match(d).group(1)) for d in manifest.dependencies
                if _DIST_RE.match(d)} | {_norm(x.split(".")[0]) for x in manifest.modules}
    own_tops = _tops(files)
    in_tests = mod.rel.split("/")[0] == TESTS_DIR
    test_tops = set()
    if in_tests:
        test_tops = _tops({r[len(TESTS_DIR) + 1:] for r in files if r.startswith(TESTS_DIR + "/")})
    for full, names, line in mod.absolute:
        top, *rest = full.split(".")
        at = f"{mod.rel}:{line}: {full}"
        if top in ALWAYS:
            continue
        if top == "adsk":
            if not in_fusion:
                out.append(f"{at}: adsk solo en {FUSION_DIR}/ (lo que corre en Fusion, P15)")
            continue
        if top == "pizarra_engine":
            subs = rest[:1] or names
            if not subs or any(s != "core" for s in subs):
                out.append(f"{at}: del motor solo se usa pizarra_engine.core (el SDK, P22)")
            continue
        if top == packs.PACKAGE:
            # en Fusion también vale uno de [requires]: lo que alcanza de él se mira aparte (P37)
            targets = rest[:1] or names
            for t in targets:
                if t == manifest.id:
                    if not in_tests:
                        out.append(f"{at}: se importa a sí mismo en absoluto; lo propio va en "
                                   f"relativo (from .modulo import x, P23)")
                elif t not in manifest.requires:
                    out.append(f"{at}: usa el paquete {t} sin declararlo en [requires]")
            continue
        if in_fusion:
            out.append(f"{at}: lo que corre en Fusion solo usa stdlib, adsk, pizarra_engine.core "
                       f"y código propio o de un paquete de [requires] que cumpla lo mismo (P15, P37)")
            continue
        if top == "boardprint_sdk":
            continue
        if top == "pizarra":
            if in_tests:
                continue             # los tests abren una pizarra con el backend (P65)
            out.append(f"{at}: importa el backend de la app; un paquete solo usa boardprint_sdk")
            continue
        if top in test_tops:
            continue                 # tests/paquete.py como `import paquete` (unittest, P65)
        if top in own_tops and not in_tests:
            out.append(f"{at}: es código del paquete; impórtalo en relativo (from .{top} import …, P23)")
            continue
        if _norm(top) not in declared:
            out.append(f"{at}: la librería {top} no está en [python] dependencies (si se "
                       f"instala con otro nombre, añádelo a [python] modules)")
    return out


def validate(folder, find=None, scans=None, locales=True):
    """Problemas del paquete de `folder` (lista de textos; vacía si se puede instalar). `find`
    (id → carpeta o None) dice dónde está un paquete de [requires] para seguir lo que alcanza
    `fusion/` (P37); por defecto, junto a este. `scans` ({carpeta: análisis}): lo ya leído de
    un paquete, para que la carga, que los valida todos, lea cada uno una sola vez. `locales`:
    si se miran los catálogos de traducción; la carga no lo hace (para ella son avisos, O15)."""
    folder = Path(folder)
    scans = {} if scans is None else scans
    if _is_link(folder) or not folder.is_dir():
        return [f"{folder}: no es una carpeta"]
    problems = _files_problems(folder)
    try:
        manifest = packs.read_manifest(folder)
    except ValueError as exc:
        return problems + [f"pack.toml: {e}" for e in str(exc).split("; ")]
    data_missing = [k for k in REQUIRED if not str(getattr(manifest, k) or "").strip()
                    or (k == "name" and not _has_key(folder, "name"))]
    problems += [f"pack.toml: falta {k}" for k in data_missing]
    if not (folder / f"{manifest.module}.py").is_file():
        problems.append(f"falta {manifest.module}.py, el módulo con register(pack)")
    if manifest.ui and not (folder / manifest.ui).is_file():
        problems.append(f"[ui] entry: no está {manifest.ui}")
    if locales:
        problems += pack_locales.problems(folder)

    files, mods = _scan_cached(scans, folder)
    for mod in mods.values():
        problems += mod.problems
        in_fusion = mod.rel.split("/")[0] == FUSION_DIR
        problems += _check_absolute(manifest, files, mod, in_fusion)
    reach = _FusionReach(manifest, folder, files, mods, find or _sibling(folder), scans)
    return problems + reach.problems()


def _scan_cached(scans, folder):
    key = str(Path(folder).resolve())
    if key not in scans:
        scans[key] = _scan_pack(Path(folder))
    return scans[key]


def _scan_pack(folder):
    """`(ficheros, {módulo: _Module})` del paquete de `folder`."""
    files = frozenset(packs.pack_files(folder))
    py = sorted(rel for rel in files if rel.endswith(".py"))
    return files, {rel: _scan(folder, rel, files) for rel in py if not _is_link(folder / rel)}


def _sibling(folder):
    """Dónde buscar un paquete de [requires] por defecto: junto a este (el repo, una carpeta de
    paquetes instalados), si su manifiesto dice ese id."""
    def find(pack_id):
        cand = folder.parent / pack_id
        try:
            return cand if packs.read_manifest(cand).id == pack_id else None
        except (OSError, ValueError):
            return None
    return find


class _FusionReach:
    """P15 transitivo, P37: lo que alcanza `fusion/`, propio o de un paquete de [requires] (y
    de los suyos), cumple también las reglas de Fusion. Los nodos son (id, módulo)."""

    def __init__(self, manifest, folder, files, mods, find, scans):
        self.root = manifest.id
        self.find = find
        self.scans = scans
        self.packs = {manifest.id: (manifest, files, mods)}   # id -> (manifiesto, ficheros, módulos)
        self.bad = {}

    def _pack(self, pack_id):
        if pack_id not in self.packs:
            folder = self.find(pack_id)
            try:
                if folder is None:
                    raise ValueError
                manifest = packs.read_manifest(Path(folder))
                self.packs[pack_id] = (manifest, *_scan_cached(self.scans, folder))
            except (OSError, ValueError):
                self.packs[pack_id] = None
        return self.packs[pack_id]

    def _name(self, node):
        pack_id, rel = node
        return rel if pack_id == self.root else f"{pack_id}/{rel}"

    def _bad(self, node):
        """El primer motivo por el que el módulo `node` no se puede usar en Fusion, o None."""
        if node not in self.bad:
            manifest, files, mods = self.packs[node[0]]
            mod = mods.get(node[1])
            found = _check_absolute(manifest, files, mod, in_fusion=True) if mod else []
            self.bad[node] = None if not found else \
                found[0] if node[0] == self.root else f"{node[0]}/{found[0]}"
        return self.bad[node]

    def _edges(self, node):
        """Los módulos que importa `node`: los propios en relativo y los de otro paquete."""
        pack_id, rel = node
        manifest, _files, mods = self.packs[pack_id]
        mod = mods.get(rel)
        if mod is None:
            return [], []
        out, missing = [(pack_id, x) for x in sorted(mod.local)], []
        for full, names, line in mod.absolute:
            top, *rest = full.split(".")
            if top != packs.PACKAGE or not rest or rest[0] == pack_id \
                    or rest[0] not in manifest.requires:
                continue                     # sin paquete, a sí mismo o sin declarar: ya avisado
            other = self._pack(rest[0])
            where = f"{self._name(node)}:{line}: {full}"
            if other is None:
                missing.append(f"{where}: no se encuentra el paquete {rest[0]} para comprobar "
                               f"lo que alcanza en Fusion (P37)")
                continue
            files = other[1]
            found = [m for m in [_module_of(files, rest[1:]) if rest[1:] else None]
                     + [_module_of(files, rest[1:] + [n]) for n in names if n != "*"] if m]
            if not found:
                missing.append(f"{where}: no está en el paquete {rest[0]}")
            out += [(rest[0], m) for m in found]
        return out, missing

    def problems(self):
        _manifest, _files, mods = self.packs[self.root]
        out = []
        for rel in sorted(r for r in mods if r.split("/")[0] == FUSION_DIR):
            start = (self.root, rel)
            seen, stack = {start}, [start]
            while stack:
                cur = stack.pop()
                edges, missing = self._edges(cur)
                out += [f"{rel} alcanza {self._name(cur)}: {m}" if cur != start else m
                        for m in missing]
                for nxt in edges:
                    if nxt in seen:
                        continue
                    seen.add(nxt)
                    stack.append(nxt)
                    if nxt[0] == self.root and nxt[1].split("/")[0] == FUSION_DIR:
                        continue             # otro de fusion/: ya se mira desde él
                    why = self._bad(nxt)
                    if why:
                        out.append(f"{rel} alcanza {self._name(nxt)}, que no se puede usar en "
                                   f"Fusion: {why}")
        return list(dict.fromkeys(out))


def _has_key(folder, key):
    try:
        return key in tomllib.loads((folder / "pack.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
