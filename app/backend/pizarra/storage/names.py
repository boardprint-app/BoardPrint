"""Nombres y rutas de carpetas y proyectos (docs/PLAN_PIZARRA.md §2, D65).

Un nombre es el de una carpeta en disco, así que se rechaza todo lo que Windows no admite,
aunque se esté en Mac: un workspace se puede copiar de una máquina a otra. Una ruta viene de
la interfaz y nunca puede salir del workspace.
"""
from pizarra import i18n
from pizarra.storage.base import InvalidName, NotFound

MAX_NAME = 120          # Windows limita la ruta entera a 260 caracteres por defecto
_BAD_CHARS = set('<>:"/\\|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
ROOT_RESERVED = {"profile", "packs"}          # carpetas del propio workspace (§2)


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
