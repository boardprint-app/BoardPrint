"""API de Microsoft 365 (docs/PLAN_M365.md §3): la cuenta de *Ajustes → Cuentas*.

    GET    /api/m365            {configured, account|null, sharepoint}
    POST   /api/m365/sign-in    {sharepoint?}   abre el navegador y espera (M2)
    POST   /api/m365/sign-out
    GET    /api/m365/drive?drive_id&item_id&service   lo de dentro de una carpeta (M14)
    GET    /api/m365/drive/search?q
    POST   /api/projects/{pid}/m365/bring   {drive_id, item_id, service, x, y} (M6)
    GET    /api/m365/sites?q    GET /api/m365/sites/{id}/drives       SharePoint (M4)
    GET    /api/m365/mail/folders    GET /api/m365/mail?folder&q       Correo (M10)
    POST   /api/projects/{pid}/m365/mail/bring   {message_id, attachments, x, y}
    POST   /api/projects/{pid}/m365/cards/{cid}/refresh   {force}   (M7, M8)
    POST   /api/projects/{pid}/m365/cards/{cid}/upload    {service, drive_id, folder_id} (M9)

WebSocket: `{"type": "m365", "cards": {id: al_dia|descargada|conflicto|sin_conexion}}` tras cada
pasada del sondeo y cada *Actualizar*; `{"type": "m365"}` al iniciar o cerrar sesión.

Los fallos de Microsoft vuelven como 409 con el texto en el idioma de la app; un inicio de
sesión a la vez (otro mientras tanto, 409).
"""
import asyncio
import threading

from urllib.parse import quote

from pizarra import desktop, i18n, m365_files, m365_mail
from pizarra.validation import ValidationError
from pizarra.m365_auth import (SCOPES_BASE, SCOPES_SHAREPOINT, M365Error, NeedsConsent,
                               NotConfigured, NotSignedIn, SignInFailed)
from pizarra.m365_graph import Graph, GraphError, Offline

WATCH_EVERY = 60                # s: el sondeo de la nube (M7)
SIN_CONEXION = "sin_conexion"


def view(auth):
    """La cuenta sin red: lo que hay en la caché. `sharepoint` dice si ya se dio su permiso."""
    configured = auth.configured()
    account = auth.account() if configured else None
    return {"configured": configured, "account": account,
            "sharepoint": bool(account) and auth.has_scopes(SCOPES_SHAREPOINT)}


def message(exc):
    """El texto de un fallo de Microsoft 365, para la interfaz y para el agente."""
    if isinstance(exc, NotConfigured):
        return i18n.t("m365.sin_configurar")
    if isinstance(exc, NotSignedIn):
        return i18n.t("m365.sin_sesion")
    if isinstance(exc, NeedsConsent):
        return i18n.t("m365.falta_permiso")
    if isinstance(exc, SignInFailed):
        return i18n.t("m365.inicio_fallido", motivo=str(exc) or "-")
    if isinstance(exc, Offline):
        return i18n.t("m365.sin_conexion")
    if isinstance(exc, GraphError):
        return i18n.t("m365.error_graph", estado=exc.status, motivo=exc.message or exc.code)
    return str(exc)


def graph_for(auth, transport=None):
    kw = {"transport": transport} if transport is not None else {}
    return Graph(lambda scopes, fresh: auth.token(scopes, fresh), **kw)


