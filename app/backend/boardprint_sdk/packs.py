"""El lado app del SDK (docs/PLAN_PAQUETES.md §2, P22): lo que `register(pack)` y los bloques
de un paquete usan. Movido de `pizarra/packs.py` sin cambiar el contrato.

`register(pack)` recibe un `PackBuilder` y llama a `pack.port(...)`, `pack.block(...)`,
`pack.template(...)`; desde la 1.1, `pack.view(...)` y `pack.action(...)` (§5), y desde la 1.2
`pack.connector(...)` (§6). Todo lo que registra un paquete lleva su id delante
(`robotica.brazo`), así dos paquetes no se pueden pisar; su conector, si lo declara, se llama
como el paquete (`fusion`).

Contrato de un bloque: `run(params, inputs, ctx) -> {puerto_de_salida: carga}`, donde
`inputs` es `{puerto_de_entrada: carga}` y una carga son campos
`{nombre: {"value", "unit", "label"?}}`. `ctx` es un `RunContext`.

Solo stdlib: viaja al entorno de paquetes (P19) tal cual.
"""
import math
from dataclasses import dataclass, field
from pathlib import Path

from .library import Library

__all__ = ["Param", "ConfirmRequired", "Pull", "Fix", "PortType", "BlockType", "Template",
           "RunContext", "PackBuilder", "View", "Action", "Connector", "chart", "view2d", "box",
           "line", "point"]

# Controles genéricos (§5, P8) que pinta la app sin que el paquete programe interfaz.
# `chart` y `view2d` pintan los campos de salida hechos con `chart()` y `view2d()` (P52).
CONTROLS = ("params", "results", "chart", "view2d")
OWN_UI = "ui"         # la interfaz propia del paquete (`[ui] entry`, P24)
TONES = ("", "accent", "muted", "warn")   # cómo se pinta un elemento de una vista 2D


# Datos de los controles genéricos `chart` y `view2d` (§5, P52). Cada función da un campo de
# salida (`{"value", "unit", "label", "control"}`) que va en la carga de una salida como
# cualquier otro; *Resultados* nunca lo pinta: lo pinta el control que lo declara en
# `pack.view`. Un dato que no es un número finito es un ValueError: el bloque acaba en error
# con el motivo, nunca con un dibujo a medias.

def _num(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"{what}: {x!r} no es un número finito")
    return x


def _xy(p, what):
    try:
        px, py = p
    except (TypeError, ValueError):
        raise ValueError(f"{what}: {p!r} no es un punto (x, y)") from None
    return [_num(px, what), _num(py, what)]


def _axis(a, what):
    """`("Posición", "mm")` o solo el nombre."""
    if isinstance(a, str):
        return {"label": a, "unit": ""}
    try:
        label, unit = a
    except (TypeError, ValueError):
        raise ValueError(f"{what}: el eje es (nombre, unidad) o un nombre, no {a!r}") from None
    return {"label": str(label), "unit": str(unit)}


def _tone(tone, what):
    if tone not in TONES:
        raise ValueError(f"{what}: el tono {tone!r} no existe (hay {', '.join(map(repr, TONES))})")
    return tone


def chart(x, y, curves, label=""):
    """Campo con una gráfica x-y para el control `chart`. `x` e `y`: nombre y unidad de cada
    eje (`("Posición", "mm")`). `curves`: `{nombre: [(x, y), …]}`, al menos dos puntos cada
    una, en el orden en que se pintan. Todas comparten los ejes: dos magnitudes con unidades
    distintas son dos gráficas."""
    if not isinstance(curves, dict) or not curves:
        raise ValueError("chart: curves es {nombre: [(x, y), …]} con al menos una curva")
    out = []
    for name, pts in curves.items():
        what = f"chart, curva {name!r}"
        if isinstance(pts, (str, bytes, dict)):
            raise ValueError(f"{what}: los puntos son una lista de (x, y)")
        pts = [_xy(p, what) for p in pts]
        if len(pts) < 2:
            raise ValueError(f"{what}: hacen falta al menos dos puntos")
        out.append({"label": str(name), "points": pts})
    return {"value": {"x": _axis(x, "chart, x"), "y": _axis(y, "chart, y"), "curves": out},
            "unit": "", "label": label, "control": "chart"}


