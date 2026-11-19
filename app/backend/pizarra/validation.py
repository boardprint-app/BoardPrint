"""Reglas duras sobre lo que escribe un agente en la pizarra (D19, D20).

- Ningún número sin fuente: un texto con cifras exige `sources` no vacío o la marca
  explícita de estimación sin verificar. Una cuenta del agente se cita como "calculo" con su
  fórmula; las designaciones (6061-T6, M6) no cuentan como cifras (D51, D52).
- Un agente solo crea y edita elementos de autoría propia; para tocar lo del usuario tiene
  que dejar una propuesta.
"""
import math
import re

from pizarra import i18n
from pizarra.config import AGENT_AUTHORS, AUTHOR_USER
from pizarra.pasted import ANIMATION_MAX
from pizarra.scene import ANCHORED

POSTIT_KINDS = ("nota", "sugerencia", "riesgo", "pregunta")
POSTIT_STATES = ("abierto", "aceptado", "descartado")
# "calculo": una cuenta del propio agente sobre salidas de bloques, con la fórmula escrita (D52)
# "archivo": un archivo de la pizarra leído con `leer_archivo`, con su página o celda (R36)
SOURCE_KINDS = ("bloque", "ficha", "dato_vivo", "calculo", "archivo")

_DIGIT = re.compile(r"[\d²³¹¼-¾⁰-⁹₀-₉⅐-⅟]")

# Designaciones (D51): material, rosca, norma o protección no son cifras de diseño. Cuenta como
# designación una cifra pegada detrás de una mayúscula (M6, T6, IP67, S235JR, AW-6082, M6x20),
# la que va seguida de guion y mayúscula (6061-T6) y lo que sigue al código de una norma
# (ISO 9409-1, DIN 912, NEMA 17). Todo lo demás pide fuente, también con la unidad pegada
# (30mm, 120MPa), con Ø delante o suelto (6061). Precio aceptado: "R5" también pasa.
_STANDARDS = r"(?:ISO|DIN|EN|UNE|ASTM|IEC|NEMA|AISI|SAE|JIS|ANSI|ASME)"
_DESIGNATION = re.compile(
    rf"\b{_STANDARDS}\b(?:[ -]+[A-Z]{{1,3}}\b)*[ -]+\d[\w-]*"
    r"|\b\d+-(?=[A-Z])"
    r"|(?<!\w)[A-Z][^\W\d_]*-?\d[\w-]*")


class ValidationError(ValueError):
    """La escritura del agente se rechaza; el mensaje explica por qué."""


def check_param(name, spec, value):
    """Un valor para el parámetro `name` (un `Param` del SDK) tiene el tipo del de por defecto
    (PLAN_PAQUETES P49): número finito para un número, texto de la lista si la hay, objeto o
    lista para lo que es JSON. Uno que vale None por defecto es un número opcional (None o
    número), salvo con `widget`, que guarda lo que su control decida. Vale para todo lo que
    cambia parámetros (tarjeta, interfaz propia de un paquete, agente, *Traer*): la interfaz de
    un paquete no tiene por qué mandar lo que mandaría la tarjeta."""
    d = spec.default
    is_num = lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v))
    if d is None:
        ok = spec.widget or value is None or is_num(value)
        want = "parametro.numero_o_nada"
    elif isinstance(d, bool):
        ok, want = isinstance(value, bool), "parametro.si_o_no"
    elif isinstance(d, (int, float)):
        ok, want = is_num(value), "parametro.numero"
    elif isinstance(d, str):
        ok, want = isinstance(value, str), "parametro.texto"
        if ok and spec.choices and not spec.widget and value not in spec.choices:
            raise ValidationError(i18n.t("parametro.no_es_opcion", nombre=name, valor=repr(value),
                                         opciones=", ".join(spec.choices)))
    elif isinstance(d, dict):
        ok, want = isinstance(value, dict), "parametro.objeto"
    elif isinstance(d, list):
        ok, want = isinstance(value, list), "parametro.lista"
    else:
        ok, want = True, ""
    if not ok:
        raise ValidationError(i18n.t("parametro.tipo", nombre=name, tipo=i18n.t(want), valor=repr(value)))


