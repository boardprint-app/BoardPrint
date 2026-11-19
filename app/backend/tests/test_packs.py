"""Paquetes de dominio (plan D94, §10 «Paquetes»).

Regla: un paquete roto, con un puerto de un tipo que nadie registra o con un tipo de bloque
que ya existe nunca se carga ni pisa al que ya estaba, y la app arranca igual con los demás.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import tempfile
import textwrap
import unittest
from pathlib import Path

from pizarra import packs
from tests.helpers import new_board, reopen, necesita_paquetes
from pizarra import scene

OK_BLOCK = '''
from boardprint_sdk.packs import Param

def run(p, i, c):
    return {{"out": {{"x": {{"value": p["a"], "unit": "mm"}}}}}}

def register(pack):
    pack.port("{id}.t", "t")
    pack.block("{id}.b", "B", run, params={{"a": Param(1, "mm")}}, outputs={{"out": "{id}.t"}})
'''


def write_pack(root, folder, body, pack_id=None, module="blocks"):
    d = Path(root) / folder
    d.mkdir(parents=True)
    (d / "pack.toml").write_text(
        f'id = "{pack_id or folder}"\nname = "{folder}"\nauthor = "Pruebas"\ndescription = "Paquete de prueba"\nversion = "1.0.0"\nsdk = ">=1.0,<2"\nmodule = "{module}"\n',
        encoding="utf-8")
    (d / f"{module}.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return d


def load(*dirs):
    logs = []
    reg = packs.load([str(d) for d in dirs], log=logs.append)
    return reg, {p.id: p for p in reg.packs}, logs


class PaqueteRoto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_pack(self.root, "bueno", OK_BLOCK.format(id="bueno"))

    def tearDown(self):
        self.tmp.cleanup()

    def assert_solo_carga_el_bueno(self, roto):
        reg, info, logs = load(self.root)
        self.assertIn("bueno.b", reg)
        self.assertIsNone(info["bueno"].error)
        self.assertIsNotNone(info[roto].error)
        self.assertFalse([k for k in reg if k.startswith(roto + ".")], "nada del paquete roto")
        self.assertFalse([t for t in reg.ports if t.startswith(roto + ".")], "ni sus puertos")
        self.assertTrue(logs, "el fallo queda en el registro")
        return info[roto].error

    def test_un_modulo_que_no_importa_no_impide_cargar_los_demas(self):
        write_pack(self.root, "roto", "def register(pack):\n    esto no es python\n")
        self.assert_solo_carga_el_bueno("roto")

    def test_register_que_lanza_no_deja_nada_a_medias(self):
        write_pack(self.root, "roto", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.port("roto.t", "t")
                pack.block("roto.b", "B", run, outputs={"o": "roto.t"})
                raise RuntimeError("a medias")
        ''')
        self.assert_solo_carga_el_bueno("roto")

    def test_sin_register_no_se_carga(self):
        write_pack(self.root, "roto", "X = 1\n")
        self.assert_solo_carga_el_bueno("roto")

    def test_un_puerto_de_un_tipo_que_nadie_registra_tumba_el_paquete(self):
        write_pack(self.root, "roto", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.port("roto.t", "t")
                pack.block("roto.b", "B", run, inputs={"i": "nadie.t"}, outputs={"o": "roto.t"})
        ''')
        err = self.assert_solo_carga_el_bueno("roto")
        self.assertIn("nadie.t", err)

    def test_un_tipo_de_bloque_sin_el_prefijo_del_paquete_no_se_carga(self):
        write_pack(self.root, "roto", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.block("bueno.b", "Impostor", run)
        ''')
        self.assert_solo_carga_el_bueno("roto")
        reg, _, _ = load(self.root)
        self.assertEqual(reg["bueno.b"].title, "B", "nunca pisa al que ya estaba")

    def test_un_tipo_de_bloque_repetido_en_el_paquete_no_se_carga(self):
        write_pack(self.root, "roto", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.block("roto.b", "B1", run)
                pack.block("roto.b", "B2", run)
        ''')
        self.assert_solo_carga_el_bueno("roto")

    def test_una_vista_previa_que_no_es_una_funcion_tumba_el_paquete(self):
        write_pack(self.root, "roto", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.block("roto.b", "B", run, preview="no")
        ''')
        self.assertIn("preview no es una función", self.assert_solo_carga_el_bueno("roto"))

    def test_el_mismo_paquete_en_otra_carpeta_no_pisa_al_primero(self):
        otra = self.root / "otra"
        write_pack(otra, "bueno", OK_BLOCK.format(id="bueno").replace('"B"', '"Copia"'))
        reg, _, _ = load(self.root, otra)
        self.assertEqual(reg["bueno.b"].title, "B")
        self.assertEqual(sum(p.id == "bueno" and p.error is None for p in reg.packs), 1)

    def test_el_id_de_pack_toml_tiene_que_ser_el_de_la_carpeta(self):
        write_pack(self.root, "roto", OK_BLOCK.format(id="otro"), pack_id="otro")
        self.assert_solo_carga_el_bueno("roto")

    def test_una_plantilla_que_une_tipos_distintos_tumba_el_paquete(self):
        write_pack(self.root, "roto", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.port("roto.a", "a")
                pack.port("roto.b", "b")
                pack.block("roto.x", "X", run, outputs={"o": "roto.a"})
                pack.block("roto.y", "Y", run, inputs={"i": "roto.b"})
                pack.template("roto.t", "T", [("x", "roto.x", 0, 0), ("y", "roto.y", 300, 0)],
                              [("x", "o", "y", "i")])
        ''')
        self.assert_solo_carga_el_bueno("roto")

    def test_una_plantilla_con_un_ciclo_tumba_el_paquete(self):
        write_pack(self.root, "roto", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.port("roto.a", "a")
                pack.block("roto.x", "X", run, inputs={"i": "roto.a"}, outputs={"o": "roto.a"})
                pack.template("roto.t", "T", [("p", "roto.x", 0, 0), ("q", "roto.x", 300, 0)],
                              [("p", "o", "q", "i"), ("q", "o", "p", "i")])
        ''')
        self.assert_solo_carga_el_bueno("roto")


class PlantillaDeOtroPaquete(unittest.TestCase):
    """docs/PLAN_TERMINALES.md T83: una plantilla que nombra bloques de un paquete que no está
    cargado no se ofrece y su paquete carga igual; un tipo que no existe en un paquete cargado
    sigue tumbando el paquete."""

    BODY = '''
        def run(p, i, c):
            return {}
        def register(pack):
            pack.port("con.a", "a")
            pack.block("con.x", "X", run, outputs={"o": "con.a"})
            pack.template("con.t", "T", [("x", "con.x", 0, 0), ("y", "%s", 300, 0)], [])
    '''

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_pack(self.root, "bueno", OK_BLOCK.format(id="bueno"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_sin_el_otro_paquete_no_se_ofrece_y_el_suyo_carga(self):
        write_pack(self.root, "con", self.BODY % "ausente.y")
        reg, info, logs = load(self.root)
        self.assertIsNone(info["con"].error)
        self.assertIn("con.x", reg)
        self.assertNotIn("con.t", reg.templates)
        self.assertTrue(any("con.t no se ofrece" in m and "ausente" in m for m in logs), logs)

    def test_con_el_otro_paquete_cargado_se_ofrece(self):
        write_pack(self.root, "con", self.BODY % "bueno.b")
        reg, info, _logs = load(self.root)
        self.assertIsNone(info["con"].error)
        self.assertIn("con.t", reg.templates)

    def test_un_tipo_que_no_existe_en_un_paquete_cargado_tumba_el_paquete(self):
        write_pack(self.root, "con", self.BODY % "bueno.no_existe")
        reg, info, _logs = load(self.root)
        self.assertIn("no existe", info["con"].error)
        self.assertNotIn("con.x", reg)

    def test_un_tipo_suyo_que_no_existe_tumba_el_paquete(self):
        write_pack(self.root, "con", self.BODY % "con.no_existe")
        _reg, info, _logs = load(self.root)
        self.assertIn("no existe", info["con"].error)


class Dependencias(unittest.TestCase):
    """Un paquete puede usar los tipos de otro; si ese otro cae, cae con él."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_pack(self.root, "usa", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.block("usa.b", "B", run, inputs={"i": "base.t"})
        ''')

    def tearDown(self):
        self.tmp.cleanup()

    def test_usa_los_tipos_de_otro_paquete_que_carga(self):
        write_pack(self.root, "base", OK_BLOCK.format(id="base"))
        reg, info, _ = load(self.root)
        self.assertIn("usa.b", reg)
        self.assertIsNone(info["usa"].error)

    def test_si_el_paquete_de_sus_tipos_cae_tampoco_se_carga(self):
        write_pack(self.root, "base", OK_BLOCK.format(id="base") + "\nraise ImportError('roto')\n")
        reg, info, _ = load(self.root)
        self.assertNotIn("usa.b", reg)
        self.assertIsNotNone(info["usa"].error)

    def test_los_tipos_del_nucleo_valen_sin_paquete(self):
        write_pack(self.root, "cad", '''
            def run(p, i, c):
                return {}
            def register(pack):
                pack.block("cad.b", "B", run, inputs={"m": "cad.modelo"})
        ''')
        reg, info, _ = load(self.root)
        self.assertIn("cad.b", reg)


@necesita_paquetes
class PaquetesDeLaApp(unittest.TestCase):
    """Los paquetes que vienen con la app cargan sin errores."""

    def test_demo_carga_con_sus_bloques_puertos_y_plantilla(self):
        reg = packs.load()
        info = {p.id: p for p in reg.packs}
        self.assertIsNone(info["demo"].error)
        self.assertEqual(reg["demo.voladizo"].inputs, {"tubo": "demo.tubo"})
        self.assertIn("demo.cadena", reg.templates)
        d = reg.describe()
        self.assertEqual(d["blocks"]["demo.tubo"]["outputs"], {"tubo": "demo.tubo"})
        self.assertIn("cad.modelo", d["ports"])


@necesita_paquetes
class SalidasDelSpike(unittest.TestCase):
    """Unas salidas guardadas sin puerto (spike) no se leen con el contrato nuevo: el bloque
    vuelve a «nunca» y conserva sus parámetros."""

    def test_salidas_sin_puerto_se_descartan_al_abrir(self):
        b = new_board()
        el = scene.block_element("demo.tubo", 0, 0)
        b.apply_client_elements([el])
        b.set_params(el["id"], {"L": 450})
        b.state[el["id"]].update(outputs={"masa": {"value": 1.2, "unit": "kg"}},
                                 outputs_hash="x", last_hash="y")
        b.save()
        b2 = reopen(b)
        st = b2.state[el["id"]]
        self.assertIsNone(st["outputs"])
        self.assertEqual(st["params"]["L"], 450)
        self.assertEqual(b2.statuses()[el["id"]], "nunca")


class ContratoDeRun(unittest.TestCase):
    """Un bloque que devuelve otros puertos que los suyos da error en el bloque, no rompe nada."""

    def test_puertos_equivocados_son_un_error_del_bloque(self):
        reg = packs.Registry()
        reg.ports["x.t"] = packs.PortType("x.t", "t")
        reg["x.b"] = packs.BlockType(kind="x.b", title="B", params={}, inputs={},
                                     outputs={"o": "x.t"}, run=lambda p, i, c: {"otro": {}})
        b = new_board()
        b.registry = reg
        el = scene.block_element("x.b", 0, 0)
        b.apply_client_elements([el])
        b.run(el["id"])
        self.assertIn("se esperaban los puertos", b.state[el["id"]]["error"])
        self.assertEqual(b.statuses()[el["id"]], "error")


if __name__ == "__main__":
    unittest.main()
