"""La librería del workspace con stock (FF 7.1 recortada; docs/PLAN_V020.md §5 y §7, V14-V17).

Reglas que protegen:
- **El núcleo no sabe de tipos** (V15): acepta una ficha de un tipo que no conoce mientras su
  `[meta]` (`key`, `type`, `status`) sea válido, y guarda el resto tal cual; un `[meta]` malo
  se rechaza con el motivo y no se guarda nada.
- **Cantidad desconocida** (D33): una cantidad vacía es «desconocida» (None), nunca 0.
- **Importar** (V16): nada se escribe hasta aceptar; una fila mala no tumba las buenas; un
  resumen viejo (el archivo cambió) no se aplica; una fila de solo stock nunca tapa la ficha
  de un paquete.
- **Las fichas de los paquetes** se ven en solo lectura y una del workspace con la misma clave
  manda (V15).
- **buscar_libreria** (V17): por tipo, texto y stock, cada ficha con su fuente `ficha`, y la
  unidad de cada valor que declara el esquema del paquete.
- **Campos por tipo** (docs/PLAN_LIBRERIA.md L3, L4): los que declara el `schema.toml` de un
  paquete salen primero, en su orden y con su unidad; los de fichas que nadie declara, después
  y con `declarado: false`; un tipo declarado sin fichas sale como tipo; dos paquetes con el
  mismo tipo se unen y manda el primero; un `schema.toml` roto no impide cargar el paquete ni
  sus fichas (queda en el registro). El esquema nunca pasa por ficha.
- **SDK** (1.5): la librería del workspace llega al paquete en la ejecución, la acción y la
  vista previa (`ctx.library`, `library.current()`), también por el trabajador; sin
  workspace, vacía y sin error.

Ejecutar desde app/backend:  python -m unittest tests.test_libreria -v
"""
import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from boardprint_sdk import library as sdk_library
from boardprint_sdk.packs import RunContext
from pizarra import agent as agent_mod
from pizarra import library_import, library_schema, pack_data, pack_host, packs, scene
from pizarra.board import Board
from pizarra.library import WorkspaceLibrary, dump, pack_libraries, parse
from pizarra.storage import Conflict, InvalidName, LocalWorkspace, NotFound, names
from pizarra.validation import ValidationError, check_source
from tests.helpers import new_board

FICHA_RARA = """# Un muelle de gas: ningún paquete sabe qué es
[meta]
key = "MG-200"
type = "muelle_gas"
kind = "traccion"
manufacturer = "Stabilus"
status = "unverified"

[source]
title = "Catálogo"
file = "catalogo.pdf"
sha256 = "00"

[values]
fuerza = { v = 200, src = "p. 4" }
carrera = { v = 80, src = "p. 4" }
color = { v = "negro", src = "p. 2" }
"""

FICHA_PAQUETE = """[meta]
key = "RED-1"
type = "reducer"
kind = "planetary"
manufacturer = "Fabricante"
status = "verified"
verified_by = "Ingeniero"
verified_on = "2026-11-01"

[source]
title = "Datasheet"
file = "red.pdf"
sha256 = "aa"

[values]
ratio = { v = 50, src = "p. 1" }
mass = { v = 0.5, src = "p. 1" }
"""


def _workspace():
    tmp = Path(tempfile.mkdtemp())
    return tmp, LocalWorkspace.open(tmp / "Personal", trash=lambda p: Path(p).unlink())


def _pack_lib(root):
    """Las fichas de un «paquete» de prueba: `<root>/library/reducers/RED-1.toml`."""
    d = Path(root) / "library" / "reducers"
    d.mkdir(parents=True)
    (d / "RED-1.toml").write_text(FICHA_PAQUETE, encoding="utf-8")
    return [("pk", sdk_library.Library(Path(root) / "library"))]


