"""Ajustes de la app y arranque (docs/PLAN_PIZARRA.md §2, D63, D67, D70).

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from pizarra.settings import MAX_RECENT, RIGHT_PANEL_DEFAULT, RIGHT_PANEL_MIN, Settings
from pizarra.startup import bootstrap, legacy_settings, start_view
from pizarra.storage import LocalWorkspace


def _tree_hash(root):
    """Huella de todo lo que hay en una carpeta: nombres, contenido y fecha de modificación."""
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
            h.update(str(p.stat().st_mtime_ns).encode())
    return h.hexdigest()


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings_path = self.tmp / "appdata" / "settings.toml"
        self.default_root = self.tmp / "Documentos" / "BoardPrint" / "Personal"
        self.bin = self.tmp / "papelera"
        self.bin.mkdir()

    def trash(self, path):
        shutil.move(str(path), str(self.bin / Path(path).name))

    def boot(self, spikes=()):
        return bootstrap(self.settings_path, self.default_root, spikes, trash=self.trash)


class Ajustes(_Tmp):
    def test_sin_fichero_salen_los_valores_por_defecto(self):
        s = Settings.load(self.settings_path)
        self.assertEqual(s.workspaces(), [])
        self.assertFalse(s.spike_imported)

    def test_guardar_y_cargar_conserva_lo_guardado(self):
        s = Settings.load(self.settings_path)
        s.add_workspace("w1", "Personal", self.default_root)
        s.touch_project("w1", "p1", "Brazo pinza")
        s.spike_imported = True
        s.save()
        t = Settings.load(self.settings_path)
        self.assertEqual(t.workspaces()[0]["name"], "Personal")
        self.assertEqual(Path(t.workspaces()[0]["path"]), self.default_root)
        self.assertEqual(t.last_project("w1"), "p1")
        self.assertTrue(t.spike_imported)

    def test_guardar_nunca_pierde_claves_que_esta_version_no_conoce(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text(
            'schema = 1\nwindow_mode = "fullscreen"\n[fonts]\nboard = "Nunito"\n', "utf-8")
        s = Settings.load(self.settings_path)
        s.add_workspace("w1", "Personal", self.default_root)
        s.save()
        text = self.settings_path.read_text("utf-8")
        self.assertIn('window_mode = "fullscreen"', text)
        self.assertIn('board = "Nunito"', text)

    def test_un_fichero_ilegible_no_impide_arrancar_ni_se_pierde(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text("esto = = no es toml", "utf-8")
        s = Settings.load(self.settings_path)
        self.assertEqual(s.workspaces(), [])
        self.assertTrue(s.problem)
        apartados = list(self.settings_path.parent.glob("settings.toml.ilegible-*"))
        self.assertEqual(len(apartados), 1)
        self.assertEqual(apartados[0].read_text("utf-8"), "esto = = no es toml")

    def test_recientes_sin_repetir_lo_ultimo_delante_y_con_tope(self):
        s = Settings.load(self.settings_path)
        s.add_workspace("w1", "Personal", self.default_root)
        for i in range(MAX_RECENT + 3):
            s.touch_project("w1", f"p{i}", f"P{i}")
        s.touch_project("w1", "p5", "P5 renombrado")
        rec = s.recent("w1")
        self.assertEqual(len(rec), MAX_RECENT)
        self.assertEqual(rec[0], {"id": "p5", "name": "P5 renombrado"})
        self.assertEqual(len({r["id"] for r in rec}), MAX_RECENT)
        self.assertEqual(s.last_project("w1"), "p5")

    def test_olvidar_un_proyecto_lo_quita_de_recientes_y_de_ultimo(self):
        s = Settings.load(self.settings_path)
        s.add_workspace("w1", "Personal", self.default_root)
        s.touch_project("w1", "p1", "A")
        s.touch_project("w1", "p2", "B")
        s.forget_project("w1", "p2")
        self.assertEqual([r["id"] for r in s.recent("w1")], ["p1"])
        self.assertIsNone(s.last_project("w1"))


class Skin(_Tmp):
    """D58, D79: escuela por defecto; un skin que no existe nunca impide arrancar."""

    def test_sin_skin_guardado_es_escuela(self):
        self.assertEqual(Settings.load(self.settings_path).skin, "escuela")

    def test_un_skin_desconocido_nunca_impide_arrancar_y_se_usa_escuela(self):
        for raw in ('skin = "neon"', "skin = 3", "skin = [1, 2]", '[skin]\nx = 1'):
            with self.subTest(raw=raw):
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                self.settings_path.write_text(f"schema = 1\n{raw}\n", "utf-8")
                s = Settings.load(self.settings_path)
                self.assertIsNone(s.problem)
                self.assertEqual(s.skin, "escuela")

    def test_el_skin_elegido_se_guarda_y_se_recupera(self):
        s = Settings.load(self.settings_path)
        s.skin = "cad"
        s.save()
        self.assertEqual(Settings.load(self.settings_path).skin, "cad")

    def test_nunca_se_guarda_un_skin_que_no_existe(self):
        s = Settings.load(self.settings_path)
        with self.assertRaises(ValueError):
            s.skin = "neon"
        self.assertEqual(s.skin, "escuela")


class PanelDerecho(_Tmp):
    """D60, D174: el ancho del panel derecho se guarda y nunca queda por debajo de 320 px."""

    def test_sin_ancho_guardado_es_el_de_por_defecto(self):
        self.assertEqual(Settings.load(self.settings_path).right_panel, RIGHT_PANEL_DEFAULT)

    def test_el_ancho_se_guarda_y_se_recupera(self):
        s = Settings.load(self.settings_path)
        s.right_panel = 512
        s.save()
        self.assertEqual(Settings.load(self.settings_path).right_panel, 512)

    def test_nunca_se_guarda_por_debajo_del_minimo(self):
        s = Settings.load(self.settings_path)
        for w in (319, 100, 0, -50):
            with self.subTest(w=w):
                s.right_panel = w
                s.save()
                self.assertEqual(s.data["paneles"]["derecho"], RIGHT_PANEL_MIN)
                self.assertEqual(Settings.load(self.settings_path).right_panel, 320)

    def test_unos_ajustes_con_un_ancho_menor_se_leen_con_el_minimo(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        for raw, want in (("derecho = 120", 320), ('derecho = "ancho"', RIGHT_PANEL_DEFAULT),
                          ("derecho = true", RIGHT_PANEL_DEFAULT), ("derecho = nan", RIGHT_PANEL_DEFAULT)):
            with self.subTest(raw=raw):
                self.settings_path.write_text(f"schema = 1\n[paneles]\n{raw}\n", "utf-8")
                s = Settings.load(self.settings_path)
                self.assertIsNone(s.problem)
                self.assertEqual(s.right_panel, want)

    def test_un_ancho_que_no_es_un_numero_no_se_guarda(self):
        s = Settings.load(self.settings_path)
        for bad in ("400", None, True, float("nan")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                s.right_panel = bad
        self.assertEqual(s.right_panel, RIGHT_PANEL_DEFAULT)


class Arranque(_Tmp):
    def spike(self, name="spike"):
        src = self.tmp / "viejo" / name
        (src / "board").mkdir(parents=True)
        (src / "blocks").mkdir()
        (src / "board" / "scene.json").write_text(
            '{"type": "excalidraw", "version": 2, "elements": [{"id": "a", "version": 1}]}',
            "utf-8")
        (src / "blocks" / "state.json").write_text('{"a": {"params": {"L": 300}}}', "utf-8")
        (src / "notas_del_agente.md").write_text("no se copia", "utf-8")
        return src

    def test_la_primera_vez_crea_el_workspace_personal_y_va_al_inicio(self):
        st = self.boot()
        self.assertEqual(st.workspace.info().name, "Personal")
        self.assertTrue((self.default_root / "workspace.toml").is_file())
        self.assertEqual(start_view(st), {"view": "home", "missing": None})
        self.assertEqual(Settings.load(self.settings_path).workspaces()[0]["id"],
                         st.workspace.info().id)

    def test_el_spike_se_importa_como_copia_y_el_original_no_se_toca(self):
        src = self.spike()
        before = _tree_hash(src)
        st = self.boot([src])
        self.assertEqual(_tree_hash(src), before)
        [node] = st.workspace.tree().children
        self.assertEqual(node.name, "Spike")
        self.assertEqual(st.workspace.load_scene(node.id), [{"id": "a", "version": 1}])
        self.assertEqual(st.workspace.load_block_state(node.id), {"a": {"params": {"L": 300}}})
        self.assertFalse((self.default_root / "Spike" / "notas_del_agente.md").exists())
        self.assertEqual(st.settings.recent(st.workspace.info().id)[0]["name"], "Spike")
        self.assertEqual(start_view(st)["view"], "home")    # la primera vez, el inicio (D63)

    def test_el_spike_se_importa_una_sola_vez_aunque_se_borre_el_importado(self):
        src = self.spike()
        st = self.boot([src])
        st.workspace.trash_project(st.workspace.tree().children[0].id)
        st = self.boot([src])
        self.assertEqual(st.workspace.tree().children, [])

    def test_sin_spike_no_se_crea_nada_y_no_se_vuelve_a_buscar(self):
        st = self.boot([self.tmp / "no-existe"])
        self.assertEqual(st.workspace.tree().children, [])
        self.assertTrue(Settings.load(self.settings_path).spike_imported)

    def test_dos_spikes_no_chocan_de_nombre(self):
        st = self.boot([self.spike("a"), self.spike("b")])
        self.assertEqual([c.name for c in st.workspace.tree().children], ["Spike", "Spike (2)"])

    def test_se_abre_el_ultimo_proyecto(self):
        st = self.boot()
        p = st.workspace.create_project("", "Brazo pinza")
        st.settings.touch_project(st.workspace.info().id, p.id, p.name)
        st.settings.save()
        self.assertEqual(start_view(self.boot()), {"view": "project", "project": p.id})

    def test_si_el_ultimo_proyecto_ya_no_existe_va_al_inicio_y_dice_cual(self):
        st = self.boot()
        p = st.workspace.create_project("", "Brazo pinza")
        st.settings.touch_project(st.workspace.info().id, p.id, p.name)
        st.settings.save()
        shutil.rmtree(self.default_root / "Brazo pinza")       # borrado desde el Explorador
        self.assertEqual(start_view(self.boot()), {"view": "home", "missing": "Brazo pinza"})

    def test_si_falta_la_carpeta_del_workspace_no_se_recrea_vacia(self):
        self.boot()
        shutil.rmtree(self.default_root)                      # p. ej. un disco desconectado
        st = self.boot()
        self.assertIsNone(st.workspace)
        self.assertIn(str(self.default_root), st.problem)
        self.assertFalse(self.default_root.exists())
        self.assertEqual(start_view(st)["view"], "home")

    def test_si_el_id_de_ajustes_no_es_el_de_la_carpeta_manda_la_carpeta(self):
        # e2e FF 4.7: un settings.toml escrito a mano (o de otra copia) con otro id hacía que
        # abrir cualquier proyecto tirase el WebSocket (touch_project con None).
        self.boot()
        s = Settings.load(self.settings_path)
        s.data["workspaces"][0]["id"] = s.data["current_workspace"] = "a_mano"
        s.save()
        st = self.boot()
        ws_id = st.workspace.info().id
        self.assertEqual(st.settings.current_workspace()["id"], ws_id)
        p = st.workspace.create_project("", "Brazo")
        st.settings.touch_project(ws_id, p.id, p.name)       # antes: TypeError
        self.assertEqual(Settings.load(self.settings_path).current_workspace()["id"], ws_id)

    def test_un_proyecto_movido_a_mano_se_sigue_abriendo(self):
        st = self.boot()
        p = st.workspace.create_project("", "Brazo")
        st.settings.touch_project(st.workspace.info().id, p.id, p.name)
        st.settings.save()
        (self.default_root / "Brazos").mkdir()
        (self.default_root / "Brazo").rename(self.default_root / "Brazos" / "Brazo")
        self.assertEqual(start_view(self.boot()), {"view": "project", "project": p.id})


class AjustesDeAntesDelNombre(_Tmp):
    """D158: los ajustes de una instalación anterior (otra carpeta de la app) se adoptan."""
    def setUp(self):
        super().setUp()
        self.old_path = self.tmp / "dev.cadllm.pizarra" / "settings.toml"
        self.old_root = self.tmp / "Documentos" / "CAD-LLM" / "Personal"

    def old_install(self):
        return bootstrap(self.old_path, self.old_root, trash=self.trash)

    def boot_new(self, legacy):
        return bootstrap(self.settings_path, self.default_root, trash=self.trash, legacy=legacy)

    def test_las_rutas_viejas_son_hermanas_de_la_nueva(self):
        self.assertEqual(legacy_settings(self.settings_path),
                         [self.tmp / "dev.cadllm.pizarra" / "settings.toml",
                          self.tmp / "cad-llm" / "settings.toml"])

    def test_sin_ajustes_nuevos_se_sigue_en_el_workspace_de_antes(self):
        old = self.old_install()
        before = self.old_path.read_bytes()
        st = self.boot_new(legacy_settings(self.settings_path))
        self.assertEqual(st.workspace.info().id, old.workspace.info().id)
        self.assertEqual(st.workspace.root, self.old_root.resolve())
        self.assertFalse(self.default_root.exists())
        self.assertEqual(self.old_path.read_bytes(), before)      # el original no se toca

    def test_si_ya_hay_ajustes_nuevos_no_se_pisan(self):
        self.old_install()
        new = self.boot_new(())
        st = self.boot_new(legacy_settings(self.settings_path))
        self.assertEqual(st.workspace.info().id, new.workspace.info().id)

    def test_gana_la_primera_carpeta_vieja_que_exista(self):
        first = self.old_install()
        second_path = self.tmp / "cad-llm" / "settings.toml"
        bootstrap(second_path, self.tmp / "otro", trash=self.trash)
        st = self.boot_new(legacy_settings(self.settings_path))
        self.assertEqual(st.workspace.info().id, first.workspace.info().id)


if __name__ == "__main__":
    unittest.main()
