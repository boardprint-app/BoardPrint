"""El núcleo nunca nombra un paquete (docs/PLAN_PAQUETES.md §10 «Núcleo sin dominio», P18, P38).

Regla: el código del núcleo (el backend `pizarra`, el SDK y el motor `pizarra_engine`) no
importa ni nombra un paquete: ni un `import` suyo, ni un nombre (`fusion_sync`), ni un texto
que lo nombre (`"fusion.pull"`). Lo que hace falta de un paquete llega por lo que declara
(`pack.connector`, `pack.action`, `formerly=`…). Los comentarios y los docstrings sí pueden
citarlo (explican, no dependen), y un texto para el usuario puede hablar del programa
(«Fusion no responde»): el programa no es el paquete, y tampoco su API (`adsk.fusion`, que
usan `fusion_io` y las piezas de `parts/`, P15).

Las excepciones van en `ALLOWED`, cada una con su motivo. El test entró en FF 10.8 con
`fusion`; FF 10.2 añadió los nombres de robótica y terminales y el motor entero (`core` y
`parts`), y FF 10.9 añade el frontend (P67): aquí sus `.css` (ninguna clase ni variable lleva un
paquete como palabra: `.block-open-fusion`), y su TypeScript en `app/frontend/src/nucleo.test.ts`,
con el parser de TypeScript, que entiende el JSX.

Ejecutar desde app/backend:  python -m unittest tests.test_nucleo_sin_dominio -v
"""
import ast
import re
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
ROOTS = [BACKEND / "pizarra", BACKEND / "boardprint_sdk", REPO / "engine" / "pizarra_engine"]

# Los paquetes que el núcleo no nombra (§10), y lo suyo que más se nombraba (el tipo de la
# brida, los motores de robótica y terminales).
NAMES = ("fusion", "robotica", "robotica_base", "terminales", "brida", "robotarm", "terminals")
_ALT = "|".join(NAMES)
# En un import o un nombre: el paquete como pieza (`fusion_sync`, `pizarra_packs.fusion`).
WORD_RE = re.compile(r"(^|[._])(" + _ALT + r")($|[._])", re.IGNORECASE)
# En un texto: el id del paquete o algo suyo (`"fusion"`, `"fusion.pull"`, `pizarra_packs.fusion`).
TEXT_RE = re.compile(r"^(" + _ALT + r")(\.[a-z_]+)*$|pizarra_packs\.(" + _ALT + r")\b")

# {fichero relativo al repo: (lo que puede nombrar, motivo)}; "*": todo el fichero.
FUSION_IO = ("P15: `pizarra_engine.core.fusion_io`, lo común de la API de Fusion (el programa), "
             "no el paquete")
ALLOWED = {
    "app/backend/pizarra/pack_validate.py": (
        {"fusion", "FUSION_DIR", "fusion_bad", "in_fusion"},
        "P15: la carpeta `fusion/` de cualquier paquete (lo que corre dentro de Fusion), no el "
        "paquete `fusion`"),
    "engine/pizarra_engine/core/runner.py": ({"pizarra_engine.core.fusion_io", "fusion_io"}, FUSION_IO),
    "engine/pizarra_engine/core/sweep.py": ({"pizarra_engine.core.fusion_io", "fusion_io"}, FUSION_IO),
    "engine/pizarra_engine/core/params.py": ({"FUSION_UNITS"}, "P15: las unidades de la API de Fusion"),
}


