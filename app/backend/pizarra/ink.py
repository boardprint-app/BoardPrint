"""La tinta (docs/PLAN_PIZARRA.md §3, D188, D192-D194): un trazo de tinta es un `freedraw` de
la escena con `customData = {kind: "ink", ink: {brush, size, opacity, shape?}, author, created,
anchor?}` y `opacity 0`: Excalidraw lo guarda y lo deshace, y lo pinta la capa de la app,
encima de las tarjetas (frontend/src/ink.ts hace lo mismo en la interfaz).

Funciones puras sobre los elementos:
- `normalized`: la regla de la opacidad (D188), al recibir del cliente.
- `pointing` y `describe`: a qué apunta cada trazo (D193), calculado cada vez que se lee con
  las cajas de la escena del momento; nunca da un id que no esté en ella.
- `mark_element`: la marca del agente (`marcar`, D194), con los puntos alrededor de la caja
  del objetivo y una irregularidad de mano determinista (misma entrada, mismos puntos).
"""
import math
import random
import re
import zlib

from pizarra import scene
from pizarra.validation import ValidationError

BRUSHES = ("rotulador", "pluma", "subrayador")
SHAPES = ("recta", "flecha", "círculo", "elipse", "rectángulo", "triángulo")
CLOSED_SHAPES = ("círculo", "elipse", "rectángulo", "triángulo")
# Las tarjetas que pinta la app encima del lienzo (las de `CARD_KINDS` de ink.ts).
CARD_KINDS = ("postit", "block", "file", "folder", "image", "link")
# Formas de Excalidraw que también se pueden marcar (las flechas de conexión y la tinta, no).
SHAPE_TYPES = ("rectangle", "ellipse", "diamond", "image", "line", "arrow", "freedraw")
# Los colores del menú de Tinta (D189) por su nombre; otro color sale con su hex.
COLOR_NAMES = {"#1e1e1e": "negro", "#e03131": "rojo", "#1971c2": "azul", "#2f9e44": "verde",
               "#fab005": "amarillo"}
COLORS = {v: k for k, v in COLOR_NAMES.items()}

CLOSED_GAP = 0.2        # cerrado: extremos a menos del 20 % del tamaño (shapes.ts)
AROUND = 0.6            # rodea: la caja del objetivo, dentro de la del trazo en un 60 % o más
UNDER_PX = 24           # subraya: la recta, a menos de 24 px por debajo del borde inferior
BOTTOM_BAND = 0.2       # ... o dentro del 20 % de abajo de la caja (la letra baja)
STRIKE_SPAN = 0.6       # tacha: la recta cruza el 60 % del ancho, por la parte de en medio
ARROW_PX = 16           # la punta o la cola de una flecha, a menos de esto de la caja

MARKS = ("rodear", "subrayar", "resaltar", "flecha", "tachar")
MARGIN = 12             # lo que se aparta la marca del agente de la caja del objetivo
AGENT_SIZE = 4


def is_ink(e):
    return (e.get("customData") or {}).get("kind") == "ink"


def ink_data(e):
    """Los datos de tinta de un elemento con lo que falte o no valga por defecto, como `inkData`
    de ink.ts (None si no es tinta)."""
    if not is_ink(e):
        return None
    raw = (e.get("customData") or {}).get("ink")
    raw = raw if isinstance(raw, dict) else {}
    size, opacity = raw.get("size"), raw.get("opacity")
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    out = {"brush": raw.get("brush") if raw.get("brush") in BRUSHES else "rotulador",
           "size": min(size, 200) if num(size) and size > 0 else 4,
           "opacity": min(1, max(0.05, opacity)) if num(opacity) else 1}
    if raw.get("shape") in SHAPES:
        out["shape"] = raw["shape"]
    return out


def normalized(e):
    """Un trazo de tinta siempre va con `opacity 0` (D188): si llega con otra (0-100, la del
    panel de Excalidraw), pasa a `customData.ink.opacity` (0-1) y el elemento vuelve a 0. Lo
    que no es tinta (el lápiz de Excalidraw también) o ya está bien sale igual, el mismo
    objeto: normalizar dos veces da lo mismo."""
    op = e.get("opacity")
    if not is_ink(e) or not op:
        return e
    cd = e.get("customData") or {}
    raw = cd.get("ink") if isinstance(cd.get("ink"), dict) else {}
    value = min(1, op / 100) if isinstance(op, (int, float)) and math.isfinite(op) else 1
    return {**e, "opacity": 0, "customData": {**cd, "ink": {**raw, "opacity": value}}}


