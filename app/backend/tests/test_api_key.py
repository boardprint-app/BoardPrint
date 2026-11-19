"""El agente con API key de Anthropic además de con la sesión de Claude Code
(docs/PLAN_PUBLICACION.md O9, §4.4, §6).

Regla: la clave nunca se escribe en `settings.toml`, en un log, en la respuesta de los ajustes
ni en el entorno del backend; solo llega al proceso del agente (`ClaudeAgentOptions.env`), y
solo con el acceso «api_key». Con «api_key» y sin clave guardada, el agente no arranca con la
sesión a escondidas: lo dice.

Ejecutar desde app/backend:  python -m unittest tests.test_api_key -v
"""
import logging
import os
import tempfile
import unittest
from pathlib import Path

from pizarra import api_key, settings_api
from pizarra.settings import Settings

KEY = "sk-ant-api03-" + "x" * 80


class FakeStore:
    """El almacén del sistema (keyring) en memoria."""

    def __init__(self):
        self.data = {}

    def set_password(self, service, user, value):
        self.data[(service, user)] = value

    def get_password(self, service, user):
        return self.data.get((service, user))

    def delete_password(self, service, user):
        if (service, user) not in self.data:
            raise KeyError(user)
        del self.data[(service, user)]


class ApiKey(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = Settings.load(self.tmp / "settings.toml")

    def test_guardar_leer_y_borrar(self):
        self.assertFalse(api_key.saved(self.store))
        api_key.save(KEY, self.store)
        self.assertTrue(api_key.saved(self.store))
        self.assertEqual(api_key.load(self.store), KEY)
        api_key.delete(self.store)
        self.assertFalse(api_key.saved(self.store))
        api_key.delete(self.store)                  # borrar lo que no está no falla

    def test_una_clave_mal_formada_no_se_guarda(self):
        for bad in ("", "hola", "sk-ant-" + "x" * 5, KEY + " ", "sk-ant-a b" + "x" * 30, 42, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                api_key.save(bad, self.store)
        self.assertFalse(api_key.saved(self.store))

    def test_nunca_en_settings_toml_ni_en_los_ajustes_ni_en_el_entorno(self):
        with self.assertLogs("pizarra", level=logging.DEBUG) as logs:
            logging.getLogger("pizarra").debug("inicio")
            api_key.save(KEY, self.store)
            self.settings.agent_access = "api_key"
            self.settings.save()
            env = api_key.agent_env(self.settings, self.store)
        self.assertEqual(env, {"ANTHROPIC_API_KEY": KEY})
        self.assertNotIn(KEY, (self.tmp / "settings.toml").read_text(encoding="utf-8"))
        self.assertNotIn(KEY, repr(settings_api.view(self.settings, None, self.store)))
        self.assertNotIn(KEY, "\n".join(logs.output))
        self.assertNotIn(KEY, os.environ.values())

    def test_con_la_sesion_no_se_pasa_ninguna_clave(self):
        api_key.save(KEY, self.store)
        self.assertEqual(self.settings.agent_access, "sesion")      # el de por defecto
        self.assertEqual(api_key.agent_env(self.settings, self.store), {})
        self.assertEqual(api_key.agent_env(None, self.store), {})

    def test_con_api_key_y_sin_clave_el_agente_no_arranca_con_la_sesion(self):
        self.settings.agent_access = "api_key"
        with self.assertRaises(api_key.MissingKey):
            api_key.agent_env(self.settings, self.store)

    def test_el_acceso_se_elige_en_los_ajustes_y_se_valida(self):
        settings_api.apply(self.settings, None, {"agentes": {"acceso": "api_key"}})
        self.assertEqual(self.settings.agent_access, "api_key")
        with self.assertRaises(ValueError):
            settings_api.apply(self.settings, None, {"agentes": {"acceso": "otro"}})
        view = settings_api.view(self.settings, None, self.store)
        self.assertEqual(view["agentes"]["acceso"], "api_key")
        self.assertFalse(view["agentes"]["api_key_guardada"])
        api_key.save(KEY, self.store)
        self.assertTrue(settings_api.view(self.settings, None, self.store)["agentes"]["api_key_guardada"])

    def test_un_acceso_ilegible_en_settings_toml_es_la_sesion(self):
        (self.tmp / "settings.toml").write_text('[agentes]\nacceso = 3\n', encoding="utf-8")
        self.assertEqual(Settings.load(self.tmp / "settings.toml").agent_access, "sesion")

    def test_sin_almacen_del_sistema_no_hay_clave_y_no_rompe_los_ajustes(self):
        class Broken:
            def get_password(self, *a):
                raise RuntimeError("sin keyring")
        self.assertFalse(api_key.saved(Broken()))
        self.assertFalse(settings_api.view(self.settings, None, Broken())["agentes"]["api_key_guardada"])


if __name__ == "__main__":
    unittest.main()
