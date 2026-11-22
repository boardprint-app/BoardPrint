"""Inicio de sesión de Microsoft 365 (docs/PLAN_M365.md §2, §9: M3, M4, M5, M12).

Reglas: ningún conjunto de permisos pide nunca `Mail.Send` (la app no puede enviar, M5);
SharePoint nunca está en los del inicio de sesión (M4). El client ID de `settings.toml` manda
sobre el del código; sin ninguno, la app dice que no está configurada y nunca llama a MSAL. La
caché de tokens va al lado de `settings.toml`, nunca en el workspace (M3). Sin cuenta, `token`
da `NotSignedIn`; con cuenta pero sin los permisos de SharePoint, `NeedsConsent`.

Ejecutar desde app/backend:  python -m unittest tests.test_m365_auth -v
"""
import tempfile
import unittest
from pathlib import Path

from pizarra import m365_auth
from pizarra.m365_auth import (Auth, NeedsConsent, NotConfigured, NotSignedIn, SCOPES_BASE,
                               SCOPES_SHAREPOINT, SignInFailed)
from pizarra.settings import Settings

PERSONAL = {"home_account_id": "oid." + m365_auth.PERSONAL_TENANT,
            "username": "alguien@outlook.com"}
WORK = {"home_account_id": "oid.11111111-2222-3333-4444-555555555555",
        "username": "alguien@empresa.com"}


class FakeMsal:
    """PublicClientApplication en memoria: qué permisos tiene dados cada cuenta."""

    def __init__(self, client_id, authority, cache):
        self.client_id, self.authority, self.cache = client_id, authority, cache
        self.accounts = []
        self.granted = set()
        self.interactive = []
        self.next_interactive = None

    def get_accounts(self):
        return list(self.accounts)

    def acquire_token_silent(self, scopes, account, force_refresh=False):
        if account in self.accounts and set(scopes) <= self.granted:
            return {"access_token": "tok-" + "-".join(scopes)}
        return None

    def acquire_token_interactive(self, scopes, **kw):
        self.interactive.append(list(scopes))
        result = self.next_interactive
        if result is None:
            self.accounts = [PERSONAL]
            self.granted |= set(scopes)
            return {"access_token": "t", "id_token_claims": {"name": "Alguien"}}
        return result

    def remove_account(self, account):
        self.accounts.remove(account)


def make(settings=None, client_id="cid"):
    made = []

    def factory(cid, authority, cache):
        app = FakeMsal(cid, authority, cache)
        made.append(app)
        return app

    old = m365_auth.CLIENT_ID
    m365_auth.CLIENT_ID = client_id
    auth = Auth(Path("x") / m365_auth.CACHE_NAME, settings, app_factory=factory,
                cache_factory=lambda path: ("cache", path))
    return auth, made, old


class Permisos(unittest.TestCase):
    def test_nunca_se_pide_mail_send(self):
        for scopes in m365_auth.ALL_SCOPE_SETS:
            self.assertFalse(any(s.lower().startswith("mail.send") for s in scopes), scopes)

    def test_sharepoint_no_esta_en_el_inicio_de_sesion(self):
        self.assertFalse(set(SCOPES_SHAREPOINT) & set(SCOPES_BASE))
        self.assertFalse(any(s.startswith("Sites.") for s in SCOPES_BASE))

    def test_no_pasa_permisos_reservados(self):
        reserved = {"offline_access", "openid", "profile"}
        for scopes in m365_auth.ALL_SCOPE_SETS:
            self.assertFalse(reserved & set(scopes))


class Configuracion(unittest.TestCase):
    _old = m365_auth.CLIENT_ID

    def tearDown(self):
        m365_auth.CLIENT_ID = self._old

    def _settings(self, table):
        tmp = Path(tempfile.mkdtemp())
        return Settings(tmp / "settings.toml", {"microsoft365": table} if table else {})

    def test_el_de_settings_manda_sobre_el_del_codigo(self):
        auth, made, self._old = make(self._settings({"client_id": " propio ",
                                                     "tenant": "empresa.com"}))
        self.assertEqual(auth.client_id(), "propio")
        self.assertEqual(auth.authority(), m365_auth.AUTHORITY_BASE + "empresa.com")

    def test_sin_settings_el_del_codigo_y_common(self):
        auth, made, self._old = make(self._settings({"client_id": "", "tenant": 3}))
        self.assertEqual(auth.client_id(), "cid")
        self.assertTrue(auth.authority().endswith("/common"))

    def test_sin_ninguno_no_esta_configurada_y_no_llama_a_msal(self):
        auth, made, self._old = make(None, client_id="")
        self.assertFalse(auth.configured())
        self.assertIsNone(auth.account())
        auth.sign_out()
        with self.assertRaises(NotConfigured):
            auth.sign_in()
        self.assertEqual(made, [])

    def test_la_cache_va_al_lado_de_settings(self):
        tmp = Path(tempfile.mkdtemp())
        self.assertEqual(m365_auth.cache_path(tmp / "settings.toml"),
                         tmp / m365_auth.CACHE_NAME)


class Sesion(unittest.TestCase):
    def setUp(self):
        self.auth, self.made, self._old = make()

    def tearDown(self):
        m365_auth.CLIENT_ID = self._old

    def test_sin_cuenta_token_da_not_signed_in(self):
        self.assertIsNone(self.auth.account())
        with self.assertRaises(NotSignedIn):
            self.auth.token()

    def test_iniciar_pide_solo_los_permisos_base(self):
        view = self.auth.sign_in()
        self.assertEqual(self.made[0].interactive, [list(SCOPES_BASE)])
        self.assertEqual(view, {"username": "alguien@outlook.com", "name": "Alguien",
                                "kind": "personal"})
        self.assertEqual(self.auth.account()["name"], "Alguien")
        self.assertTrue(self.auth.token().startswith("tok-"))

    def test_sharepoint_sin_dar_es_needs_consent(self):
        self.auth.sign_in()
        with self.assertRaises(NeedsConsent):
            self.auth.token(SCOPES_SHAREPOINT)
        self.assertFalse(self.auth.has_scopes(SCOPES_SHAREPOINT))
        self.auth.sign_in(SCOPES_SHAREPOINT)
        self.assertTrue(self.auth.has_scopes(SCOPES_SHAREPOINT))

    def test_error_del_navegador_es_sign_in_failed(self):
        self.auth._msal().next_interactive = {"error": "access_denied",
                                              "error_description": "cerrado"}
        with self.assertRaises(SignInFailed):
            self.auth.sign_in()
        self.assertIsNone(self.auth.account())

    def test_cerrar_sesion_borra_la_cuenta(self):
        self.auth.sign_in()
        self.auth.sign_out()
        self.assertIsNone(self.auth.account())
        with self.assertRaises(NotSignedIn):
            self.auth.token()

    def test_cuenta_de_trabajo(self):
        self.assertEqual(m365_auth.account_view(WORK)["kind"], "trabajo")


if __name__ == "__main__":
    unittest.main()