def box(x0, y0, x1, y1, label="", tone=""):
    """Una caja de una vista 2D (`view2d`), por dos esquinas opuestas."""
    a, b = _xy((x0, y0), "box"), _xy((x1, y1), "box")
    return {"box": [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])],
            "label": str(label), "tone": _tone(tone, "box")}


def line(points, label="", tone=""):
    """Una polilínea de una vista 2D, de al menos dos puntos."""
    if isinstance(points, (str, bytes, dict)):
        raise ValueError("line: los puntos son una lista de (x, y)")
    pts = [_xy(p, "line") for p in points]
    if len(pts) < 2:
        raise ValueError("line: hacen falta al menos dos puntos")
    return {"line": pts, "label": str(label), "tone": _tone(tone, "line")}


def point(x, y, label="", tone=""):
    """Un punto con nombre de una vista 2D."""
    return {"point": _xy((x, y), "point"), "label": str(label), "tone": _tone(tone, "point")}


_KINDS = ("box", "line", "point")


def view2d(x, y, items, label="", y_down=False):
    """Campo con una vista 2D a escala para el control `view2d`: cajas, líneas y puntos con
    nombre (`box`, `line`, `point`) en un plano. `x` e `y`, nombre y unidad de cada eje (la
    misma unidad: 1 en x mide lo mismo que 1 en y); `y_down`, el eje y hacia abajo (la vista
    lateral de una brida). Un elemento hecho a mano pasa la misma comprobación."""
    items = list(items)
    if not items:
        raise ValueError("view2d: sin elementos")
    out = []
    for it in items:
        kinds = [k for k in _KINDS if isinstance(it, dict) and k in it]
        if len(kinds) != 1:
            raise ValueError(f"view2d: {it!r} no es un box, line ni point")
        k = kinds[0]
        if k == "box":
            out.append(box(*_flat(it["box"], 4), it.get("label", ""), it.get("tone", "")))
        elif k == "line":
            out.append(line(it["line"], it.get("label", ""), it.get("tone", "")))
        else:
            out.append(point(*_flat(it["point"], 2), it.get("label", ""), it.get("tone", "")))
    return {"value": {"x": _axis(x, "view2d, x"), "y": _axis(y, "view2d, y"),
                      "y_down": bool(y_down), "items": out},
            "unit": "", "label": label, "control": "view2d"}


def _flat(v, n):
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise ValueError(f"view2d: {v!r} no son {n} números")
    return v

@dataclass(frozen=True)
class Param:
    default: object
    unit: str = ""
    label: str = ""
    choices: tuple = ()
    # Control especial en la tarjeta: uno de la app ("archivo_step") o "<paquete>.<x>", que pinta
    # la interfaz de ese paquete, el del bloque o su conector ("fusion.destino", D113, P41).
    widget: str = ""
    # Lo que enseña la interfaz de cada opción (D181, SDK 1.4.0): `((valor, etiqueta), …)`.
    # Más cómodo, `choices={valor: etiqueta}`, que se reparte aquí. Se guarda el valor.
    choice_labels: tuple = ()

    def __post_init__(self):
        if isinstance(self.choices, dict):
            object.__setattr__(self, "choice_labels",
                               tuple((str(v), str(l)) for v, l in self.choices.items()))
            object.__setattr__(self, "choices", tuple(self.choices))
        else:
            object.__setattr__(self, "choices", tuple(self.choices))
        labels = self.choice_labels.items() if isinstance(self.choice_labels, dict)             else self.choice_labels
        labels = tuple((v, l) for v, l in labels)
        stray = [v for v, _ in labels if v not in self.choices]
        if stray:
            raise ValueError(f"etiqueta para {stray[0]!r}, que no es una de las opciones")
        object.__setattr__(self, "choice_labels", labels)


