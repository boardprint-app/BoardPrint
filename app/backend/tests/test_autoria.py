"""Autoría y estado de lo que manda el cliente (docs/PLAN_PIZARRA.md §3, D72, D73).

El cliente nunca se apropia de un autor de agente; cambiar el contenido (texto o tipo) de un
post-it o texto del agente lo pasa al usuario con `origin`; moverlo, redimensionarlo o cambiar
su estado no cambia el autor. Un agente nunca cambia el estado de un post-it.
Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import unittest

from pizarra import scene, validation
from tests.helpers import new_board

AGENT = "agent:design"


def agent_postit(board, text="Revisa la unión", kind="riesgo"):
    (el,) = board.agent_add_postit({"text": text, "kind": kind, "author": AGENT})
    return el


def edit(el, version_up=1, **cd):
    """El elemento como lo manda el cliente tras cambiarlo."""
    return {**el, "version": el["version"] + version_up,
            "customData": {**el["customData"], **cd}}


def current(board, eid):
    return next(e for e in board.elements if e["id"] == eid)


class AutorDesdeElCliente(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.p = agent_postit(self.b)

    def test_cambiar_el_texto_de_un_post_it_del_agente_lo_pasa_al_usuario_con_origin(self):
        _, rewritten = self.b.apply_client_elements([edit(self.p, text="Va atornillado")])
        cd = current(self.b, self.p["id"])["customData"]
        self.assertEqual((cd["author"], cd["origin"]), ("user", AGENT))
        self.assertEqual(cd["text"], "Va atornillado")
        self.assertEqual([e["id"] for e in rewritten], [self.p["id"]])

    def test_cambiar_el_tipo_tambien(self):
        self.b.apply_client_elements([edit(self.p, postitKind="pregunta")])
        cd = current(self.b, self.p["id"])["customData"]
        self.assertEqual((cd["author"], cd["origin"]), ("user", AGENT))

    def test_pegarle_una_imagen_tambien_es_cambiar_su_contenido(self):
        self.b.apply_client_elements([edit(self.p, image={"file": "ab" * 32 + ".png",
                                                           "width": 40, "height": 30})])
        cd = current(self.b, self.p["id"])["customData"]
        self.assertEqual((cd["author"], cd["origin"]), ("user", AGENT))
        self.assertEqual(cd["text"], self.p["customData"]["text"])

    def test_si_el_cliente_ya_lo_pasa_al_usuario_se_acepta_sin_reescribir(self):
        _, rewritten = self.b.apply_client_elements(
            [edit(self.p, text="Otro", author="user", origin=AGENT)])
        self.assertEqual(rewritten, [])
        self.assertEqual(current(self.b, self.p["id"])["customData"]["author"], "user")

    def test_mover_redimensionar_o_cambiar_el_estado_nunca_cambia_el_autor(self):
        moved = {**edit(self.p, state="aceptado"), "x": 500, "width": 300}
        _, rewritten = self.b.apply_client_elements([moved])
        cd = current(self.b, self.p["id"])["customData"]
        self.assertEqual(cd["author"], AGENT)
        self.assertNotIn("origin", cd)
        self.assertEqual(cd["state"], "aceptado")
        self.assertEqual(rewritten, [])

    def test_el_cliente_nunca_pone_un_autor_de_agente_en_un_elemento_del_usuario(self):
        rect = {"id": "r1", "type": "rectangle", "x": 0, "y": 0, "version": 1,
                "customData": {"author": "user"}}
        self.b.apply_client_elements([rect])
        _, rewritten = self.b.apply_client_elements([edit(rect, author=AGENT)])
        self.assertEqual(current(self.b, "r1")["customData"]["author"], "user")
        self.assertEqual(len(rewritten), 1)

    def test_ni_le_quita_el_autor_a_uno_del_agente_sin_cambiar_su_contenido(self):
        self.b.apply_client_elements([edit(self.p, author="user")])
        self.assertEqual(current(self.b, self.p["id"])["customData"]["author"], AGENT)

    def test_ni_cambia_el_origen_de_uno_editado(self):
        self.b.apply_client_elements([edit(self.p, text="Mío")])
        mine = current(self.b, self.p["id"])
        self.b.apply_client_elements([edit(mine, origin="agent:review")])
        self.assertEqual(current(self.b, self.p["id"])["customData"]["origin"], AGENT)

    def test_un_elemento_nuevo_con_autor_de_agente_es_del_usuario(self):
        pasted = {**self.p, "id": "copia", "version": 1}
        _, rewritten = self.b.apply_client_elements([pasted])
        cd = current(self.b, "copia")["customData"]
        self.assertEqual((cd["author"], cd["origin"]), ("user", AGENT))
        self.assertIn("copia", [e["id"] for e in rewritten])

    def test_un_texto_del_agente_editado_pasa_al_usuario(self):
        txt = {"id": "t1", "type": "text", "x": 0, "y": 0, "version": 1, "text": "Hola",
               "customData": {"author": AGENT}}
        self.b.agent_update_element(AGENT, txt)
        changed = {**current(self.b, "t1"), "text": "Hola, editado", "version": 9}
        self.b.apply_client_elements([changed])
        cd = current(self.b, "t1")["customData"]
        self.assertEqual((cd["author"], cd["origin"]), ("user", AGENT))

    def test_un_elemento_nuevo_sin_autor_se_deja_como_esta_y_es_del_usuario(self):
        _, rewritten = self.b.apply_client_elements(
            [{"id": "n1", "type": "ellipse", "x": 0, "y": 0, "version": 1}])
        self.assertEqual(rewritten, [])
        self.assertEqual(validation.element_author(current(self.b, "n1")), "user")

    def test_lo_que_ya_trae_autor_y_fecha_no_se_reescribe(self):
        _, rewritten = self.b.apply_client_elements(
            [{"id": "n2", "type": "ellipse", "x": 0, "y": 0, "version": 1,
              "customData": {"author": "user", "created": "2026-11-09T10:00:00+00:00"}}])
        self.assertEqual(rewritten, [])


class EstadoDelPostit(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.p = agent_postit(self.b)

    def test_un_agente_nunca_cambia_el_estado_tampoco_de_uno_suyo(self):
        with self.assertRaises(validation.ValidationError):
            self.b.agent_update_element(AGENT, edit(self.p, state="descartado"))
        self.assertEqual(current(self.b, self.p["id"])["customData"]["state"], "abierto")

    def test_un_agente_si_puede_cambiar_el_texto_de_uno_suyo(self):
        self.b.agent_update_element(AGENT, edit(self.p, text="Corregido"))
        self.assertEqual(current(self.b, self.p["id"])["customData"]["text"], "Corregido")

    def test_un_post_it_nuevo_nace_siempre_abierto(self):
        pasted = {**self.p, "id": "copia", "version": 1,
                  "customData": {**self.p["customData"], "state": "aceptado"}}
        self.b.apply_client_elements([pasted])
        self.assertEqual(current(self.b, "copia")["customData"]["state"], "abierto")
        el = self.b.user_add_postit("nota", 0, 0)
        self.assertEqual(el["customData"]["state"], "abierto")

    def test_descartar_nunca_lo_borra(self):
        self.b.apply_client_elements([edit(self.p, state="descartado")])
        el = current(self.b, self.p["id"])
        self.assertFalse(el.get("isDeleted"))
        self.assertEqual(el["customData"]["state"], "descartado")

    def test_un_estado_desconocido_del_cliente_no_se_guarda(self):
        self.b.apply_client_elements([edit(self.p, state="borrado")])
        self.assertEqual(current(self.b, self.p["id"])["customData"]["state"], "abierto")


if __name__ == "__main__":
    unittest.main()
