"""Rutas REST de la librería del workspace (docs/PLAN_V020.md §5, V14-V16).

    GET    /api/library?type=            {items: [resumen], types: [tipo]}
    GET    /api/library/fields?type=     {type, fields: [{nombre, unidad, descripcion, obligatorio,
                                          min, max, declarado, paquete}]}  (PLAN_LIBRERIA L4)
    GET    /api/library/ficha/{key}      resumen + {toml, data, stock}
    PUT    /api/library/ficha/{key}      {toml} -> resumen         (valida solo [meta], V15)
    DELETE /api/library/ficha/{key}      a la papelera (D66)
    GET    /api/library/stock            {stock: {clave: entrada}}
    PUT    /api/library/stock            {clave: entrada | null} -> {stock}
    POST   /api/library/import/inspect   {path?, sheet?} -> {file, sheets, sheet, columns, sample, rows}
    POST   /api/library/import/plan      {path, sheet?, type?, mapping} -> {token, rows, counts…}
    POST   /api/library/import/apply     {token} -> {created, updated, unchanged, invalid…}

Una ficha va en `/ficha/{key}` y no en `/{key}`: así una clave `stock` no choca con el stock.
Sin `path`, `inspect` abre el diálogo del sistema (como *Archivo* de la pizarra); cancelado,
`{file: null}`. Un error de una ficha o de un archivo es 422; un resumen caducado, 409.
"""
import asyncio

from fastapi import Body, HTTPException
from pydantic import BaseModel

from pizarra import desktop, i18n, library_import
from pizarra.library import WorkspaceLibrary, pack_libraries
from pizarra.validation import ValidationError


class FichaIn(BaseModel):
    toml: str


class InspectIn(BaseModel):
    path: str | None = None
    sheet: str | None = None


class PlanIn(BaseModel):
    path: str
    sheet: str | None = None
    type: str | None = None
    mapping: dict


class ApplyIn(BaseModel):
    token: str


async def _in_thread(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def register(app, *, need_workspace, registry=None):
    """`need_workspace()` es el del servidor (503 sin workspace). `registry()`, el registro de
    paquetes cargado (de él salen las fichas de los paquetes, en solo lectura); sin él, ninguna."""

    def lib():
        return WorkspaceLibrary(need_workspace(), pack_libraries(registry() if registry else None))

    def checked(fn, *args):
        try:
            return fn(*args)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/library")
    def get_library(type: str | None = None):     # noqa: A002 el nombre del parámetro de la URL
        lb = lib()
        return {"items": lb.list(type or None), "types": lb.types()}

    @app.get("/api/library/fields")
    def get_fields(type: str):                     # noqa: A002
        return {"type": type, "fields": lib().fields(type)}

    @app.get("/api/library/stock")
    def get_stock():
        return {"stock": lib().stock()}

    @app.put("/api/library/stock")
    def put_stock(changes: dict = Body(...)):
        return {"stock": checked(lib().update_stock, changes)}

    @app.get("/api/library/ficha/{key}")
    def get_ficha(key: str):
        return lib().get(key)

    @app.put("/api/library/ficha/{key}")
    def put_ficha(key: str, f: FichaIn):
        return checked(lib().save, key, f.toml)

    @app.delete("/api/library/ficha/{key}")
    def delete_ficha(key: str):
        checked(lib().delete, key)
        return {"ok": True}

    @app.post("/api/library/import/inspect")
    async def post_inspect(p: InspectIn):
        need_workspace()
        path = p.path
        if not path:
            path = await _in_thread(desktop.choose_file, i18n.t("dialogo.importar_libreria"),
                                    [(i18n.t("dialogo.hojas_calculo"), "*.xlsx;*.xlsm;*.csv;*.tsv"),
                                     (i18n.t("dialogo.todos"), "*.*")])
            if not path:
                return {"file": None}
        return await _in_thread(checked, library_import.inspect, path, p.sheet)

    @app.post("/api/library/import/plan")
    async def post_plan(p: PlanIn):
        lb = lib()
        return await _in_thread(checked, library_import.plan, lb, p.path, p.sheet, p.type,
                                p.mapping)

    @app.post("/api/library/import/apply")
    async def post_apply(a: ApplyIn):
        lb = lib()
        return await _in_thread(checked, library_import.apply, lb, a.token)
