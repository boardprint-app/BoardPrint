"""Los nombres definidos de un Excel como datos de la pizarra (docs/PLAN_EXCEL.md §3.1, X3, X5,
X9).

Reglas:
- Solo un nombre definido de **una celda** da valor, del libro o de una hoja. Un nombre de
  varias celdas, una constante (`=0,5`) o un `#REF!` nunca dan un valor: dan su motivo.
- El valor es el calculado que guarda el archivo. Una fórmula sin valor guardado nunca da 0
  ni el texto de la fórmula: pasa por el recálculo y, si tampoco lo hay, queda sin valor.
- `.xlsx` y `.xlsm`.

Los libros se escriben con openpyxl en carpetas temporales. openpyxl no guarda el valor de una
fórmula: el que guardaría Excel se pone a mano en el XML (`cached`).

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import openpyxl
from openpyxl.workbook.defined_name import DefinedName

from pizarra import excel_names


def tmp():
    d = Path(tempfile.mkdtemp())
    return d


def book(path, cells, names, local=None):
    """Un libro con `cells` = {hoja: {celda: valor}}, los nombres del libro `names` = {nombre:
    referencia} y los de una hoja `local` = {hoja: {nombre: referencia}}."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet, values in cells.items():
        ws = wb.create_sheet(sheet)
        for coord, v in values.items():
            ws[coord] = v
    for n, ref in names.items():
        wb.defined_names[n] = DefinedName(n, attr_text=ref)
    for sheet, more in (local or {}).items():
        for n, ref in more.items():
            wb[sheet].defined_names[n] = DefinedName(n, attr_text=ref)
    wb.save(path)
    return path


def cached(path, sheet_index, values):
    """Pone en el XML el valor calculado de las fórmulas (`{celda: valor}`), como lo guarda
    Excel: openpyxl deja `<v></v>`."""
    tmp_path = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp_path, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == f"xl/worksheets/sheet{sheet_index}.xml":
                text = data.decode()
                for coord, v in values.items():
                    kind = ' t="e"' if str(v).startswith("#") else ""     # un error de Excel
                    text = re.sub(rf'<c r="{coord}"([^>]*)>(<f>[^<]*</f>)<v></v>',
                                  rf'<c r="{coord}"{kind}\g<1>>\g<2><v>{v}</v>', text)
                data = text.encode()
            dst.writestr(item, data)
    shutil.move(tmp_path, path)
    return path


class LoQueNuncaDaUnValor(unittest.TestCase):
    """X3: lo que no es una celda se lista, con su motivo y sin valor."""

    def setUp(self):
        self.path = book(tmp() / "datos.xlsx",
                         {"Datos": {"B3": 0.3, "C1": 1, "C2": 2}},
                         {"L_m": "Datos!$B$3", "rango": "Datos!$C$1:$C$2", "cte": "0.5",
                          "roto": "#REF!", "roto_hoja": "Datos!#REF!",
                          "otra": "Nada!$A$1"})
        self.got = excel_names.names(self.path)

    def test_un_nombre_de_varias_celdas_da_su_motivo_y_no_un_valor(self):
        n = self.got["rango"]
        self.assertIsNone(n.valor)
        self.assertEqual(n.problema, "varias_celdas")

    def test_una_constante_da_su_motivo_y_no_un_valor(self):
        n = self.got["cte"]
        self.assertIsNone(n.valor, "nunca el 0,5 de la constante")
        self.assertEqual(n.problema, "constante")

    def test_una_referencia_rota_da_su_motivo_y_no_un_valor(self):
        for name in ("roto", "roto_hoja", "otra"):
            with self.subTest(name):
                self.assertIsNone(self.got[name].valor)
                self.assertEqual(self.got[name].problema, "ref_rota")

    def test_el_nombre_de_una_celda_da_su_valor_su_hoja_y_su_celda(self):
        n = self.got["L_m"]
        self.assertEqual((n.valor, n.hoja, n.celda, n.where, n.problema),
                         (0.3, "Datos", "B3", "Datos!B3", None))
        self.assertEqual(n.unidad, "m")
        self.assertIsNone(n.formula)


