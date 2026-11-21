"""La lista de workspaces: crear, abrir y quitar (docs/PLAN_WORKSPACES.md §3, W3, W7; PLAN_PIZARRA
D12).

Rutas (`register`):

    GET    /api/workspaces              {workspaces: [{id, nombre, ruta, abierto, falta}],
                                         carpeta_base}: la lista de `settings.toml`; `falta`, si
                                         su carpeta no está; `carpeta_base`, donde va uno nuevo
                                         sin carpeta (Documentos/<App>/), o null
    POST   /api/workspaces {nombre, ruta?, desde?}
                                         crea uno nuevo, lo añade a la lista y lo abre:
                                         {workspace, perfil, reinicio}. Sin `ruta`,
                                         `<carpeta_base>/<nombre>`. `desde` (W4): `vacio`
                                         (por defecto), `plantilla:<id>` (de GET
                                         /api/profile/templates) o el `token` de
                                         POST /api/profile/import/inspect con
                                         `destino: "nuevo"`; `perfil`, lo que dejó
                                         (`profile_zip.apply`) o null
    POST   /api/workspaces/abrir {id | ruta}
                                         abre uno de la lista o una carpeta que ya es un
                                         workspace: {workspace, reinicio}
    DELETE /api/workspaces/{id}          lo quita de la lista: {workspaces}

**Un proceso, un workspace** (W3): abrir y crear contestan y después rearrancan el servidor en el
mismo puerto (`restart`, como la bienvenida); la ventana espera y recarga. Con `reinicio` false
y `al_abrir`, no hay quien rearranque (vale al volver a abrir la app); con `reinicio` false y
sin `al_abrir`, ya era el abierto.

**Quitar de la lista nunca borra nada en disco**, y el abierto no se quita (W7). Abrir una
carpeta movida (el mismo id en otra ruta) actualiza su ruta y no la repite; una copia (el mismo
id y la otra en su sitio) no se abre: compartirían recientes y último proyecto.

Errores, con el motivo en `detail`: 422 lo que no vale (nombre vacío, ruta que no es completa,
carpeta que no existe o no es un workspace, `desde` que no se entiende, plantilla que no
existe), 404 un id que no está en la lista y 409 un choque (nombre repetido, carpeta que ya es
otro workspace o está dentro de uno, quitar el abierto, la carpeta del de la lista que falta,
una copia, un token caducado, gastado o de otro destino).
"""
import asyncio
import os
import re
import shutil
import tempfile
import tomllib
from pathlib import Path

from pizarra import i18n, profile_zip, welcome
from pizarra.storage import Conflict, InvalidName, LocalWorkspace, NotFound
from pizarra.storage.local import WORKSPACE_FILE
from pizarra.storage.names import check_name
from pizarra.validation import ValidationError

EMPTY = "vacio"                         # `desde`: vacío, una plantilla o el token de un perfil
TEMPLATE = "plantilla:"
TOKEN = re.compile(r"[0-9a-f]{32}")     # los de `profile_zip.plan` (uuid4().hex)


def _norm(path):
    return Path(os.path.normcase(os.path.abspath(path)))


def _inside(a, b):
    """`a` es `b` o está dentro."""
    a, b = _norm(a), _norm(b)
    return a == b or b in a.parents


def entry_view(entry, open_ws=None):
    """{id, nombre, ruta, abierto, falta} de una entrada de `settings.toml`."""
    return {"id": entry["id"], "nombre": str(entry.get("name") or Path(entry["path"]).name),
            "ruta": str(entry["path"]),
            "abierto": open_ws is not None and open_ws.info().id == entry["id"],
            "falta": not Path(entry["path"]).is_dir()}


def listing(settings, open_ws):
    """La lista de `settings.toml`, en su orden; `open_ws` es el de este proceso (o None)."""
    return [entry_view(w, open_ws) for w in settings.workspaces()]


def remove(settings, ws_id, open_ws):
    """Quita `ws_id` de la lista (sin guardar) y no toca su carpeta (W7). `NotFound` si no está;
    `Conflict` si es el abierto."""
    entry = settings.workspace(ws_id)
    if entry is None:
        raise NotFound(i18n.t("workspaces.no_en_lista", id=ws_id))
    if open_ws is not None and open_ws.info().id == ws_id:
        raise Conflict(i18n.t("workspaces.quitar_abierto", nombre=entry.get("name")))
    settings.data["workspaces"] = [w for w in settings.data["workspaces"] if w is not entry]
    if settings.data.get("current_workspace") == ws_id:
        nxt = next(iter(settings.workspaces()), None)
        if nxt is None:
            settings.data.pop("current_workspace", None)
        else:
            settings.data["current_workspace"] = nxt["id"]


