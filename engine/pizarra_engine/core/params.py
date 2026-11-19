"""Lectura y validación de params.toml (valores por defecto de una pieza).

params.toml es la semilla: define cada parámetro con su valor por defecto,
unidad, rango admisible y descripción. Los valores vivos están en la tabla
de parámetros de Fusion (Change Parameters); este módulo no depende de Fusion.
"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Unidades que se pasan tal cual a Fusion. Cualquier otra magnitud
# (N, MPa, kg/m3...) se guarda en Fusion sin unidad ("") y su unidad real
# va en `label`, porque Fusion solo convierte unidades geométricas.
FUSION_UNITS = {"mm", "deg", ""}


@dataclass
class Param:
    name: str
    value: float
    unit: str          # unidad de Fusion: "mm", "deg" o ""
    label: str         # unidad mostrada (N, MPa, kg/m3, mm...)
    min: float
    max: float
    desc: str
    group: str
    lock: bool = False   # True: el dimensionado automático no lo cambia
    formula: str = ""    # si no está vacía, el parámetro es derivado: Fusion recibe esta expresión

    @property
    def expression(self) -> str:
        if self.formula:
            return self.formula
        return f"{self.value:g} {self.unit}".strip()


@dataclass
class PartSpec:
    part: str
    component: str
    document: str
    params: dict  # name -> Param


def load(path: Path) -> PartSpec:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    meta = data["meta"]
    params = {}
    for name, d in data["params"].items():
        unit = d.get("unit", "")
        if unit not in FUSION_UNITS:
            raise ValueError(f"{name}: unidad de Fusion '{unit}' no soportada; usa {sorted(FUSION_UNITS)} y pon la real en 'label'")
        p = Param(name=name, value=float(d["value"]), unit=unit,
                  label=d.get("label", unit), min=float(d["min"]), max=float(d["max"]),
                  desc=d["desc"], group=d.get("group", "general"), lock=bool(d.get("lock", False)))
        if not (p.min <= p.value <= p.max):
            raise ValueError(f"{name}: valor por defecto {p.value} fuera de rango [{p.min}, {p.max}]")
        params[name] = p
    return PartSpec(part=meta["part"], component=meta["component"],
                    document=meta["document"], params=params)


def range_issues(spec: PartSpec, values: dict) -> list:
    """Parámetros cuyo valor vivo está fuera del rango declarado."""
    out = []
    for name, p in spec.params.items():
        v = values.get(name)
        if v is None:
            out.append(f"{name}: no existe en Fusion")
        elif not (p.min <= v <= p.max):
            out.append(f"{name} = {v:g} {p.label} fuera de [{p.min:g}, {p.max:g}]")
    return out
