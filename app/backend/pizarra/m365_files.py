"""Archivos de OneDrive y SharePoint en la pizarra (docs/PLAN_M365.md §4, §5: M6-M9).

Un archivo de la nube se descarga en `<proyecto>/microsoft365/` y su tarjeta es una tarjeta de
archivo normal con `customData.m365` (servicio, `drive_id`, `item_id`, `ctag`, `web_url` y el
sha256 de lo descargado): leerlo el agente, el Excel como datos y el sondeo de D134 funcionan
igual que con un archivo local.

El sondeo de la nube (M7) mira el `cTag` y decide con `refresh_action`; la copia local nunca se
pisa si el usuario la cambió (M8). Guardar en la nube nunca escribe encima (M9): siempre con
`conflictBehavior=rename`.
"""
import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from pizarra import scene
from pizarra.m365_auth import SCOPES_SHAREPOINT
from pizarra.office_write import _create_exclusive
from pizarra.storage.local import atomic_write
from pizarra.validation import ValidationError

FOLDER = "microsoft365"
SERVICES = ("onedrive", "sharepoint", "correo")
NAME_MAX = 120
MAX_BYTES = 250 * 1024 * 1024       # lo que se trae a la pizarra de una vez
SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024  # más, sesión de subida (M9)
CHUNK = 320 * 1024 * 16              # 5 MiB: los trozos de una sesión, múltiplo de 320 KiB
AL_DIA, DESCARGAR, CONFLICTO = "al_dia", "descargar", "conflicto"
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
ITEM_SELECT = ("id,name,size,file,folder,cTag,eTag,webUrl,lastModifiedDateTime,parentReference,"
               "remoteItem")


def safe_name(name, fallback="archivo"):
    """Un nombre de la nube (o el asunto de un correo) como nombre de archivo en Windows y en
    macOS: sin carpetas, sin caracteres prohibidos, sin nombres reservados y sin pasarse de
    `NAME_MAX`, conservando la extensión."""
    name = _BAD.sub("_", str(name or "")).strip().strip(".").strip()
    if not name or set(name) <= {"_", " "}:
        name = fallback
    stem, suffix = Path(name).stem, Path(name).suffix
    if len(suffix) > 16:
        stem, suffix = name, ""
    if stem.lower() in _RESERVED:
        stem = f"{stem}_"
    if len(stem) + len(suffix) > NAME_MAX:
        stem = stem[:NAME_MAX - len(suffix)].rstrip(" .") or fallback
    return stem + suffix


def item_view(item, service="onedrive"):
    """Lo que el panel enseña de un `driveItem`. Un elemento compartido conmigo viene como
    `remoteItem`: manda su unidad y su id."""
    remote = item.get("remoteItem") or {}
    parent = remote.get("parentReference") or item.get("parentReference") or {}
    return {"id": remote.get("id") or item.get("id"),
            "drive_id": parent.get("driveId"),
            "name": item.get("name") or remote.get("name") or "",
            "folder": "folder" in item or "folder" in remote,
            "child_count": (item.get("folder") or remote.get("folder") or {}).get("childCount"),
            "size": item.get("size") or remote.get("size") or 0,
            "modified": item.get("lastModifiedDateTime") or "",
            "web_url": item.get("webUrl") or remote.get("webUrl") or "",
            "ctag": item.get("cTag") or remote.get("cTag"),
            "service": service}


def _item_path(drive_id, item_id):
    return f"/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}"


def children(graph, drive_id=None, item_id=None, service="onedrive", scopes=None):
    """Lo de dentro de una carpeta; sin carpeta, la raíz de mi OneDrive."""
    if drive_id and item_id == "root":
        path = f"/drives/{quote(drive_id, safe='')}/root/children"
    elif drive_id and item_id:
        path = _item_path(drive_id, item_id) + "/children"
    else:
        path = "/me/drive/root/children"
    kw = {"scopes": scopes} if scopes else {}
    items = graph.get_all(path + f"?$top=200&$select={ITEM_SELECT}", **kw)
    out = [item_view(i, service) for i in items]
    return sorted(out, key=lambda v: (not v["folder"], v["name"].lower()))


