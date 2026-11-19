"""Office con el agente (plan D61, D176, §10 «Office con el agente» y «Edición de Office»).

Reglas que protegen:
- `editar_archivo` nunca escribe sobre el original (se compara byte a byte antes y después):
  escribe `<nombre>_n.<ext>`, el primer libre, y deja una propuesta con el diff legible.
- Aceptar pasa la tarjeta al archivo nuevo (la misma tarjeta: las conexiones siguen) y el
  original sigue igual; rechazar manda a la papelera solo el nuevo.
- `crear_archivo` nunca pisa un archivo (`_n`), escribe donde se le deja (la carpeta del
  proyecto o una tarjeta de carpeta, nunca una ruta suya) y su tarjeta es del agente.
- Las cifras que escribe el agente llevan fuente (D19); con *Excluir adjuntos*, no edita.
- Un cambio que no vale no deja nada: ni copia ni propuesta.

Los archivos se crean en el test, pequeños.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from pizarra import agent, agent_office_tools as aot, read_files
from pizarra.board import Board
from pizarra.storage import LocalWorkspace

FIG_SRC = [{"kind": "calculo", "formula": "dato del enunciado", "inputs": []}]


def new_board():
    """Una pizarra cuya papelera borra de verdad (y apunta qué), para ver qué se quita."""
    trashed = []

    def trash(p):
        trashed.append(Path(p))
        os.remove(p)

    ws = LocalWorkspace.open(Path(tempfile.mkdtemp()) / "Personal", trash=trash)
    board = Board(ws, ws.create_project("", "Proyecto").id, connectors=frozenset())
    return board, trashed


def _docx(path):
    import docx
    d = docx.Document()
    d.add_heading("Oferta", level=1)
    d.add_paragraph("Plazo de entrega: cuatro semanas")
    d.add_paragraph("Precio sin IVA")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Pieza", "Material"
    t.cell(1, 0).text, t.cell(1, 1).text = "Ménsula", "acero S275"
    d.save(path)
    return Path(path)


def _xlsx(path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lista"
    ws.append(["Ref", "Cantidad"])
    ws.append(["M6", 4])
    ws["C2"] = "=B2*2"
    wb.create_sheet("Notas")["A1"] = "nada"
    wb.save(path)
    return Path(path)


def _pptx(path):
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Revisión de diseño"
    s.placeholders[1].text_frame.text = "Material pendiente"
    s.shapes.add_textbox(Inches(1), Inches(6.5), Inches(4), Inches(0.5)).text_frame.text = "Pie"
    prs.save(path)
    return Path(path)


def _card(board, path):
    return board.add_cards([path])[0]["id"]


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in Path(folder).iterdir() if p.is_file()}


class EditarNuncaPisa(unittest.TestCase):
    def setUp(self):
        self.board, self.trashed = new_board()
        self.dir = Path(tempfile.mkdtemp())

    def _edit(self, card, cambios, **kw):
        result, proposed = aot.tool_editar_archivo(
            self.board, {"tarjeta": card, "cambios": cambios, "motivo": "lo pide el ingeniero",
                         **kw})
        return result, proposed

    def test_word_escribe_la_copia_y_el_original_queda_byte_a_byte(self):
        src = _docx(self.dir / "oferta.docx")
        before = src.read_bytes()
        card = _card(self.board, src)
        result, proposed = self._edit(card, [{"parrafo": 2, "texto": "Plazo de entrega: dos semanas"}])
        self.assertTrue(proposed, result)
        self.assertEqual(src.read_bytes(), before)
        new = self.dir / "oferta_1.docx"
        self.assertTrue(new.is_file())
        text = "\n".join(c.text for c in read_files.read(new))
        self.assertIn("dos semanas", text)
        self.assertNotIn("cuatro semanas", text)
        self.assertIn("cuatro semanas", "\n".join(c.text for c in read_files.read(src)))
        # la tarjeta sigue en el original hasta que se acepte
        self.assertEqual(self.board.card_path(self.board.card(card)), src)

    def test_diff_de_word_parrafo_celda_y_texto_que_habia(self):
        src = _docx(self.dir / "oferta.docx")
        card = _card(self.board, src)
        self._edit(card, [{"tabla": 1, "fila": 2, "columna": 2, "texto": "aluminio 6061-T6"},
                          {"antes": "sin IVA", "texto": "con IVA"}])
        p = self.board.proposals[-1]
        diff = p["change"]["file"]["diff"]
        self.assertEqual(diff, [
            {"where": "tabla 1, fila 2, columna 2", "before": "acero S275", "after": "aluminio 6061-T6"},
            {"where": "párrafo 3", "before": "Precio sin IVA", "after": "Precio con IVA"}])
        table = [c for c in read_files.read(self.dir / "oferta_1.docx") if c.table][0]
        self.assertEqual(table.table[1], ("Ménsula", "aluminio 6061-T6"))

    def test_diff_de_excel_por_celda_con_la_hoja(self):
        src = _xlsx(self.dir / "lista.xlsx")
        before = src.read_bytes()
        card = _card(self.board, src)
        result, proposed = self._edit(card, [{"celda": "Lista!B2", "valor": 6}], sources=FIG_SRC)
        self.assertTrue(proposed, result)
        self.assertEqual(src.read_bytes(), before)
        self.assertEqual(self.board.proposals[-1]["change"]["file"]["diff"],
                         [{"where": "Lista!B2", "before": "4", "after": "6"}])
        import openpyxl
        wb = openpyxl.load_workbook(self.dir / "lista_1.xlsx")
        self.assertEqual(wb["Lista"]["B2"].value, 6)
        self.assertEqual(wb["Lista"]["C2"].value, "=B2*2")      # la fórmula sigue en la copia

    def test_diff_de_powerpoint_por_diapositiva_y_forma(self):
        src = _pptx(self.dir / "revision.pptx")
        before = src.read_bytes()
        card = _card(self.board, src)
        result, proposed = self._edit(card, [{"diapositiva": 1, "forma": 2, "texto": "Material: aluminio"},
                                             {"antes": "Pie", "texto": "Pie de página"}])
        self.assertTrue(proposed, result)
        self.assertEqual(src.read_bytes(), before)
        self.assertEqual(self.board.proposals[-1]["change"]["file"]["diff"], [
            {"where": "diapositiva 1, forma 2", "before": "Material pendiente", "after": "Material: aluminio"},
            {"where": "diapositiva 1, forma 3", "before": "Pie", "after": "Pie de página"}])
        text = read_files.read(self.dir / "revision_1.pptx")[0].text
        self.assertIn("Material: aluminio", text)

    def test_la_copia_es_el_primer_n_libre_y_no_toca_las_que_hay(self):
        src = _docx(self.dir / "oferta.docx")
        (self.dir / "oferta_1.docx").write_bytes(b"otra version")
        card = _card(self.board, src)
        self._edit(card, [{"parrafo": 3, "texto": "Precio cerrado"}])
        self.assertEqual((self.dir / "oferta_1.docx").read_bytes(), b"otra version")
        self.assertTrue((self.dir / "oferta_2.docx").is_file())
        self.assertTrue(self.board.proposals[-1]["change"]["file"]["nuevo"].endswith("oferta_2.docx"))

    def test_tambien_en_una_tarjeta_del_agente_deja_propuesta(self):
        src = _docx(self.dir / "oferta.docx")
        card = self.board.add_cards([src], author=agent.AGENT)[0]["id"]
        before = src.read_bytes()
        _, proposed = self._edit(card, [{"parrafo": 3, "texto": "Precio cerrado"}])
        self.assertTrue(proposed)
        self.assertEqual(src.read_bytes(), before)
        self.assertEqual(self.board.card_path(self.board.card(card)), src)

    def test_un_cambio_que_no_vale_no_deja_ni_copia_ni_propuesta(self):
        src = _docx(self.dir / "oferta.docx")
        card = _card(self.board, src)
        before = _snapshot(self.dir)
        for cambios in ([{"parrafo": 9, "texto": "x"}], [{"antes": "no está", "texto": "x"}],
                        [{"antes": "e", "texto": "x"}], [{"parrafo": 2, "texto": "Plazo de entrega: cuatro semanas"}],
                        [], "texto"):
            result, proposed = self._edit(card, cambios)
            self.assertFalse(proposed, cambios)
            self.assertTrue(result.get("is_error"), cambios)
        self.assertEqual(_snapshot(self.dir), before)
        self.assertEqual(self.board.proposals, [])

    def test_una_segunda_edicion_con_otra_pendiente_se_rechaza_sin_escribir(self):
        src = _docx(self.dir / "oferta.docx")
        card = _card(self.board, src)
        self._edit(card, [{"parrafo": 3, "texto": "Precio cerrado"}])
        before = _snapshot(self.dir)
        result, proposed = self._edit(card, [{"parrafo": 3, "texto": "Precio abierto"}])
        self.assertFalse(proposed)
        self.assertIn("pendiente", result["content"][0]["text"])
        self.assertEqual(_snapshot(self.dir), before)

    def test_ni_pdf_ni_carpeta_ni_formato_antiguo(self):
        (self.dir / "a.pdf").write_bytes(b"%PDF-1.4")
        (self.dir / "b.doc").write_bytes(b"viejo")
        sub = self.dir / "sub"
        sub.mkdir()
        for path in (self.dir / "a.pdf", self.dir / "b.doc", sub):
            card = _card(self.board, path)
            _, proposed = self._edit(card, [{"parrafo": 1, "texto": "x"}])
            self.assertFalse(proposed, path)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["a.pdf", "b.doc", "sub"])

    def test_cifras_sin_fuente_se_rechazan_sin_escribir(self):
        src = _xlsx(self.dir / "lista.xlsx")
        card = _card(self.board, src)
        result, proposed = self._edit(card, [{"celda": "Lista!B2", "valor": 6}])
        self.assertFalse(proposed)
        self.assertIn("fuente", result["content"][0]["text"])
        self.assertFalse((self.dir / "lista_1.xlsx").exists())
        _, proposed = self._edit(card, [{"celda": "Lista!B2", "valor": 6}], estimate=True)
        self.assertTrue(proposed)

    def test_con_excluir_adjuntos_no_edita(self):
        src = _docx(self.dir / "oferta.docx")
        card = _card(self.board, src)
        result, proposed = aot.tool_editar_archivo(
            self.board, {"tarjeta": card, "cambios": [{"parrafo": 3, "texto": "x"}],
                         "motivo": "m"}, excluded=True)
        self.assertFalse(proposed)
        self.assertIn("Excluir adjuntos", result["content"][0]["text"])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["oferta.docx"])

    def test_proponer_cambio_no_puede_apuntar_una_tarjeta_a_otra_ruta(self):
        src = _docx(self.dir / "oferta.docx")
        card = _card(self.board, src)
        result, _, proposed = agent.tool_proponer_cambio(self.board, {
            "target": card, "change": {"file": {"nuevo": str(self.dir / "otro.docx"), "diff": []}},
            "reason": "r"})
        self.assertFalse(proposed)
        self.assertTrue(result.get("is_error"))


class AceptarYRechazar(unittest.TestCase):
    def setUp(self):
        self.board, self.trashed = new_board()
        self.dir = Path(tempfile.mkdtemp())
        self.src = _docx(self.dir / "oferta.docx")
        self.before = self.src.read_bytes()
        self.card = _card(self.board, self.src)
        aot.tool_editar_archivo(self.board, {"tarjeta": self.card, "motivo": "m",
                                             "cambios": [{"parrafo": 3, "texto": "Precio cerrado"}]})
        self.p = self.board.proposals_view()[0]
        self.new = self.dir / "oferta_1.docx"

    def test_aceptar_pasa_la_tarjeta_al_nuevo_y_el_original_sigue_igual(self):
        bid = self.board.add_block("demo.viga")["id"] if "demo.viga" in self.board.registry \
            else None
        ids_before = [e["id"] for e in self.board.elements]
        changed = self.board.accept_proposal(self.p["id"], self.p["current"])
        self.assertEqual([e["id"] for e in changed], [self.card])
        self.assertEqual(self.board.card_path(self.board.card(self.card)), self.new)
        self.assertEqual([e["id"] for e in self.board.elements], ids_before)   # la misma tarjeta
        self.assertEqual(self.src.read_bytes(), self.before)
        self.assertTrue(self.new.is_file())
        self.assertEqual(self.trashed, [])
        self.assertEqual(self.board.proposals[-1]["state"], "aceptada")

    def test_aceptar_conserva_las_conexiones_de_la_tarjeta(self):
        arrow = {"id": "flecha", "type": "arrow", "x": 0, "y": 0, "width": 10, "height": 0,
                 "startBinding": {"elementId": self.card}, "endBinding": {"elementId": "b"},
                 "customData": {"kind": "connection", "from": "archivo", "to": "doc"}}
        self.board.elements = self.board.elements + [arrow]
        self.board.accept_proposal(self.p["id"], self.p["current"])
        a = next(e for e in self.board.elements if e["id"] == "flecha")
        self.assertEqual(a["startBinding"]["elementId"], self.card)

    def test_rechazar_borra_solo_el_nuevo(self):
        other = self.dir / "notas.txt"
        other.write_text("mías")
        self.board.reject_proposal(self.p["id"])
        self.assertEqual(self.trashed, [self.new.resolve()])
        self.assertFalse(self.new.exists())
        self.assertEqual(self.src.read_bytes(), self.before)
        self.assertEqual(other.read_text(), "mías")
        self.assertEqual(self.board.card_path(self.board.card(self.card)), self.src)
        self.assertEqual(self.board.proposals[-1]["state"], "rechazada")

    def test_con_la_tarjeta_cambiada_despues_no_se_acepta(self):
        other = _docx(self.dir / "otra.docx")
        self.board.relocate_card(self.card, other)
        view = self.board.proposals_view()[0]
        self.assertTrue(view["stale"])
        with self.assertRaises(Exception):
            self.board.accept_proposal(self.p["id"], self.p["current"])
        self.assertEqual(self.board.card_path(self.board.card(self.card)), other)

    def test_si_el_nuevo_ya_no_esta_aceptar_falla_y_la_tarjeta_no_cambia(self):
        self.new.unlink()
        with self.assertRaises(Exception):
            self.board.accept_proposal(self.p["id"], self.p["current"])
        self.assertEqual(self.board.card_path(self.board.card(self.card)), self.src)

    def test_la_propuesta_sobrevive_a_reabrir_la_pizarra(self):
        self.board.save()
        again = Board(self.board.ws, self.board.project_id, connectors=frozenset())
        p = again.proposals_view()[0]
        self.assertEqual(p["change"]["file"]["diff"][0]["after"], "Precio cerrado")
        json.dumps(p)         # se guarda y se manda tal cual


class CrearNuncaPisa(unittest.TestCase):
    def setUp(self):
        self.board, _ = new_board()

    def _create(self, **kw):
        args = {"tipo": "docx", "nombre": "informe",
                "contenido": {"bloques": [{"titulo": "Informe"}, {"parrafo": "Todo correcto"}]}}
        return aot.tool_crear_archivo(self.board, {**args, **kw})

    def test_en_la_carpeta_del_proyecto_con_su_tarjeta_del_agente(self):
        result, new = self._create()
        self.assertFalse(result.get("is_error"), result)
        path = self.board.dir / "archivos" / "informe.docx"
        self.assertTrue(path.is_file())
        self.assertEqual(new[0]["customData"]["author"], agent.AGENT)
        self.assertEqual(self.board.card_path(self.board.card(new[0]["id"])).resolve(), path.resolve())
        self.assertIn("Todo correcto", "\n".join(c.text for c in read_files.read(path)))

    def test_si_el_nombre_esta_usa_el_primer_n_libre_y_no_toca_el_que_hay(self):
        folder = self.board.dir / "archivos"
        folder.mkdir()
        (folder / "informe.docx").write_bytes(b"del ingeniero")
        (folder / "informe_1.docx").write_bytes(b"otra")
        result, new = self._create()
        self.assertEqual((folder / "informe.docx").read_bytes(), b"del ingeniero")
        self.assertEqual((folder / "informe_1.docx").read_bytes(), b"otra")
        self.assertTrue((folder / "informe_2.docx").is_file())
        self.assertIn("informe_2.docx", result["content"][0]["text"])

    def test_en_una_tarjeta_de_carpeta_y_nunca_en_otra_ruta(self):
        user = Path(tempfile.mkdtemp())
        folder = self.board.add_cards([user])[0]["id"]
        result, new = self._create(tipo="xlsx", nombre="materiales",
                                   contenido={"hojas": [{"nombre": "BOM", "filas": [["Ref"], ["M6"]]}]},
                                   carpeta=folder)
        self.assertFalse(result.get("is_error"), result)
        self.assertTrue((user / "materiales.xlsx").is_file())
        for bad in (str(user), "no-existe"):
            result, new = self._create(carpeta=bad)
            self.assertTrue(result.get("is_error"))
            self.assertEqual(new, [])
        for name in ("../fuera", "C:\\x\\y", "a/b"):
            result, _ = self._create(nombre=name)
            self.assertTrue(result.get("is_error"), name)
        self.assertEqual(sorted(p.name for p in user.iterdir()), ["materiales.xlsx"])

    def test_powerpoint_con_vinetas_y_tabla(self):
        result, _ = self._create(tipo="pptx", nombre="revision", contenido={"diapositivas": [
            {"titulo": "Revisión", "vinetas": ["Material", "Uniones"], "tabla": [["Pieza", "Estado"], ["Ménsula", "ok"]]}]})
        self.assertFalse(result.get("is_error"), result)
        chunks = read_files.read(self.board.dir / "archivos" / "revision.pptx")
        self.assertIn("Uniones", chunks[0].text)
        self.assertEqual(chunks[1].table[1], ("Ménsula", "ok"))

    def test_cifras_sin_fuente_se_rechazan_sin_escribir(self):
        content = {"bloques": [{"parrafo": "La flecha es de 1,2 mm"}]}
        result, new = self._create(contenido=content)
        self.assertTrue(result.get("is_error"))
        self.assertEqual(new, [])
        self.assertFalse((self.board.dir / "archivos" / "informe.docx").exists())
        result, new = self._create(contenido=content, estimate=True)
        self.assertFalse(result.get("is_error"), result)
        self.assertTrue(new[0]["customData"]["estimate"])

    def test_un_contenido_que_no_vale_no_deja_nada(self):
        for tipo, content in (("docx", {"bloques": []}), ("docx", {"bloques": [{"otro": 1}]}),
                              ("xlsx", {"hojas": [{"nombre": "a/b", "filas": [["x"]]}]}),
                              ("pptx", {"diapositivas": [{}]}), ("odt", {"bloques": []})):
            result, new = self._create(tipo=tipo, contenido=content)
            self.assertTrue(result.get("is_error"), (tipo, content))
            self.assertEqual(new, [])
        folder = self.board.dir / "archivos"
        self.assertEqual(list(folder.iterdir()) if folder.exists() else [], [])

    def test_con_excluir_adjuntos_si_crea(self):
        result, new = aot.tool_crear_archivo(self.board, {
            "tipo": "docx", "nombre": "nota", "contenido": {"bloques": [{"parrafo": "hola"}]}},
            excluded=True)
        self.assertFalse(result.get("is_error"), result)
        self.assertEqual(len(new), 1)


if __name__ == "__main__":
    unittest.main()
