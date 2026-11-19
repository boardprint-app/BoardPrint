"""{name}: {description}

Un paquete de BoardPrint (docs de la guía: herramienta `guia_paquetes`). `register(pack)`
declara puertos y bloques; cada bloque es `run(params, inputs, ctx) -> {puerto: {campo:
{"value", "unit", "label"?}}}`. Ningún número sin fuente: lo que sale de un bloque es su
fuente (D19).
"""
from boardprint_sdk.packs import Param


def area(params, inputs, ctx):
    """Ejemplo: el área de un rectángulo. Sustitúyelo por el cálculo del paquete."""
    a = params["ancho"] * params["alto"]
    return {"resultado": {"area": {"value": a, "unit": "mm²", "label": "Área"}}}


def register(pack):
    pack.port("{id}.resultado", "resultado")
    pack.block("{id}.ejemplo", "Ejemplo", area,
               params={"ancho": Param(10.0, "mm", "Ancho"), "alto": Param(5.0, "mm", "Alto")},
               outputs={"resultado": "{id}.resultado"},
               description="El área de un rectángulo (ejemplo de la plantilla)")
