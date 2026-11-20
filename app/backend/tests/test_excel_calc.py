"""El recálculo bajo demanda de las fórmulas sin valor guardado (docs/PLAN_EXCEL.md §3.4, X7,
R1, R3).

Reglas:
- Una celda que el recalculador no sabe calcular deja **solo esa** sin valor; las demás siguen.
- Nunca bloquea el sondeo: se lanza en un hilo y, mientras, los nombres que esperan dicen
  `calculando` (también el motivo del bloque enlazado). Al terminar avisa (`on_done`), y el
  siguiente sondeo da el valor sin que el archivo cambie.
- Sin entorno (sin el Python de la app, sin `uv`, sin red): todo sin valor con el motivo, y no
  se reintenta en cada sondeo; sí cuando cambia el archivo.
- La caché es por huella del archivo (`<caché>/excel_calc/<huella>.json`): el mismo archivo no
  se recalcula otra vez, ni tras reabrir la app.
- Un valor guardado por Excel nunca se recalcula ni se sustituye.
- El entorno de xlcalculator va aparte del de los paquetes, y el script va en el instalador.
- La prueba con xlcalculator de verdad se salta sin el Python y el `uv` de la app.

Ejecutar desde app/backend:  python -m unittest tests.test_excel_calc -v
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path

import openpyxl
from openpyxl.workbook.defined_name import DefinedName

from pizarra import excel_calc, excel_names, pack_env, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace
from tests.test_excel_links import REG

BACKEND = Path(__file__).resolve().parents[1]
CONF = BACKEND.parent / "shell" / "src-tauri" / "tauri.conf.json"


def tmp():
    return Path(tempfile.mkdtemp())


def libro(path, cells, names, bump=None):
    """Libro `path` (hoja Datos) con `cells` y `names` = {nombre: referencia}. openpyxl no guarda
    el valor de una fórmula: todas quedan sin valor guardado."""
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


CELLS = {"B3": 0.3, "B4": 2.5, "B5": "=B3*2", "B6": "=VLOOKUP(2.5,D1:E3,2,TRUE)",
         "D1": 1, "E1": 10, "D2": 2, "E2": 20, "D3": 3, "E3": 30}
NAMES = {"L_m": "Datos!$B$3", "doble_m": "Datos!$B$5", "busca_kg": "Datos!$B$6"}


class Falso:
    """Recalculador de mentira: `values` y `errors` por celda, como el script. Con `gate`,
    espera a que se abra (un cálculo largo). `fail`: lanza ese `CalcError` (sin entorno)."""

    def __init__(self, values=None, errors=None, gate=None, fail=None):
        self.values, self.errors, self.gate, self.fail = values or {}, errors or {}, gate, fail
        self.calls = []

    def __call__(self, path, cells):
        self.calls.append(list(cells))
        if self.gate is not None:
            self.gate.wait(10)
        if self.fail is not None:
            raise self.fail
        return {"values": {c: self.values[c] for c in cells if c in self.values},
                "errors": {c: self.errors.get(c, "no está") for c in cells
                           if c not in self.values}}


class Base(unittest.TestCase):
    def setUp(self):
        self.cache = tmp()
        self.done = threading.Event()
        self.path = libro(tmp() / "datos.xlsx", CELLS, NAMES)

    def calc(self, run, **kw):
        return excel_calc.Calculator(self.cache, run=run, on_done=self.done.set, **kw)

    def wait(self, calc):
        self.assertTrue(self.done.wait(10), "el recálculo no termina")
        self.done.clear()
        calc.join()

    def names(self, calc, path=None):
        path = path or self.path
        return excel_names.names(path, calc.recalc_for(excel_calc.digest(path)))


class Celdas(Base):
    def test_una_celda_que_falla_deja_solo_esa_sin_valor(self):
        run = Falso({"Datos!B5": 0.6}, {"Datos!B6": "NotImplementedError: Excact match only"})
        calc = self.calc(run)
        self.names(calc)
        self.wait(calc)
        got = self.names(calc)
        self.assertEqual(run.calls, [["Datos!B5", "Datos!B6"]], "solo las fórmulas sin valor")
        self.assertEqual(got["doble_m"].valor, 0.6)
        self.assertIsNone(got["doble_m"].problema)
        self.assertIsNone(got["busca_kg"].valor)
        self.assertEqual(got["busca_kg"].problema, "sin_valor")
        self.assertEqual(got["L_m"].valor, 0.3, "un valor que no es fórmula, tal cual")

    def test_un_error_de_excel_del_recalculo_no_es_un_valor(self):
        calc = self.calc(Falso({"Datos!B5": "#DIV/0!", "Datos!B6": 3}))
        self.names(calc)
        self.wait(calc)
        got = self.names(calc)
        self.assertEqual(got["doble_m"].problema, "sin_valor")
        self.assertEqual(got["busca_kg"].valor, 3)

    def test_un_valor_guardado_no_se_recalcula(self):
        run = Falso({"Datos!B5": 99})
        calc = self.calc(run)
        path = libro(tmp() / "sin_formulas.xlsx", {"B3": 0.3}, {"L_m": "Datos!$B$3"})
        got = self.names(calc, path)
        self.assertEqual(got["L_m"].valor, 0.3)
        self.assertEqual(run.calls, [])
        self.assertFalse(calc.running(excel_calc.digest(path)))


class SinEsperar(Base):
    def test_mientras_calcula_dice_calculando_y_no_espera(self):
        gate = threading.Event()
        calc = self.calc(Falso({"Datos!B5": 0.6, "Datos!B6": 3}, gate=gate))
        t0 = time.perf_counter()
        book = excel_calc_book(self.path, calc)
        self.assertLess(time.perf_counter() - t0, 5, "el sondeo no espera al recálculo")
        self.assertEqual(book.names["doble_m"].problema, "calculando")
        self.assertIsNone(book.names["doble_m"].valor)
        self.assertEqual(book.calc_state, "calculando")
        again = excel_calc_book(self.path, calc)
        self.assertEqual(again.names["busca_kg"].problema, "calculando")
        gate.set()
        self.wait(calc)
        self.assertEqual(excel_calc_book(self.path, calc).names["doble_m"].valor, 0.6)

    def test_sin_entorno_todo_sin_valor_con_motivo_y_sin_esperar(self):
        calc = excel_calc.Calculator(self.cache, pyenv=None, on_done=self.done.set)
        t0 = time.perf_counter()
        book = excel_calc_book(self.path, calc)
        self.assertLess(time.perf_counter() - t0, 5)
        self.assertEqual({n.problema for k, n in book.names.items() if k != "L_m"}, {"sin_valor"})
        self.assertEqual(book.calc_state, "error")
        from pizarra import excel_links
        motivos = {v["nombre"]: v["motivo"] for v in excel_links.names_view(book)}
        self.assertIn("Excel", motivos["doble_m"], "dice que se abra y se guarde en Excel")
        self.assertNotEqual(motivos["doble_m"], excel_links.problem_text("sin_valor"),
                            "con el motivo de por qué no se recalcula")

    def test_un_fallo_del_entorno_no_se_reintenta_hasta_que_cambia_el_archivo(self):
        run = Falso(fail=excel_calc.CalcError("excel.calculo.no_se_instala", motivo="sin red"))
        calc = self.calc(run)
        excel_calc_book(self.path, calc)
        self.wait(calc)
        for _ in range(3):
            book = excel_calc_book(self.path, calc)
        self.assertEqual(len(run.calls), 1, "cada 5 s no se vuelve a intentar")
        self.assertEqual(book.calc_state, "error")
        self.assertEqual(book.names["doble_m"].problema, "sin_valor")
        libro(self.path, {**CELLS, "B3": 0.4}, NAMES)           # otro archivo: otra huella
        excel_calc_book(self.path, calc)
        self.wait(calc)
        self.assertEqual(len(run.calls), 2)


def excel_calc_book(path, calc):
    from pizarra import excel_links
    return excel_links.read_book(path, excel_calc.digest(path), calc)


class Cache(Base):
    def test_la_cache_es_por_huella(self):
        run = Falso({"Datos!B5": 0.6, "Datos!B6": 3})
        calc = self.calc(run)
        self.names(calc)
        self.wait(calc)
        h = excel_calc.digest(self.path)
        self.assertTrue((self.cache / "excel_calc" / f"{h}.json").is_file())
        again = self.calc(run)                    # la app reabierta: la caché sigue
        self.assertEqual(self.names(again)["doble_m"].valor, 0.6)
        self.assertEqual(len(run.calls), 1)
        libro(self.path, {**CELLS, "B3": 0.5}, NAMES)
        self.assertEqual(excel_calc_book(self.path, again).names["doble_m"].problema, "calculando")
        self.wait(again)
        self.assertEqual(len(run.calls), 2, "otra huella, otro cálculo")

    def test_calcula_sobre_una_copia_que_luego_borra(self):
        seen = []
        run = Falso({"Datos!B5": 0.6})
        calc = self.calc(lambda path, cells: (seen.append(Path(path)), run(path, cells))[1])
        self.names(calc)
        self.wait(calc)
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(seen[0], self.path, "el archivo del usuario no se abre mientras")
        self.assertFalse(seen[0].exists(), "la copia no se queda en la caché")


class EnLaPizarra(Base):
    """El sondeo de la pizarra (D134) con el recalculador: no espera, el bloque enlazado queda
    `incompleto` con «calculando» y, al terminar, el siguiente sondeo trae el valor."""

    def setUp(self):
        super().setUp()
        ws = LocalWorkspace.open(tmp() / "Personal", trash=lambda p: None)
        self.b = Board(ws, ws.create_project("", "X").id, registry=REG, connectors=frozenset())
        block = scene.block_element("xl.viga", 0, 0)
        self.b.apply_client_elements([block])
        self.bid = block["id"]
        (card,) = self.b.add_cards([self.path], 400, 0)
        self.cid = card["id"]

    def test_el_sondeo_no_espera_y_al_acabar_trae_el_valor(self):
        gate = threading.Event()
        self.b.calc = self.calc(Falso({"Datos!B5": 0.6, "Datos!B6": 3}, gate=gate))
        t0 = time.perf_counter()
        self.b.probe()
        self.assertLess(time.perf_counter() - t0, 5)
        names = {n["nombre"]: n for n in self.b.sources_view()[self.cid]["names"]}
        self.assertEqual(names["doble_m"]["problema"], "calculando")
        self.assertTrue(names["doble_m"]["motivo"])
        self.b.link_param(self.bid, "L", self.cid, "doble_m")      # se enlaza sin valor (R1)
        v = self.b.blocks_view()["blocks"][self.bid]
        self.assertEqual(v["status"], "incompleto")
        self.assertIn(excel_calc_text("calculando"), v["reason"])
        self.assertFalse(self.b.probe(), "sigue calculando: nada cambia")
        gate.set()
        self.wait(self.b.calc)
        self.assertTrue(self.b.probe(), "el valor llega sin que cambie el archivo")
        self.assertAlmostEqual(self.b.state[self.bid]["params"]["L"], 600)
        self.assertNotEqual(self.b.blocks_view()["blocks"][self.bid]["status"], "incompleto")

    def test_sin_recalculador_es_como_antes(self):
        self.b.calc = None
        excel_calc.configure(None)
        self.b.probe()
        names = {n["nombre"]: n for n in self.b.sources_view()[self.cid]["names"]}
        self.assertEqual(names["doble_m"]["problema"], "sin_valor")


def excel_calc_text(code):
    from pizarra import excel_links
    return excel_links.problem_text(code)


class Instalador(unittest.TestCase):
    def test_el_script_va_en_el_instalador_donde_lo_busca_la_app(self):
        resources = json.loads(CONF.read_text(encoding="utf-8"))["bundle"]["resources"]
        rel = Path(excel_calc.WORKER_SCRIPT)
        self.assertIn(f"worker/{rel.as_posix()}", resources.values())
        self.assertTrue((BACKEND / rel).is_file(), "en desarrollo, worker_dir es app/backend")

    def test_el_script_solo_importa_la_stdlib_y_xlcalculator(self):
        tree = ast.parse((BACKEND / excel_calc.WORKER_SCRIPT).read_text(encoding="utf-8"))
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertEqual(mods - set(sys.stdlib_module_names), {"xlcalculator"})


# `uv` de mentira que apunta todo lo que se le pide (como en test_pack_env).
FAKE_UV = '''
import sys
from pathlib import Path
args = sys.argv[1:]
with open(sys.argv[0] + ".log", "a", encoding="utf-8") as f:
    f.write(" ".join(args) + "\\n")
if args[0] == "venv":
    d = Path(args[-1]); d.mkdir(parents=True); (d / "pyvenv.cfg").write_text("home = x")
'''


class Entorno(unittest.TestCase):
    def test_el_de_la_app_sale_del_entorno_de_paquetes(self):
        cache = tmp()
        env = pack_env.PackEnvironment(BACKEND, None, cache, pyenv=None)   # desarrollo sin pyenv
        calc = excel_calc.Calculator.for_app(env)
        self.assertEqual(calc.cache_dir, cache)
        self.assertEqual(calc.script, BACKEND / excel_calc.WORKER_SCRIPT)
        self.assertEqual(calc.start("x.xlsx", "h", ["Datos!B5"])[0], excel_calc.ERROR,
                         "sin pyenv: sin entorno, y sin lanzar nada")
        self.assertIsNone(excel_calc.Calculator.for_app(None), "sin caché, sin recálculo")

    def test_va_aparte_del_de_los_paquetes_y_con_numpy_2(self):
        root = tmp()
        py = root / "pyenv" / "python" / ("python.exe" if pack_env.EXE else "bin/python3")
        py.parent.mkdir(parents=True)
        py.write_text("")
        uv = root / "uv.py"
        uv.write_text(textwrap.dedent(FAKE_UV), encoding="utf-8")
        pyenv = pack_env.Pyenv(root / "pyenv", uv=[sys.executable, str(uv)])
        cache = root / "cache"
        env_dir = excel_calc.ensure_env(pyenv, cache)
        self.assertTrue(env_dir.is_relative_to(cache / excel_calc.ENVS))
        self.assertFalse((cache / "envs").exists(), "la limpieza de los paquetes no lo toca")
        log = Path(str(uv) + ".log").read_text(encoding="utf-8")
        self.assertIn("xlcalculator==0.5.0", log)
        self.assertIn("--override", log)
        # sin overrides, la huella de un entorno de paquetes no cambia
        self.assertEqual(pack_env.ensure_env(pyenv, cache, [])[0].name,
                         pack_env.env_hash([], pyenv.meta))


def app_pyenv():
    """El Python y el `uv` de la app: `BOARDPRINT_PYENV` o el de `fetch_pyenv.py`."""
    root = os.environ.get("BOARDPRINT_PYENV") or BACKEND.parent / "shell" / "src-tauri" / "pyenv"
    pyenv = pack_env.Pyenv(root)
    return pyenv if pyenv.python.is_file() and Path(pyenv.uv[0]).is_file() else None


@unittest.skipIf(app_pyenv() is None, "sin el Python y el uv de la app (fetch_pyenv.py)")
class XlcalculatorDeVerdad(Base):
    """Crea el entorno con `uv` (descarga unos 200 MB la primera vez) y recalcula de verdad."""

    def test_recalcula_y_lo_que_no_sabe_queda_sin_valor(self):
        calc = excel_calc.Calculator(self.cache, pyenv=app_pyenv(), worker_dir=BACKEND,
                                     on_done=self.done.set)
        self.names(calc)
        self.assertTrue(self.done.wait(600), "uv y xlcalculator tardan demasiado")
        calc.join()
        self.assertIsNone(calc.failed(excel_calc.digest(self.path)))
        got = self.names(calc)
        self.assertAlmostEqual(got["doble_m"].valor, 0.6)
        self.assertEqual(got["busca_kg"].problema, "sin_valor",
                         "VLOOKUP aproximado: xlcalculator no lo sabe")

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