def is_target(e):
    """¿Puede la tinta apuntar a este elemento? Tarjetas, textos sueltos y formas de Excalidraw;
    nunca algo borrado, otra tinta, una flecha de conexión ni el texto dentro de una forma."""
    if e.get("isDeleted") or e.get("containerId") or "x" not in e:
        return False
    kind = (e.get("customData") or {}).get("kind")
    if kind in CARD_KINDS:
        return True
    if kind in ("ink", "connection"):
        return False
    return e.get("type") == "text" or e.get("type") in SHAPE_TYPES


def _cut(text, n=60):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def name(e, registry=None):
    """Cómo se nombra el elemento al que apunta un trazo: bloque con su título, post-it y texto
    con lo que dicen, tarjeta con su archivo."""
    cd = e.get("customData") or {}
    kind = cd.get("kind")
    if kind == "block":
        btype = registry.get(cd.get("blockType")) if registry is not None else None
        return f"bloque {btype.title if btype is not None else cd.get('blockType')}"
    if kind == "postit":
        return f"post-it «{_cut(cd.get('text'))}»" if cd.get("text") else "post-it"
    if kind in ("file", "folder"):
        path = str(cd.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1]
        return f"{'carpeta' if kind == 'folder' else 'archivo'} {path}".strip()
    if kind == "image":
        return "imagen"
    if kind == "link":
        return f"enlace {cd.get('url') or ''}".strip()
    if e.get("type") == "text":
        return f"texto «{_cut(e.get('text'))}»"
    return f"forma ({e.get('type')})"


def color_name(color):
    c = str(color or "").lower()
    return COLOR_NAMES.get(c, color)


# ------------------------------------------------------------------ geometría
def points_of(e):
    """Los puntos del trazo en la escena."""
    return [(e["x"] + p[0], e["y"] + p[1]) for p in e.get("points") or []
            if isinstance(p, (list, tuple)) and len(p) >= 2]


