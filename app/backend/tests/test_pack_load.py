"""Manifiesto, dependencias y orígenes de los paquetes (docs/PLAN_PAQUETES.md §1, §3, §10).

Reglas:
- **Manifiesto**: un `pack.toml` con un id que no es su carpeta, una versión que no es semver
  o un `sdk` que no cumple la versión de la app **nunca se carga**, y los demás paquetes sí.
- **Dependencias**: un paquete cuya dependencia falta o no cumple la versión **no se carga**,
  aunque esté bien; el orden de carga respeta `[requires]` y un ciclo es un error de los
  paquetes del ciclo.
- **Validación** (P30, desde FF 10.2): un paquete que no pasa la validación estática **no se
  carga ni se importa**, ni lo que lo pide; los demás sí. Lo que alcanza `fusion/` de otro
  paquete se sigue en el que carga, venga del origen que venga.
- **Prioridad**: con el mismo paquete en usuario y workspace, **se usa siempre el del
  workspace**; con desarrollo, el de desarrollo (P10, P26).

Ejecutar desde app/backend:  python -m unittest tests.test_pack_load -v
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from pizarra import packs
from pizarra.pack_versions import parse_spec, parse_version, satisfies
from tests.helpers import necesita_paquetes

BODY = '''
from boardprint_sdk.packs import Param

def run(p, i, c):
    return {{"out": {{"x": {{"value": p["a"], "unit": "mm"}}}}}}

def register(pack):
    pack.port("{id}.t", "t")
    pack.block("{id}.b", "{title}", run, params={{"a": Param(1, "mm")}}, outputs={{"out": "{id}.t"}})
'''


def write(root, pack_id, version="1.0.0", sdk='">=1.0,<2"', requires=None, body=None,
          title="B", extra="", folder=None):
    d = Path(root) / (folder or pack_id)
    d.mkdir(parents=True)
    lines = [f'id = "{pack_id}"', f'name = "{pack_id}"']
    if "author" not in extra:                     # la validación los pide (P30)
        lines += ['author = "Pruebas"', 'description = "Paquete de prueba"']
    if version is not None:
        lines.append(f'version = "{version}"')
    if sdk is not None:
        lines.append(f"sdk = {sdk}")
    lines.append(extra)
    if requires:
        lines.append("[requires]")
        lines += [f'{k} = "{v}"' for k, v in requires.items()]
    (d / "pack.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "blocks.py").write_text(textwrap.dedent(body or BODY.format(id=pack_id, title=title)),
                                 encoding="utf-8")
    return d


def load(*dirs):
    logs = []
    reg = packs.load(list(dirs), log=logs.append)
    return reg, {p.id: p for p in reg.packs}, logs


class Versiones(unittest.TestCase):
    def test_semver_estricta(self):
        self.assertEqual(parse_version("0.12.3"), (0, 12, 3))
        for bad in ("1", "1.0", "01.0.0", "1.0.0-beta", "v1.0.0", "", None, 1):
            with self.assertRaises(ValueError, msg=bad):
                parse_version(bad)

    def test_rangos(self):
        self.assertTrue(satisfies("1.0.0", ">=1.0,<2"))
        self.assertTrue(satisfies("1.9.9", ">=1.0,<2"))
        self.assertFalse(satisfies("2.0.0", ">=1.0,<2"))
        self.assertFalse(satisfies("0.9.0", ">=1.0,<2"))
        self.assertTrue(satisfies("0.2.1", "0.2.1"))
        self.assertFalse(satisfies("0.2.1", "!=0.2.1"))
        self.assertTrue(satisfies("0.1.5", ">0.1, <=0.1.5"))
        for bad in ("", ">=1.0,", "~=1.0", ">= 1.x", "latest"):
            with self.assertRaises(ValueError, msg=bad):
                parse_spec(bad)


class Manifiesto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, "bueno")

    def tearDown(self):
        self.tmp.cleanup()

    def assert_no_carga(self, roto, *texto):
        reg, info, _ = load(self.root)
        self.assertIn("bueno.b", reg, "los demás cargan")
        self.assertIsNotNone(info[roto].error)
        self.assertFalse([k for k in reg if k.startswith(roto + ".")])
        self.assertFalse([t for t in reg.ports if t.startswith(roto + ".")])
        for t in texto:
            self.assertIn(t, info[roto].error)
        return info[roto]

    def test_un_id_que_no_es_su_carpeta_no_carga(self):
        write(self.root, "otro", folder="roto")
        self.assert_no_carga("roto", "nombre de la carpeta")

    def test_una_version_que_no_es_semver_no_carga(self):
        for i, v in enumerate(("1", "1.0", "0.1.0-dev", "uno")):
            write(self.root, f"roto{i}", version=v)
            self.assert_no_carga(f"roto{i}", "semver")

    def test_sin_version_no_carga(self):
        write(self.root, "roto", version=None)
        self.assert_no_carga("roto", "semver")

    def test_un_sdk_que_no_cumple_el_de_la_app_no_carga(self):
        write(self.root, "roto", sdk='">=2.0,<3"')
        self.assert_no_carga("roto", "pide el SDK >=2.0,<3", packs.SDK_VERSION)

    def test_sin_sdk_no_carga(self):
        write(self.root, "roto", sdk=None)
        self.assert_no_carga("roto", "falta sdk")

    def test_un_sdk_ilegible_no_carga(self):
        write(self.root, "roto", sdk='"cualquiera"')
        self.assert_no_carga("roto", "sdk")

    def test_un_toml_roto_no_carga(self):
        d = write(self.root, "roto")
        (d / "pack.toml").write_text("id = = 3", encoding="utf-8")
        self.assert_no_carga("roto", "no se puede leer")

    def test_dice_todo_lo_que_falla_a_la_vez(self):
        write(self.root, "roto", version="1", sdk=None, extra='[ports]\n"otro.t" = "rojo"')
        self.assert_no_carga("roto", "semver", "falta sdk", "no empieza por", "#rrggbb")

    def test_el_manifiesto_completo_se_lee(self):
        write(self.root, "lleno", requires={"bueno": ">=1.0,<2"}, extra=textwrap.dedent('''
            author = "Yo"
            description = "Todo"
            [python]
            dependencies = ["numpy>=2,<3", "scikit-learn"]
            modules = ["sklearn"]
            [ports]
            "lleno.t" = "#1f7a8c"
            [ui]
            entry = "ui/index.html"
        '''))
        m = packs.read_manifest(self.root / "lleno")
        self.assertEqual((m.author, m.description, m.ui), ("Yo", "Todo", "ui/index.html"))
        self.assertEqual(m.dependencies, ("numpy>=2,<3", "scikit-learn"))
        self.assertEqual(m.modules, ("sklearn",))
        self.assertEqual(m.ports, {"lleno.t": "#1f7a8c"})
        self.assertEqual(m.requires, {"bueno": ">=1.0,<2"})
        (self.root / "lleno" / "ui").mkdir()                 # [ui] entry tiene que estar (P61)
        (self.root / "lleno" / "ui" / "index.html").write_text("<p></p>", encoding="utf-8")
        reg, info, _ = load(self.root)
        self.assertIsNone(info["lleno"].error)

    def test_ui_fuera_del_paquete_no_carga(self):
        write(self.root, "roto", extra='[ui]\nentry = "../fuera.html"')
        self.assert_no_carga("roto", "[ui] entry")

    def test_el_catalogo_manda_el_color_del_ports(self):
        # Colores de puerto (§10, P67): la interfaz pinta el tipo del color de su paquete; sin
        # él, `null`, y la interfaz usa su paleta.
        write(self.root, "pintado", extra='[ports]\n"pintado.t" = "#1f7a8c"')
        reg, info, _ = load(self.root)
        self.assertIsNone(info["pintado"].error)
        ports = reg.describe()["ports"]
        self.assertEqual(ports["pintado.t"], {"label": "t", "color": "#1f7a8c"})
        self.assertEqual(ports["bueno.t"], {"label": "t", "color": None})
        self.assertIsNone(ports["cad.modelo"]["color"])

    def test_un_color_de_un_tipo_que_no_registra_no_carga(self):
        write(self.root, "roto", extra='[ports]\n"roto.otro" = "#1f7a8c"')
        self.assert_no_carga("roto", "[ports] roto.otro", "no registra")


class Dependencias(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_una_dependencia_que_falta_impide_cargar(self):
        write(self.root, "usa", requires={"base": ">=0.1"})
        write(self.root, "suelto")
        reg, info, _ = load(self.root)
        self.assertNotIn("usa.b", reg)
        self.assertIn("falta el paquete base", info["usa"].error)
        self.assertIn("suelto.b", reg)

    def test_una_dependencia_de_otra_version_impide_cargar(self):
        write(self.root, "base", version="0.3.0")
        write(self.root, "usa", requires={"base": ">=0.1,<0.2"})
        reg, info, _ = load(self.root)
        self.assertIn("base.b", reg)
        self.assertNotIn("usa.b", reg)
        self.assertIn("pide base >=0.1,<0.2 y está la 0.3.0", info["usa"].error)

    def test_una_dependencia_rota_arrastra_a_quien_la_pide_y_a_los_de_detras(self):
        write(self.root, "base", body="raise ImportError('rota')\n")
        write(self.root, "medio", requires={"base": ">=1.0"})
        write(self.root, "arriba", requires={"medio": ">=1.0"})
        reg, info, _ = load(self.root)
        for pid in ("base", "medio", "arriba"):
            self.assertIsNotNone(info[pid].error, pid)
            self.assertFalse([k for k in reg if k.startswith(pid + ".")])
        self.assertIn("base", info["medio"].error)
        self.assertIn("medio", info["arriba"].error)

    def test_una_dependencia_con_el_manifiesto_roto_arrastra_a_quien_la_pide(self):
        write(self.root, "base", version="1")
        write(self.root, "usa", requires={"base": ">=1.0"})
        reg, info, _ = load(self.root)
        self.assertNotIn("usa.b", reg)
        self.assertIsNotNone(info["usa"].error)

    def test_se_carga_despues_de_lo_que_pide(self):
        # «aaa» va antes por nombre, pero importa el código de «zzz» al cargarse (P23)
        write(self.root, "zzz", body=BODY.format(id="zzz", title="Z") + "\nVALOR = 42\n")
        write(self.root, "aaa", requires={"zzz": ">=1.0"}, body='''
            from pizarra_packs.zzz.blocks import VALOR

            def register(pack):
                pack.block("aaa.b", f"A{VALOR}", lambda p, i, c: {}, inputs={"i": "zzz.t"})
        ''')
        reg, info, _ = load(self.root)
        self.assertIsNone(info["aaa"].error)
        self.assertEqual(reg["aaa.b"].title, "A42")

    def test_un_ciclo_es_un_error_de_los_del_ciclo_y_solo_de_ellos(self):
        write(self.root, "uno", requires={"dos": ">=1.0"})
        write(self.root, "dos", requires={"tres": ">=1.0"})
        write(self.root, "tres", requires={"uno": ">=1.0"})
        write(self.root, "fuera")
        write(self.root, "detras", requires={"uno": ">=1.0"})
        reg, info, _ = load(self.root)
        for pid in ("uno", "dos", "tres"):
            self.assertIn("ciclo de dependencias entre dos, tres, uno", info[pid].error)
        self.assertNotIn("ciclo", info["detras"].error, "no está en el ciclo: cae porque cae uno")
        self.assertIsNone(info["fuera"].error)
        self.assertEqual(sorted(reg), ["fuera.b"])

    def test_pedirse_a_si_mismo_es_un_error_del_manifiesto(self):
        write(self.root, "solo", requires={"solo": ">=1.0"})
        _, info, _ = load(self.root)
        self.assertIn("no es el id de otro paquete", info["solo"].error)

    def test_si_cae_por_sus_puertos_cae_tambien_quien_lo_pide(self):
        # «base» importa bien pero usa un tipo que nadie registra: cae en la segunda vuelta
        write(self.root, "base", body='''
            def register(pack):
                pack.block("base.b", "B", lambda p, i, c: {}, inputs={"i": "nadie.t"})
        ''')
        write(self.root, "usa", requires={"base": ">=1.0"})
        reg, info, _ = load(self.root)
        self.assertIsNotNone(info["base"].error)
        self.assertIn("base", info["usa"].error)
        self.assertEqual(list(reg), [])


class Validacion(unittest.TestCase):
    """P30, FF 10.2: la carga aplica la validación estática (§1) antes de importar nada."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_uno_que_no_pasa_no_carga_ni_se_importa_y_los_demas_si(self):
        pid = "sin_validar"                 # un id que ningún otro test importa en este proceso
        write(self.root, pid, body="from pizarra import board\n" + BODY.format(id=pid, title="B"))
        write(self.root, "suelto")
        reg, info, logs = load(self.root)
        self.assertNotIn(f"{pid}.b", reg)
        self.assertIn("no pasa la validación", info[pid].error)
        self.assertIn("blocks.py:1: pizarra: importa el backend de la app", info[pid].error)
        self.assertNotIn(f"pizarra_packs.{pid}.blocks", sys.modules)
        self.assertTrue(any(f"{pid}: no se carga" in m for m in logs))
        self.assertIn("suelto.b", reg)

    def test_quien_pide_uno_que_no_pasa_tampoco_carga(self):
        write(self.root, "base", body="import numpy\n" + BODY.format(id="base", title="B"))
        write(self.root, "usa", requires={"base": ">=1.0"})
        reg, info, _ = load(self.root)
        self.assertIn("la librería numpy no está", info["base"].error)
        self.assertNotIn("usa.b", reg)
        self.assertIn("no se carga base", info["usa"].error)

    def test_lo_de_fusion_se_sigue_en_el_paquete_que_se_carga_de_otro_origen(self):
        # base está en otra carpeta que usa: la validación la busca donde la encuentra la
        # carga, no al lado (P37)
        dev, user = self.root / "dev", self.root / "user"
        base = write(dev, "base")
        (base / "calc.py").write_text("import math\n", encoding="utf-8")
        usa = write(user, "usa", requires={"base": ">=1.0"})
        (usa / "fusion").mkdir()
        (usa / "fusion" / "build.py").write_text("from pizarra_packs.base import calc\n",
                                                 encoding="utf-8")
        reg, info, _ = load(("desarrollo", dev), ("usuario", user))
        self.assertIsNone(info["usa"].error)
        self.assertIn("usa.b", reg)
        (base / "calc.py").write_text("import numpy\n", encoding="utf-8")
        reg, info, _ = load(("desarrollo", dev), ("usuario", user))
        self.assertIn("alcanza base/calc.py, que no se puede usar en Fusion", info["usa"].error)

    def test_con_muchos_problemas_dice_los_primeros_y_cuantos_mas(self):
        bad = "".join(f"import lib{k}\n" for k in range(packs.MAX_SHOWN + 2))
        write(self.root, "roto", body=bad + BODY.format(id="roto", title="B"))
        _, info, _ = load(self.root)
        self.assertIn("lib0", info["roto"].error)
        self.assertNotIn(f"lib{packs.MAX_SHOWN}", info["roto"].error)
        self.assertIn("y 2 más", info["roto"].error)


