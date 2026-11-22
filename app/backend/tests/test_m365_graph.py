"""Cliente de Microsoft Graph (docs/PLAN_M365.md §8, §9).

Reglas: `get_all` sigue `@odata.nextLink` hasta el final y nunca más de `MAX_PAGES`; un 429 o
un 503 espera su `Retry-After` (recortado) y reintenta como mucho `MAX_RETRIES` veces; un 401
pide token nuevo una sola vez; un fallo de red da `Offline`, nunca una excepción sin tipo; una
URL de sesión de subida va sin `Authorization`.

Ejecutar desde app/backend:  python -m unittest tests.test_m365_graph -v
"""
import json
import unittest

from pizarra import m365_graph
from pizarra.m365_graph import Graph, GraphError, Offline


class Resp:
    def __init__(self, status=200, payload=None, headers=None, content=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload
        self.content = content if content is not None else (
            json.dumps(payload).encode() if payload is not None else b"")

    def json(self):
        if self._payload is None:
            raise ValueError("sin json")
        return self._payload


class Recorded:
    """Un transporte que devuelve las respuestas en orden y guarda lo que se le pidió."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def graph(*responses):
    tokens = []

    def token_fn(scopes, fresh):
        tokens.append(fresh)
        return "nuevo" if fresh else "viejo"

    transport = Recorded(*responses)
    waits = []
    return Graph(token_fn, transport, sleep=waits.append), transport, tokens, waits


class Paginas(unittest.TestCase):
    def test_sigue_next_link_hasta_el_final(self):
        g, t, _, _ = graph(
            Resp(payload={"value": [1, 2], "@odata.nextLink": "https://graph.microsoft.com/v1.0/p2"}),
            Resp(payload={"value": [3], "@odata.nextLink": "https://graph.microsoft.com/v1.0/p3"}),
            Resp(payload={"value": [4]}))
        self.assertEqual(g.get_all("/me/drive/root/children"), [1, 2, 3, 4])
        self.assertEqual(t.calls[0][1], m365_graph.GRAPH + "/me/drive/root/children")
        self.assertEqual(t.calls[2][1], "https://graph.microsoft.com/v1.0/p3")

    def test_nunca_mas_de_max_pages(self):
        loop = {"value": [0], "@odata.nextLink": "https://graph.microsoft.com/v1.0/otra"}
        g, t, _, _ = graph(*[Resp(payload=loop) for _ in range(m365_graph.MAX_PAGES + 5)])
        self.assertEqual(len(g.get_all("/x")), m365_graph.MAX_PAGES)
        self.assertEqual(len(t.calls), m365_graph.MAX_PAGES)


class Reintentos(unittest.TestCase):
    def test_429_espera_su_retry_after(self):
        g, t, _, waits = graph(Resp(429, headers={"Retry-After": "7"}), Resp(payload={"ok": 1}))
        self.assertEqual(g.get("/me"), {"ok": 1})
        self.assertEqual(waits, [7.0])

    def test_retry_after_largo_se_recorta_y_sin_el_espera_lo_de_por_defecto(self):
        g, t, _, waits = graph(Resp(503, headers={"Retry-After": "9999"}), Resp(429),
                               Resp(payload={}))
        g.get("/me")
        self.assertEqual(waits, [m365_graph.MAX_WAIT, m365_graph.DEFAULT_WAIT])

    def test_como_mucho_max_retries(self):
        g, t, _, waits = graph(*[Resp(429, payload={"error": {"code": "TooMany"}})
                                 for _ in range(m365_graph.MAX_RETRIES + 1)])
        with self.assertRaises(GraphError) as cm:
            g.get("/me")
        self.assertEqual(cm.exception.status, 429)
        self.assertEqual(len(waits), m365_graph.MAX_RETRIES)

    def test_401_pide_token_nuevo_una_sola_vez(self):
        g, t, tokens, _ = graph(Resp(401), Resp(401, payload={"error": {"code": "InvalidAuth"}}))
        with self.assertRaises(GraphError) as cm:
            g.get("/me")
        self.assertEqual(cm.exception.code, "InvalidAuth")
        self.assertEqual(tokens, [False, True])
        self.assertEqual(t.calls[1][2]["Authorization"], "Bearer nuevo")

    def test_401_y_luego_bien(self):
        g, t, tokens, _ = graph(Resp(401), Resp(payload={"id": "yo"}))
        self.assertEqual(g.get("/me"), {"id": "yo"})


class Fallos(unittest.TestCase):
    def test_fallo_de_red_es_offline(self):
        for exc in (Offline("sin red"), ConnectionError("x"), TimeoutError("y")):
            g, _, _, _ = graph(exc)
            with self.assertRaises(Offline):
                g.get("/me")

    def test_error_sin_json(self):
        g, _, _, _ = graph(Resp(500, content=b"<html>"))
        with self.assertRaises(GraphError) as cm:
            g.get("/me")
        self.assertEqual(cm.exception.status, 500)

    def test_sesion_de_subida_sin_authorization(self):
        g, t, tokens, _ = graph(Resp(payload={"id": "f"}))
        g.request("PUT", "https://subida.sharepoint.com/sesion", body=b"x", auth=False)
        self.assertNotIn("Authorization", t.calls[0][2])
        self.assertEqual(tokens, [])

    def test_post_manda_json(self):
        g, t, _, _ = graph(Resp(201, payload={"id": "m"}))
        self.assertEqual(g.post("/me/messages", {"subject": "Hola"}), {"id": "m"})
        method, url, headers, body = t.calls[0]
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"subject": "Hola"})


if __name__ == "__main__":
    unittest.main()
