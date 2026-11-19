"""La tinta (docs/PLAN_PIZARRA.md §3, D188, D192-D194).

Reglas que protegen:
- Un trazo de tinta siempre se guarda con `opacity 0`: la que traía pasa a
  `customData.ink.opacity`; normalizar dos veces da lo mismo; un `freedraw` del lápiz de
  Excalidraw nunca se toca.
- A qué apunta un trazo: un círculo alrededor de un bloque apunta a ese bloque y nunca al de al
  lado; una flecha de un post-it a un bloque dice de dónde sale y adónde va; una recta bajo un
  texto lo subraya y una que lo cruza lo tacha; la tinta en vacío no apunta a nada; nunca da un
  id que no esté en la escena (ni uno borrado).
- Marcas del agente: rodear deja la caja del objetivo dentro con margen; subrayar queda debajo
  sin tocarla; la misma marca da los mismos puntos; un objetivo que no existe da error; el
  agente nunca quita una marca del usuario, y sí las suyas.
- `leer_pizarra` lista la tinta con lo que marca.

Lo que pinta la tinta y la reconoce está en el frontend (ink.test.ts, shapes.test.ts).
Ejecutar desde app/backend:  python -m unittest discover -s tests -t .
"""
import json
import math
import unittest

from pizarra import agent, agent_board_tools as abt, agent_threads, ink, scene
from tests.helpers import new_board

AGENT = "agent:design"


def stroke(points, shape=None, brush="rotulador", size=4, author="user", opacity=0, eid=None,
           color="#e03131", version=1):
    """Un trazo de tinta como lo manda la interfaz: `points` en la escena, guardados relativos
    al primero."""
    ox, oy = points[0]
    data = {"brush": brush, "size": size, "opacity": 1, **({"shape": shape} if shape else {})}
    e = scene._base("freedraw", ox, oy, 0, 0, opacity=opacity, strokeColor=color,
                    points=[[x - ox, y - oy] for x, y in points], version=version,
                    customData={"kind": "ink", "ink": data, "author": author})
    if eid:
        e["id"] = eid
    return e


def text(eid, x, y, w, h, words="Montaje"):
    return scene._base("text", x, y, w, h, id=eid, text=words, originalText=words)


def ring(cx, cy, rx, ry, n=40):
    return [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
            for i in range(n + 1)]


def current(board, eid):
    return next(e for e in board.elements if e["id"] == eid)


def ids(apunta):
    return [t["id"] for t, _ in apunta]


def rel(apunta):
    return {t["id"]: r for t, r in apunta}


class TintaEnLaEscena(unittest.TestCase):
    def setUp(self):
        self.b = new_board()

    def test_un_ink_siempre_se_guarda_con_opacity_0_y_la_suya_pasa_a_customdata(self):
        s = stroke([(0, 0), (50, 10), (90, 0)], opacity=60)
        _, rewritten = self.b.apply_client_elements([s])
        saved = current(self.b, s["id"])
        self.assertEqual(saved["opacity"], 0)
        self.assertAlmostEqual(saved["customData"]["ink"]["opacity"], 0.6)
        self.assertEqual([e["id"] for e in rewritten], [s["id"]])
        self.assertGreater(saved["version"], s["version"])      # gana en todas las ventanas

    def test_normalizar_dos_veces_da_lo_mismo(self):
        s = stroke([(0, 0), (50, 10)], opacity=100)
        once = ink.normalized(s)
        self.assertEqual(ink.normalized(once), once)
        self.assertEqual(once["opacity"], 0)
        self.assertEqual(once["customData"]["ink"]["opacity"], 1)
        # uno que ya está bien no se reescribe
        _, rewritten = self.b.apply_client_elements([stroke([(0, 0), (40, 0)])])
        self.assertEqual(rewritten, [])

    def test_un_freedraw_del_lapiz_de_excalidraw_nunca_se_toca(self):
        pencil = scene._base("freedraw", 0, 0, 40, 40, opacity=80,
                             points=[[0, 0], [20, 30], [40, 40]])
        self.assertIs(ink.normalized(pencil), pencil)
        _, rewritten = self.b.apply_client_elements([pencil])
        self.assertEqual(rewritten, [])
        saved = current(self.b, pencil["id"])
        self.assertEqual(saved["opacity"], 80)
        self.assertNotIn("customData", saved)
        self.assertEqual(ink.describe(self.b.elements), [])

    def test_en_las_versiones_la_tinta_sale_como_tinta_y_el_lapiz_como_trazo(self):
        from pizarra import diff
        pencil = scene._base("freedraw", 0, 0, 40, 40, points=[[0, 0], [40, 40]])
        changes = diff.diff([], [stroke([(0, 0), (40, 0)]), pencil])
        self.assertEqual(sorted(c["element"]["kind"] for c in changes), ["freedraw", "ink"])


