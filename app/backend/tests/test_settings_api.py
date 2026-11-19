"""Ajustes de la interfaz y su API (docs/PLAN_PIZARRA.md D179-D185).

Ejecutar desde app/backend:  python -m unittest tests.test_settings_api -v
"""
import re
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from pizarra import agent_prompt, i18n, settings_api, units
from pizarra.settings import (SHORTCUT_ACTIONS, Settings, language_from_locale, normalize_combo,
                              system_language)
from pizarra.storage import LocalWorkspace


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "settings.toml"
        self.ws = LocalWorkspace.open(self.tmp / "Personal")

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        return Settings.load(self.path)


class ValoresIlegibles(_Tmp):
    def test_un_settings_toml_con_valores_ilegibles_da_los_de_por_defecto(self):
        s = self.write('idioma = "klingon"\n[ventana]\nmodo = "flotante"\nescala = "grande"\n'
                       '[fuentes]\npizarra = "Comic Sans MS"\ninterfaz = 3\n[bienvenida]\nvista = "si"\n')
        self.assertEqual(s.language, system_language())   # el del sistema (O11)
        self.assertEqual(s.window_mode, "maximizada")
        self.assertEqual(s.scale, 100)
        self.assertEqual(s.fonts["pizarra"], "Excalifont")
        self.assertEqual(s.fonts["interfaz"], "sistema")
        self.assertFalse(s.welcome_seen)

    def test_una_escala_a_mano_fuera_de_rango_se_lleva_al_borde(self):
        self.assertEqual(self.write("[ventana]\nescala = 400\n").scale, 150)
        self.assertEqual(self.write("[ventana]\nescala = 10\n").scale, 80)
        self.assertEqual(self.write("[ventana]\nescala = 114\n").scale, 110)
        self.assertEqual(self.write("[ventana]\nescala = 125\n").scale, 130)   # como el shell

    def test_unas_unidades_ilegibles_en_workspace_toml_dan_si(self):
        self.ws.save_units({"longitud": "pies", "masa": 7})
        self.assertEqual(units.clean(self.ws.load_units()), units.SI)
        (self.tmp / "Personal" / "workspace.toml").write_text("esto no es toml [", encoding="utf-8")
        self.assertEqual(units.clean(self.ws.load_units()), units.SI)


class Atajos(_Tmp):
    def test_la_forma_canonica_ordena_los_modificadores_y_cmd_es_ctrl(self):
        self.assertEqual(normalize_combo("shift+cmd+b"), "Ctrl+Mayús+B")
        self.assertEqual(normalize_combo("Alt+1"), "Alt+1")
        self.assertEqual(normalize_combo(""), "")

    def test_lo_que_no_es_un_atajo_se_rechaza(self):
        for bad in ("Ctrl+", "Ctrl+Ctrl+B", "Super+B", "Ctrl+F1", "Ctrl+ñ", 3):
            with self.assertRaises(ValueError, msg=bad):
                normalize_combo(bad)

    def test_unos_atajos_ilegibles_dejan_los_de_por_defecto(self):
        s = self.write('[atajos]\n"blocks.search" = "Hyper+B"\n"fit.all" = 5\n')
        self.assertEqual(s.shortcuts, {})
        self.assertEqual(self.write('atajos = "Ctrl+B"\n').shortcuts, {})

    def test_nunca_quedan_dos_acciones_con_el_mismo_atajo(self):
        # a mano en el fichero: ninguna de las dos se queda con él
        s = self.write('[atajos]\n"blocks.search" = "Ctrl+K"\n"view.fit_all" = "ctrl+k"\n'
                       '"tinta.activar" = "Alt+K"\n')
        self.assertEqual(s.shortcuts, {"tinta.activar": "Alt+K"})
        # por la API: se rechaza, salvo que la otra acción venga sin atajo (choque confirmado)
        s.set_shortcuts({"blocks.search": "Ctrl+J"})
        with self.assertRaises(ValueError):
            s.set_shortcuts({"view.fit_all": "Ctrl+J"})
        s.set_shortcuts({"view.fit_all": "Ctrl+J", "blocks.search": ""})
        self.assertEqual(s.shortcuts["view.fit_all"], "Ctrl+J")
        self.assertEqual(s.shortcuts["blocks.search"], "")

    def test_ctrl_mayus_b_no_choca_con_ctrl_b(self):
        s = Settings.load(self.path)
        s.set_shortcuts({"blocks.search": "Ctrl+B", "view.fit_all": "Ctrl+Mayús+B"})
        self.assertEqual(s.shortcuts, {"blocks.search": "Ctrl+B", "view.fit_all": "Ctrl+Mayús+B"})

    def test_un_atajo_de_una_accion_que_no_existe_se_rechaza_con_su_motivo(self):
        s = Settings.load(self.path)
        with self.assertRaises(ValueError) as ctx:
            s.set_shortcuts({"no.existe": "Ctrl+K"})
        self.assertIn("no.existe", str(ctx.exception))
        self.assertEqual(s.shortcuts, {}, "nada guardado")
        # y uno escrito a mano en el fichero no cuenta
        self.assertEqual(self.write('[atajos]\n"no.existe" = "Ctrl+K"\n').shortcuts, {})

    def test_las_acciones_son_las_de_la_interfaz(self):
        ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "shortcuts.ts").read_text(encoding="utf-8")
        table = ts[ts.index("export const SHORTCUTS"):ts.index("];", ts.index("export const SHORTCUTS"))]
        self.assertEqual(tuple(re.findall(r'id: "([^"]+)"', table)), SHORTCUT_ACTIONS)


