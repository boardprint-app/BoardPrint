"""La bienvenida y el aviso de la primera animación (docs/PLAN_PIZARRA.md D186, D187).

Ejecutar desde app/backend:  python -m unittest tests.test_welcome -v
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pizarra import claude_session, welcome
from pizarra.settings import Settings
from pizarra.startup import bootstrap
from pizarra.storage import LocalWorkspace


def _tree(root):
    return sorted((str(p.relative_to(root)), p.read_bytes() if p.is_file() else b"")
                  for p in Path(root).rglob("*"))


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings_path = self.tmp / "settings.toml"
        self.start = bootstrap(self.settings_path, self.tmp / "Documentos" / "Personal", ())
        self.settings = self.start.settings


class LaBienvenida(_Tmp):
    def test_sale_hasta_que_se_termina_o_se_salta(self):
        self.assertFalse(self.settings.welcome_seen)
        self.settings.welcome_seen = True
        self.settings.save()
        self.assertTrue(Settings.load(self.settings_path).welcome_seen)

    def test_una_instalacion_que_ya_existe_tambien_la_ve(self):
        # settings.toml de antes de FF 4.7, con su workspace y sin [bienvenida]
        self.settings.save()
        self.assertFalse(Settings.load(self.settings_path).welcome_seen)


class CambiarDeCarpeta(_Tmp):
    def test_cambiar_de_carpeta_nunca_toca_la_de_antes(self):
        old = self.start.workspace
        old.create_project("", "Brazo")
        before = _tree(old.root)
        new_root = self.tmp / "Otra" / "Mis proyectos"
        info = welcome.switch_workspace(self.settings, str(new_root))
        self.settings.save()
        self.assertEqual(_tree(old.root), before)
        self.assertTrue((new_root / "workspace.toml").is_file())
        s = Settings.load(self.settings_path)
        self.assertEqual(s.current_workspace()["id"], info.id)
        self.assertIn(old.info().id, [w["id"] for w in s.workspaces()])   # se queda en la lista

    def test_la_de_antes_borrada_no_se_recrea_al_arrancar_con_la_nueva(self):
        old_root = self.start.workspace.root
        welcome.switch_workspace(self.settings, str(self.tmp / "Nueva"))
        self.settings.save()
        shutil.rmtree(old_root)
        start = bootstrap(self.settings_path, old_root, ())
        self.assertEqual(Path(start.workspace.root), self.tmp / "Nueva")
        self.assertFalse(old_root.exists())

    def test_una_carpeta_con_workspace_toml_se_abre_sin_crear_otro(self):
        other = LocalWorkspace.open(self.tmp / "Equipo", name="Equipo")
        other.create_project("", "Pinza")
        info = welcome.switch_workspace(self.settings, str(self.tmp / "Equipo"))
        self.assertEqual(info.id, other.info().id)
        self.assertEqual(info.name, "Equipo")
        self.assertEqual(len([p for p in (self.tmp / "Equipo").rglob("workspace.toml")]), 1)

    def test_volver_a_una_que_ya_esta_en_la_lista_no_la_repite(self):
        first = self.settings.current_workspace()["id"]
        welcome.switch_workspace(self.settings, str(self.tmp / "Nueva"))
        welcome.switch_workspace(self.settings, str(self.start.workspace.root))
        self.assertEqual(self.settings.current_workspace()["id"], first)
        self.assertEqual(len(self.settings.workspaces()), 2)

    def test_una_ruta_que_no_vale_se_rechaza_sin_tocar_nada(self):
        f = self.tmp / "fichero.txt"
        f.write_text("x")
        for bad in ("", "relativa/carpeta", str(f)):
            with self.assertRaises(ValueError, msg=bad):
                welcome.switch_workspace(self.settings, bad)
        self.assertEqual(len(self.settings.workspaces()), 1)


class LaSesion(unittest.TestCase):
    def test_conectada_con_su_cuenta(self):
        out = json.dumps({"loggedIn": True, "email": "ana@taller.es", "subscriptionType": "max"})
        self.assertEqual(claude_session.parse(0, out),
                         {"estado": "conectada", "cuenta": "ana@taller.es", "plan": "max",
                          "motivo": None})

    def test_sin_sesion(self):
        self.assertEqual(claude_session.parse(1, '{"loggedIn": false}')["estado"], "sin_sesion")

    def test_una_salida_ilegible_nunca_sale_conectada(self):
        for out in ("", "Logged in as ana", '{"loggedIn": "yes"}', "[]", None):
            self.assertEqual(claude_session.parse(0, out)["estado"], "no_comprobada", out)

    def test_sin_el_cli_sale_no_comprobada(self):
        r = claude_session.status(str(Path(tempfile.gettempdir()) / "no-existe-claude"),
                                  run=lambda *a, **k: (_ for _ in ()).throw(OSError("no está")))
        self.assertEqual(r["estado"], "no_comprobada")

    def test_sin_claude_code_instalado_sale_sin_cli_nunca_conectada(self):
        # PLAN_PUBLICACION O13: el instalador ya no lo trae; la bienvenida ofrece instalarlo
        orig = claude_session.find_cli
        claude_session.find_cli = lambda cli_path=None: None
        try:
            r = claude_session.status(None, run=lambda *a, **k: self.fail("no hay CLI que lanzar"))
        finally:
            claude_session.find_cli = orig
        self.assertEqual(r["estado"], claude_session.NO_CLI)

    def test_un_cli_que_se_cuelga_sale_no_comprobada(self):
        import subprocess

        def hang(*a, **k):
            raise subprocess.TimeoutExpired("claude", 20)
        orig = claude_session.find_cli
        claude_session.find_cli = lambda cli=None: "claude"
        try:
            self.assertEqual(claude_session.status(run=hang)["estado"], "no_comprobada")
        finally:
            claude_session.find_cli = orig


class LaPrimeraAnimacion(_Tmp):
    def setUp(self):
        super().setUp()
        self.ws = self.start.workspace
        self.pid = self.ws.create_project("", "Engranajes").id

    def test_avisa_una_sola_vez_por_proyecto(self):
        self.assertTrue(welcome.first_animation(self.ws, self.pid, True))
        self.assertFalse(welcome.first_animation(self.ws, self.pid, True))
        otro = self.ws.create_project("", "Levas").id
        self.assertTrue(welcome.first_animation(self.ws, otro, True))

    def test_nunca_con_el_ajuste_desactivado(self):
        self.assertFalse(welcome.first_animation(self.ws, self.pid, False))
        # y no gasta el aviso: si luego se activa, sale con la siguiente
        self.assertTrue(welcome.first_animation(self.ws, self.pid, True))

    def test_la_marca_no_pisa_los_ajustes_del_agente_del_proyecto(self):
        self.ws.save_project_agent_settings(self.pid, {"tope_usd": 2.0, "excluir_adjuntos": True})
        welcome.first_animation(self.ws, self.pid, True)
        self.assertEqual(self.ws.load_project_agent_settings(self.pid),
                         {"tope_usd": 2.0, "excluir_adjuntos": True, "aviso_animacion": True})


if __name__ == "__main__":
    unittest.main()
