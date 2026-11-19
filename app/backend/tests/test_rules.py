"""Reglas del plan de la pizarra (docs/PLAN_PIZARRA.md §10) que ya existen en el spike.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import tempfile
import unittest

from pizarra import graph, scene, validation
from pizarra.blocks import REGISTRY
from tests.helpers import new_board, reopen
from pizarra.validation import ValidationError


def _arrow(aid, src, dst, version=1):
    return {"id": aid, "type": "arrow", "version": version, "isDeleted": False,
            "startBinding": {"elementId": src} if src else None,
            "endBinding": {"elementId": dst} if dst else None}


def _board(*kinds):
    b = new_board()
    els = [scene.block_element(k, 400 * i, 0) for i, k in enumerate(kinds)]
    b.apply_client_elements(els)
    return b, [e["id"] for e in els]


class NumerosConFuente(unittest.TestCase):
    """Nunca se guarda un post-it del agente con cifras y sin fuente (D19)."""

    def base(self, **kw):
        return {"text": "La pared es fina", "kind": "riesgo", "author": "agent:design", **kw}

    def test_cifras_sin_fuente_se_rechazan_aunque_lo_pida_el_agente(self):
        with self.assertRaises(ValidationError):
            validation.validate_postit(self.base(text="La flecha es de 2.3 mm"))

    def test_cifras_con_fuente_de_bloque_se_aceptan(self):
        p = validation.validate_postit(self.base(
            text="La flecha es de 2.3 mm", sources=[{"kind": "bloque", "ref": "bloque:abc"}]))
        self.assertEqual(p["state"], "abierto")

    def test_marca_de_estimacion_se_acepta_y_queda_registrada(self):
        p = validation.validate_postit(self.base(text="Unos 3 kg", estimate=True))
        self.assertTrue(p["estimate"])

    def test_dato_vivo_sin_url_ni_fecha_no_vale_como_fuente(self):
        with self.assertRaises(ValidationError):
            validation.validate_postit(self.base(
                text="Plazo 5 días", sources=[{"kind": "dato_vivo", "ref": "proveedor"}]))

    def test_texto_sin_cifras_no_necesita_fuente(self):
        validation.validate_postit(self.base())

    def test_autor_humano_no_puede_escribir_como_agente(self):
        with self.assertRaises(ValidationError):
            validation.validate_postit(self.base(author="user"))

    def test_post_it_del_board_queda_en_la_escena_con_su_tipo(self):
        b, _ = _board()
        new = b.agent_add_postit(self.base())
        self.assertEqual(new[0]["customData"]["kind"], "postit")
        self.assertEqual(new[0]["customData"]["author"], "agent:design")
        self.assertEqual(new[0]["type"], "embeddable")           # tarjeta, D71


class Autoria(unittest.TestCase):
    """El agente nunca modifica un elemento del usuario aunque tenga su id (D20)."""

    def test_agente_no_edita_elemento_del_usuario(self):
        b, _ = _board()
        mine = {"id": "u1", "type": "rectangle", "version": 3, "x": 0, "y": 0}
        b.apply_client_elements([mine])
        with self.assertRaises(ValidationError):
            b.agent_update_element("agent:design", {**mine, "x": 50})
        self.assertEqual(next(e for e in b.elements if e["id"] == "u1")["x"], 0)

    def test_agente_edita_lo_suyo_y_sube_la_version(self):
        b, _ = _board()
        new = b.agent_add_postit({"text": "ok", "kind": "nota", "author": "agent:design"})
        upd = b.agent_update_element("agent:design", {**new[0], "x": 99})
        self.assertEqual(upd["version"], new[0]["version"] + 1)

    def test_un_agente_no_edita_lo_de_otro_agente(self):
        b, _ = _board()
        new = b.agent_add_postit({"text": "ok", "kind": "nota", "author": "agent:design"})
        with self.assertRaises(ValidationError):
            b.agent_update_element("agent:review", {**new[0], "x": 99})


class Grafo(unittest.TestCase):
    """Nunca se acepta una conexión incompatible ni una que cierre un ciclo."""

    def test_tipos_incompatibles_no_conectan(self):
        b, (t, v) = _board("prueba.tubo", "prueba.voladizo")
        edges, problems = graph.build(b.elements + [_arrow("a", v, t)], REGISTRY)
        self.assertEqual(edges, {})
        self.assertEqual(len(problems), 1)

    def test_conexion_compatible_ocupa_el_puerto_por_tipo(self):
        b, (t, v) = _board("prueba.tubo", "prueba.voladizo")
        edges, problems = graph.build(b.elements + [_arrow("a", t, v)], REGISTRY)
        self.assertEqual(edges, {v: {"tubo": (t, "tubo")}})
        self.assertEqual(problems, [])

    def test_segunda_flecha_al_mismo_puerto_se_rechaza(self):
        b, (t1, t2, v) = _board("prueba.tubo", "prueba.tubo", "prueba.voladizo")
        edges, problems = graph.build(
            b.elements + [_arrow("a", t1, v), _arrow("b", t2, v)], REGISTRY)
        self.assertEqual(edges, {v: {"tubo": (t1, "tubo")}})
        self.assertEqual(len(problems), 1)

    def test_ciclo_se_rechaza(self):
        fake = {"x.a": REGISTRY["prueba.voladizo"].__class__(
            kind="x.a", title="A", params={}, inputs={"in": "t"}, outputs={"out": "t"},
            run=lambda p, i, c: {})}
        els = [scene.block_element("x.a", 0, 0), scene.block_element("x.a", 300, 0)]
        a, c = els[0]["id"], els[1]["id"]
        edges, problems = graph.build(els + [_arrow("1", a, c), _arrow("2", c, a)], fake)
        self.assertEqual(edges, {c: {"in": (a, "out")}})
        self.assertIn("ciclo", problems[0]["reason"])

    def test_flecha_libre_no_es_conexion_ni_problema(self):
        b, (t,) = _board("prueba.tubo")
        edges, problems = graph.build(b.elements + [_arrow("a", t, None)], REGISTRY)
        self.assertEqual((edges, problems), ({}, []))


class Desactualizado(unittest.TestCase):
    """Cambiar una entrada marca lo de detrás y nada más; nunca ejecuta nada (D14)."""

    def setUp(self):
        self.b, (self.t, self.v) = _board("prueba.tubo", "prueba.voladizo")
        self.b.apply_client_elements([_arrow("a", self.t, self.v)])
        self.b.run(self.v)

    def test_ejecutar_el_final_ejecuta_la_cadena_y_todo_queda_al_dia(self):
        self.assertEqual(self.b.statuses(), {self.t: "al_dia", self.v: "al_dia"})
        self.assertEqual(self.b.state[self.v]["outputs"]["voladizo"]["sigma"]["source"], f"bloque:{self.v}")

    def test_cambiar_un_parametro_de_delante_desactualiza_lo_de_detras(self):
        self.b.set_params(self.t, {"t": 4})
        self.assertEqual(self.b.statuses(), {self.t: "desactualizado", self.v: "desactualizado"})

    def test_cambiar_un_parametro_de_detras_no_toca_lo_de_delante(self):
        self.b.set_params(self.v, {"F": 300})
        self.assertEqual(self.b.statuses(), {self.t: "al_dia", self.v: "desactualizado"})

    def test_cambiar_un_parametro_no_ejecuta_nada(self):
        before = self.b.state[self.v]["outputs"]
        self.b.set_params(self.t, {"t": 4})
        self.assertIs(self.b.state[self.v]["outputs"], before)

    def test_volver_al_valor_anterior_deja_el_bloque_al_dia_sin_ejecutar(self):
        self.b.set_params(self.v, {"F": 300})
        self.b.set_params(self.v, {"F": 200})
        self.assertEqual(self.b.statuses()[self.v], "al_dia")

    def test_bloque_no_conectado_no_se_entera(self):
        self.b.apply_client_elements([scene.block_element("prueba.tubo", 0, 500)])
        other = [k for k in self.b.statuses() if k not in (self.t, self.v)][0]
        self.b.set_params(self.t, {"t": 4})
        self.assertEqual(self.b.statuses()[other], "nunca")

    def test_sin_entrada_conectada_queda_incompleto_y_no_se_ejecuta(self):
        b, (v,) = _board("prueba.voladizo")
        self.assertEqual(b.statuses()[v], "incompleto")
        with self.assertRaises(ValidationError):
            b.run(v)

    def test_error_del_motor_se_ve_en_el_bloque(self):
        self.b.set_params(self.t, {"t": 30})
        self.b.run(self.t)
        self.assertEqual(self.b.statuses()[self.t], "error")
        self.assertIn("imposible", self.b.state[self.t]["error"])


class Fusion(unittest.TestCase):
    def test_gana_la_version_mas_alta(self):
        cur = [{"id": "a", "version": 5, "x": 1}]
        self.assertEqual(scene.merge(cur, [{"id": "a", "version": 4, "x": 2}])[0]["x"], 1)
        self.assertEqual(scene.merge(cur, [{"id": "a", "version": 6, "x": 2}])[0]["x"], 2)

    def test_no_pierde_lo_que_el_cliente_aun_no_tiene(self):
        cur = [{"id": "a", "version": 1}, {"id": "agente", "version": 1}]
        out = scene.merge(cur, [{"id": "a", "version": 2}])
        self.assertEqual([e["id"] for e in out], ["a", "agente"])


class Persistencia(unittest.TestCase):
    def test_la_pizarra_sobrevive_a_reabrir_el_proyecto(self):
        b, (t,) = _board("prueba.tubo")
        b.run(t)
        b.save()
        b2 = reopen(b)
        self.assertEqual(b2.statuses(), {t: "al_dia"})


if __name__ == "__main__":
    unittest.main()
