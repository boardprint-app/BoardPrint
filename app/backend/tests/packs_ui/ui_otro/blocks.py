"""Otro paquete con una acción: la interfaz de `ui_prueba` nunca la alcanza (PLAN_PAQUETES §10)."""


def _secreto(params, inputs, args, ctx):
    return {"secreto": True}


def register(pack):
    pack.action("ui_otro.secreto", _secreto)
