"""Propuestas del agente (docs/PLAN_PIZARRA.md §3, D20, D75): qué puede cambiar y qué hay ahora.

Cuando un agente quiere cambiar algo del usuario no lo toca: deja una propuesta
`{id, author, target, base_version, base, change, reason, sources, estimate, state, created}`
en `board/proposals.json`. `change` ⊂ {text, postitKind, params, delete}: contenido o borrado,
nunca posición, tamaño ni estilo. La propuesta de archivo (D176) es `change = {file: {nuevo,
diff}}` sobre una tarjeta de archivo: solo la deja `editar_archivo` (`agent_office_tools`), que
escribe antes la copia `nuevo`; `proponer_cambio` no la acepta (`FIELDS`), así el agente nunca
apunta una tarjeta a una ruta suya. `state` ∈ {pendiente, aceptada, rechazada}; «desfasada» no se
guarda: es una pendiente cuyo elemento ya no tiene lo que tenía al proponerla (`base`). Se mira
el contenido, no la versión: moverlo sube la versión y no es editarlo.

Funciones puras; el `Board` las usa y guarda.
"""
from pizarra.validation import POSTIT_KINDS, ValidationError

FIELDS = ("text", "postitKind", "params", "delete")


def _kind(element):
    cd = element.get("customData") or {}
    if cd.get("kind") in ("postit", "block"):
        return cd["kind"]
    return "text" if element.get("type") == "text" else None


def check_change(element, change, registry):
    """Valida un cambio propuesto sobre `element`. Devuelve el cambio normalizado."""
    if not isinstance(change, dict) or not change:
        raise ValidationError("el cambio está vacío: propone text, postitKind, params o delete")
    extra = set(change) - set(FIELDS)
    if extra:
        raise ValidationError(
            f"una propuesta solo cambia contenido o borra ({', '.join(FIELDS)}), nunca "
            f"{', '.join(sorted(extra))}: posición, tamaño y estilo son del ingeniero")
    kind = _kind(element)
    out = {}
    if "delete" in change:
        if change["delete"] is not True or len(change) > 1:
            raise ValidationError("un borrado se propone solo: {\"delete\": true}")
        return {"delete": True}
    if "text" in change:
        text = change["text"]
        if kind not in ("postit", "text"):
            raise ValidationError("el texto solo se propone en un post-it o un texto")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("el texto propuesto está vacío")
        out["text"] = text.strip()
    if "postitKind" in change:
        if kind != "postit":
            raise ValidationError("el tipo solo se propone en un post-it")
        if change["postitKind"] not in POSTIT_KINDS:
            raise ValidationError(f"tipo de post-it desconocido: {change['postitKind']!r}")
        out["postitKind"] = change["postitKind"]
    if "params" in change:
        params = change["params"]
        if kind != "block":
            raise ValidationError("los parámetros solo se proponen en un bloque")
        btype = registry.get(element["customData"]["blockType"])
        if not isinstance(params, dict) or not params:
            raise ValidationError("`params` tiene que ser un objeto con algún parámetro")
        unknown = set(params) - set(btype.params if btype else ())
        if unknown:
            raise ValidationError(f"el bloque no tiene esos parámetros: {', '.join(sorted(unknown))}")
        out["params"] = dict(params)
    return out


def content(element, state, change):
    """Lo que hay ahora en los campos que toca `change` (para `base` y para ver si está
    desfasada). `element` es None si ya no existe."""
    out = {}
    cd = (element or {}).get("customData") or {}
    for f in change:
        if f == "text":
            out["text"] = cd.get("text") if cd.get("kind") == "postit" else (element or {}).get("text")
        elif f == "postitKind":
            out["postitKind"] = cd.get("postitKind")
        elif f == "params":
            p = ((state.get(element["id"]) if element else None) or {}).get("params") or {}
            out["params"] = {k: p.get(k) for k in change["params"]}
        elif f == "delete":
            out["delete"] = element is None or bool(element.get("isDeleted"))
        elif f == "file":           # la ruta de la tarjeta: si el usuario la cambia, desfasada
            out["file"] = cd.get("path")
    return out


def apply(element, change):
    """El elemento con el contenido propuesto (sin parámetros: van al estado del bloque).
    Nunca toca posición, tamaño, estilo ni autor."""
    cd = dict(element.get("customData") or {})
    out = dict(element)
    if change.get("delete"):
        out["isDeleted"] = True
    if "text" in change:
        if cd.get("kind") == "postit":
            cd["text"] = change["text"]
        else:
            out["text"] = out["originalText"] = change["text"]
    if "postitKind" in change:
        cd["postitKind"] = change["postitKind"]
    out["customData"] = cd
    return out