class Prioridad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.dev, self.ws, self.user = root / "dev", root / "ws", root / "user"
        for d in (self.dev, self.ws, self.user):
            d.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def origins(self, dev=True):
        env = {packs.DEV_ENV: str(self.dev)} if dev else {packs.DEV_ENV: ""}
        out = packs.default_origins(user_dir=self.user, workspace_dir=self.ws, environ=env)
        return out if dev else [o for o in out if o[0] != "desarrollo"]

    def test_manda_el_del_workspace_sobre_el_del_usuario(self):
        write(self.user, "p", title="del usuario")
        write(self.ws, "p", title="del workspace")
        reg = packs.load(self.origins(dev=False), log=lambda m: None)
        self.assertEqual(reg["p.b"].title, "del workspace")
        info = {p.id: p for p in reg.packs}["p"]
        self.assertEqual((info.origin, info.shadowed), ("workspace", ["usuario"]))
        self.assertEqual(Path(info.path), self.ws / "p")

    def test_manda_el_de_desarrollo_sobre_los_dos(self):
        write(self.user, "p", title="del usuario")
        write(self.ws, "p", title="del workspace")
        write(self.dev, "p", title="de desarrollo")
        reg = packs.load(self.origins(), log=lambda m: None)
        self.assertEqual(reg["p.b"].title, "de desarrollo")
        info = {p.id: p for p in reg.packs}["p"]
        self.assertEqual((info.origin, info.shadowed), ("desarrollo", ["workspace", "usuario"]))
        self.assertEqual(reg.describe()["packs"][0]["shadowed"], ["workspace", "usuario"])

    def test_manda_aunque_el_de_mas_prioridad_este_roto(self):
        # el que se usa es el de más prioridad, roto o no: nunca se cae al otro sin avisar
        write(self.user, "p", title="del usuario")
        write(self.ws, "p", version="1")
        reg = packs.load(self.origins(dev=False), log=lambda m: None)
        self.assertNotIn("p.b", reg)
        self.assertEqual({p.id: p for p in reg.packs}["p"].origin, "workspace")

    def test_cada_uno_de_su_origen(self):
        write(self.user, "u")
        write(self.ws, "w", requires={"u": ">=1.0"})
        reg = packs.load(self.origins(dev=False), log=lambda m: None)
        self.assertEqual(sorted(reg), ["u.b", "w.b"])
        self.assertEqual({p.id: p.origin for p in reg.packs}, {"u": "usuario", "w": "workspace"})

    def test_varias_carpetas_de_desarrollo_por_la_variable(self):
        otra = Path(self.tmp.name) / "otra"
        out = packs.default_origins(environ={packs.DEV_ENV: os.pathsep.join([str(self.dev), str(otra)])})
        self.assertEqual(out[:2], [("desarrollo", self.dev), ("desarrollo", otra)])

    def test_sin_la_variable_nunca_se_carga_packs_del_repo(self):
        # P81: la carga no conoce el repo; lo pone el arranque de desarrollo
        out = packs.default_origins(user_dir=self.user, workspace_dir=self.ws,
                                    environ={packs.DEV_ENV: "  "})
        self.assertEqual(out, [("workspace", self.ws), ("usuario", self.user)])
        self.assertEqual(packs.default_origins(environ={}), [])

    def test_empaquetada_solo_usuario_y_workspace_aunque_este_la_variable(self):
        # P11, P81: la app no trae paquetes (sin origen «incluido») y desarrollo no cuenta
        with mock.patch.object(packs.sys, "frozen", True, create=True), \
                mock.patch.object(packs.sys, "_MEIPASS", str(self.tmp.name), create=True):
            out = packs.default_origins(user_dir=self.user, workspace_dir=self.ws,
                                        environ={packs.DEV_ENV: str(self.dev)})
        self.assertEqual(out, [("workspace", self.ws), ("usuario", self.user)])