def search(graph, text):
    """Buscar en mi OneDrive (y lo compartido conmigo) por nombre y contenido."""
    q = str(text or "").strip().replace("'", "''")
    if not q:
        return []
    items = graph.get_all(f"/me/drive/root/search(q='{quote(q, safe='')}')?$top=50"
                          f"&$select={ITEM_SELECT}")
    return [item_view(i) for i in items]


def sites(graph, text, scopes=None):
    """Sitios de SharePoint por nombre (M4: con el permiso aparte). Sin texto, los que sigo."""
    q = str(text or "").strip()
    kw = {"scopes": scopes} if scopes else {}
    path = f"/sites?search={quote(q, safe='')}" if q else "/me/followedSites"
    return [{"id": s.get("id"), "name": s.get("displayName") or s.get("name") or "",
             "web_url": s.get("webUrl") or ""} for s in graph.get_all(path, **kw)]


def site_drives(graph, site_id, scopes=None):
    """Las bibliotecas de documentos de un sitio."""
    kw = {"scopes": scopes} if scopes else {}
    items = graph.get_all(f"/sites/{quote(site_id, safe=',')}/drives", **kw)
    return [{"id": d.get("id"), "name": d.get("name") or "", "web_url": d.get("webUrl") or ""}
            for d in items]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    path = Path(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def card_for_item(board, drive_id, item_id):
    """La tarjeta viva que ya trae ese archivo de la nube, o None (M6: no se duplica)."""
    for el in board.elements:
        if el.get("isDeleted") or el.get("type") != "embeddable":
            continue
        m = (el.get("customData") or {}).get("m365") or {}
        if m.get("item_id") == item_id and m.get("drive_id") == drive_id:
            return el
    return None


def target_folder(board):
    path = Path(board.dir) / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_new(board, name, data):
    """Escribe `data` en `<proyecto>/microsoft365/` con un nombre libre (`_n`, nunca pisa).
    Devuelve la ruta. Un nombre con `..` o `/` no sale de la carpeta: se limpia antes."""
    folder = target_folder(board)
    path = _create_exclusive(folder, safe_name(name), lambda f: f.write(data))
    if path.resolve().parent != folder.resolve():       # nunca fuera de la carpeta
        path.unlink(missing_ok=True)
        raise ValidationError(f"{name!r}: nombre no válido")
    return path


NEAR_TRIES = 12                 # huecos que se prueban debajo del sitio pedido


def place(board, x, y):
    """Dónde va una tarjeta traída (M14): en (x, y) si está libre; si no, el primer hueco
    debajo, en la misma columna (sigue a la vista); y si no hay, el de `_free_spot`. Nunca
    encima de otra tarjeta."""
    w, h = scene.FILE_SIZE
    if x is not None and y is not None:
        for k in range(NEAR_TRIES):
            want = (x, y + k * (h + 16))
            if board._free_spot(w, h, None, prefer=want) == want:
                return want
    return board._free_spot(w, h, None)


def bring(board, graph, drive_id, item_id, x=None, y=None, service="onedrive",
          author="user", scopes=None):
    """Trae un archivo de la nube a la pizarra (M6). Devuelve (tarjeta, nueva). Si ya está, la
    misma tarjeta sin descargar nada."""
    if service not in SERVICES:
        raise ValidationError(f"servicio desconocido: {service!r}")
    existing = card_for_item(board, drive_id, item_id)
    if existing is not None:
        return existing, False
    kw = {"scopes": scopes} if scopes else {}
    item = graph.get(_item_path(drive_id, item_id) + f"?$select={ITEM_SELECT}", **kw)
    view = item_view(item, service)
    if view["folder"]:
        raise ValidationError(f"{view['name']}: es una carpeta; trae sus archivos uno a uno")
    if view["size"] > MAX_BYTES:
        raise ValidationError(f"{view['name']}: pasa de {MAX_BYTES // (1024 * 1024)} MB")
    data = graph.download(_item_path(drive_id, item_id) + "/content", **kw)
    path = write_new(board, view["name"], data)
    x, y = place(board, x, y)
    el = board.add_cards([path], x, y, author=author)[0]
    el["customData"]["m365"] = {"service": service, "drive_id": drive_id, "item_id": item_id,
                                "name": view["name"], "ctag": view["ctag"],
                                "web_url": view["web_url"], "sha256": sha256(data)}
    board.save()
    return el, True


def refresh_action(stored_ctag, remote_ctag, downloaded_sha, local_sha):
    """Qué hacer con una tarjeta de la nube en el sondeo (M7, M8):
    - el mismo `cTag`: `al_dia` (nunca se descarga);
    - otro, y la copia local sin tocar (o borrada): `descargar`;
    - otro, y la copia local cambiada aquí: `conflicto` (nunca se descarga encima)."""
    if remote_ctag is None or remote_ctag == stored_ctag:
        return AL_DIA
    if local_sha is None or local_sha == downloaded_sha:
        return DESCARGAR
    return CONFLICTO


def _set_m365(board, el, **changes):
    cd = {**el["customData"], "m365": {**el["customData"]["m365"], **changes}}
    new = scene.bumped({**el, "customData": cd})
    board.elements = [new if e["id"] == el["id"] else e for e in board.elements]
    return new


def cloud_cards(board):
    """Las tarjetas de archivo vivas que vienen de OneDrive o SharePoint."""
    return [el for el in board.elements
            if not el.get("isDeleted") and el.get("type") == "embeddable"
            and ((el.get("customData") or {}).get("m365") or {}).get("item_id")
            and (el["customData"]["m365"].get("service") in ("onedrive", "sharepoint"))]


def refresh(board, graph, el, force=False):
    """Una pasada del sondeo para una tarjeta (M7, M8). Devuelve su estado: `al_dia`,
    `descargada`, `conflicto`. `force` (*Traer la de la nube*) descarga aunque haya conflicto;
    la copia local cambiada va antes a la papelera (D20). Sin red, `Offline` sale hacia arriba."""
    m = el["customData"]["m365"]
    kw = {"scopes": SCOPES_SHAREPOINT} if m.get("service") == "sharepoint" else {}
    path = board.card_path(el)
    item = graph.get(_item_path(m["drive_id"], m["item_id"]) + "?$select=id,cTag,size,webUrl",
                     **kw)
    local = file_sha(path)
    action = refresh_action(m.get("ctag"), item.get("cTag"), m.get("sha256"), local)
    if not force and action != DESCARGAR:
        return action
    if (item.get("size") or 0) > MAX_BYTES:
        raise ValidationError(f"{path.name}: pasa de {MAX_BYTES // (1024 * 1024)} MB")
    data = graph.download(_item_path(m["drive_id"], m["item_id"]) + "/content", **kw)
    if local is not None and local != m.get("sha256"):     # cambiada aquí: a la papelera
        board.ws._trash_fn(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, data)
    _set_m365(board, el, ctag=item.get("cTag"), sha256=sha256(data),
              web_url=item.get("webUrl") or m.get("web_url"))
    board.save()
    return "descargada"


def upload(graph, path, drive_id=None, folder_id=None, scopes=None):
    """Sube una copia de `path` a una carpeta de la nube (M9), con `conflictBehavior=rename`:
    nunca escribe encima. Sin carpeta, a la raíz de mi OneDrive. Devuelve el `driveItem`."""
    path = Path(path)
    data = path.read_bytes()
    name = quote(safe_name(path.name), safe="")
    base = _item_path(drive_id, folder_id) if drive_id and folder_id else "/me/drive/root"
    kw = {"scopes": scopes} if scopes else {}
    if len(data) <= SIMPLE_UPLOAD_MAX:
        return graph.put(f"{base}:/{name}:/content?@microsoft.graph.conflictBehavior=rename",
                         data, **kw)
    session = graph.post(f"{base}:/{name}:/createUploadSession",
                         {"item": {"@microsoft.graph.conflictBehavior": "rename"}}, **kw)
    url, total, result = session["uploadUrl"], len(data), {}
    for start in range(0, total, CHUNK):
        part = data[start:start + CHUNK]
        end = start + len(part) - 1
        response = graph.request("PUT", url, body=part, auth=False, headers={
            "Content-Length": str(len(part)),
            "Content-Range": f"bytes {start}-{end}/{total}"})
        if response.content:
            result = response.json()
    return result
