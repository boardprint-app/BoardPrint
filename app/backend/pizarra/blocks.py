"""Tipos de bloque de la app: los que registran los paquetes instalados (plan D94, §3).

Los dos bloques del spike viven ahora en `packs/demo/`; el contrato y la carga, en
`pizarra.packs`. Este módulo solo da el registro ya cargado a quien lo importe.
"""
import sys

from pizarra import pack_host, packs

REGISTRY = packs.load()


def _env_spec(env, origins):
    """El trabajador del entorno para `origins` (P92); si sus librerías no se pueden tener, el
    de la app sin librerías, y los paquetes que las piden no cargarán diciendo por qué."""
    from pizarra.pack_env import EnvError
    try:
        return env.spec(origins), None
    except EnvError as exc:
        print(f"[paquetes] {exc}", file=sys.stderr)
        return env.base_spec(), str(exc)


def configure(user_dir=None, workspace_dir=None, validated=None, worker=None, env=None):
    """Añade los orígenes del usuario (`<ajustes>/packs`) y del workspace
    (`<workspace>/.boardprint/packs`), con su prioridad (docs/PLAN_PAQUETES.md §3, P10), y el
    fichero de las validaciones guardadas (`validated`, P80). Con `worker`
    (`pack_host.WorkerSpec`, la app), los paquetes se cargan en el trabajador y el backend
    solo tiene sus datos (P89). Sin él (los tests), en este proceso, y solo recarga si con los
    orígenes cambia lo que se carga. Con `env` (`pack_env.PackEnvironment`), el trabajador
    es el del entorno de los paquetes que se usan (P92) y los entornos viejos se borran.
    Devuelve el registro."""
    global REGISTRY
    origins = packs.default_origins(user_dir=user_dir, workspace_dir=workspace_dir)
    if env is not None:
        spec, problem = _env_spec(env, origins)
        host = pack_host.WorkerHost(spec, origins, validated)
        host.env, host.env_problem = env, problem
        REGISTRY = host.load()
        env.cleanup(spec)
        return REGISTRY
    if worker is not None:
        REGISTRY = pack_host.WorkerHost(worker, origins, validated).load()
        return REGISTRY
    if packs.discover(origins) != packs.discover(REGISTRY.origins):
        REGISTRY = packs.load(origins, validated=validated)
    else:
        REGISTRY.origins = [(o, str(d)) for o, d in origins]
        REGISTRY.validated = str(validated) if validated else None
    return REGISTRY


def reload():
    """Vuelve a cargar los mismos orígenes (tras instalar o desinstalar, §7). Devuelve el
    registro nuevo; quien tenga el de antes (las pizarras abiertas) lo cambia por este."""
    global REGISTRY
    host = REGISTRY.host
    if isinstance(host, pack_host.WorkerHost):
        env = getattr(host, "env", None)
        if env is not None:             # otro conjunto de paquetes, otro entorno (P92)
            host.spec, host.env_problem = _env_spec(env, host.origins)
        REGISTRY = host.load()          # el trabajador caliente vuelve a arrancar
    else:
        REGISTRY = packs.load(REGISTRY.origins, validated=REGISTRY.validated)
    return REGISTRY


def default_params(kind):
    return REGISTRY.default_params(kind)


def describe():
    """Lo que el frontend necesita para pintar y editar cada tipo de bloque."""
    return REGISTRY.describe()