class APuntaLaTinta(unittest.TestCase):
    """Bloque A en (0, 0, 280, 220) y bloque B a su derecha, a 40 px."""

    def setUp(self):
        self.a = {**scene.block_element("demo.tubo", 0, 0), "id": "A"}
        self.bb = {**scene.block_element("demo.tubo", 320, 0), "id": "B"}
        self.elements = [self.a, self.bb]

    def test_un_circulo_alrededor_de_un_bloque_apunta_a_el_y_nunca_al_de_al_lado(self):
        for shape in ("círculo", "elipse", None):          # reconocido o a mano, cerrado
            c = stroke(ring(140, 110, 175, 140), shape=shape)
            apunta, _ = ink.pointing(c, self.elements + [c])
            self.assertEqual(ids(apunta), ["A"], shape)
            self.assertEqual(rel(apunta)["A"], "rodea")

    def test_una_flecha_de_un_post_it_a_un_bloque_dice_de_donde_sale_y_adonde_va(self):
        p = {**scene.postit_element({"text": "Ojo", "kind": "nota", "state": "abierto",
                                     "author": "user", "sources": [], "estimate": False,
                                     "anchor": None}, 0, 400), "id": "P"}
        tail, tip = (130, 450), (450, 200)       # sale del post-it, llega al borde de B
        f = stroke([tail, tip, (430, 215), tip, (440, 230)], shape="flecha")
        apunta, desde = ink.pointing(f, self.elements + [p, f])
        self.assertEqual(ids(apunta), ["B"])
        self.assertEqual(rel(apunta)["B"], "señala")
        self.assertEqual(desde["id"], "P")
        d = ink.describe_stroke(f, self.elements + [p, f])
        self.assertEqual(d["desde"]["id"], "P")
        self.assertEqual(d["forma"], "flecha")

    def test_una_recta_bajo_un_texto_lo_subraya_y_una_que_lo_cruza_lo_tacha(self):
        t = text("T", 0, 400, 200, 25)
        under = stroke([(-5, 436), (205, 438)], shape="recta")
        over = stroke([(-10, 412), (210, 413)], shape="recta")
        self.assertEqual(rel(ink.pointing(under, [t, under])[0]), {"T": "subraya"})
        self.assertEqual(rel(ink.pointing(over, [t, over])[0]), {"T": "tacha"})
        # muy por debajo ya no subraya nada
        far = stroke([(-5, 480), (205, 480)], shape="recta")
        self.assertEqual(ink.pointing(far, [t, far])[0], [])

    def test_el_subrayador_resalta_lo_que_toca(self):
        t = text("T", 0, 400, 200, 25)
        h = stroke([(5, 412), (100, 413), (195, 412)], brush="subrayador", size=8)
        self.assertEqual(rel(ink.pointing(h, [t, h])[0]), {"T": "resalta"})

    def test_la_tinta_en_vacio_no_apunta_a_nada(self):
        for s in (stroke(ring(1000, 1000, 60, 40)), stroke([(900, 900), (1000, 950)]),
                  stroke([(900, 900), (1100, 900)], shape="recta"),
                  stroke([(900, 900), (1000, 900), (985, 890), (1000, 900), (985, 910)],
                         shape="flecha")):
            apunta, desde = ink.pointing(s, self.elements + [s])
            self.assertEqual(apunta, [])
            self.assertIsNone(desde)

    def test_nunca_da_un_id_que_no_este_en_la_escena_ni_uno_borrado(self):
        gone = {**self.a, "isDeleted": True}
        other = stroke(ring(140, 110, 175, 140), eid="otra")       # otra tinta, encima de A
        connection = scene.connection_element(self.a, self.bb, "salida", "entrada")
        for s in (stroke(ring(140, 110, 175, 140)), stroke([(50, 50), (200, 150)]),
                  stroke([(-10, 110), (290, 110)], shape="recta")):
            scene_now = [gone, self.bb, other, connection, s]
            apunta, _ = ink.pointing(s, scene_now)
            live = {e["id"] for e in scene_now if not e.get("isDeleted")}
            self.assertTrue(set(ids(apunta)) <= live - {other["id"], connection["id"], s["id"]})
            self.assertNotIn("A", ids(apunta))


