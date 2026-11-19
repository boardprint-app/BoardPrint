"""¿Está una carpeta dentro de una sincronizada con la nube? (docs/PLAN_PIZARRA.md R3, D186)

Un workspace dentro de OneDrive, iCloud, Dropbox o Google Drive funciona, pero la nube puede
subir un `scene.json` a medio escribir o dejar una copia en conflicto: la bienvenida y
*Ajustes → General* avisan. Puro: la ruta, las variables de entorno y el sistema se pasan, así
que se prueba igual en cualquier máquina. Quien llama resuelve antes los enlaces de la ruta
(en Mac, «Escritorio y Documentos en iCloud» hace de `~/Documents` un enlace a iCloud).
"""
import os
import sys
from pathlib import PurePosixPath, PureWindowsPath

# Variables que pone el cliente de OneDrive en Windows (personal y de empresa).
ONEDRIVE_ENV = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
# Nombre de una carpeta de la ruta (sin mayúsculas) → servicio. «OneDrive - Empresa» empieza
# por «onedrive»; en Mac, `~/Library/CloudStorage/<Servicio>-<cuenta>` también.
_BY_PREFIX = (("onedrive", "OneDrive"), ("dropbox", "Dropbox"), ("googledrive", "Google Drive"),
              ("google drive", "Google Drive"), ("icloud", "iCloud"))
_BY_NAME = {"icloud drive": "iCloud", "iclouddrive": "iCloud", "mobile documents": "iCloud",
            "my drive": "Google Drive", "mi unidad": "Google Drive"}


def service(path, env=None, platform=None):
    """El nombre del servicio («OneDrive», «iCloud», «Dropbox», «Google Drive») si `path` está
    dentro de una carpeta suya, si no None."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    pure = PureWindowsPath if platform == "win32" else PurePosixPath
    p = pure(str(path))
    fold = (lambda s: s.lower()) if platform == "win32" else (lambda s: s)
    for var in ONEDRIVE_ENV:
        root = env.get(var)
        if root and _inside(p, pure(root), fold):
            return "OneDrive"
    for part in p.parts[1:]:
        low = part.lower()
        if low in _BY_NAME:
            return _BY_NAME[low]
        for prefix, name in _BY_PREFIX:
            if low.startswith(prefix):
                return name
    return None


def _inside(path, root, fold):
    a = [fold(x) for x in path.parts]
    b = [fold(x) for x in root.parts]
    return len(b) > 1 and a[:len(b)] == b
