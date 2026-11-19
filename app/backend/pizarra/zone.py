"""La imagen de una zona de la pizarra para el agente (`ver_zona`, plan §4, D171).

No hay un pintor de Excalidraw en Python: la pinta una ventana abierta del proyecto. El backend
le pide por el WebSocket

    {"type": "zone_request", "id", "rect": {x, y, width, height} | "elements": [ids],
     "maxSide": 1568, "excludeImages": bool}

y espera `{"type": "zone_image", "id", "png": <base64>}` o `{"type": "zone_image", "id",
"error": <motivo>}` (`frontend/src/zone.ts`). Sin ventana, si tarda más de `TIMEOUT` s o si lo
que vuelve no es un PNG de hasta `MAX_SIDE` px de lado, error con el motivo: nunca una imagen
vacía.
"""
import asyncio
import base64
import binascii
import struct
import uuid

from pizarra.validation import ValidationError

TIMEOUT = 15.0              # s que se espera a la ventana (D171)
MAX_SIDE = 1568             # px del lado más largo: lo que Claude ve sin reescalar
MAX_BYTES = 8 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data):
    """`(ancho, alto)` de un PNG por su cabecera, o None si no es un PNG."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def check_png(b64):
    """El PNG en base64 tal como lo manda la ventana, comprobado; si no vale, `ValidationError`."""
    if not isinstance(b64, str) or not b64:
        raise ValidationError("la ventana no ha devuelto ninguna imagen")
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError("la ventana ha devuelto algo que no es base64") from None
    size = png_size(data)
    if size is None or 0 in size:
        raise ValidationError("la ventana ha devuelto algo que no es un PNG")
    if max(size) > MAX_SIDE or len(data) > MAX_BYTES:
        raise ValidationError(f"la imagen de la zona pasa de {MAX_SIDE} px de lado o de 8 MB")
    return b64


class ZoneRequests:
    """Las peticiones de imagen pendientes de un proyecto (una por llamada a `ver_zona`)."""

    def __init__(self):
        self._pending = {}

    async def request(self, clients, payload, prefer=None, timeout=TIMEOUT):
        """Pide la zona a una sola ventana de `clients` (la de `prefer` si sigue abierta, la
        que preguntó al agente) y devuelve el PNG en base64. `ValidationError` con el motivo
        sin ventana, si no contesta en `timeout` s o si contesta con un error."""
        live = list(clients)
        if not live:
            raise ValidationError("no hay ninguna ventana abierta de este proyecto que pinte "
                                  "la zona: trabaja con leer_pizarra")
        order = ([prefer] if prefer in live else []) + [c for c in live if c is not prefer]
        rid = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            for ws in order:                  # si una ventana se acaba de cerrar, la siguiente
                try:
                    await ws.send_json({"type": "zone_request", "id": rid, **payload})
                    break
                except Exception:             # noqa: BLE001 cerrada a medias
                    continue
            else:
                raise ValidationError("ninguna ventana del proyecto ha podido recibir la petición")
            try:
                msg = await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                raise ValidationError(f"la ventana no ha devuelto la imagen en {timeout:g} s") \
                    from None
        finally:
            self._pending.pop(rid, None)
        if msg.get("error"):
            raise ValidationError(f"la ventana no ha podido pintar la zona: {msg['error']}")
        return check_png(msg.get("png"))

    def answer(self, msg):
        """La respuesta de una ventana (`zone_image`). Una que ya no se espera (llegó tarde) se
        descarta. Devuelve si se esperaba."""
        fut = self._pending.get(msg.get("id"))
        if fut is None or fut.done():
            return False
        fut.set_result(msg)
        return True
