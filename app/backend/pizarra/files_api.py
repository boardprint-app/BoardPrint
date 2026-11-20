"""Rutas REST de las tarjetas de archivo y de carpeta (plan §3, D59, D109, D131-D141).

Van aparte de `server.py` (que ya pasaba de 900 líneas); `register` las añade a la app con las
utilidades del servidor. Los diálogos del sistema los abre el backend (la interfaz no ve rutas,
D129) en un hilo: bloquean hasta que el usuario elige. Las rutas arrastradas desde el
explorador las da el shell de Tauri.

    POST /api/projects/<id>/cards {paths?, kind?, x, y}   añadir: con `paths` (arrastradas), si
                                                          no, el diálogo de `kind` file|folder
    GET  /api/projects/<id>/cards/<c>                     ruta absoluta, nombre, carpeta y estado
    POST /api/projects/<id>/cards/<c>/open {with}         abrir (un STEP, en Fusion si está
                                                          abierto); `with`: «Abrir con» (D141)
    POST /api/projects/<id>/cards/<c>/reveal              abrir en el explorador, seleccionado
    GET  /api/projects/<id>/cards/<c>/content             lo que hay en la carpeta (su vista)
    POST /api/projects/<id>/cards/<c>/relocate {path?}    «Buscar de nuevo» (D138): sin `path`,
                                                          el diálogo
    POST /api/projects/<id>/cards/<c>/confirm             calcular el hash de una carpeta
                                                          de más de 500 MB (D136)
    POST /api/projects/<id>/blocks/<b>/save-to {path?}    *Guardar también en…* (D109)
    POST /api/projects/<id>/blocks/<b>/links {param,      *Tomar de Excel* (PLAN_EXCEL §3.2):
         card?, name?}                                    enlaza el parámetro a un nombre del
                                                          Excel; sin `card`, quita el enlace
    POST /api/projects/<id>/cards/<c>/writes {name,       qué campo de salida va a un nombre
         block?, port?, field?}                           del Excel (PLAN_EXCEL §3.3); sin
                                                          `block`, nada
    POST /api/projects/<id>/cards/<c>/write-copy          *Escribir copia*: la copia `_n` y su
                                                          propuesta; las fórmulas se recalculan
                                                          después y se añaden a la propuesta
    GET  /api/projects/<id>/cards/<c>/raw                 el archivo tal cual, para
                                                          *Previsualizar* (D135)
    GET|PUT /api/mesh/<hash>                              malla del visor STEP por hash del
                                                          archivo (D62), en la caché de la app
    POST /api/projects/<id>/images                        guardar una imagen pegada (los bytes
                                                          en el cuerpo) en `board/files/` (D84)
    GET  /api/projects/<id>/images/<sha256>.<ext>         una imagen pegada
    GET  /animations/<id>/<sha256>.html                   la animación de un post-it (D175),
                                                          sin token y con la CSP sin red
    POST /api/projects/<id>/links/<c>/open                abrir un enlace en el navegador (D137)
Quitar una tarjeta es borrarla de la escena: nunca toca el archivo. La foto suelta y el enlace
los crea la interfaz al pegar (entran en deshacer); aquí solo se guarda la imagen y se abre el
enlace con la URL de la escena.
"""
import asyncio
import mimetypes
import os
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from pizarra import connectors as connectors_mod, desktop, excel_write, files, i18n, packs as packs_mod, pasted
from pizarra.storage import StorageError
from pizarra.validation import ValidationError

