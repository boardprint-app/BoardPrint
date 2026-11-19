"""SDK de paquetes (docs/PLAN_PAQUETES.md §2, §10 «SDK», P22).

Regla: la superficie pública de `boardprint_sdk` (los nombres de `__all__`, las firmas y los
métodos públicos de cada uno) **no cambia sin subir la versión**: quitar o cambiar algo sube la
mayor, solo añadir sube la menor. Cada paquete de un usuario depende de ella (`sdk = ">=1.0,<2"`).
Un argumento nuevo **al final y con valor por defecto** es añadir (P55): toda llamada que
funcionaba sigue funcionando igual.

Si este test falla porque la superficie cambió a propósito: se sube `boardprint_sdk.__version__`
como toca, se apunta en su changelog y se copia aquí la superficie nueva
(`python -m tests.test_sdk` la imprime).

Ejecutar desde app/backend:  python -m unittest tests.test_sdk -v
"""
import inspect
import json
import unittest

import boardprint_sdk
from boardprint_sdk import library as sdk_library
from boardprint_sdk import packs as sdk_packs
from pizarra import packs
from pizarra.pack_versions import parse_version

# La superficie publicada, con la versión que la publicó.
PUBLISHED_VERSION = "1.5.0"
PUBLISHED = {
    "Action": {
        "__init__": "(name: str, run: object, description: str = '', pack: str = '') -> None"
    },
    "BlockType": {
        "__init__": "(kind: str, title: str, params: dict, inputs: dict, outputs: dict, run: object, requires: tuple = (), description: str = '', pack: str = '', pull: boardprint_sdk.packs.Pull | None = None, optional: tuple = (), fix: boardprint_sdk.packs.Fix | None = None, preview: object = None, connector: str = '', formerly: tuple = ()) -> None"
    },
    "ConfirmRequired": {
        "__init__": "(message, action, label)"
    },
    "Connector": {
        "__init__": "(id: str, title: str, available: object, launch: object = None, open_file: object = None, accepts: tuple = (), gives: tuple = (), config: dict = <factory>, card: bool = False, panel: bool = False, pack: str = '') -> None"
    },
    "Fix": {
        "__init__": "(port: str, field: str, via: str, label: str = 'Fijar') -> None"
    },
    "PackBuilder": {
        "__init__": "(pack_id)",
        "action": "(self, name, run, description='')",
        "block": "(self, kind, title, run, inputs=None, outputs=None, params=None, requires=(), description='', pull=None, optional=(), fix=None, preview=None, connector='', formerly=())",
        "connector": "(self, title, available, launch=None, open_file=None, accepts=(), gives=(), config=None, card=False, panel=False)",
        "port": "(self, type_, label)",
        "template": "(self, id_, title, blocks, links, description='')",
        "view": "(self, kind, card=('params', 'results'), panel=())"
    },
    "Param": {
        "__init__": "(default: object, unit: str = '', label: str = '', choices: tuple = (), widget: str = '', choice_labels: tuple = ()) -> None"
    },
    "PortType": {
        "__init__": "(type: str, label: str) -> None"
    },
    "Pull": {
        "__init__": "(classify: object = None, accept_port: str = '', accept_param: str = 'locks', self_param: str = '', accept: object = None) -> None"
    },
    "RunContext": {
        "__init__": "(block_id: str, workdir: pathlib.Path | None = None, connectors: dict = <factory>, options: dict = <factory>, project_name: str = '', sync_file: pathlib.Path | None = None, _progress: object = None, _cancelled: object = None, library: boardprint_sdk.library.Library | None = None) -> None",
        "add_postit": "(self, block_id, text, kind='nota', keys=())",
        "block": "(self, block_id)",
        "block_file": "(self, block_id, name)",
        "block_type": "(self, block_id)",
        "cancelled": "(self)",
        "clear_error": "(self, block_id, action)",
        "postits": "(self, block_id)",
        "progress": "(self, fraction=None, message='')",
        "set_params": "(self, block_id, params)",
        "sync_file_of": "(self, block_id)",
        "upstream": "(self, block_id, port)"
    },
    "Template": {
        "__init__": "(id: str, title: str, blocks: tuple, links: tuple, description: str = '', pack: str = '') -> None"
    },
    "View": {
        "__init__": "(card: object = ('params', 'results'), panel: object = ()) -> None"
    },
    "box": {
        "__init__": "(x0, y0, x1, y1, label='', tone='')"
    },
    "chart": {
        "__init__": "(x, y, curves, label='')"
    },
    "line": {
        "__init__": "(points, label='', tone='')"
    },
    "point": {
        "__init__": "(x, y, label='', tone='')"
    },
    "view2d": {
        "__init__": "(x, y, items, label='', y_down=False)"
    },
    "library.Ficha": {
        "__init__": "(key: str, type: str, status: str, path: pathlib.Path, data: dict = <factory>) -> None",
        "verified": "property"
    },
    "library.Library": {
        "__init__": "(root=None)",
        "load": "(self, key)",
        "records": "(self, type=None)",
        "stock": "(self, key)"
    },
    "library.current": {
        "__init__": "()"
    },
    "library.using": {
        "__init__": "(library)"
    }
}


