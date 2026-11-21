"""La flecha de enlace de una tarjeta de Excel a un bloque (docs/PLAN_EXCEL.md §3.6, R5).

Reglas:
- La flecha es la vista de `links`: no hay dato aparte. Enlazar varias parejas nombre →
  parámetro de una vez (`set_pair`) es todo o nada: una que no vale (la unidad) no deja
  ninguna.
- Lo de la pareja que no se elige se desenlaza; lo enlazado a otra tarjeta no se toca.
- Borrar la flecha (`unlink_card`) quita todos los enlaces de esa pareja y cada parámetro
  conserva su último valor; los de otra tarjeta siguen.
- La flecha no entra en el orden de ejecución: la tarjeta no es una entrada del bloque.
- En inglés, el motivo de un enlace lleva la etiqueta del parámetro traducida con el catálogo
  del paquete (O15), nunca la del paquete en español.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from pizarra import excel_links, graph, i18n, packs, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace
from pizarra.validation import ValidationError
from tests.test_excel_links import CELLS, NAMES, excel

PACK = '''
from boardprint_sdk.packs import Param


def viga(p, i, ctx):
    return {"x": {"L": {"value": p["L"], "unit": "mm"}}}


def register(pack):
    pack.port("xa.num", "número")
    pack.block("xa.viga", "Viga", viga, outputs={"x": "xa.num"},
               params={"L": Param(300, "mm", "Largo"), "F": Param(200, "N", "Carga"),
                       "n": Param(1, "", "Piezas")})
'''


def tmp():
    return Path(tempfile.mkdtemp())


def make_pack():
    root = tmp()
    d = root / "xa"
    (d / "locales").mkdir(parents=True)
    (d / "pack.toml").write_text('id = "xa"\nname = "Flecha"\nauthor = "Pruebas"\n'
                                 'description = "Paquete de prueba"\nversion = "0.1.0"\n'
                                 'sdk = ">=1.0,<2"\n', encoding="utf-8")
    (d / "blocks.py").write_text(textwrap.dedent(PACK), encoding="utf-8")
    (d / "locales" / "en.toml").write_text('"Largo" = "Length"\n"Carga" = "Load"\n', encoding="utf-8")
    reg = packs.load([root], log=lambda m: None)
    assert "xa.viga" in reg, reg.packs
    return reg


REG = make_pack()


class Flecha(unittest.TestCase):
    def setUp(self):
        ws = LocalWorkspace.open(tmp() / "Personal", trash=lambda p: None)
        self.b = Board(ws, ws.create_project("", "X").id, registry=REG, connectors=frozenset())
        block = scene.block_element("xa.viga", 0, 0)
        self.b.apply_client_elements([block])
        self.bid = block["id"]
        self.path = excel(tmp() / "datos.xlsx", CELLS, NAMES)
        self.other = excel(tmp() / "otro.xlsx", CELLS, NAMES)
        card, other = self.b.add_cards([self.path, self.other], 400, 0)
        self.cid, self.oid = card["id"], other["id"]
        self.b.probe()

    def links(self):
        return self.b.state[self.bid].get("links") or {}

    def params(self):
        return self.b.state[self.bid]["params"]

    def test_enlaza_varias_parejas_de_una_vez_con_su_valor_convertido(self):
        view = excel_links.set_pair(self.b, self.bid, self.cid, {"L": "L_m", "F": "F_kN"})
        self.assertEqual(self.links(), {"L": {"card": self.cid, "name": "L_m"},
                                        "F": {"card": self.cid, "name": "F_kN"}})
        self.assertEqual((self.params()["L"], self.params()["F"]), (300, 1500))
        self.assertEqual(sorted(view), ["F", "L"])
        self.assertEqual(view["L"]["where"], "Datos!B3")

    def test_todo_o_nada_una_pareja_que_no_casa_no_deja_ninguna(self):
        with self.assertRaises(ValidationError) as cm:
            excel_links.set_pair(self.b, self.bid, self.cid, {"L": "L_m", "F": "masa_kg"})
        self.assertIn("masa_kg", str(cm.exception))
        self.assertEqual(self.links(), {}, "ni la pareja buena")
        self.assertEqual(self.params()["L"], 300)

    def test_lo_no_elegido_se_desenlaza_y_lo_de_otra_tarjeta_no_se_toca(self):
        excel_links.set_pair(self.b, self.bid, self.cid, {"L": "L_m", "F": "F_kN"})
        excel_links.link(self.b, self.bid, "n", self.oid, "piezas")
        excel_links.set_pair(self.b, self.bid, self.cid, {"L": "L_m"})
        self.assertEqual(self.links(), {"L": {"card": self.cid, "name": "L_m"},
                                        "n": {"card": self.oid, "name": "piezas"}})
        self.assertEqual(self.params()["F"], 1500, "F se queda con su último valor")

    def test_elegir_un_parametro_de_otra_tarjeta_lo_pasa_a_esta(self):
        excel_links.link(self.b, self.bid, "n", self.oid, "piezas")
        excel_links.set_pair(self.b, self.bid, self.cid, {"n": "piezas"})
        self.assertEqual(self.links(), {"n": {"card": self.cid, "name": "piezas"}})

    def test_borrar_la_flecha_quita_sus_enlaces_y_conserva_los_valores(self):
        excel_links.set_pair(self.b, self.bid, self.cid, {"L": "L_m", "F": "F_kN"})
        excel_links.link(self.b, self.bid, "n", self.oid, "piezas")
        excel_links.unlink_card(self.b, self.bid, self.cid)
        self.assertEqual(self.links(), {"n": {"card": self.oid, "name": "piezas"}})
        self.assertEqual((self.params()["L"], self.params()["F"], self.params()["n"]), (300, 1500, 4))
        excel_links.unlink_card(self.b, self.bid, self.oid)
        self.assertNotIn("links", self.b.state[self.bid], "sin enlaces, sin la clave")
        self.assertNotIn(self.bid, excel_links.view(self.b), "ni flecha")
        excel_links.unlink_card(self.b, self.bid, self.oid)      # otra vez: nada que quitar

    def test_un_bloque_que_no_existe_se_niega(self):
        with self.assertRaises(ValidationError):
            excel_links.unlink_card(self.b, "no-existe", self.cid)
        with self.assertRaises(ValidationError):
            excel_links.set_pair(self.b, self.bid, self.cid, {"no_existe": "L_m"})

    def test_la_flecha_no_entra_en_el_orden_de_ejecucion(self):
        excel_links.set_pair(self.b, self.bid, self.cid, {"L": "L_m"})
        edges, problems = graph.build(self.b.elements, self.b.registry)
        self.assertEqual((edges.get(self.bid, {}), problems), ({}, []))
        self.assertEqual(graph.writes_in(self.b.elements, self.b.registry), {})
        self.assertEqual(graph.topo_upstream(edges, self.bid), [self.bid])
        self.assertEqual(self.b.statuses()[self.bid], "nunca")


class MotivoEnIngles(unittest.TestCase):
    """El motivo de un enlace, con la etiqueta del paquete traducida (§3.6, O15)."""

    def setUp(self):
        Flecha.setUp(self)
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "es")

    def test_un_nombre_borrado_lleva_la_etiqueta_traducida(self):
        excel_links.link(self.b, self.bid, "L", self.cid, "L_m")
        names = {k: v for k, v in NAMES.items() if k != "L_m"}
        excel(self.path, CELLS, names, bump=1_800_000_000_000_000_000)
        self.b.probe()
        reason = excel_links.view(self.b)[self.bid]["L"]["reason"]
        self.assertTrue(reason.startswith("Length ← L_m: "), reason)
        self.assertNotIn("Largo", self.b.explain()[1][self.bid])

    def test_al_negar_el_enlace_tambien(self):
        with self.assertRaises(ValidationError) as cm:
            excel_links.link(self.b, self.bid, "F", self.cid, "masa_kg")
        self.assertTrue(str(cm.exception).startswith("Load ← masa_kg: "), str(cm.exception))

    def test_sin_traduccion_queda_la_del_paquete(self):
        with self.assertRaises(ValidationError) as cm:
            excel_links.link(self.b, self.bid, "n", self.cid, "L_m")
        self.assertTrue(str(cm.exception).startswith("Piezas ← L_m: "), str(cm.exception))


if __name__ == "__main__":
    unittest.main()