def _bounds(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def is_closed(pts):
    """Cerrado si los extremos quedan a menos del 20 % de su tamaño (`isClosed` de shapes.ts)."""
    if len(pts) < 3:
        return False
    x0, y0, x1, y1 = _bounds(pts)
    size = max(x1 - x0, y1 - y0)
    return size > 0 and math.dist(pts[0], pts[-1]) < CLOSED_GAP * size


def _inside_frac(a, b):
    """Fracción de la caja `a` que queda dentro de `b` (una caja plana cuenta por su largo)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w < 0 or h < 0:
        return 0.0
    aw, ah = a[2] - a[0], a[3] - a[1]
    if aw > 0 and ah > 0:
        return (w * h) / (aw * ah)
    span, inner = (aw, w) if aw > 0 else (ah, h)
    return inner / span if span > 0 else 1.0


def _point_box(p, b):
    dx = max(b[0] - p[0], 0, p[0] - b[2])
    dy = max(b[1] - p[1], 0, p[1] - b[3])
    return math.hypot(dx, dy)


def _point_seg(p, a, b):
    abx, aby = b[0] - a[0], b[1] - a[1]
    l2 = abx * abx + aby * aby
    t = 0 if not l2 else min(1, max(0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / l2))
    return math.dist(p, (a[0] + abx * t, a[1] + aby * t))


def _clip(a, b, box):
    """El tramo (t0, t1) del segmento a-b dentro de la caja (Liang-Barsky), o None."""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - box[0]), (dx, box[2] - a[0]), (-dy, a[1] - box[1]),
                 (dy, box[3] - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return t0, t1


def _seg_box(a, b, box):
    """Distancia del segmento a-b a la caja (0 si la cruza o la toca)."""
    if _clip(a, b, box) is not None:
        return 0.0
    corners = ((box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3]))
    return min([_point_box(a, box), _point_box(b, box)] + [_point_seg(c, a, b) for c in corners])


def _stroke_box(pts, box):
    if len(pts) == 1:
        return _point_box(pts[0], box)
    return min(_seg_box(pts[i], pts[i + 1], box) for i in range(len(pts) - 1))


# ------------------------------------------------------------------ a qué apunta
def _targets(e, elements):
    """Los objetivos posibles, de arriba abajo (lo último de la escena se pinta encima)."""
    return [(t, scene.bbox(t)) for t in reversed(elements)
            if t.get("id") != e.get("id") and is_target(t)]


def _at(p, targets, tol=ARROW_PX):
    """El objetivo más cercano a `p` a menos de `tol` (a igualdad, el de más arriba)."""
    best = None
    for t, box in targets:
        d = _point_box(p, box)
        if d <= tol and (best is None or d < best[0]):
            best = (d, t)
    return None if best is None else best[1]


def _touched(pts, targets, tol, relation):
    return [(t, relation) for t, box in targets if _stroke_box(pts, box) <= tol]


def _line(a, b, targets):
    """Lo que subraya o tacha una recta. Casi horizontal: subraya lo que tiene justo encima
    (su borde inferior a menos de `UNDER_PX`, o la recta en la franja de abajo de la caja) y
    tacha lo que cruza por en medio en buena parte de su ancho; si la cruza poco, lo toca. Muy
    inclinada: tacha lo que cruza."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    out = []
    if abs(dx) < 2 * abs(dy):
        return [(t, "tacha") for t, box in targets if _clip(a, b, box) is not None]
    lx0, lx1 = min(a[0], b[0]), max(a[0], b[0])
    for t, (x0, y0, x1, y1) in targets:
        ov = min(lx1, x1) - max(lx0, x0)
        if ov <= 0:
            continue
        xm = (max(lx0, x0) + min(lx1, x1)) / 2
        ly = a[1] + dy * ((xm - a[0]) / dx) if dx else a[1]
        h = y1 - y0
        if y1 - BOTTOM_BAND * h <= ly < y1 + UNDER_PX:
            if ov >= 0.3 * min(lx1 - lx0, x1 - x0):
                out.append((t, "subraya"))
        elif y0 < ly < y1 - BOTTOM_BAND * h:
            out.append((t, "tacha" if ov >= STRIKE_SPAN * (x1 - x0) else "toca"))
    return out


def pointing(e, elements):
    """A qué apunta el trazo `e` en la escena `elements` (D193). Devuelve `(apunta, desde)`:
    `apunta`, `[(elemento, relación)]`, con la relación rodea, señala, subraya, tacha, resalta
    o toca; `desde`, el elemento de la cola de una flecha (o None). Solo objetivos vivos de la
    escena (`is_target`)."""
    data = ink_data(e) or {"brush": "rotulador", "size": 4}
    pts = points_of(e)
    if not pts:
        return [], None
    targets = _targets(e, elements)
    shape = data.get("shape")
    if shape == "flecha":
        tip = pts[1] if len(pts) > 1 else pts[-1]
        head = _at(tip, targets)
        tail = _at(pts[0], targets)
        if tail is not None and head is not None and tail["id"] == head["id"]:
            tail = None
        return ([(head, "señala")] if head is not None else []), tail
    if shape in CLOSED_SHAPES or (shape is None and is_closed(pts)):
        box = _bounds(pts)
        around = [(t, "rodea") for t, b in targets if _inside_frac(b, box) >= AROUND]
        if around:
            return around, None
    if data["brush"] == "subrayador":
        return _touched(pts, targets, 1.5 * data["size"], "resalta"), None
    if shape == "recta" and len(pts) > 1:
        return _line(pts[0], pts[-1], targets), None
    return _touched(pts, targets, max(data["size"] / 2, 2), "toca"), None


def describe_stroke(e, elements, registry=None):
    """El trazo tal como lo lee el agente (`leer_pizarra`, los hilos): forma, pincel, color por
    su nombre, autor y a qué apunta, con su id, su nombre y la relación; la flecha, también de
    dónde sale."""
    data = ink_data(e) or {"brush": "rotulador"}
    cd = e.get("customData") or {}
    apunta, desde = pointing(e, elements)
    out = {"id": e["id"], "forma": data.get("shape") or "a mano", "pincel": data["brush"],
           "color": color_name(e.get("strokeColor")), "autor": cd.get("author", "user"),
           "apunta": [{"id": t["id"], "nombre": name(t, registry), "relacion": rel}
                      for t, rel in apunta]}
    if data.get("shape") == "flecha":
        out["desde"] = None if desde is None else {"id": desde["id"], "nombre": name(desde, registry)}
    return out


def describe(elements, registry=None):
    """Todos los trazos de tinta vivos de la escena, con `describe_stroke`."""
    return [describe_stroke(e, elements, registry) for e in elements
            if is_ink(e) and not e.get("isDeleted")]


# ------------------------------------------------------------------ marcas del agente
def _color(marca, color):
    if color is None or color == "":
        return COLORS["amarillo" if marca == "resaltar" else "rojo"]
    c = str(color).strip().lower()
    if c in COLORS:
        return COLORS[c]
    if re.fullmatch(r"#[0-9a-f]{6}", c):
        return c
    raise ValidationError(f"color desconocido: {color!r}; usa {', '.join(COLORS)} o un "
                          "hex «#rrggbb»")


def _wobble(rng):
    """Una irregularidad suave de -1 a 1 a lo largo del trazo (t de 0 a 1)."""
    k1, k2 = rng.choice((1, 2)), rng.choice((3, 4))
    f1, f2 = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    return lambda t: 0.6 * math.sin(2 * math.pi * k1 * t + f1) + 0.4 * math.sin(2 * math.pi * k2 * t + f2)


def _stroke(a, b, rng, n=10, amp=1.0, ends=2.0):
    """Una recta a mano de `a` a `b`: los extremos un poco movidos en vertical y un temblor."""
    w = _wobble(rng)
    ja, jb = rng.uniform(-ends, ends), rng.uniform(-ends, ends)
    return [(a[0] + (b[0] - a[0]) * i / n,
             a[1] + (b[1] - a[1]) * i / n + ja + (jb - ja) * i / n + amp * w(i / n))
            for i in range(n + 1)]


def _around(box, rng, n=48):
    """Una elipse a mano que deja la caja dentro con `MARGIN` (semiejes w/√2, h/√2, los de la
    elipse más pequeña que contiene la caja, más el margen) y se pasa un poco al cerrar."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    a = (x1 - x0) / math.sqrt(2) + MARGIN
    b = (y1 - y0) / math.sqrt(2) + MARGIN
    start, sweep, w = rng.uniform(0, 2 * math.pi), 2 * math.pi * 1.08, _wobble(rng)
    out = []
    for i in range(n + 1):
        t = i / n
        k = 1 + 0.025 * (1 + w(t)) + 0.03 * t          # solo hacia fuera: nunca entra en la caja
        ang = start + sweep * t
        out.append((cx + a * k * math.cos(ang), cy + b * k * math.sin(ang)))
    return out


_DIRS = [(-1, -1), (1, -1), (-1, 1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)]


def _arrow(target, box, targets, rng, length=110, gap=4, barb=18):
    """Una flecha que llega a la caja desde fuera: la cola en la primera dirección que no cae
    sobre otro elemento (de arriba a la izquierda en adelante)."""
    x0, y0, x1, y1 = box
    cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    others = [b for t, b in targets if t["id"] != target["id"]]
    pick = None
    for dx, dy in _DIRS:
        n = math.hypot(dx, dy)
        d = (dx / n, dy / n)
        t = min(hw / abs(d[0]) if d[0] else math.inf, hh / abs(d[1]) if d[1] else math.inf)
        tip = (cx + d[0] * (t + gap), cy + d[1] * (t + gap))
        tail = (tip[0] + d[0] * length, tip[1] + d[1] * length)
        pick = pick or (d, tip, tail)
        if all(_point_box(tail, b) > 2 * ARROW_PX for b in others):
            pick = (d, tip, tail)
            break
    d, tip, tail = pick
    tail = (tail[0] + rng.uniform(-3, 3), tail[1] + rng.uniform(-3, 3))
    ang = math.radians(28)

    def side(s):
        c, sn = math.cos(ang), s * math.sin(ang)
        return (tip[0] + barb * (d[0] * c - d[1] * sn), tip[1] + barb * (d[1] * c + d[0] * sn))
    return [tail, tip, side(1), tip, side(-1)]


def mark_element(target, marca, elements, author, color=None):
    """La marca `marca` del agente sobre `target` (D194), como trazo de tinta suyo y anclado al
    objetivo: rodear con una elipse, subrayar o tachar con una recta, flecha que llega desde
    fuera y resaltar con el subrayador por en medio. Los puntos salen de la caja del objetivo
    con una irregularidad que solo depende de su id, la marca y la caja."""
    if marca not in MARKS:
        raise ValidationError(f"marca desconocida: {marca!r} (válidas: {', '.join(MARKS)})")
    color = _color(marca, color)
    box = scene.bbox(target)
    x0, y0, x1, y1 = box
    seed = zlib.crc32(f"{target['id']}|{marca}|{[round(v, 2) for v in box]}".encode("utf-8"))
    rng = random.Random(seed)
    cy = (y0 + y1) / 2
    brush, size, shape = "rotulador", AGENT_SIZE, None
    if marca == "rodear":
        pts, shape = _around(box, rng), "elipse"
    elif marca == "subrayar":
        pts, shape = _stroke((x0 - 4, y1 + 10), (x1 + 4, y1 + 10), rng), "recta"
    elif marca == "tachar":
        pts, shape = _stroke((x0 - 8, cy), (x1 + 8, cy), rng), "recta"
    elif marca == "flecha":
        pts, shape = _arrow(target, box, _targets(target, elements), rng), "flecha"
    else:
        brush, size = "subrayador", max(4, min(16, round((y1 - y0) / 3)))
        pts = _stroke((x0 + 2, cy), (x1 - 2, cy), rng, amp=1.5)
    pts = [(round(x, 2), round(y, 2)) for x, y in pts]
    return scene.ink_element(pts, brush, size, color, author, shape=shape, anchor=target["id"])
