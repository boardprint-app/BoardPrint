"""Rutas de *Ajustes → Paquetes* (docs/PLAN_PAQUETES.md §7, P78, P82-P84).

- `GET /api/packs`: los paquetes con su origen, versión, autor, código y librerías, si están en
  otro origen, quién los pide y su error; y a dónde se puede instalar.
- `POST /api/packs/uploads?name=x.bppack`: el archivo en el cuerpo (soltarlo sobre la
  ventana, P82); devuelve una ruta para `inspect`.
- `POST /api/packs/inspect {paths?, target}`: el resumen (`pack_install.Plan`). Sin `paths`,
  el diálogo del sistema para elegir los `.bppack`.
- `POST /api/packs/install {token}`, `DELETE /api/packs/inspect/{token}`.
- `POST /api/packs/{id}/uninstall {origin}`.
- `POST /api/packs/{id}/export {folder?}` (sin carpeta, el diálogo del sistema) y
  `GET /api/packs/{id}/export` (una descarga, para el navegador).

Instalar y desinstalar se niegan (409) mientras un bloque se ejecuta (P83): recargar el
registro con una ejecución a medias la dejaría con otro paquete. Al terminar, `changed()`
recarga y avisa a las ventanas.
"""
import asyncio
import re
import secrets
import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from pizarra import blocks as blocks_mod
from pizarra import desktop, i18n, pack_host, pack_install

UPLOAD_MAX = 64 * 1024 * 1024
UPLOADS = "subidas"
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_PLANS = 8


class InspectIn(BaseModel):
    paths: list[str] | None = None
    target: str = "usuario"


class TokenIn(BaseModel):
    token: str


class UninstallIn(BaseModel):
    origin: str


class ExportIn(BaseModel):
    folder: str | None = None


async def _in_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def pack_list(reg):
    """Lo que enseña *Ajustes → Paquetes* (§7)."""
    out = []
    for p in reg.packs:
        folder = Path(p.path)
        out.append({"id": p.id, "name": p.name or p.id, "version": p.version, "author": p.author,
                    "description": p.description, "origin": p.origin, "path": p.path,
                    "shadowed": list(p.shadowed), "error": p.error, "requires": dict(p.requires),
                    "libraries": list(p.dependencies),
                    "code": any(folder.rglob("*.py")) if folder.is_dir() else False,
                    "required_by": pack_install.dependents(p.id, reg.packs),
                    "removable": p.origin in pack_install.TARGETS,
                    # sus catálogos (O15): desde el inicio no hay catálogo de bloques cargado
                    "i18n": p.i18n if p.error is None else {}})
    return out