def _docstrings(tree):
    """Los textos que son docstrings: en ellos se puede citar un paquete."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


API = "adsk"     # la API de Fusion (el programa, P15): `adsk.fusion` no es el paquete `fusion`


def _is_api(module):
    return module == API or module.startswith(API + ".")


def names_of(path):
    """`[(línea, lo que nombra)]`: imports, nombres y textos del código que citan un paquete."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docs and TEXT_RE.search(node.value):
                found.append((node.lineno, node.value))
            continue
        if isinstance(node, ast.Import):
            words = [a.name for a in node.names if not _is_api(a.name)] \
                + [a.asname or "" for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if _is_api(node.module or ""):
                continue
            words = ([node.module or ""] + [a.name for a in node.names]
                     + [a.asname or "" for a in node.names])
        elif isinstance(node, ast.Name):
            words = [node.id]
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == API:
                continue                       # adsk.fusion.Design: la API, no el paquete
            words = [node.attr]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            words = [node.name]
        elif isinstance(node, ast.arg):
            words = [node.arg]
        else:
            continue
        found += [(getattr(node, "lineno", 0), w) for w in words if w and WORD_RE.search(w)]
    return found


FRONTEND = REPO / "app" / "frontend" / "src"
CSS_NAME_RE = re.compile(r"-?[A-Za-z_][\w-]*")


def css_names_of(text):
    """`[(línea, nombre)]` de un `.css`: clases, variables y valores con un paquete como palabra
    (`block-open-fusion`), fuera de los comentarios."""
    clean = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)
    return [(i, m.group()) for i, line in enumerate(clean.split("\n"), 1)
            for m in CSS_NAME_RE.finditer(line)
            if any(w in NAMES for w in re.split(r"[-_]+", m.group()))]


class NucleoSinDominio(unittest.TestCase):
    def test_el_css_del_frontend_nunca_nombra_un_paquete(self):
        bad = [f"{p.relative_to(REPO).as_posix()}:{line}: {word!r}"
               for p in sorted(FRONTEND.rglob("*.css"))
               for line, word in css_names_of(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [], "una clase del núcleo nombra un paquete")

    def test_la_regla_del_css_ve_lo_que_tiene_que_ver(self):
        css = "/* .fusion, un comentario */\n.block-open-fusion:hover { --c: #fff; }\n.terminal { }"
        self.assertEqual(css_names_of(css), [(2, "block-open-fusion")])

    def test_el_nucleo_nunca_nombra_un_paquete(self):
        bad = []
        for root in ROOTS:
            for path in sorted(root.rglob("*.py")):
                rel = path.relative_to(REPO).as_posix()
                allowed = ALLOWED.get(rel, (set(), ""))[0]
                bad += [f"{rel}:{line}: {word!r}" for line, word in names_of(path)
                        if word not in allowed and "*" not in allowed]
        self.assertEqual(bad, [], "el núcleo nombra un paquete; si es a propósito, va en "
                                  "ALLOWED con su motivo")

    def test_la_regla_ve_lo_que_tiene_que_ver(self):
        tmp = BACKEND / "tests" / "_nombra_un_paquete.tmp.py"
        tmp.write_text('"""Cita fusion en el docstring: vale."""\n'
                       "# y en un comentario: fusion\n"
                       "from pizarra_packs.fusion import fusion_sync\n"
                       'ACCION = "fusion.pull"\n'
                       'TEXTO = "Fusion no responde: ábrelo"\n'
                       "def ver(conector=None):\n    return conector\n"
                       "import adsk.fusion\nfrom adsk.fusion import Design\n"
                       "O = adsk.fusion.DimensionOrientations\n"
                       "from pizarra_packs.robotica_base import flange\n"
                       'PUERTO = "robotica_base.brida"\n'
                       "from pizarra_engine.robotarm import model\n", encoding="utf-8")
        self.addCleanup(tmp.unlink)
        words = [w for _, w in names_of(tmp)]
        self.assertEqual(sorted(words), ["fusion.pull", "fusion_sync", "pizarra_engine.robotarm",
                                         "pizarra_packs.fusion", "pizarra_packs.robotica_base",
                                         "robotica_base.brida"])

    def test_cada_excepcion_dice_por_que_y_sigue_haciendo_falta(self):
        for rel, (allowed, why) in ALLOWED.items():
            with self.subTest(rel=rel):
                self.assertTrue(why.strip())
                used = {w for _, w in names_of(REPO / rel)}
                self.assertTrue(used if "*" in allowed else allowed & used,
                                f"{rel} ya no usa {sorted(allowed)}: quítalo")


if __name__ == "__main__":
    unittest.main()
