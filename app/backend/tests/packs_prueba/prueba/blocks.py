"""Paquete `prueba`: los bloques mínimos de los tests del núcleo (docs/PLAN_PUBLICACION.md §4.5).

Solo para los tests: no es un ejemplo ni sale en la app. Vive en `tests/` y no en `packs/`
porque el repo público no lleva paquetes, y las reglas del núcleo (grafo, desactualizado,
copiar, versiones, herramientas del agente...) necesitan algún tipo de bloque con puertos,
parámetros, controles genéricos y una plantilla. Son el Tubo y el Voladizo del spike (FF 3.1),
con las mismas cuentas y los mismos tres materiales (genéricos: orden de magnitud). Cada salida
numérica lleva su unidad; la fuente (`bloque:<id>`) la pone el backend al guardar (D19).

El Tubo enseña su vista lateral (`view2d`) y el Voladizo la flecha a lo largo del tubo
(`chart`), en la tarjeta y en su panel, con vista previa mientras se escribe la carga.
"""
import math
from collections import namedtuple

from boardprint_sdk.packs import Param, box, chart, view2d

# Los de `catalog.MATERIALS` del motor (genéricos: orden de magnitud), con lo que usa el Tubo.
Material = namedtuple("Material", "name E Sy rho")      # MPa, MPa, kg/m3
MATERIALS = {
    "al6061": Material("Aluminio 6061-T6", 68900, 276, 2700),
    "al7075": Material("Aluminio 7075-T6", 71700, 503, 2810),
    "s355": Material("Acero S355", 210000, 355, 7850),
}


def section_modulus(od, t):
    """Módulo resistente a flexión de un tubo redondo, mm³ (`robotarm.sizing`)."""
    d = max(od - 2 * t, 0)
    return math.pi * (od ** 4 - d ** 4) / (32 * od)


def second_moment(od, t):
    """Momento de inercia de la sección de un tubo redondo, mm⁴ (`robotarm.sizing`)."""
    d = max(od - 2 * t, 0)
    return math.pi * (od ** 4 - d ** 4) / 64


def _v(value, unit):
    return {"value": value, "unit": unit}


def _run_tubo(p, _inputs, _ctx):
    m = MATERIALS[p["material"]]
    od, t, L = float(p["od"]), float(p["t"]), float(p["L"])
    if not (0 < t < od / 2):
        raise ValueError(f"pared t = {t} mm imposible para Ø{od} mm")
    area = 3.141592653589793 * (od ** 2 - (od - 2 * t) ** 2) / 4          # mm²
    return {"tubo": {
        "material": _v(m.name, ""),
        "od": _v(od, "mm"), "t": _v(t, "mm"), "L": _v(L, "mm"),
        "masa": _v(round(m.rho * area * L * 1e-9, 4), "kg"),
        "W": _v(round(section_modulus(od, t), 1), "mm³"),
        "I": _v(round(second_moment(od, t), 1), "mm⁴"),
        "E": _v(m.E, "MPa"), "Sy": _v(m.Sy, "MPa"),
        "vista": view2d(("x", "mm"), ("y", "mm"), [
            box(0, -od / 2, L, od / 2, label=f"Ø{od:g} × {L:g}", tone="accent"),
            box(0, -od / 2 + t, L, od / 2 - t, label="hueco", tone="muted"),
        ], label="Vista lateral"),
    }}


def _run_voladizo(p, inputs, _ctx):
    tubo = inputs["tubo"]
    F = float(p["F"])
    L, W, I = tubo["L"]["value"], tubo["W"]["value"], tubo["I"]["value"]
    E, Sy = tubo["E"]["value"], tubo["Sy"]["value"]
    sigma = F * L / W                                   # MPa (N·mm / mm³)
    delta = F * L ** 3 / (3 * E * I)                    # mm
    # Elástica del voladizo con la carga en la punta: y(x) = F x² (3L − x) / (6 E I).
    xs = [L * i / 20 for i in range(21)]
    curve = [(round(x, 2), round(F * x ** 2 * (3 * L - x) / (6 * E * I), 4)) for x in xs]
    return {"voladizo": {
        "sigma": _v(round(sigma, 2), "MPa"),
        "flecha": _v(round(delta, 3), "mm"),
        "FS": _v(round(Sy / sigma, 2) if sigma else None, ""),
        "elastica": chart(("Posición", "mm"), ("Flecha", "mm"), {f"F = {F:g} N": curve},
                          label="Flecha a lo largo del tubo"),
    }}


def _preview_voladizo(p, inputs):
    # Lo mismo que la ejecución, sin guardar: el panel lo enseña mientras se escribe (T26).
    if "tubo" not in inputs:
        raise ValueError("conecta un Tubo ejecutado para ver la vista previa")
    return _run_voladizo(p, inputs, None)


def register(pack):
    pack.port("prueba.tubo", "tubo")
    pack.port("prueba.voladizo", "voladizo")
    pack.block(
        "prueba.tubo", "Tubo", _run_tubo,
        params={
            "material": Param("al6061", label="Material",
                              choices={k: m.name for k, m in MATERIALS.items()}),
            "od": Param(40, "mm", "Ø exterior"),
            "t": Param(3, "mm", "Pared"),
            "L": Param(300, "mm", "Largo"),
        },
        outputs={"tubo": "prueba.tubo"},
        description="Sección, masa y rigidez de un tubo")
    pack.block(
        "prueba.voladizo", "Voladizo", _run_voladizo,
        params={"F": Param(200, "N", "Carga en la punta")},
        inputs={"tubo": "prueba.tubo"}, outputs={"voladizo": "prueba.voladizo"},
        description="Tensión y flecha de un tubo en voladizo", preview=_preview_voladizo)
    # Controles genéricos (§5): lo de editar encima de Ejecutar, lo demás debajo y en orden.
    pack.view("prueba.tubo", card=["params", "view2d", "results"])
    pack.view("prueba.voladizo", card=["params", "chart", "results"],
              panel=["params", "chart", "results"])
    pack.template(
        "prueba.cadena", "Tubo y voladizo",
        blocks=[("t", "prueba.tubo", 0, 0), ("v", "prueba.voladizo", 360, 0)],
        links=[("t", "tubo", "v", "tubo")],
        description="La cadena del spike")
