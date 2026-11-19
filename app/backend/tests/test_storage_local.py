"""Almacenamiento local sobre carpetas: el contrato común y lo que el usuario hace a mano en
el Explorador (docs/PLAN_PIZARRA.md §2, D64-D66).

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from pizarra.storage import LocalWorkspace, NotFound, local
from tests.storage_contract import StorageContract


class _Disco(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "Personal"
        self.bin = self.tmp / "papelera"
        self.bin.mkdir()
        super().setUp()

    def fake_trash(self, path):
        """Papelera falsa: mueve la carpeta fuera del workspace y lo apunta."""
        self.trashed.append(Path(path))
        shutil.move(str(path), str(self.bin / f"{len(self.trashed)}-{Path(path).name}"))

    def make_workspace(self):
        return LocalWorkspace.open(self.root, trash=self.fake_trash)

    def reopen(self):
        """Lo que pasa al cerrar y volver a abrir la app."""
        return LocalWorkspace.open(self.root, trash=self.fake_trash)


class ContratoLocal(StorageContract, _Disco):
    pass


class CambiosDesdeElExplorador(_Disco):
    def setUp(self):
        self.trashed = []
        super().setUp()
        self.ws = self.make_workspace()

    def ids(self, node=None):
        node = node or self.ws.tree()
        out = []
        for c in node.children:
            out += [c.id] if c.kind == "project" else self.ids(c)
        return out

    def test_el_indice_de_antes_del_nombre_se_renombra(self):
        """D158: un workspace con el índice en `.cad-llm/` lo pasa a `.boardprint/`."""
        p = self.ws.create_project("", "Brazo")
        self.ws.tree()
        (self.root / ".boardprint").rename(self.root / ".cad-llm")
        ws = self.reopen()
        self.assertFalse((self.root / ".cad-llm").exists())
        self.assertTrue((self.root / ".boardprint" / "index.json").is_file())
        self.assertEqual(ws.project(p.id).name, "Brazo")

    def test_si_ya_hay_indice_nuevo_el_viejo_se_deja(self):
        self.ws.create_project("", "Brazo")
        self.ws.tree()
        (self.root / ".cad-llm").mkdir()
        self.reopen()
        self.assertTrue((self.root / ".cad-llm").is_dir())
        self.assertTrue((self.root / ".boardprint" / "index.json").is_file())

    def test_el_workspace_conserva_su_id_al_reabrirlo(self):
        self.assertEqual(self.reopen().info().id, self.ws.info().id)

    def test_carpeta_copiada_a_mano_recibe_otro_id_y_el_original_conserva_el_suyo(self):
        p = self.ws.create_project("", "Brazo")
        self.ws.tree()                                     # el índice conoce la ruta
        shutil.copytree(self.root / "Brazo", self.root / "Brazo - copia")
        ids = self.ids()
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(self.ws.project(p.id).path, "Brazo")
        copia = next(i for i in ids if i != p.id)
        self.assertEqual(self.ws.project(copia).path, "Brazo - copia")
        toml = tomllib.loads((self.root / "Brazo - copia" / "project.toml").read_text("utf-8"))
        self.assertEqual(toml["id"], copia)

    def test_la_copia_se_detecta_tambien_tras_reabrir_la_app(self):
        p = self.ws.create_project("", "Brazo")
        shutil.copytree(self.root / "Brazo", self.root / "A copia")   # va antes por nombre
        ws = self.reopen()
        self.assertEqual(ws.project(p.id).path, "Brazo")
        self.assertEqual(len(set(self.ids(ws.tree()))), 2)

    def test_manda_la_ruta_del_indice_aunque_la_copia_parezca_mas_antigua(self):
        # En Linux no hay fecha de creación (st_ctime cambia al renombrar): la edad engaña.
        p = self.ws.create_project("", "Brazo")
        shutil.copytree(self.root / "Brazo", self.root / "Brazo - copia")
        real_birth = local._birth
        local._birth = lambda d: 0.0 if d.name == "Brazo - copia" else 1.0
        self.addCleanup(setattr, local, "_birth", real_birth)
        self.ws.tree()
        self.assertEqual(self.ws.project(p.id).path, "Brazo")

    def test_renombrar_o_mover_a_mano_no_cambia_el_id(self):
        p = self.ws.create_project("", "Brazo")
        self.ws.save_scene(p.id, [{"id": "a", "version": 1}])
        (self.root / "Brazos").mkdir()                     # carpeta creada a mano
        (self.root / "Brazo").rename(self.root / "Brazos" / "Brazo pinza")
        got = self.ws.project(p.id)
        self.assertEqual(got.path, "Brazos/Brazo pinza")
        self.assertEqual(self.ws.load_scene(p.id), [{"id": "a", "version": 1}])
        self.assertEqual(self.reopen().project(p.id).name, "Brazo pinza")

    def test_ocultas_profile_y_packs_no_son_carpetas_del_workspace(self):
        for name in (".git", ".cache", "profile", "packs"):
            (self.root / name / "dentro").mkdir(parents=True)
            (self.root / name / "dentro" / "project.toml").write_text('id = "x"\n', "utf-8")
        (self.root / "Hecha a mano").mkdir()
        (self.root / "suelto.txt").write_text("no es carpeta", "utf-8")
        tree = self.ws.tree()
        self.assertEqual([(c.name, c.kind) for c in tree.children], [("Hecha a mano", "folder")])

    def test_un_project_toml_ilegible_nunca_se_sobrescribe(self):
        bad = self.root / "Roto"
        bad.mkdir()
        (bad / "project.toml").write_text("esto no es toml = = =", "utf-8")
        node = self.ws.tree().children[0]
        self.assertEqual((node.name, node.kind, node.id), ("Roto", "project", None))
        self.assertTrue(node.error)
        self.assertEqual((bad / "project.toml").read_text("utf-8"), "esto no es toml = = =")

    def test_borrar_nunca_elimina_en_el_sitio(self):
        p = self.ws.create_project("", "Spike")
        self.ws.save_scene(p.id, [{"id": "a", "version": 1}])
        self.ws.trash_project(p.id)
        self.assertEqual(self.trashed, [self.root / "Spike"])
        self.assertTrue((self.bin / "1-Spike" / "board" / "scene.json").is_file())

    def test_un_proyecto_borrado_a_mano_es_no_encontrado(self):
        p = self.ws.create_project("", "Spike")
        shutil.rmtree(self.root / "Spike")
        with self.assertRaises(NotFound):
            self.ws.project(p.id)


if __name__ == "__main__":
    unittest.main()
