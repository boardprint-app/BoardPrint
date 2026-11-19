"""Archivos y carpetas: rutas, tipos, hash de lo marcado, sondeo y salidas a una carpeta
(plan D109, D110, D132, D134, D136, D138, §10).

Reglas:
- Dentro del workspace la ruta se guarda relativa y fuera absoluta; un workspace movido sigue
  encontrando sus archivos.
- `.stp` es un STEP; nada sale con el tipo `archivo.stp`.
- El hash de una carpeta solo cambia con lo marcado: un archivo desmarcado o fuera del patrón
  nunca lo cambia, y cambiar, añadir, quitar o renombrar uno marcado siempre lo hace. Sin
  marcar nada entra todo, subcarpetas incluidas.
- El sondeo nunca vuelve a leer un archivo cuya fecha y tamaño no han cambiado (antes de
  ejecutar, `fresh`, lee todo). Lo que no está sale sin hash y con motivo.
- Por encima de 500 MB, una carpeta no calcula el hash sin confirmar.
- Por defecto nunca se sobrescribe: el archivo nuevo es el primer `_n` libre; sobrescribir
  solo pisa ese archivo; una copia que falla vuelve con su error, no para las demás y nunca
  toca el origen.
- Quitar una tarjeta de la pizarra nunca borra el archivo.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pizarra import files, packs
from pizarra.board import Board
from pizarra.files import Content, Prober
from pizarra.storage import LocalWorkspace


def tmp():
    return Path(tempfile.mkdtemp())


def write(path, text, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, ns=(mtime, mtime))
    return path


class Counting:
    """`digest` que cuenta qué archivos lee."""

    def __init__(self):
        self.read = []

    def __call__(self, path):
        self.read.append(Path(path).name)
        return files.file_digest(path)


class Rutas(unittest.TestCase):
    def test_dentro_del_workspace_se_guarda_relativa_con_barras(self):
        ws = tmp()
        p = write(ws / "datos" / "motor.pdf", "x")
        self.assertEqual(files.stored_path(p, ws), "datos/motor.pdf")

    def test_fuera_del_workspace_se_guarda_absoluta(self):
        ws, fuera = tmp(), tmp()
        p = write(fuera / "robot.step", "x")
        stored = files.stored_path(p, ws)
        self.assertTrue(Path(stored).is_absolute())
        self.assertEqual(files.resolve(stored, ws), p.resolve())

    def test_un_workspace_movido_sigue_encontrando_lo_relativo(self):
        base = tmp()
        write(base / "ws" / "datos" / "a.pdf", "x")
        stored = files.stored_path(base / "ws" / "datos" / "a.pdf", base / "ws")
        (base / "ws").rename(base / "otro")
        self.assertTrue(files.resolve(stored, base / "otro").is_file())


class Tipos(unittest.TestCase):
    def test_el_tipo_va_por_la_extension_en_minusculas(self):
        self.assertEqual(files.port_type("datos/Motor.PDF"), "archivo.pdf")
        self.assertEqual(files.port_type("r.step"), "archivo.step")

    def test_stp_es_un_step(self):
        self.assertEqual(files.port_type("robot.STP"), "archivo.step")

    def test_sin_extension_es_archivo(self):
        self.assertEqual(files.port_type("LEEME"), "archivo")

    def test_un_alias_no_es_un_tipo_de_archivo(self):
        self.assertTrue(files.is_file_port("archivo.step"))
        self.assertTrue(files.is_file_port("archivo"))
        self.assertFalse(files.is_file_port("archivo.stp"))
        self.assertFalse(files.is_file_port("carpeta"))

    def test_un_paquete_puede_declarar_entradas_de_archivo_y_carpeta(self):
        root = tmp()
        for pid, inputs in (("fbien", "{'a': 'archivo', 'b': 'archivo.pdf', 'c': 'carpeta', 'd': 'archivo.step'}"),
                            ("fmal", "{'a': 'archivo.stp'}")):
            (root / pid).mkdir()
            (root / pid / "pack.toml").write_text(
                f'id = "{pid}"\nname = "P"\nauthor = "Pruebas"\ndescription = "Paquete de prueba"\nversion = "0.1.0"\nsdk = ">=1.0,<2"\nmodule = "blocks"\n', encoding="utf-8")
            (root / pid / "blocks.py").write_text(
                "def register(pack):\n"
                f"    pack.block('{pid}.lee', 'Lee', lambda p, i, c: {{}}, inputs={inputs})\n",
                encoding="utf-8")
        reg = packs.load([root], log=lambda m: None)
        errors = {p.id: p.error for p in reg.packs}
        self.assertIsNone(errors["fbien"])
        self.assertIn("fbien.lee", reg)
        self.assertIn("archivo.stp", errors["fmal"] or "", "un alias no lo registra nadie")


class HashDeCarpeta(unittest.TestCase):
    """El hash de una carpeta solo cambia con lo marcado (D110, D136)."""

    def setUp(self):
        self.dir = tmp()
        write(self.dir / "a.pdf", "a")
        write(self.dir / "b.txt", "b")
        write(self.dir / "sub" / "c.pdf", "c")
        self.prober = Prober()

    def h(self, content=Content()):
        return self.prober.probe_folder(self.dir, content, fresh=True).hash

    def test_sin_marcar_nada_entra_todo_con_subcarpetas(self):
        st = self.prober.probe_folder(self.dir)
        self.assertEqual(st.files, ("a.pdf", "b.txt", "sub/c.pdf"))
        self.assertTrue(Content().everything)

    def test_cambiar_anadir_quitar_o_renombrar_uno_marcado_cambia_el_hash(self):
        seen = {self.h()}
        write(self.dir / "sub" / "c.pdf", "otro")
        seen.add(self.h())
        write(self.dir / "d.pdf", "d")
        seen.add(self.h())
        (self.dir / "a.pdf").unlink()
        seen.add(self.h())
        (self.dir / "d.pdf").rename(self.dir / "e.pdf")
        seen.add(self.h())
        self.assertEqual(len(seen), 5, "cada cambio da un hash distinto")

    def test_un_desmarcado_nunca_cambia_el_hash(self):
        c = Content(exclude=("b.txt",))
        h0 = self.h(c)
        write(self.dir / "b.txt", "cambiado")
        self.assertEqual(self.h(c), h0)
        (self.dir / "b.txt").unlink()
        self.assertEqual(self.h(c), h0)

    def test_una_subcarpeta_desmarcada_quita_todo_lo_suyo(self):
        c = Content(exclude=("sub",))
        h0 = self.h(c)
        write(self.dir / "sub" / "nuevo.pdf", "n")
        write(self.dir / "sub" / "c.pdf", "otro")
        self.assertEqual(self.h(c), h0)
        self.assertEqual(self.prober.probe_folder(self.dir, c).files, ("a.pdf", "b.txt"))

    def test_fuera_del_patron_nunca_cambia_el_hash(self):
        c = Content(patterns=("*.PDF",))
        self.assertEqual(self.prober.probe_folder(self.dir, c).files, ("a.pdf", "sub/c.pdf"))
        h0 = self.h(c)
        write(self.dir / "b.txt", "cambiado")
        write(self.dir / "nuevo.txt", "n")
        self.assertEqual(self.h(c), h0)
        write(self.dir / "nuevo.pdf", "n")
        self.assertNotEqual(self.h(c), h0, "uno nuevo que cumple el patrón entra")

    def test_lo_marcado_se_lee_de_la_tarjeta(self):
        c = Content.from_card({"exclude": ["sub/"], "patterns": ["*.pdf", " "]})
        self.assertEqual(c, Content(("sub",), ("*.pdf",)))
        self.assertFalse(c.everything)

    def test_por_encima_del_limite_no_calcula_el_hash_sin_confirmar(self):
        reader = Counting()
        p = Prober(reader)
        with mock.patch.object(files, "BIG_FOLDER", 1):
            st = p.probe_folder(self.dir)
            self.assertTrue(st.big)
            self.assertIsNone(st.hash)
            self.assertIn("MB", st.reason)
            self.assertEqual(reader.read, [], "ni un archivo leído")
            self.assertIsNotNone(p.probe_folder(self.dir, allow_big=True).hash)


class Sondeo(unittest.TestCase):
    """D134: solo se vuelve a leer lo que ha cambiado de fecha o de tamaño."""

    def setUp(self):
        self.dir = tmp()
        self.a = write(self.dir / "a.pdf", "a", mtime=10 ** 18)
        self.b = write(self.dir / "b.pdf", "b", mtime=10 ** 18)
        self.reader = Counting()
        self.p = Prober(self.reader)

    def test_sin_cambios_de_fecha_ni_tamano_nunca_vuelve_a_leer(self):
        first = self.p.probe_folder(self.dir)
        self.p.probe_file(self.a)
        self.reader.read.clear()
        again = self.p.probe_folder(self.dir)
        self.p.probe_file(self.a)
        self.assertEqual(self.reader.read, [])
        self.assertEqual(again.hash, first.hash)

    def test_lee_solo_el_que_ha_cambiado(self):
        h0 = self.p.probe_folder(self.dir).hash
        self.reader.read.clear()
        write(self.b, "B", mtime=10 ** 18 + 10 ** 9)     # mismo tamaño, un segundo después
                                                         # (NTFS guarda la fecha en pasos de 100 ns)
        st = self.p.probe_folder(self.dir)
        self.assertEqual(self.reader.read, ["b.pdf"])
        self.assertNotEqual(st.hash, h0)

    def test_antes_de_ejecutar_lee_todo(self):
        self.p.probe_folder(self.dir)
        self.reader.read.clear()
        self.p.probe_folder(self.dir, fresh=True)
        self.assertEqual(sorted(self.reader.read), ["a.pdf", "b.pdf"])

    def test_un_archivo_cambiado_cambia_su_hash(self):
        h0 = self.p.probe_file(self.a).hash
        write(self.a, "otro contenido")
        self.assertNotEqual(self.p.probe_file(self.a).hash, h0)

    def test_lo_que_no_esta_sale_sin_hash_y_con_motivo(self):
        h0 = self.p.probe_file(self.a).hash
        self.assertIsNotNone(h0)
        self.a.unlink()
        st = self.p.probe_file(self.a)
        self.assertIsNone(st.hash, "nunca el hash viejo de la caché")
        self.assertEqual(st.reason, "no encontrado")
        self.assertIsNone(self.p.probe_folder(self.dir / "nada").hash)
        self.assertIsNone(self.p.probe_file(self.dir).hash, "una carpeta no es un archivo")
        self.assertIsNone(self.p.probe_folder(self.b).hash, "un archivo no es una carpeta")

    def test_olvidar_deja_en_la_cache_solo_lo_de_la_pizarra(self):
        self.p.probe_file(self.a)
        self.p.probe_file(self.b)
        self.p.forget([self.a])
        self.reader.read.clear()
        self.p.probe_file(self.a)
        self.p.probe_file(self.b)
        self.assertEqual(self.reader.read, ["b.pdf"])


class SalidasACarpeta(unittest.TestCase):
    """D109: nunca se pisa nada sin que lo diga el usuario."""

    def setUp(self):
        self.src = tmp()
        self.dest = tmp()
        self.bom = write(self.src / "bom.xlsx", "v1")
        self.inf = write(self.src / "informe.pdf", "v1")

    def test_el_primer_n_libre(self):
        self.assertEqual(files.first_free(self.dest, "bom.xlsx").name, "bom.xlsx")
        write(self.dest / "bom.xlsx", "x")
        self.assertEqual(files.first_free(self.dest, "bom.xlsx").name, "bom_1.xlsx")
        write(self.dest / "bom_1.xlsx", "x")
        self.assertEqual(files.first_free(self.dest, "bom.xlsx").name, "bom_2.xlsx")

    def test_por_defecto_dos_ejecuciones_nunca_pisan_nada(self):
        files.copy_outputs([self.bom], self.dest)
        write(self.bom, "v2")
        r = files.copy_outputs([self.bom], self.dest)
        self.assertEqual(r[0].dest.name, "bom_1.xlsx")
        self.assertEqual((self.dest / "bom.xlsx").read_text(encoding="utf-8"), "v1")
        self.assertEqual((self.dest / "bom_1.xlsx").read_text(encoding="utf-8"), "v2")

    def test_sobrescribir_solo_pisa_ese_archivo(self):
        write(self.dest / "bom.xlsx", "viejo")
        write(self.dest / "informe.pdf", "viejo")
        r = files.copy_outputs([self.bom, self.inf], self.dest, overwrite={"bom.xlsx"})
        self.assertEqual([x.dest.name for x in r], ["bom.xlsx", "informe_1.pdf"])
        self.assertEqual((self.dest / "bom.xlsx").read_text(encoding="utf-8"), "v1")
        self.assertEqual((self.dest / "informe.pdf").read_text(encoding="utf-8"), "viejo")

    def test_una_copia_que_falla_vuelve_con_error_y_no_para_las_demas(self):
        real = files.shutil.copy2

        def copy2(a, b):
            if Path(a).name == "bom.xlsx":
                raise PermissionError(13, "Permiso denegado")
            return real(a, b)

        with mock.patch.object(files.shutil, "copy2", copy2):
            r = files.copy_outputs([self.bom, self.inf], self.dest)
        self.assertIn("Permiso denegado", r[0].error)
        self.assertIsNone(r[0].dest)
        self.assertIsNone(r[1].error)
        self.assertTrue((self.dest / "informe.pdf").is_file())
        self.assertEqual(self.bom.read_text(encoding="utf-8"), "v1", "el origen no se toca")

    def test_a_una_carpeta_que_no_esta_nunca_la_crea(self):
        r = files.copy_outputs([self.bom], self.dest / "nada")
        self.assertEqual(r[0].error, "la carpeta no existe")
        self.assertFalse((self.dest / "nada").exists())
        self.assertTrue(self.bom.is_file())


def empty_board():
    ws = LocalWorkspace.open(tmp() / "Personal", trash=lambda p: None)
    return Board(ws, ws.create_project("", "F").id, registry=packs.Registry(),
                 connectors=frozenset())


class QuitarTarjeta(unittest.TestCase):
    def test_quitar_una_tarjeta_nunca_borra_el_archivo(self):
        b = empty_board()
        doc = write(tmp() / "motor.pdf", "x")
        card = {"id": "f1", "type": "rectangle", "version": 1, "isDeleted": False,
                "customData": {"kind": "file", "path": str(doc)}}
        b.apply_client_elements([card])
        b.probe()
        b.save()
        b.apply_client_elements([{**card, "version": 2, "isDeleted": True}])
        b.probe()
        b.save()
        self.assertTrue(doc.is_file())
        self.assertEqual(b.sources, {}, "y deja de sondearla")


class TarjetasEnLaPizarra(unittest.TestCase):
    """D59, D134, D138 en la pizarra: añadir, sondear y «Buscar de nuevo»."""

    def setUp(self):
        self.b = empty_board()

    def test_dentro_del_workspace_relativa_fuera_absoluta_y_la_carpeta_es_carpeta(self):
        dentro = write(self.b.ws.root / "datos" / "motor.pdf", "x")
        fuera = write(tmp() / "robot.step", "x")
        a, f, d = self.b.add_cards([dentro, fuera, fuera.parent])
        self.assertEqual(a["customData"], {**a["customData"], "kind": "file", "path": "datos/motor.pdf"})
        self.assertTrue(Path(f["customData"]["path"]).is_absolute())
        self.assertEqual(d["customData"]["kind"], "folder")
        self.assertEqual(d["customData"]["content"], {"exclude": [], "patterns": []})
        self.assertLess(a["y"], f["y"], "en columna, sin taparse")

    def test_la_tarjeta_de_una_ruta_es_la_que_ya_apunta_a_ella(self):
        dentro = write(self.b.ws.root / "datos" / "motor.pdf", "x")
        fuera = write(tmp() / "robot.step", "x")
        a, f = self.b.add_cards([dentro, fuera])
        self.assertEqual(self.b.card_for(dentro)["id"], a["id"], "relativa al workspace")
        self.assertEqual(self.b.card_for(fuera)["id"], f["id"], "absoluta")
        self.assertIsNone(self.b.card_for(fuera.parent), "la carpeta no es el archivo")

    def test_una_ruta_que_no_existe_no_crea_nada(self):
        from pizarra.validation import ValidationError
        with self.assertRaises(ValidationError):
            self.b.add_cards([tmp() / "no.pdf"])
        self.assertEqual(self.b.elements, [])

    def test_el_sondeo_nunca_vuelve_a_leer_lo_que_no_ha_cambiado(self):
        reader = Counting()
        self.b.prober = Prober(reader)
        doc = write(tmp() / "motor.pdf", "x")
        (card,) = self.b.add_cards([doc])
        self.assertTrue(self.b.probe())
        self.assertFalse(self.b.probe(), "nada nuevo que enseñar")
        self.assertEqual(reader.read, ["motor.pdf"])
        self.b.probe(fresh=True)
        self.assertEqual(reader.read, ["motor.pdf", "motor.pdf"], "antes de ejecutar, todo")
        self.assertTrue(self.b.sources_view()[card["id"]]["ok"])

    def test_lo_que_no_esta_sale_no_encontrado_y_buscar_de_nuevo_conserva_la_tarjeta(self):
        doc = write(tmp() / "motor.pdf", "x")
        (card,) = self.b.add_cards([doc])
        doc.unlink()
        self.b.probe()
        view = self.b.sources_view()[card["id"]]
        self.assertEqual((view["ok"], view["reason"]), (False, "no encontrado"))
        nuevo = write(tmp() / "motor_v2.pdf", "y")
        moved = self.b.relocate_card(card["id"], nuevo)
        self.assertEqual(moved["id"], card["id"])
        self.assertGreater(moved["version"], card["version"])
        self.b.probe()
        self.assertTrue(self.b.sources_view()[card["id"]]["ok"])

    def test_la_carpeta_dice_cuantos_entran_de_cuantos_y_los_tipos_que_asoman(self):
        d = tmp()
        for n in ("a.pdf", "b.STP", "c.txt", "sub/d.pdf"):
            write(d / n, "x")
        (card,) = self.b.add_cards([d])
        self.b.apply_client_elements([{**card, "version": card["version"] + 1, "customData": {
            **card["customData"], "content": {"exclude": ["c.txt"], "patterns": []}}}])
        self.b.probe()
        view = self.b.sources_view()[card["id"]]
        self.assertEqual((view["type"], view["files"], view["total"]), ("carpeta", 3, 4))
        self.assertEqual(view["peek"], ["archivo.pdf", "archivo.step", "archivo.pdf"])
        (doc,) = self.b.add_cards([d / "b.STP"])
        self.assertEqual(self.b.sources_view()[doc["id"]]["type"], "archivo.step",
                         "el tipo sale de la ruta, también antes del primer sondeo")

    def test_buscar_de_nuevo_no_cambia_un_archivo_por_una_carpeta(self):
        from pizarra.validation import ValidationError
        (card,) = self.b.add_cards([write(tmp() / "motor.pdf", "x")])
        with self.assertRaises(ValidationError):
            self.b.relocate_card(card["id"], tmp())

    def test_una_carpeta_grande_espera_a_confirmar_y_luego_tiene_hash(self):
        d = tmp()
        write(d / "a.pdf", "x" * 100)
        (card,) = self.b.add_cards([d])
        with mock.patch.object(files, "BIG_FOLDER", 10):
            self.b.probe()
            self.assertTrue(self.b.sources_view()[card["id"]]["big"])
            self.assertFalse(self.b.sources_view()[card["id"]]["ok"])
            self.b.confirm_big(card["id"])
            self.b.probe()
            self.assertTrue(self.b.sources_view()[card["id"]]["ok"])


class VistaDeCarpeta(unittest.TestCase):
    """D139: la vista en árbol, con casillas de tres estados en las subcarpetas."""

    def test_lo_marcado_y_las_casillas_de_las_subcarpetas(self):
        d = tmp()
        for rel in ("a.pdf", "sub/b.pdf", "sub/c.txt", "solo/d.txt", "fuera/e.pdf"):
            write(d / rel, rel)
        entries, cut = files.tree(d, Content(exclude=("fuera",), patterns=("*.pdf",)))
        got = {e["path"]: e["marked"] for e in entries}
        self.assertFalse(cut)
        self.assertEqual(got, {"fuera": "none", "solo": "none", "sub": "some",
                               "a.pdf": True, "fuera/e.pdf": False, "solo/d.txt": False,
                               "sub/b.pdf": True, "sub/c.txt": False})
        self.assertEqual(next(e for e in entries if e["path"] == "sub")["size"], 18)

    def test_sin_marcar_nada_todo_entra(self):
        d = tmp()
        write(d / "sub" / "b.pdf", "x")
        entries, _ = files.tree(d)
        self.assertEqual([e["marked"] for e in entries], ["all", True])

    def test_una_carpeta_enorme_se_corta_y_lo_dice(self):
        d = tmp()
        for i in range(5):
            write(d / f"{i}.txt", "x")
        entries, cut = files.tree(d, limit=3)
        self.assertTrue(cut)
        self.assertEqual(len(entries), 3)


if __name__ == "__main__":
    unittest.main()
