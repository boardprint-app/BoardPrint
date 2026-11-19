"""El registro de paquetes como datos, y lo que hace falta para ejecutar en cualquier proceso
(docs/PLAN_PAQUETES.md §4, P89-P91).

El trabajador (`boardprint_worker`) carga los paquetes y manda al backend `to_data(registro)`:
todo lo que el backend lee de los tipos de bloque, los puertos, las plantillas, las vistas, las
acciones y los conectores, sin funciones. El backend lo vuelve a armar con `from_data`, con los
mismos objetos del SDK y, en el sitio de cada función, `REMOTE`: quien la necesite la pide al
anfitrión del registro (`pizarra.pack_host`), que la manda al trabajador.

`run_step` es la ejecución de un bloque que hacen el proceso de cálculo (D92) y el trabajador:
nunca lanza, el error vuelve como resultado. Va con el trabajador como recurso: solo stdlib y
el SDK.
"""
import json
from dataclasses import asdict
from pathlib import Path

from boardprint_sdk.packs import (Action, BlockType, ConfirmRequired, Connector, Fix, Param,
                                  PortType, Pull, RunContext, Template, View)

DATA_VERSION = 1


class _Remote:
    """Una función de un paquete que no está en este proceso: corre en el trabajador."""

    def __call__(self, *args, **kwargs):
        raise RuntimeError("esta función de paquete corre en el trabajador: pídela al anfitrión "
                           "del registro (pizarra.pack_host)")

    def __repr__(self):
        return "REMOTE"


REMOTE = _Remote()


def _surface(value):
    return value if isinstance(value, str) else list(value)


def to_data(reg):
    """El registro `reg` (cargado en este proceso) como JSON."""
    return {
        "version": DATA_VERSION,
        "blocks": {k: {
            "title": b.title, "pack": b.pack, "description": b.description,
            "params": {n: [p.default, p.unit, p.label, list(p.choices), p.widget,
                           [list(x) for x in p.choice_labels]]
                       for n, p in b.params.items()},
            "inputs": dict(b.inputs), "outputs": dict(b.outputs), "requires": list(b.requires),
            "optional": list(b.optional), "connector": b.connector, "formerly": list(b.formerly),
            "preview": b.preview is not None,
            "pull": None if b.pull is None else {
                "classify": b.pull.classify is not None, "accept_port": b.pull.accept_port,
                "accept_param": b.pull.accept_param, "self_param": b.pull.self_param},
            "fix": None if b.fix is None else {"port": b.fix.port, "field": b.fix.field,
                                                "via": b.fix.via, "label": b.fix.label},
        } for k, b in reg.items()},
        "ports": {t: p.label for t, p in reg.ports.items()},
        "colors": dict(reg.colors),
        "templates": {t.id: {"title": t.title, "blocks": [list(x) for x in t.blocks],
                             "links": [list(x) for x in t.links],
                             "description": t.description, "pack": t.pack}
                      for t in reg.templates.values()},
        "views": {k: {"card": _surface(v.card), "panel": _surface(v.panel)}
                  for k, v in reg.views.items()},
        "actions": {n: {"description": a.description, "pack": a.pack}
                    for n, a in reg.actions.items()},
        "connectors": {c.id: {"title": c.title, "launch": c.launch is not None,
                              "open_file": c.open_file is not None, "accepts": list(c.accepts),
                              "gives": list(c.gives), "config": dict(c.config), "card": c.card,
                              "panel": c.panel, "pack": c.pack}
                       for c in reg.connectors.values()},
        "packs": [{**asdict(p), "dependencies": list(p.dependencies)} for p in reg.packs],
        "dirs": list(reg.dirs), "origins": [list(o) for o in reg.origins],
        "validated": reg.validated,
    }


def _view_surface(value):
    return value if isinstance(value, str) else tuple(value)


