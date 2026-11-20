"""Escribir las salidas de un bloque en una copia del Excel (docs/PLAN_EXCEL.md §3.3, X6, X8,
R4).

Reglas:
- **El original nunca se escribe**: sale igual byte a byte, también si la escritura falla.
- La copia es `<nombre>_n.xlsx` junto al original, y deja una propuesta de archivo (R47) con
  el diff: las celdas escritas y las fórmulas con nombre que cambian por ellas (recalculadas).
- Rechazar manda a la papelera solo la copia. Aceptar pasa la tarjeta a la copia: el mismo id,
  así que sus conexiones, los enlaces de los parámetros y lo que se escribe la siguen.
- La flecha de un bloque a un Excel es de escritura: no crea un ciclo (el bloque puede leer
  del mismo Excel) ni entra en el orden de ejecución (X8). A otro archivo, se niega como antes.
- La unidad del campo se convierte al sufijo del nombre (X4); si no casa, se niega con su
  motivo. Solo se escribe en un nombre admitido que no es una fórmula (R4).
- Sin resultado, o con el bloque desactualizado, no se escribe: el botón dice por qué.

Ejecutar desde app/backend:  python -m unittest tests.test_excel_write -v
"""
import hashlib
import tempfile
import unittest
from pathlib import Path

import openpyxl

from pizarra import excel_calc, excel_names, excel_write, graph, office_write, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace
from pizarra.validation import ValidationError
from tests.test_excel_links import REG, excel


def tmp():
    return Path(tempfile.mkdtemp())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# Lee L_m (B3) y escribe el resultado del bloque en res_m (B10); doble_m (B11) es una fórmula
# que depende de lo escrito, y masa_kg, de otra magnitud.
NAMES = {"L_m": "Datos!$B$3", "res_m": "Datos!$B$10", "doble_m": "Datos!$B$11",
         "masa_kg": "Datos!$B$4", "nota": "Datos!$B$12", "rango_m": "Datos!$B$3:$B$4"}
CELLS = {"B3": 0.3, "B4": 2.5, "B10": 0.1, "B11": "=B10*2", "B12": "texto"}


def doble(path, cells):
    """Recalculador de mentira: B11 = 2·B10 del libro que le dan (el original o la copia)."""
    wb = openpyxl.load_workbook(path, data_only=False)
    v = wb["Datos"]["B10"].value
    return {"values": {c: (v * 2 if c == "Datos!B11" else None) for c in cells}, "errors": {}}


class Base(unittest.TestCase):
    calc_run = staticmethod(doble)

    def setUp(self):
        self.trashed = []
        ws = LocalWorkspace.open(tmp() / "Personal", trash=self._trash)
        self.b = Board(ws, ws.create_project("", "X").id, registry=REG, connectors=frozenset())
        self.b.calc = excel_calc.Calculator(tmp(), run=self.calc_run) if self.calc_run else None
        block = scene.block_element("xl.viga", 0, 0)
        self.b.apply_client_elements([block])
        self.bid = block["id"]
        self.dir = tmp()
        self.path = excel(self.dir / "datos.xlsx", CELLS, NAMES)
        (card,) = self.b.add_cards([self.path], 400, 0)
        self.cid = card["id"]
        self.probe()
        self.original = sha(self.path)

    def _trash(self, p):
        self.trashed.append(Path(p))
        Path(p).unlink()

    def probe(self):
        self.b.probe()
        if self.b.calc is not None:
            self.b.calc.join()
            self.b.probe()

    def arrow(self, src=None, dst=None):
        """La flecha de escritura del bloque a la tarjeta (como `connect` de la interfaz)."""
        return self.b.connect(src or self.bid, None, dst or self.cid, None)[0]

    def ready(self):
        """Bloque enlazado a L_m, ejecutado, con flecha y res_m ← x · L."""
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.run(self.bid)
        self.arrow()
        excel_write.set_write(self.b, self.cid, "res_m", self.bid, "x", "L")

    def write(self):
        p, finish = excel_write.write_copy(self.b, self.cid)
        if finish is not None:
            excel_write.apply_calc(self.b, p["id"], finish())
        return next(q for q in self.b.proposals if q["id"] == p["id"])

    def view(self):
        return self.b.sources_view()[self.cid]["write"]