def has_figures(text):
    """¿Lleva el texto alguna cifra que necesite fuente? Las designaciones no cuentan."""
    return bool(_DIGIT.search(_DESIGNATION.sub(" ", text or "")))


def check_source(src):
    if not isinstance(src, dict):
        raise ValidationError("cada fuente tiene que ser un objeto {kind, ref, ...}")
    kind = src.get("kind")
    if kind not in SOURCE_KINDS:
        raise ValidationError(f"fuente de tipo desconocido: {kind!r} (válidos: {SOURCE_KINDS})")
    if kind == "calculo":
        formula = src.get("formula")
        if not isinstance(formula, str) or not formula.strip():
            raise ValidationError("un cálculo del agente necesita 'formula': la cuenta escrita "
                                  "con sus valores, p. ej. 'L/500 = 600 mm / 500 = 1,2 mm'")
        inputs = src.get("inputs", [])
        if not isinstance(inputs, list) or not all(isinstance(r, str) for r in inputs):
            raise ValidationError("'inputs' de un cálculo es una lista de refs 'bloque:<id>'")
        return
    if not src.get("ref"):
        raise ValidationError(f"fuente {kind} sin 'ref'")
    if kind == "dato_vivo" and not (src.get("url") and src.get("date")):
        raise ValidationError("un dato vivo necesita 'url' y 'date'")
    if kind == "archivo":
        if not str(src["ref"]).startswith("archivo:"):
            raise ValidationError("la ref de un archivo es 'archivo:<id de su tarjeta>'")
        where = src.get("where")
        if not isinstance(where, str) or not where.strip():
            raise ValidationError("una fuente de archivo necesita 'where': la página, la "
                                  "diapositiva o la hoja y celda que da leer_archivo")


def validate_postit(postit):
    """Valida un post-it propuesto por un agente. Devuelve el post-it normalizado."""
    text = (postit.get("text") or "").strip()
    if not text:
        raise ValidationError("post-it vacío")
    kind = postit.get("kind", "nota")
    if kind not in POSTIT_KINDS:
        raise ValidationError(f"tipo de post-it desconocido: {kind!r} (válidos: {POSTIT_KINDS})")
    author = postit.get("author")
    if author not in AGENT_AUTHORS:
        raise ValidationError(f"autor de agente desconocido: {author!r}")
    sources = postit.get("sources") or []
    if not isinstance(sources, list):
        raise ValidationError("`sources` tiene que ser una lista")
    for src in sources:
        check_source(src)
    estimate = bool(postit.get("estimate"))
    if has_figures(text) and not sources and not estimate:
        raise ValidationError(
            "el texto contiene cifras y no lleva fuente: cita un bloque, una ficha o un dato "
            "vivo, o márcalo como estimación sin verificar")
    return {
        "text": text,
        "kind": kind,
        "state": "abierto",
        "author": author,
        "sources": sources,
        "estimate": estimate,
        "anchor": postit.get("anchor"),
    }


def check_animation(html):
    """La animación de un post-it del agente (D143, D175): un HTML no vacío de hasta
    `ANIMATION_MAX` bytes. Devuelve sus bytes (UTF-8), que se guardan tal cual."""
    if not isinstance(html, str) or not html.strip():
        raise ValidationError("`animacion` tiene que ser el HTML de la animación, en un texto")
    data = html.encode("utf-8")
    if len(data) > ANIMATION_MAX:
        raise ValidationError(
            f"la animación ocupa {len(data) / 1024:.0f} KB y el máximo es "
            f"{ANIMATION_MAX // 1024} KB: hazla más sencilla")
    return data


def element_author(element):
    return (element.get("customData") or {}).get("author", AUTHOR_USER)


def _content(e):
    """Lo que cuenta como contenido para la autoría (D72): texto, tipo e imagen de un post-it
    (D140), texto de un texto suelto. `None` en lo demás (moverlo o estirarlo nunca es
    contenido)."""
    cd = e.get("customData") or {}
    if cd.get("kind") == "postit":
        image = cd.get("image") if isinstance(cd.get("image"), dict) else {}
        return cd.get("text"), cd.get("postitKind"), image.get("file")
    if e.get("type") == "text":
        return e.get("text")
    return None


