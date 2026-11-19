"""La copia de Issues al repo nuevo (docs/PLAN_PUBLICACION.md §4.5 paso 3, O18).

Reglas:
- Cada número del origen acaba en el mismo número del destino: un PR o un hueco del origen se
  rellena con una Issue cerrada, para que cada `Refs #N` de los commits siga apuntando a la suya.
- Se puede repetir si se corta: lo ya creado no se crea otra vez, solo se completa (cerrar y
  los comentarios que faltan).
- Un destino con algo que no casa (otro título en un número, un hueco, números de más) para
  todo antes de escribir.
- Al apuntar `.env` al destino, el token y las demás líneas no cambian.

Ejecutar desde app/backend:  python -m unittest tests.test_copiar_issues -v
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if not (REPO / "scripts" / "copiar_issues.py").is_file():     # el repo público no lo lleva
    raise unittest.SkipTest("sin scripts/copiar_issues.py")
sys.path.insert(0, str(REPO / "scripts"))
import copiar_issues as ci  # noqa: E402


def issue(n, titulo=None, estado="open", motivo=None, pr=False, comentarios=()):
    return {"number": n, "title": titulo or f"FF {n}", "body": f"cuerpo {n}", "state": estado,
            "state_reason": motivo, "is_pr": pr,
            "comments": [{"body": b, "created_at": f"2026-10-{10 + k}T21:00:00Z"}
                         for k, b in enumerate(comentarios)]}


def ya(n, titulo=None, estado="open", comentarios=0, pr=False):
    return {"number": n, "title": titulo or f"FF {n}", "state": estado, "is_pr": pr,
            "comments": comentarios}


class Planificar(unittest.TestCase):
    def test_destino_vacio_copia_cada_numero_con_su_estado_y_comentarios(self):
        plan = ci.planificar([issue(1, estado="closed", motivo="completed", comentarios=["Hecho"]),
                              issue(2)], [])
        self.assertEqual([c.numero for c in plan], [1, 2])
        self.assertTrue(all(c.crear for c in plan))
        self.assertEqual(plan[0].cerrar, "completed")
        self.assertIsNone(plan[1].cerrar)
        self.assertEqual(plan[0].comentarios, ["_Escrito el 2026-10-10._\n\nHecho"])
        self.assertEqual(plan[0].cuerpo, "cuerpo 1")

    def test_un_pr_o_un_hueco_del_origen_se_rellena_con_una_issue_cerrada(self):
        plan = ci.planificar([issue(1), issue(2, pr=True), issue(4)], [])
        self.assertEqual([c.numero for c in plan], [1, 2, 3, 4])
        for c in plan[1:3]:
            self.assertEqual(c.titulo, ci.HUECO_TITULO)
            self.assertEqual(c.cerrar, "not_planned")
        self.assertEqual(plan[3].titulo, "FF 4")

    def test_cerrada_sin_motivo_se_cierra_como_completada(self):
        plan = ci.planificar([issue(1, estado="closed", motivo=None)], [])
        self.assertEqual(plan[0].cerrar, "completed")

    def test_al_repetir_no_crea_lo_que_ya_esta_y_completa_lo_que_falta(self):
        origen = [issue(1, estado="closed", motivo="completed", comentarios=["a", "b"]),
                  issue(2, estado="closed", motivo="completed"), issue(3)]
        # El #1 se creó y recibió un comentario de dos; el #2 ya se cerró; el #3 no existe.
        plan = ci.planificar(origen, [ya(1, comentarios=1), ya(2, estado="closed")])
        self.assertEqual([(c.numero, c.crear) for c in plan], [(1, False), (2, False), (3, True)])
        self.assertEqual(plan[0].comentarios, ["_Escrito el 2026-10-11._\n\nb"])
        self.assertEqual(plan[0].cerrar, "completed")
        self.assertIsNone(plan[1].cerrar)

    def test_otro_titulo_en_un_numero_ocupado_para_todo(self):
        with self.assertRaisesRegex(ValueError, "número 1"):
            ci.planificar([issue(1), issue(2)], [ya(1, titulo="Bienvenida automática")])

    def test_un_pr_en_el_destino_para_todo(self):
        with self.assertRaises(ValueError):
            ci.planificar([issue(1)], [ya(1, pr=True)])

    def test_destino_con_numeros_de_mas_o_con_huecos_para_todo(self):
        with self.assertRaisesRegex(ValueError, "no tiene"):
            ci.planificar([issue(1)], [ya(1), ya(2)])
        with self.assertRaisesRegex(ValueError, "huecos"):
            ci.planificar([issue(1), issue(2), issue(3)], [ya(1), ya(3)])


class Env(unittest.TestCase):
    def test_cambia_solo_las_claves_pedidas_y_anade_las_que_faltan(self):
        texto = ("# comentario\nGITHUB_TOKEN=secreto\nGITHUB_OWNER=viejo\n"
                 "GITHUB_OWNER_TYPE=user\nGITHUB_REPO=CAD-LLM\nOTRA=1\n")
        nuevo = ci.env_actualizado(texto, {"GITHUB_OWNER": "boardprint", "GITHUB_REPO": "BoardPrint",
                                           "GITHUB_OWNER_TYPE": "org",
                                           "GITHUB_PROJECT_NUMBER": "1"})
        self.assertEqual(nuevo, "# comentario\nGITHUB_TOKEN=secreto\nGITHUB_OWNER=boardprint\n"
                                "GITHUB_OWNER_TYPE=org\nGITHUB_REPO=BoardPrint\nOTRA=1\n"
                                "GITHUB_PROJECT_NUMBER=1\n")


if __name__ == "__main__":
    unittest.main()
