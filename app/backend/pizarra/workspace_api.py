"""Rutas REST del workspace, sus carpetas y proyectos, y las versiones de un proyecto (plan
§2, D63, D66, D76).

Van aparte de `server.py` (que llegaba a 1000 líneas), como `files_api`; `register` las añade a
la app con las utilidades del servidor. La lista de rutas está en el docstring de `server.py`.
"""
from dataclasses import asdict

from fastapi import Body, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from pizarra import desktop, i18n, profile_zip
from pizarra.config import APP_NAME
from pizarra.settings import RIGHT_PANEL_MIN
from pizarra.startup import StartState, start_view
from pizarra.storage import NotFound
from pizarra.validation import ValidationError

MAX_THUMBNAIL = 2 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PROFILE_MAX = profile_zip.FABRICACION_MAX   # caracteres del perfil de fabricación (V8); al agente, menos


class FolderIn(BaseModel):
    parent: str = ""
    name: str


class FolderPatch(BaseModel):
    path: str
    name: str | None = None
    dest: str | None = None


class ProjectIn(BaseModel):
    folder: str = ""
    name: str


class VersionIn(BaseModel):
    name: str


class ProjectPatch(BaseModel):
    name: str | None = None
    dest: str | None = None


class SkinIn(BaseModel):
    skin: str


class PanelsIn(BaseModel):
    right: float


class RevealIn(BaseModel):
    project: str | None = None
    folder: str | None = None


def _node(n):
    out = {"kind": n.kind, "name": n.name, "path": n.path, "modified": n.modified}
    if n.kind == "project":
        out.update(id=n.id, error=n.error, thumbnail=n.thumbnail)
    else:
        out["children"] = [_node(c) for c in n.children]
    return out


def profile_view(ws):
    """El perfil de fabricación (V8) para *Ajustes → General*: el guardado o, si no hay
    ninguno, la plantilla (que los agentes no leen hasta que se guarda)."""
    text = ws.load_manufacturing_profile()
    template = i18n.t("perfil.plantilla")
    return {"texto": template if text is None else text, "guardado": text is not None,
            "plantilla": template}