class ConfirmRequired(Exception):
    """El bloque necesita que el usuario confirme algo antes de seguir (plan §7, D112): la
    ejecución acaba en error con su `action`, la tarjeta pinta un botón con `label` y pulsarlo
    lo relanza una vez con `ctx.options[action] = True`."""

    def __init__(self, message, action, label):
        super().__init__(message)
        self.action = action
        self.label = label


@dataclass(frozen=True)
class Pull:
    """Cómo trae un bloque de conector lo cambiado en su herramienta (plan §7, D116).

    - Qué parámetros no se pueden aceptar (p. ej. una cota de un componente comercial) lo
      guarda el bloque al enviar, en el registro (`fusion_sync.send(refuse=…)`): así vale
      aunque luego el bloque falle y pierda sus archivos. `classify(archivo)` es opcional y
      lo sustituye: recibe `archivo(nombre)` (un archivo de salida del bloque) y devuelve
      `por_que(parámetro)`, o None si se puede.
    - `accept_port`: la entrada cuyo bloque de delante recibe lo aceptado, en su parámetro
      `accept_param` ({parámetro: valor}, los candados).
    - `self_param` (D127, *Modelo de Fusion*): el documento es del ingeniero y lo decidido va
      al propio bloque, a ese parámetro ({nombre: expresión}, lo cambiado en la tarjeta):
      aceptar se queda con lo de Fusion, rechazar deja lo de la tarjeta. Sin post-it.
    - `accept(params, aceptados)` (T28 de docs/PLAN_TERMINALES.md): opcional, cómo entra lo
      aceptado (y lo fijado, `Fix`) en el bloque de `accept_port`. Recibe sus parámetros y
      {parámetro: valor}, y devuelve los parámetros que cambian ({nombre: valor nuevo}); un
      `ValueError` lo rechaza todo. Sin él, se añade a los candados de `accept_param`."""
    classify: object = None
    accept_port: str = ""
    accept_param: str = "locks"
    self_param: str = ""
    accept: object = None


@dataclass(frozen=True)
class Fix:
    """Una propuesta de candados que el bloque deja en sus salidas y la tarjeta ofrece fijar
    con un botón (D121: *Analizar en Fusion* y sus límites libres).

    - `port`, `field`: la salida y el campo con la propuesta, `{parámetro: valor}`.
    - `via`: la entrada por la que se llega al bloque que fija: el bloque de esa entrada trae de
      su herramienta (`Pull`), y lo fijado va, como lo aceptado al traer, al bloque de su
      `accept_port`, en su `accept_param`."""
    port: str
    field: str
    via: str
    label: str = "Fijar"


@dataclass(frozen=True)
class PortType:
    type: str
    label: str


@dataclass(frozen=True)
class View:
    """Qué pinta la tarjeta de un bloque y su panel lateral (§5, P7). Cada uno es `"ui"` (la
    interfaz propia del paquete, en un `iframe` aislado, P24) o una tupla de controles
    genéricos (`CONTROLS`). `panel` vacío: el bloque no abre panel."""
    card: object = ("params", "results")
    panel: object = ()


@dataclass(frozen=True)
class Action:
    """Lo que la interfaz propia de un paquete puede pedir a su lado de la app (§5, P40).
    `run(params, inputs, args, ctx) -> JSON`: los parámetros guardados del bloque desde cuya
    interfaz se llama, lo último que dio cada entrada, los `args` del mensaje y un
    `RunContext`. Solo la llama una interfaz del mismo paquete."""
    name: str
    run: object
    description: str = ""
    pack: str = ""


