"""Ejecución de bloques en segundo plano (plan D89, D92, D93, §10).

Reglas:
- Ejecutar la cadena solo ejecuta lo que no está al día, en orden; nunca se ejecuta un bloque
  cuyo bloque de delante acaba de fallar; nunca hay dos ejecuciones a la vez en un proyecto.
- Cancelar deja con resultado lo terminado y el bloque en curso exactamente como estaba, nunca
  con salidas ni archivos a medias.
- Un parámetro cambiado durante la ejecución deja el bloque desactualizado al terminar, nunca
  al día con parámetros que no usó.
- Un bloque solo escribe en su `blocks/<id>/`: un archivo citado fuera de su carpeta es un
  error; guardar y restaurar una versión se lleva sus archivos; copiar un bloque, nunca.
- El proceso de cálculo da lo mismo que ejecutar aquí, manda el progreso, y si muere de golpe
  el bloque da error (no se queda colgado).

Los bloques de prueba son un paquete de verdad en una carpeta temporal: el proceso de cálculo
carga los paquetes desde su carpeta, como en la app.

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import asyncio
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from pizarra import execution, graph, packs, scene
from pizarra.board import Board
from pizarra.storage import LocalWorkspace, NotFound
from pizarra.validation import ValidationError

PACK = '''
import os, time
from pathlib import Path
from boardprint_sdk.packs import Param

CALLS = []          # en este proceso: lo que se ha ejecutado (solo vale con run_inline)


def _v(x, unit=""):
    return {"value": x, "unit": unit}


def fuente(p, i, ctx):
    CALLS.append(("fuente", ctx.block_id))
    (ctx.workdir / "dato.txt").write_text(str(p["n"]), encoding="utf-8")
    return {"x": {"n": _v(p["n"]), "dato": {"value": "dato.txt", "unit": "", "file": "dato.txt"}}}


def doble(p, i, ctx):
    CALLS.append(("doble", ctx.block_id))
    dato = i["x"].get("dato")
    leido = Path(dato["path"]).read_text(encoding="utf-8") if dato else ""
    return {"x": {"n": _v(i["x"]["n"]["value"] * 2), "leido": _v(leido)}}


def lento(p, i, ctx):
    CALLS.append(("lento", ctx.block_id))
    (ctx.workdir / "salida.txt").write_text(str(i["x"]["n"]["value"]), encoding="utf-8")
    for k in range(int(p["pasos"])):
        ctx.progress(k / p["pasos"], f"paso {k}")
        time.sleep(p["s"])
    return {"x": {"n": _v(i["x"]["n"]["value"] + 1)}}


def falla(p, i, ctx):
    CALLS.append(("falla", ctx.block_id))
    raise ValueError("no cuadra")


def muere(p, i, ctx):
    os._exit(3)


SEEN = []          # (bloque, options, project_name, sync_file) de cada ejecución


def confirma(p, i, ctx):
    from boardprint_sdk.packs import ConfirmRequired
    SEEN.append((ctx.block_id, dict(ctx.options), ctx.project_name, ctx.sync_file))
    if not ctx.options.get("seguro"):
        raise ConfirmRequired("¿seguro?", "seguro", "Sí, seguro")
    return {"x": {"n": _v(i["x"]["n"]["value"])}}


def mira(p, i, ctx):
    SEEN.append((ctx.block_id, dict(ctx.options), ctx.project_name, ctx.sync_file))
    return {"x": {"n": _v(p["n"])}}


def fuera(p, i, ctx):
    return {"x": {"n": _v(1), "f": {"value": "", "unit": "", "file": "../state.json"}}}


def lee(p, i, ctx):
    a = i["f"]["archivo"]
    CALLS.append(("lee", Path(a["path"]).read_text(encoding="utf-8")))
    return {"x": {"n": _v(len(Path(a["path"]).read_text(encoding="utf-8")))}}


def lista(p, i, ctx):
    CALLS.append(("lista", tuple(i["c"]["archivos"]["value"]), tuple(i["c"]["archivos"]["paths"])))
    return {"x": {"n": _v(len(i["c"]["archivos"]["value"]))}}


def casi(p, i, ctx):
    (ctx.workdir / "dato.txt").write_text("a medias", encoding="utf-8")
    raise ValueError("falla después de escribir")


def register(pack):
    pack.port("t.num", "número")
    pack.block("t.fuente", "Fuente", fuente, params={"n": Param(3)}, outputs={"x": "t.num"})
    pack.block("t.doble", "Doble", doble, inputs={"x": "t.num"}, outputs={"x": "t.num"})
    pack.block("t.lento", "Lento", lento, params={"s": Param(0.05), "pasos": Param(4)},
               inputs={"x": "t.num"}, outputs={"x": "t.num"})
    pack.block("t.falla", "Falla", falla, inputs={"x": "t.num"}, outputs={"x": "t.num"})
    pack.block("t.muere", "Muere", muere, inputs={"x": "t.num"}, outputs={"x": "t.num"})
    pack.block("t.fuera", "Fuera", fuera, outputs={"x": "t.num"})
    pack.block("t.mira", "Mira", mira, params={"n": Param(1)}, outputs={"x": "t.num"})
    pack.block("t.confirma", "Confirma", confirma, inputs={"x": "t.num"}, outputs={"x": "t.num"})
    pack.block("t.lee", "Lee", lee, inputs={"f": "archivo"}, outputs={"x": "t.num"})
    pack.block("t.lista", "Lista", lista, inputs={"c": "carpeta"}, outputs={"x": "t.num"})
    pack.block("t.casi", "Casi", casi, outputs={"x": "t.num"})
'''


def make_pack():
    root = Path(tempfile.mkdtemp())
    d = root / "t"
    d.mkdir()
    (d / "pack.toml").write_text('id = "t"\nname = "Pruebas"\nauthor = "Pruebas"\ndescription = "Paquete de prueba"\nversion = "0.1.0"\nsdk = ">=1.0,<2"\n', encoding="utf-8")
    (d / "blocks.py").write_text(textwrap.dedent(PACK), encoding="utf-8")
    reg = packs.load([root], log=lambda m: None)
    assert "t.fuente" in reg, reg.packs
    import sys
    return reg, sys.modules["pizarra_packs.t.blocks"].CALLS


def arrow(aid, src, dst, frm="x", to="x"):
    return {"id": aid, "type": "arrow", "version": 1, "isDeleted": False,
            "startBinding": {"elementId": src}, "endBinding": {"elementId": dst},
            "customData": {"kind": "connection", "from": frm, "to": to}}


def chain(reg, *kinds):
    """Una pizarra con los bloques en cadena (cada uno alimenta al siguiente)."""
    ws = LocalWorkspace.open(Path(tempfile.mkdtemp()) / "Personal", trash=lambda p: None)
    b = Board(ws, ws.create_project("", "E").id, registry=reg, connectors=frozenset())
    els = [scene.block_element(k, 400 * i, 0) for i, k in enumerate(kinds)]
    ids = [e["id"] for e in els]
    b.apply_client_elements(els + [arrow(f"a{i}", ids[i], ids[i + 1])
                                   for i in range(len(ids) - 1)])
    return b, ids


def snapshot(b, bid):
    import copy
    return copy.deepcopy(b.state.get(bid))


class Cadena(unittest.TestCase):
    def setUp(self):
        self.reg, self.calls = make_pack()
        self.calls.clear()

    def test_solo_se_ejecuta_lo_que_no_esta_al_dia_y_en_orden(self):
        b, (f, d1, d2) = chain(self.reg, "t.fuente", "t.doble", "t.doble")
        b.run(d2)
        self.assertEqual([c[1] for c in self.calls], [f, d1, d2])
        self.calls.clear()
        b.run(d2)                       # lo de delante ya está al día
        self.assertEqual([c[1] for c in self.calls], [d2])
        self.assertEqual(b.state[d2]["outputs"]["x"]["n"]["value"], 12)
        self.assertEqual(b.state[d1]["outputs"]["x"]["leido"]["value"], "3",
                         "lee el archivo de delante por su ruta")

    def test_nunca_se_ejecuta_lo_que_va_detras_de_un_bloque_que_acaba_de_fallar(self):
        b, (f, x, d) = chain(self.reg, "t.fuente", "t.falla", "t.doble")
        summary = b.run(d)
        self.assertEqual([c[0] for c in self.calls], ["fuente", "falla"])
        self.assertEqual(summary["failed"], [x])
        self.assertIn("no cuadra", b.state[x]["error"])
        self.assertIsNone(b.state[d].get("outputs"))

    def test_nunca_hay_dos_ejecuciones_a_la_vez_en_un_proyecto(self):
        b, (f, d) = chain(self.reg, "t.fuente", "t.doble")
        job = execution.Job.plan(b, d)
        with self.assertRaises(ValidationError):
            execution.Job.plan(b, f)
        with self.assertRaises(ValidationError):
            b.restore_version("cualquiera")
        job.close()
        execution.Job.plan(b, f).close()

    def test_un_parametro_cambiado_mientras_corre_deja_el_bloque_desactualizado(self):
        b, (f,) = chain(self.reg, "t.fuente")
        job = execution.Job.plan(b, f)
        step = job.next()
        b.set_params(f, {"n": 7})                       # mientras corre
        job.finish(step, execution.execute(self.reg, step))
        job.close()
        self.assertEqual(b.state[f]["outputs"]["x"]["n"]["value"], 3, "lo que usó")
        self.assertEqual(b.statuses()[f], "desactualizado")

    def test_ejecutar_lo_desactualizado_ejecuta_todo_y_salta_lo_que_no_se_puede(self):
        b, (f, d) = chain(self.reg, "t.fuente", "t.doble")
        suelto = scene.block_element("t.doble", 0, 600)     # sin entrada: incompleto
        b.apply_client_elements([suelto])
        b.run()
        self.assertEqual(b.statuses()[f], "al_dia")
        self.assertEqual(b.statuses()[d], "al_dia")
        b.set_params(f, {"n": 5})
        self.calls.clear()
        summary = b.run()
        self.assertEqual([c[1] for c in self.calls], [f, d])
        self.assertEqual(summary["skipped"], [])        # el suelto no está desactualizado
        with self.assertRaises(ValidationError):
            b.run()                                     # ya no queda nada


class Confirmacion(unittest.TestCase):
    """D112: un bloque que pide confirmación acaba en error con su acción; la confirmación va
    solo a ese bloque y solo esa vez."""

    def setUp(self):
        self.reg, _ = make_pack()
        import sys
        self.seen = sys.modules["pizarra_packs.t.blocks"].SEEN
        self.seen.clear()

    def test_sin_confirmar_da_error_con_su_accion(self):
        b, (m, c) = chain(self.reg, "t.mira", "t.confirma")
        b.run(c)
        view = b.blocks_view()["blocks"][c]
        self.assertEqual(view["status"], "error")
        self.assertIn("seguro", view["error"])
        self.assertEqual(view["error_action"], {"action": "seguro", "label": "Sí, seguro"})

    def test_la_confirmacion_va_solo_al_bloque_y_solo_esa_vez(self):
        b, (m, c) = chain(self.reg, "t.mira", "t.confirma")
        b.run(c)
        self.seen.clear()
        b.set_params(m, {"n": 2})                   # lo de delante también se ejecuta
        b.run(c, {"seguro": True})
        self.assertEqual([(x[0], x[1]) for x in self.seen], [(m, {}), (c, {"seguro": True})])
        self.assertEqual(b.statuses()[c], "al_dia")
        self.assertIsNone(b.blocks_view()["blocks"][c]["error_action"])
        b.set_params(m, {"n": 3})
        b.run(c)
        self.assertEqual(b.statuses()[c], "error", "la confirmación no se queda")

    def test_el_bloque_recibe_el_proyecto_y_su_registro_fuera_de_sus_archivos(self):
        b, (m,) = chain(self.reg, "t.mira")
        b.run(m)
        _, _, name, sync = self.seen[-1]
        self.assertEqual(name, b.ws.project(b.project_id).name)
        self.assertEqual(sync.name, f"{m}.json")
        self.assertNotIn("blocks", sync.parts)
        sync.parent.mkdir(parents=True, exist_ok=True)
        sync.write_text("{}", encoding="utf-8")
        b.ws.clear_block_files(b.project_id, m)     # un error después no se lo lleva
        self.assertTrue(sync.exists())


class Archivos(unittest.TestCase):
    def setUp(self):
        self.reg, _ = make_pack()

    def test_los_archivos_van_a_la_carpeta_del_bloque_y_cada_ejecucion_los_reescribe(self):
        b, (f, d) = chain(self.reg, "t.fuente", "t.doble")
        b.run(d)
        p = b.ws.block_file(b.project_id, f, "dato.txt")
        self.assertEqual(p.parent.name, f)
        p.write_text("otro", encoding="utf-8")          # mismo campo, otro contenido
        h = b.state[f]["outputs_hash"]["x"]
        b.run(f)
        self.assertEqual(b.state[f]["outputs_hash"]["x"], h, "el bloque lo vuelve a escribir")

    def test_un_archivo_citado_fuera_de_su_carpeta_es_un_error(self):
        b, (x,) = chain(self.reg, "t.fuera")
        b.run(x)
        self.assertIn("sale de la carpeta", b.state[x]["error"])
        self.assertIsNone(b.state[x]["outputs"])

    def test_una_version_se_lleva_los_archivos_y_restaurar_los_devuelve(self):
        b, (f,) = chain(self.reg, "t.fuente")
        b.run(f)
        v = b.save_version("tres")
        b.set_params(f, {"n": 9})
        b.run(f)
        self.assertEqual(b.ws.block_file(b.project_id, f, "dato.txt").read_text(), "9")
        b.restore_version(v["id"])
        self.assertEqual(b.ws.block_file(b.project_id, f, "dato.txt").read_text(), "3")
        self.assertEqual(b.statuses()[f], "al_dia")

    def test_un_bloque_que_falla_se_queda_sin_archivos(self):
        b, (f, x) = chain(self.reg, "t.fuente", "t.falla")
        b.run(f)
        b.run(x)
        with self.assertRaises(NotFound):
            b.ws.block_file(b.project_id, x, "dato.txt")
        self.assertFalse(any(p.name.startswith(".run-")
                             for p in (b.dir / "blocks").iterdir()), "sin carpetas de trabajo")


def with_card(b, path, block_id, frm, to):
    """Pone la tarjeta de `path` y la conecta a la entrada `to` de `block_id`."""
    (card,) = b.add_cards([path])
    b.apply_client_elements([scene.connection_element(card, b._element(block_id), frm, to)])
    return card["id"]


class EntradasDeArchivo(unittest.TestCase):
    """D110, D134, D145: un archivo o una carpeta conectados entran con sus rutas absolutas, y
    el hash se lee de nuevo antes de ejecutar."""

    def setUp(self):
        self.reg, self.calls = make_pack()
        self.calls.clear()

    def test_el_bloque_recibe_la_ruta_absoluta_aunque_la_tarjeta_la_guarde_relativa(self):
        b, (r,) = chain(self.reg, "t.lee")
        doc = b.ws.root / "datos" / "motor.txt"
        doc.parent.mkdir()
        doc.write_text("hola", encoding="utf-8")
        cid = with_card(b, doc, r, "archivo", "f")
        self.assertEqual(b._element(cid)["customData"]["path"], "datos/motor.txt")
        self.assertEqual(b.run(r)["done"], [r])
        self.assertEqual(self.calls, [("lee", "hola")])
        self.assertEqual(b.state[r]["outputs"]["x"]["n"]["value"], 4)

    def test_antes_de_ejecutar_se_lee_el_hash_aunque_fecha_y_tamano_no_cambien(self):
        b, (r,) = chain(self.reg, "t.lee")
        doc = Path(tempfile.mkdtemp()) / "a.txt"
        doc.write_text("aaa", encoding="utf-8")
        t = doc.stat().st_mtime_ns
        with_card(b, doc, r, "archivo", "f")
        b.run(r)
        doc.write_text("bbb", encoding="utf-8")           # mismo tamaño y misma fecha
        import os
        os.utime(doc, ns=(t, t))
        b.probe()
        self.assertEqual(b.statuses()[r], "al_dia", "el sondeo no lo ve (D134)")
        b.run(r)
        self.assertEqual(self.calls, [("lee", "aaa"), ("lee", "bbb")],
                         "ejecutar sí lo ve: lee el hash otra vez antes de empezar")

    def test_ejecutar_lo_desactualizado_salta_las_tarjetas(self):
        b, (r,) = chain(self.reg, "t.lee")
        doc = Path(tempfile.mkdtemp()) / "a.txt"
        doc.write_text("aaa", encoding="utf-8")
        with_card(b, doc, r, "archivo", "f")
        self.assertEqual(b.run()["done"], [r])

    def test_una_carpeta_entra_con_la_lista_de_lo_marcado(self):
        b, (r,) = chain(self.reg, "t.lista")
        d = Path(tempfile.mkdtemp())
        for rel in ("a.pdf", "sub/b.pdf", "sub/c.txt"):
            (d / rel).parent.mkdir(exist_ok=True)
            (d / rel).write_text(rel, encoding="utf-8")
        cid = with_card(b, d, r, "carpeta", "c")
        el = b._element(cid)
        b.apply_client_elements([scene.bumped({**el, "customData": {
            **el["customData"], "content": {"exclude": [], "patterns": ["*.pdf"]}}})])
        b.run(r)
        (_, rels, paths), = self.calls
        self.assertEqual(rels, ("a.pdf", "sub/b.pdf"))
        self.assertEqual([Path(p) for p in paths], [d / "a.pdf", d / "sub" / "b.pdf"])

    def test_un_archivo_que_no_esta_no_deja_ejecutar_y_dice_por_que(self):
        b, (r,) = chain(self.reg, "t.lee")
        doc = Path(tempfile.mkdtemp()) / "a.txt"
        doc.write_text("aaa", encoding="utf-8")
        with_card(b, doc, r, "archivo", "f")
        doc.unlink()
        with self.assertRaises(ValidationError) as cm:
            b.run(r)
        self.assertIn("no encontrado", str(cm.exception))
        self.assertEqual(self.calls, [])


class CopiasACarpeta(unittest.TestCase):
    """D109: tras una ejecución que termina bien, sus archivos van a la carpeta de la flecha."""

    def setUp(self):
        self.reg, _ = make_pack()
        self.dest = Path(tempfile.mkdtemp())

    def to_folder(self, b, block_id, overwrite=None):
        new = b.save_to(block_id, self.dest)
        arrow = next(e for e in new if e["type"] == "arrow")
        if overwrite is not None:
            b.apply_client_elements([scene.bumped({**arrow, "customData": {
                **arrow["customData"], "overwrite": overwrite}})])
        return next(e for e in new if (e.get("customData") or {}).get("kind") == "folder")["id"]

    def test_por_defecto_dos_ejecuciones_dejan_dos_archivos_sin_pisar_nada(self):
        b, (f,) = chain(self.reg, "t.fuente")
        self.to_folder(b, f)
        b.run(f)
        b.set_params(f, {"n": 9})
        b.run(f)
        self.assertEqual((self.dest / "dato.txt").read_text(), "3")
        self.assertEqual((self.dest / "dato_1.txt").read_text(), "9")

    def test_sobrescribir_en_la_flecha_pisa_ese_archivo(self):
        b, (f,) = chain(self.reg, "t.fuente")
        self.to_folder(b, f, overwrite=["dato.txt"])
        b.run(f)
        b.set_params(f, {"n": 9})
        b.run(f)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["dato.txt"])
        self.assertEqual((self.dest / "dato.txt").read_text(), "9")

    def test_guardar_tambien_en_la_misma_carpeta_usa_su_tarjeta(self):
        b, (f, d) = chain(self.reg, "t.fuente", "t.doble")
        c1 = self.to_folder(b, f)
        c2 = self.to_folder(b, d)
        self.assertEqual(c1, c2)
        _, copies, problems = graph.connections(b.elements, b.registry)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(src for src, _, _ in copies[c1]), sorted([f, d]))

    def test_guardar_tambien_en_dos_veces_la_misma_carpeta_copia_una_vez(self):
        """Prueba de punta a punta de FF 4.8: la segunda vez añadía otra flecha y cada
        ejecución copiaba dos veces."""
        b, (f,) = chain(self.reg, "t.fuente")
        c1 = self.to_folder(b, f)
        c2 = self.to_folder(b, f)
        self.assertEqual(c1, c2)
        arrows = [e for e in b.elements if e.get("type") == "arrow" and not e.get("isDeleted")
                  and (e.get("endBinding") or {}).get("elementId") == c1]
        self.assertEqual(len(arrows), 1)
        b.run(f)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["dato.txt"])

    def test_guardar_tambien_en_sobre_una_flecha_de_una_salida_la_abre_a_todas(self):
        b, (f,) = chain(self.reg, "t.fuente")
        new = b.save_to(f, self.dest)
        arrow = next(e for e in new if e["type"] == "arrow")
        b.apply_client_elements([scene.bumped({**arrow, "customData": {
            **arrow["customData"], "from": "x"}})])
        again = next(e for e in b.save_to(f, self.dest) if e["type"] == "arrow")
        self.assertEqual(again["id"], arrow["id"])
        self.assertIsNone(again["customData"]["from"])
        self.assertGreater(again["version"], arrow["version"] + 1)

    def test_una_ejecucion_con_error_nunca_copia_nada(self):
        b, (x,) = chain(self.reg, "t.casi")
        self.to_folder(b, x)
        b.run(x)
        self.assertTrue(b.state[x]["error"])
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_una_copia_que_falla_deja_aviso_en_la_carpeta_y_nunca_error_en_el_bloque(self):
        from pizarra import files
        b, (f,) = chain(self.reg, "t.fuente")
        cid = self.to_folder(b, f)

        def copy2(a, c):
            raise PermissionError(13, "Permiso denegado")

        from unittest import mock
        with mock.patch.object(files.shutil, "copy2", copy2):
            b.run(f)
        self.assertIsNone(b.state[f]["error"])
        self.assertEqual(b.statuses()[f], "al_dia")
        self.assertIn("Permiso denegado", b.sources_view()[cid]["notice"])
        self.assertEqual(b.ws.block_file(b.project_id, f, "dato.txt").read_text(), "3",
                         "blocks/<id>/ no se toca")
        b.set_params(f, {"n": 4})
        b.run(f)                                         # la siguiente sale bien: sin aviso
        self.assertIsNone(b.sources_view()[cid]["notice"])


class ProcesoAparte(unittest.TestCase):
    """El proceso de cálculo de verdad (multiprocessing, spawn)."""

    def setUp(self):
        self.reg, _ = make_pack()

    def run_async(self, b, block_id, cancel_after=None):
        events = []

        async def main():
            job = execution.Job.plan(b, block_id)
            worker = execution.ProcessWorker(self.reg.dirs)

            async def on_event(kind):
                events.append((kind, job.view()))
                if cancel_after and kind == "progress" and job.progress[1] == cancel_after:
                    worker.kill()

            return await execution.run_job(job, worker, on_event)

        return asyncio.run(main()), events

    def test_da_lo_mismo_que_ejecutar_aqui_y_manda_el_progreso(self):
        b, (f, d, s) = chain(self.reg, "t.fuente", "t.doble", "t.lento")
        t0 = time.monotonic()
        summary, events = self.run_async(b, s)
        self.assertEqual(summary["done"], [f, d, s])
        self.assertEqual(b.state[s]["outputs"]["x"]["n"]["value"], 7)
        self.assertTrue(any(k == "progress" and v["block"] == s for k, v in events))
        self.assertIn(("step", d), [(k, v["block"]) for k, v in events])
        self.assertLess(time.monotonic() - t0, 20)
        self.assertIsNone(b.job)

    def test_cancelar_deja_lo_terminado_y_el_bloque_en_curso_como_estaba(self):
        b, (f, s) = chain(self.reg, "t.fuente", "t.lento")
        b.run(s)                                    # una ejecución anterior, al día
        before = snapshot(b, s)
        b.set_params(f, {"n": 10})
        b.set_params(s, {"s": 0.5, "pasos": 20})
        summary, _ = self.run_async(b, s, cancel_after="paso 1")
        self.assertTrue(summary["cancelled"])
        self.assertEqual(summary["done"], [f], "la fuente terminó y se queda")
        self.assertEqual(b.state[f]["outputs"]["x"]["n"]["value"], 10)
        after = snapshot(b, s)
        self.assertEqual({k: after[k] for k in before if k != "params"},
                         {k: before[k] for k in before if k != "params"},
                         "salidas, hash y error como estaban")
        self.assertFalse(any(p.name.startswith(".run-")
                             for p in (b.dir / "blocks").iterdir()), "sin archivos a medias")
        self.assertEqual(b.ws.block_file(b.project_id, s, "salida.txt").read_text(), "3",
                         "el archivo de la ejecución anterior, no el que escribía la cancelada")
        self.assertIsNone(b.job)

    def test_una_ejecucion_cancelada_nunca_copia_a_la_carpeta(self):
        b, (f, s) = chain(self.reg, "t.fuente", "t.lento")
        dest = Path(tempfile.mkdtemp())
        b.save_to(s, dest)
        b.set_params(s, {"s": 0.5, "pasos": 20})
        summary, _ = self.run_async(b, s, cancel_after="paso 1")
        self.assertTrue(summary["cancelled"])
        self.assertEqual(list(dest.iterdir()), [])

    def test_si_el_proceso_muere_de_golpe_el_bloque_da_error(self):
        b, (f, m) = chain(self.reg, "t.fuente", "t.muere")
        summary, _ = self.run_async(b, m)
        self.assertEqual(summary["failed"], [m])
        self.assertIn("terminó de golpe", b.state[m]["error"])


if __name__ == "__main__":
    unittest.main()