# Lo que el navegador pintaría ejecutando algo (HTML, SVG) sale con la cabecera `sandbox`:
# sin scripts aunque se abra la URL a mano. El PDF no la lleva: rompería el visor del navegador.
SANDBOXED = {"text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "application/xml"}
# La animación de un post-it (D143, D175) la escribe el agente: se sirve aislada como cabecera
# (un `srcdoc` no la lleva). Sin red (`default-src 'none'`: ni fetch, ni WebSocket, ni recursos
# de fuera), solo scripts y estilos en línea e imágenes `data:`, sin formularios ni `<base>`, y
# con `sandbox allow-scripts`: aunque se abra la URL a mano, su origen es opaco y no ve la app.
ANIMATION_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                 "img-src data:; form-action 'none'; base-uri 'none'; sandbox allow-scripts")
ANIMATION_NAME = re.compile(r"^[0-9a-f]{64}\.html$")
# El hash de una malla es el sha256 del archivo (files.file_digest): nada más entra en la ruta
# de la caché. `MESH_FORMAT` va en el nombre: si cambia el formato (frontend/src/mesh.ts), las
# mallas viejas no se leen.
MESH_HASH = re.compile(r"^[0-9a-f]{64}$")
MESH_FORMAT = "m1"
MESH_MAX = 1024 ** 3


def media_type(path):
    """Tipo MIME para enseñarlo en la app: el del sistema y, si no lo sabe, texto para lo que
    es texto (`.toml`, `.log`…) o binario."""
    guess = mimetypes.guess_type(path.name)[0]
    if guess:
        return guess
    return "text/plain" if path.suffix.lower() in TEXT_EXT else "application/octet-stream"


TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg",
            ".log", ".py", ".xml", ".html", ".htm", ".svg"}


class CardsIn(BaseModel):
    paths: list[str] | None = None
    kind: str = "file"
    x: float = 0
    y: float = 0


class OpenCardIn(BaseModel):
    model_config = {"populate_by_name": True}
    with_: bool = Field(False, alias="with")       # «Abrir con» (D141)


class PathIn(BaseModel):
    path: str | None = None


class LinkIn(BaseModel):
    param: str
    card: str | None = None         # sin tarjeta: quitar el enlace
    name: str | None = None


class WriteIn(BaseModel):
    name: str
    block: str | None = None        # sin bloque: el nombre no recibe nada
    port: str | None = None
    field: str | None = None


