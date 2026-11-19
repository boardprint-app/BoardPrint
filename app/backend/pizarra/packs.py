"""Carga de paquetes (docs/PLAN_PAQUETES.md §1, §3; plan D24, D94).

Un paquete es una carpeta `<origen>/<id>/` con `pack.toml` (el formato completo, en §1 del
plan; aquí se lee con `read_manifest`):

    id = "terminales"            # igual que la carpeta: minúsculas, cifras y _
    name = "Terminales"
    version = "0.2.0"            # semver
    sdk = ">=1.0,<2"             # versión del SDK que necesita (P22)
    module = "blocks"            # blocks.py de la carpeta; define register(pack)
    [requires]                   # otros paquetes, con su rango (P14, P23)
    robotica_base = ">=0.1,<0.2"

Lo que un paquete usa para registrarse y ejecutar (`Param`, `PackBuilder`, `RunContext`…) es
el SDK (`boardprint_sdk.packs`); aquí se reexporta para el backend.

**Orígenes** (§3, P10, P26, P81), de más a menos prioridad: desarrollo (`BOARDPRINT_DEV_PACKS`,
solo en una app sin congelar; el arranque de desarrollo la pone a `packs/` del repo), el
workspace (`<workspace>/.boardprint/packs`) y el usuario (`<ajustes>/packs`). Nada más: la
app no trae paquetes (P11). Si un paquete está en dos, se usa el de más prioridad y el otro
queda anotado en `PackInfo.shadowed`.

**Validación guardada** (P80): si `load` recibe `validated` (la ruta de
`<ajustes>/cache/packs-validados.json`), un paquete cuya clave ya pasó no se vuelve a validar.
La clave es su huella, las de lo que alcanza por `[requires]`, la versión del SDK y la de las
reglas (`rules_hash`).

**Orden**: se cargan en orden de `[requires]`. Un paquete cuya dependencia falta, no cumple
el rango o no carga, no se carga; un ciclo es un error de todos los paquetes del ciclo.

La carga es tolerante: un paquete roto (manifiesto mal, no pasa la validación estática de
`pack_validate`, que desde FF 10.2 se aplica antes de importar nada, P30; no importa, `register` falla, declara
un puerto de un tipo que nadie registra, repite un tipo de bloque...) no se carga entero, queda
con su error en `Registry.packs` y la app arranca con los demás. Nunca pisa nada de lo ya
cargado.
"""
from dataclasses import dataclass, field
import hashlib
import importlib
import json
import os
import re
import sys
import tomllib
import traceback
import types
from pathlib import Path

import boardprint_sdk
from boardprint_sdk.packs import (OWN_UI, Action, BlockType, ConfirmRequired,  # noqa: F401
                                  Connector, Fix, PackBuilder, Param, PortType, Pull, RunContext,
                                  Template, View, box, chart, line, point, view2d)
from pizarra import files
from pizarra.pack_versions import parse_spec, parse_version, satisfies

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Tipos de puerto del núcleo: los registran los conectores (D35) y las tarjetas de archivo y de
# carpeta (D131), no un paquete. Además vale cualquier `archivo.<ext>` (`files.is_file_port`).
CORE_PORT_TYPES = {"cad.modelo": "modelo CAD", "archivo": "archivo", "archivo.step": "archivo STEP",
                   "carpeta": "carpeta"}

PACKAGE = "pizarra_packs"     # paquete virtual bajo el que se importan los módulos de los paquetes
SDK_VERSION = boardprint_sdk.__version__
DEV_ENV = "BOARDPRINT_DEV_PACKS"
WORKSPACE_PACKS = Path(".boardprint") / "packs"     # dentro del workspace (P10)
# Orígenes, de más a menos prioridad. La app no trae paquetes (P11, P81).
ORIGINS = ("desarrollo", "workspace", "usuario")
VALIDATED_MAX = 1000  # claves en packs-validados.json; las más viejas se olvidan
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# Lo que no es del paquete: ni entra en su huella ni se exporta (§7).
SKIP_DIRS = frozenset({"__pycache__", "ui-src", "node_modules", ".git"})
MAX_SHOWN = 5         # problemas de la validación en el error de un paquete que no carga