class ElOriginal(Base):
    def test_el_original_nunca_se_escribe(self):
        self.ready()
        self.write()
        self.assertEqual(sha(self.path), self.original, "el original sale igual byte a byte")

    def test_ni_si_la_escritura_falla(self):
        self.ready()
        wb = openpyxl.load_workbook(self.path)      # la hoja de res_m ya no está
        wb["Datos"].title = "Otra"
        wb.save(self.path)
        self.probe()
        original = sha(self.path)
        with self.assertRaises(ValidationError):
            excel_write.write_copy(self.b, self.cid)
        self.assertEqual(sha(self.path), original)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["datos.xlsx"])


class LaCopia(Base):
    def test_la_copia_es_n_junto_al_original(self):
        self.ready()
        p = self.write()
        nuevo = Path(p["change"]["file"]["nuevo"])
        self.assertEqual(nuevo.name, "datos_1.xlsx")
        self.assertTrue((self.dir / "datos_1.xlsx").is_file())
        self.assertEqual(p["target"], self.cid)
        self.assertEqual(p["state"], "pendiente")

    def test_el_diff_lleva_las_celdas_escritas_convertidas(self):
        self.ready()                                # L = 300 mm → res_m = 0,3 m
        diff = self.write()["change"]["file"]["diff"]
        cell = next(d for d in diff if d["where"] == "Datos!B10")
        self.assertEqual((cell["before"], cell["after"], cell["name"]), ("0.1", "0.3", "res_m"))
        self.assertIn("L", cell["source"])
        self.assertEqual(openpyxl.load_workbook(self.dir / "datos_1.xlsx")["Datos"]["B10"].value, 0.3)

    def test_y_las_formulas_con_nombre_que_cambian_recalculadas(self):
        self.ready()
        p = self.write()
        f = next(d for d in p["change"]["file"]["diff"] if d["where"] == "Datos!B11")
        self.assertEqual((f["name"], f["before"], f["after"], f["formula"]), ("doble_m", "0.2", "0.6", True))
        self.assertEqual(p["change"]["file"]["calc"]["state"], "hecho")
        self.assertNotIn("L_m", {d.get("name") for d in p["change"]["file"]["diff"]},
                         "lo que no cambia no sale")

    def test_mientras_calcula_la_propuesta_lo_dice_y_no_espera(self):
        import threading
        gate = threading.Event()
        self.b.calc = excel_calc.Calculator(tmp(), run=lambda path, cells: (gate.wait(10), doble(path, cells))[1])
        self.ready()
        p, finish = excel_write.write_copy(self.b, self.cid)
        self.assertEqual(p["change"]["file"]["calc"]["state"], "calculando")
        self.assertEqual([d["where"] for d in p["change"]["file"]["diff"]], ["Datos!B10"])
        gate.set()
        excel_write.apply_calc(self.b, p["id"], finish())
        p = next(q for q in self.b.proposals if q["id"] == p["id"])
        self.assertEqual(p["change"]["file"]["calc"]["state"], "hecho")
        self.assertIn("Datos!B11", [d["where"] for d in p["change"]["file"]["diff"]])

    def test_sin_recalculo_las_formulas_quedan_sin_valor_con_aviso(self):
        self.b.calc = excel_calc.Calculator(tmp())              # sin entorno
        self.ready()
        p = self.write()
        calc = p["change"]["file"]["calc"]
        self.assertEqual(calc["state"], "sin_valor")
        self.assertEqual(calc["names"], ["doble_m"])
        self.assertIn("Excel", calc["motivo"])
        self.assertTrue(p["change"]["file"]["aviso"], "avisa de lo que openpyxl puede perder")

    def test_una_copia_que_saldria_igual_no_se_escribe(self):
        excel(self.path, {**CELLS, "B10": 0.3}, NAMES, bump=1_700_000_000_000_000_000)
        self.probe()
        self.ready()
        with self.assertRaises(ValidationError):
            excel_write.write_copy(self.b, self.cid)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["datos.xlsx"])