async def _in_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def register(app, *, board_for, board_changed, probe_now, mesh_dir=None):
    """`board_for(pid) -> (board, sesión | None)`, `board_changed(board, sesión, nuevos)` y
    `probe_now(board, sesión)` (sondea y avisa a las ventanas) son los del servidor.
    `mesh_dir`: carpeta de la caché de mallas del visor STEP (sin ella, no hay caché)."""

    def card_of(board, cid):
        try:
            return board.card(cid)
        except ValidationError as exc:
            raise HTTPException(404, str(exc))

    def checked(fn, *args):
        try:
            return fn(*args)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/projects/{pid}/cards")
    async def post_cards(pid: str, c: CardsIn):
        board, session = board_for(pid)
        paths = c.paths
        if paths is None:
            if c.kind == "folder":
                got = await _in_thread(desktop.choose_folder, i18n.t("dialogo.anadir_carpeta"))
                paths = [got] if got else []
            elif c.kind == "file":
                paths = await _in_thread(desktop.choose_files, i18n.t("dialogo.anadir_archivos"))
            else:
                raise HTTPException(422, i18n.t("tarjeta.tipo_desconocido", tipo=repr(c.kind)))
        if not paths:
            return {"ids": [], "existing": []}       # diálogo cancelado
        # Lo que ya está en la pizarra no se repite: vuelve su tarjeta en `existing` y la
        # interfaz la selecciona (O17). Una ruta dos veces en la misma petición, una tarjeta.
        existing, fresh, seen = [], [], set()
        for p in paths:
            card = board.card_for(p)
            if card is not None:
                if card["id"] not in existing:
                    existing.append(card["id"])
            elif os.path.normcase(str(Path(p).resolve())) not in seen:
                seen.add(os.path.normcase(str(Path(p).resolve())))
                fresh.append(p)
        new = checked(board.add_cards, fresh, c.x, c.y) if fresh else []
        if new:
            await board_changed(board, session, new)
            await probe_now(board, session)
        return {"ids": [e["id"] for e in new], "existing": existing}

    @app.get("/api/projects/{pid}/cards/{cid}")
    def get_card(pid: str, cid: str):
        board, _ = board_for(pid)
        el = card_of(board, cid)
        path = board.card_path(el)
        return {"id": cid, "kind": el["customData"]["kind"], "path": str(path),
                "stored": el["customData"]["path"], "name": path.name,
                "folder": str(path.parent), "exists": path.exists(),
                "type": files.port_type(path) if el["customData"]["kind"] == "file" else files.FOLDER,
                "open_with": desktop.OPEN_WITH,
                **board.sources_view().get(cid, {})}

    @app.post("/api/projects/{pid}/cards/{cid}/open")
    async def open_card(pid: str, cid: str, o: OpenCardIn):
        board, _ = board_for(pid)
        path = board.card_path(card_of(board, cid))
        if not path.exists():
            raise HTTPException(404, i18n.t("tarjeta.ruta_no_encontrada", ruta=path))
        try:
            if o.with_:
                desktop.open_with(path)
                return {"opened": "con"}
            # Con el conector disponible que acepta su extensión, en su programa (D141: un STEP
            # en Fusion); si no, con el del sistema.
            con = connectors_mod.opener(path)
            if con is not None:
                try:
                    await _in_thread(connectors_mod.open_file, con.id, path)
                except Exception as exc:      # noqa: BLE001 el conector de un paquete no tumba la app
                    raise HTTPException(502, packs_mod.action_error(f"{con.id}.open_file", exc))
                return {"opened": con.id}
            desktop.open_file(path)
            return {"opened": "sistema"}
        except OSError as exc:
            raise HTTPException(500, i18n.t("tarjeta.no_abre", motivo=exc))

    @app.post("/api/projects/{pid}/cards/{cid}/reveal")
    def reveal_card(pid: str, cid: str):
        board, _ = board_for(pid)
        path = board.card_path(card_of(board, cid))
        if not path.exists():
            raise HTTPException(404, i18n.t("tarjeta.ruta_no_encontrada", ruta=path))
        desktop.reveal_file(path)
        return {"ok": True}

    @app.get("/api/projects/{pid}/cards/{cid}/raw")
    def card_raw(pid: str, cid: str):
        """El archivo de una tarjeta, para *Previsualizar* (D135). Solo el de una tarjeta de
        la pizarra: la ruta la da la escena, nunca la interfaz."""
        board, _ = board_for(pid)
        el = card_of(board, cid)
        if el["customData"]["kind"] != "file":
            raise HTTPException(422, i18n.t("tarjeta.carpeta_sin_vista_previa"))
        path = board.card_path(el)
        if not path.is_file():
            raise HTTPException(404, i18n.t("tarjeta.ruta_no_encontrada", ruta=path))
        kind = media_type(path)
        headers = {"Cache-Control": "no-cache", "Content-Disposition": "inline",
                   "X-Content-Type-Options": "nosniff"}
        if kind in SANDBOXED or kind.startswith("text/"):
            headers["Content-Security-Policy"] = "sandbox"
        if kind.startswith("text/"):
            kind += "; charset=utf-8"
        return FileResponse(path, media_type=kind, headers=headers)

    def mesh_path(digest):
        if mesh_dir is None:
            raise HTTPException(404, "sin caché de mallas")
        if not MESH_HASH.match(digest):
            raise HTTPException(422, "el hash de una malla es un sha256 en hexadecimal")
        return Path(mesh_dir) / f"{digest}.{MESH_FORMAT}"

    @app.get("/api/mesh/{digest}")
    def get_mesh(digest: str):
        """La malla, o 204 si no está: no estar en la caché es lo normal la primera vez, no un
        error (un 404 dejaría un error en la consola cada vez)."""
        path = mesh_path(digest)
        if not path.is_file():
            return Response(status_code=204)
        return FileResponse(path, media_type="application/octet-stream")

    @app.put("/api/mesh/{digest}")
    async def put_mesh(digest: str, request: Request):
        """Guarda la malla que ha calculado el visor (D62), para no volver a leer el STEP."""
        body = await request.body()     # antes de rechazar: si no, la conexión se queda a medias
        path = mesh_path(digest)
        if not body or len(body) > MESH_MAX:
            raise HTTPException(422, "malla vacía o demasiado grande")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.replace(tmp, path)
        return {"ok": True, "size": len(body)}

    @app.get("/api/projects/{pid}/cards/{cid}/content")
    async def card_content(pid: str, cid: str):
        board, _ = board_for(pid)
        el = card_of(board, cid)
        if el["customData"]["kind"] != "folder":
            raise HTTPException(422, i18n.t("tarjeta.contenido_solo_carpeta"))
        path = board.card_path(el)
        if not path.is_dir():
            raise HTTPException(404, i18n.t("tarjeta.carpeta_no_encontrada", ruta=path))
        content = files.Content.from_card(el["customData"].get("content"))
        entries, cut = await _in_thread(files.tree, path, content)
        return {"entries": entries, "cut": cut, "everything": content.everything}

    @app.post("/api/projects/{pid}/cards/{cid}/relocate")
    async def relocate_card(pid: str, cid: str, p: PathIn):
        board, session = board_for(pid)
        el = card_of(board, cid)
        path = p.path
        if path is None:
            if el["customData"]["kind"] == "folder":
                path = await _in_thread(desktop.choose_folder, i18n.t("dialogo.buscar_carpeta"))
            else:
                got = await _in_thread(desktop.choose_files, i18n.t("dialogo.buscar_archivo"), (), False)
                path = got[0] if got else None
        if not path:
            return {"id": None}
        new = checked(board.relocate_card, cid, path)
        await board_changed(board, session, [new])
        await probe_now(board, session)
        return {"id": cid}

    @app.post("/api/projects/{pid}/cards/{cid}/confirm")
    async def confirm_card(pid: str, cid: str):
        board, session = board_for(pid)
        card_of(board, cid)
        new = checked(board.confirm_big, cid)
        await board_changed(board, session, [new])
        await probe_now(board, session)
        return {"id": cid}

    @app.post("/api/projects/{pid}/blocks/{bid}/save-to")
    async def save_to(pid: str, bid: str, p: PathIn):
        board, session = board_for(pid)
        path = p.path or await _in_thread(desktop.choose_folder, i18n.t("dialogo.guardar_tambien"))
        if not path:
            return {"ids": []}
        new = checked(board.save_to, bid, Path(path))
        await board_changed(board, session, new)
        await probe_now(board, session)
        return {"ids": [e["id"] for e in new]}

    @app.post("/api/projects/{pid}/blocks/{bid}/links")
    async def post_link(pid: str, bid: str, body: LinkIn):
        """Enlaza un parámetro del bloque a un nombre de una tarjeta de Excel, o quita el
        enlace (el parámetro se queda con el último valor). Devuelve los enlaces del bloque,
        como van en `blocks_view`; un enlace que no vale es un 422 con el motivo."""
        board, session = board_for(pid)
        if body.card is None:
            checked(board.unlink_param, bid, body.param)
        else:
            await _in_thread(checked, board.link_param, bid, body.param, body.card,
                             body.name or "")
        await board_changed(board, session, [])
        return {"links": board.blocks_view()["blocks"].get(bid, {}).get("links") or {}}

    @app.post("/api/projects/{pid}/cards/{cid}/writes")
    async def post_write(pid: str, cid: str, body: WriteIn):
        """Elige el campo de salida que va a un nombre del Excel (o lo quita). Devuelve lo que
        la tarjeta enseña para escribir; uno que no vale (la unidad, una fórmula…), un 422."""
        board, session = board_for(pid)
        card_of(board, cid)
        new = await _in_thread(checked, excel_write.set_write, board, cid, body.name,
                               body.block, body.port, body.field)
        await board_changed(board, session, [new])
        return {"write": board.sources_view().get(cid, {}).get("write")}

    tasks = set()           # los recálculos de las copias en marcha (que no los recoja el GC)

    @app.post("/api/projects/{pid}/cards/{cid}/write-copy")
    async def write_copy(pid: str, cid: str):
        """*Escribir copia* (PLAN_EXCEL §3.3): la propuesta sale ya con las celdas escritas; las
        fórmulas con nombre de la copia se recalculan en un hilo y se añaden al acabar (R4)."""
        board, session = board_for(pid)
        card_of(board, cid)
        p, finish = await _in_thread(checked, excel_write.write_copy, board, cid)
        await board_changed(board, session, [])
        if finish is not None:
            async def complete():
                try:
                    result = await _in_thread(finish)
                except Exception:       # noqa: BLE001 la copia ya no está (rechazada): nada
                    return
                if excel_write.apply_calc(board, p["id"], result):
                    await board_changed(board, session, [])
            task = asyncio.create_task(complete())
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return {"proposal": p["id"], "nuevo": Path(p["change"]["file"]["nuevo"]).name}

    @app.post("/api/projects/{pid}/images")
    async def post_image(pid: str, request: Request):
        """Una imagen pegada (D84, D140): se guarda por su contenido y se devuelve su nombre,
        que la interfaz pone en el post-it o en la foto suelta. El tipo sale de sus bytes."""
        body = await request.body()
        board, _ = board_for(pid)
        if len(body) > pasted.IMAGE_MAX:
            raise HTTPException(413, i18n.t("imagen.demasiado_grande", mb=pasted.IMAGE_MAX // 1024 ** 2))
        ext = pasted.image_ext(body)
        if ext is None:
            raise HTTPException(422, i18n.t("imagen.formato"))
        return {"file": board.ws.save_board_file(board.project_id, body, ext)}

    @app.get("/api/projects/{pid}/images/{name}")
    def get_image(pid: str, name: str):
        board, _ = board_for(pid)
        if name.rpartition(".")[2] not in pasted.IMAGE_EXT:
            raise HTTPException(404, "no es una imagen de la pizarra")     # una animación, no
        path = board.ws.board_file(board.project_id, name)
        # El nombre es el hash del contenido: nunca cambia, se puede guardar para siempre.
        return FileResponse(path, media_type=pasted.MEDIA_TYPE[path.suffix[1:]],
                            headers={"Cache-Control": "private, max-age=31536000, immutable",
                                     "X-Content-Type-Options": "nosniff"})

    @app.get("/animations/{pid}/{name}")
    def get_animation(pid: str, name: str):
        """La animación de un post-it (D175) para su `iframe`. Fuera de `/api/`, sin token: el
        `iframe` lo llevaría en su URL y la animación, que escribe el agente, lo leería. La
        URL es su hash: solo la conoce quien tiene el post-it. Siempre con la CSP sin red,
        también la respuesta de lo que no se sirve."""
        hdrs = {"Content-Security-Policy": ANIMATION_CSP, "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer"}
        if not ANIMATION_NAME.match(name):
            raise HTTPException(404, "no es una animación de la pizarra", headers=hdrs)
        try:
            board, _ = board_for(pid)
            path = board.ws.board_file(board.project_id, name)
        except HTTPException as exc:
            raise HTTPException(exc.status_code, exc.detail, headers=hdrs)
        except StorageError:              # ni el proyecto ni el archivo: 404
            raise HTTPException(404, "no hay esa animación", headers=hdrs)
        # El nombre es el hash del contenido: lo que se sirve nunca cambia (los errores, sin caché)
        return FileResponse(path, media_type="text/html; charset=utf-8",
                            headers={**hdrs,
                                     "Cache-Control": "private, max-age=31536000, immutable"})

    @app.post("/api/projects/{pid}/links/{cid}/open")
    def open_link(pid: str, cid: str):
        board, _ = board_for(pid)
        desktop.open_url(checked(board.link_url, cid))
        return {"ok": True}
