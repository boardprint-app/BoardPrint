"""La API de *Ajustes* (docs/PLAN_PIZARRA.md D179): todo lo que enseña la ventana en una
lectura y los cambios en una escritura.

- `GET /api/settings`: idioma, unidades del workspace (D182), ventana y escala (D183),
  fuentes (D184), atajos (D185), ajustes de los agentes (D144, D168), skin y bienvenida
  (D186), con las listas de lo que se puede elegir.
- `PUT /api/settings`: solo lo que cambia, con las mismas claves. **Todo o nada**: si una
  clave no vale, contesta 422 con el motivo y no se guarda ninguna. El cambio llega a todas
  las ventanas abiertas como `{"type": "settings"}` por el WebSocket, que vuelven a leer.

`PUT /api/settings/skin` y `/panels` (`workspace_api`) se quedan como estaban.
"""
import asyncio
import copy

from pizarra import api_key, i18n, units, welcome
from pizarra.settings import (FONT_CHOICES, LANGUAGES, SCALE_MAX, SCALE_MIN, SCALE_STEP, SKINS,
                              WINDOW_MODES, positive_usd)
from pizarra.storage import StorageError

KEYS = ("idioma", "unidades", "ventana", "fuentes", "atajos", "atajos_por_defecto",
        "agentes", "skin", "bienvenida_vista")


def view(settings, workspace, key_store=None):
    """`key_store`: el almacén de la API key (por defecto, el del sistema; los tests, uno en
    memoria). De la clave solo sale si está guardada, nunca la clave (O9)."""
    return {
        "idioma": settings.language,
        "unidades": units.clean(workspace.load_units()) if workspace is not None else dict(units.SI),
        "ventana": {"modo": settings.window_mode, "escala": settings.scale},
        "fuentes": settings.fonts,
        "atajos": settings.shortcuts,
        "agentes": {"animaciones_automaticas": settings.animations_auto,
                    "tope_proyecto_usd": settings.project_limit_usd,
                    "acceso": settings.agent_access,
                    "api_key_guardada": api_key.saved(key_store)},
        "skin": settings.skin,
        "bienvenida_vista": settings.welcome_seen,
        "workspace": welcome.location(workspace),       # dónde se guarda (D186)
        "opciones": {
            "idiomas": list(LANGUAGES),
            "unidades": {m: list(u) for m, u in units.UNITS.items()},
            "juegos_unidades": units.PRESETS,
            "modos_ventana": list(WINDOW_MODES),
            "escala": {"min": SCALE_MIN, "max": SCALE_MAX, "paso": SCALE_STEP},
            "fuentes": {k: list(v) for k, v in FONT_CHOICES.items()},
            "skins": list(SKINS),
        },
    }


def apply(settings, workspace, changes):
    """Aplica `changes` sobre `settings` (en memoria) y devuelve las unidades que hay que
    guardar en el workspace, o None. ValueError con el motivo si algo no vale."""
    if not isinstance(changes, dict):
        raise ValueError(i18n.t("ajustes.no_es_objeto"))
    unknown = [k for k in changes if k not in KEYS]
    if unknown:
        raise ValueError(i18n.t("ajustes.clave_desconocida", clave=unknown[0]))
    if "idioma" in changes:
        settings.language = changes["idioma"]
    if "ventana" in changes:
        w = _table(changes["ventana"], "ventana")
        if "modo" in w:
            settings.window_mode = w["modo"]
        if "escala" in w:
            settings.scale = w["escala"]
    if "fuentes" in changes:
        for kind, font in _table(changes["fuentes"], "fuentes").items():
            settings.set_font(kind, font)
    if changes.get("atajos_por_defecto") is True:
        settings.reset_shortcuts()
    if "atajos" in changes:
        settings.set_shortcuts(_table(changes["atajos"], "atajos"))
    if "agentes" in changes:
        a = _table(changes["agentes"], "agentes")
        if "animaciones_automaticas" in a:
            if not isinstance(a["animaciones_automaticas"], bool):
                raise ValueError(i18n.t("ajustes.no_es_booleano", clave="animaciones_automaticas"))
            settings.animations_auto = a["animaciones_automaticas"]
        if "tope_proyecto_usd" in a:
            if positive_usd(a["tope_proyecto_usd"]) is None:
                raise ValueError(i18n.t("ajustes.tope_no_valido"))
            settings.project_limit_usd = a["tope_proyecto_usd"]
        if "acceso" in a:
            if a["acceso"] not in api_key.ACCESS:
                raise ValueError(i18n.t("ajustes.acceso_no_valido"))
            settings.agent_access = a["acceso"]
    if "skin" in changes:
        settings.skin = changes["skin"]
    if "bienvenida_vista" in changes:
        if not isinstance(changes["bienvenida_vista"], bool):
            raise ValueError(i18n.t("ajustes.no_es_booleano", clave="bienvenida_vista"))
        settings.welcome_seen = changes["bienvenida_vista"]
    if "unidades" in changes:
        if workspace is None:
            raise ValueError(i18n.t("ajustes.sin_workspace"))
        return {**units.clean(workspace.load_units()), **units.validate(changes["unidades"])}
    return None


def _table(value, name):
    if not isinstance(value, dict):
        raise ValueError(i18n.t("ajustes.no_es_tabla", clave=name))
    return value


def register(app, *, settings, workspace, sessions, broadcast):
    from fastapi import Body, HTTPException     # aquí: los tests de `apply` no la necesitan

    @app.get("/api/settings")
    def get_settings():
        return view(settings, workspace)

    @app.put("/api/settings/api-key")
    async def put_api_key(body: dict = Body(...)):
        """Guarda la API key de Anthropic en el almacén del sistema (O9). La respuesta son los
        ajustes, sin la clave."""
        try:
            await asyncio.to_thread(api_key.save, body.get("clave"))
        except ValueError:
            raise HTTPException(422, i18n.t("ajustes.api_key_no_valida"))
        except Exception as exc:        # sin almacén del sistema
            raise HTTPException(409, i18n.t("ajustes.api_key_sin_almacen", motivo=type(exc).__name__))
        return view(settings, workspace)

    @app.delete("/api/settings/api-key")
    async def delete_api_key():
        await asyncio.to_thread(api_key.delete)
        return view(settings, workspace)

    @app.put("/api/settings")
    async def put_settings(changes: dict = Body(...)):
        before = copy.deepcopy(settings.data)
        try:
            new_units = apply(settings, workspace, changes)
        except ValueError as exc:
            settings.data = before            # todo o nada: nada queda a medias en memoria
            raise HTTPException(422, str(exc))
        try:
            if new_units is not None:
                workspace.save_units(new_units)
        except StorageError as exc:
            settings.data = before
            raise HTTPException(409, str(exc))
        settings.save()
        i18n.set_language(settings.language)    # los mensajes del backend, en el idioma nuevo (O16)
        for s in sessions.all() if sessions is not None else []:
            await broadcast(s, {"type": "settings"})
        return view(settings, workspace)
