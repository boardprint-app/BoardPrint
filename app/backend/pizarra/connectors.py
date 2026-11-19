"""Registro de conectores (docs/PLAN_PAQUETES.md §6, P38; plan D35, D106).

Un conector es un programa externo (Fusion, mañana KiCad o Ansys) que declara un paquete con
`pack.connector` (SDK 1.2, P56). El núcleo no sabe nada de ninguno: solo los registra, dice si
están disponibles, los lanza (*Abrir*), elige el que abre un archivo y les pasa su
configuración. Lo demás (enviar, traer, diff) lo hacen los bloques y las acciones del paquete.

Un bloque cuyo conector no está disponible sale `no_disponible` (atenuado, sin error) y no se
ejecuta. `available()` de cada conector es rápido, pero se pregunta a menudo (cada estado de
la pizarra): la respuesta vale `TTL` segundos. Tras *Abrir*, el conector sale «arrancando»
hasta que está disponible o pasan `LAUNCH_WAIT` segundos.

El registro es el de los paquetes cargados (`pizarra.blocks.REGISTRY`) salvo que se pase otro.
"""
import time

from pizarra import i18n

TTL = 2.0                     # s que vale una comprobación
LAUNCH_WAIT = 240             # s que se espera a un programa tras pedir abrirlo

_cache = {"at": -1e9, "value": frozenset(), "registry": None}
_launch = {}                  # id -> cuándo se pidió abrirlo
_engine = {"dir": None}


def _reg(registry):
    if registry is not None:
        return registry
    from pizarra import blocks
    return blocks.REGISTRY


def _up(reg, connector):
    """Un `available()` que falla es un conector no disponible, nunca una app caída. Lo
    contesta el anfitrión del registro: en la app, el trabajador (PLAN_PAQUETES P89). Si está
    ocupado con otra petición, `HostBusy` sale: no se sabe, que no es «no disponible»."""
    from pizarra.pack_host import HostBusy
    try:
        return bool(reg.host.connector(connector.id, "available"))
    except HostBusy:
        raise
    except Exception:         # noqa: BLE001 el conector de un paquete no tumba la app
        return False


def available(registry=None, ttl=TTL):
    """Conectores disponibles ahora mismo, como `frozenset` de ids. Con el trabajador ocupado,
    lo último que se supo (se vuelve a preguntar en la siguiente llamada): esto se llama desde
    el bucle del servidor y nunca espera."""
    from pizarra.pack_host import HostBusy
    reg = _reg(registry)
    now = time.monotonic()
    if now - _cache["at"] >= ttl or _cache["registry"] is not reg:
        try:
            value = frozenset(c.id for c in reg.connectors.values() if _up(reg, c))
        except HostBusy:
            return _cache["value"]
        _cache.update(value=value, at=now, registry=reg)
        for cid in _cache["value"]:
            _launch.pop(cid, None)
    return _cache["value"]


def configure(engine_dir):
    """La ruta del motor instalado, que el código de un paquete importa en su programa
    (Fusion: plan R1, R3)."""
    _engine["dir"] = str(engine_dir) if engine_dir else None


def config(registry=None):
    """Lo que reciben los bloques y las acciones en `ctx.connectors`: por conector, su
    `config` más `engine_dir` y `packs` ({id: carpeta} de los paquetes cargados, para que su
    programa los importe como `pizarra_packs.<id>`, §6)."""
    reg = _reg(registry)
    loaded = {p.id: p.path for p in reg.packs if p.error is None}
    return {c.id: {**c.config, "engine_dir": _engine["dir"], "packs": dict(loaded)}
            for c in reg.connectors.values()}


def status(registry=None):
    """Para la interfaz: `{id: {name, available, launching}}`."""
    reg = _reg(registry)
    up = available(reg)
    now = time.monotonic()
    return {c.id: {"name": c.title, "available": c.id in up,
                   "launching": (c.id not in up and c.id in _launch
                                 and now - _launch[c.id] < LAUNCH_WAIT)}
            for c in reg.connectors.values()}


def launch(cid, registry=None):
    """*Abrir* el programa del conector `cid`: lo que diga su `launch()` («abierto» o
    «arrancando»). `KeyError` si no hay ese conector, `ValueError` si no se puede abrir desde
    la app; lo que lance su `launch()` (`FileNotFoundError` si no está instalado) pasa tal cual."""
    reg = _reg(registry)
    c = reg.connectors[cid]
    if c.launch is None:
        raise ValueError(i18n.t("conector.no_se_abre", nombre=c.title))
    r = reg.host.connector(cid, "launch")
    if r != "abierto":
        _launch[cid] = time.monotonic()
        _cache["at"] = -1e9
    return r


def open_file(cid, path, registry=None):
    """Abre `path` en el programa del conector `cid` (su `open_file`, por el anfitrión)."""
    return _reg(registry).host.connector(cid, "open_file", str(path))


def opener(path, registry=None):
    """El conector disponible que abre `path` por su extensión (`accepts`), o None."""
    reg = _reg(registry)
    ext = str(path).lower()
    up = available(reg)
    for c in sorted(reg.connectors.values(), key=lambda c: c.id):
        if c.open_file is not None and c.id in up and any(ext.endswith(e) for e in c.accepts):
            return c
    return None
