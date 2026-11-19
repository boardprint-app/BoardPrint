"""Lectura de archivos para el agente (plan R36, §10 «Lectura de archivos»).

Reglas que protegen:
- Cada trozo lleva dónde está (página, párrafos o tabla, hoja y celda, diapositiva): una cifra
  que el agente saque de ahí se puede citar (D19).
- Nunca se lee un archivo que no está en la pizarra, ni uno desmarcado de una carpeta (R5).
- Un formato que no se conoce, uno roto o uno sin texto dan error, nunca texto vacío.
- Una cifra citada de un archivo necesita una tarjeta que existe y el sitio (`where`).

Los archivos se crean en el test, pequeños; el PDF, a mano (no hay biblioteca para escribirlos).
"""
import json
import tempfile
import unittest
from pathlib import Path

from pizarra import agent, read_files
from tests.helpers import new_board


def _pdf(path, pages):
    """Un PDF mínimo con una línea de texto por página (Helvetica)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    Path(path).write_bytes(bytes(out))
    return Path(path)


def _docx(path):
    import docx
    d = docx.Document()
    d.add_heading("Motor M3", level=1)
    d.add_paragraph("Par nominal 1.2 Nm")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Velocidad", "3000 rpm"
    t.cell(1, 0).text, t.cell(1, 1).text = "Masa", "0.8 kg"
    d.add_paragraph("Tras la tabla")
    d.save(path)
    return Path(path)


def _xlsx(path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lista de piezas"
    ws["B3"], ws["C3"] = "Pieza", "Masa"
    ws["B4"], ws["C4"] = "Brida", 0.25
    ws["C5"] = "=SUM(C4:C4)"
    wb.create_sheet("Vacía")
    wb.save(path)
    return Path(path)


def _pptx(path):
    from pptx import Presentation
    from pptx.util import Inches
    p = Presentation()
    s1 = p.slides.add_slide(p.slide_layouts[5])
    s1.shapes.title.text = "Resumen"
    s1.notes_slide.notes_text_frame.text = "Recordar el par"
    s2 = p.slides.add_slide(p.slide_layouts[6])
    tbl = s2.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(1)).table
    tbl.cell(0, 0).text, tbl.cell(0, 1).text = "Eje", "Par"
    tbl.cell(1, 0).text, tbl.cell(1, 1).text = "J1", "40 Nm"
    p.save(path)
    return Path(path)


def _tmp():
    return Path(tempfile.mkdtemp())


class CadaTrozoDiceDondeEsta(unittest.TestCase):
    def test_pdf_por_pagina(self):
        chunks = read_files.read(_pdf(_tmp() / "ficha.pdf", ["Par 1.2 Nm", "Masa 0.8 kg"]))
        self.assertEqual([(c.where, c.text) for c in chunks],
                         [("página 1", "Par 1.2 Nm"), ("página 2", "Masa 0.8 kg")])

    def test_word_parrafos_y_tablas_en_orden(self):
        chunks = read_files.read(_docx(_tmp() / "motor.docx"))
        self.assertEqual([c.where for c in chunks], ["párrafos 1-2", "tabla 1", "párrafo 3"])
        self.assertEqual(chunks[0].text, "# Motor M3\nPar nominal 1.2 Nm")
        self.assertEqual(chunks[1].table, (("Velocidad", "3000 rpm"), ("Masa", "0.8 kg")))

    def test_excel_con_su_rango_y_la_fila_y_columna_de_cada_celda(self):
        chunks = read_files.read(_xlsx(_tmp() / "bom.xlsx"))
        self.assertEqual(len(chunks), 1)           # la hoja vacía no da trozo
        c = chunks[0]
        self.assertEqual(c.where, "'Lista de piezas'!B3:C5")
        self.assertEqual(c.table, (("", "B", "C"), ("3", "Pieza", "Masa"),
                                   ("4", "Brida", "0.25"),
                                   # sin valor calculado (no lo guardó Excel): la fórmula, nunca vacío
                                   ("5", "", "=SUM(C4:C4)")))

    def test_excel_grande_se_parte_por_filas_sin_perder_el_rango(self):
        import openpyxl
        wb = openpyxl.Workbook()
        for r in range(1, 6):
            wb.active.cell(r, 1, r)
        path = _tmp() / "largo.xlsx"
        wb.save(path)
        old = read_files.SHEET_CELLS
        read_files.SHEET_CELLS = 2
        try:
            chunks = read_files.read(path)
        finally:
            read_files.SHEET_CELLS = old
        self.assertEqual([c.where for c in chunks], ["Sheet!A1:A2", "Sheet!A3:A4", "Sheet!A5:A5"])

    def test_powerpoint_por_diapositiva_con_notas_y_tablas(self):
        chunks = read_files.read(_pptx(_tmp() / "revision.pptx"))
        self.assertEqual([c.where for c in chunks], ["diapositiva 1", "diapositiva 2, tabla 1"])
        self.assertEqual(chunks[0].text, "Resumen\nNotas: Recordar el par")
        self.assertEqual(chunks[1].table, (("Eje", "Par"), ("J1", "40 Nm")))

    def test_texto_por_lineas(self):
        p = _tmp() / "notas.txt"
        p.write_text("uno\ndos\n", encoding="utf-8")
        self.assertEqual([(c.where, c.text) for c in read_files.read(p)],
                         [("líneas 1-2", "uno\ndos")])


class NuncaTextoVacio(unittest.TestCase):
    def test_un_formato_que_no_conoce_da_error(self):
        p = _tmp() / "pieza.step"
        p.write_text("ISO-10303-21;", encoding="ascii")
        with self.assertRaisesRegex(read_files.ReadError, r"no se leen archivos \.step"):
            read_files.read(p)

    def test_el_office_antiguo_dice_como_guardarlo(self):
        p = _tmp() / "viejo.xls"
        p.write_bytes(b"\xd0\xcf\x11\xe0")
        with self.assertRaisesRegex(read_files.ReadError, r"guárdalo como \.xlsx"):
            read_files.read(p)

    def test_un_archivo_roto_da_error_con_su_nombre(self):
        p = _tmp() / "roto.docx"
        p.write_bytes(b"no soy un zip")
        with self.assertRaisesRegex(read_files.ReadError, "no se pudo leer roto.docx"):
            read_files.read(p)

    def test_un_pdf_sin_texto_da_error(self):
        p = _pdf(_tmp() / "escaneado.pdf", [""])
        with self.assertRaisesRegex(read_files.ReadError, "no tiene texto"):
            read_files.read(p)

    def test_un_binario_con_extension_de_texto_da_error(self):
        p = _tmp() / "raro.txt"
        p.write_bytes(b"\x00\x01\x02")
        with self.assertRaisesRegex(read_files.ReadError, "no es texto"):
            read_files.read(p)


def _key(path):
    st = path.stat()
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


class PorTramos(unittest.TestCase):
    def setUp(self):
        self.pdf = _pdf(_tmp() / "catalogo.pdf", [f"Pagina {i} " + "x" * 80 for i in range(1, 6)])

    def test_lo_que_no_cabe_sigue_con_next_y_nunca_se_pierde_una_pagina(self):
        seen, start = [], 0
        while start is not None:
            part, start, count = read_files.read_part(self.pdf, start, limit=250)
            self.assertTrue(part)
            seen += [c.where for c in part]
        self.assertEqual((seen, count), ([f"página {i}" for i in range(1, 6)], 5))

    def test_una_pagina_mayor_que_el_limite_sale_entera(self):
        part, nxt, _ = read_files.read_part(self.pdf, 0, limit=10)
        self.assertEqual(([c.where for c in part], nxt), (["página 1"], 1))

    def test_pages_lee_solo_esas_paginas(self):
        part, nxt, _ = read_files.read_part(self.pdf, pages="4-9")
        self.assertEqual(([c.where for c in part], nxt), (["página 4", "página 5"], None))
        self.assertEqual(sorted(read_files._CACHE[_key(self.pdf)].units), [3, 4])

    def test_pages_fuera_del_pdf_o_en_otro_formato_da_error(self):
        with self.assertRaisesRegex(read_files.ReadError, "tiene 5 páginas"):
            read_files.read_part(self.pdf, pages="8")
        with self.assertRaisesRegex(read_files.ReadError, "como '7' o '45-50'"):
            read_files.read_part(self.pdf, pages="la tabla")
        with self.assertRaisesRegex(read_files.ReadError, "solo vale en un PDF"):
            read_files.read_part(_docx(_tmp() / "m.docx"), pages="1")

    def test_seguir_no_relee_y_un_archivo_cambiado_se_lee_de_nuevo(self):
        read_files.read(self.pdf)
        read_files._CACHE[_key(self.pdf)].units[0] = [read_files.Chunk("página 1", "de la caché")]
        self.assertEqual(read_files.read(self.pdf)[0].text, "de la caché")
        _pdf(self.pdf, ["Otra cosa distinta"])
        self.assertEqual([c.text for c in read_files.read(self.pdf)], ["Otra cosa distinta"])


class TablasDeVerdad(unittest.TestCase):
    def test_un_recuadro_de_maquetacion_no_es_una_tabla(self):
        self.assertTrue(read_files._real_table((("Tamaño", "Par"), ("14", "7.8"))))
        self.assertFalse(read_files._real_table((("párrafo " * 60, ""), ("", ""))))
        self.assertFalse(read_files._real_table((("", "", ""), ("", "", ""))))
        self.assertFalse(read_files._real_table((("Tamaño", "Par"),)))


def _call(board, **args):
    r = agent.tool_leer_archivo(board, args)
    return r.get("is_error", False), r["content"][0]["text"]


class LaHerramientaSoloLeeLaPizarra(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        d = _tmp()
        self.pdf = _pdf(d / "ficha.pdf", ["Par 1.2 Nm"])
        self.folder = d / "datasheets"
        (self.folder / "viejos").mkdir(parents=True)
        _docx(self.folder / "motor.docx")
        _pdf(self.folder / "viejos" / "antiguo.pdf", ["Descatalogado"])
        (self.folder / "foto.png").write_bytes(b"\x89PNG")
        self.card, self.fold = (e["id"] for e in self.b.add_cards([self.pdf, self.folder]))

    def test_lee_una_tarjeta_y_dice_como_citarla(self):
        err, text = _call(self.b, card=self.card)
        self.assertFalse(err)
        data = json.loads(text)
        self.assertEqual(data["chunks"], [{"where": "página 1", "text": "Par 1.2 Nm"}])
        self.assertEqual(data["cite_as"]["ref"], f"archivo:{self.card}")
        self.assertEqual(data["pages"], 1)
        self.assertNotIn("next", data)

    def test_pages_llega_hasta_el_lector(self):
        err, text = _call(self.b, card=self.card, pages="3")
        self.assertTrue(err)
        self.assertIn("tiene 1 página: no hay página 3", text)

    def test_leer_pizarra_lista_las_tarjetas(self):
        data = json.loads(agent.tool_leer_pizarra(self.b, {})["content"][0]["text"])
        self.assertEqual({(f["id"], f["kind"], f["type"]) for f in data["files"]},
                         {(self.card, "archivo", "archivo.pdf"),
                          (self.fold, "carpeta", "carpeta")})

    def test_una_ruta_que_no_es_una_tarjeta_nunca_se_lee(self):
        err, text = _call(self.b, card=str(self.pdf))
        self.assertTrue(err)
        self.assertIn("no hay ninguna tarjeta", text)

    def test_en_una_carpeta_lista_lo_marcado_y_lee_uno(self):
        err, text = _call(self.b, card=self.fold)
        self.assertFalse(err)
        files = {f["file"]: f["readable"] for f in json.loads(text)["files"]}
        self.assertEqual(files, {"foto.png": False, "motor.docx": True,
                                 "viejos/antiguo.pdf": True})
        err, text = _call(self.b, card=self.fold, file="viejos\\antiguo.pdf")
        self.assertFalse(err)
        self.assertEqual(json.loads(text)["chunks"][0]["text"], "Descatalogado")

    def test_lo_desmarcado_de_una_carpeta_nunca_se_lee(self):
        el = self.b.card(self.fold)
        el["customData"]["content"] = {"exclude": ["viejos"], "patterns": []}
        err, text = _call(self.b, card=self.fold, file="viejos/antiguo.pdf")
        self.assertTrue(err)
        self.assertIn("no es de lo marcado", text)
        self.assertNotIn("viejos/antiguo.pdf", text.split("no es de")[1])

    def test_salir_de_la_carpeta_con_dos_puntos_nunca_se_lee(self):
        err, text = _call(self.b, card=self.fold, file="../ficha.pdf")
        self.assertTrue(err)
        self.assertIn("no es de lo marcado", text)

    def test_un_archivo_que_ya_no_esta_da_error(self):
        self.pdf.unlink()
        err, text = _call(self.b, card=self.card)
        self.assertTrue(err)
        self.assertIn("no encontrado", text)


class CitarUnArchivo(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.card = self.b.add_cards([_pdf(_tmp() / "ficha.pdf", ["Par 1.2 Nm"])])[0]["id"]

    def _postit(self, **src):
        return agent.tool_crear_postit(self.b, {"text": "El par nominal es 1.2 Nm", "kind": "nota",
                                                "sources": [{"kind": "archivo", **src}]})

    def test_con_la_tarjeta_y_la_pagina_se_crea(self):
        result, new = self._postit(ref=f"archivo:{self.card}", where="página 1")
        self.assertNotIn("is_error", result)
        self.assertEqual(new[0]["customData"]["sources"][0]["where"], "página 1")

    def test_sin_el_sitio_se_rechaza(self):
        result, new = self._postit(ref=f"archivo:{self.card}")
        self.assertTrue(result["is_error"])
        self.assertIn("where", result["content"][0]["text"])
        self.assertEqual(new, [])

    def test_una_tarjeta_que_no_existe_se_rechaza(self):
        result, new = self._postit(ref="archivo:nadie", where="página 1")
        self.assertTrue(result["is_error"])
        self.assertIn("ninguna tarjeta", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