def register(app, *, busy, changed, drafts=None):
    """`busy()`: hay un bloque ejecutándose en alguna pizarra. `changed()` (corrutina): recarga
    el registro y avisa a las ventanas."""
    plans = {}

    def reg():
        return blocks_mod.REGISTRY

    def targets():
        return {o: d for o, d in reg().origins if o in pack_install.TARGETS}

    def uploads_dir():
        t = targets()
        base = t.get("usuario") or next(iter(t.values()), None)
        if base is None:
            raise HTTPException(503, i18n.t("paquete.sin_destino"))
        return Path(base) / pack_install.WORK / UPLOADS

    def need_idle():
        if busy():
            raise HTTPException(409, i18n.t("paquete.ejecucion_en_curso"))

    def pack_info(pack_id):
        p = next((p for p in reg().packs if p.id == pack_id), None)
        if p is None:
            raise HTTPException(404, i18n.t("paquete.no_existe", id=repr(pack_id)))
        return p

    @app.get("/api/packs")
    def get_packs():
        return {"packs": pack_list(reg()), "targets": targets()}

    @app.post("/api/packs/uploads")
    async def post_upload(request: Request, name: str = "paquete.bppack"):
        body = await request.body()     # antes de rechazar: si no, la conexión se queda a medias
        if not body or len(body) > UPLOAD_MAX:
            raise HTTPException(422, i18n.t("paquete.subida_no_valida"))
        # cada uno en su carpeta, con su nombre: el resumen dice qué archivo es cuál
        d = uploads_dir() / secrets.token_hex(6)
        d.mkdir(parents=True, exist_ok=True)
        stem = SAFE_NAME.sub("_", Path(name).stem)[:80] or "paquete"
        path = d / f"{stem}{pack_install.SUFFIX}"
        path.write_bytes(body)
        return {"path": str(path)}

    @app.post("/api/packs/inspect")
    async def post_inspect(body: InspectIn):
        paths = body.paths
        if paths is None:
            paths = await _in_thread(desktop.choose_files, "Instalar paquetes",
                                     [("Paquete de BoardPrint", f"*{pack_install.SUFFIX}")])
        if not paths:
            return {"cancelled": True}
        r = reg()
        # en la app, la carga de prueba va a un trabajador nuevo (PLAN_PAQUETES P95), en el
        # entorno con las librerías de todos, el paquete nuevo incluido (P92)
        resolve = None
        trial = pack_install.trial_load
        if isinstance(r.host, pack_host.WorkerHost):
            trial = pack_host.trial_with(r.host.spec)
            if r.host.env is not None:
                env = r.host.env

                def resolve(origins):
                    return pack_host.trial_with(env.spec(origins))
        try:
            plan = await _in_thread(lambda: pack_install.inspect(
                paths, body.target, r.origins, loaded=r.packs, validated=r.validated,
                trial=trial, resolve=resolve))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        while len(plans) >= MAX_PLANS:                  # el más viejo
            plans.pop(next(iter(plans))).discard()
        plans[plan.token] = plan
        return plan.view()

    @app.delete("/api/packs/inspect/{token}")
    def delete_inspect(token: str):
        plan = plans.pop(token, None)
        if plan is not None:
            plan.discard()
        return {"ok": True}

    @app.post("/api/packs/install")
    async def post_install(body: TokenIn):
        need_idle()
        plan = plans.pop(body.token, None)
        if plan is None:
            raise HTTPException(404, i18n.t("paquete.resumen_caducado"))
        try:
            ids = await _in_thread(pack_install.install, plan)
        except ValueError as exc:
            plan.discard()
            raise HTTPException(422, str(exc))
        await changed()
        return {"installed": ids, "packs": pack_list(reg())}

    @app.post("/api/packs/{pack_id}/uninstall")
    async def post_uninstall(pack_id: str, body: UninstallIn):
        need_idle()
        r = reg()
        try:
            await _in_thread(pack_install.uninstall, pack_id, body.origin, r.origins, r.packs)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        await changed()
        return {"packs": pack_list(reg())}

    def find():
        chosen = {p.id: Path(p.path) for p in reg().packs}
        return chosen.get

    @app.post("/api/packs/{pack_id}/export")
    async def post_export(pack_id: str, body: ExportIn):
        p = pack_info(pack_id)
        folder = body.folder
        if folder is None:
            folder = await _in_thread(desktop.choose_folder, i18n.t("paquete.dialogo_exportar",
                                                                     nombre=p.name or p.id))
            if not folder:
                return {"cancelled": True}
        try:
            path = await _in_thread(pack_install.export, p.path, folder, find())
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc))
        return {"path": str(path)}

    @app.post("/api/packs/drafts/{pack_id}/export")
    async def post_draft_export(pack_id: str):
        """*Instalar* de la tarjeta de un paquete que propone el agente (P102): el `.bppack` del
        borrador, si sigue igual que al validarlo, para abrir el resumen de instalar."""
        from pizarra import agent_packs
        if drafts is None:
            raise HTTPException(404, i18n.t("paquete.sin_borradores"))
        out = Path(drafts) / ".exportados" / secrets.token_hex(4)
        try:
            path, summary = await _in_thread(agent_packs.export, drafts, pack_id, out,
                                             reg().origins)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc))
        return {"path": str(path), "pack": summary}

    @app.get("/api/packs/{pack_id}/export")
    async def get_export(pack_id: str):
        p = pack_info(pack_id)
        tmp = Path(tempfile.mkdtemp(prefix="bppack-"))
        try:
            path = await _in_thread(pack_install.export, p.path, tmp, find())
        except (ValueError, OSError) as exc:
            _rm(tmp)
            raise HTTPException(422, str(exc))
        return FileResponse(path, media_type="application/zip", filename=path.name,
                            background=BackgroundTask(_rm, tmp))


def _rm(folder):
    shutil.rmtree(folder, ignore_errors=True)
