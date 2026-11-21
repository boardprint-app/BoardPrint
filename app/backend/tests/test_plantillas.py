"""Plantillas de un paquete en la pizarra (plan D91, §10).

Reglas:
- Una plantilla deja sus bloques y sus conexiones, con sus puertos, y el grafo las acepta todas.
- Nunca cae encima de lo que ya hay en la pizarra.
- Una plantilla que no existe es un error, y no deja nada.

Plantillas de sector (perfiles que vienen con la app, PLAN_WORKSPACES W4, W5, §6):
- cada carpeta de `profile_templates/` es un perfil válido (pasa el mismo `plan` que un `.zip`,
  en cada idioma) y se marca como genérica;
- crear un workspace desde «Robótica» deja su perfil de fabricación y nada más (ni proveedores
  ni fichas: W5);
- una plantilla que no existe es un error y no crea nada;
- la carpeta va en el ejecutable de la app y en el repo público.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from pizarra import graph, profile_zip, scene, workspaces
from pizarra.startup import bootstrap
from pizarra.validation import ValidationError
from tests.helpers import new_board, necesita_paquetes


def overlaps(a, b):
    ax0, ay0, ax1, ay1 = scene.bbox(a)
    bx0, by0, bx1, by1 = scene.bbox(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


class Plantillas(unittest.TestCase):
    def setUp(self):
        self.b = new_board()

    @necesita_paquetes
    def test_deja_bloques_y_conexiones_que_el_grafo_acepta(self):
        t = self.b.registry.templates["robotica.brazo"]
        new = self.b.add_template("robotica.brazo")
        blocks = [e for e in new if e["type"] == "embeddable"]
        arrows = [e for e in new if e["type"] == "arrow"]
        self.assertEqual((len(blocks), len(arrows)), (len(t.blocks), len(t.links)))
        edges, problems = graph.build(self.b.elements, self.b.registry)
        self.assertEqual(problems, [])
        self.assertEqual(sum(len(v) for v in edges.values()), len(t.links))
        for a in arrows:
            self.assertEqual(a["customData"]["kind"], "connection")
            src = next(e for e in blocks if e["id"] == a["startBinding"]["elementId"])
            self.assertIn({"id": a["id"], "type": "arrow"}, src["boundElements"])
        sts = self.b.statuses()
        self.assertEqual({sts[e["id"]] for e in blocks}, {"nunca", "no_disponible"})

    @necesita_paquetes
    def test_nunca_cae_encima_de_lo_que_ya_hay(self):
        tubo = scene.block_element("prueba.tubo", 300, 100)
        self.b.apply_client_elements([tubo])
        new = self.b.add_template("robotica.brazo", x=0, y=0)       # pedida encima del tubo
        for e in new:
            if e["type"] == "embeddable":
                self.assertFalse(overlaps(e, tubo), e["customData"]["blockType"])

    def test_donde_se_pide_si_cabe(self):
        new = self.b.add_template("prueba.cadena", x=500, y=-200)
        self.assertEqual(min(e["x"] for e in new if e["type"] == "embeddable"), 500)

    def test_una_que_no_existe_es_un_error_y_no_deja_nada(self):
        with self.assertRaises(ValidationError):
            self.b.add_template("robotica.no_existe")
        self.assertEqual(self.b.elements, [])


REPO = Path(__file__).resolve().parents[3]


class PlantillasDeSector(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_cada_una_es_un_perfil_valido_y_generico(self):
        carpetas = {p.name for p in profile_zip.TEMPLATES_DIR.iterdir() if p.is_dir()}
        self.assertIn("robotica", carpetas)
        for lang in ("es", "en"):
            ts = profile_zip.templates(lang)
            self.assertEqual({t["id"] for t in ts}, carpetas)
            for t in ts:
                self.assertTrue(t["generica"], t["id"])
                self.assertTrue(t["titulo"] and t["descripcion"], (t["id"], lang))
                zip_ = profile_zip.write_template(t["id"], self.tmp / lang, lang)
                plan = profile_zip.plan(None, zip_, "nuevo")
                self.assertEqual((plan["invalid"], plan["ignored"]), ([], []), (t["id"], lang))
                self.assertTrue(plan["manifest"]["generica"])
                self.assertEqual(plan["fabricacion"], t["lleva"]["fabricacion"])
                self.assertEqual(plan["fichas"], t["lleva"]["fichas"])
                self.assertEqual(plan["proveedores"], t["lleva"]["proveedores"])

    def test_empaquetarla_dos_veces_da_los_mismos_bytes(self):
        a = profile_zip.write_template("robotica", self.tmp / "a", "es").read_bytes()
        b = profile_zip.write_template("robotica", self.tmp / "b", "es").read_bytes()
        self.assertEqual(a, b)

    def crear(self, lang):
        start = bootstrap(self.tmp / "settings.toml", self.tmp / "Docs" / "Personal", ())
        info, done = workspaces.create(start.settings, "Taller", base=self.tmp / "Docs",
                                       desde="plantilla:robotica", language=lang)
        from pizarra.storage import LocalWorkspace
        return LocalWorkspace.open(self.tmp / "Docs" / "Taller"), done

    def test_robotica_deja_su_perfil_de_fabricacion_y_nada_mas(self):
        ws, done = self.crear("es")
        texto = ws.load_manufacturing_profile()
        esperado = (profile_zip.TEMPLATES_DIR / "robotica" / "fabricacion.md").read_text(
            encoding="utf-8")
        self.assertEqual(texto, esperado)
        for tema in ("aluminio", "impresión 3d", "chapa", "perfil ranurado", "tolerancia",
                     "genéric", "orden de magnitud"):
            self.assertIn(tema, texto.lower())
        self.assertEqual((ws.list_library_fichas(), ws.load_providers_text(), ws.load_stock()),
                         ({}, None, {}))
        self.assertEqual((done["fabricacion"], done["fichas"], done["copia"]), (True, 0, None))

    def test_en_ingles_con_su_texto_en_ingles(self):
        ws, _ = self.crear("en")
        texto = ws.load_manufacturing_profile()
        self.assertEqual(texto, (profile_zip.TEMPLATES_DIR / "robotica" / "fabricacion.en.md")
                         .read_text(encoding="utf-8"))
        for tema in ("aluminium", "3d printing", "sheet", "slotted", "generic"):
            self.assertIn(tema, texto.lower())

    def test_una_plantilla_que_no_existe_es_un_error_y_no_crea_nada(self):
        start = bootstrap(self.tmp / "settings.toml", self.tmp / "Docs" / "Personal", ())
        for desde in ("plantilla:no_existe", "plantilla:../robotica", "plantilla:"):
            with self.assertRaises(ValueError, msg=desde):
                workspaces.create(start.settings, "Taller", base=self.tmp / "Docs", desde=desde)
        self.assertFalse((self.tmp / "Docs" / "Taller").exists())
        self.assertEqual(len(start.settings.workspaces()), 1)

    def test_va_en_el_ejecutable(self):
        # el backend de la app es un ejecutable de PyInstaller: un dato que no está en
        # `--add-data` no existe en la app instalada (como `pack_template`)
        build = (REPO / "app" / "shell" / "build_sidecar.py").read_text(encoding="utf-8")
        self.assertIn("'profile_templates'}{sep}pizarra/profile_templates", build)

    # `exportar_publico.py` es del repo privado y no se publica: en el público no hay qué mirar
    @unittest.skipUnless((REPO / "scripts" / "exportar_publico.py").is_file(),
                         "sin scripts/exportar_publico.py: solo en el repo de desarrollo")
    def test_va_en_el_repo_publico(self):
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            import exportar_publico
        finally:
            sys.path.remove(str(REPO / "scripts"))
        for p in profile_zip.TEMPLATES_DIR.rglob("*"):
            if p.is_file():
                rel = p.relative_to(REPO).as_posix()
                self.assertTrue(exportar_publico.publica(rel), rel)
                self.assertFalse(exportar_publico.prohibida(rel), rel)


if __name__ == "__main__":
    unittest.main()
