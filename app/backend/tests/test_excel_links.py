"""Un parámetro de bloque enlazado a una celda con nombre de un Excel (docs/PLAN_EXCEL.md §3.2,
X2, X4, X5).

Reglas:
- Un parámetro enlazado toma el valor del Excel, convertido a su unidad, al sondear y antes de
  ejecutar, y lleva su fuente (`archivo:<tarjeta>`, `Hoja!B3`).
- Cambiar el Excel en el disco deja desactualizado el bloque.
- Un nombre borrado, una tarjeta que ya no está o una celda sin valor dejan el bloque
  `incompleto` con su motivo, y nunca entra un valor falso (0, el texto de la fórmula).
- Solo se enlaza a un `.xlsx`/`.xlsm` de la pizarra, a un nombre que existe y se admite, y con
  la unidad que casa (X4). Un parámetro enlazado no se cambia a mano.
- Quitar el enlace conserva el último valor.
- El paquete recibe un parámetro normal: nada cambia en el SDK.

El bloque de prueba es un paquete de verdad en una carpeta temporal, como en test_ejecucion.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import openpyxl
from openpyxl.workbook.defined_name import DefinedName

from pizarra import packs, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace
from pizarra.validation import ValidationError

PACK = '''
from boardprint_sdk.packs import Param

CALLS = []


def viga(p, i, ctx):
    CALLS.append(dict(p))
    return {"x": {"L": {"value": p["L"], "unit": "mm"}}}


def register(pack):
    pack.port("xl.num", "número")
    pack.block("xl.viga", "Viga", viga, outputs={"x": "xl.num"},
               params={"L": Param(300, "mm", "Largo"), "F": Param(200, "N", "Carga"),
                       "material": Param("acero", choices=("acero", "aluminio")),
                       "n": Param(1, "", "Piezas")})
'''


def tmp():
    return Path(tempfile.mkdtemp())


def make_pack():
    root = tmp()
    d = root / "xl"
    d.mkdir()
    (d / "pack.toml").write_text('id = "xl"\nname = "Excel"\nauthor = "Pruebas"\n'
                                 'description = "Paquete de prueba"\nversion = "0.1.0"\n'
                                 'sdk = ">=1.0,<2"\n', encoding="utf-8")
    (d / "blocks.py").write_text(textwrap.dedent(PACK), encoding="utf-8")
    reg = packs.load([root], log=lambda m: None)
    assert "xl.viga" in reg, reg.packs
    return reg, sys.modules["pizarra_packs.xl.blocks"].CALLS


REG, CALLS = make_pack()


def excel(path, cells, names, bump=None):
    """Escribe el libro `path` (hoja Datos) con `cells` = {celda: valor} y `names` = {nombre:
    referencia}. `bump`: una fecha distinta, para que el sondeo vea que cambió."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Datos"
    for coord, v in cells.items():
        ws[coord] = v
    for n, ref in names.items():
        wb.defined_names[n] = DefinedName(n, attr_text=ref)
    wb.save(path)
    if bump is not None:
        os.utime(path, ns=(bump, bump))
    return path


NAMES = {"L_m": "Datos!$B$3", "masa_kg": "Datos!$B$4", "F_kN": "Datos!$B$5",
         "piezas": "Datos!$B$6", "material": "Datos!$B$7", "rango_mm": "Datos!$B$3:$B$4",
         "doble_m": "Datos!$B$8", "sin_sufijo": "Datos!$B$3"}
CELLS = {"B3": 0.3, "B4": 2.5, "B5": 1.5, "B6": 4, "B7": "aluminio", "B8": "=B3*2",
         "C1": "otra cosa"}


class Base(unittest.TestCase):
    def setUp(self):
        CALLS.clear()
        ws = LocalWorkspace.open(tmp() / "Personal", trash=lambda p: None)
        self.b = Board(ws, ws.create_project("", "X").id, registry=REG, connectors=frozenset())
        block = scene.block_element("xl.viga", 0, 0)
        self.b.apply_client_elements([block])
        self.bid = block["id"]
        self.path = excel(tmp() / "datos.xlsx", CELLS, NAMES)
        (card,) = self.b.add_cards([self.path], 400, 0)
        self.cid = card["id"]
        self.b.probe()

    def params(self):
        return self.b.state[self.bid]["params"]

    def view(self):
        return self.b.blocks_view()["blocks"][self.bid]

    def rewrite(self, cells=None, names=None, n=1):
        excel(self.path, {**CELLS, **(cells or {})}, NAMES if names is None else names,
              bump=1_700_000_000_000_000_000 + n * 1_000_000_000)
        self.b.probe()