class LaApi(_Tmp):
    def apply(self, s, changes):
        new_units = settings_api.apply(s, self.ws, changes)
        if new_units is not None:
            self.ws.save_units(new_units)
        s.save()

    def test_un_valor_fuera_de_rango_se_rechaza_con_su_motivo(self):
        s = Settings.load(self.path)
        cases = [({"ventana": {"escala": 170}}, "escala"),
                 ({"ventana": {"escala": 85}}, "escala"),
                 ({"ventana": {"modo": "flotante"}}, "modo"),
                 ({"fuentes": {"pizarra": "Arial"}}, "pizarra"),
                 ({"idioma": "klingon"}, "idioma"),
                 ({"unidades": {"longitud": "pies"}}, "longitud"),
                 ({"agentes": {"tope_proyecto_usd": -1}}, "tope"),
                 ({"agentes": {"animaciones_automaticas": "no"}}, "animaciones"),
                 ({"brillo": 3}, "brillo")]
        for changes, word in cases:
            with self.assertRaises(ValueError, msg=changes) as cm:
                settings_api.apply(s, self.ws, changes)
            self.assertIn(word, str(cm.exception))

    def test_guardar_un_ajuste_nunca_pierde_los_demas_ni_los_desconocidos(self):
        s = self.write('skin = "cad"\nfuturo = "x"\n[ventana]\nmodo = "ventana"\notra = 1\n')
        self.apply(s, {"ventana": {"escala": 120}})
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["skin"], "cad")
        self.assertEqual(data["futuro"], "x")
        self.assertEqual(data["ventana"], {"modo": "ventana", "otra": 1, "escala": 120})

    def test_las_unidades_van_al_workspace_y_nunca_a_settings(self):
        s = Settings.load(self.path)
        self.apply(s, {"unidades": {"longitud": "in"}})
        self.assertEqual(units.clean(self.ws.load_units())["longitud"], "in")
        self.assertEqual(units.clean(self.ws.load_units())["masa"], "kg")
        self.assertNotIn("unidades", tomllib.loads(self.path.read_text(encoding="utf-8")))
        self.assertEqual(settings_api.view(s, self.ws)["unidades"]["longitud"], "in")
        # el workspace.toml sigue con su id y su nombre
        data = tomllib.loads((self.tmp / "Personal" / "workspace.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["id"], self.ws.info().id)

    def test_la_vista_lleva_lo_que_se_puede_elegir(self):
        v = settings_api.view(Settings.load(self.path), self.ws)
        self.assertEqual(v["ventana"], {"modo": "maximizada", "escala": 100})
        self.assertIn("pantalla_completa", v["opciones"]["modos_ventana"])
        self.assertEqual(v["opciones"]["juegos_unidades"]["imperial"]["longitud"], "in")
        self.assertTrue(v["agentes"]["animaciones_automaticas"])
        self.assertFalse(v["bienvenida_vista"])

    def test_restablecer_atajos_vuelve_a_los_de_por_defecto(self):
        s = Settings.load(self.path)
        self.apply(s, {"atajos": {"blocks.search": "Ctrl+K"}})
        self.apply(s, {"atajos_por_defecto": True})
        self.assertEqual(Settings.load(self.path).shortcuts, {})


class Idioma(unittest.TestCase):
    def test_una_clave_que_falta_da_la_clave_nunca_un_hueco(self):
        self.assertEqual(i18n.t("no.existe"), "no.existe")
        self.assertEqual(i18n.t("ajustes.clave_desconocida"), "ajuste desconocido: {clave}")
        self.assertEqual(i18n.t("ajustes.clave_desconocida", clave="x"), "ajuste desconocido: x")

    def test_el_prompt_del_agente_lleva_el_idioma(self):
        prompt = agent_prompt.build("base", True, None, "es")
        self.assertIn(i18n.t("agente.idioma", "es"), prompt)
        prompt = agent_prompt.build("base", True, None, "en")
        self.assertIn("Always answer in English", prompt)

    def test_el_ingles_tiene_las_mismas_claves_que_el_espanol(self):
        # PLAN_PUBLICACION §6: un texto nuevo nunca se queda sin su traducción
        self.assertEqual(set(i18n.EN), set(i18n.ES))

    def test_al_cambiar_el_idioma_los_mensajes_del_backend_salen_en_ese_idioma(self):
        # O16: el idioma de los mensajes que ve el usuario sigue al ajuste, sin reiniciar
        try:
            from fastapi import FastAPI
        except ImportError:
            self.skipTest("falta fastapi")
        import asyncio
        self.addCleanup(i18n.set_language, "es")      # los demás tests leen en español
        with tempfile.TemporaryDirectory() as d:
            s = Settings.load(Path(d) / "settings.toml")
            s.language = "es"
            app = FastAPI()
            settings_api.register(app, settings=s, workspace=LocalWorkspace.open(Path(d) / "ws"),
                                  sessions=None, broadcast=None)
            put = next(r.endpoint for r in app.routes
                       if getattr(r, "path", "") == "/api/settings" and "PUT" in r.methods)
            asyncio.run(put(changes={"idioma": "en"}))
            self.assertEqual(i18n.t("ajustes.clave_desconocida", clave="x"), "unknown setting: x")
            with self.assertRaises(ValueError) as cm:      # un error cualquiera, ya en inglés
                Settings.load(Path(d) / "otro.toml").scale = 170
            self.assertIn("invalid scale", str(cm.exception))
            asyncio.run(put(changes={"idioma": "es"}))
            self.assertEqual(i18n.t("ajustes.clave_desconocida", clave="x"), "ajuste desconocido: x")

    def test_el_ingles_se_elige_y_se_guarda(self):
        with tempfile.TemporaryDirectory() as d:
            s = Settings.load(Path(d) / "settings.toml")
            s.language = "en"
            s.save()
            self.assertEqual(Settings.load(Path(d) / "settings.toml").language, "en")


class IdiomaDelSistema(unittest.TestCase):
    """Sin idioma guardado, el del sistema: español si está en una lengua de España, inglés si no
    (O11)."""

    def test_un_locale_en_espanol_da_espanol(self):
        for name in ("es_ES", "es-419", "es_MX.UTF-8", "Spanish_Spain", "es", "ca_ES", "Catalan_Spain", "gl_ES", "eu_ES"):
            self.assertEqual(language_from_locale(name), "es", name)

    def test_cualquier_otro_idioma_da_ingles_nunca_espanol(self):
        for name in ("en_US", "de_DE", "fr-FR", "English_United States", "et_EE", "est_EE", "pt_BR"):
            self.assertEqual(language_from_locale(name), "en", name)

    def test_un_locale_vacio_no_decide(self):
        for name in ("", None, "C", "POSIX"):
            self.assertIsNone(language_from_locale(name))


if __name__ == "__main__":
    unittest.main()
