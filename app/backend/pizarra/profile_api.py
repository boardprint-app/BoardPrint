"""Rutas REST del perfil `.zip` del workspace (docs/PLAN_LIBRERIA.md §5, L8-L10).

    POST /api/profile/export          {carpeta?, con_stock} -> {file, nombre, fichas, stock…}
    POST /api/profile/import/inspect  {ruta?} -> resumen + {token}
    POST /api/profile/import/apply    {token} -> {copia, fichas, quitadas, fabricacion, stock}

Sin `carpeta` (o sin `ruta`), abre el diálogo del sistema (`choose_folder`, `choose_file`);
cancelado, `{file: null}`. Un zip o una carpeta que no valen son 422; un resumen caducado o
que ya no cuadra con el zip o el perfil, 409 (`Conflict`, como importar un CSV).
"""
import asyncio
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from pizarra import desktop, i18n, profile_zip, update_api
from pizarra.validation import ValidationError


class ExportIn(BaseModel):
    carpeta: str | None = None
    con_stock: bool = False


class InspectIn(BaseModel):
    ruta: str | None = None


class ApplyIn(BaseModel):
    token: str


async def _in_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def register(app, *, need_workspace, settings):
    """`need_workspace()` es el del servidor (503 sin workspace); de `settings` sale la carpeta
    donde el shell deja la versión de la app (`update_api.app_version`)."""
    folder = Path(settings.path).parent

    def checked(fn, *args):
        try:
            return fn(*args)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/profile/export")
    async def post_export(p: ExportIn):
        ws = need_workspace()
        carpeta = p.carpeta
        if not carpeta:
            carpeta = await _in_thread(desktop.choose_folder, i18n.t("dialogo.exportar_perfil"))
            if not carpeta:
                return {"file": None}
        return await _in_thread(checked, profile_zip.export, ws, carpeta, p.con_stock,
                                update_api.app_version(folder))

    @app.post("/api/profile/import/inspect")
    async def post_inspect(p: InspectIn):
        ws = need_workspace()
        ruta = p.ruta
        if not ruta:
            ruta = await _in_thread(desktop.choose_file, i18n.t("dialogo.importar_perfil"),
                                    [(i18n.t("dialogo.perfil_zip"), "*.zip")])
            if not ruta:
                return {"file": None}
        return await _in_thread(checked, profile_zip.plan, ws, ruta)

    @app.post("/api/profile/import/apply")
    async def post_apply(a: ApplyIn):
        ws = need_workspace()
        return await _in_thread(checked, profile_zip.apply, ws, a.token)
