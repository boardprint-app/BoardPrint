"""Bloque de prueba de la interfaz propia (PLAN_PAQUETES §5): pinta su página en la tarjeta y
en el panel, y su página llama a la acción `ui_prueba.eco`."""
from boardprint_sdk.packs import Param


def _run(p, _inputs, _ctx):
    return {"out": {"doble": {"value": 2 * p["a"], "unit": "mm"}}}


def _eco(params, inputs, args, ctx):
    """Devuelve lo que recibe: así se ve qué le llega a una acción."""
    if args.get("falla"):
        raise ValueError("me han pedido fallar")
    return {"block": ctx.block_id, "a": params["a"], "args": args, "inputs": sorted(inputs)}


def register(pack):
    pack.port("ui_prueba.t", "t")
    pack.block("ui_prueba.b", "Con interfaz", _run, params={"a": Param(1.0, "mm", "A")},
               outputs={"out": "ui_prueba.t"})
    pack.view("ui_prueba.b", card="ui", panel="ui")
    pack.action("ui_prueba.eco", _eco)