def _workspace_id(folder):
    """(id, nombre) del `workspace.toml` de `folder`, o None si no tiene uno legible."""
    try:
        data = tomllib.loads((Path(folder) / WORKSPACE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    return (str(data.get("id") or ""), str(data.get("name") or Path(folder).name))


def _absolute(ruta):
    if not isinstance(ruta, str) or not ruta.strip():
        raise InvalidName(i18n.t("workspaces.falta_carpeta"))
    p = Path(ruta.strip())
    if not p.is_absolute():
        raise InvalidName(i18n.t("bienvenida.ruta_no_absoluta", ruta=ruta))
    return p


def open_existing(settings, ws_id=None, ruta=None):
    """Deja como el actual (sin guardar) el workspace `ws_id` de la lista, o el de la carpeta
    `ruta`, que tiene que ser ya un workspace. Devuelve su `WorkspaceInfo`. Nunca crea nada:
    una carpeta que no existe o sin `workspace.toml` es `InvalidName`; un id que no está,
    `NotFound`; uno cuya carpeta falta, o una copia de otro de la lista, `Conflict`."""
    if ws_id:
        entry = settings.workspace(ws_id)
        if entry is None:
            raise NotFound(i18n.t("workspaces.no_en_lista", id=ws_id))
        if not Path(entry["path"]).is_dir():
            raise Conflict(i18n.t("workspaces.no_se_encuentra", nombre=entry.get("name"),
                                  ruta=entry["path"]))
        ruta = str(entry["path"])
    elif not ruta:
        raise InvalidName(i18n.t("workspaces.falta_que_abrir"))
    p = _absolute(ruta)
    if not p.is_dir():
        raise InvalidName(i18n.t("workspaces.no_existe_carpeta", ruta=p))
    found = _workspace_id(p)
    if found is None and not (p / WORKSPACE_FILE).exists():
        raise InvalidName(i18n.t("workspaces.no_es_workspace", ruta=p))
    same = settings.workspace(found[0]) if found is not None else None
    if same is not None and not welcome._same(same["path"], p) \
            and (_workspace_id(same["path"]) or ("",))[0] == found[0]:
        raise Conflict(i18n.t("workspaces.copia", ruta=p, nombre=same.get("name"),
                              otra=same["path"]))
    return welcome.switch_workspace(settings, str(p))


def _check_new_folder(settings, p):
    """`Conflict` si `p` ya es un workspace (de la lista o no) o está dentro de uno, o lo
    contiene; `InvalidName` si existe y no es una carpeta."""
    if p.exists() and not p.is_dir():
        raise InvalidName(i18n.t("bienvenida.no_es_carpeta", ruta=p))
    for w in settings.workspaces():
        if welcome._same(w["path"], p):
            raise Conflict(i18n.t("workspaces.ya_es_workspace", ruta=p, nombre=w.get("name")))
    if (p / WORKSPACE_FILE).exists():
        found = _workspace_id(p)
        raise Conflict(i18n.t("workspaces.ya_es_workspace", ruta=p,
                              nombre=found[1] if found else p.name))
    for w in settings.workspaces():
        if _inside(p, w["path"]) or _inside(w["path"], p):
            raise Conflict(i18n.t("workspaces.dentro_de_otro", ruta=p, nombre=w.get("name")))


def create(settings, nombre, ruta=None, base=None, desde=EMPTY, language=None):
    """Crea el workspace `nombre` en `ruta` (o en `<base>/<nombre>`), lo añade a la lista como
    el actual y guarda los ajustes. `desde` (W4): `vacio`, `plantilla:<id>` (en `language`) o
    el token de un perfil inspeccionado hacia un workspace nuevo (`profile_zip.plan(...,
    destino="nuevo")`). Devuelve `(WorkspaceInfo, perfil)`: `perfil`, lo que devuelve
    `profile_zip.apply`, o None si empieza vacío.

    Lo valida todo antes de escribir nada: `InvalidName` si el nombre, la carpeta o `desde` no
    valen; `Conflict` si el nombre está repetido, la carpeta es (o está dentro de) otro
    workspace o el token ya no vale (sin gastarlo); `ValidationError` si la plantilla no
    existe."""
    nombre = check_name(nombre)
    for w in settings.workspaces():
        if str(w.get("name") or "").strip().casefold() == nombre.casefold():
            raise Conflict(i18n.t("workspaces.nombre_repetido", nombre=nombre))
    if ruta:
        p = _absolute(ruta)
    elif base is not None:
        p = Path(base) / nombre
    else:
        raise InvalidName(i18n.t("workspaces.falta_carpeta"))
    _check_new_folder(settings, p)
    desde = desde or EMPTY
    with tempfile.TemporaryDirectory() as tmp:
        if desde.startswith(TEMPLATE):
            # la plantilla, empaquetada como un perfil, por el mismo `plan` que un .zip
            zip_ = profile_zip.write_template(desde[len(TEMPLATE):], tmp, language)
            token = profile_zip.plan(None, zip_, "nuevo")["token"]
        elif desde == EMPTY:
            token = None
        elif TOKEN.fullmatch(desde):
            token = desde
            profile_zip.check_token(token, "nuevo")
        else:
            raise InvalidName(i18n.t("workspaces.desde_no_valido", valor=repr(desde)))
        existed = p.exists()
        ws = LocalWorkspace.open(p, name=nombre)
        try:
            perfil = profile_zip.apply(ws, token, "nuevo") if token else None
        except Exception:
            if not existed:               # la que acaba de crear, y nada más
                shutil.rmtree(p, ignore_errors=True)
            raise
    info = ws.info()
    settings.add_workspace(info.id, info.name, p)
    settings.data["current_workspace"] = info.id
    settings.save()
    return info, perfil


def register(app, *, settings, workspace, base=None, restart=None):
    """`workspace` es el abierto en este proceso (None si su carpeta falta: la lista sigue
    sirviendo para abrir o crear otro); `base`, la carpeta de los nuevos sin carpeta;
    `restart()`, el de `server.main` (None: sin quien rearranque)."""
    from fastapi import HTTPException
    from pydantic import BaseModel

    class NewIn(BaseModel):
        nombre: str = ""
        ruta: str | None = None
        desde: str = EMPTY

    class OpenIn(BaseModel):
        id: str | None = None
        ruta: str | None = None

    def view(ws_id):
        # la del id o, si la de la lista tenía otro (ajustes a mano), la que quedó como actual
        return entry_view(settings.workspace(ws_id) or settings.current_workspace(), workspace)

    def reopen(out):
        """Contesta y, después, rearranca (W3). `restart()` usa el bucle del servidor: solo
        desde una ruta `async`, y el servidor sale 0,3 s después, con la respuesta ya dada."""
        if restart is None:
            return {**out, "reinicio": False, "al_abrir": True}
        restart()
        return {**out, "reinicio": True}

    @app.get("/api/workspaces")
    def get_workspaces():
        return {"workspaces": listing(settings, workspace),
                "carpeta_base": str(base) if base is not None else None}

    @app.post("/api/workspaces")
    async def post_workspace(p: NewIn):
        try:
            info, perfil = await asyncio.to_thread(create, settings, p.nombre, p.ruta, base,
                                                   p.desde, settings.language)
        except ValidationError as exc:      # una plantilla que no existe, un zip que no vale
            raise HTTPException(422, str(exc))
        return reopen({"workspace": view(info.id), "perfil": perfil})

    @app.post("/api/workspaces/abrir")
    async def open_workspace(p: OpenIn):
        if workspace is not None and (
                (p.id and p.id == workspace.info().id)
                or (not p.id and p.ruta and welcome._same(workspace.root, p.ruta))):
            return {"workspace": view(workspace.info().id), "reinicio": False}
        info = await asyncio.to_thread(open_existing, settings, p.id, p.ruta)
        settings.save()
        return reopen({"workspace": view(info.id)})

    @app.delete("/api/workspaces/{ws_id}")
    def delete_workspace(ws_id: str):
        remove(settings, ws_id, workspace)
        settings.save()
        return {"workspaces": listing(settings, workspace)}
