"""El prompt de sistema del agente de diseño, construido en cada mensaje (plan §4, D144, D172).

Lleva la base (`agent.SYSTEM_PROMPT`), lo de las animaciones según «Animaciones automáticas»
(`[agentes] animaciones_automaticas` de `settings.toml`) y el `agent.md` de cada paquete
cargado.

- **Animaciones** (D143, D144): activadas, el prompt lleva el criterio (ponerla cuando el
  movimiento explica mejor que el texto) y la guía de cómo hacerlas. Desactivadas, lleva la
  orden de no hacerlas salvo que el ingeniero la pida en ese mensaje y **nunca** la guía: el
  agente la pide con la herramienta `guia_animacion` cuando se la piden. Así no gasta tokens ni
  tiempo en una que nadie ha pedido, que es el motivo del ajuste.
- **`agent.md` de un paquete** (D172): solo de los paquetes que cargaron, hasta
  `AGENT_MD_CHARS` caracteres cada uno; uno más largo se corta y queda un aviso en el registro.
"""
import logging
from pathlib import Path

from pizarra import i18n
from pizarra.pasted import ANIMATION_MAX
from pizarra.scene import ANIMATION_SIZE

log = logging.getLogger(__name__)

AGENT_MD = "agent.md"
AGENT_MD_CHARS = 4000
CUT = " […]"

ANIMATIONS_ON = """\
- Animaciones (crear_postit con `animacion`): un post-it puede llevar encima de su texto una \
animación interactiva en HTML. Ponla por tu cuenta solo cuando el movimiento explica mejor \
que el texto cómo funciona algo (un tren de engranajes, una leva, un cuatro barras, una junta \
que gira); nunca para adornar ni para dar datos. Si el ingeniero la pide, hazla siempre y \
marca pedida_por_usuario=true. Ilustra, no es fuente de nada: las cifras del texto siguen \
con sus `sources`."""

ANIMATIONS_OFF = """\
- Animaciones: el ingeniero ha desactivado las animaciones automáticas. No pongas \
`animacion` en crear_postit salvo que en este mensaje te pida una animación; entonces lee \
antes guia_animacion y crea el post-it con pedida_por_usuario=true."""

# Desactivadas, va delante de cada mensaje que recibe el agente (no del que se guarda en el
# chat): el prompt de sistema no basta frente a una animación que ya hizo en esa conversación
# (prueba de punta a punta de FF 4.6).
ANIMATIONS_OFF_NOTE = ("Animaciones automáticas desactivadas: no hagas ninguna salvo que este "
                       "mensaje la pida.")

W, H = ANIMATION_SIZE
ANIMATION_GUIDE = f"""\
Cómo se hace la animación de un post-it:
- Un solo documento HTML autocontenido (<!doctype html>, con <style> y <script> en línea), \
de hasta {ANIMATION_MAX // 1024} KB. Sin red: nada de CDN, fuentes ni imágenes de fuera, \
fetch ni WebSocket (la página no tiene red); una imagen, solo como data:. Mejor SVG o \
<canvas> dibujados por el script.
- Se ve encima del texto del post-it a {W} × {H} px: diseña para eso, con html y body a \
100 % de ancho y alto, sin márgenes ni barras de desplazamiento, y que escale si cambia.
- Colores del skin: la app manda por postMessage {{type: "skin", vars: {{"--bp-bg": …, \
"--bp-fg": …, "--bp-muted": …, "--bp-line": …, "--bp-accent": …}}}}. Ponlas con \
document.documentElement.style.setProperty y usa var(--bp-fg, #222) y compañía, siempre con un \
valor por defecto: hasta que llega el mensaje, se ven esos.
- Controles pequeños dentro del recuadro, si ayudan: un deslizador (velocidad, un ángulo, una \
relación) y un botón de pausa. Sin alert, prompt ni formularios, ni localStorage ni cookies: \
la página está aislada y fallan.
- Mueve con requestAnimationFrame. El ingeniero la maneja con el post-it seleccionado.
- Lo que dibujas es un esquema que explica el funcionamiento, no un cálculo: si enseñas \
cifras, que sean las del texto del post-it, con sus fuentes."""

GUIDE_TOOL = "La guía para hacer la animación de un post-it: léela antes de hacer una que te piden."


def animations_part(auto):
    """Lo de las animaciones en el prompt: con `auto`, el criterio y la guía; sin él, solo la
    orden de no hacerlas sin que se pidan (la guía, con `guia_animacion`)."""
    return f"{ANIMATIONS_ON}\n\n{ANIMATION_GUIDE}" if auto else ANIMATIONS_OFF


def pack_instructions(registry):
    """`[(paquete, nombre, texto)]` con el `agent.md` de cada paquete cargado, recortado a
    `AGENT_MD_CHARS` (con aviso en el registro). Los que no cargaron no entran nunca."""
    out = []
    for p in getattr(registry, "packs", None) or []:
        if p.error is not None or not p.path:
            continue
        f = Path(p.path) / AGENT_MD
        try:
            text = f.read_text(encoding="utf-8").strip() if f.is_file() else ""
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("[paquetes] %s: no se puede leer su %s (%s); el agente no lo ve",
                        p.id, AGENT_MD, exc)
            continue
        if not text:
            continue
        if len(text) > AGENT_MD_CHARS:
            log.warning("[paquetes] %s: su %s tiene %d caracteres y el máximo es %d; al "
                        "agente le llega cortado", p.id, AGENT_MD, len(text), AGENT_MD_CHARS)
            text = text[:AGENT_MD_CHARS].rstrip() + CUT
        out.append((p.id, p.name or p.id, text))
    return out


# Lo que la prueba de punta a punta de FF 4.6 vio que faltaba (D19, D170).
RULES = """- Una cifra derivada de una salida (un porcentaje, una resta, un cociente, un redondeo que cambia el valor) es kind "calculo" con su `formula` y sus `inputs`, nunca "bloque": un bloque solo es fuente de lo que da tal cual.
- Nunca lanzas nada que escriba fuera del proyecto. ejecutar_bloque se niega si la ejecución lleva un bloque que pide un conector (Construir o Analizar en Fusion…): dile al ingeniero que pulse Ejecutar él. Las salidas de esos bloques, ya al día, sí las puedes usar.
- Si Fusion está abierto o no, y cómo acabaron tus propuestas, lo dice leer_pizarra (`connectors`, `my_proposals`): no lo des por sabido de antes."""

OFFICE = """- Office (D176): crear_archivo cuando te pidan un informe, una lista de materiales o una presentación (Word, Excel o PowerPoint): queda en la carpeta del proyecto, o en una carpeta de la pizarra con `carpeta`, y nunca pisa nada. editar_archivo cuando te pidan cambiar un archivo de la pizarra: escribe una copia <nombre>_n y deja una propuesta con el diff; nunca toques el original de otra forma. Las cifras que escribes en los dos llevan `sources` (un archivo leído, `where` incluido, o un bloque) o estimate=true, como en un post-it."""


def build(base, auto, registry, language="es"):
    """El prompt entero: la base, las reglas con el idioma de la interfaz en que responde
    (D41, D180), las animaciones, Office y las instrucciones de los paquetes."""
    parts = [base, RULES + "\n- " + i18n.t("agente.idioma", language), animations_part(auto),
             OFFICE]
    packs = pack_instructions(registry)
    if packs:
        parts.append("Instrucciones de los paquetes de bloques cargados (sus bloques están en "
                     "`catalog` de leer_pizarra):\n\n" + "\n\n".join(
                         f"## {name} (`{pid}`)\n{text}" for pid, name, text in packs))
    return "\n\n".join(parts)
