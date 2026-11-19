"""Nombres y rutas de carpetas y proyectos (docs/PLAN_PIZARRA.md §2, D65), y las claves y
los tipos de las fichas de la librería del workspace (PLAN_V020 V14).

Un nombre es el de una carpeta en disco, así que se rechaza todo lo que Windows no admite,
aunque se esté en Mac: un workspace se puede copiar de una máquina a otra. Una ruta viene de
la interfaz y nunca puede salir del workspace.
"""
import re

from pizarra import i18n
from pizarra.storage.base import InvalidName, NotFound

MAX_NAME = 120          # Windows limita la ruta entera a 260 caracteres por defecto
_BAD_CHARS = set('<>:"/\\|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
ROOT_RESERVED = {"profile", "packs"}   # carpetas del propio workspace (§2); la librería va en profile/ (V14)
# Una ficha es `library/<tipo>s/<clave>.toml`: la clave es su nombre de fichero (como las de los
# paquetes, `SHG-20-100-2UH`) y el tipo, el de su carpeta.
FICHA_KEY_MAX = 100
_FICHA_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_FICHA_TYPE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")


def check_name(name, at_root=False):
    """Devuelve el nombre sin espacios a los lados, o `InvalidName` con el motivo."""
    if not isinstance(name, str):
        raise InvalidName(i18n.t("nombre.no_es_texto"))
    name = name.strip()
    if not name:
        raise InvalidName(i18n.t("nombre.vacio"))
    if len(name) > MAX_NAME:
        raise InvalidName(i18n.t("nombre.largo", max=MAX_NAME))
    bad = sorted({c for c in name if c in _BAD_CHARS or ord(c) < 32})
    if bad:
        shown = " ".join(repr(c) if ord(c) < 32 else c for c in bad)
        raise InvalidName(i18n.t("nombre.caracteres", caracteres=shown))
    if name.startswith("."):
        raise InvalidName(i18n.t("nombre.empieza_punto"))
    if name.endswith("."):
        raise InvalidName(i18n.t("nombre.acaba_punto"))
    if name.split(".")[0].rstrip().upper() in _RESERVED:
        raise InvalidName(i18n.t("nombre.reservado_windows", nombre=name))
    if at_root and name.casefold() in ROOT_RESERVED:
        raise InvalidName(i18n.t("nombre.reservado_raiz", nombre=name))
    return name


def check_ficha_key(key):
    """La clave de una ficha, o `InvalidName`: letras, cifras, `.`, `_`, `+` y `-`, sin empezar
    ni acabar en punto, ni un nombre reservado de Windows."""
    ok = (isinstance(key, str) and 0 < len(key) <= FICHA_KEY_MAX and _FICHA_KEY_RE.fullmatch(key)
          and not key.endswith(".") and key.split(".")[0].upper() not in _RESERVED)
    if not ok:
        raise InvalidName(i18n.t("libreria.clave_no_valida", clave=repr(key), max=FICHA_KEY_MAX))
    return key


def check_ficha_type(type_):
    """El tipo de una ficha (`reducer`, `gripper`…), o `InvalidName`. El núcleo no sabe qué tipos
    hay (V15): cualquiera con minúsculas, cifras y `_`."""
    if not isinstance(type_, str) or not _FICHA_TYPE_RE.fullmatch(type_):
        raise InvalidName(i18n.t("libreria.tipo_no_valido", tipo=repr(type_)))
    return type_


def split_rel(path):
    """Partes de una ruta relativa al workspace ("" = la raíz). Nunca sale del workspace:
    se rechazan `..`, `.`, rutas absolutas, unidades (`C:`), `\\` y tramos vacíos."""
    if not isinstance(path, str):
        raise InvalidName(i18n.t("ruta.no_es_texto"))
    if path == "":
        return []
    if "\\" in path or ":" in path or path.startswith("/"):
        raise InvalidName(i18n.t("ruta.no_valida", ruta=repr(path)))
    parts = path.split("/")
    for p in parts:
        if p in ("", ".", ".."):
            raise InvalidName(i18n.t("ruta.no_valida", ruta=repr(path)))
        if p.startswith("."):
            raise NotFound(i18n.t("carpeta.no_existe", ruta=repr(path)))
    return parts