class ElNucleoNoSabeDeTipos(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ws = _workspace()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lib = WorkspaceLibrary(self.ws)

    def test_una_ficha_de_un_tipo_que_no_conoce_se_guarda_tal_cual(self):
        s = self.lib.save("MG-200", FICHA_RARA)
        self.assertEqual((s["type"], s["manufacturer"], s["fields"], s["origin"]),
                         ("muelle_gas", "Stabilus", 3, "workspace"))
        self.assertEqual(self.ws.load_library_ficha("MG-200"), FICHA_RARA)   # el comentario también
        got = self.lib.get("MG-200")
        self.assertEqual(got["data"]["values"]["color"]["v"], "negro")
        self.assertEqual(self.lib.types(), ["muelle_gas"])
        self.assertEqual([f["nombre"] for f in self.lib.fields("muelle_gas")], ["carrera", "color", "fuerza"])
        self.assertFalse(any(f["declarado"] for f in self.lib.fields("muelle_gas")))

    def test_un_meta_malo_se_rechaza_con_el_motivo_y_no_guarda_nada(self):
        malos = {
            "sin meta": '[values]\nx = { v = 1, src = "p" }\n',
            "sin status": '[meta]\nkey = "MG-200"\ntype = "muelle_gas"\n',
            "status raro": FICHA_RARA.replace('"unverified"', '"casi"'),
            "tipo raro": FICHA_RARA.replace('"muelle_gas"', '"Muelle Gas"'),
            "otra clave": FICHA_RARA.replace('key = "MG-200"', 'key = "MG-300"'),
            "no es toml": "esto = = no",
        }
        for nombre, texto in malos.items():
            with self.assertRaises(ValidationError, msg=nombre):
                self.lib.save("MG-200", texto)
        self.assertEqual(self.ws.list_library_fichas(), {})

    def test_el_tipo_decide_la_carpeta_y_borrar_va_a_la_papelera(self):
        self.lib.save("MG-200", FICHA_RARA)
        self.assertTrue((self.ws.library_dir() / "muelle_gass" / "MG-200.toml").is_file())
        self.lib.delete("MG-200")
        self.assertEqual(self.lib.list(), [])
        with self.assertRaises(NotFound):
            self.lib.delete("MG-200")

    def test_una_ficha_ilegible_a_mano_sale_con_su_error_y_no_rompe_la_lista(self):
        d = self.ws.library_dir() / "cosas"
        d.mkdir(parents=True)
        (d / "ROTA.toml").write_text("esto = = no", encoding="utf-8")
        self.lib.save("MG-200", FICHA_RARA)
        items = {s["key"]: s for s in self.lib.list()}
        self.assertTrue(items["ROTA"]["error"])
        self.assertIsNone(items["MG-200"]["error"])

    def test_dump_escribe_el_formato_de_las_fichas_y_se_lee_igual(self):
        data = parse(FICHA_RARA)
        text = dump(data)
        self.assertIn('fuerza = { v = 200, src = "p. 4" }', text)
        self.assertEqual(parse(text), data)


class ElStock(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ws = _workspace()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lib = WorkspaceLibrary(self.ws)

    def test_una_cantidad_vacia_es_desconocida_no_cero(self):
        stock = self.lib.update_stock({"MG-200": {"cantidad": "", "ubicacion": "Estante 3"},
                                       "SHG-20": {"cantidad": 0},
                                       "M6": {"cantidad": "2,5"}})
        self.assertIsNone(stock["MG-200"]["cantidad"])
        self.assertEqual(stock["SHG-20"]["cantidad"], 0)
        self.assertEqual(stock["M6"]["cantidad"], 2.5)
        csv = (self.ws.library_dir() / "stock.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(csv[0], "key,cantidad,ubicacion,fecha,nota")
        self.assertIn("MG-200,,Estante 3,,", csv)
        self.assertIn("SHG-20,0,,,", csv)

    def test_una_entrada_mala_no_guarda_ninguna(self):
        self.lib.update_stock({"A": {"cantidad": 3}})
        for malo in ({"B": {"cantidad": -1}}, {"B": {"cantidad": "muchas"}},
                     {"B": {"cantidad": True}}, {"B": {"precio": 3}}, {"B": 3},
                     {"../x": {"cantidad": 1}}):
            with self.assertRaises((ValidationError, InvalidName), msg=malo):
                self.lib.update_stock({"A": {"cantidad": 9}, **malo})
        self.assertEqual(self.lib.stock()["A"]["cantidad"], 3)

    def test_none_quita_la_clave_del_stock(self):
        self.lib.update_stock({"A": {"cantidad": 3}, "B": {"cantidad": 1}})
        self.assertEqual(set(self.lib.update_stock({"A": None})), {"B"})

    def test_el_stock_sin_ficha_sale_en_la_lista(self):
        self.lib.update_stock({"A": {"cantidad": None}})
        (s,) = self.lib.list()
        self.assertEqual((s["key"], s["origin"], s["stock"]["cantidad"]), ("A", "stock", None))


class LasFichasDeLosPaquetes(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ws = _workspace()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lib = WorkspaceLibrary(self.ws, _pack_lib(self.tmp / "pk"))

    def test_se_ven_en_solo_lectura_con_su_paquete(self):
        (s,) = self.lib.list("reducer")
        self.assertEqual((s["key"], s["origin"], s["pack"], s["editable"]),
                         ("RED-1", "pack", "pk", False))
        self.assertEqual(self.lib.get("RED-1")["toml"], FICHA_PAQUETE)
        with self.assertRaises(ValidationError):
            self.lib.delete("RED-1")
        self.assertEqual([f["nombre"] for f in self.lib.fields("reducer")], ["mass", "ratio"])

    def test_una_del_workspace_con_la_misma_clave_manda(self):
        self.lib.save("RED-1", FICHA_PAQUETE.replace("Fabricante", "El mío"))
        (s,) = self.lib.list("reducer")
        self.assertEqual((s["origin"], s["manufacturer"], s["overrides"]), ("workspace", "El mío", "pk"))

    def test_su_stock_se_apunta_por_clave_sin_copiarla(self):
        self.lib.update_stock({"RED-1": {"cantidad": 2}})
        (s,) = self.lib.list()
        self.assertEqual((s["origin"], s["stock"]["cantidad"]), ("pack", 2))
        self.assertEqual(self.ws.list_library_fichas(), {})


ESQUEMA = """# lo que declara el paquete de prueba
[reducer]
clases = ["planetary"]
ratio = { obligatorio = true, unidad = "-", min = 3, max = 200, descripcion = "Relación" }
T_rated = { obligatorio = true, unidad = "Nm", min = 0.1, max = 1e5, descripcion = "Par nominal" }
mass = { unidad = "kg", min = 0.01, max = 500, descripcion = "Masa" }

[motor]
par = { obligatorio = true, unidad = "Nm", min = 0, max = 100, descripcion = "Par" }
"""

FICHA_MIA = FICHA_PAQUETE.replace('"RED-1"', '"MIA-1"') + 'color = { v = "negro", src = "p. 2" }\n'


def _pack_con_esquema(root, pid, esquema, ficha=True):
    """Un paquete `pid` en `<root>/<pid>/` sin bloques, con `library/schema.toml` (si
    `esquema` no es None) y, con `ficha`, la reductora `RED-1`."""
    d = Path(root) / pid
    (d / "library" / "reducers").mkdir(parents=True)
    (d / "pack.toml").write_text(
        f'id = "{pid}"\nname = "{pid}"\nversion = "1.0.0"\nauthor = "Pruebas"\n'
        'description = "Paquete de prueba del esquema de la librería"\nsdk = ">=1.5,<2"\n',
        encoding="utf-8")
    (d / "blocks.py").write_text("def register(pack):\n    pass\n", encoding="utf-8")
    if esquema is not None:
        (d / "library" / "schema.toml").write_text(esquema, encoding="utf-8")
    if ficha:
        (d / "library" / "reducers" / "RED-1.toml").write_text(FICHA_PAQUETE, encoding="utf-8")
    return d


class CamposPorTipo(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ws = _workspace()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = []

    def libreria(self):
        reg = packs.load([self.tmp / "packs"], log=self.log.append)
        return reg, WorkspaceLibrary(self.ws, pack_libraries(reg))

    def test_los_declarados_primero_en_su_orden_y_con_su_unidad(self):
        _pack_con_esquema(self.tmp / "packs", "pk", ESQUEMA)
        _, lib = self.libreria()
        lib.save("MIA-1", FICHA_MIA)                      # usa `color`, que nadie declara
        got = lib.fields("reducer")
        self.assertEqual([(f["nombre"], f["unidad"], f["obligatorio"], f["declarado"], f["paquete"])
                          for f in got],
                         [("ratio", "-", True, True, "pk"), ("T_rated", "Nm", True, True, "pk"),
                          ("mass", "kg", False, True, "pk"), ("color", "", False, False, None)])
        self.assertEqual((got[1]["descripcion"], got[1]["min"], got[1]["max"]), ("Par nominal", 0.1, 1e5))
        self.assertNotIn("clases", [f["nombre"] for f in got])     # es del tipo, no un campo

    def test_un_tipo_declarado_sin_fichas_sale_como_tipo(self):
        _pack_con_esquema(self.tmp / "packs", "pk", ESQUEMA)
        _, lib = self.libreria()
        self.assertEqual(lib.types(), ["motor", "reducer"])
        self.assertEqual([f["nombre"] for f in lib.fields("motor")], ["par"])
        self.assertEqual(lib.list("motor"), [])

    def test_dos_paquetes_con_el_mismo_tipo_se_unen_y_manda_el_primero(self):
        _pack_con_esquema(self.tmp / "packs", "pk", ESQUEMA)
        _pack_con_esquema(self.tmp / "packs", "pl", '[reducer]\nmass = { unidad = "g", descripcion = "Peso" }\n'
                          'eff = { unidad = "-", descripcion = "Rendimiento" }\n', ficha=False)
        _, lib = self.libreria()
        got = {f["nombre"]: f for f in lib.fields("reducer")}
        self.assertEqual(list(got), ["ratio", "T_rated", "mass", "eff"])
        self.assertEqual((got["mass"]["unidad"], got["mass"]["paquete"]), ("kg", "pk"))
        self.assertEqual((got["eff"]["paquete"], got["eff"]["declarado"]), ("pl", True))

    def test_un_esquema_roto_no_impide_cargar_el_paquete_ni_sus_fichas(self):
        _pack_con_esquema(self.tmp / "packs", "pk", "esto = = no")
        reg, lib = self.libreria()
        self.assertIsNotNone(reg.pack("pk"), self.log)          # cargado y sin error
        self.assertTrue(any("pk" in m and "schema.toml" in m for m in self.log), self.log)
        self.assertEqual([s["key"] for s in lib.list()], ["RED-1"])
        self.assertEqual([(f["nombre"], f["declarado"]) for f in lib.fields("reducer")],
                         [("mass", False), ("ratio", False)])

    def test_una_linea_mala_se_queda_fuera_y_las_demas_valen(self):
        _pack_con_esquema(self.tmp / "packs", "pk", ESQUEMA.replace('unidad = "kg"', "unidad = 3")
                          + '\n["Tipo Raro"]\nx = { unidad = "mm" }\n')
        reg, lib = self.libreria()
        self.assertIsNotNone(reg.pack("pk"), self.log)
        self.assertEqual([f["nombre"] for f in lib.fields("reducer") if f["declarado"]],
                         ["ratio", "T_rated"])
        self.assertEqual(lib.types(), ["motor", "reducer"])
        self.assertEqual(sum("schema.toml" in m for m in self.log), 2, self.log)

    def test_el_esquema_nunca_pasa_por_ficha(self):
        d = _pack_con_esquema(self.tmp / "packs", "pk", ESQUEMA)
        # aunque el fichero tuviera la forma de una ficha, en la raíz de library/ no es una
        (d / "library" / "schema.toml").write_text(FICHA_PAQUETE.replace("RED-1", "ESQUEMA"),
                                                  encoding="utf-8")
        self.assertEqual([f.key for f in sdk_library.Library(d / "library").records()], ["RED-1"])
        _, lib = self.libreria()
        self.assertEqual([s["key"] for s in lib.list()], ["RED-1"])

    def test_la_regla_del_tipo_es_la_de_las_fichas(self):
        self.assertEqual(library_schema.TYPE_RE.pattern, names._FICHA_TYPE_RE.pattern)

    def test_buscar_da_la_unidad_de_cada_valor_declarado(self):
        _pack_con_esquema(self.tmp / "packs", "pk", ESQUEMA)
        _, lib = self.libreria()
        lib.save("MIA-1", FICHA_MIA)
        got = {r["key"]: r for r in lib.search("reducer")[0]}
        self.assertEqual(got["RED-1"]["units"], {"ratio": "-", "mass": "kg"})
        self.assertEqual(got["MIA-1"]["units"], {"ratio": "-", "mass": "kg"})    # color: sin unidad


CSV = """Ref;Marca;Relación;Masa (kg);Uds;Sitio
RED-1;Fabricante;50;0,5;4;Estante 1
RED-2;Otra;100;0,8;;Estante 2
;Sin clave;3;1;1;
RED-3;Mala;30;0,2;muchas;
RED-2;Repetida;1;1;1;
"""
MAPEO = {"Ref": "key", "Marca": "manufacturer", "Relación": "values.ratio",
         "Masa (kg)": "values.mass", "Uds": "cantidad", "Sitio": "ubicacion"}


class Importar(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ws = _workspace()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.lib = WorkspaceLibrary(self.ws, _pack_lib(self.tmp / "pk"))
        self.csv = self.tmp / "stock.csv"
        self.csv.write_text(CSV, encoding="utf-8")

    def test_inspeccionar_da_las_columnas_y_unas_filas(self):
        got = library_import.inspect(self.csv)
        self.assertEqual(got["columns"], ["Ref", "Marca", "Relación", "Masa (kg)", "Uds", "Sitio"])
        self.assertEqual((got["rows"], got["sample"][0]["_row"], got["sample"][0]["Masa (kg)"]),
                         (5, 2, "0,5"))

    def test_importar_no_escribe_nada_hasta_aceptar(self):
        plan = library_import.plan(self.lib, self.csv, None, "reducer", MAPEO)
        self.assertEqual(self.ws.list_library_fichas(), {})
        self.assertEqual(self.ws.load_stock(), {})
        self.assertFalse(self.ws.library_dir().exists())
        self.assertEqual(plan["counts"], {"create": 2, "update": 0, "unchanged": 0, "invalid": 3})
        done = library_import.apply(self.lib, plan["token"])
        self.assertEqual((done["fichas"], done["stock"]), (1, 2))
        with self.assertRaises(Conflict):                      # un token se usa una vez
            library_import.apply(self.lib, plan["token"])

    def test_una_fila_mala_no_tumba_las_buenas(self):
        plan = library_import.plan(self.lib, self.csv, None, "reducer", MAPEO)
        rows = {r["row"]: r for r in plan["rows"]}
        self.assertEqual({n: r["state"] for n, r in rows.items()},
                         {2: "create", 3: "create", 4: "invalid", 5: "invalid", 6: "invalid"})
        self.assertIn("sin clave", rows[4]["reason"])
        self.assertIn("muchas", rows[5]["reason"])
        self.assertIn("fila 3", rows[6]["reason"])
        library_import.apply(self.lib, plan["token"])
        red2 = parse(self.ws.load_library_ficha("RED-2"))
        self.assertEqual((red2["meta"]["status"], red2["values"]["ratio"]["v"],
                          red2["values"]["mass"]["v"]), ("unverified", 100, 0.8))
        self.assertEqual(red2["values"]["mass"]["src"], "stock.csv, fila 3")
        self.assertEqual(red2["source"]["file"], "stock.csv")
        self.assertIsNone(self.ws.load_library_ficha("RED-3"))
        stock = self.ws.load_stock()
        self.assertEqual((stock["RED-1"]["cantidad"], stock["RED-2"]["cantidad"]), (4, None))
        self.assertEqual(stock["RED-2"]["ubicacion"], "Estante 2")

    def test_lo_que_ya_dice_la_ficha_del_paquete_no_la_copia(self):
        plan = library_import.plan(self.lib, self.csv, None, "reducer", MAPEO)
        red1 = next(r for r in plan["rows"] if r["key"] == "RED-1")
        self.assertEqual((red1["ficha"], red1["stock"]), (None, "create"))

    def test_cambiar_un_valor_de_la_ficha_de_un_paquete_la_copia_sin_verificar(self):
        self.csv.write_text("Ref;Relación\nRED-1;60\n", encoding="utf-8")
        plan = library_import.plan(self.lib, self.csv, None, "reducer",
                                   {"Ref": "key", "Relación": "values.ratio"})
        (row,) = plan["rows"]
        self.assertEqual(row["ficha"], "create")
        self.assertEqual(len(row["warnings"]), 2)            # copia del paquete y pierde la verificación
        library_import.apply(self.lib, plan["token"])
        copia = parse(self.ws.load_library_ficha("RED-1"))
        self.assertEqual((copia["values"]["ratio"]["v"], copia["values"]["mass"]["v"],
                          copia["meta"]["status"]), (60, 0.5, "unverified"))

    def test_una_fila_de_solo_stock_nunca_tapa_la_ficha_de_un_paquete(self):
        plan = library_import.plan(self.lib, self.csv, None, None, {"Ref": "key", "Uds": "cantidad"})
        library_import.apply(self.lib, plan["token"])
        self.assertEqual(self.ws.list_library_fichas(), {})
        self.assertEqual(self.ws.load_stock()["RED-1"]["cantidad"], 4)

    def test_una_celda_vacia_no_borra_lo_que_habia(self):
        self.lib.update_stock({"RED-2": {"cantidad": 7, "ubicacion": "Cajón"}})
        plan = library_import.plan(self.lib, self.csv, None, None, {"Ref": "key", "Uds": "cantidad"})
        library_import.apply(self.lib, plan["token"])
        self.assertEqual(self.ws.load_stock()["RED-2"], {"cantidad": 7, "ubicacion": "Cajón",
                                                         "fecha": "", "nota": ""})

    def test_si_el_archivo_cambia_entre_el_resumen_y_aceptar_no_se_aplica(self):
        plan = library_import.plan(self.lib, self.csv, None, "reducer", MAPEO)
        self.csv.write_text(CSV.replace("RED-2;Otra;100", "RED-2;Otra;101"), encoding="utf-8")
        with self.assertRaises(Conflict):
            library_import.apply(self.lib, plan["token"])
        self.assertEqual(self.ws.list_library_fichas(), {})

    def test_un_mapeo_que_no_vale_se_dice_antes(self):
        for mapeo, tipo in (({"Marca": "manufacturer"}, "reducer"),          # sin clave
                            ({"Ref": "key", "Nada": "kind"}, "reducer"),     # columna que no está
                            ({"Ref": "key", "Marca": "precio"}, "reducer"),  # destino raro
                            ({"Ref": "key", "Marca": "kind", "Sitio": "kind"}, "reducer"),
                            ({"Ref": "key", "Marca": "manufacturer"}, None)):  # ficha sin tipo
            with self.assertRaises(ValidationError, msg=mapeo):
                library_import.plan(self.lib, self.csv, None, tipo, mapeo)

    def test_un_excel_con_su_hoja(self):
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active.title = "Portada"
        ws = wb.create_sheet("Stock")
        ws.append(["Código", "Cantidad"])
        ws.append(["MG-200", 3])
        ws.append(["MG-300", None])
        path = self.tmp / "stock.xlsx"
        wb.save(path)
        got = library_import.inspect(path, "Stock")
        self.assertEqual((got["sheets"], got["columns"]), (["Portada", "Stock"], ["Código", "Cantidad"]))
        with self.assertRaises(ValidationError):
            library_import.inspect(path, "Otra")
        plan = library_import.plan(self.lib, path, "Stock", None, {"Código": "key", "Cantidad": "cantidad"})
        library_import.apply(self.lib, plan["token"])
        self.assertEqual({k: v["cantidad"] for k, v in self.ws.load_stock().items()},
                         {"MG-200": 3, "MG-300": None})

    def test_un_formato_que_no_es_una_tabla_se_rechaza(self):
        (self.tmp / "x.pdf").write_bytes(b"%PDF")
        for p in (self.tmp / "x.pdf", self.tmp / "no_esta.csv"):
            with self.assertRaises(ValidationError):
                library_import.inspect(p)


class BuscarLibreria(unittest.TestCase):
    def setUp(self):
        self.board = new_board()
        self.ws = self.board.ws
        WorkspaceLibrary(self.ws).save("MG-200", FICHA_RARA)
        WorkspaceLibrary(self.ws).update_stock({"MG-200": {"cantidad": None}})

    def buscar(self, **args):
        return json.loads(agent_mod.tool_buscar_libreria(self.board, args)["content"][0]["text"])

    def test_por_tipo_texto_y_stock_con_su_fuente_ficha(self):
        (r,) = self.buscar(type="muelle_gas", text="stabilus")["results"]
        self.assertEqual(r["values"]["fuerza"], 200)
        check_source(r["cite_as"])                 # D19: vale como fuente tal cual
        self.assertEqual(r["cite_as"], {"kind": "ficha", "ref": "ficha:MG-200"})
        self.assertEqual(len(self.buscar(con_stock=True)["results"]), 1)   # desconocida cuenta
        self.assertEqual(self.buscar(type="muelle_gas", con_stock=False)["results"], [])
        self.assertEqual(self.buscar(text="bosch")["results"], [])
        self.assertEqual(self.buscar(type="amortiguador")["results"], [])

    def test_las_tienen_los_dos_agentes(self):
        from pizarra import agent_review
        self.assertIn("buscar_libreria", agent_review.TOOLS)


SDK_PACK = '''
from boardprint_sdk import library
from boardprint_sdk.packs import Param


def run(p, i, ctx):
    s = ctx.library.stock("MG-200")
    return {"out": {"n": {"value": len(ctx.library.records(p["tipo"])), "unit": ""},
                    "otra": {"value": len(library.current().records()), "unit": ""},
                    "cantidad": {"value": -1 if s is None else (s["cantidad"] if s["cantidad"] is not None else -2),
                                 "unit": ""}}}


def preview(p, i):
    f = library.current().load("MG-200")
    return {"ficha": None if f is None else f.data["meta"]["manufacturer"]}


def accion(params, inputs, args, ctx):
    return {"claves": [f.key for f in ctx.library.records()]}


def register(pack):
    pack.port("lib.t", "t")
    pack.block("lib.b", "Con librería", run, params={"tipo": Param("muelle_gas")},
               outputs={"out": "lib.t"}, preview=preview)
    pack.action("lib.ver", accion)
'''


def _sdk_pack(root):
    d = Path(root) / "lib"
    d.mkdir(parents=True)
    (d / "pack.toml").write_text(textwrap.dedent('''\
        id = "lib"
        name = "Lib"
        version = "1.0.0"
        author = "Pruebas"
        description = "Paquete de prueba de la librería"
        sdk = ">=1.5,<2"
        '''), encoding="utf-8")
    (d / "blocks.py").write_text(SDK_PACK, encoding="utf-8")
    return d


class LaLibreriaEnElSdk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        _sdk_pack(cls.tmp / "packs")
        cls.reg = packs.load([cls.tmp / "packs"], log=lambda m: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        base = new_board()
        WorkspaceLibrary(base.ws).save("MG-200", FICHA_RARA)
        WorkspaceLibrary(base.ws).update_stock({"MG-200": {"cantidad": 5}})
        self.board = Board(base.ws, base.project_id, registry=self.reg, connectors=frozenset())
        el = scene.block_element("lib.b", 0, 0)
        self.board.apply_client_elements([el])
        self.bid = el["id"]

    def test_un_paquete_sin_workspace_tiene_la_libreria_vacia(self):
        ctx = RunContext(block_id="t")
        self.assertEqual((ctx.library.records(), ctx.library.load("MG-200"), ctx.library.stock("MG-200")),
                         ([], None, None))
        self.assertEqual(sdk_library.current().records(), [])
        self.assertEqual(pack_data.context("t", {}).library.records(), [])
        self.assertEqual(sdk_library.Library(self.tmp / "no_esta").records(), [])

    def test_el_entorno_de_la_ejecucion_lleva_la_carpeta_de_la_libreria(self):
        self.assertEqual(self.board.run_env(self.bid)["library_dir"], str(self.board.ws.library_dir()))

    def test_la_ejecucion_la_accion_y_la_vista_previa_la_leen(self):
        self.board.run(self.bid)
        out = self.board.state[self.bid]["outputs"]["out"]
        self.assertEqual((out["n"]["value"], out["otra"]["value"], out["cantidad"]["value"]), (1, 1, 5))
        self.assertEqual(self.board.preview(self.bid), {"ficha": "Stabilus"})
        self.assertEqual(self.board.action(self.bid, "lib.ver"), {"claves": ["MG-200"]})
        self.assertEqual(sdk_library.current().records(), [])     # fuera, otra vez vacía

    def test_tambien_por_el_trabajador(self):
        host = pack_host.WorkerHost(pack_host.default_spec(stderr=subprocess.DEVNULL),
                                    [("pruebas", self.tmp / "packs")])
        try:
            host.load()
            env = self.board.run_env(self.bid)
            self.assertEqual(host.preview("lib.b", {"tipo": "muelle_gas"}, {}, env),
                             {"ficha": "Stabilus"})
            self.assertEqual(host.preview("lib.b", {"tipo": "muelle_gas"}, {}), {"ficha": None})
            self.assertEqual(host.action("lib.ver", {}, {}, {}, env, block_id=self.bid),
                             {"claves": ["MG-200"]})
        finally:
            host.close()


try:
    import uvicorn
    from pizarra.server import create_app
    from pizarra.startup import bootstrap
    DEPS = True
except ImportError:                     # job básico del CI: solo biblioteca estándar
    DEPS = False


@unittest.skipUnless(DEPS, "faltan fastapi/uvicorn")
class LasRutas(unittest.TestCase):
    """`library_api`: la superficie sobre la que se construye la interfaz."""

    @classmethod
    def setUpClass(cls):
        import socket
        import threading
        import time
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.tmp = Path(tempfile.mkdtemp())
        start = bootstrap(cls.tmp / "settings.toml", cls.tmp / "Documentos" / "Personal", (),
                          trash=lambda p: Path(p).unlink())
        start.settings.language = "es"
        cls.ws = start.workspace
        cls.server = uvicorn.Server(uvicorn.Config(create_app(start), host="127.0.0.1",
                                                   port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        t0 = time.time()
        while not cls.server.started and time.time() - t0 < 10:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def api(self, method, path, body=None):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_fichas_stock_e_importar(self):
        code, s = self.api("PUT", "/api/library/ficha/MG-200", {"toml": FICHA_RARA})
        self.assertEqual((code, s["type"]), (200, "muelle_gas"))
        self.assertEqual(self.api("PUT", "/api/library/ficha/MG-200",
                                  {"toml": "[meta]\nkey = 'MG-200'\n"})[0], 422)
        self.assertEqual(self.api("PUT", "/api/library/ficha/con%20espacio", {"toml": FICHA_RARA})[0], 422)
        code, got = self.api("GET", "/api/library/ficha/MG-200")
        self.assertEqual((code, got["toml"], got["editable"]), (200, FICHA_RARA, True))
        self.assertEqual(self.api("GET", "/api/library/ficha/NADA")[0], 404)
        code, lst = self.api("GET", "/api/library?type=muelle_gas")
        self.assertEqual(([i["key"] for i in lst["items"]], "muelle_gas" in lst["types"]),
                         (["MG-200"], True))
        fields = self.api("GET", "/api/library/fields?type=muelle_gas")[1]["fields"]
        self.assertEqual([(f["nombre"], f["unidad"], f["declarado"], f["paquete"]) for f in fields],
                         [("carrera", "", False, None), ("color", "", False, None),
                          ("fuerza", "", False, None)])

        code, st = self.api("PUT", "/api/library/stock", {"MG-200": {"cantidad": ""}})
        self.assertEqual((code, st["stock"]["MG-200"]["cantidad"]), (200, None))
        self.assertEqual(self.api("PUT", "/api/library/stock", {"MG-200": {"cantidad": -3}})[0], 422)
        self.assertIsNone(self.api("GET", "/api/library/stock")[1]["stock"]["MG-200"]["cantidad"])

        csv = self.tmp / "importar.csv"
        csv.write_text("Ref,Uds\nMG-200,4\n,1\n", encoding="utf-8")
        code, ins = self.api("POST", "/api/library/import/inspect", {"path": str(csv)})
        self.assertEqual((code, ins["columns"]), (200, ["Ref", "Uds"]))
        code, plan = self.api("POST", "/api/library/import/plan",
                              {"path": str(csv), "mapping": {"Ref": "key", "Uds": "cantidad"}})
        self.assertEqual((code, plan["counts"]["update"], plan["counts"]["invalid"]), (200, 1, 1))
        self.assertIsNone(self.ws.load_stock()["MG-200"]["cantidad"])     # aún nada
        code, done = self.api("POST", "/api/library/import/apply", {"token": plan["token"]})
        self.assertEqual((code, done["stock"]), (200, 1))
        self.assertEqual(self.ws.load_stock()["MG-200"]["cantidad"], 4)
        self.assertEqual(self.api("POST", "/api/library/import/apply", {"token": plan["token"]})[0], 409)
        self.assertEqual(self.api("POST", "/api/library/import/plan",
                                  {"path": str(csv), "mapping": {"Uds": "cantidad"}})[0], 422)

        self.assertEqual(self.api("DELETE", "/api/library/ficha/MG-200")[0], 200)
        self.assertEqual(self.api("DELETE", "/api/library/ficha/MG-200")[0], 404)


if __name__ == "__main__":
    unittest.main()