class RegistroDeLaApp(unittest.TestCase):
    """`blocks.configure`: la app carga también los paquetes del usuario y del workspace."""

    def setUp(self):
        from pizarra import blocks
        self.blocks = blocks
        self.saved = blocks.REGISTRY
        self.tmp = tempfile.TemporaryDirectory()
        self.user, self.ws = Path(self.tmp.name) / "user", Path(self.tmp.name) / "ws"

    def tearDown(self):
        self.blocks.REGISTRY = self.saved
        self.tmp.cleanup()

    def test_sin_paquetes_del_usuario_ni_del_workspace_no_recarga(self):
        reg = self.blocks.configure(user_dir=self.user, workspace_dir=self.ws)
        self.assertIs(reg, self.saved)
        self.assertIn(("usuario", str(self.user)), reg.origins)

    @necesita_paquetes
    def test_con_paquetes_carga_los_suyos_y_manda_el_del_workspace(self):
        write(self.user, "extra", title="del usuario")
        write(self.ws, "extra", title="del workspace")
        reg = self.blocks.configure(user_dir=self.user, workspace_dir=self.ws)
        self.assertIsNot(reg, self.saved)
        self.assertEqual(reg["extra.b"].title, "del workspace")
        self.assertIn("demo.tubo", reg, "los de desarrollo siguen")
        # una pizarra nueva usa el registro recargado; el proceso de cálculo carga lo mismo
        from tests.helpers import new_board
        self.assertIs(new_board().registry, reg)
        again = packs.load(reg.dirs, log=lambda m: None)
        self.assertEqual(again["extra.b"].title, "del workspace")


class Huella(unittest.TestCase):
    def test_cambia_con_el_contenido_y_no_con_pycache(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write(tmp, "p")
            h0 = packs.digest(d)
            (d / "__pycache__").mkdir()
            (d / "__pycache__" / "blocks.cpython-313.pyc").write_bytes(b"x")
            (d / "ui-src").mkdir()
            (d / "ui-src" / "main.ts").write_text("x", encoding="utf-8")
            self.assertEqual(packs.digest(d), h0)
            (d / "blocks.py").write_text("# otro\n", encoding="utf-8")
            self.assertNotEqual(packs.digest(d), h0)

    def test_la_carga_la_apunta(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = write(tmp, "p")
            reg = packs.load([tmp], log=lambda m: None)
            self.assertEqual(reg.packs[0].digest, packs.digest(d))


if __name__ == "__main__":
    unittest.main()
