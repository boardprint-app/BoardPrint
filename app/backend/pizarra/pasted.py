"""Lo que se pega en la pizarra (plan §3, D84, D137, D140): imágenes y enlaces.

Reglas puras, sin almacenamiento ni servidor:
- Una imagen pegada se reconoce por sus primeros bytes, nunca por lo que diga la petición: el
  tipo declarado lo pone quien la manda. SVG no entra (es un documento que puede llevar
  scripts, y Ctrl+V de una captura nunca lo da).
- Un enlace solo se abre si es `http` o `https` con un dominio: la URL vive en la escena y la
  puede escribir cualquier cliente, así que se comprueba al abrir, no al pegar.
"""
from urllib.parse import urlsplit

# Firma → extensión con la que se guarda (`board/files/<sha256>.<ext>`).
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)
IMAGE_EXT = {"png", "jpg", "gif", "bmp", "webp"}
MEDIA_TYPE = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp",
              "webp": "image/webp"}
IMAGE_MAX = 30 * 1024 ** 2      # una captura de pantalla 4K en PNG ronda los 10 MB
# No se pega, pero vive al lado: la animación de un post-it del agente (D143, D175), un HTML
# autocontenido en `board/files/<sha256>.html`, hasta 256 KB.
ANIMATION_EXT = "html"
ANIMATION_MAX = 256 * 1024


def image_ext(data):
    """La extensión de la imagen que son estos bytes, o `None` si no es una que se guarde."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    for sig, ext in _SIGNATURES:
        if data.startswith(sig) and len(data) > len(sig):
            return ext
    return None


def safe_url(url):
    """La URL si se puede abrir en el navegador (`http` o `https`, con dominio y sin espacios),
    o `None`. Nunca `file:`, `javascript:` ni nada que abra un programa del sistema."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or any(c.isspace() for c in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return url