@dataclass(frozen=True)
class Connector:
    """Un programa externo con el que trabajan los bloques (§6, P38): Fusion, y mañana KiCad o
    Ansys. Se llama como su paquete y el núcleo solo lo registra, dice si está disponible y le
    pasa lo que le piden; lo demás (enviar, traer, diff) lo hacen sus bloques y sus acciones.

    - `available()`: ¿se puede usar ahora? Rápido y sin efectos (una conexión TCP, no una
      llamada): el núcleo lo pregunta a menudo y guarda la respuesta un par de segundos.
    - `launch()`: *Abrir* el programa, si se puede (devuelve `"abierto"` o `"arrancando"`).
    - `open_file(path)`: abrir en el programa un archivo con una extensión de `accepts`
      (`(".step", ".stp")`), desde su tarjeta de archivo.
    - `gives`: tipos de puerto que dan sus bloques (P42: `cad.modelo`), para la paleta.
    - `config`: lo que reciben sus bloques en `ctx.connectors[id]` (la URL de su servidor…);
      el núcleo añade `engine_dir`, el motor instalado.
    - `card`, `panel` (P41): la tarjeta y el panel de un bloque con `connector=` llevan, debajo
      de lo suyo, la interfaz propia de este paquete, en su propio `iframe`."""
    id: str
    title: str
    available: object
    launch: object = None
    open_file: object = None
    accepts: tuple = ()
    gives: tuple = ()
    config: dict = field(default_factory=dict)
    card: bool = False
    panel: bool = False
    pack: str = ""


@dataclass(frozen=True)
class BlockType:
    kind: str
    title: str
    params: dict          # nombre -> Param
    inputs: dict          # puerto -> tipo
    outputs: dict         # puerto -> tipo
    run: object           # (params, inputs, ctx) -> {puerto: carga}
    requires: tuple = ()  # conectores (D35): el id de su paquete ("fusion"), ...
    description: str = ""
    pack: str = ""
    pull: Pull | None = None   # cómo trae de su herramienta (D116); None: no trae
    # Entradas opcionales (D99, D122): el bloque se ejecuta sin ellas, y lo de delante de una
    # opcional nunca lo para ni lo deja incompleto; si está conectada y tiene resultado, entra.
    optional: tuple = ()
    fix: Fix | None = None     # propuesta de candados que la tarjeta ofrece fijar (D121)
    # Vista previa (PLAN_TERMINALES T26): `preview(params, inputs)` da lo que el editor del
    # bloque enseña con los parámetros que se están editando, sin ejecutarlo (el panel del
    # árbol de un terminal, lo que da la ficha de un robot). Corre en el servidor y tiene que
    # ser rápida y pura: nada de conectores ni archivos.
    preview: object = None
    # El conector con el que trabaja (P41): el id de un paquete que declara `pack.connector`,
    # el suyo o uno de su `[requires]`. Va también en `requires`: sin él disponible, el bloque
    # sale «no disponible».
    connector: str = ""
    # Los ids que tuvo antes (P59): un bloque guardado con uno de ellos se abre con este. Lo
    # declara el paquete, para que el núcleo no nombre ninguno.
    formerly: tuple = ()


@dataclass(frozen=True)
class Template:
    """Cadena de bloques ya conectada. `blocks`: [(clave, tipo, dx, dy[, parámetros])], con
    los parámetros que la plantilla pone en vez de los de por defecto; `links`:
    [(clave_origen, puerto_salida, clave_destino, puerto_entrada)]."""
    id: str
    title: str
    blocks: tuple
    links: tuple
    description: str = ""
    pack: str = ""



