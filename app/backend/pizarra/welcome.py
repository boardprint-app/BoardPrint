"""La bienvenida (el onboarding) y el aviso de la primera animación (docs/PLAN_PIZARRA.md
D186, D187).

Rutas (`register`):

    POST /api/welcome/session            `claude auth status` (claude_session): {estado, cuenta,
                                         plan, motivo}; no gasta tokens
    POST /api/welcome/login              abre `claude auth login` en una consola: {ok}
    POST /api/welcome/install            abre en el navegador la página para instalar
                                         Claude Code (O13): {ok}
    POST /api/welcome/folder             diálogo del sistema para elegir carpeta: {ruta, nube};
                                         no cambia nada
    POST /api/welcome/workspace {ruta}   abre allí el workspace (o crea uno) y pasa a ser el
                                         actual: {reinicio}. Con `reinicio`, el servidor vuelve
                                         a arrancar en el mismo puerto y la ventana recarga

**Cambiar de carpeta nunca toca la de antes**: ni la mueve, ni la borra, ni la recrea; se
queda en disco y en `settings.toml`. Una carpeta que ya tiene `workspace.toml` se abre tal
cual (p. ej. al reinstalar), sin crear otro.
"""
import asyncio
import os
from pathlib import Path

from pizarra import claude_session, cloud, i18n
from pizarra.storage import LocalWorkspace, StorageError

NOTICE_FLAG = "aviso_animacion"         # en `[agentes]` de project.toml (D187)


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def location(workspace):
    """{nombre, ruta, nube} del workspace abierto (None si no hay)."""
    if workspace is None:
        return None
    root = getattr(workspace, "root", None)
    return {"nombre": workspace.info().name, "ruta": str(root) if root else None,
            "nube": cloud.service(os.path.realpath(root)) if root else None}


def switch_workspace(settings, path):
    """Abre (o crea) el workspace de `path` y lo deja como el actual en `settings` (sin
    guardar). Devuelve el `WorkspaceInfo`. ValueError si la ruta no vale; StorageError si su
    `workspace.toml` no se puede leer."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError(i18n.t("bienvenida.falta_carpeta"))
    p = Path(path.strip())
    if not p.is_absolute():
        raise ValueError(i18n.t("bienvenida.ruta_no_absoluta", ruta=path))
    if p.exists() and not p.is_dir():
        raise ValueError(i18n.t("bienvenida.no_es_carpeta", ruta=p))
    info = LocalWorkspace.open(p).info()
    known = next((w for w in settings.workspaces() if _same(w["path"], p)), None)
    if known is None:
        same_id = settings.workspace(info.id)
        if same_id is not None:             # la misma carpeta movida (mismo id): su ruta nueva
            same_id["path"] = str(p)
        else:
            settings.add_workspace(info.id, info.name, p)
    settings.data["current_workspace"] = (known or {}).get("id") or info.id
    return info


def first_animation(workspace, project_id, auto):
    """¿Hay que avisar de la primera animación del proyecto? (D187) Sí una sola vez por
    proyecto, y nunca con «Animaciones automáticas» desactivado. Al decir que sí, la marca
    queda en `project.toml`."""
    if not auto:
        return False
    agents = workspace.load_project_agent_settings(project_id)
    if agents.get(NOTICE_FLAG) is True:
        return False
    workspace.save_project_agent_settings(project_id, {**agents, NOTICE_FLAG: True})
    return True


def register(app, *, settings, workspace, claude_cli=None, restart=None):
    from fastapi import HTTPException
    from pydantic import BaseModel

    from pizarra import desktop

    class FolderIn(BaseModel):
        ruta: str

    @app.post("/api/welcome/session")
    async def check_session():
        return await asyncio.to_thread(claude_session.status, claude_cli)

    @app.post("/api/welcome/install")
    def open_install_page():
        """Abre la página de Claude Code en el navegador (O13): una URL fija, nunca una que
        llegue de la interfaz."""
        desktop.open_url(claude_session.INSTALL_URL)
        return {"ok": True}

    @app.post("/api/welcome/login")
    def open_login():
        return {"ok": claude_session.login(claude_cli)}

    @app.post("/api/welcome/folder")
    async def choose_folder():
        got = await asyncio.to_thread(desktop.choose_folder,
                                      i18n.t("bienvenida.dialogo_carpeta", settings.language))
        if not got:
            return {"ruta": None, "nube": None}
        return {"ruta": got, "nube": cloud.service(os.path.realpath(got))}

    @app.post("/api/welcome/workspace")
    async def put_workspace(p: FolderIn):      # async: restart() usa el bucle del servidor
        if workspace is not None and getattr(workspace, "root", None) is not None \
                and _same(workspace.root, p.ruta):
            return {"reinicio": False}
        try:
            switch_workspace(settings, p.ruta)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except (StorageError, OSError) as exc:
            raise HTTPException(409, str(exc))
        settings.save()
        if restart is None:                 # sin quien lo rearranque: vale al volver a abrir
            return {"reinicio": False, "al_abrir": True}
        restart()
        return {"reinicio": True}