def client_authorship(prev, e, now):
    """Autor, origen, fecha y estado de un elemento que manda el cliente (D72, D73).

    `prev` es el elemento tal como estaba (None si es nuevo). El cliente nunca pone ni quita un
    autor de agente: un elemento nuevo con autor de agente (p. ej. pegado) es del usuario, con
    ese autor en `origin`; uno del agente cuyo contenido cambia pasa al usuario con `origin`;
    en lo demás autor y origen quedan como estaban. `author` y `created` de lo nuevo los pone
    la interfaz al crearlo; uno sin `author` es del usuario. Un post-it nuevo nace abierto y un
    estado desconocido no se guarda. Devuelve el `customData` corregido, o `None` si no hay
    nada que corregir."""
    cd = e.get("customData") or {}
    claimed = cd.get("author", AUTHOR_USER)
    out = dict(cd)
    if prev is None:
        if claimed in AGENT_AUTHORS:
            out["author"] = AUTHOR_USER
            out.setdefault("created", now)
        origin = claimed if claimed in AGENT_AUTHORS else cd.get("origin")
    else:
        pcd = prev.get("customData") or {}
        before = pcd.get("author", AUTHOR_USER)
        if before in AGENT_AUTHORS and _content(prev) != _content(e):
            author, origin = AUTHOR_USER, before
        else:
            author, origin = before, pcd.get("origin")
        if claimed != author:
            out["author"] = author
    if origin:
        out["origin"] = origin
    else:
        out.pop("origin", None)
    if cd.get("kind") == "postit":
        if prev is None:
            out["state"] = "abierto"
        elif out.get("state") not in POSTIT_STATES:
            out["state"] = (prev.get("customData") or {}).get("state", "abierto")
    return None if out == cd else out


def anchor_ok(postit_id, target, elements):
    """Se puede anclar el post-it o la foto `postit_id` a `target` (D74, D140): no es él mismo,
    `target` existe y no está borrado, y seguir los anclajes desde `target` no vuelve a él
    (ciclo)."""
    if target == postit_id:
        return False
    by_id = {e["id"]: e for e in elements}
    if target not in by_id or by_id[target].get("isDeleted"):
        return False
    seen, cur = set(), target
    while cur and cur not in seen:
        if cur == postit_id:
            return False
        seen.add(cur)
        cd = (by_id.get(cur) or {}).get("customData") or {}
        cur = cd.get("anchor") if cd.get("kind") in ANCHORED else None
    return True


def client_anchor(prev, e, elements):
    """Un anclaje nuevo que manda el cliente y no vale (a sí mismo, a algo que no existe o en
    ciclo) vuelve al que tenía (D74). Desanclar siempre vale, y un anclaje que ya tenía (aunque
    su elemento se haya borrado: «sin anclaje») no se toca. Devuelve el `customData` corregido,
    o `None`."""
    cd = e.get("customData") or {}
    if cd.get("kind") not in ANCHORED:
        return None
    new = cd.get("anchor")
    old = ((prev or {}).get("customData") or {}).get("anchor")
    if not new or new == old or anchor_ok(e["id"], new, elements):
        return None
    return {**cd, "anchor": old}


def check_agent_may_edit(agent, existing):
    """Un agente solo puede modificar o borrar elementos suyos.

    `existing` es el elemento tal como está en la escena (None si es nuevo).
    """
    if existing is None:
        return
    owner = element_author(existing)
    if owner != agent:
        raise ValidationError(
            f"el elemento {existing.get('id')} es de {owner!r}: {agent} no puede modificarlo, "
            "solo dejar una propuesta")


def check_agent_keeps_state(existing, element):
    """El estado de un post-it lo cambia solo el usuario, también en los del agente (D73)."""
    cd = element.get("customData") or {}
    if cd.get("kind") != "postit":
        return
    before = ((existing or {}).get("customData") or {}).get("state", "abierto")
    if cd.get("state", before) != before:
        raise ValidationError(
            "el estado de un post-it (aceptado, descartado) lo cambia solo el usuario")