@dataclass
class RunContext:
    """Lo que un bloque recibe al ejecutarse además de parámetros y entradas."""
    block_id: str
    workdir: Path | None = None         # blocks/<id>/: los archivos de salida van aquí
    # Configuración de los conectores: {"cad": {"url", "engine_dir"}} (plan §7)
    connectors: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)   # de una confirmación, solo esta vez (D112)
    project_name: str = ""
    # Registro de sincronización del bloque con su herramienta (`sync/<bloque>.json`, §7). No
    # está en `workdir`: se escribe en cuanto la herramienta guarda, aunque el bloque falle.
    sync_file: Path | None = None
    _progress: object = None
    _cancelled: object = None
    # La librería del workspace (SDK 1.5, PLAN_V020 V15): `records(type)`, `load(key)`,
    # `stock(key)`. Sin workspace (los tests de un paquete), vacía.
    library: Library | None = None
    # La pizarra, para la API de P39 (abajo). La pone el núcleo en una acción (`pack.action`);
    # al ejecutar un bloque en su proceso aparte (D92) no hay pizarra y no está.
    _board: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.library is None:
            self.library = Library()

    def sync_file_of(self, block_id):
        """El registro de otro bloque del proyecto (p. ej. *Analizar* lee el de su *Construir*,
        D123): los registros de un proyecto están juntos, uno por bloque. Solo lectura."""
        if self.sync_file is None:
            return None
        if not isinstance(block_id, str) or not block_id or any(c in block_id for c in "/\\:."):
            raise ValueError(f"id de bloque no válido: {block_id!r}")
        return Path(self.sync_file).with_name(f"{block_id}.json")

    def progress(self, fraction=None, message=""):
        if self._progress:
            self._progress(fraction, message)

    def cancelled(self):
        return bool(self._cancelled and self._cancelled())

    # ---------------------------------- lo que un paquete hace en la pizarra (P39, SDK 1.2):
    # solo esto, nunca la escena entera. Solo en una acción.
    def _api(self):
        if self._board is None:
            raise RuntimeError("la pizarra solo está a mano en una acción (pack.action), no al "
                               "ejecutar un bloque")
        return self._board

    def block(self, block_id):
        """El estado de un bloque, en copia: `{id, type, params, outputs, status, error,
        busy}`; `status` como lo pinta la tarjeta (`al_dia`, `desactualizado`…) y `busy`, si
        hay una ejecución en curso en el proyecto. `None` si no existe."""
        return self._api().block(block_id)

    def upstream(self, block_id, port):
        """El id del bloque conectado a la entrada `port` de `block_id`, o `None`."""
        return self._api().upstream(block_id, port)

    def set_params(self, block_id, params):
        """Cambia parámetros (candados incluidos) de un bloque, con la validación de la
        tarjeta: un nombre que no es suyo se ignora y un valor de otro tipo es un `ValueError`
        sin guardar ninguno. Lo de detrás sale desactualizado, como al editar la tarjeta."""
        self._api().set_params(block_id, params)

    def postits(self, block_id):
        """Los post-its anclados a un bloque: `[{id, text, kind, state, keys}]`."""
        return self._api().postits(block_id)

    def add_postit(self, block_id, text, kind="nota", keys=()):
        """Un post-it anclado a `block_id`, junto a él y sin tapar nada, con el bloque como
        fuente de sus cifras (D51). `keys`, marcas del paquete para reconocerlo luego en
        `postits` (lo ya avisado). Devuelve su id; `ValueError` si el bloque no existe."""
        return self._api().add_postit(block_id, text, kind, keys)

    def clear_error(self, block_id, action):
        """Quita el error de un bloque si es el de la confirmación `action` (lo resuelto en el
        programa ya no lo para). Devuelve si lo quitó."""
        return self._api().clear_error(block_id, action)

    def block_file(self, block_id, name):
        """Un archivo de salida de un bloque (`blocks/<id>/<name>`), para leerlo."""
        return self._api().block_file(block_id, name)

    def block_type(self, block_id):
        """El tipo de un bloque (`BlockType`), aunque sea de otro paquete: cómo trae (`pull`),
        qué fija (`fix`)… Lo usa un conector que trabaja con los bloques de otros (P57). `None`
        si no existe."""
        return self._api().block_type(block_id)