def _sig(fn):
    # `pathlib.Path` se escribe `pathlib._local.Path` desde Python 3.13: no es un cambio del SDK
    return str(inspect.signature(fn)).replace("pathlib._local.", "pathlib.")


# Los módulos públicos del SDK: los de `packs` van por su nombre (`Param`) y los de los demás,
# con el módulo delante (`library.Library`, 1.5).
MODULES = {"": sdk_packs, "library.": sdk_library}


def surface():
    """{nombre: {miembro: firma}} de lo que exportan los módulos del SDK (`MODULES`)."""
    out = {}
    for prefix, module in MODULES.items():
        for name in sorted(module.__all__):
            obj = getattr(module, name)
            members = {"__init__": _sig(obj)}
            if inspect.isclass(obj):
                for m, fn in sorted(vars(obj).items()):
                    if not m.startswith("_") and (inspect.isfunction(fn) or isinstance(fn, property)):
                        members[m] = "property" if isinstance(fn, property) else _sig(fn)
            out[prefix + name] = members
    return out


def _params(sig):
    """`(a, b=1) -> None` → (["a", "b=1"], " -> None"): los parámetros de una firma escrita,
    separados por las comas de primer nivel (no las de un valor por defecto como `('a', 'b')`)."""
    depth, quote, cur, out = 0, None, "", []
    for i, ch in enumerate(sig):
        if quote:
            cur += ch
            if ch == quote and sig[i - 1] != "\\":
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "([{<":
            depth += 1
            if depth == 1:
                continue
        elif ch in ")]}>":
            depth -= 1
            if depth == 0:
                out.append(cur.strip())
                return [x for x in out if x], sig[i + 1:]
        elif ch == "," and depth == 1:
            out.append(cur.strip())
            cur = ""
            continue
        if depth >= 1:
            cur += ch
    raise ValueError(f"firma sin cerrar: {sig}")


def _extends(old, new):
    """`new` es `old` con argumentos nuevos al final, todos con valor por defecto (P55)."""
    (po, ro), (pn, rn) = _params(old), _params(new)
    extra = pn[len(po):]
    return (ro == rn and pn[:len(po)] == po and bool(extra)
            and not any(p.startswith("*") for p in po)
            and all("=" in p and not p.startswith("*") for p in extra))


def diff(old, new):
    """(quitado o cambiado, añadido): listas de `nombre.miembro`."""
    broken, added = [], []
    for name in sorted(set(old) | set(new)):
        o, n = old.get(name, {}), new.get(name, {})
        for m in sorted(set(o) | set(n)):
            if m not in n:
                broken.append(f"{name}.{m}")
            elif m not in o or (o[m] != n[m] and _extends(o[m], n[m])):
                added.append(f"{name}.{m}")
            elif o[m] != n[m]:
                broken.append(f"{name}.{m}")
    return broken, added


