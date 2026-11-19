"""Catálogos de traducción de un paquete (docs/PLAN_PUBLICACION.md O15).

Un paquete se escribe en un idioma (los del repo, en español) y se traduce con un catálogo por
texto de origen: `locales/<idioma>.toml`, una tabla plana

    "Masa (kg)" = "Mass (kg)"
    "Falla por {x} mm" = "Fails by {x} mm"

La clave es el texto tal y como lo da el paquete y el valor, su traducción. Una clave con
`{nombre}` es un **patrón**: casa la frase entera con cualquier valor en cada marcador, y la
traducción lleva los mismos marcadores (en el orden que pida el idioma, y repetidos si hace
falta). La interfaz traduce **solo al pintar** (`frontend/src/packI18n.ts`); los datos (ids,
claves, valores que viajan por las flechas) nunca se tocan, y el código del paquete no cambia.

Aquí se leen y se comprueban. La carga es tolerante: un catálogo ilegible o una entrada mal
hecha se apunta como aviso y se deja fuera, y el paquete carga igual. La validación estática
(`pack_validate`, al exportar, instalar o proponer) los da como problemas.
"""
import re
import tomllib
from pathlib import Path

LOCALES_DIR = "locales"
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
# Solo `{palabra}` en ASCII, como `\w` en JavaScript (packI18n.ts): «{parámetro: valor}» es texto.
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}", re.ASCII)


def placeholders(text):
    """Los nombres de los marcadores `{nombre}` de `text` (conjunto)."""
    return set(PLACEHOLDER_RE.findall(text))


def _entry_problem(key, value):
    """Por qué la entrada `key = value` no vale, o None."""
    if not isinstance(value, str):
        return "tiene que ser un texto (la tabla es plana: «texto de origen» = «traducción»)"
    if not key.strip():
        return "la clave está vacía"
    if not value.strip():
        return "la traducción está vacía"
    src, dst = placeholders(key), placeholders(value)
    if src != dst:
        return (f"los marcadores no son los mismos en el texto ({', '.join(sorted(src)) or 'ninguno'}) "
                f"y en la traducción ({', '.join(sorted(dst)) or 'ninguno'})")
    if src and not PLACEHOLDER_RE.sub("", key).strip():
        return "una clave que solo tiene marcadores casaría con cualquier texto"
    return None


def read(folder):
    """`(catálogos, problemas)` del paquete de `folder`: `{idioma: {origen: traducción}}` con lo
    que vale, y la lista de lo que no (textos). Sin `locales/`, `({}, [])`. Nunca lanza."""
    root = Path(folder) / LOCALES_DIR
    catalogs, problems = {}, []
    if not root.is_dir():
        return catalogs, problems
    for path in sorted(root.glob("*.toml")):
        rel = f"{LOCALES_DIR}/{path.name}"
        lang = path.stem
        if not LANG_RE.match(lang):
            problems.append(f"{rel}: el nombre tiene que ser el código del idioma (en.toml, pt-BR.toml)")
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            problems.append(f"{rel}: no se puede leer: {exc}")
            continue
        table = {}
        for key, value in data.items():
            why = _entry_problem(key, value)
            if why:
                problems.append(f"{rel}: {key!r}: {why}")
            else:
                table[key] = value
        catalogs[lang] = table
    return catalogs, problems


def problems(folder):
    """Lo que no vale de los catálogos de `folder` (para `pack_validate`)."""
    return read(folder)[1]