class PackBuilder:
    """Lo que ve `register(pack)`: recoge lo que el paquete declara, sin tocar el registro."""

    def __init__(self, pack_id):
        self.id = pack_id
        self.ports = {}
        self.blocks = {}
        self.templates = {}
        self.views = {}       # {tipo de bloque: View}; sin `pack.view`, View() (§5)
        self.actions = {}
        self.connectors = {}  # {id: Connector}: como mucho uno, con el id del paquete
        self.errors = []

    def _own(self, name, what):
        if not isinstance(name, str) or not name.startswith(self.id + "."):
            self.errors.append(f"{what} {name!r} no empieza por {self.id + '.'!r}")
            return False
        return True

    def port(self, type_, label):
        if self._own(type_, "el tipo de puerto"):
            if type_ in self.ports:
                self.errors.append(f"el tipo de puerto {type_!r} está repetido")
            self.ports[type_] = PortType(type_, label)

    def block(self, kind, title, run, inputs=None, outputs=None, params=None, requires=(),
              description="", pull=None, optional=(), fix=None, preview=None, connector="",
              formerly=()):
        if not self._own(kind, "el tipo de bloque"):
            return
        if kind in self.blocks:
            self.errors.append(f"el tipo de bloque {kind!r} está repetido")
        if not callable(run):
            self.errors.append(f"{kind}: run no es una función")
        params = dict(params or {})
        for n, p in params.items():
            if not isinstance(p, Param):
                self.errors.append(f"{kind}: el parámetro {n!r} no es un Param")
        if pull is not None:
            if not isinstance(pull, Pull) or (pull.classify is not None and not callable(pull.classify)):
                self.errors.append(f"{kind}: pull tiene que ser un Pull (classify, si lo lleva, una función)")
            elif pull.accept_port and pull.accept_port not in (inputs or {}):
                self.errors.append(f"{kind}: pull.accept_port {pull.accept_port!r} no es una entrada")
        optional = (optional,) if isinstance(optional, str) else tuple(optional)
        for ip in optional:
            if ip not in (inputs or {}):
                self.errors.append(f"{kind}: la entrada opcional {ip!r} no es una entrada")
        if fix is not None and (not isinstance(fix, Fix) or fix.port not in (outputs or {})
                                or fix.via not in (inputs or {})):
            self.errors.append(f"{kind}: fix tiene que ser un Fix con una salida (port) y una "
                               "entrada (via) del bloque")
        if preview is not None and not callable(preview):
            self.errors.append(f"{kind}: preview no es una función")
        requires = tuple(requires)
        if not isinstance(connector, str):
            self.errors.append(f"{kind}: connector es el id del paquete del conector")
            connector = ""
        if connector and connector not in requires:
            requires += (connector,)
        for n, p in params.items():
            w = getattr(p, "widget", "") or ""
            if "." in w and w.split(".", 1)[0] not in {self.id, connector} - {""}:
                self.errors.append(f"{kind}: el control {w!r} de {n!r} no es de este paquete ni "
                                   "de su conector (connector=)")
        formerly = (formerly,) if isinstance(formerly, str) else tuple(formerly)
        for old in formerly:
            if not isinstance(old, str) or "." not in old or old == kind:
                self.errors.append(f"{kind}: formerly son los ids de antes del bloque "
                                   f"(«paquete.tipo»), no {old!r}")
        self.blocks[kind] = BlockType(kind=kind, title=title, params=params,
                                      inputs=dict(inputs or {}), outputs=dict(outputs or {}),
                                      run=run, requires=requires,
                                      description=description, pack=self.id, pull=pull,
                                      optional=optional, fix=fix, preview=preview,
                                      connector=connector, formerly=formerly)

    def template(self, id_, title, blocks, links, description=""):
        if self._own(id_, "la plantilla"):
            self.templates[id_] = Template(id=id_, title=title, blocks=tuple(map(tuple, blocks)),
                                           links=tuple(map(tuple, links)),
                                           description=description, pack=self.id)


    def _surface(self, kind, where, value):
        if value == OWN_UI:
            return OWN_UI
        if isinstance(value, str) or not isinstance(value, (tuple, list)):
            self.errors.append(f"{kind}: {where} tiene que ser \"ui\" o una lista de controles "
                               f"({', '.join(CONTROLS)})")
            return ()
        bad = [c for c in value if c not in CONTROLS]
        if bad:
            self.errors.append(f"{kind}: {where} lleva controles que no existen {bad} "
                               f"(hay {', '.join(CONTROLS)})")
        elif len(set(value)) != len(value):
            self.errors.append(f"{kind}: {where} repite un control")
        return tuple(value)

    def view(self, kind, card=View.card, panel=View.panel):
        """Qué pintan la tarjeta y el panel de `kind`, un bloque ya declarado de este paquete
        (§5). `"ui"` necesita `[ui] entry` en `pack.toml` (lo comprueba la carga)."""
        if kind not in self.blocks:
            self.errors.append(f"pack.view: {kind!r} no es un bloque de {self.id} declarado "
                               "antes con pack.block")
            return
        if kind in self.views:
            self.errors.append(f"pack.view: la vista de {kind!r} está repetida")
        self.views[kind] = View(card=self._surface(kind, "card", card),
                                panel=self._surface(kind, "panel", panel))

    def action(self, name, run, description=""):
        """Una acción que la interfaz propia del paquete llama con `action` (§5, P40):
        `run(params, inputs, args, ctx)` devuelve algo que se pueda pasar a JSON."""
        if not self._own(name, "la acción"):
            return
        if name in self.actions:
            self.errors.append(f"la acción {name!r} está repetida")
        if not callable(run):
            self.errors.append(f"{name}: run no es una función")
        self.actions[name] = Action(name=name, run=run, description=description, pack=self.id)

    def connector(self, title, available, launch=None, open_file=None, accepts=(), gives=(),
                  config=None, card=False, panel=False):
        """El conector de este paquete (§6, P38), con el id del paquete: los bloques lo piden
        con `pack.block(..., connector="<id>")`. `card`/`panel` necesitan `[ui] entry` (lo
        comprueba la carga); `gives`, tipos de puerto que alguien registre."""
        what = f"pack.connector de {self.id}"
        if self.connectors:
            self.errors.append(f"{what}: un paquete declara como mucho un conector")
        if not callable(available):
            self.errors.append(f"{what}: available no es una función")
        for name, fn in (("launch", launch), ("open_file", open_file)):
            if fn is not None and not callable(fn):
                self.errors.append(f"{what}: {name} no es una función")
        accepts = (accepts,) if isinstance(accepts, str) else tuple(accepts)
        if any(not isinstance(e, str) or not e.startswith(".") or e != e.lower() or len(e) < 2
               for e in accepts):
            self.errors.append(f"{what}: accepts son extensiones en minúsculas con su punto "
                               f"(\".step\"), no {list(accepts)}")
        if (open_file is None) != (not accepts):
            self.errors.append(f"{what}: open_file y accepts van juntos")
        gives = (gives,) if isinstance(gives, str) else tuple(gives)
        if not all(isinstance(g, str) and g for g in gives):
            self.errors.append(f"{what}: gives son tipos de puerto")
        if config is not None and not isinstance(config, dict):
            self.errors.append(f"{what}: config es un objeto")
        if not isinstance(card, bool) or not isinstance(panel, bool):
            self.errors.append(f"{what}: card y panel son True o False")
        self.connectors[self.id] = Connector(
            id=self.id, title=title, available=available, launch=launch, open_file=open_file,
            accepts=accepts, gives=gives, config=dict(config) if isinstance(config, dict) else {},
            card=card is True, panel=panel is True, pack=self.id)
