"""Grafo con puertos, desactualizado y no disponible (plan D88, D93, §10).

Reglas:
- Nunca se acepta una conexión entre puertos de distinto tipo, a una entrada ya ocupada, a un
  puerto que no existe ni una que cierre un ciclo; una flecha sin puerto a un bloque con dos
  compatibles nunca se conecta sola; una salida alimenta a varias entradas; migrar una flecha
  del spike le pone el único puerto compatible y migrar dos veces da lo mismo.
- Un bloque cuyo conector falta sale `no_disponible`, nunca `error`; si algo de la cadena está
  `no_disponible` o `incompleto` no se ejecuta nada.
- Volver a ejecutar algo de delante que da la misma carga en un puerto nunca desactualiza lo
  que cuelga de ese puerto; un archivo de salida con otro contenido y los mismos campos sí.
- Una tarjeta de archivo o de carpeta (D131-D133, D138) nunca tiene estado de bloque; los
  tipos de archivo casan por prefijo y nada más; cuenta su contenido, no su ruta; si no está
  (o no se ha sondeado) lo de detrás queda incompleto con el motivo, nunca con el hash viejo;
  «Buscar de nuevo» conserva las conexiones; una carpeta que recibe la salida de un bloque y
  alimenta a ese bloque o a uno de delante se rechaza como ciclo.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import tempfile
import unittest
from pathlib import Path

from pizarra import files, graph, packs, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace
from pizarra.validation import ValidationError


def _v(x, unit=""):
    return {"value": x, "unit": unit}


def registry():
    """Tipos de prueba: una fuente con dos salidas del mismo tipo y otra de otro tipo, un
    consumidor de una entrada, uno de dos entradas del mismo tipo y uno que necesita un CAD."""
    reg = packs.Registry()
    for t in ("p.a", "p.b"):
        reg.ports[t] = packs.PortType(t, t)
    calls = []

    def fuente(p, i, c):
        calls.append(c.block_id)
        return {"x": {"n": _v(p["n"])}, "y": {"n": _v(p["m"])}, "z": {"n": _v(1)}}

    def uno(p, i, c):
        calls.append(c.block_id)
        return {"out": {"n": _v(i["in"]["n"]["value"] * 2)}}

    def dos(p, i, c):
        calls.append(c.block_id)
        return {}

    def cad(p, i, c):
        calls.append(c.block_id)
        return {"m": {"n": _v(0)}}

    P = packs.Param
    for b in (
        packs.BlockType("p.fuente", "Fuente", {"n": P(1), "m": P(2)}, {},
                        {"x": "p.a", "y": "p.a", "z": "p.b"}, fuente),
        packs.BlockType("p.uno", "Uno", {}, {"in": "p.a"}, {"out": "p.a"}, uno),
        packs.BlockType("p.dos", "Dos", {}, {"a": "p.a", "b": "p.a"}, {}, dos),
        packs.BlockType("p.cad", "Construir", {}, {"in": "p.a"}, {"m": "cad.modelo"}, cad,
                        requires=("cad",)),
    ):
        reg[b.kind] = b
    return reg, calls


def arrow(aid, src, dst, frm=None, to=None, version=1):
    a = {"id": aid, "type": "arrow", "version": version, "isDeleted": False,
         "startBinding": {"elementId": src} if src else None,
         "endBinding": {"elementId": dst} if dst else None}
    if frm or to:
        a["customData"] = {"kind": "connection", **({"from": frm} if frm else {}),
                           **({"to": to} if to else {})}
    return a


def blocks(*kinds):
    els = [scene.block_element(k, 400 * i, 0) for i, k in enumerate(kinds)]
    return els, [e["id"] for e in els]


def board(reg, connectors=frozenset()):
    ws = LocalWorkspace.open(Path(tempfile.mkdtemp()) / "Personal", trash=lambda p: None)
    return Board(ws, ws.create_project("", "G").id, registry=reg, connectors=connectors)


class PuertosExplicitos(unittest.TestCase):
    def setUp(self):
        self.reg, _ = registry()

    def build(self, els):
        return graph.build(els, self.reg)

    def test_la_flecha_con_puertos_conecta_esos_puertos(self):
        els, (f, d) = blocks("p.fuente", "p.dos")
        edges, problems = self.build(els + [arrow("1", f, d, "y", "b")])
        self.assertEqual(edges, {d: {"b": (f, "y")}})
        self.assertEqual(problems, [])

    def test_puertos_de_distinto_tipo_no_conectan(self):
        els, (f, u) = blocks("p.fuente", "p.uno")
        edges, problems = self.build(els + [arrow("1", f, u, "z", "in")])
        self.assertEqual(edges, {})
        self.assertEqual(len(problems), 1)

    def test_un_puerto_que_no_existe_no_conecta(self):
        els, (f, u) = blocks("p.fuente", "p.uno")
        for frm, to in (("nada", "in"), ("x", "nada")):
            edges, problems = self.build(els + [arrow("1", f, u, frm, to)])
            self.assertEqual(edges, {}, (frm, to))
            self.assertEqual(len(problems), 1)

    def test_una_entrada_ocupada_no_admite_otra_flecha(self):
        els, (f, u) = blocks("p.fuente", "p.uno")
        edges, problems = self.build(els + [arrow("1", f, u, "x", "in"), arrow("2", f, u, "y", "in")])
        self.assertEqual(edges, {u: {"in": (f, "x")}})
        self.assertEqual(len(problems), 1)

    def test_una_salida_alimenta_a_varias_entradas(self):
        els, (f, d, u) = blocks("p.fuente", "p.dos", "p.uno")
        edges, problems = self.build(els + [arrow("1", f, d, "x", "a"), arrow("2", f, d, "x", "b"),
                                            arrow("3", f, u, "x", "in")])
        self.assertEqual(edges, {d: {"a": (f, "x"), "b": (f, "x")}, u: {"in": (f, "x")}})
        self.assertEqual(problems, [])

    def test_un_ciclo_no_conecta(self):
        els, (a, b) = blocks("p.uno", "p.uno")
        edges, problems = self.build(els + [arrow("1", a, b, "out", "in"), arrow("2", b, a, "out", "in")])
        self.assertEqual(len(edges), 1)
        self.assertIn("ciclo", problems[0]["reason"])


class SinPuerto(unittest.TestCase):
    """Una flecha dibujada sin puerto: solo conecta si no hay duda."""

    def setUp(self):
        self.reg, _ = registry()

    def test_con_un_solo_par_compatible_conecta_sola(self):
        els, (a, b) = blocks("p.uno", "p.uno")
        edges, problems = graph.build(els + [arrow("1", a, b)], self.reg)
        self.assertEqual(edges, {b: {"in": (a, "out")}})
        self.assertEqual(problems, [])

    def test_con_dos_entradas_compatibles_nunca_se_conecta_sola(self):
        els, (u, d) = blocks("p.uno", "p.dos")
        edges, problems = graph.build(els + [arrow("1", u, d)], self.reg)
        self.assertEqual(edges, {})
        self.assertIn("elige", problems[0]["reason"])

    def test_con_dos_salidas_compatibles_tampoco(self):
        els, (f, u) = blocks("p.fuente", "p.uno")
        edges, problems = graph.build(els + [arrow("1", f, u)], self.reg)
        self.assertEqual(edges, {})
        self.assertEqual(len(problems), 1)

    def test_con_la_entrada_dicha_y_una_sola_salida_compatible_conecta(self):
        els, (u, d) = blocks("p.uno", "p.dos")
        edges, _ = graph.build(els + [arrow("1", u, d, to="b")], self.reg)
        self.assertEqual(edges, {d: {"b": (u, "out")}})

    def test_una_flecha_libre_no_es_conexion_ni_problema(self):
        els, (u,) = blocks("p.uno")
        self.assertEqual(graph.build(els + [arrow("1", u, None)], self.reg), ({}, []))


class Migracion(unittest.TestCase):
    """Las flechas del spike (sin puertos) reciben el único puerto compatible al abrir."""

    def setUp(self):
        self.reg, _ = registry()

    def test_le_pone_el_unico_puerto_compatible_y_sube_la_version(self):
        els, (a, b) = blocks("p.uno", "p.uno")
        out, changed = scene.migrate_connections(els + [arrow("1", a, b, version=3)], self.reg)
        self.assertTrue(changed)
        a1 = next(e for e in out if e["id"] == "1")
        self.assertEqual(a1["customData"], {"kind": "connection", "from": "out", "to": "in"})
        self.assertEqual(a1["version"], 4)

    def test_migrar_dos_veces_da_lo_mismo(self):
        els, (a, b) = blocks("p.uno", "p.uno")
        once, _ = scene.migrate_connections(els + [arrow("1", a, b)], self.reg)
        twice, changed = scene.migrate_connections(once, self.reg)
        self.assertFalse(changed)
        self.assertEqual(once, twice)

    def test_una_flecha_con_duda_o_libre_no_se_toca(self):
        els, (u, d) = blocks("p.uno", "p.dos")
        src = els + [arrow("1", u, d), arrow("2", u, None)]
        out, changed = scene.migrate_connections(src, self.reg)
        self.assertFalse(changed)
        self.assertEqual(out, src)

    def test_abrir_un_proyecto_migra_y_guarda(self):
        b = board(self.reg)
        els, (x, y) = blocks("p.uno", "p.uno")
        b.apply_client_elements(els + [arrow("1", x, y)])
        b.save()
        b2 = Board(b.ws, b.project_id, registry=self.reg, connectors=frozenset())
        a1 = next(e for e in b2.elements if e["id"] == "1")
        self.assertEqual(a1["customData"]["to"], "in")


class NoDisponible(unittest.TestCase):
    def setUp(self):
        self.reg, self.calls = registry()

    def chain(self, connectors=frozenset()):
        b = board(self.reg, connectors)
        els, (f, c) = blocks("p.fuente", "p.cad")
        b.apply_client_elements(els + [arrow("1", f, c, "x", "in")])
        return b, f, c

    def test_sin_el_conector_sale_no_disponible_nunca_error(self):
        b, f, c = self.chain()
        self.assertEqual(b.statuses()[c], "no_disponible")

    def test_con_el_conector_sale_su_estado_normal(self):
        b, f, c = self.chain(frozenset({"cad"}))
        self.assertEqual(b.statuses()[c], "nunca")

    def test_si_algo_de_la_cadena_no_esta_disponible_no_se_ejecuta_nada(self):
        b, f, c = self.chain()
        with self.assertRaises(ValidationError) as ctx:
            b.run(c)
        self.assertIn("Construir", str(ctx.exception))
        self.assertEqual(self.calls, [], "ni siquiera lo de delante")

    def test_si_algo_de_la_cadena_esta_incompleto_no_se_ejecuta_nada(self):
        b = board(self.reg)
        els, (f, u, w) = blocks("p.fuente", "p.uno", "p.uno")
        b.apply_client_elements(els + [arrow("1", u, w, "out", "in")])
        with self.assertRaises(ValidationError):
            b.run(w)
        self.assertEqual(self.calls, [])


class EntradaOpcional(unittest.TestCase):
    """D99, D122: una lista de materiales con la entrada opcional `med`, que llega de un bloque
    que pide Fusion. Sin Fusion, la lista se ejecuta igual y no espera."""

    def setUp(self):
        self.reg, self.calls = registry()
        P = packs.Param

        def mide(p, i, c):
            self.calls.append(c.block_id)
            return {"m": {"n": _v(p["k"])}}

        def lista(p, i, c):
            self.calls.append(c.block_id)
            med = i.get("med")
            return {"out": {"n": _v(med["n"]["value"] if med else None)}}

        self.reg["p.mide"] = packs.BlockType("p.mide", "Analizar", {"k": P(1)}, {"in": "p.a"},
                                             {"m": "cad.modelo"}, mide, requires=("cad",))
        self.reg["p.lista"] = packs.BlockType("p.lista", "Lista", {}, {"in": "p.a", "med": "cad.modelo"},
                                              {"out": "p.b"}, lista, optional=("med",))

    def chain(self, connectors=frozenset(), connect=True):
        b = board(self.reg, connectors)
        els, (f, m, l) = blocks("p.fuente", "p.mide", "p.lista")
        arrows = [arrow("1", f, m, "x", "in"), arrow("2", f, l, "y", "in")]
        if connect:
            arrows.append(arrow("3", m, l, "m", "med"))
        b.apply_client_elements(els + arrows)
        return b, f, m, l

    def med(self, b, l):
        return b.state[l]["outputs"]["out"]["n"]["value"]

    def test_libre_no_deja_el_bloque_incompleto_y_se_ejecuta_sin_ella(self):
        b, f, m, l = self.chain(connect=False)
        self.assertEqual(b.statuses()[l], "nunca")
        b.run(l)
        self.assertIsNone(self.med(b, l))

    def test_con_su_bloque_no_disponible_se_ejecuta_sin_ella_y_no_para_la_cadena(self):
        b, f, m, l = self.chain()
        self.assertEqual(b.statuses()[l], "nunca", "ni incompleto ni no_disponible")
        b.run(l)
        self.assertEqual(self.calls, [f, l], "lo de Fusion no se ejecuta, y no para nada")
        self.assertIsNone(self.med(b, l))
        self.assertEqual(b.statuses()[l], "al_dia")

    def test_ejecutar_lo_desactualizado_sin_fusion_ejecuta_la_lista(self):
        b, f, m, l = self.chain()
        b.run()
        self.assertEqual(sorted(self.calls), sorted([f, l]))
        self.assertEqual(b.statuses()[l], "al_dia")

    def test_con_fusion_lo_de_la_opcional_se_ejecuta_antes_y_entra(self):
        b, f, m, l = self.chain(frozenset({"cad"}))
        b.run(l)
        self.assertEqual(self.calls, [f, m, l])
        self.assertEqual(self.med(b, l), 1)

    def test_conectada_y_con_resultado_cambiarla_desactualiza_el_bloque(self):
        b, f, m, l = self.chain(frozenset({"cad"}))
        b.run(l)
        b.set_params(m, {"k": 2})
        b.run(m)
        self.assertEqual(b.statuses()[l], "desactualizado")
        b.run(l)
        self.assertEqual(self.med(b, l), 2)

    def test_cuando_su_bloque_da_resultado_por_primera_vez_desactualiza(self):
        b, f, m, l = self.chain()
        b.run(l)                                  # sin Fusion: sin medir
        b._connectors = frozenset({"cad"})        # se abre Fusion
        self.assertEqual(b.statuses()[l], "al_dia", "abrir Fusion no cambia lo que entra")
        b.run(m)
        self.assertEqual(b.statuses()[l], "desactualizado")

    def test_ejecutar_lo_desactualizado_sigue_con_lo_que_su_opcional_desactualiza(self):
        """e2e del 20/11: Analizar en error y la lista al día sin medir; al reintentar todo,
        Analizar da resultado y la lista se quedaba desactualizada (no estaba en el plan)."""
        b, f, m, l = self.chain()
        b.run(l)                                  # sin Fusion: sin medir
        b._connectors = frozenset({"cad"})        # se abre Fusion
        self.calls.clear()
        b.run()
        self.assertEqual(self.calls, [m, l])
        self.assertEqual(self.med(b, l), 1)
        self.assertEqual(b.statuses()[l], "al_dia")

    def test_lo_de_detras_que_sigue_al_dia_no_se_ejecuta(self):
        b, f, m, l = self.chain(frozenset({"cad"}))
        b.run(l)
        b.set_params(m, {"k": 1})                 # el mismo valor: misma salida de Analizar
        b.state[m]["error"] = "falló"             # y en error, para que sea objetivo
        self.calls.clear()
        b.run()
        self.assertEqual(self.calls, [m], "la lista no se vuelve a ejecutar si sigue al día")

    def test_cerrar_fusion_no_desactualiza_lo_que_ya_uso_su_resultado(self):
        b, f, m, l = self.chain(frozenset({"cad"}))
        b.run(l)
        b._connectors = frozenset()               # se cierra Fusion
        st = b.statuses()
        self.assertEqual(st[m], "no_disponible")
        self.assertEqual(st[l], "al_dia")

    def test_una_obligatoria_libre_sigue_dejando_el_bloque_incompleto(self):
        b = board(self.reg)
        els, (f, m, l) = blocks("p.fuente", "p.mide", "p.lista")
        b.apply_client_elements(els)
        self.assertEqual(b.statuses()[l], "incompleto")

    def test_una_opcional_que_no_es_entrada_es_un_error_del_paquete(self):
        pb = packs.PackBuilder("p")
        pb.block("p.x", "X", lambda p, i, c: {}, inputs={"a": "p.a"}, optional=("b",))
        self.assertTrue(any("opcional" in e for e in pb.errors))


class HashPorPuerto(unittest.TestCase):
    def test_misma_carga_en_un_puerto_no_desactualiza_lo_que_cuelga_de_el(self):
        reg, _ = registry()
        b = board(reg)
        els, (f, u1, u2) = blocks("p.fuente", "p.uno", "p.uno")
        b.apply_client_elements(els + [arrow("1", f, u1, "x", "in"), arrow("2", f, u2, "y", "in")])
        b.run(u1)
        b.run(u2)
        b.set_params(f, {"m": 5})       # cambia solo la salida y
        b.run(f)
        st = b.statuses()
        self.assertEqual(st[u1], "al_dia", "x no cambió")
        self.assertEqual(st[u2], "desactualizado", "y sí")

    def test_un_archivo_con_otro_contenido_cambia_el_hash_aunque_los_campos_no(self):
        out = {"brazo": {"arm": {"value": "arm.toml", "unit": "", "file": "arm.toml"}}}
        h1 = graph.outputs_hash(out, lambda name: "aaa")
        h2 = graph.outputs_hash(out, lambda name: "bbb")
        h3 = graph.outputs_hash(out, lambda name: "aaa")
        self.assertNotEqual(h1["brazo"], h2["brazo"])
        self.assertEqual(h1, h3)


def card(cid, path, kind="file"):
    """Tarjeta de archivo o de carpeta (D131): un nodo fuente, no un bloque."""
    return {"id": cid, "type": "rectangle", "version": 1, "isDeleted": False,
            "customData": {"kind": kind, "path": path}}


def file_registry():
    """Bloques que leen archivos y carpetas: uno de cualquier archivo, uno de STEP con la
    entrada opcional, uno de carpeta, uno que escribe archivos con una entrada de carpeta, uno
    que da un `archivo` genérico y uno de paso."""
    reg, calls = registry()
    P = packs.Param
    for b in (
        packs.BlockType("p.lee", "Lee", {}, {"doc": "archivo"}, {"out": "p.a"}, lambda p, i, c: {}),
        packs.BlockType("p.step", "STEP", {"k": P(1)}, {"modelo": "archivo.step"}, {"out": "p.a"},
                        lambda p, i, c: {}, optional=("modelo",)),
        packs.BlockType("p.dir", "Datos", {}, {"datos": "carpeta"}, {"out": "p.a"}, lambda p, i, c: {}),
        packs.BlockType("p.bom", "Lista", {}, {"in": "p.a", "datos": "carpeta"}, {"bom": "p.a"},
                        lambda p, i, c: {}, optional=("datos",)),
        packs.BlockType("p.gen", "Genérico", {}, {}, {"f": "archivo"}, lambda p, i, c: {}),
    ):
        reg[b.kind] = b
    return reg, calls


class TiposDeArchivo(unittest.TestCase):
    """D132: `archivo` acepta cualquier `archivo.*`; `archivo.step`, `.step` y `.stp`;
    `carpeta`, solo carpetas."""

    def setUp(self):
        self.reg, _ = file_registry()

    def connects(self, src_el, kind, port):
        els, (b,) = blocks(kind)
        edges, problems = graph.build(els + [src_el, arrow("a", src_el["id"], b)], self.reg)
        return edges.get(b, {}).get(port) is not None

    def test_archivo_acepta_un_step_y_un_pdf(self):
        self.assertTrue(self.connects(card("f", "r.step"), "p.lee", "doc"))
        self.assertTrue(self.connects(card("f", "datos/motor.PDF"), "p.lee", "doc"))

    def test_archivo_step_acepta_step_y_stp(self):
        self.assertTrue(self.connects(card("f", "robot.STEP"), "p.step", "modelo"))
        self.assertTrue(self.connects(card("f", "robot.stp"), "p.step", "modelo"))

    def test_archivo_step_nunca_acepta_un_pdf_ni_un_archivo_generico(self):
        self.assertFalse(self.connects(card("f", "motor.pdf"), "p.step", "modelo"))
        els, (g, s) = blocks("p.gen", "p.step")
        edges, problems = graph.build(els + [arrow("a", g, s)], self.reg)
        self.assertEqual(edges, {})
        self.assertEqual(len(problems), 1)

    def test_carpeta_solo_carpetas(self):
        self.assertTrue(self.connects(card("c", "datasheets", "folder"), "p.dir", "datos"))
        self.assertFalse(self.connects(card("f", "motor.pdf"), "p.dir", "datos"))
        self.assertFalse(self.connects(card("c", "datasheets", "folder"), "p.lee", "doc"))

    def test_las_demas_conexiones_siguen_pidiendo_el_mismo_tipo(self):
        self.assertFalse(graph.accepts("p.a", "p.b"))
        self.assertTrue(graph.accepts("p.a", "p.a"))
        self.assertFalse(graph.accepts("archivo.pdf", "archivo.step"))


class TarjetaDeArchivo(unittest.TestCase):
    """D131, D133, D138: un nodo fuente con el hash de su contenido."""

    def setUp(self):
        self.reg, self.calls = file_registry()
        bl, (self.b,) = blocks("p.lee")
        self.f = card("f", "datos/motor.pdf")
        self.els = bl + [self.f, arrow("a", "f", self.b)]
        self.edges, _ = graph.build(self.els, self.reg)

    def ran_with(self, sources):
        """Estado del bloque como si se hubiera ejecutado con `sources`."""
        return {self.b: {"params": {}, "outputs": {}, "outputs_hash": {},
                         "last_hash": graph.input_hash(self.b, {}, self.edges, {}, sources)}}

    def test_nunca_tiene_estado_de_bloque(self):
        sts = graph.statuses(self.els, self.reg, {}, sources={"f": files.FileState("h1")})
        self.assertEqual(set(sts), {self.b})

    def test_con_el_mismo_contenido_lo_de_detras_sigue_al_dia(self):
        src = {"f": files.FileState("h1")}
        self.assertEqual(graph.statuses(self.els, self.reg, self.ran_with(src), sources=src)[self.b],
                         "al_dia")

    def test_otro_contenido_en_la_misma_ruta_desactualiza(self):
        state = self.ran_with({"f": files.FileState("h1")})
        sts = graph.statuses(self.els, self.reg, state, sources={"f": files.FileState("h2")})
        self.assertEqual(sts[self.b], "desactualizado")

    def test_otra_ruta_con_el_mismo_contenido_sigue_al_dia(self):
        state = self.ran_with({"f": files.FileState("h1")})
        moved = [dict(e, customData={"kind": "file", "path": "otra/ruta/motor.pdf"})
                 if e["id"] == "f" else e for e in self.els]
        sts = graph.statuses(moved, self.reg, state, sources={"f": files.FileState("h1")})
        self.assertEqual(sts[self.b], "al_dia")

    def test_un_archivo_que_no_esta_deja_incompleto_lo_de_detras_con_el_motivo(self):
        state = self.ran_with({"f": files.FileState("h1")})
        sts, why = graph.explain(self.els, self.reg, state,
                                 sources={"f": files.FileState(None, "no encontrado")})
        self.assertEqual(sts[self.b], "incompleto", "nunca al día con el hash viejo")
        self.assertEqual(why[self.b], "motor.pdf: no encontrado")

    def test_sin_sondear_tampoco_cuenta_como_al_dia(self):
        state = self.ran_with({"f": files.FileState("h1")})
        sts, why = graph.explain(self.els, self.reg, state)
        self.assertEqual(sts[self.b], "incompleto")
        self.assertIn("sin comprobar", why[self.b])

    def test_en_una_entrada_opcional_tambien_deja_incompleto(self):
        bl, (s,) = blocks("p.step")
        els = bl + [card("f", "robot.stp"), arrow("a", "f", s)]
        sts = graph.statuses(els, self.reg, {}, sources={"f": files.FileState(None, "no encontrado")})
        self.assertEqual(sts[s], "incompleto", "nunca se ejecuta como si no estuviera conectada")

    def test_buscar_de_nuevo_conserva_las_conexiones(self):
        again = [dict(e, customData={"kind": "file", "path": "C:/nuevo/motor.pdf"}, version=2)
                 if e["id"] == "f" else e for e in self.els]
        self.assertEqual(graph.build(again, self.reg)[0], self.edges)

    def test_una_tarjeta_borrada_no_conecta(self):
        gone = [dict(e, isDeleted=True) if e["id"] == "f" else e for e in self.els]
        self.assertEqual(graph.statuses(gone, self.reg, {})[self.b], "incompleto")


class CarpetaComoSalida(unittest.TestCase):
    """D109, D110: una carpeta recibe salidas y alimenta bloques, sin cerrar ciclos."""

    def setUp(self):
        self.reg, _ = file_registry()

    def test_la_flecha_de_un_bloque_a_una_carpeta_es_un_destino_no_una_entrada(self):
        els, (u, l) = blocks("p.uno", "p.bom")
        c = card("c", "salidas", "folder")
        edges, copies, problems = graph.connections(
            els + [c, arrow("1", u, l, "out", "in"), arrow("2", l, "c", "bom")], self.reg)
        self.assertEqual(copies, {"c": [(l, "bom", "2")]})
        self.assertNotIn("c", edges)
        self.assertEqual(problems, [])

    def test_sin_puerto_van_todas_las_salidas(self):
        els, (l,) = blocks("p.bom")
        _, copies, _ = graph.connections(els + [card("c", "s", "folder"), arrow("2", l, "c")], self.reg)
        self.assertEqual(copies, {"c": [(l, None, "2")]})

    def test_dos_flechas_del_mismo_bloque_con_la_misma_salida_copian_una_vez(self):
        """Prueba de punta a punta de FF 4.8: con dos flechas a la misma carpeta, cada ejecución
        copiaba dos veces (bom.csv y bom_1.csv a la vez). La segunda es un problema."""
        els, (l,) = blocks("p.bom")
        c = card("c", "s", "folder")
        for first, second in ((None, None), (None, "bom"), ("bom", None), ("bom", "bom")):
            _, copies, problems = graph.connections(
                els + [c, arrow("1", l, "c", first), arrow("2", l, "c", second)], self.reg)
            self.assertEqual(copies, {"c": [(l, first, "1")]}, (first, second))
            self.assertEqual([p["arrow"] for p in problems], ["2"], (first, second))
            self.assertIn("ya llega", problems[0]["reason"])

    def test_salidas_distintas_del_mismo_bloque_a_la_misma_carpeta_si_valen(self):
        self.reg["p.dos"] = packs.BlockType("p.dos", "Dos", {}, {}, {"x": "p.a", "y": "p.a"},
                                            lambda p, i, c: {})
        els, (d,) = blocks("p.dos")
        c = card("c", "s", "folder")
        _, copies, problems = graph.connections(
            els + [c, arrow("1", d, "c", "x"), arrow("2", d, "c", "y")], self.reg)
        self.assertEqual(problems, [])
        self.assertEqual(copies, {"c": [(d, "x", "1"), (d, "y", "2")]})

    def test_a_un_archivo_o_desde_otra_tarjeta_no_se_conecta(self):
        els, (l,) = blocks("p.bom")
        f, c = card("f", "a.pdf"), card("c", "s", "folder")
        for a in (arrow("1", l, "f"), arrow("1", "f", "c"), arrow("1", l, "c", "nada")):
            edges, copies, problems = graph.connections(els + [f, c, a], self.reg)
            self.assertEqual((edges, copies), ({}, {}))
            self.assertEqual(len(problems), 1, a)

    def test_la_carpeta_que_alimenta_al_bloque_que_la_llena_se_rechaza_como_ciclo(self):
        els, (l,) = blocks("p.bom")
        c = card("c", "s", "folder")
        for into, out in (("1", "2"), ("2", "1")):          # en los dos órdenes
            edges, copies, problems = graph.connections(
                els + [c, arrow(into, l, "c", "bom"), arrow(out, "c", l, to="datos")], self.reg)
            self.assertEqual(len(problems), 1, (into, out))
            self.assertIn("ciclo", problems[0]["reason"])

    def test_tambien_si_alimenta_a_uno_de_delante(self):
        els, (d, l) = blocks("p.dir", "p.bom")
        c = card("c", "s", "folder")
        edges, copies, problems = graph.connections(
            els + [c, arrow("1", d, l, "out", "in"), arrow("2", l, "c"), arrow("3", "c", d)], self.reg)
        self.assertEqual(len(problems), 1)
        self.assertIn("ciclo", problems[0]["reason"])

    def test_si_alimenta_a_uno_de_detras_no_es_ciclo(self):
        els, (u, d) = blocks("p.uno", "p.dir")
        c = card("c", "s", "folder")
        edges, copies, problems = graph.connections(
            els + [c, arrow("1", u, "c"), arrow("2", "c", d)], self.reg)
        self.assertEqual(problems, [])
        self.assertEqual(edges, {d: {"datos": ("c", "carpeta")}})


if __name__ == "__main__":
    unittest.main()