def action_error(name, exc):
    """El motivo de una acción de paquete que falla (P46): un `ValueError` o un `RuntimeError`
    es lo que el paquete dice al usuario y va tal cual («no hay nada traído que aplicar»);
    cualquier otra excepción es un fallo del paquete y lleva la acción y su tipo."""
    if isinstance(exc, ValueError) or type(exc) is RuntimeError:
        return str(exc)
    return f"{name}: {type(exc).__name__}: {exc}"


def pack_id_of(kind):
    """El paquete de un tipo de bloque, de puerto o de plantilla: lo de antes del primer punto."""
    return kind.split(".", 1)[0] if isinstance(kind, str) else ""


@dataclass(frozen=True)
class Manifest:
    """`pack.toml` ya comprobado (§1)."""
    id: str
    name: str
    version: str
    sdk: str
    module: str = "blocks"
    author: str = ""
    description: str = ""
    requires: dict = field(default_factory=dict)   # {id: rango}
    dependencies: tuple = ()      # [python] dependencies: librerías (P3, P20)
    # [python] modules: nombres importables que no salen del de su librería (`scikit-learn`
    # se importa como `sklearn`); la validación los da por declarados (P30)
    modules: tuple = ()
    ports: dict = field(default_factory=dict)      # {tipo de puerto: color}
    ui: str = ""                  # [ui] entry (P24)


@dataclass
class PackInfo:
    id: str
    name: str = ""
    version: str = ""
    path: str = ""
    error: str | None = None
    origin: str = ""              # de dónde se carga (ORIGINS, o la carpeta si se pasó a mano)
    shadowed: list = field(default_factory=list)   # orígenes donde también está y no se usa
    requires: dict = field(default_factory=dict)
    digest: str = ""              # huella del contenido (`board/packs.lock`, P25)
    ui: str = ""                  # [ui] entry: la interfaz propia (P24), dentro de `ui/`
    author: str = ""
    description: str = ""
    dependencies: tuple = ()      # [python] dependencies (Ajustes → Paquetes, §7)
    # catálogos de traducción (`locales/<idioma>.toml`, O15): {idioma: {origen: traducción}}
    i18n: dict = field(default_factory=dict)