class AceptarYRechazar(Base):
    def test_rechazar_borra_solo_la_copia(self):
        self.ready()
        p = self.write()
        self.b.reject_proposal(p["id"])
        self.assertEqual(self.trashed, [(self.dir / "datos_1.xlsx").resolve()])
        self.assertEqual(sha(self.path), self.original)
        self.assertEqual(self.b.card_path(self.b.card(self.cid)), self.path)

    def test_aceptar_pasa_la_tarjeta_a_la_copia_con_sus_conexiones_y_enlaces(self):
        self.ready()
        p = self.write()
        self.b.accept_proposal(p["id"], self.b.proposals_view()[0]["current"])
        self.probe()
        card = self.b.card(self.cid)
        self.assertEqual(self.b.card_path(card).name, "datos_1.xlsx")
        self.assertEqual(card["customData"]["writes"]["res_m"]["block"], self.bid)
        self.assertEqual(self.b.state[self.bid]["links"]["L"]["card"], self.cid)
        self.assertEqual(excel_write.writers(self.b, self.cid), [self.bid], "la flecha sigue")
        names = {n["nombre"]: n for n in self.b.sources_view()[self.cid]["names"]}
        self.assertEqual(names["res_m"]["valor"], 0.3)
        self.assertEqual(names["doble_m"]["valor"], 0.6, "la fórmula de la copia, recalculada")
        # el Excel enlazado es otro archivo: el bloque queda desactualizado (cada vuelta, a mano)
        self.assertEqual(self.b.statuses()[self.bid], "desactualizado")
        self.assertEqual(sha(self.path), self.original)

    def test_con_una_copia_pendiente_no_se_escribe_otra(self):
        self.ready()
        self.write()
        self.assertFalse(self.view()["ready"])
        self.assertTrue(self.view()["reason"])
        with self.assertRaises(ValidationError):
            excel_write.write_copy(self.b, self.cid)


class LaFlecha(Base):
    """X8: la flecha de escritura no es una dependencia."""

    def test_leer_y_escribir_el_mismo_excel_no_es_un_ciclo(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        a = self.arrow()
        edges, copies, problems = graph.connections(self.b.elements, self.b.registry)
        self.assertEqual(problems, [])
        self.assertNotIn(self.cid, edges, "no es una entrada de la tarjeta")
        self.assertEqual(copies, {}, "ni una copia de archivos a una carpeta")
        self.assertEqual(graph.writes_in(self.b.elements, self.b.registry),
                         {self.cid: [(self.bid, None, a["id"])]})

    def test_no_entra_en_el_orden_de_ejecucion(self):
        other = scene.block_element("xl.viga", 0, 300)
        self.b.apply_client_elements([other])
        self.arrow()
        self.arrow(src=other["id"])
        edges, _ = graph.build(self.b.elements, self.b.registry)
        self.assertEqual(graph.topo_upstream(edges, self.bid), [self.bid])
        self.assertEqual(graph.topo_upstream(edges, other["id"]), [other["id"]])
        self.b.run(self.bid)
        self.assertEqual(self.b.statuses()[self.bid], "al_dia", "escribir no desactualiza")

    def test_a_un_archivo_que_no_es_un_excel_se_niega(self):
        txt = self.dir / "notas.txt"
        txt.write_text("x", encoding="utf-8")
        (card,) = self.b.add_cards([txt], 800, 0)
        with self.assertRaises(ValidationError):
            self.b.connect(self.bid, None, card["id"], None)

    def test_dos_flechas_del_mismo_bloque_al_mismo_excel_se_niegan(self):
        self.arrow()
        with self.assertRaises(ValidationError):
            self.arrow()


class LoQueSeElige(Base):
    def setUp(self):
        super().setUp()
        self.b.run(self.bid)
        self.arrow()

    def refused(self, *args):
        with self.assertRaises(ValidationError) as cm:
            excel_write.set_write(self.b, self.cid, *args)
        return str(cm.exception)

    def test_la_unidad_que_no_casa_se_niega_con_su_motivo(self):
        why = self.refused("masa_kg", self.bid, "x", "L")
        self.assertIn("kg", why)
        self.assertIn("mm", why)
        self.assertNotIn("writes", self.b.card(self.cid)["customData"])

    def test_un_nombre_sin_sufijo_no_recibe_un_campo_con_unidad(self):
        self.assertIn("mm", self.refused("nota", self.bid, "x", "L"))

    def test_nunca_encima_de_una_formula(self):
        self.assertIn("fórmula", self.refused("doble_m", self.bid, "x", "L"))

    def test_ni_en_lo_que_no_se_admite(self):
        self.refused("rango_m", self.bid, "x", "L")

    def test_solo_un_bloque_con_flecha_y_un_campo_que_tiene(self):
        other = scene.block_element("xl.viga", 0, 300)
        self.b.apply_client_elements([other])
        self.b.run(other["id"])
        self.refused("res_m", other["id"], "x", "L")
        self.refused("res_m", self.bid, "x", "no_esta")

    def test_un_campo_que_no_es_un_valor_no_se_escribe(self):
        # la prueba de punta a punta: la vista 2D de un Tubo salía en el menú (un objeto)
        self.b.state[self.bid]["outputs"]["x"]["vista"] = {"value": {"items": []}, "unit": "",
                                                             "control": "view2d"}
        self.assertIn("vista", self.refused("nota", self.bid, "x", "vista"))

    def test_se_guarda_en_la_tarjeta_y_se_quita(self):
        excel_write.set_write(self.b, self.cid, "res_m", self.bid, "x", "L")
        self.assertEqual(self.b.card(self.cid)["customData"]["writes"],
                         {"res_m": {"block": self.bid, "port": "x", "field": "L"}})
        row = self.view()["rows"]["res_m"]
        self.assertEqual((row["value"], row["unit"], row["reason"]), (0.3, "m", None))
        excel_write.set_write(self.b, self.cid, "res_m", None)
        self.assertNotIn("writes", self.b.card(self.cid)["customData"])


class ElBoton(Base):
    """Sin resultado, o con el bloque desactualizado, «Escribir copia» no deja y dice por qué."""

    def test_desactualizado_no_deja_escribir(self):
        self.ready()
        self.assertTrue(self.view()["ready"])
        self.b.unlink_param(self.bid, "L")
        self.b.set_params(self.bid, {"L": 400})
        v = self.view()
        self.assertFalse(v["ready"])
        self.assertIn("desactualizado", v["reason"])
        with self.assertRaises(ValidationError):
            excel_write.write_copy(self.b, self.cid)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["datos.xlsx"])

    def test_sin_resultado_no_deja_escribir(self):
        self.ready()
        self.b.state[self.bid].update(outputs=None, outputs_hash=None, last_hash=None)
        v = self.view()
        self.assertFalse(v["ready"])
        self.assertIn("resultado", v["rows"]["res_m"]["reason"])

    def test_sin_nada_elegido_tampoco(self):
        self.b.run(self.bid)
        self.arrow()
        v = self.view()
        self.assertEqual(v["writers"], [{"id": self.bid, "title": "Viga"}])
        self.assertFalse(v["ready"])
        self.assertTrue(v["reason"])

    def test_una_tarjeta_sin_flecha_ni_escrituras_no_enseña_nada(self):
        self.assertIsNone(self.view())