def from_data(data, registry_cls=None):
    """El registro que describe `data` (de `to_data`), con `REMOTE` en lugar de las funciones.
    `registry_cls`: la clase del registro (por defecto `pizarra.packs.Registry`)."""
    if registry_cls is None:
        from pizarra.packs import Registry as registry_cls
    from pizarra.packs import PackInfo
    if data.get("version") != DATA_VERSION:
        raise ValueError(f"el trabajador da el registro en la versión {data.get('version')!r} y "
                         f"el backend lee la {DATA_VERSION}")
    reg = registry_cls()
    reg.ports.update({t: PortType(t, label) for t, label in data["ports"].items()})
    reg.colors.update(data["colors"])
    for k, b in data["blocks"].items():
        pull = b["pull"]
        fix = b["fix"]
        reg[k] = BlockType(
            kind=k, title=b["title"], run=REMOTE, description=b["description"], pack=b["pack"],
            # v[5], las etiquetas de las opciones (D181), no la trae un trabajador de antes
            params={n: Param(v[0], v[1], v[2], tuple(v[3]), v[4],
                             tuple(tuple(x) for x in (v[5] if len(v) > 5 else ())))
                    for n, v in b["params"].items()},
            inputs=dict(b["inputs"]), outputs=dict(b["outputs"]), requires=tuple(b["requires"]),
            optional=tuple(b["optional"]), connector=b["connector"], formerly=tuple(b["formerly"]),
            preview=REMOTE if b["preview"] else None,
            pull=None if pull is None else Pull(classify=REMOTE if pull["classify"] else None,
                                                accept_port=pull["accept_port"],
                                                accept_param=pull["accept_param"],
                                                self_param=pull["self_param"]),
            fix=None if fix is None else Fix(**fix))
    for tid, t in data["templates"].items():
        reg.templates[tid] = Template(tid, t["title"], tuple(tuple(x) for x in t["blocks"]),
                                      tuple(tuple(x) for x in t["links"]), t["description"],
                                      t["pack"])
    for k, v in data["views"].items():
        reg.views[k] = View(card=_view_surface(v["card"]), panel=_view_surface(v["panel"]))
    for n, a in data["actions"].items():
        reg.actions[n] = Action(n, REMOTE, a["description"], a["pack"])
    for cid, c in data["connectors"].items():
        reg.connectors[cid] = Connector(
            cid, c["title"], available=REMOTE, launch=REMOTE if c["launch"] else None,
            open_file=REMOTE if c["open_file"] else None, accepts=tuple(c["accepts"]),
            gives=tuple(c["gives"]), config=dict(c["config"]), card=c["card"], panel=c["panel"],
            pack=c["pack"])
    reg.packs = [PackInfo(**{**p, "dependencies": tuple(p["dependencies"])}) for p in data["packs"]]
    reg.dirs = list(data["dirs"])
    reg.origins = [tuple(o) for o in data["origins"]]
    reg.validated = data["validated"]
    return reg


def context(block_id, env=None, workdir=None, options=None, progress=None):
    """El `RunContext` de un bloque con su entorno (`Board.run_env`: proyecto, registro de
    sincronización y conectores)."""
    env = env or {}
    return RunContext(block_id=block_id, workdir=Path(workdir) if workdir else None,
                      _progress=progress, options=dict(options or {}),
                      project_name=env.get("project_name", ""),
                      sync_file=Path(env["sync_file"]) if env.get("sync_file") else None,
                      connectors=dict(env.get("connectors") or {}))


def run_step(registry, step, progress=None):
    """Ejecuta un paso (`execution.Step` como dict) con el `run` de su tipo. Nunca lanza:
    `("ok", salidas)`, `("error", texto)` o, si pide confirmación (D112),
    `("error", texto, {"action", "label"})`."""
    btype = registry.get(step["kind"])
    if btype is None:
        return ("error", f"el tipo de bloque {step['kind']!r} no está cargado")
    ctx = context(step["block_id"], step.get("env"), step.get("workdir"), step.get("options"),
                  progress)
    try:
        return ("ok", btype.run(step["params"], step["inputs"], ctx))
    except ConfirmRequired as exc:
        return ("error", str(exc), {"action": exc.action, "label": exc.label})
    except Exception as exc:          # noqa: BLE001 el error se enseña en el bloque
        return ("error", f"{type(exc).__name__}: {exc}")


def as_json(value):
    """`value` tal como llega al otro lado: JSON sin ∞ ni NaN (lo que guarda el backend).
    `ValueError` o `TypeError` si no se puede."""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
