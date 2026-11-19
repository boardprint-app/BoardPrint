"""Unidades en pantalla (docs/PLAN_PIZARRA.md D40, D182).

Por dentro todo va en SI (mm, kg, N…) y nada cambia en disco por elegir otra unidad: la
interfaz convierte solo al pintar y al editar (`frontend/src/units.ts`, con los factores). Aquí
está lo que se puede elegir por magnitud, que se guarda en `workspace.toml` (`[unidades]`), y
los dos juegos de un clic. La interfaz tiene la misma lista: si cambia una, cambia la otra.
"""
from pizarra import i18n

UNITS = {
    "longitud": ("mm", "cm", "m", "in"),
    "masa": ("g", "kg", "lb"),
    "fuerza": ("N", "kN", "lbf"),
    "par": ("N·m", "N·mm", "lbf·in"),
    "angulo": ("°", "rad"),
}
SI = {"longitud": "mm", "masa": "kg", "fuerza": "N", "par": "N·m", "angulo": "°"}
IMPERIAL = {"longitud": "in", "masa": "lb", "fuerza": "lbf", "par": "lbf·in", "angulo": "°"}
PRESETS = {"si": SI, "imperial": IMPERIAL}


def clean(raw):
    """Las unidades de `workspace.toml` listas para usar: una magnitud que falta o con una
    unidad que no está en su lista vale la de SI (nunca impide abrir el workspace)."""
    raw = raw if isinstance(raw, dict) else {}
    return {m: raw[m] if raw.get(m) in choices else SI[m] for m, choices in UNITS.items()}


def validate(changes):
    """`{magnitud: unidad}` que se quiere guardar; ValueError con el motivo si algo no vale."""
    if not isinstance(changes, dict):
        raise ValueError(i18n.t("unidades.no_es_tabla"))
    for m, u in changes.items():
        if m not in UNITS:
            raise ValueError(i18n.t("unidades.magnitud_desconocida", magnitud=repr(m)))
        if u not in UNITS[m]:
            raise ValueError(i18n.t("unidades.no_disponible", magnitud=m, unidad=repr(u)))
    return dict(changes)