class MarcasDelAgente(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.blk = scene.block_element("demo.tubo", 0, 0)
        self.t = text("T", 0, 400, 200, 25)
        self.b.apply_client_elements([self.blk, self.t])

    def mark(self, target, marca, **kw):
        res, new = abt.tool_marcar(self.b, {"objetivo": target, "marca": marca, **kw})
        self.assertFalse(res.get("is_error"), res)
        return new[0], json.loads(res["content"][0]["text"])

    def test_rodear_deja_la_caja_del_objetivo_dentro_con_margen(self):
        for target in (self.blk, self.t):
            m, out = self.mark(target["id"], "rodear")
            x0, y0, x1, y1 = scene.bbox(target)
            pts = ink.points_of(m)
            mx0, my0, mx1, my1 = (min(p[0] for p in pts), min(p[1] for p in pts),
                                  max(p[0] for p in pts), max(p[1] for p in pts))
            self.assertTrue(mx0 <= x0 - 8 and my0 <= y0 - 8 and mx1 >= x1 + 8 and my1 >= y1 + 8)
            self.assertFalse(any(x0 < px < x1 and y0 < py < y1 for px, py in pts))
            self.assertEqual([a["id"] for a in out["apunta"]], [target["id"]])
            self.assertEqual(out["apunta"][0]["relacion"], "rodea")

    def test_subrayar_queda_debajo_sin_tocar_la_caja(self):
        m, out = self.mark("T", "subrayar")
        x0, y0, x1, y1 = scene.bbox(self.t)
        pts = ink.points_of(m)
        self.assertTrue(all(y1 + 2 < py < y1 + 24 for _, py in pts))
        self.assertTrue(min(p[0] for p in pts) <= x0 and max(p[0] for p in pts) >= x1)
        self.assertEqual(out["apunta"], [{"id": "T", "nombre": "texto «Montaje»",
                                          "relacion": "subraya"}])

    def test_cada_marca_es_del_agente_anclada_al_objetivo_y_apunta_a_el(self):
        relations = {"rodear": "rodea", "subrayar": "subraya", "tachar": "tacha",
                     "flecha": "señala", "resaltar": "resalta"}
        for marca, relation in relations.items():
            m, out = self.mark("T", marca)
            cd = m["customData"]
            self.assertEqual((cd["kind"], cd["author"], cd["anchor"], m["opacity"]),
                             ("ink", AGENT, "T", 0), marca)
            self.assertEqual(cd["ink"]["brush"], "subrayador" if marca == "resaltar" else "rotulador")
            self.assertEqual([(a["id"], a["relacion"]) for a in out["apunta"]], [("T", relation)],
                             marca)

    def test_la_misma_marca_da_los_mismos_puntos(self):
        one = ink.mark_element(self.t, "rodear", self.b.elements, AGENT)
        two = ink.mark_element(self.t, "rodear", self.b.elements, AGENT)
        self.assertEqual((one["x"], one["y"], one["points"]), (two["x"], two["y"], two["points"]))
        other = ink.mark_element(self.blk, "rodear", self.b.elements, AGENT)
        self.assertNotEqual(one["points"], other["points"])

    def test_un_objetivo_que_no_existe_o_una_marca_desconocida_dan_error_y_no_dejan_nada(self):
        before = len(self.b.elements)
        gone = {**self.t, "isDeleted": True, "version": 5}
        for args in ({"objetivo": "no-existe", "marca": "rodear"},
                     {"objetivo": self.blk["id"], "marca": "garabatear"},
                     {"objetivo": self.blk["id"], "marca": "rodear", "color": "fucsia"}):
            res, new = abt.tool_marcar(self.b, args)
            self.assertTrue(res.get("is_error"))
            self.assertEqual(new, [])
        self.b.apply_client_elements([gone])
        res, _ = abt.tool_marcar(self.b, {"objetivo": "T", "marca": "rodear"})
        self.assertIn("no hay ningún elemento", res["content"][0]["text"])
        self.assertEqual(len(self.b.elements), before)

    def test_el_agente_nunca_quita_una_marca_del_usuario_y_si_la_suya(self):
        mine, _ = self.mark("T", "rodear")
        user = stroke(ring(140, 110, 175, 140))
        self.b.apply_client_elements([user])
        res, changed = abt.tool_quitar_marca(self.b, {"id": user["id"]})
        self.assertTrue(res.get("is_error"))
        self.assertEqual(changed, [])
        self.assertFalse(current(self.b, user["id"]).get("isDeleted"))
        # tampoco algo que no es tinta, aunque sea suyo
        res, _ = abt.tool_quitar_marca(self.b, {"id": self.blk["id"]})
        self.assertTrue(res.get("is_error"))
        res, changed = abt.tool_quitar_marca(self.b, {"id": mine["id"]})
        self.assertFalse(res.get("is_error"), res)
        self.assertTrue(current(self.b, mine["id"])["isDeleted"])
        self.assertEqual([e["id"] for e in changed], [mine["id"]])

    def test_marcar_y_quitar_marca_estan_entre_las_herramientas_del_agente(self):
        self.assertIn("marcar", abt.NAMES)
        self.assertIn("quitar_marca", abt.NAMES)


class LeerLaTinta(unittest.TestCase):
    def setUp(self):
        self.b = new_board()
        self.blk = scene.block_element("demo.tubo", 0, 0)
        self.b.apply_client_elements([self.blk])
        x0, y0, x1, y1 = scene.bbox(self.blk)
        self.c = stroke(ring((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.65, (y1 - y0) * 0.65),
                        shape="elipse", color="#1971c2")
        self.b.apply_client_elements([self.c])

    def test_leer_pizarra_lista_la_tinta_con_lo_que_apunta(self):
        out = json.loads(agent.tool_leer_pizarra(self.b, {})["content"][0]["text"])
        (t,) = out["tinta"]
        self.assertEqual({k: t[k] for k in ("id", "forma", "pincel", "color", "autor")},
                         {"id": self.c["id"], "forma": "elipse", "pincel": "rotulador",
                          "color": "azul", "autor": "user"})
        self.assertEqual([(a["id"], a["relacion"]) for a in t["apunta"]],
                         [(self.blk["id"], "rodea")])
        self.assertTrue(t["apunta"][0]["nombre"].startswith("bloque "))

    def test_un_hilo_anclado_a_la_tinta_la_describe_con_lo_que_marca(self):
        brief = agent_threads.anchor_brief(self.b, self.c["id"], 600)
        self.assertEqual(brief["es"], "tinta")
        self.assertEqual([a["id"] for a in brief["apunta"]], [self.blk["id"]])

    def test_un_color_que_no_es_del_menu_sale_con_su_hex(self):
        odd = stroke([(2000, 0), (2100, 50)], color="#123456")
        self.b.apply_client_elements([odd])
        t = next(t for t in self.b.summary()["tinta"] if t["id"] == odd["id"])
        self.assertEqual((t["color"], t["forma"], t["apunta"]), ("#123456", "a mano", []))


if __name__ == "__main__":
    unittest.main()
