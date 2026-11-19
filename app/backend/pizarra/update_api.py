"""El actualizador visto desde el backend (docs/PLAN_V020.md §4, V9-V13).

Lo hace el shell (`app/shell/src-tauri/src/updates.rs`) con `tauri-plugin-updater`; este
módulo solo hace de puente por ficheros en la carpeta de los ajustes, como el modo de ventana:

- `update.json` lo escribe el shell con lo último que sabe (`estado`: `disponible`, `al_dia`,
  `instalando` o `error`, más `version`, `actual`, `notas`, `fecha`, `motivo`). Sin él (en
  desarrollo, sin shell, o antes de la primera comprobación), `{"estado": "desconocido"}`.
- `update.request` lo escribe este módulo cuando el usuario pide *Buscar actualizaciones*
  (`check`) o *Instalar y reiniciar* (`install`). **Instalar solo lo pide el usuario**: nada
  de aquí lo escribe por su cuenta.
"""
import json
from pathlib import Path

STATE = "update.json"
REQUEST = "update.request"
ACTIONS = ("check", "install")


def state(folder):
    """Lo que sabe el shell, o `{"estado": "desconocido"}`; un fichero roto cuenta como no
    sabido, nunca como un fallo de la app."""
    try:
        got = json.loads((Path(folder) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"estado": "desconocido"}
    return got if isinstance(got, dict) and isinstance(got.get("estado"), str) else {"estado": "desconocido"}


def app_version(folder):
    """La versión de la app: la que dice el shell (`actual` de `update.json`) o, en
    desarrollo, la de `tauri.conf.json` del repo; "" si no se sabe. La lleva el manifiesto del
    perfil `.zip` (PLAN_LIBRERIA L8)."""
    got = state(folder).get("actual")
    if isinstance(got, str) and got:
        return got
    conf = Path(__file__).resolve().parents[2] / "shell" / "src-tauri" / "tauri.conf.json"
    try:
        got = json.loads(conf.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return ""
    return got if isinstance(got, str) else ""


def request(folder, action):
    """Pide `action` al shell. ValueError si no es `check` ni `install`."""
    if action not in ACTIONS:
        raise ValueError(action)
    (Path(folder) / REQUEST).write_text(action, encoding="utf-8")


def register(app, *, settings):
    from fastapi import HTTPException

    folder = Path(settings.path).parent

    @app.get("/api/update")
    def get_update():
        return state(folder)

    @app.post("/api/update/{action}")
    def post_update(action: str):
        try:
            request(folder, action)
        except ValueError:
            raise HTTPException(404, action)
        return {"pedido": action}
