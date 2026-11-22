"""Herramientas de Microsoft 365 del agente (docs/PLAN_M365.md §7, §9: M5, M11).

Reglas: son exactamente buscar, traer y redactar (ninguna envía, borra ni sube); sin sesión de
Microsoft ninguna llama a Graph y el error dice cómo iniciarla; los adjuntos de un borrador son
tarjetas de archivo de la pizarra, nunca una ruta ni una carpeta; con *Excluir adjuntos*, buscar
no da el principio de los correos; lo que trae el agente queda con su autoría.

Ejecutar desde app/backend:  python -m unittest tests.test_agent_m365_tools -v
"""
import json
import unittest
from pathlib import Path

from pizarra import agent_m365_tools as tools
from pizarra.agent import AGENT

from tests.helpers import new_board
from tests.test_m365_files import FakeGraph
from tests.test_m365_mail import FakeMailGraph


def payload(result):
    return json.loads(result["content"][0]["text"])


class NoAuth:
    def configured(self):
        return True

    def account(self):
        return None


class Lista(unittest.TestCase):
    def test_exactamente_tres_y_ninguna_envia(self):
        self.assertEqual(set(tools.NAMES),
                         {"buscar_microsoft365", "traer_de_microsoft365", "redactar_correo"})
        for name in tools.NAMES:
            self.assertNotIn("enviar", name)
            self.assertNotIn("send", name)


class SinSesion(unittest.TestCase):
    def tearDown(self):
        tools.use(None)

    def test_ninguna_llama_a_graph(self):
        tools.use(NoAuth())
        board = new_board()
        r = tools.tool_buscar(board, {"fuente": "correo"})
        self.assertTrue(r.get("is_error"))
        self.assertIn("Ajustes", r["content"][0]["text"])
        r, new = tools.tool_traer(board, {"fuente": "archivos", "id": "x"})
        self.assertTrue(r.get("is_error"))
        self.assertEqual(new, [])
        self.assertTrue(tools.tool_redactar(board, {"para": ["a@b.com"], "asunto": "x",
                                                    "cuerpo": "y"}).get("is_error"))

    def test_sin_registro(self):
        tools.use(None)
        r = tools.tool_buscar(new_board(), {"fuente": "correo"})
        self.assertTrue(r.get("is_error"))


class ConGraph(unittest.TestCase):
    def setUp(self):
        self.board = new_board()

    def test_traer_archivo_del_agente(self):
        g = FakeGraph()
        g.add("i1", "Cálculo.xlsx", b"x")
        r, new = tools.tool_traer(self.board, {"fuente": "archivos", "id": "i1", "drive_id": "d1"},
                                  graph=g)
        self.assertFalse(r.get("is_error"))
        self.assertEqual(new[0]["customData"]["author"], AGENT)
        self.assertEqual(payload(r)["tarjetas"][0]["archivo"], "Cálculo.xlsx")

    def test_excluir_adjuntos_quita_el_principio(self):
        class G:
            def get(self, path, **kw):
                return {"value": [{"id": "m1", "subject": "S", "bodyPreview": "secreto"}]}
        r = tools.tool_buscar(self.board, {"fuente": "correo"}, excluded=True, graph=G())
        self.assertNotIn("preview", payload(r)["resultados"][0])
        r = tools.tool_buscar(self.board, {"fuente": "correo"}, graph=G())
        self.assertEqual(payload(r)["resultados"][0]["preview"], "secreto")

    def test_borrador_solo_con_tarjetas_de_archivo(self):
        g = FakeGraph()
        g.add("i1", "informe.pdf", b"%PDF")
        _, new = tools.tool_traer(self.board, {"fuente": "archivos", "id": "i1", "drive_id": "d1"},
                                  graph=g)
        mail = FakeMailGraph()
        r = tools.tool_redactar(self.board, {"para": ["ana@ejemplo.com"], "asunto": "Informe",
                                             "cuerpo": "Adjunto", "adjuntos": [new[0]["id"]]},
                                graph=mail)
        self.assertFalse(r.get("is_error"), r)
        self.assertEqual(payload(r)["web_link"], "https://outlook.live.com/borrador1")
        create = next(c for c in mail.calls if c[0] == "POST")[2]
        self.assertEqual([a["name"] for a in create["attachments"]], ["informe.pdf"])
        bad = tools.tool_redactar(self.board, {"para": ["ana@ejemplo.com"], "asunto": "x",
                                               "cuerpo": "y", "adjuntos": [str(Path("C:/x.txt"))]},
                                  graph=FakeMailGraph())
        self.assertTrue(bad.get("is_error"))


if __name__ == "__main__":
    unittest.main()
