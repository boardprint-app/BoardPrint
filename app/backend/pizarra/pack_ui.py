"""La interfaz propia de un paquete, servida para su `iframe` (docs/PLAN_PAQUETES.md §5, P24).

`GET /packs/<id>/ui/<ruta>` sirve un fichero de la carpeta `ui/` de un paquete **cargado** y
nada más: ni de fuera de `ui/` (`blocks.py`, `pack.toml`), ni de fuera del paquete (`..`, rutas
absolutas, enlaces que salen de la carpeta), ni de un paquete roto.

Todo lo servido lleva la CSP sin red: `default-src 'none'`, y scripts, estilos, imágenes y
fuentes **solo** de la propia `ui/` del paquete (con la ruta: ni otro paquete ni la API). Lo
en línea se permite: no abre ningún camino a la red. `connect-src` queda en `'none'` (sin
`fetch`, WebSocket ni `EventSource`), y el `iframe` la carga con `sandbox="allow-scripts"`, sin
`allow-same-origin`: su origen es opaco y no lee nada de la app.

Va fuera de `/api/`, sin token: el `iframe` no lo tiene (y un script o una hoja de estilos que
pide no lo llevaría), y estos ficheros no son más secretos que la interfaz de la app, que
también se sirve sin token. Como el `iframe` tiene origen opaco, un `<script type="module">` y
las fuentes se piden en modo CORS: de ahí `Access-Control-Allow-Origin: *`.

A cada página (`.html`) se le mete delante de todo lo suyo el **puente de la rueda** (P54): la
rueda que nace dentro de un `iframe` nunca llega a la app, y con 30 tarjetas el ratón casi
siempre está encima de una. El puente deja la rueda a la página mientras algo suyo pueda
desplazarse en esa dirección; si no, o con Ctrl (zoom), la cancela (tampoco hace zoom de la
página entera) y la manda a la app como `wheel` del protocolo v1, que la pasa al lienzo. Lo
hace el núcleo y no cada paquete: el que se olvidara dejaría la pizarra atascada.
"""
import re
from pathlib import Path, PurePosixPath

UI_DIR = "ui"
PAGE_SUFFIXES = (".html", ".htm")

# La misma regla que `wheelToCanvas` (frontend/src/block.ts), del lado de la página.
BRIDGE = (
    "<script>/* BoardPrint: la rueda al lienzo (P54) */(()=>{"
    "const can=(e,dx,dy)=>{for(;e&&e.nodeType===1;e=e.parentElement){"
    "const s=getComputedStyle(e),r=e===document.scrollingElement,"
    "oy=r?s.overflowY!=='hidden':/auto|scroll/.test(s.overflowY),"
    "ox=r?s.overflowX!=='hidden':/auto|scroll/.test(s.overflowX);"
    "if(dy&&oy&&e.scrollHeight>e.clientHeight&&(dy<0?e.scrollTop>0:"
    "e.scrollTop+e.clientHeight<e.scrollHeight-1))return true;"
    "if(dx&&ox&&e.scrollWidth>e.clientWidth&&(dx<0?e.scrollLeft>0:"
    "e.scrollLeft+e.clientWidth<e.scrollWidth-1))return true;}return false};"
    "addEventListener('wheel',ev=>{"
    "if(!ev.ctrlKey&&!ev.metaKey&&can(ev.target,ev.deltaX,ev.deltaY))return;"
    "ev.preventDefault();"
    "parent.postMessage({v:1,type:'wheel',dx:ev.deltaX,dy:ev.deltaY,mode:ev.deltaMode,"
    "x:ev.clientX,y:ev.clientY,ctrl:ev.ctrlKey,meta:ev.metaKey,shift:ev.shiftKey,"
    "alt:ev.altKey},'*')},{passive:false,capture:true})})();</script>"
)
_AFTER = [re.compile(p, re.I) for p in (rb"<head\b[^>]*>", rb"<html\b[^>]*>", rb"<!doctype\b[^>]*>")]


def is_page(path):
    return Path(path).suffix.lower() in PAGE_SUFFIXES


def with_bridge(html):
    """La página (bytes) con el puente delante de todo lo suyo: detrás de `<head>`; sin él,
    detrás de `<html>` o del `<!doctype>` (delante, el navegador pasaría a modo quirks)."""
    start = 3 if html.startswith(b"\xef\xbb\xbf") else 0
    for pat in _AFTER:
        if m := pat.search(html):
            start = m.end()
            break
    return html[:start] + BRIDGE.encode() + html[start:]


class NotServed(Exception):
    """Lo pedido no se sirve (404): no hay paquete cargado, o la ruta sale de su `ui/`."""


def resolve(registry, pack_id, rel):
    """La ruta en disco de `<paquete>/ui/<rel>`, o `NotServed`. `rel` es lo de detrás de
    `/ui/` en la URL, ya decodificado."""
    info = registry.pack(pack_id)
    if info is None or not info.ui:
        raise NotServed(f"el paquete {pack_id!r} no está cargado o no tiene interfaz propia")
    if not rel or "\\" in rel or "\0" in rel or ":" in rel:
        raise NotServed(f"ruta no válida: {rel!r}")
    parts = PurePosixPath(rel).parts
    if PurePosixPath(rel).is_absolute() or any(p in ("", ".", "..") for p in parts):
        raise NotServed(f"ruta no válida: {rel!r}")
    root = (Path(info.path) / UI_DIR).resolve()
    target = (root / Path(*parts)).resolve()          # resuelve también los enlaces
    if not target.is_relative_to(root) or not target.is_file():
        raise NotServed(f"no está {UI_DIR}/{rel} en {pack_id}")
    return target


def csp(origin, pack_id):
    """La CSP de todo lo servido: nada de red, y lo suyo solo de su `ui/` (P24). `origin` es el
    del backend tal y como lo pidió el navegador (`http://127.0.0.1:8765`), o None si no se
    sabe (un `Host` raro): entonces nada se carga, ni de su `ui/`."""
    own = f"{origin}/packs/{pack_id}/{UI_DIR}/" if origin else "'none'"
    return "; ".join([
        "default-src 'none'",
        f"script-src {own} 'unsafe-inline'",
        f"style-src {own} 'unsafe-inline'",
        f"img-src {own} data: blob:",
        f"font-src {own} data:",
        "connect-src 'none'",
        "form-action 'none'",
        "base-uri 'none'",
    ])


def headers(origin, pack_id):
    """Las cabeceras de toda respuesta de `/packs/…`, servida o no."""
    return {"Content-Security-Policy": csp(origin, pack_id),
            "X-Content-Type-Options": "nosniff",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache"}       # un paquete en desarrollo cambia (P26)
