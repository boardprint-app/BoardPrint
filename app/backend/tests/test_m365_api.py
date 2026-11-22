"""API de Microsoft 365 (docs/PLAN_M365.md §4, §9: M7).

Reglas: sin red, sin sesión o con el archivo ya fuera de la nube, *Actualizar* deja la tarjeta
`sin_conexion` con su última copia, nunca un error, y lo avisa por el WebSocket; *Guardar en la
nube* solo acepta tarjetas de archivo. Se llama a las funciones de las rutas sin HTTP.

Ejecutar desde app/backend:  python -m unittest tests.test_m365_api -v
"""
import asyncio
import unittest

from fastapi import FastAPI, HTTPException

from pizarra import m365_api
from pizarra.m365_graph import Offline

from tests.helpers import new_board
from tests.test_m365_files import FakeGraph


class FakeAuth:
    def __init__(self):
        self.signed = True

    def configured(self):
        return True

    def account(self):
        return {"username": "a@outlook.com", "name": "A", "kind": "personal"} if self.signed else None

    def token(self, scopes=None, fresh=False):
        return "t"

    def has_scopes(self, scopes):
        return False


def offline(*args):
    raise Offline("sin red")


class Rutas(unittest.TestCase):
    def setUp(self):
        self.board = new_board()
        g = FakeGraph()
        g.add("i1", "a.txt", b"v1")
        from pizarra import m365_files
        self.el, _ = m365_files.bring(self.board, g, "d1", "i1", 0, 0)
        self.sent = []

        async def broadcast(session, msg):
            self.sent.append(msg)

        async def nothing(*a, **k):
            return None

        self.app = FastAPI()
        m365_api.register(self.app, auth=FakeAuth(), sessions=None, broadcast=broadcast,
                          board_for=lambda pid: (self.board, "sesion"),
                          board_changed=nothing, probe_now=nothing, transport=offline)

    def route(self, path, method):
        return next(r.endpoint for r in self.app.routes
                    if getattr(r, "path", "") == path and method in r.methods)

    def test_sin_red_es_sin_conexion_y_lo_avisa(self):
        fn = self.route("/api/projects/{pid}/m365/cards/{cid}/refresh", "POST")
        got = asyncio.run(fn("p", self.el["id"], {"force": False}))
        self.assertEqual(got, {"state": "sin_conexion"})
        self.assertEqual(self.sent[-1], {"type": "m365", "cards": {self.el["id"]: "sin_conexion"}})
        self.assertEqual(self.board.card_path(self.el).read_bytes(), b"v1")

    def test_guardar_solo_archivos(self):
        fn = self.route("/api/projects/{pid}/m365/cards/{cid}/upload", "POST")
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(fn("p", "no-existe", {}))
        self.assertEqual(cm.exception.status_code, 404)

    def test_estan_todas_las_rutas(self):
        """Todas las del docstring de m365_api, también la cuenta (se quedó fuera una vez)."""
        have = {(m, r.path) for r in self.app.routes for m in getattr(r, "methods", ())}
        for want in [("GET", "/api/m365"), ("POST", "/api/m365/sign-in"),
                     ("POST", "/api/m365/sign-out"), ("GET", "/api/m365/drive"),
                     ("GET", "/api/m365/drive/search"), ("POST", "/api/projects/{pid}/m365/bring"),
                     ("GET", "/api/m365/sites"), ("GET", "/api/m365/sites/{site_id}/drives"),
                     ("POST", "/api/m365/open"), ("GET", "/api/m365/mail/folders"),
                     ("GET", "/api/m365/mail"), ("POST", "/api/projects/{pid}/m365/mail/bring"),
                     ("POST", "/api/projects/{pid}/m365/cards/{cid}/refresh"),
                     ("POST", "/api/projects/{pid}/m365/cards/{cid}/upload")]:
            self.assertIn(want, have)

    def test_vista_sin_sharepoint(self):
        self.assertEqual(m365_api.view(FakeAuth())["sharepoint"], False)


if __name__ == "__main__":
    unittest.main()
