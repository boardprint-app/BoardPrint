"""El registro de conectores del núcleo y los ids de antes de un bloque (docs/PLAN_PAQUETES.md
§6, §10 «Conector» y «Migración», P38, P59; plan D35, D106).

Reglas:
- El núcleo no sabe de ningún conector: los que hay, si están disponibles, su configuración y
  quién abre un archivo salen de lo que declaran los paquetes (`pack.connector`).
- Un `available()` que falla es un conector no disponible, nunca una app caída. La respuesta
  vale unos segundos (`TTL`), salvo que cambie el registro.
- Tras *Abrir*, el conector sale «arrancando» hasta que está disponible; si su programa ya
  estaba abierto, nunca.
- Un bloque guardado con un id que su paquete declara como de antes (`formerly=`) se abre con
  el de ahora; migrar dos veces da lo mismo. Un id de antes que es un tipo que existe, o que
  declaran dos bloques, tumba el paquete.

Ejecutar desde app/backend:  python -m unittest tests.test_connector_registry -v
"""
import tempfile
import unittest
from pathlib import Path

from pizarra import connectors, scene
from tests.test_pack_connector import load, write

PROG = '''
STATE = globals()["STATE"] = {"up": False, "launched": 0}

def up():
    return STATE["up"]

def launch():
    STATE["launched"] += 1
    return "arrancando"

pack.connector("Programa", available=up, launch=launch, open_file=lambda path: None,
               accepts=(".prg", ".prx"), config={"url": "http://127.0.0.1:1"})
pack.block("prog.b", "B", run, params={"a": Param(1)}, outputs={"out": "prog.t"},
           connector="prog", formerly=("viejo.b",))
'''
ROTO = '''
def up():
    raise OSError("el puerto no contesta")

pack.connector("Roto", available=up)
'''


class Registro(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        write(root, "prog", PROG)
        write(root, "roto", ROTO)
        self.reg, self.info = load(root)
        self.assertIsNone(self.info["prog"].error)
        self.state = __import__("sys").modules["pizarra_packs.prog.blocks"].STATE
        connectors._cache["at"] = -1e9
        connectors._launch.clear()
        self.addCleanup(lambda: connectors._cache.update(at=-1e9, registry=None))
        self.addCleanup(self.tmp.cleanup)

    def test_solo_estan_los_que_declaran_los_paquetes_y_uno_que_falla_no_esta_disponible(self):
        self.state["up"] = True
        self.assertEqual(connectors.available(self.reg, ttl=0), frozenset({"prog"}))
        self.assertEqual(set(connectors.status(self.reg)), {"prog", "roto"})
        self.assertFalse(connectors.status(self.reg)["roto"]["available"])

    def test_la_respuesta_vale_unos_segundos(self):
        self.state["up"] = True
        self.assertIn("prog", connectors.available(self.reg, ttl=0))
        self.state["up"] = False
        self.assertIn("prog", connectors.available(self.reg, ttl=60), "aún vale la de antes")
        self.assertNotIn("prog", connectors.available(self.reg, ttl=0))

    def test_tras_abrir_sale_arrancando_hasta_que_esta(self):
        self.assertEqual(connectors.launch("prog", self.reg), "arrancando")
        self.assertEqual(self.state["launched"], 1)
        self.assertTrue(connectors.status(self.reg)["prog"]["launching"])
        self.state["up"] = True
        connectors._cache["at"] = -1e9
        self.assertEqual(connectors.status(self.reg)["prog"],
                         {"name": "Programa", "available": True, "launching": False})

    def test_abrir_lo_que_no_se_puede(self):
        with self.assertRaises(KeyError):
            connectors.launch("no_existe", self.reg)
        with self.assertRaises(ValueError):
            connectors.launch("roto", self.reg)

    def test_la_configuracion_lleva_el_motor_y_los_paquetes(self):
        connectors.configure("C:/motor")
        self.addCleanup(connectors.configure, None)
        cfg = connectors.config(self.reg)["prog"]
        self.assertEqual((cfg["url"], cfg["engine_dir"]), ("http://127.0.0.1:1", "C:/motor"))
        self.assertEqual(cfg["packs"]["prog"], self.info["prog"].path)

    def test_abre_un_archivo_el_disponible_que_acepta_su_extension(self):
        self.assertIsNone(connectors.opener("a/plano.PRG", self.reg), "no disponible")
        self.state["up"] = True
        connectors._cache["at"] = -1e9
        self.assertEqual(connectors.opener("a/plano.PRG", self.reg).id, "prog")
        self.assertIsNone(connectors.opener("a/plano.pdf", self.reg))


class IdsDeAntes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_un_bloque_con_el_id_de_antes_pasa_al_de_ahora_y_dos_veces_da_lo_mismo(self):
        write(self.root, "prog", PROG)
        reg, _ = load(self.root)
        self.assertEqual(reg.renamed(), {"viejo.b": "prog.b"})
        old = scene.block_element("viejo.b", 0, 0)
        other = scene.block_element("prog.b", 400, 0)
        once, changed = scene.migrate_kinds([old, other], reg.renamed())
        self.assertTrue(changed)
        self.assertEqual([e["customData"]["blockType"] for e in once], ["prog.b", "prog.b"])
        self.assertEqual(once[0]["id"], old["id"])
        self.assertEqual(once[1], other)
        twice, changed = scene.migrate_kinds(once, reg.renamed())
        self.assertFalse(changed)
        self.assertEqual(twice, once)

    def test_un_id_de_antes_que_existe_o_que_declaran_dos_tumba_el_paquete(self):
        write(self.root, "a", 'pack.block("a.b", "B", run, params={"a": Param(1)}, '
                              'outputs={"out": "a.t"})\n'
                              'pack.block("a.c", "C", run, params={"a": Param(1)}, '
                              'outputs={"out": "a.t"}, formerly=("a.b",))')
        write(self.root, "d", 'pack.block("d.b", "B", run, params={"a": Param(1)}, '
                              'outputs={"out": "d.t"}, formerly=("x.y",))\n'
                              'pack.block("d.c", "C", run, params={"a": Param(1)}, '
                              'outputs={"out": "d.t"}, formerly=("x.y",))')
        _, info = load(self.root)
        self.assertIn("es un tipo de bloque que existe", info["a"].error)
        self.assertIn("lo declara también otro bloque", info["d"].error)


if __name__ == "__main__":
    unittest.main()