class Superficie(unittest.TestCase):
    def test_la_superficie_no_cambia_sin_subir_la_version(self):
        now = parse_version(boardprint_sdk.__version__)
        published = parse_version(PUBLISHED_VERSION)
        broken, added = diff(PUBLISHED, surface())
        if broken:
            self.assertGreater(now[0], published[0],
                               f"cambia o quita {broken}: hay que subir la versión mayor del SDK")
        if added:
            self.assertGreater(now, published,
                               f"añade {added}: hay que subir al menos la versión menor del SDK")

    def test_la_regla_ve_un_cambio_de_firma_y_un_nombre_nuevo(self):
        # la propia comparación: una firma distinta rompe, un miembro nuevo solo añade
        new = json.loads(json.dumps(PUBLISHED))
        new["Param"]["__init__"] = "(default)"
        new["Param"]["nuevo"] = "(self)"
        self.assertEqual(diff(PUBLISHED, new), (["Param.__init__"], ["Param.nuevo"]))

    def test_un_argumento_nuevo_al_final_con_defecto_solo_anade(self):
        # P55: `connector=` en `pack.block` no obliga a subir la mayor; lo demás sí rompe
        old = {"F": {"__init__": "(self, a, b=('x', 'y'), c=None) -> None"}}
        ok = ("(self, a, b=('x', 'y'), c=None, d='') -> None",
              "(self, a, b=('x', 'y'), c=None, d: dict = <factory>, e=1) -> None")
        broken = ("(self, a, b=('x', 'y'), c=None, d) -> None",          # sin defecto
                  "(self, a, d='', b=('x', 'y'), c=None) -> None",       # en medio
                  "(self, a, b=('x', 'y'), c=None, *args) -> None",      # no es un argumento
                  "(self, a, b=('x', 'y'), c=None, d='') -> int",        # devuelve otra cosa
                  "(self, a, b=('x',), c=None, d='') -> None",           # cambia un defecto
                  "(self, a, b=('x', 'y')) -> None")                     # quita uno
        for sig in ok:
            self.assertEqual(diff(old, {"F": {"__init__": sig}}), ([], ["F.__init__"]), sig)
        for sig in broken:
            self.assertEqual(diff(old, {"F": {"__init__": sig}}), (["F.__init__"], []), sig)

    def test_todo_lo_de_all_existe_y_nada_publico_se_queda_fuera(self):
        for module in MODULES.values():
            public = {n for n, v in vars(module).items()
                      if not n.startswith("_") and getattr(v, "__module__", None) == module.__name__}
            self.assertEqual(public, set(module.__all__), module.__name__)


class ElBackendUsaElSDK(unittest.TestCase):
    """El backend no tiene un contrato propio: lo que reexporta es el del SDK (un paquete y
    el backend ven las mismas clases, P22)."""

    def test_las_clases_del_backend_son_las_del_sdk(self):
        for name in sdk_packs.__all__:
            self.assertIs(getattr(packs, name), getattr(sdk_packs, name), name)

    def test_el_sdk_es_solo_stdlib(self):
        # viaja tal cual al entorno de paquetes (P19): no puede importar el backend
        import ast
        from pathlib import Path
        import sys
        for f in Path(sdk_packs.__file__).parent.glob("*.py"):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                         else [])
                for n in names:
                    self.assertIn(n.split(".")[0], sys.stdlib_module_names, f"{f.name}: {n}")


class OpcionesConEtiqueta(unittest.TestCase):
    """D181: la interfaz enseña la etiqueta y se guarda el valor."""

    def test_un_diccionario_da_las_opciones_y_sus_etiquetas(self):
        p = sdk_packs.Param("al6061", choices={"al6061": "Aluminio 6061", "s235": "Acero S235"})
        self.assertEqual(p.choices, ("al6061", "s235"))
        self.assertEqual(dict(p.choice_labels), {"al6061": "Aluminio 6061", "s235": "Acero S235"})

    def test_un_paquete_con_la_tupla_de_antes_sigue_valiendo(self):
        p = sdk_packs.Param("a", choices=("a", "b"))
        self.assertEqual(p.choices, ("a", "b"))
        self.assertEqual(p.choice_labels, ())

    def test_las_etiquetas_llegan_a_la_interfaz_y_al_trabajador(self):
        from pizarra import pack_data
        reg = packs.load([], log=lambda m: None)
        reg["x.b"] = sdk_packs.BlockType(
            "x.b", "B", {"m": sdk_packs.Param("a", choices={"a": "Alfa", "b": "Beta"})}, {}, {},
            run=lambda *a: {}, pack="x")
        self.assertEqual(reg.describe()["blocks"]["x.b"]["params"]["m"]["choice_labels"],
                         {"a": "Alfa", "b": "Beta"})
        back = pack_data.from_data(json.loads(json.dumps(pack_data.to_data(reg))))
        self.assertEqual(dict(back["x.b"].params["m"].choice_labels), {"a": "Alfa", "b": "Beta"})

    def test_una_etiqueta_para_un_valor_que_no_esta_se_rechaza(self):
        with self.assertRaises(ValueError) as cm:
            sdk_packs.Param("a", choices=("a",), choice_labels={"b": "Be"})
        self.assertIn("'b'", str(cm.exception))


if __name__ == "__main__":
    print(json.dumps(surface(), indent=4, ensure_ascii=False))
