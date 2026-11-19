"""Comparar dos escenas (docs/PLAN_PIZARRA.md §3, D76): qué se ha añadido, quitado o cambiado.

Función pura sobre los elementos y el estado de los bloques de cada lado. Cada cambio es
`{id, change, element, fields, moved, resized}`:
    change    added | removed | modified (contenido) | minor (solo movido o redimensionado)
    element   lo justo para nombrarlo y, si se quitó, pintar su fantasma: tipo, texto, tipo
              de post-it o de bloque, y su caja
    fields    en un `modified`, cada campo con [antes, después]; los parámetros, por nombre
Mover o redimensionar nunca es un cambio de contenido. El texto dentro de una forma va con
la forma y no sale suelto.
"""

GEOMETRY_POS = ("x", "y", "angle", "points")
GEOMETRY_SIZE = ("width", "height")


def _live(elements):
    return {e["id"]: e for e in elements if not e.get("isDeleted") and not e.get("containerId")}


def _kind(e):
    cd = e.get("customData") or {}
    if cd.get("kind") in ("postit", "block", "ink"):     # ink: un trazo de tinta, «Tinta» (D188)
        return cd["kind"]
    return e.get("type") if e.get("type") in ("text", "arrow", "line", "freedraw", "image") else "shape"


def _content(e, state):
    cd = e.get("customData") or {}
    kind = _kind(e)
    if kind == "postit":
        return {k: cd.get(k) for k in ("text", "postitKind", "state")}
    if kind == "block":
        return {"params": ((state or {}).get(e["id"]) or {}).get("params") or {}}
    if kind == "text":
        return {"text": e.get("text")}
    return {}


def _summary(e):
    cd = e.get("customData") or {}
    out = {"kind": _kind(e), "type": e.get("type"),
           **{k: e.get(k, 0) for k in ("x", "y", "width", "height")}}
    if out["kind"] == "postit":
        out.update(text=cd.get("text"), postitKind=cd.get("postitKind"))
    elif out["kind"] == "block":
        out["blockType"] = cd.get("blockType")
    elif out["kind"] == "text":
        out["text"] = e.get("text")
    return out


def _fields(a, b):
    out = {}
    for k in a.keys() | b.keys():
        va, vb = a.get(k), b.get(k)
        if k == "params":
            ch = {p: [va.get(p), vb.get(p)] for p in sorted(va.keys() | vb.keys())
                  if va.get(p) != vb.get(p)}
            if ch:
                out["params"] = ch
        elif va != vb:
            out[k] = [va, vb]
    return out


def diff(before, after, state_before=None, state_after=None):
    """Lista de cambios de `before` a `after`: añadidos, quitados, modificados y menores, en
    ese orden y, dentro de cada uno, en el orden de la escena."""
    b, a = _live(before), _live(after)
    out = {"added": [], "removed": [], "modified": [], "minor": []}
    for eid, e in a.items():
        if eid not in b:
            out["added"].append({"id": eid, "change": "added", "element": _summary(e)})
    for eid, e in b.items():
        if eid not in a:
            out["removed"].append({"id": eid, "change": "removed", "element": _summary(e)})
    for eid, e in a.items():
        old = b.get(eid)
        if old is None:
            continue
        fields = _fields(_content(old, state_before), _content(e, state_after))
        moved = any(old.get(k) != e.get(k) for k in GEOMETRY_POS)
        resized = any(old.get(k) != e.get(k) for k in GEOMETRY_SIZE)
        if fields:
            out["modified"].append({"id": eid, "change": "modified", "element": _summary(e),
                                    "fields": fields, "moved": moved, "resized": resized})
        elif moved or resized:
            out["minor"].append({"id": eid, "change": "minor", "element": _summary(e),
                                 "moved": moved, "resized": resized})
    return out["added"] + out["removed"] + out["modified"] + out["minor"]