class Formulas(unittest.TestCase):
    """X5: el valor calculado que guarda el archivo; sin él, nunca 0 ni la fórmula."""

    def setUp(self):
        self.path = book(tmp() / "calc.xlsx", {"Datos": {"B3": 0.3, "B4": "=B3*2", "B5": "=B3+1"}},
                         {"doble_m": "Datos!$B$4", "mas_m": "Datos!$B$5"})

    def test_una_formula_sin_valor_guardado_queda_sin_valor_nunca_0_ni_su_texto(self):
        n = excel_names.names(self.path)["doble_m"]
        self.assertIsNone(n.valor)
        self.assertEqual(n.problema, "sin_valor")
        self.assertEqual(n.formula, "=B3*2", "se sabe que es una fórmula")

    def test_una_formula_con_valor_guardado_da_ese_valor(self):
        cached(self.path, 1, {"B4": 0.6})
        n = excel_names.names(self.path)["doble_m"]
        self.assertEqual((n.valor, n.problema, n.formula), (0.6, None, "=B3*2"))

    def test_sin_valor_guardado_pide_el_recalculo_solo_de_lo_que_falta(self):
        cached(self.path, 1, {"B4": 0.6})
        asked = []

        def recalc(path, cells):
            asked.append(sorted(cells))
            return {"Datos!B5": 1.3}

        got = excel_names.names(self.path, recalc=recalc)
        self.assertEqual(asked, [["Datos!B5"]], "B4 ya tiene su valor guardado")
        self.assertEqual((got["mas_m"].valor, got["mas_m"].problema), (1.3, None))
        self.assertEqual(got["doble_m"].valor, 0.6, "nunca se sustituye un valor guardado")

    def test_un_recalculo_que_no_da_la_celda_o_falla_deja_sin_valor(self):
        for recalc in (lambda p, c: {}, lambda p, c: 1 / 0):
            with self.subTest(recalc):
                n = excel_names.names(self.path, recalc=recalc)["mas_m"]
                self.assertEqual((n.valor, n.problema), (None, "sin_valor"))

    def test_un_error_de_excel_guardado_no_es_un_valor(self):
        cached(self.path, 1, {"B4": "#DIV/0!"})
        n = excel_names.names(self.path)["doble_m"]
        self.assertEqual((n.valor, n.problema), (None, "error_celda"))


class Alcance(unittest.TestCase):
    def test_los_nombres_de_una_hoja_van_con_su_hoja_y_no_pisan_los_del_libro(self):
        path = book(tmp() / "h.xlsx", {"Datos": {"B3": 1, "B4": 2}, "Otra hoja": {"A1": 5}},
                    {"L_mm": "Datos!$B$3", "esp": "'Otra hoja'!$A$1"},
                    local={"Datos": {"L_mm": "Datos!$B$4"}})
        got = excel_names.names(path)
        self.assertEqual(got["L_mm"].valor, 1)
        self.assertEqual(got["Datos!L_mm"].valor, 2)
        self.assertEqual(got["Datos!L_mm"].unidad, "mm")
        self.assertEqual((got["esp"].hoja, got["esp"].where), ("Otra hoja", "'Otra hoja'!A1"))

    def test_una_celda_vacia_no_es_un_valor(self):
        path = book(tmp() / "v.xlsx", {"Datos": {"A1": 1}}, {"nada": "Datos!$C$9"})
        n = excel_names.names(path)["nada"]
        self.assertEqual((n.valor, n.problema), (None, "vacia"))

    def test_los_nombres_internos_de_excel_no_se_listan(self):
        path = book(tmp() / "i.xlsx", {"Datos": {"A1": 1}},
                    {"_xlnm._FilterDatabase": "Datos!$A$1", "x": "Datos!$A$1"})
        self.assertEqual(list(excel_names.names(path)), ["x"])

    def test_un_xlsm_se_lee_igual(self):
        path = book(tmp() / "macro.xlsm", {"Datos": {"B3": 7}}, {"masa_kg": "Datos!$B$3"})
        self.assertEqual(excel_names.names(path)["masa_kg"].valor, 7)
        self.assertTrue(excel_names.is_excel(path))
        self.assertFalse(excel_names.is_excel(tmp() / "viejo.xls"), "openpyxl no abre .xls (X9)")

    def test_la_vista_es_json_y_lleva_el_motivo(self):
        path = book(tmp() / "j.xlsx", {"Datos": {"C1": 1, "C2": 2}}, {"rango": "Datos!$C$1:$C$2"})
        view = excel_names.names(path)["rango"].view()
        self.assertEqual(view["problema"], "varias_celdas")
        self.assertEqual(view["nombre"], "rango")


if __name__ == "__main__":
    unittest.main()
