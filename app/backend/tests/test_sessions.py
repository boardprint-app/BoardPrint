"""Envíos parciales de la escena y sesiones por proyecto (docs/PLAN_PIZARRA.md §2, §3, D69).

Ejecutar desde app/backend:  python -m unittest discover -s tests -t . -v
"""
import asyncio
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from pizarra import scene
from pizarra.sessions import Sessions, send_all
from pizarra.storage import LocalWorkspace, NotFound


def _el(eid, version=1, index=None, **kw):
    e = {"id": eid, "version": version, **kw}
    if index is not None:
        e["index"] = index
    return e


class EnvioParcial(unittest.TestCase):
    """Un envío parcial nunca pierde ni reordena los elementos que no trae."""

    def test_lo_que_no_viene_se_queda_como_estaba_y_en_su_sitio(self):
        cur = [_el("a"), _el("b"), _el("c")]
        out = scene.merge(cur, [_el("b", 2, text="nuevo")])
        self.assertEqual([e["id"] for e in out], ["a", "b", "c"])
        self.assertEqual(out[1]["text"], "nuevo")

    def test_lo_nuevo_va_al_final(self):
        out = scene.merge([_el("a"), _el("b")], [_el("z"), _el("a", 2)])
        self.assertEqual([e["id"] for e in out], ["a", "b", "z"])

    def test_una_version_vieja_no_pisa_la_nueva(self):
        out = scene.merge([_el("a", 5, text="bueno")], [_el("a", 3, text="viejo")])
        self.assertEqual(out[0]["text"], "bueno")

    def test_un_borrado_viaja_como_un_cambio_mas(self):
        out = scene.merge([_el("a"), _el("b")], [_el("a", 2, isDeleted=True)])
        self.assertEqual([(e["id"], e.get("isDeleted", False)) for e in out],
                         [("a", True), ("b", False)])

    def test_el_orden_de_dibujo_lo_da_el_indice_de_excalidraw(self):
        # Traer "a" al frente en otra ventana: le cambia el índice y la versión.
        cur = [_el("a", 1, "a0"), _el("b", 1, "a1"), _el("c", 1, "a2")]
        out = scene.merge(cur, [_el("a", 2, "a3")])
        self.assertEqual([e["id"] for e in out], ["b", "c", "a"])

    def test_sin_indice_en_todos_se_respeta_el_orden_de_llegada(self):
        cur = [_el("a", 1, "a0"), _el("b", 1, "a1")]
        out = scene.merge(cur, [_el("nuevo")])            # creado por el backend, sin índice
        self.assertEqual([e["id"] for e in out], ["a", "b", "nuevo"])

    def test_accepted_dice_que_cambios_ganaron(self):
        cur = [_el("a", 5), _el("b", 1)]
        incoming = [_el("a", 3), _el("b", 2), _el("c", 1)]
        self.assertEqual([e["id"] for e in scene.accepted(cur, incoming)], ["b", "c"])


class SesionesPorProyecto(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ws = LocalWorkspace.open(self.tmp / "Personal", trash=lambda p: None)
        self.a = self.ws.create_project("", "A").id
        self.b = self.ws.create_project("", "B").id
        self.sessions = Sessions(self.ws)

    def test_dos_ventanas_del_mismo_proyecto_comparten_pizarra(self):
        s1, s2 = self.sessions.open(self.a), self.sessions.open(self.a)
        self.assertIs(s1, s2)
        self.assertIsNot(s1.board, self.sessions.open(self.b).board)

    def test_un_proyecto_que_no_existe_no_abre_sesion(self):
        with self.assertRaises(NotFound):
            self.sessions.open("no-existe")
        self.assertEqual(self.sessions.open_ids(), [])

    def test_al_irse_la_ultima_ventana_se_guarda_y_se_suelta(self):
        s = self.sessions.open(self.a)
        s.clients.update({"v1", "v2"})
        s.board.apply_client_elements([_el("x")])
        self.sessions.leave(s, "v1")
        self.assertEqual(self.sessions.open_ids(), [self.a])
        self.sessions.leave(s, "v2")
        self.assertEqual(self.sessions.open_ids(), [])
        self.assertEqual(self.ws.load_scene(self.a), [_el("x")])

    def test_no_se_suelta_mientras_el_agente_trabaja(self):
        s = self.sessions.open(self.a)
        s.clients.add("v1")
        s.agent_busy = True
        self.sessions.leave(s, "v1")
        self.assertEqual(self.sessions.open_ids(), [self.a])

    def test_cerrar_guarda_y_devuelve_la_sesion_para_avisar_a_sus_ventanas(self):
        s = self.sessions.open(self.a)
        s.clients.add("v1")
        s.board.apply_client_elements([_el("x")])
        closed = self.sessions.close([self.a, "otro"])
        self.assertEqual([c.project_id for c in closed], [self.a])
        self.assertEqual(self.ws.load_scene(self.a), [_el("x")])
        self.assertEqual(self.sessions.open_ids(), [])

    def test_la_pizarra_sigue_al_proyecto_si_se_renombra_abierto(self):
        s = self.sessions.open(self.a)
        self.ws.rename_project(self.a, "A renombrado")
        s.board.apply_client_elements([_el("x")])
        s.board.save()
        self.assertTrue((self.tmp / "Personal" / "A renombrado" / "board" / "scene.json").is_file())
        self.assertEqual(s.board.dir.name, "A renombrado")



class _Ventana:
    """Un WebSocket falso: guarda lo que recibe o, si `lee` es False, nunca acepta nada (una
    pestaña congelada con el búfer lleno)."""
    def __init__(self, lee=True):
        self.lee = lee
        self.recibido = []
        self.cerrada = None

    async def send_json(self, msg):
        if not self.lee:
            await asyncio.Event().wait()
        self.recibido.append(msg)

    async def close(self, code=1000):
        self.cerrada = code


class EnvioATodas(unittest.TestCase):
    """Una ventana que deja de leer no para a nadie más (e2e de v0.1.0: la ejecución, *Cancelar*
    y las demás ventanas esperaban para siempre a que aceptase un mensaje)."""

    def test_la_que_no_lee_sale_y_las_demas_reciben(self):
        buena, parada, yo = _Ventana(), _Ventana(lee=False), _Ventana()
        clientes = {buena, parada, yo}

        async def dos_envios():
            t0 = time.monotonic()
            await send_all(clientes, {"n": 1}, exclude=yo, timeout=0.2)
            await send_all(clientes, {"n": 2}, timeout=0.2)
            return time.monotonic() - t0

        tardado = asyncio.run(dos_envios())
        self.assertLess(tardado, 1.0)               # nunca más que el tope, y solo una vez
        self.assertEqual(buena.recibido, [{"n": 1}, {"n": 2}])
        self.assertEqual(yo.recibido, [{"n": 2}])   # `exclude` no lo recibe
        self.assertEqual(clientes, {buena, yo})     # la parada ya no recibe nada más

    def test_la_que_falla_sale_sin_esperar(self):
        class Rota(_Ventana):
            async def send_json(self, msg):
                raise RuntimeError("conexión cerrada")
        buena, rota = _Ventana(), Rota()
        clientes = {buena, rota}
        asyncio.run(send_all(clientes, {"n": 1}, timeout=5))
        self.assertEqual(clientes, {buena})
        self.assertEqual(buena.recibido, [{"n": 1}])


if __name__ == "__main__":
    unittest.main()
