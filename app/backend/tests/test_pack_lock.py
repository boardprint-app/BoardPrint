"""Lock de paquetes del proyecto y *paquete no instalado* (docs/PLAN_PAQUETES.md §3, §10
«Lock y huella», P13, P25).

Reglas:
- Un bloque ejecutado con la versión A de su paquete sale **desactualizado** con la B, y al
  volver a ejecutarlo queda al día con la B.
- Un paquete que falta **nunca borra** parámetros ni resultados: sus bloques salen *paquete no
  instalado* y, al volver el paquete, están como estaban.
- `board/packs.lock` dice con qué versión se hizo el proyecto, también de un paquete que
  ahora falta.

Ejecutar desde app/backend:  python -m unittest tests.test_pack_lock -v
"""
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from pizarra import packs, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace

BODY = '''
from boardprint_sdk.packs import Param

def run(p, i, c):
    return {"out": {"x": {"value": p["a"] * 2, "unit": "mm"}}}

def register(pack):
    pack.port("{id}.t", "t")
    pack.block("{id}.b", "B", run, params={"a": Param(1, "mm")}, outputs={"out": "{id}.t"})
'''


class Lock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.packs_dir = root / "packs"
        self.packs_dir.mkdir()
        self.ws = LocalWorkspace.open(root / "ws", trash=lambda p: None)
        self.pid = self.ws.create_project("", "P").id

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self, pack_id, version):
        d = self.packs_dir / pack_id
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        (d / "pack.toml").write_text(f'id = "{pack_id}"\nname = "{pack_id}"\nversion = "{version}"\n'
                                     'author = "Pruebas"\ndescription = "Paquete de prueba"\n'
                                     'sdk = ">=1.0,<2"\n', encoding="utf-8")
        (d / "blocks.py").write_text(textwrap.dedent(BODY.replace("{id}", pack_id)), encoding="utf-8")

    def board(self):
        reg = packs.load([self.packs_dir], log=lambda m: None)
        return Board(self.ws, self.pid, registry=reg, connectors=frozenset())

    def run_one(self, pack_id="p", a=5):
        b = self.board()
        el = scene.block_element(f"{pack_id}.b", 0, 0)
        b.apply_client_elements([el])
        b.set_params(el["id"], {"a": a})
        b.run(el["id"])
        b.save()
        return b, el["id"]

    def test_con_otra_version_sale_desactualizado_y_al_ejecutar_se_pone_al_dia(self):
        self.pack("p", "1.0.0")
        b, bid = self.run_one()
        self.assertEqual(b.statuses()[bid], "al_dia")
        self.assertEqual(b.state[bid]["pack_version"], "1.0.0")
        self.pack("p", "1.1.0")
        b2 = self.board()
        sts, reasons = b2.explain()
        self.assertEqual(sts[bid], "desactualizado")
        self.assertIn("p 1.0.0", reasons[bid])
        self.assertEqual(b2.packs_check()["changed"],
                         [{"id": "p", "locked": "1.0.0", "installed": "1.1.0"}])
        self.assertEqual(b2.state[bid]["outputs"]["out"]["x"]["value"], 10, "nada se pierde")
        b2.run(bid)
        self.assertEqual(b2.statuses()[bid], "al_dia")
        self.assertEqual(b2.packs_check()["changed"], [])
        self.assertEqual(self.ws.load_pack_lock(self.pid)["p"]["version"], "1.1.0")

    def test_lo_de_detras_de_un_bloque_de_otra_version_tambien_sale_desactualizado(self):
        self.pack("p", "1.0.0")
        self.pack("q", "1.0.0")
        (self.packs_dir / "q" / "blocks.py").write_text(textwrap.dedent('''
            def run(p, i, c):
                return {"out": i["i"]}
            def register(pack):
                pack.block("q.b", "Q", run, inputs={"i": "p.t"}, outputs={"out": "p.t"})
        '''), encoding="utf-8")
        b = self.board()
        a, c = scene.block_element("p.b", 0, 0), scene.block_element("q.b", 300, 0)
        arrow = {"id": "f", "type": "arrow", "version": 1, "isDeleted": False,
                 "startBinding": {"elementId": a["id"]}, "endBinding": {"elementId": c["id"]},
                 "customData": {"kind": "connection", "from": "out", "to": "i"}}
        b.apply_client_elements([a, c, arrow])
        b.run()
        b.save()
        self.assertEqual(b.statuses(), {a["id"]: "al_dia", c["id"]: "al_dia"})
        self.pack("p", "2.0.0")
        self.assertEqual(self.board().statuses(), {a["id"]: "desactualizado", c["id"]: "desactualizado"})

    def test_un_paquete_que_falta_no_borra_nada_y_al_volver_esta_como_estaba(self):
        self.pack("p", "1.0.0")
        b, bid = self.run_one(a=7)
        before = b.state[bid]
        shutil.rmtree(self.packs_dir / "p")
        sin = self.board()
        check = sin.packs_check()
        self.assertEqual(check["missing"], [{"id": "p", "version": "1.0.0", "blocks": [bid]}])
        self.assertNotIn(bid, sin.blocks_view()["blocks"], "no entra en el grafo (R6)")
        self.assertEqual(sin.blocks_view()["packs"], check)
        # se edita y se guarda el proyecto sin el paquete: el bloque y su estado siguen
        sin.apply_client_elements([scene.block_element("otro.b", 0, 400)])
        sin.save()
        self.assertEqual(self.ws.load_block_state(self.pid)[bid], before)
        self.assertIn(bid, [e["id"] for e in self.ws.load_scene(self.pid)])
        self.pack("p", "1.0.0")
        con = self.board()
        self.assertEqual(con.state[bid], before)
        self.assertEqual(con.statuses()[bid], "al_dia")
        self.assertEqual(con.packs_check()["missing"], [{"id": "otro", "version": "", "blocks":
                                                         [e["id"] for e in con.elements
                                                          if e["customData"].get("blockType") == "otro.b"]}])

    def test_el_lock_dice_version_y_huella_y_guarda_la_de_un_paquete_que_falta(self):
        self.pack("p", "1.0.0")
        self.pack("q", "0.3.0")
        b, _ = self.run_one("p")
        self.run_one("q")
        lock = self.ws.load_pack_lock(self.pid)
        self.assertEqual(lock, {"p": {"version": "1.0.0", "digest": packs.digest(self.packs_dir / "p")},
                                "q": {"version": "0.3.0", "digest": packs.digest(self.packs_dir / "q")}})
        shutil.rmtree(self.packs_dir / "p")
        self.pack("q", "0.4.0")
        b = self.board()
        qid = next(e["id"] for e in b.elements if e["customData"].get("blockType") == "q.b")
        b.run(qid)
        lock = self.ws.load_pack_lock(self.pid)
        self.assertEqual(lock["p"]["version"], "1.0.0", "falta, pero el proyecto se hizo con ella")
        self.assertEqual(lock["q"]["version"], "0.4.0")

    def test_un_bloque_de_antes_del_lock_se_da_por_la_version_de_ahora(self):
        # proyectos de antes de FF 10.1: ni lock ni pack_version; no se desactualizan solos
        self.pack("p", "1.0.0")
        b, bid = self.run_one()
        b.state[bid].pop("pack_version")
        b.save()
        (self.ws.root / "P" / "board" / "packs.lock").unlink()
        self.pack("p", "1.5.0")
        b2 = self.board()
        self.assertEqual(b2.statuses()[bid], "al_dia")
        self.assertEqual(b2.packs_check(), {"missing": [], "changed": []})


if __name__ == "__main__":
    unittest.main()
