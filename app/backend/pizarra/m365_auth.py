"""Inicio de sesión de Microsoft 365 con MSAL (docs/PLAN_M365.md §2, M1-M4, M12).

Cliente público con autoridad `common`: cuentas de trabajo o escuela y personales. El
inicio de sesión abre el navegador del sistema con redirección a `http://localhost` (M2). La
caché de tokens va cifrada junto a `settings.toml` (DPAPI en Windows, Keychain en macOS), nunca
en el workspace ni en el proyecto (M3).

Permisos (M4): los de `SCOPES_BASE` al iniciar sesión; los de SharePoint, la primera vez que se
abre. **`Mail.Send` no se pide nunca** (M5): la app no puede enviar correos.

`msal` y `msal_extensions` se importan dentro de las funciones: la lógica y sus tests corren
sin ellas (el CI solo instala `requirements-base.txt`). Los tests pasan su propia fábrica.
"""
from pathlib import Path

# El registro de la app en Entra ID (M12, 21/11/2026, en el directorio del autor): multiinquilino
# con cuentas personales, cliente público, redirección http://localhost y token v2. No es
# secreto: identifica la app, no da acceso.
CLIENT_ID = "bcf4a042-596d-4739-850b-b1ce243b49d3"
AUTHORITY_BASE = "https://login.microsoftonline.com/"
DEFAULT_TENANT = "common"
# El inquilino de todas las cuentas personales de Microsoft.
PERSONAL_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"
# offline_access, openid y profile los añade MSAL solo (son reservados: pasarlos da error).
SCOPES_BASE = ("User.Read", "Files.ReadWrite", "Mail.ReadWrite")
SCOPES_SHAREPOINT = ("Sites.Read.All", "Files.ReadWrite.All")
ALL_SCOPE_SETS = (SCOPES_BASE, SCOPES_SHAREPOINT)
CACHE_NAME = "m365_cache.bin"
SIGN_IN_TIMEOUT = 300           # s: lo que espera el navegador antes de rendirse


class M365Error(Exception):
    """Base de los fallos de Microsoft 365 que la interfaz explica."""


class NotConfigured(M365Error):
    """La app no tiene client ID: ni registro (M12) ni `[microsoft365] client_id`."""


class NotSignedIn(M365Error):
    """No hay cuenta en la caché, o su sesión caducó y hay que volver a iniciarla."""


class NeedsConsent(M365Error):
    """La cuenta no ha dado aún esos permisos (SharePoint la primera vez, M4)."""


class SignInFailed(M365Error):
    """El navegador volvió con un error o el usuario lo cerró."""


def cache_path(settings_path):
    """La caché de tokens, al lado de `settings.toml` (la carpeta de datos de la app, M3)."""
    return Path(settings_path).parent / CACHE_NAME


def account_view(account, name=None):
    """Lo que enseña *Ajustes → Cuentas* de una cuenta de MSAL."""
    home = account.get("home_account_id") or ""
    tenant = home.split(".", 1)[1] if "." in home else ""
    return {"username": account.get("username") or "",
            "name": name or account.get("username") or "",
            "kind": "personal" if tenant == PERSONAL_TENANT else "trabajo"}


def _msal_app(client_id, authority, cache):
    import msal
    return msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)


def _encrypted_cache(path):
    from msal_extensions import PersistedTokenCache, build_encrypted_persistence
    path.parent.mkdir(parents=True, exist_ok=True)
    return PersistedTokenCache(build_encrypted_persistence(str(path)))


class Auth:
    """Una cuenta de Microsoft por instalación. Bloquea en `sign_in`: llamarla en un hilo."""

    def __init__(self, cache_file, settings=None, app_factory=_msal_app,
                 cache_factory=_encrypted_cache):
        self.cache_file = Path(cache_file)
        self.settings = settings
        self._app_factory = app_factory
        self._cache_factory = cache_factory
        self._app = None
        self._app_key = None
        self._names = {}            # username -> nombre del id_token, mientras corre la app

    # ------------------------------------------------------------ configuración (M12)
    def _own(self):
        return self.settings.m365 if self.settings is not None else {}

    def client_id(self):
        return self._own().get("client_id") or CLIENT_ID or None

    def authority(self):
        return AUTHORITY_BASE + (self._own().get("tenant") or DEFAULT_TENANT)

    def configured(self):
        return bool(self.client_id())

    def _msal(self):
        client_id = self.client_id()
        if not client_id:
            raise NotConfigured()
        key = (client_id, self.authority())
        if self._app is None or self._app_key != key:
            self._app = self._app_factory(client_id, self.authority(),
                                          self._cache_factory(self.cache_file))
            self._app_key = key
        return self._app

    # ------------------------------------------------------------ cuenta
    def _account(self):
        if not self.configured():
            return None
        accounts = self._msal().get_accounts()
        return accounts[0] if accounts else None

    def account(self):
        """La cuenta con sesión, o None. Sin red: solo mira la caché."""
        account = self._account()
        if account is None:
            return None
        return account_view(account, self._names.get(account.get("username")))

    def sign_in(self, scopes=SCOPES_BASE, timeout=SIGN_IN_TIMEOUT):
        """Abre el navegador del sistema y espera (M2). Devuelve la vista de la cuenta."""
        app = self._msal()
        result = app.acquire_token_interactive(list(scopes), prompt="select_account",
                                               timeout=timeout)
        if not result or "access_token" not in result:
            raise SignInFailed((result or {}).get("error_description")
                               or (result or {}).get("error") or "")
        claims = result.get("id_token_claims") or {}
        account = self._account()
        if account is None:
            raise SignInFailed("")
        if claims.get("name"):
            self._names[account.get("username")] = claims["name"]
        return account_view(account, claims.get("name"))

    def token(self, scopes=SCOPES_BASE, fresh=False):
        """Un token de acceso sin abrir nada: de la caché o con el de refresco. `fresh` no usa
        el de la caché (Graph acaba de rechazarlo con un 401)."""
        account = self._account()
        if account is None:
            raise NotSignedIn()
        app = self._msal()
        result = app.acquire_token_silent(list(scopes), account=account, force_refresh=fresh)
        if result and "access_token" in result:
            return result["access_token"]
        if tuple(scopes) != tuple(SCOPES_BASE):
            # La sesión vive pero estos permisos no se han dado: hay que pedirlos (M4).
            base = app.acquire_token_silent(list(SCOPES_BASE), account=account)
            if base and "access_token" in base:
                raise NeedsConsent()
        raise NotSignedIn()

    def has_scopes(self, scopes):
        try:
            self.token(scopes)
            return True
        except M365Error:
            return False

    def sign_out(self):
        if not self.configured():
            return
        app = self._msal()
        for account in app.get_accounts():
            app.remove_account(account)
        self._names.clear()