class TomaElValor(Base):
    def test_un_parametro_enlazado_toma_el_valor_convertido_al_sondear(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.probe()
        self.assertAlmostEqual(self.params()["L"], 300)
        self.b.link_param(self.bid, "F", self.cid, "F_kN")
        self.b.probe()
        self.assertAlmostEqual(self.params()["F"], 1500)

    def test_lleva_su_fuente_y_su_celda(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.probe()
        link = self.view()["links"]["L"]
        self.assertEqual(link["source"], {"kind": "archivo", "ref": f"archivo:{self.cid}",
                                          "where": "Datos!B3"})
        self.assertEqual((link["card"], link["name"], link["reason"]), (self.cid, "L_m", None))

    def test_sin_unidad_y_texto_a_sus_parametros(self):
        self.b.link_param(self.bid, "n", self.cid, "piezas")
        self.b.link_param(self.bid, "material", self.cid, "material")
        self.b.probe()
        self.assertEqual((self.params()["n"], self.params()["material"]), (4, "aluminio"))

    def test_antes_de_ejecutar_lee_el_excel_de_ahora(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.probe()
        excel(self.path, {**CELLS, "B3": 0.45}, NAMES, bump=1_700_000_000_000_000_000)
        self.b.run(self.bid)                  # sin sondear antes: lo hace la ejecución
        self.assertAlmostEqual(CALLS[-1]["L"], 450)


class Desactualiza(Base):
    def setUp(self):
        super().setUp()
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.run(self.bid)
        self.assertEqual(self.view()["status"], "al_dia")

    def test_cambiar_el_valor_en_el_excel_deja_el_bloque_desactualizado(self):
        self.rewrite({"B3": 0.4})
        self.assertAlmostEqual(self.params()["L"], 400)
        self.assertEqual(self.view()["status"], "desactualizado")

    def test_cambiar_otra_celda_del_excel_enlazado_tambien(self):
        self.rewrite({"C1": "cambiada"})
        self.assertAlmostEqual(self.params()["L"], 300)
        self.assertEqual(self.view()["status"], "desactualizado",
                         "la huella de la tarjeta entra en el hash de entradas")

    def test_quitar_el_enlace_conserva_el_ultimo_valor(self):
        self.rewrite({"B3": 0.4})
        self.b.unlink_param(self.bid, "L")
        self.assertAlmostEqual(self.params()["L"], 400)
        self.assertNotIn("L", self.view()["links"] or {})
        self.rewrite({"B3": 0.9}, n=2)
        self.assertAlmostEqual(self.params()["L"], 400, "sin enlace, el Excel ya no lo cambia")
        self.b.set_params(self.bid, {"L": 123})          # y se edita a mano otra vez
        self.assertEqual(self.params()["L"], 123)


class Incompleto(Base):
    def setUp(self):
        super().setUp()
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.probe()

    def assertIncomplete(self, *words, param="L"):
        v = self.view()
        self.assertEqual(v["status"], "incompleto")
        for w in words:
            self.assertIn(w, v["reason"])
        self.assertIsNotNone(v["links"][param]["reason"])

    def test_un_nombre_borrado_deja_el_bloque_incompleto_con_su_motivo(self):
        self.rewrite(names={k: v for k, v in NAMES.items() if k != "L_m"})
        self.assertIncomplete("L_m")
        self.assertAlmostEqual(self.params()["L"], 300, "se queda el último valor, sin inventar")
        with self.assertRaises(ValidationError) as cm:
            self.b.run(self.bid)
        self.assertIn("L_m", str(cm.exception))
        self.assertEqual(CALLS, [], "nunca se ejecuta")

    def test_una_tarjeta_quitada_deja_el_bloque_incompleto(self):
        card = self.b.card(self.cid)
        self.b.apply_client_elements([{**card, "version": card["version"] + 1, "isDeleted": True}])
        self.b.probe()
        self.assertIncomplete("L_m")

    def test_un_excel_que_no_esta_deja_el_bloque_incompleto(self):
        self.path.unlink()
        self.b.probe()
        self.assertIncomplete("no encontrado")

    def test_una_formula_sin_valor_nunca_da_0(self):
        self.b.link_param(self.bid, "F", self.cid, "F_kN")
        self.b.probe()
        self.rewrite({"B5": "=B4*2"})            # openpyxl no guarda el valor calculado
        self.assertIncomplete("F_kN", param="F")
        self.assertAlmostEqual(self.params()["F"], 1500, "el de antes, nunca 0 ni la fórmula")

    def test_un_texto_que_no_es_de_la_lista_deja_el_bloque_incompleto(self):
        self.b.link_param(self.bid, "material", self.cid, "material")
        self.rewrite({"B7": "titanio"})
        v = self.view()
        self.assertEqual(v["status"], "incompleto")
        self.assertIn("titanio", v["reason"])
        self.assertEqual(self.params()["material"], "aluminio")


class Validacion(Base):
    def assertRefused(self, *args):
        with self.assertRaises(ValidationError):
            self.b.link_param(self.bid, *args)
        self.assertNotIn(args[0], (self.b.state[self.bid].get("links") or {}))

    def test_solo_a_un_excel_de_la_pizarra(self):
        pdf = tmp() / "ficha.pdf"
        pdf.write_bytes(b"%PDF")
        (card,) = self.b.add_cards([pdf])
        self.b.probe()
        self.assertRefused("L", card["id"], "L_m")
        self.assertRefused("L", "no-existe", "L_m")

    def test_solo_a_un_nombre_que_existe_y_se_admite(self):
        self.assertRefused("L", self.cid, "no_existe_mm")
        self.assertRefused("L", self.cid, "rango_mm")

    def test_nunca_con_una_unidad_que_no_casa(self):
        self.assertRefused("L", self.cid, "masa_kg")
        self.assertRefused("L", self.cid, "sin_sufijo")
        self.assertRefused("n", self.cid, "L_m")

    def test_solo_un_parametro_del_bloque(self):
        self.assertRefused("no_es_param", self.cid, "L_m")
        with self.assertRaises(ValidationError):
            self.b.link_param("no-es-bloque", "L", self.cid, "L_m")

    def test_un_parametro_enlazado_no_se_cambia_a_mano(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.probe()
        with self.assertRaises(ValidationError):
            self.b.set_params(self.bid, {"L": 999})
        self.b.set_params(self.bid, {"L": self.params()["L"], "F": 10})   # lo mismo, sí
        self.assertEqual(self.params()["F"], 10)

    def test_la_tarjeta_lista_sus_nombres_con_su_motivo(self):
        names = {n["nombre"]: n for n in self.b.sources_view()[self.cid]["names"]}
        self.assertEqual(names["L_m"]["valor"], 0.3)
        self.assertEqual(names["L_m"]["where"], "Datos!B3")
        self.assertEqual(names["rango_mm"]["problema"], "varias_celdas")
        self.assertTrue(names["rango_mm"]["motivo"])
        self.assertEqual(names["doble_m"]["problema"], "sin_valor")


class ElPaquete(Base):
    def test_el_paquete_recibe_un_parametro_normal(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.link_param(self.bid, "material", self.cid, "material")
        self.b.run(self.bid)
        (p,) = CALLS
        self.assertEqual(set(p), {"L", "F", "material", "n"}, "ni enlaces ni fuentes")
        self.assertIsInstance(p["L"], float)
        self.assertAlmostEqual(p["L"], 300)
        self.assertEqual(p["material"], "aluminio")


class ElAgente(Base):
    """El agente ve los enlaces en `leer_pizarra` (§2: «los ve porque están en el estado del
    bloque»). La prueba de punta a punta de FF 7.2 vio que `summary()` los llevaba, pero
    `leer_pizarra` se quedaba solo con `id`, `type`, `status` y `params`."""

    def read(self):
        import json
        from pizarra.agent import tool_leer_pizarra
        out = tool_leer_pizarra(self.b, {})
        text = out["content"][0]["text"] if isinstance(out, dict) else out
        return {b["id"]: b for b in json.loads(text)["blocks"]}

    def test_leer_pizarra_lleva_los_enlaces_con_su_celda(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.probe()
        link = self.read()[self.bid]["links"]["L"]
        self.assertEqual((link["card"], link["name"], link["where"], link["reason"]),
                         (self.cid, "L_m", "Datos!B3", None))

    def test_y_el_motivo_de_uno_sin_valor(self):
        self.b.link_param(self.bid, "L", self.cid, "L_m")
        self.b.probe()
        self.rewrite(names={k: v for k, v in NAMES.items() if k != "L_m"})
        self.assertIn("L_m", self.read()[self.bid]["links"]["L"]["reason"])


if __name__ == "__main__":
    unittest.main()
