"""La API key de Anthropic para el agente (docs/PLAN_PUBLICACION.md O9, §4.4).

El agente trabaja con la sesión de Claude Code (R4 de PLAN_PIZARRA) o, si en *Ajustes →
Agentes* se elige «API key», con una clave de Anthropic. La clave vive **solo en el almacén del
sistema** (Credential Manager en Windows, Keychain en macOS, por `keyring`): nunca en
`settings.toml`, en un log, en la respuesta de los ajustes ni en el entorno del backend. Llega
al proceso del agente por `ClaudeAgentOptions.env` (`agent_env`).

`store` es el almacén (por defecto, `keyring`); los tests le pasan uno en memoria.
"""
import logging
import re

log = logging.getLogger(__name__)

SERVICE = "BoardPrint"
USER = "anthropic_api_key"
ACCESS = ("sesion", "api_key")          # cómo entra el agente: la sesión de Claude Code o la clave
DEFAULT_ACCESS = "sesion"
_FORMAT = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,300}")


class MissingKey(RuntimeError):
    """Acceso «api_key» sin clave guardada: el agente no arranca con la sesión a escondidas."""


def _store(store):
    if store is not None:
        return store
    import keyring                      # aquí: los tests y el CI no lo necesitan
    return keyring


def save(key, store=None):
    """Guarda la clave. ValueError si no tiene la forma de una clave de Anthropic (sin decir
    cuál: el motivo nunca la repite)."""
    if not isinstance(key, str) or not _FORMAT.fullmatch(key):
        raise ValueError("no parece una API key de Anthropic (empieza por sk-ant-)")
    _store(store).set_password(SERVICE, USER, key)
    log.info("API key guardada en el almacén del sistema")


def load(store=None):
    """La clave guardada, o None (también si el almacén del sistema no responde)."""
    try:
        return _store(store).get_password(SERVICE, USER) or None
    except Exception as exc:            # keyring sin backend, Credential Manager bloqueado…
        log.warning("no se pudo leer el almacén del sistema: %s", type(exc).__name__)
        return None


def saved(store=None):
    return load(store) is not None


def delete(store=None):
    try:
        _store(store).delete_password(SERVICE, USER)
    except Exception:                   # no estaba: no pasa nada
        pass
    log.info("API key borrada del almacén del sistema")


def agent_env(settings, store=None):
    """Lo que el proceso del agente lleva de más en su entorno: la clave, solo con el acceso
    «api_key». `MissingKey` si se eligió y no hay clave."""
    if settings is None or settings.agent_access != "api_key":
        return {}
    key = load(store)
    if key is None:
        raise MissingKey("api_key")
    return {"ANTHROPIC_API_KEY": key}