class Registry(dict):
    """`{tipo de bloque: BlockType}`, más los puertos, las plantillas y el estado de cada paquete."""

    def __init__(self):
        super().__init__()
        self.ports = {t: PortType(t, label) for t, label in CORE_PORT_TYPES.items()}
        self.colors = {}      # {tipo de puerto: #rrggbb}, del [ports] de su paquete (P67)
        self.templates = {}
        self.views = {}       # {tipo de bloque: View}: los que no la declaran no están (§5)
        self.actions = {}     # {nombre: Action} (§5, P40)
        self.connectors = {}  # {id: Connector}, con el id de su paquete (§6, P38)
        self.packs = []
        self.dirs = []        # de dónde se cargó: el proceso de cálculo carga lo mismo (D92)
        self.origins = []     # [(origen, carpeta)], en el mismo orden
        self.validated = None  # packs-validados.json con el que se cargó (P80), o None
        self._host = None

    @property
    def host(self):
        """Quien corre el código de los paquetes de este registro (`pizarra.pack_host`): el
        trabajador si se cargó con él (la app, P89); si no, este mismo proceso."""
        if self._host is None:
            from pizarra.pack_host import InProcessHost
            self._host = InProcessHost(self)
        return self._host

    @host.setter
    def host(self, value):
        self._host = value

    def default_params(self, kind):
        return {k: p.default for k, p in self[kind].params.items()}

    def renamed(self):
        """`{id de antes: id de ahora}` de los bloques que declaran `formerly` (P59): la escena
        de un proyecto se migra al abrirlo, sin que el núcleo nombre ningún paquete."""
        return {old: k for k, b in self.items() for old in b.formerly}

    def describe(self):
        """Lo que la interfaz necesita para pintar la paleta y las tarjetas."""
        return {
            "blocks": {k: {"title": b.title, "pack": b.pack, "description": b.description,
                           "inputs": dict(b.inputs), "outputs": dict(b.outputs),
                           "requires": list(b.requires), "pull": b.pull is not None,
                           "optional": list(b.optional), "preview": b.preview is not None,
                           "connector": b.connector,
                           "fix": {"port": b.fix.port, "field": b.fix.field, "label": b.fix.label}
                                  if b.fix else None,
                           "params": {n: {"default": p.default, "unit": p.unit, "label": p.label,
                                          "choices": list(p.choices), "widget": p.widget,
                                          "choice_labels": dict(p.choice_labels)}
                                      for n, p in b.params.items()},
                           "view": {"card": _surface(self.view(k).card),
                                    "panel": _surface(self.view(k).panel)}}
                       for k, b in self.items()},
            # el color, el del [ports] del paquete; sin él (null), la interfaz usa su paleta
            "ports": {t: {"label": p.label, "color": self.colors.get(t)}
                      for t, p in self.ports.items()},
            "templates": {t.id: {"title": t.title, "pack": t.pack, "description": t.description,
                                 "blocks": [list(b) for b in t.blocks],
                                 "links": [list(l) for l in t.links]}
                          for t in self.templates.values()},
            "packs": [{"id": p.id, "name": p.name, "version": p.version, "error": p.error,
                       "origin": p.origin, "shadowed": list(p.shadowed),
                       "requires": dict(p.requires),
                       # la interfaz propia se sirve en /packs/<id>/<ui> (pack_ui)
                       "ui": p.ui if p.error is None else "",
                       # sus catálogos de traducción (O15): la interfaz traduce al pintar
                       "i18n": p.i18n if p.error is None else {},
                       "actions": sorted(a for a in self.actions if pack_id_of(a) == p.id)}
                      for p in self.packs],
            # la parte de interfaz de un conector (P41) es la interfaz propia de su paquete
            "connectors": {c.id: {"title": c.title, "accepts": list(c.accepts),
                                  "gives": list(c.gives), "launch": c.launch is not None,
                                  "card": c.card, "panel": c.panel}
                           for c in self.connectors.values()},
        }

    def view(self, kind):
        """La `View` de un tipo de bloque: la de `pack.view`, o la tarjeta de siempre."""
        return self.views.get(kind) or View()

    def pack(self, pack_id):
        """El `PackInfo` del paquete `pack_id` si se cargó bien, o None."""
        return next((p for p in self.packs if p.id == pack_id and p.error is None), None)

    def pack_of(self, kind):
        """El `PackInfo` cargado del paquete de un tipo de bloque (`robotica.brazo` →
        `robotica`), o None."""
        return self.pack(pack_id_of(kind))


def _surface(value):
    """Una superficie de `View` en JSON: `"ui"` o la lista de controles."""
    return value if value == OWN_UI else list(value)


def default_origins(user_dir=None, workspace_dir=None, environ=None):
    """`[(origen, carpeta)]` de más a menos prioridad (§3). `user_dir`: `<ajustes>/packs`;
    `workspace_dir`: `<workspace>/.boardprint/packs`. Desarrollo solo en una app sin congelar
    (P26): las carpetas de `BOARDPRINT_DEV_PACKS` (con el separador de rutas); sin ella, nada
    (P81)."""
    environ = os.environ if environ is None else environ
    out = []
    if not getattr(sys, "frozen", False):
        out += [("desarrollo", Path(d)) for d in environ.get(DEV_ENV, "").split(os.pathsep)
                if d.strip()]
    if workspace_dir is not None:
        out.append(("workspace", Path(workspace_dir)))
    if user_dir is not None:
        out.append(("usuario", Path(user_dir)))
    return out


def default_dirs():
    """Las carpetas de `default_origins()`, en su orden: lo que carga `load()` sin argumentos."""
    return [d for _, d in default_origins()]


def ensure_engine_path():
    """Los bloques llaman al motor (`pizarra_engine`). En desarrollo, `engine/` va en sys.path;
    empaquetado, PyInstaller ya lleva el motor dentro."""
    if not getattr(sys, "frozen", False):
        engine = Path(__file__).resolve().parents[3] / "engine"
        if str(engine) not in sys.path:
            sys.path.insert(0, str(engine))


def _import_pack(pack_id, folder, module):
    if PACKAGE not in sys.modules:
        root = types.ModuleType(PACKAGE)
        root.__path__ = []
        sys.modules[PACKAGE] = root
    name = f"{PACKAGE}.{pack_id}"
    for m in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[m]                      # recargar desde la carpeta de ahora
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(folder)]
    sys.modules[name] = pkg
    return importlib.import_module(f"{name}.{module}")