def register(app, *, auth, sessions, broadcast, board_for=None, board_changed=None,
             probe_now=None, transport=None):
    from fastapi import Body, HTTPException
    busy = threading.Lock()
    graph = graph_for(auth, transport)

    async def graph_call(fn, *args, **kw):
        """Una llamada a Graph en un hilo; sus fallos, como 409 con el texto de la app."""
        try:
            return await asyncio.to_thread(fn, *args, **kw)
        except M365Error as exc:
            raise HTTPException(409, message(exc))
        except ValidationError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/m365/drive")
    async def drive(drive_id: str = "", item_id: str = "", service: str = "onedrive"):
        """Lo de dentro de una carpeta de la nube; sin ella, la raíz de mi OneDrive (§3)."""
        scopes = SCOPES_SHAREPOINT if service == "sharepoint" else None
        items = await graph_call(m365_files.children, graph, drive_id or None, item_id or None,
                                 service, scopes)
        return {"items": items}

    @app.get("/api/m365/drive/search")
    async def drive_search(q: str = ""):
        return {"items": await graph_call(m365_files.search, graph, q)}

    @app.post("/api/projects/{pid}/m365/bring")
    async def bring(pid: str, body: dict = Body(...)):
        """Trae un archivo de la nube a la pizarra (M6). `{drive_id, item_id, service, x, y}`."""
        board, session = board_for(pid)
        service = body.get("service") or "onedrive"
        scopes = SCOPES_SHAREPOINT if service == "sharepoint" else None
        el, new = await graph_call(m365_files.bring, board, graph, str(body.get("drive_id") or ""),
                                   str(body.get("item_id") or ""), body.get("x"), body.get("y"),
                                   service, "user", scopes)
        if new:
            await board_changed(board, session, [el])
            await probe_now(board, session)
        return {"ids": [el["id"]] if new else [], "existing": [] if new else [el["id"]]}

    @app.post("/api/m365/open")
    async def open_web(body: dict = Body(...)):
        """*Abrir en la web* / *Abrir en Outlook*: la URL la da Graph, nunca la interfaz (D137).
        `{service, drive_id, item_id}`; en un correo, `item_id` es el id del mensaje."""
        service, item_id = body.get("service"), str(body.get("item_id") or "")
        if service == "correo":
            got = await graph_call(graph.get, "/me/messages/"
                                   f"{quote(item_id, safe='')}?$select=webLink")
            url = got.get("webLink")
        else:
            scopes = SCOPES_SHAREPOINT if service == "sharepoint" else SCOPES_BASE
            got = await graph_call(graph.get, m365_files._item_path(
                str(body.get("drive_id") or ""), item_id) + "?$select=webUrl", scopes=scopes)
            url = got.get("webUrl")
        if not url or not str(url).startswith("https://"):
            raise HTTPException(409, i18n.t("m365.sin_enlace"))
        await asyncio.to_thread(desktop.open_url, url)
        return {"ok": True}

    @app.get("/api/m365/mail/folders")
    async def mail_folders():
        return {"items": await graph_call(m365_mail.folders, graph)}

    @app.get("/api/m365/mail")
    async def mail_list(folder: str = "inbox", q: str = ""):
        return {"items": await graph_call(m365_mail.messages, graph, folder, q)}

    @app.post("/api/projects/{pid}/m365/mail/bring")
    async def mail_bring(pid: str, body: dict = Body(...)):
        """Un correo como `.eml` y, con `attachments`, sus adjuntos (M10)."""
        board, session = board_for(pid)
        new, notes, mail = await graph_call(
            m365_mail.bring_message, board, graph, str(body.get("message_id") or ""),
            bool(body.get("attachments")), body.get("x"), body.get("y"), "user")
        if new:
            await board_changed(board, session, new)
            await probe_now(board, session)
        ids = [e["id"] for e in new]
        return {"ids": ids, "existing": [] if mail["id"] in ids else [mail["id"]],
                "notes": notes}

    @app.get("/api/m365/sites")
    async def get_sites(q: str = ""):
        return {"items": await graph_call(m365_files.sites, graph, q, SCOPES_SHAREPOINT)}

    @app.get("/api/m365/sites/{site_id}/drives")
    async def get_site_drives(site_id: str):
        return {"items": await graph_call(m365_files.site_drives, graph, site_id,
                                          SCOPES_SHAREPOINT)}

    def cloud_card(board, cid):
        el = next((e for e in m365_files.cloud_cards(board) if e["id"] == cid), None)
        if el is None:
            raise HTTPException(404, i18n.t("tarjeta.no_existe", id=repr(cid)))
        return el

    async def refresh_one(board, session, el, force=False):
        """Una tarjeta de la nube: su estado nuevo, ya avisado a las ventanas (M7, M8)."""
        try:
            state = await asyncio.to_thread(m365_files.refresh, board, graph, el, force)
        except (M365Error, ValidationError, OSError):
            # Sin red, sin sesión o el archivo ya no está en la nube: la tarjeta se queda con
            # la última copia, nunca en `error` (M7).
            state = SIN_CONEXION
        states = board.__dict__.setdefault("m365_states", {})
        states[el["id"]] = state
        if state == "descargada" and session is not None:
            fresh = next(e for e in board.elements if e["id"] == el["id"])
            await board_changed(board, session, [fresh])
            await probe_now(board, session)
        if session is not None:
            await broadcast(session, {"type": "m365", "cards": dict(states)})
        return state

    @app.post("/api/projects/{pid}/m365/cards/{cid}/refresh")
    async def post_refresh(pid: str, cid: str, body: dict = Body(default={})):
        """*Actualizar desde la nube*; con `force`, *Traer la de la nube* (M8)."""
        board, session = board_for(pid)
        el = cloud_card(board, cid)
        return {"state": await refresh_one(board, session, el, bool((body or {}).get("force")))}

    @app.post("/api/projects/{pid}/m365/cards/{cid}/upload")
    async def post_upload(pid: str, cid: str, body: dict = Body(default={})):
        """*Guardar en la nube* (M9): una copia de la tarjeta, nunca encima de nada."""
        board, _ = board_for(pid)
        try:
            el = board.card(cid)
        except ValidationError as exc:
            raise HTTPException(404, str(exc))
        if el["customData"].get("kind") != "file":
            raise HTTPException(422, i18n.t("m365.solo_archivos"))
        scopes = SCOPES_SHAREPOINT if (body or {}).get("service") == "sharepoint" else None
        item = await graph_call(m365_files.upload, graph, board.card_path(el),
                                (body or {}).get("drive_id") or None,
                                (body or {}).get("folder_id") or None, scopes)
        return {"name": item.get("name") or "", "web_url": item.get("webUrl") or "",
                "drive_id": (item.get("parentReference") or {}).get("driveId"),
                "item_id": item.get("id")}

    async def watch():
        """El sondeo de la nube (M7): cada `WATCH_EVERY` s, las tarjetas de la nube de los
        proyectos abiertos, solo con sesión de Microsoft."""
        while True:
            await asyncio.sleep(WATCH_EVERY)
            try:
                if sessions is None or not await asyncio.to_thread(auth.account):
                    continue
                for s in sessions.all():
                    for el in m365_files.cloud_cards(s.board):
                        await refresh_one(s.board, s, el)
            except Exception:       # noqa: BLE001 el vigilante no se para por un fallo suelto
                pass

    async def changed():
        for s in sessions.all() if sessions is not None else []:
            await broadcast(s, {"type": "m365"})

    @app.get("/api/m365")
    async def get_m365():
        return await asyncio.to_thread(view, auth)

    @app.post("/api/m365/sign-in")
    async def sign_in(body: dict = Body(default={})):
        scopes = SCOPES_SHAREPOINT if (body or {}).get("sharepoint") else SCOPES_BASE
        if not busy.acquire(blocking=False):
            raise HTTPException(409, i18n.t("m365.inicio_en_curso"))
        try:
            await asyncio.to_thread(auth.sign_in, scopes)
        except M365Error as exc:
            raise HTTPException(409, message(exc))
        finally:
            busy.release()
        await changed()
        return await asyncio.to_thread(view, auth)

    @app.post("/api/m365/sign-out")
    async def sign_out():
        await asyncio.to_thread(auth.sign_out)
        await changed()
        return await asyncio.to_thread(view, auth)

    return watch
