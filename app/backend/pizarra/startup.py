"""Arranque: ajustes, workspace y qué se enseña al abrir (docs/PLAN_PIZARRA.md §2, D63, D67, D70).

La primera vez se crea el workspace por defecto («Personal» en Documentos/<App>/, hasta que
el onboarding deje elegir, FF 4.7) y se copian a él las pizarras del spike de FF 3. Después,
se abre el último proyecto; si ya no existe, la pantalla de inicio, diciendo cuál falta.
"""
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from pizarra import i18n
from pizarra.config import APP_ID, LEGACY_APP_DIRS
from pizarra.settings import Settings
from pizarra.storage import Conflict, LocalWorkspace, NotFound

DEFAULT_WORKSPACE = "Personal"
SPIKE_NAME = "Spike"


@dataclass
class StartState:
    settings: Settings
    workspace: LocalWorkspace | None      # None si su carpeta ya no está
    problem: str | None = None            # algo que la pantalla de inicio tiene que decir
    default_root: Path | None = None      # el del workspace por defecto: su carpeta es donde
                                          # van los nuevos (Documentos/<App>/, PLAN_WORKSPACES W6)


def legacy_settings(settings_path, names=LEGACY_APP_DIRS):
    """Dónde estaban los ajustes antes de D158: la misma ruta con la carpeta de la app vieja
    (`%APPDATA%\\dev.cadllm.pizarra\\settings.toml` → `%APPDATA%\\<nueva>\\settings.toml`)."""
    path = Path(settings_path)
    return [path.parent.parent / name / path.name for name in names]


def _adopt_legacy_settings(settings_path, legacy):
    """Si aún no hay ajustes, copia los primeros que existan de una instalación anterior. Se
    copian, no se mueven: la app vieja puede seguir instalada al lado."""
    path = Path(settings_path)
    if path.exists():
        return
    for old in map(Path, legacy):
        if old.is_file() and old != path:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, path)
            return


def bootstrap(settings_path, default_root, spike_sources=(), trash=None, legacy=()):
    _adopt_legacy_settings(settings_path, legacy)
    settings = Settings.load(settings_path)
    problem = settings.problem
    entry = settings.current_workspace()
    if entry is None:
        ws = LocalWorkspace.open(default_root, name=DEFAULT_WORKSPACE, trash=trash)
        settings.add_workspace(ws.info().id, ws.info().name, ws.root)
    else:
        root = Path(entry["path"])
        if not root.is_dir():
            # Nunca se recrea vacía: puede ser un disco desconectado o una carpeta movida.
            settings.save()
            return StartState(settings, None,
                              i18n.t("workspace.carpeta_no_encontrada", settings.language,
                                     nombre=entry.get("name"), ruta=root), Path(default_root))
        ws = LocalWorkspace.open(root, trash=trash)
        if entry.get("id") != ws.info().id:
            # Ajustes a mano o de otra copia: manda el id de la carpeta (`workspace.toml`). Si
            # no, abrir un proyecto no encuentra su workspace en los ajustes y tira el WebSocket.
            entry["id"] = settings.data["current_workspace"] = ws.info().id
    if not settings.spike_imported:
        _import_spikes(ws, settings, spike_sources)
        settings.spike_imported = True
    settings.save()
    return StartState(settings, ws, problem, Path(default_root))


def _import_spikes(ws, settings, sources):
    """Copia (D67) la pizarra y el estado de los bloques de cada spike que exista. Lo demás de
    su carpeta (notas o ficheros del agente) se queda donde está, y el original no se toca."""
    for src in map(Path, sources):
        if not (src / "board" / "scene.json").is_file():
            continue
        for n in range(1, 100):
            name = SPIKE_NAME if n == 1 else f"{SPIKE_NAME} ({n})"
            try:
                project = ws.create_project("", name)
                break
            except Conflict:
                continue
        dst = ws.workdir(project.id)
        for sub in ("board", "blocks"):
            if (src / sub).is_dir():
                shutil.copytree(src / sub, dst / sub, dirs_exist_ok=True)
        settings.touch_project(ws.info().id, project.id, project.name, opened=False)


def start_view(state):
    """Qué abre la interfaz: `{"view": "project", "project": id}` o la pantalla de inicio
    (`{"view": "home", "missing": nombre o None}`, con `problem` si hay algo que avisar)."""
    home = {"view": "home", "missing": None}
    if state.problem:
        home["problem"] = state.problem
    if state.workspace is None:
        return home
    ws_id = state.workspace.info().id
    pid = state.settings.last_project(ws_id)
    if pid is None:
        return home
    try:
        state.workspace.project(pid)
    except NotFound:
        name = next((r["name"] for r in state.settings.recent(ws_id) if r["id"] == pid), None)
        return {**home, "missing": name or i18n.t("inicio.ultimo_proyecto", state.settings.language)}
    return {"view": "project", "project": pid}


def pack_environment(args, engine_dir, dev, repo, frozen, bundle):
    """El entorno de paquetes (`pack_env.PackEnvironment`, docs/PLAN_PAQUETES.md P89, P92,
    P93): en la app, el Python y `uv` de `--pyenv-dir` con `--worker-dir`; en desarrollo, el de
    `app/shell/src-tauri/pyenv` si se ha descargado (`fetch_pyenv.py`) o, si no, este Python
    (que no instala librerías), con `app/backend`. Un ejecutable lanzado sin ellos: None, los
    paquetes en el proceso del backend."""
    from pizarra import pack_env
    cache = args.cache_dir or (str(dev / "cache") if dev else None)
    if args.pyenv_dir and args.worker_dir:
        return pack_env.PackEnvironment(args.worker_dir, engine_dir, cache,
                                        pyenv=pack_env.Pyenv(Path(args.pyenv_dir)))
    if not frozen:
        pyenv = pack_env.Pyenv(Path(repo) / "app" / "shell" / "src-tauri" / "pyenv")
        return pack_env.PackEnvironment(bundle, engine_dir, cache,
                                        pyenv=pyenv if pyenv.python.is_file() else None)
    return None


def app_data_dir():
    """%APPDATA%/<App> (Mac: ~/Library/Application Support/<App>), plan §2. Lo normal es que
    el shell pase `--settings`; esto es por si se arranca el backend a mano."""
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / APP_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_ID
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_ID