def _str_list(value, what, errs):
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        errs.append(f"{what} tiene que ser una lista de textos")
        return ()
    return tuple(value)


def read_manifest(folder):
    """El `Manifest` de `<folder>/pack.toml`. `ValueError` con todo lo que falla, separado por
    `; `: un id que no es su carpeta, una versión que no es semver, un `sdk` que falta o que no
    cumple el de la app, un `[requires]` mal escrito…"""
    folder = Path(folder)
    try:
        data = tomllib.loads((folder / "pack.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"pack.toml no se puede leer: {exc}") from None
    errs = []
    pack_id = data.get("id")
    if pack_id != folder.name or not isinstance(pack_id, str) or not ID_RE.match(pack_id):
        errs.append(f"el id de pack.toml ({pack_id!r}) tiene que ser el nombre de la carpeta "
                    f"({folder.name!r}), en minúsculas, cifras y _")
    version = data.get("version")
    try:
        parse_version(version)
    except ValueError as exc:
        errs.append(str(exc))
    sdk = data.get("sdk")
    if sdk is None:
        errs.append('falta sdk: el rango del SDK que necesita, p. ej. sdk = ">=1.0,<2"')
    else:
        try:
            if not satisfies(SDK_VERSION, sdk):
                errs.append(f"pide el SDK {sdk} y la app trae el {SDK_VERSION}")
        except ValueError as exc:
            errs.append(f"sdk: {exc}")
    module = data.get("module", "blocks")
    if not isinstance(module, str) or not ID_RE.match(module):
        errs.append(f"module = {module!r} no es un nombre de módulo válido")
    for key in ("name", "author", "description"):
        if key in data and not isinstance(data[key], str):
            errs.append(f"{key} tiene que ser un texto")
    requires = data.get("requires", {})
    if not isinstance(requires, dict):
        errs.append("[requires] tiene que ser una tabla {paquete = rango}")
        requires = {}
    for dep, spec in requires.items():
        if not ID_RE.match(dep) or dep == pack_id:
            errs.append(f"[requires]: {dep!r} no es el id de otro paquete")
        try:
            parse_spec(spec)
        except ValueError as exc:
            errs.append(f"[requires] {dep}: {exc}")
    python = data.get("python", {})
    if not isinstance(python, dict):
        errs.append("[python] tiene que ser una tabla")
        python = {}
    deps = _str_list(python.get("dependencies", []), "[python] dependencies", errs)
    mods = _str_list(python.get("modules", []), "[python] modules", errs)
    for m in mods:
        if not MODULE_RE.match(m):
            errs.append(f"[python] modules: {m!r} no es un nombre de módulo")
    ports = data.get("ports", {})
    if not isinstance(ports, dict):
        errs.append("[ports] tiene que ser una tabla {tipo = color}")
        ports = {}
    for t, color in ports.items():
        if isinstance(pack_id, str) and not t.startswith(pack_id + "."):
            errs.append(f"[ports]: el tipo {t!r} no empieza por {pack_id + '.'!r}")
        if not isinstance(color, str) or not COLOR_RE.match(color):
            errs.append(f"[ports] {t}: el color {color!r} no es #rrggbb")
    ui = data.get("ui", {})
    entry = ui.get("entry", "") if isinstance(ui, dict) else None
    if entry is None or not isinstance(entry, str) or (
            entry and (Path(entry).is_absolute() or ".." in Path(entry).parts or "\\" in entry
                       or not entry.startswith("ui/") or entry == "ui/")):
        errs.append("[ui] entry tiene que ser una ruta dentro de ui/ del paquete (ui/index.html)")
        entry = ""
    if errs:
        raise ValueError("; ".join(errs))
    return Manifest(id=pack_id, name=data.get("name", pack_id), version=version, sdk=sdk,
                    module=module, author=data.get("author", ""),
                    description=data.get("description", ""), requires=dict(requires),
                    dependencies=deps, modules=mods, ports=dict(ports), ui=entry)


def pack_files(folder):
    """Los ficheros del paquete (rutas relativas con `/`, ordenadas), sin `__pycache__`,
    `ui-src/` ni `.pyc`: lo que entra en su huella y en un `.bppack`. No sigue enlaces."""
    folder = Path(folder)
    out = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in filenames:
            if not f.endswith((".pyc", ".pyo")):
                out.append((Path(dirpath) / f).relative_to(folder).as_posix())
    return sorted(out)


def digest(folder):
    """Huella del contenido del paquete (P25): cambia si cambia un fichero, su nombre o su
    contenido."""
    folder = Path(folder)
    h = hashlib.sha256()
    for rel in pack_files(folder):
        try:
            data = (folder / rel).read_bytes()
        except OSError:
            data = b"?"
        # con la longitud delante: dos paquetes distintos nunca dan la misma secuencia
        h.update(f"{rel}\n{len(data)}\n".encode("utf-8") + data)
    return h.hexdigest()


_rules = []


def rules_hash():
    """Huella de las reglas de la validación (P80): el código de este módulo (el manifiesto) y
    el de `pack_validate`. Cambiar una regla cambia la clave de todos los paquetes, sin tener
    que acordarse de subir un número. Congelado no hay ficheros `.py`: la del ejecutable, que
    solo cambia con una app nueva."""
    if not _rules:
        from pizarra import pack_validate
        h = hashlib.sha256()
        for mod in (sys.modules[__name__], pack_validate):
            try:
                h.update(Path(mod.__file__).read_bytes())
            except (OSError, TypeError):
                st = Path(sys.executable).stat()
                h.update(f"{sys.executable}|{st.st_size}|{st.st_mtime_ns}".encode())
        _rules.append(h.hexdigest())
    return _rules[0]


def validation_key(pack_id, requires_of, digests):
    """La clave de la validación de `pack_id` (P80): su huella, las de todo lo que alcanza por
    `[requires]` (la validación sigue sus imports, P37), la versión del SDK y la de las reglas.
    `requires_of`: `{id: [ids que pide]}`; `digests`: `{id: huella}` (un paquete que no está,
    huella vacía)."""
    seen, stack = {}, [pack_id]
    while stack:
        p = stack.pop()
        if p not in seen:
            seen[p] = digests.get(p, "")
            stack.extend(sorted(requires_of.get(p, ())))
    raw = json.dumps([sorted(seen.items()), SDK_VERSION, rules_hash()])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_validated(path):
    """Las claves que ya pasaron la validación, de la más vieja a la más nueva. Un fichero que
    no está o no se lee es una caché vacía: se valida todo."""
    try:
        keys = json.loads(Path(path).read_text(encoding="utf-8")).get("ok", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [k for k in keys if isinstance(k, str)] if isinstance(keys, list) else []


def write_validated(path, keys):
    """Guarda las claves (las `VALIDATED_MAX` más nuevas). Si no se puede, no pasa nada: la
    próxima carga vuelve a validar."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"ok": list(keys)[-VALIDATED_MAX:]}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _template_absent(t, alive):
    """Los paquetes, otros que el suyo, de los que la plantilla `t` nombra bloques y que no
    están cargados (`alive`). Con alguno, la plantilla no se ofrece y su paquete carga igual
    (docs/PLAN_TERMINALES.md T83: *Terminal sobre el brazo* sin robótica); un tipo que no existe
    en un paquete cargado sigue siendo un error de la plantilla."""
    return sorted({pack_id_of(b[1]) for b in t.blocks
                   if len(b) >= 2 and pack_id_of(b[1]) not in (t.pack, *alive)})


def _template_errors(t, blocks):
    errs = []
    keys = {}
    for b in t.blocks:
        if len(b) not in (4, 5) or (len(b) == 5 and not isinstance(b[4], dict)):
            errs.append(f"{t.id}: cada bloque es (clave, tipo, dx, dy[, parámetros])")
            continue
        key, kind = b[0], b[1]
        if kind not in blocks:
            errs.append(f"{t.id}: el tipo de bloque {kind!r} no existe")
        elif len(b) == 5:
            unknown = sorted(set(b[4]) - set(blocks[kind].params))
            if unknown:
                errs.append(f"{t.id}: {kind} no tiene los parámetros {unknown}")
        if key in keys:
            errs.append(f"{t.id}: la clave {key!r} está repetida")
        keys[key] = kind
    taken = set()
    edges = {}
    for l in t.links:
        if len(l) != 4:
            errs.append(f"{t.id}: cada conexión es (origen, puerto, destino, puerto)")
            continue
        src, op, dst, ip = l
        if src not in keys or dst not in keys or keys[src] not in blocks or keys[dst] not in blocks:
            errs.append(f"{t.id}: la conexión {l!r} usa un bloque que no está en la plantilla")
            continue
        ot = blocks[keys[src]].outputs.get(op)
        it = blocks[keys[dst]].inputs.get(ip)
        if ot is None or it is None or ot != it:
            errs.append(f"{t.id}: la conexión {l!r} no une una salida y una entrada del mismo tipo")
        if (dst, ip) in taken:
            errs.append(f"{t.id}: la entrada {dst}.{ip} tiene dos conexiones")
        taken.add((dst, ip))
        edges.setdefault(src, set()).add(dst)
    # sin ciclos
    state = {}

    def cyclic(n):
        state[n] = 1
        for m in edges.get(n, ()):
            if state.get(m) == 1 or (state.get(m) is None and cyclic(m)):
                return True
        state[n] = 2
        return False

    if any(state.get(k) is None and cyclic(k) for k in keys):
        errs.append(f"{t.id}: las conexiones cierran un ciclo")
    return errs


def _as_origins(dirs):
    """`dirs` como `[(origen, carpeta)]`: vale una lista de carpetas (el origen es la carpeta)
    o de pares `(origen, carpeta)`, ya en orden de prioridad."""
    if dirs is None:
        return default_origins()
    out = []
    for d in dirs:
        if isinstance(d, (tuple, list)):
            out.append((str(d[0]), Path(d[1])))
        else:
            out.append((str(d), Path(d)))
    return out


def discover(origins):
    """`{id: [(origen, carpeta), ...]}` con lo que hay en cada origen, de más a menos
    prioridad: el primero es el que se usa (§3)."""
    found = {}
    for origin, d in origins:
        d = Path(d)
        if not d.is_dir():
            continue
        for folder in sorted(x for x in d.iterdir() if (x / "pack.toml").is_file()):
            found.setdefault(folder.name, []).append((origin, folder))
    return found


def _cycles(graph):
    """Los nodos que están en un ciclo de `graph` ({n: {m, ...}}), con el ciclo de cada uno."""
    index, low, stack, on, out, counter = {}, {}, [], set(), {}, [0]

    def strong(v):                     # Tarjan
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                for w in comp:
                    out[w] = sorted(comp)

    for v in sorted(graph):
        if v not in index:
            strong(v)
    return out


def _dependency_order(manifests, infos):
    """Ids de `manifests` en orden de carga (cada uno después de lo que pide). Marca el error
    en `infos` de los que no se pueden cargar: una dependencia que falta, que no cumple el
    rango o que tampoco se carga, y los de un ciclo."""
    errors = {}
    graph = {pid: {d for d in m.requires if d in manifests} for pid, m in manifests.items()}
    for pid, comp in _cycles(graph).items():
        errors[pid] = "ciclo de dependencias entre " + ", ".join(comp)
    for pid, m in manifests.items():
        for dep, spec in sorted(m.requires.items()):
            if pid in errors:
                break
            if dep not in infos:
                errors[pid] = f"falta el paquete {dep} ({spec}), del que depende"
            elif dep in manifests and not satisfies(manifests[dep].version, spec):
                errors[pid] = f"pide {dep} {spec} y está la {manifests[dep].version}"
    # lo que depende de algo que no se carga, tampoco (hasta que no cambie nada)
    changed = True
    while changed:
        changed = False
        for pid, m in manifests.items():
            if pid in errors:
                continue
            bad = sorted(d for d in m.requires if d not in manifests or d in errors)
            if bad:
                errors[pid] = f"no se carga {bad[0]}, del que depende"
                changed = True
    for pid, msg in errors.items():
        infos[pid].error = f"ValueError: {msg}"
    order, done = [], set()
    pending = sorted(pid for pid in manifests if pid not in errors)
    while pending:
        ready = [pid for pid in pending if set(manifests[pid].requires) <= done]
        for pid in ready:
            order.append(pid)
            done.add(pid)
        pending = [pid for pid in pending if pid not in done]
    return order


def load(dirs=None, log=None, validated=None):
    """Carga los paquetes de `dirs` (por defecto, `default_origins()`): carpetas o pares
    `(origen, carpeta)`, de más a menos prioridad. `validated`: el fichero de las validaciones
    guardadas (P80); sin él, se valida todo. Nunca lanza."""
    log = log or (lambda msg: print(msg, file=sys.stderr))
    ensure_engine_path()
    reg = Registry()
    origins = _as_origins(dirs)
    reg.dirs = [str(d) for _, d in origins]
    reg.origins = [(o, str(d)) for o, d in origins]
    reg.validated = str(validated) if validated else None

    from pizarra import pack_locales, pack_validate   # aquí: importan este módulo

    found = discover(origins)
    chosen = {pid: places[0][1] for pid, places in found.items()}
    scans = {}                                    # cada paquete se lee una vez (P30)
    infos, manifests, digests = {}, {}, {}
    for pid, places in sorted(found.items()):
        (origin, folder), rest = places[0], places[1:]
        info = infos[pid] = PackInfo(id=pid, path=str(folder), origin=origin,
                                     shadowed=[o for o, _ in rest])
        if rest:
            log(f"[paquetes] {pid}: está en {origin} y en {', '.join(info.shadowed)}; "
                f"se usa el de {origin}")
        try:
            m = read_manifest(folder)
            info.name, info.version, info.requires = m.name, m.version, dict(m.requires)
            info.ui, info.author, info.description = m.ui, m.author, m.description
            info.dependencies = m.dependencies
            info.digest = digests[pid] = digest(folder)
            # un catálogo mal hecho es un aviso: se deja fuera y el paquete carga (O15)
            info.i18n, bad = pack_locales.read(folder)
            for msg in bad:
                log(f"[paquetes] {pid}: aviso: {msg}")
            manifests[pid] = m
        except Exception as exc:                  # noqa: BLE001 un paquete roto no tumba la app
            info.error = f"{type(exc).__name__}: {exc}"
            log(f"[paquetes] {pid}: no se carga. {info.error}")

    # La validación (§1), salvo la de una clave que ya pasó (P80)
    known = read_validated(validated) if validated else []
    passed = set(known)
    fresh = []
    requires_of = {pid: list(m.requires) for pid, m in manifests.items()}
    for pid in sorted(manifests):
        key = validation_key(pid, requires_of, digests)
        if key in passed:
            continue
        try:
            problems = pack_validate.validate(Path(infos[pid].path), find=chosen.get, scans=scans,
                                              locales=False)    # los catálogos, avisos (O15)
            if problems:
                more = f"; y {len(problems) - MAX_SHOWN} más" if len(problems) > MAX_SHOWN else ""
                raise ValueError("no pasa la validación: " + "; ".join(problems[:MAX_SHOWN]) + more)
            fresh.append(key)
        except Exception as exc:                  # noqa: BLE001 un paquete roto no tumba la app
            infos[pid].error = f"{type(exc).__name__}: {exc}"
            log(f"[paquetes] {pid}: no se carga. {infos[pid].error}")
            del manifests[pid]
    if validated and fresh:
        write_validated(validated, [k for k in known if k not in fresh] + fresh)

    order = _dependency_order(manifests, infos)
    for pid in sorted(set(manifests) - set(order)):
        log(f"[paquetes] {pid}: no se carga. {infos[pid].error}")
    built = {}                                    # id -> PackBuilder de los que registraron bien
    for pid in order:
        info, m = infos[pid], manifests[pid]
        try:
            bad = [d for d in m.requires if d not in built]
            if bad:
                raise ValueError(f"no se carga {bad[0]}, del que depende")
            mod = _import_pack(pid, Path(info.path), m.module)
            if not callable(getattr(mod, "register", None)):
                raise ValueError(f"{m.module}.py no define register(pack)")
            builder = PackBuilder(pid)
            mod.register(builder)
            if not m.ui:
                builder.errors += [f"{k}: pack.view pide la interfaz propia y pack.toml no "
                                   "tiene [ui] entry" for k, v in builder.views.items()
                                   if OWN_UI in (v.card, v.panel)]
                builder.errors += [f"pack.connector de {c.id}: card o panel piden la interfaz "
                                   "propia y pack.toml no tiene [ui] entry"
                                   for c in builder.connectors.values() if c.card or c.panel]
            builder.errors += [f"[ports] {t}: el paquete no registra ese tipo (pack.port)"
                               for t in m.ports if t not in builder.ports]
            if builder.errors:
                raise ValueError("; ".join(builder.errors))
            built[pid] = builder
        except Exception as exc:                  # noqa: BLE001 un paquete roto no tumba la app
            info.error = f"{type(exc).__name__}: {exc}"
            log(f"[paquetes] {pid}: no se carga. {info.error}\n"
                + "".join(traceback.format_exception_only(type(exc), exc)).strip())
    reg.packs = [infos[pid] for pid in sorted(infos)]

    # Un paquete puede usar los tipos de puerto del núcleo, los suyos y los de otro paquete que
    # se cargue. Si uno cae, los que dependían de sus tipos (o lo piden en [requires]) caen
    # también: se repite hasta que no cambie nada.
    alive = dict(built)
    while True:
        known = set(reg.ports) | {t for b in alive.values() for t in b.ports}
        all_blocks = {k: bt for b in alive.values() for k, bt in b.blocks.items()}
        all_connectors = {c for b in alive.values() for c in b.connectors}
        failed = {}
        for pid, b in alive.items():
            errs = [f"no se carga {d}, del que depende" for d in sorted(manifests[pid].requires)
                    if d not in alive]
            for bt in b.blocks.values():
                for side, ports in (("entrada", bt.inputs), ("salida", bt.outputs)):
                    for port, t in ports.items():
                        if t not in known and not files.is_file_port(t):
                            errs.append(f"{bt.kind}: la {side} {port!r} es de un tipo que nadie "
                                        f"registra ({t!r})")
                errs.extend(_connector_errors(pid, bt, manifests[pid], all_connectors))
                errs.extend(_formerly_errors(bt, all_blocks))
            for c in b.connectors.values():
                errs.extend(f"pack.connector de {c.id}: da {t!r}, un tipo que nadie registra"
                            for t in c.gives if t not in known and not files.is_file_port(t))
            for t in b.templates.values():
                if not _template_absent(t, alive):    # sin sus paquetes, no se ofrece (T83)
                    errs.extend(_template_errors(t, all_blocks))
            if errs:
                failed[pid] = "; ".join(errs)
        if not failed:
            break
        for pid, msg in failed.items():
            infos[pid].error = msg
            log(f"[paquetes] {pid}: no se carga. {msg}")
            del alive[pid]

    for pid in sorted(alive):
        b = alive[pid]
        reg.ports.update(b.ports)
        reg.colors.update(manifests[pid].ports)
        reg.update(b.blocks)
        for tid, t in b.templates.items():
            absent = _template_absent(t, alive)
            if absent:
                log(f"[paquetes] {pid}: la plantilla {tid} no se ofrece: nombra bloques de "
                    f"{', '.join(absent)}, que no está cargado")
            else:
                reg.templates[tid] = t
        reg.views.update(b.views)
        reg.actions.update(b.actions)
        reg.connectors.update(b.connectors)
    return reg


def _formerly_errors(bt, all_blocks):
    """Un id de antes (P59) no puede ser un tipo que existe ni el de antes de otro bloque: la
    migración no sabría a cuál llevarlo."""
    errs = []
    for old in bt.formerly:
        if old in all_blocks:
            errs.append(f"{bt.kind}: formerly {old!r} es un tipo de bloque que existe")
        elif any(old in o.formerly for k, o in all_blocks.items() if k != bt.kind):
            errs.append(f"{bt.kind}: formerly {old!r} lo declara también otro bloque")
    return errs


def _connector_errors(pid, bt, manifest, connectors):
    """El conector de un bloque (P41): el de su paquete o el de uno de su `[requires]`, y que
    ese paquete lo declare de verdad."""
    c = bt.connector
    if not c:
        return []
    if c != pid and c not in manifest.requires:
        return [f"{bt.kind}: usa el conector {c!r} sin declarar su paquete en [requires]"]
    if c not in connectors:
        return [f"{bt.kind}: el paquete {c!r} no declara ningún conector (pack.connector)"]
    return []


def validate(folder, find=None):
    """Validación estática de un paquete (§1): ver `pizarra.pack_validate`."""
    from pizarra import pack_validate
    return pack_validate.validate(folder, find)