def register(app, *, start, settings, workspace, sessions, need_workspace, board_for, broadcast,
             close_sessions, project_dict, init_msg, version_saved=None):
    """Añade las rutas a `app`. `workspace` y `sessions` son None si no hay workspace abierto
    (entonces `need_workspace` contesta 503). `version_saved(sesión, versión)`, si se da, se
    llama tras guardar una versión de un proyecto abierto (el hito del revisor, V5)."""
    # ------------------------------------------------- workspace, carpetas, proyectos
    @app.get("/api/start")
    def get_start():
        view = start_view(StartState(settings, workspace, start.problem))
        if workspace is not None:
            view["workspace"] = asdict(workspace.info())
        view["skin"] = settings.skin
        return view

    # Skin de la pizarra (D79): hasta Ajustes (FF 4.7) se elige en la píldora del proyecto.
    @app.put("/api/settings/skin")
    def put_skin(p: SkinIn):
        try:
            settings.skin = p.skin
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        settings.save()
        return {"skin": settings.skin}

    # Tamaño de los paneles (D60): el ancho del panel derecho (D174), nunca bajo su mínimo.
    @app.get("/api/settings/panels")
    def get_panels():
        return {"right": settings.right_panel, "right_min": RIGHT_PANEL_MIN}

    @app.put("/api/settings/panels")
    def put_panels(p: PanelsIn):
        try:
            settings.right_panel = p.right
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        settings.save()
        return {"right": settings.right_panel, "right_min": RIGHT_PANEL_MIN}

    @app.get("/api/workspace")
    def get_workspace():
        ws = need_workspace()
        tree = ws.tree()
        nodes = {}

        def walk(n):
            if n.kind == "project" and n.id:
                nodes[n.id] = n
            for c in n.children:
                walk(c)
        walk(tree)
        recent = []
        for r in settings.recent(ws.info().id):
            try:
                n = nodes.get(r["id"])
                recent.append({**project_dict(r["id"]), "exists": True,
                               "modified": n.modified if n else 0.0,
                               "thumbnail": bool(n and n.thumbnail)})
            except NotFound:
                recent.append({**r, "exists": False})
        return {"app": APP_NAME, "workspace": {**asdict(ws.info()), "path": str(ws.root)},
                "tree": _node(tree), "recent": recent, "problem": start.problem}

    # Perfil de fabricación del workspace (D31, PLAN_V020 V8): lo leen los dos agentes.
    @app.get("/api/workspace/fabricacion")
    def get_profile():
        return profile_view(need_workspace())

    @app.put("/api/workspace/fabricacion")
    def put_profile(p: dict = Body(...)):
        ws = need_workspace()
        text = p.get("texto") if isinstance(p, dict) else None
        if not isinstance(text, str):
            raise HTTPException(422, i18n.t("perfil.no_texto"))
        if len(text) > PROFILE_MAX:
            raise HTTPException(422, i18n.t("perfil.largo", max=PROFILE_MAX))
        ws.save_manufacturing_profile(text)
        return profile_view(ws)

    @app.post("/api/folders")
    def post_folder(f: FolderIn):
        return {"path": need_workspace().create_folder(f.parent, f.name)}

    @app.patch("/api/folders")
    def patch_folder(f: FolderPatch):
        ws = need_workspace()
        path = f.path
        if f.name is not None:
            path = ws.rename_folder(path, f.name)
        if f.dest is not None:
            path = ws.move_folder(path, f.dest)
        return {"path": path}

    @app.delete("/api/folders")
    async def delete_folder(path: str):
        ws = need_workspace()
        ids = ws.projects_under(path)
        await close_sessions(ids, "trashed")
        ws.trash_folder(path)
        for pid in ids:
            settings.forget_project(ws.info().id, pid)
        settings.save()
        return {"projects": ids}

    @app.post("/api/projects")
    def post_project(p: ProjectIn):
        return asdict(need_workspace().create_project(p.folder, p.name))

    @app.patch("/api/projects/{pid}")
    async def patch_project(pid: str, p: ProjectPatch):
        ws = need_workspace()
        info = ws.project(pid)
        if p.name is not None:
            info = ws.rename_project(pid, p.name)
        if p.dest is not None:
            info = ws.move_project(pid, p.dest)
        settings.touch_project(ws.info().id, pid, info.name, opened=False)
        settings.save()
        s = sessions.get(pid)
        if s is not None:
            await broadcast(s, {"type": "project", "project": asdict(info)})
        return asdict(info)

    @app.delete("/api/projects/{pid}")
    async def delete_project(pid: str):
        ws = need_workspace()
        ws.project(pid)
        await close_sessions([pid], "trashed")
        ws.trash_project(pid)
        settings.forget_project(ws.info().id, pid)
        settings.save()
        return {"projects": [pid]}

    @app.post("/api/reveal")
    def post_reveal(r: RevealIn):
        """Abre en el explorador del sistema un proyecto (por id) o una carpeta (por ruta)."""
        ws = need_workspace()
        target = ws.workdir(r.project) if r.project else ws.folder_dir(r.folder or "")
        desktop.reveal(target)
        return {"ok": True}

    @app.delete("/api/recent/{pid}")
    def forget_recent(pid: str):
        ws = need_workspace()
        settings.forget_project(ws.info().id, pid)
        settings.save()
        return {"ok": True}

    @app.get("/api/projects/{pid}/thumbnail")
    def get_thumbnail(pid: str):
        png = need_workspace().load_thumbnail(pid)
        if png is None:
            raise HTTPException(404, "el proyecto aún no tiene miniatura")
        return Response(png, media_type="image/png")

    @app.put("/api/projects/{pid}/thumbnail")
    async def put_thumbnail(pid: str, request: Request):
        png = await request.body()
        if len(png) > MAX_THUMBNAIL or not png.startswith(PNG_SIGNATURE):
            raise HTTPException(422, "la miniatura tiene que ser un PNG de menos de 2 MB")
        need_workspace().save_thumbnail(pid, png)
        return {"ok": True}

    # ------------------------------------------------------------- versiones (D76)
    async def versions_changed(session):
        if session is not None:
            await broadcast(session, {"type": "versions"})

    @app.get("/api/projects/{pid}/versions")
    def get_versions(pid: str):
        return {"versions": board_for(pid)[0].list_versions()}

    @app.post("/api/projects/{pid}/versions")
    async def post_version(pid: str, v: VersionIn):
        board, session = board_for(pid)
        info = board.save_version(v.name)
        await versions_changed(session)
        if version_saved is not None and session is not None and not info.get("auto"):
            await version_saved(session, info)
        return info

    @app.patch("/api/projects/{pid}/versions/{vid}")
    async def patch_version(pid: str, vid: str, v: VersionIn):
        board, session = board_for(pid)
        info = workspace.rename_version(pid, vid, v.name)
        await versions_changed(session)
        return info

    @app.delete("/api/projects/{pid}/versions/{vid}")
    async def delete_version(pid: str, vid: str):
        board, session = board_for(pid)
        workspace.trash_version(pid, vid)
        await versions_changed(session)
        return {"id": vid}

    @app.get("/api/projects/{pid}/versions/{vid}/thumbnail")
    def get_version_thumbnail(pid: str, vid: str):
        need_workspace()
        png = workspace.load_version_thumbnail(pid, vid)
        if png is None:
            raise HTTPException(404, "esta versión no tiene miniatura")
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.post("/api/projects/{pid}/versions/{vid}/restore")
    async def restore_version(pid: str, vid: str):
        board, session = board_for(pid)
        try:
            auto = board.restore_version(vid)
        except ValidationError as exc:        # hay una ejecución en curso
            raise HTTPException(409, str(exc))
        if session is not None:
            await broadcast(session, init_msg(pid, board))
            await versions_changed(session)
        return {"auto": auto}

    @app.get("/api/projects/{pid}/compare")
    def compare(pid: str, a: str, b: str = "now"):
        return {"changes": board_for(pid)[0].compare(a, b)}
