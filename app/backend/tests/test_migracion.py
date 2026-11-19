"""El post-it como tarjeta (docs/PLAN_PIZARRA.md §3, D71) y la migración de las escenas de R2.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import copy
import unittest

from pizarra import scene
from tests.helpers import new_board, reopen

SOURCES = [{"kind": "bloque", "ref": "bloque:b1"}]


def r2_postit(pid="p1", tid="t1", text="Revisa la unión del extremo", kind="riesgo",
              state="aceptado", author="agent:design", sources=SOURCES, anchor="b1",
              estimate=False, label=None):
    """Un post-it tal como lo guardaba R2: rectángulo con texto ligado (cabecera con el tipo,
    el texto y la línea de fuentes)."""
    head = label or kind.upper()
    full = "\n".join([head, text] + (["Fuente: bloque Voladizo"] if sources else []))
    rect = {"id": pid, "type": "rectangle", "x": 120, "y": 80, "width": 260, "height": 110,
            "version": 4, "index": "a1", "isDeleted": False,
            "boundElements": [{"type": "text", "id": tid}, {"type": "arrow", "id": "ar1"}],
            "customData": {"kind": "postit", "postitKind": kind, "state": state,
                           "author": author, "sources": sources, "estimate": estimate,
                           "anchor": anchor}}
    txt = {"id": tid, "type": "text", "x": 130, "y": 90, "width": 240, "height": 90,
           "version": 2, "index": "a2", "isDeleted": False, "containerId": pid,
           "text": full, "originalText": full,
           "customData": {"kind": "postit-text", "author": author}}
    return [rect, txt]


def live(elements):
    return [e for e in elements if not e.get("isDeleted")]


class Migracion(unittest.TestCase):
    """Un post-it de R2 se convierte sin perder nada; migrar dos veces da lo mismo (D71)."""

    def test_convierte_sin_perder_texto_tipo_estado_autor_fuentes_anclaje_posicion_ni_id(self):
        els, changed = scene.migrate_postits(r2_postit())
        self.assertTrue(changed)
        p = next(e for e in els if e["id"] == "p1")
        cd = p["customData"]
        self.assertEqual(p["type"], "embeddable")
        self.assertEqual(p["link"], "https://pizarra.local/postit/p1")
        self.assertEqual((p["x"], p["y"], p["width"]), (120, 80, 260))
        self.assertEqual(p["index"], "a1")
        self.assertEqual(cd["kind"], "postit")
        self.assertEqual(cd["text"], "Revisa la unión del extremo")
        self.assertEqual(cd["postitKind"], "riesgo")
        self.assertEqual(cd["state"], "aceptado")
        self.assertEqual(cd["author"], "agent:design")
        self.assertEqual(cd["sources"], SOURCES)
        self.assertEqual(cd["anchor"], "b1")
        self.assertGreater(p["version"], 4)

    def test_el_texto_ligado_nunca_queda_suelto(self):
        els, _ = scene.migrate_postits(r2_postit())
        self.assertEqual([e["id"] for e in live(els)], ["p1"])
        t = next(e for e in els if e["id"] == "t1")
        self.assertTrue(t["isDeleted"])
        self.assertGreater(t["version"], 2)          # gana a una ventana con la versión vieja
        p = next(e for e in els if e["id"] == "p1")
        self.assertEqual(p["boundElements"], [{"type": "arrow", "id": "ar1"}])

    def test_texto_de_varias_lineas_y_estimacion_se_conservan(self):
        rect, txt = r2_postit(text="Primera línea\nsegunda línea", sources=[],
                              estimate=True, label="NOTA · estimación sin verificar", kind="nota")
        els, _ = scene.migrate_postits([rect, txt])
        cd = els[0]["customData"]
        self.assertEqual(cd["text"], "Primera línea\nsegunda línea")
        self.assertTrue(cd["estimate"])

    def test_un_post_it_editado_a_mano_sin_cabecera_no_pierde_su_primera_linea(self):
        rect, txt = r2_postit(sources=[])
        txt["text"] = txt["originalText"] = "Lo reescribí entero"
        els, _ = scene.migrate_postits([rect, txt])
        self.assertEqual(els[0]["customData"]["text"], "Lo reescribí entero")

    def test_migrar_dos_veces_da_lo_mismo(self):
        once, _ = scene.migrate_postits(r2_postit())
        twice, changed = scene.migrate_postits(copy.deepcopy(once))
        self.assertFalse(changed)
        self.assertEqual(twice, once)

    def test_lo_que_no_es_un_post_it_de_r2_no_se_toca(self):
        other = [{"id": "r", "type": "rectangle", "version": 1, "x": 0, "y": 0},
                 {"id": "t", "type": "text", "version": 1, "text": "suelto", "x": 0, "y": 0},
                 scene.block_element("prueba.tubo", 0, 0)]
        els, changed = scene.migrate_postits(copy.deepcopy(other))
        self.assertFalse(changed)
        self.assertEqual(els, other)


class RespaldoDeR2(unittest.TestCase):
    """La escena original se guarda una sola vez y nunca se sobrescribe (D71)."""

    def test_abrir_una_escena_de_r2_la_migra_y_guarda_la_original_aparte(self):
        b = new_board()
        original = r2_postit()
        b.ws.save_scene(b.project_id, original)
        b2 = reopen(b)
        self.assertEqual([e["type"] for e in live(b2.elements)], ["embeddable"])
        self.assertEqual(b2.ws.load_scene_backup(b2.project_id, "r2"), original)
        # Ya está migrada en disco: abrirla otra vez no cambia nada.
        self.assertEqual(reopen(b2).elements, b2.elements)

    def test_el_respaldo_nunca_se_sobrescribe(self):
        b = new_board()
        first = r2_postit(text="Primera")
        b.ws.save_scene(b.project_id, first)
        reopen(b)
        b.ws.save_scene(b.project_id, r2_postit(text="Otra escena vieja"))
        reopen(b)
        self.assertEqual(b.ws.load_scene_backup(b.project_id, "r2"), first)

    def test_una_escena_sin_post_its_de_r2_no_deja_respaldo(self):
        b = new_board()
        b.ws.save_scene(b.project_id, [{"id": "r", "type": "rectangle", "version": 1,
                                        "x": 0, "y": 0}])
        reopen(b)
        self.assertIsNone(b.ws.load_scene_backup(b.project_id, "r2"))


class BloqueComoTarjeta(unittest.TestCase):
    """El papel del bloque lo pinta la tarjeta con el skin (D77): sin relleno ni trazo de
    Excalidraw, que asomarían por el borde y el tema oscuro invertiría."""

    def old_block(self):
        e = scene.block_element("prueba.tubo", 40, 60)
        return {**e, "strokeColor": "#1e1e1e", "backgroundColor": "#ffffff", "version": 3,
                "index": "a0"}

    def test_el_bloque_nuevo_nace_sin_trazo_y_con_relleno_casi_invisible(self):
        e = scene.block_element("prueba.tubo", 0, 0)
        self.assertEqual((e["strokeColor"], e["backgroundColor"]), ("transparent", scene.CARD_FILL))

    def test_un_bloque_de_antes_solo_cambia_sus_colores_y_sube_de_version(self):
        old = self.old_block()
        (new,), changed = scene.migrate_blocks([copy.deepcopy(old)])
        self.assertTrue(changed)
        self.assertEqual((new["strokeColor"], new["backgroundColor"]), ("transparent", scene.CARD_FILL))
        self.assertEqual(new["version"], 4)
        same = {k for k in old if k not in ("strokeColor", "backgroundColor", "version", "versionNonce")}
        self.assertEqual({k: new[k] for k in same}, {k: old[k] for k in same})

    def test_migrar_dos_veces_da_lo_mismo_y_no_toca_lo_demas(self):
        others = [{"id": "r", "type": "rectangle", "version": 1, "x": 0, "y": 0,
                   "strokeColor": "#1e1e1e", "backgroundColor": "#ffffff"},
                  scene.postit_element({"text": "", "kind": "nota", "state": "abierto",
                                        "author": "user", "sources": [], "estimate": False,
                                        "anchor": None}, 0, 0)]
        once, _ = scene.migrate_blocks([self.old_block()] + copy.deepcopy(others))
        twice, changed = scene.migrate_blocks(copy.deepcopy(once))
        self.assertFalse(changed)
        self.assertEqual(twice, once)
        self.assertEqual(once[1:], others)

    def test_abrir_un_proyecto_con_bloques_de_antes_los_deja_migrados_en_disco(self):
        b = new_board()
        b.ws.save_scene(b.project_id, [self.old_block()])
        b2 = reopen(b)
        self.assertEqual(b2.ws.load_scene(b2.project_id), b2.elements)
        self.assertEqual(b2.elements[0]["strokeColor"], "transparent")
        self.assertIsNone(b2.ws.load_scene_backup(b2.project_id, "r2"))


class PostitNuevo(unittest.TestCase):
    """El post-it nace con el esquema de D71: una tarjeta, abierto, con autor y fecha."""

    def test_el_del_usuario_nace_vacio_abierto_y_suyo(self):
        b = new_board()
        p = b.user_add_postit("pregunta", 10, 20)
        cd = p["customData"]
        self.assertEqual(p["type"], "embeddable")
        self.assertEqual(p["link"], f"https://pizarra.local/postit/{p['id']}")
        self.assertEqual((cd["kind"], cd["postitKind"], cd["state"], cd["author"], cd["text"]),
                         ("postit", "pregunta", "abierto", "user", ""))
        self.assertTrue(cd["created"])
        self.assertIn(p, b.elements)

    def test_un_tipo_desconocido_no_crea_nada(self):
        b = new_board()
        with self.assertRaises(ValueError):
            b.user_add_postit("chiste", 0, 0)
        self.assertEqual(b.elements, [])

    def test_el_del_agente_es_una_sola_tarjeta_con_su_texto(self):
        b = new_board()
        new = b.agent_add_postit({"text": "Revisa la unión", "kind": "riesgo",
                                  "author": "agent:design"})
        self.assertEqual(len(new), 1)
        cd = new[0]["customData"]
        self.assertEqual((cd["text"], cd["postitKind"], cd["author"], cd["state"]),
                         ("Revisa la unión", "riesgo", "agent:design", "abierto"))

    def test_leer_pizarra_da_el_texto_de_cada_post_it(self):
        b = new_board()
        b.agent_add_postit({"text": "Revisa la unión", "kind": "riesgo",
                            "author": "agent:design"})
        b.ws.save_scene(b.project_id, b.elements + r2_postit(pid="viejo", tid="tv"))
        postits = reopen(b).summary()["postits"]
        self.assertEqual(sorted(p["text"] for p in postits),
                         ["Revisa la unión", "Revisa la unión del extremo"])