class Xlsm(unittest.TestCase):
    def test_un_xlsm_se_copia_como_xlsm(self):
        path = tmp() / "macro.xlsm"
        excel(path, {"B3": 1}, {"a_mm": "Datos!$B$3"})
        before = sha(path)
        dest, diff = office_write.edit_copy(path, [{"celda": "Datos!B3", "valor": 2}])
        self.assertEqual(dest.name, "macro_1.xlsm")
        self.assertEqual(diff, [{"where": "Datos!B3", "before": "1", "after": "2"}])
        self.assertEqual(sha(path), before)


class Unidades(unittest.TestCase):
    """Del campo al sufijo del nombre (la dirección contraria a la de un enlace)."""

    def test_convierte_del_campo_al_nombre(self):
        self.assertAlmostEqual(excel_names.convert_out(300, "mm", "m"), 0.3)
        self.assertAlmostEqual(excel_names.convert_out(2, "kN", "N"), 2000)
        self.assertEqual(excel_names.convert_out("acero", "", ""), "acero")

    def test_niega_lo_que_no_casa(self):
        for unit, sfx, code in (("mm", "kg", "otra_magnitud"), ("mm", "", "sin_sufijo"),
                                ("", "mm", "sin_unidad"), ("furlong", "mm", "unidad_desconocida")):
            with self.assertRaises(excel_names.UnitError) as cm:
                excel_names.convert_out(1, unit, sfx)
            self.assertEqual(cm.exception.code, code, (unit, sfx))
        with self.assertRaises(excel_names.UnitError) as cm:
            excel_names.convert_out("x", "mm", "m")
        self.assertEqual(cm.exception.code, "no_es_numero")


if __name__ == "__main__":
    unittest.main()
