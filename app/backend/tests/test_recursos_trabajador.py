"""El trabajador de paquetes de la app instalada lleva solo los ficheros de `pizarra` que
`tauri.conf.json` copia como recursos (PLAN_PAQUETES P93). Regla: todo módulo de `pizarra` que
importan esos ficheros está en la lista, aunque se añada uno nuevo; si no, el trabajador
instalado no arranca (pasó con `pack_locales`, O15). También los imports de dentro de una
función: `packs.load` importa `library_schema` al cargar y el instalador de v0.2.0 no arrancaba
(PLAN_PUBLICACION §4.5). Las excepciones, con su motivo, en `SOLO_BACKEND`.

Ejecutar desde app/backend:  python -m unittest tests.test_recursos_trabajador -v
"""
import ast
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CONF = BACKEND.parent / "shell" / "src-tauri" / "tauri.conf.json"
# Imports de dentro de una función que solo corren en el backend, nunca en el trabajador.
SOLO_BACKEND = {
    "files": {"i18n"},   # `_t`: los mensajes que traduce solo los da el backend (files.py)
    "packs": {"pack_host"},   # `Registry.host`: el trabajador ejecuta él mismo, nunca lo pide
}


def worker_modules():
    """Los módulos de `pizarra` que van al trabajador: {nombre}."""
    resources = json.loads(CONF.read_text(encoding="utf-8"))["bundle"]["resources"]
    return {Path(dst).stem for dst in resources.values() if dst.startswith("worker/pizarra/")}


def top_level_imports(path, nodes=None):
    """Los módulos de `pizarra` que importa `path` al cargarse (no los de dentro de funciones)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in (tree.body if nodes is None else nodes):   # solo el nivel del módulo
        if isinstance(node, ast.ImportFrom) and node.module == "pizarra":
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("pizarra."):
            found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            found |= {a.name.split(".")[1] for a in node.names if a.name.startswith("pizarra.")}
    return found


class RecursosDelTrabajador(unittest.TestCase):
    def test_lo_que_importan_los_modulos_del_trabajador_va_con_ellos(self):
        shipped = worker_modules()
        self.assertIn("packs", shipped)
        missing = {}
        for name in shipped - {"__init__"}:
            lacking = top_level_imports(BACKEND / "pizarra" / f"{name}.py") - shipped
            if lacking:
                missing[name] = sorted(lacking)
        self.assertEqual(missing, {})

    def test_el_trabajador_solo_importa_de_pizarra_lo_que_va_en_los_recursos(self):
        worker = BACKEND / "boardprint_worker"
        shipped = worker_modules()
        lacking = set()
        for path in worker.glob("*.py"):
            lacking |= top_level_imports(path) - shipped
        self.assertEqual(lacking, set())

    def test_tampoco_falta_lo_que_importan_dentro_de_una_funcion(self):
        shipped = worker_modules()
        missing = {}
        for name in shipped - {"__init__"}:
            path = BACKEND / "pizarra" / f"{name}.py"
            todos = top_level_imports(path, list(ast.walk(ast.parse(path.read_text(encoding="utf-8")))))
            lacking = todos - shipped - SOLO_BACKEND.get(name, set())
            if lacking:
                missing[name] = sorted(lacking)
        self.assertEqual(missing, {})


if __name__ == "__main__":
    unittest.main()
