"""Propuestas del agente (docs/PLAN_PIZARRA.md §3, D20, D75).

Aceptar aplica solo lo propuesto (texto, tipo, parámetros o borrado), nunca posición, tamaño
ni estilo, y el elemento sigue siendo del usuario; una propuesta sobre un elemento editado
después nunca se aplica sin volver a verla (queda desfasada); rechazar nunca toca el elemento;
sobre algo del propio agente no hay propuesta: lo edita directamente.
Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import unittest

from pizarra import scene
from pizarra.validation import ValidationError
from tests.helpers import new_board, reopen, necesita_paquetes

AGENT = "agent:design"


def current(board, eid):
    return next(e for e in board.elements if e["id"] == eid)


class Base(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.tubo = scene.block_element("demo.tubo", 0, 0)
        self.b.apply_client_elements([self.tubo])
        self.nota = self.b.user_add_postit("nota", 0, 300)
        self.b.apply_client_elements([{**self.nota, "version": 2,
                                       "customData": {**self.nota["customData"], "text": "La pinza va a la brida"}}])

    def propose(self, target, change, reason="Concreta la brida", **kw):
        kind, p = self.b.agent_propose(AGENT, target, change, reason, **kw)
        self.assertEqual(kind, "propuesta")
        return p

    def view(self, pid):
        return next(v for v in self.b.proposals_view() if v["id"] == pid)


class CrearPropuesta(Base):
    def test_una_propuesta_no_toca_el_elemento_y_queda_pendiente(self):
        before = dict(current(self.b, self.nota["id"]))
        p = self.propose(self.nota["id"], {"text": "La pinza va a la brida ISO 9409-1-50-4-M6"})
        self.assertEqual(current(self.b, self.nota["id"]), before)
        v = self.view(p["id"])
        self.assertEqual((v["state"], v["stale"]), ("pendiente", False))
        self.assertEqual(v["current"], {"text": "La pinza va a la brida"})

    def test_nunca_posicion_tamano_ni_estilo(self):
        for change in ({"x": 5}, {"width": 10}, {"strokeColor": "#f00"}, {}, {"text": "a", "x": 1}):
            with self.assertRaises(ValidationError):
                self.b.agent_propose(AGENT, self.nota["id"], change, "porque sí")

    def test_cada_campo_solo_donde_tiene_sentido(self):
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.tubo["id"], {"text": "otro"}, "x")
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.nota["id"], {"params": {"L": 1}}, "x")
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.tubo["id"], {"params": {"inventado": 1}}, "x")
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.nota["id"], {"postitKind": "raro"}, "x")
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.nota["id"], {"delete": True, "text": "a"}, "x")

    def test_sin_motivo_o_sobre_algo_que_no_existe_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.nota["id"], {"text": "otro"}, "  ")
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, "no-existe", {"text": "otro"}, "x")

    def test_cifras_sin_fuente_se_rechazan_como_en_un_post_it(self):
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.nota["id"], {"text": "Flecha de 3 mm"}, "x")
        self.propose(self.nota["id"], {"text": "Unos 3 kg"}, estimate=True)

    def test_una_sola_pendiente_por_elemento(self):
        self.propose(self.nota["id"], {"text": "otro"})
        with self.assertRaises(ValidationError):
            self.b.agent_propose(AGENT, self.nota["id"], {"postitKind": "riesgo"}, "x")

    def test_sobre_algo_del_propio_agente_no_hay_propuesta_lo_edita(self):
        (mine,) = self.b.agent_add_postit({"text": "Revisa la unión", "kind": "riesgo", "author": AGENT})
        kind, el = self.b.agent_propose(AGENT, mine["id"], {"text": "Revisa la unión soldada"}, "x")
        self.assertEqual(kind, "aplicado")
        self.assertEqual(current(self.b, mine["id"])["customData"]["text"], "Revisa la unión soldada")
        self.assertEqual(self.b.proposals_view(), [])

    def test_se_guardan_y_vuelven_al_reabrir(self):
        p = self.propose(self.nota["id"], {"text": "otro"})
        self.b.save()
        self.assertEqual([v["id"] for v in reopen(self.b).proposals_view()], [p["id"]])


class AceptarYRechazar(Base):
    def test_aceptar_aplica_solo_el_texto_y_sigue_siendo_del_usuario(self):
        p = self.propose(self.nota["id"], {"text": "La pinza va a la brida ISO 9409-1-50-4-M6"})
        before = current(self.b, self.nota["id"])
        changed = self.b.accept_proposal(p["id"], self.view(p["id"])["current"])
        after = current(self.b, self.nota["id"])
        self.assertEqual(after["customData"]["text"], "La pinza va a la brida ISO 9409-1-50-4-M6")
        self.assertEqual(after["customData"]["author"], "user")
        for k in ("x", "y", "width", "height", "strokeColor", "backgroundColor"):
            self.assertEqual(after[k], before[k])
        self.assertGreater(after["version"], before["version"])
        self.assertEqual([e["id"] for e in changed], [self.nota["id"]])
        self.assertEqual(self.b.proposals_view(), [])

    def test_aceptar_el_tipo(self):
        p = self.propose(self.nota["id"], {"postitKind": "riesgo"})
        self.b.accept_proposal(p["id"], self.view(p["id"])["current"])
        self.assertEqual(current(self.b, self.nota["id"])["customData"]["postitKind"], "riesgo")

    @necesita_paquetes
    def test_aceptar_parametros_los_cambia_y_el_bloque_queda_por_ejecutar(self):
        self.b.run(self.tubo["id"])
        p = self.propose(self.tubo["id"], {"params": {"L": 250}})
        self.assertEqual(self.view(p["id"])["current"], {"params": {"L": 300}})
        self.b.accept_proposal(p["id"], self.view(p["id"])["current"])
        self.assertEqual(self.b.state[self.tubo["id"]]["params"]["L"], 250)
        self.assertEqual(self.b.statuses()[self.tubo["id"]], "desactualizado")

    def test_aceptar_un_borrado_lo_borra(self):
        p = self.propose(self.nota["id"], {"delete": True})
        self.b.accept_proposal(p["id"], self.view(p["id"])["current"])
        self.assertTrue(current(self.b, self.nota["id"])["isDeleted"])

    def test_rechazar_nunca_toca_el_elemento(self):
        p = self.propose(self.nota["id"], {"text": "otro"})
        before = dict(current(self.b, self.nota["id"]))
        self.b.reject_proposal(p["id"])
        self.assertEqual(current(self.b, self.nota["id"]), before)
        self.assertEqual(self.b.proposals_view(), [])
        with self.assertRaises(ValidationError):
            self.b.accept_proposal(p["id"], {"text": "La pinza va a la brida"})


class Desfasada(Base):
    def edit_text(self, text):
        n = current(self.b, self.nota["id"])
        self.b.apply_client_elements([{**n, "version": n["version"] + 1,
                                       "customData": {**n["customData"], "text": text}}])

    def test_editar_el_elemento_despues_la_deja_desfasada_y_no_se_aplica(self):
        p = self.propose(self.nota["id"], {"text": "La pinza va a la brida ISO"})
        seen = self.view(p["id"])["current"]
        self.edit_text("La pinza va atornillada")
        v = self.view(p["id"])
        self.assertTrue(v["stale"])
        self.assertEqual(v["current"], {"text": "La pinza va atornillada"})
        with self.assertRaises(ValidationError):
            self.b.accept_proposal(p["id"], seen)
        self.assertEqual(current(self.b, self.nota["id"])["customData"]["text"], "La pinza va atornillada")

    def test_vista_otra_vez_contra_lo_actual_si_se_aplica(self):
        p = self.propose(self.nota["id"], {"text": "La pinza va a la brida ISO"})
        self.edit_text("La pinza va atornillada")
        self.b.accept_proposal(p["id"], self.view(p["id"])["current"])
        self.assertEqual(current(self.b, self.nota["id"])["customData"]["text"], "La pinza va a la brida ISO")

    def test_moverlo_no_la_deja_desfasada(self):
        p = self.propose(self.nota["id"], {"text": "otro"})
        n = current(self.b, self.nota["id"])
        self.b.apply_client_elements([{**n, "x": 500, "version": n["version"] + 1}])
        self.assertFalse(self.view(p["id"])["stale"])

    def test_si_el_elemento_se_borra_no_se_ensena_y_vuelve_si_se_deshace(self):
        p = self.propose(self.nota["id"], {"text": "otro"})
        n = current(self.b, self.nota["id"])
        self.b.apply_client_elements([{**n, "isDeleted": True, "version": n["version"] + 1}])
        self.assertEqual(self.b.proposals_view(), [])
        n = current(self.b, self.nota["id"])
        self.b.apply_client_elements([{**n, "isDeleted": False, "version": n["version"] + 1}])
        self.assertEqual([v["id"] for v in self.b.proposals_view()], [p["id"]])


if __name__ == "__main__":
    unittest.main()
