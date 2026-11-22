"""Cliente mínimo de Microsoft Graph (docs/PLAN_M365.md §8).

`Graph(token_fn, transport)`: `get`, `get_all` (sigue `@odata.nextLink`), `download`, `put`,
`post`. Un 429 o un 503 se reintenta con su `Retry-After` (como mucho `MAX_RETRIES` veces); un
401, una sola vez con token nuevo. Un fallo de red da `Offline`, que la interfaz enseña como
*sin conexión* (M7), nunca una excepción sin tipo.

`token_fn(scopes, fresh)` es `Auth.token`. `transport(method, url, headers, body, timeout)`
devuelve algo con `status_code`, `headers`, `content` y `json()`: `requests` en la app, uno
grabado en los tests.
"""
import json as jsonlib
import time

from pizarra.m365_auth import SCOPES_BASE, M365Error

GRAPH = "https://graph.microsoft.com/v1.0"
MAX_RETRIES = 3
MAX_WAIT = 60                   # s: un Retry-After más largo se recorta
DEFAULT_WAIT = 2                # s: un 429 o 503 sin Retry-After
MAX_PAGES = 50                  # get_all nunca sigue más páginas (un bucle del servidor)
TIMEOUT = 30                    # s por petición


class Offline(M365Error):
    """Sin red, o Microsoft no contesta."""


class GraphError(M365Error):
    def __init__(self, status, code="", message=""):
        super().__init__(f"{status} {code}: {message}".strip())
        self.status, self.code, self.message = status, code, message


def requests_transport(method, url, headers, body, timeout):
    import requests
    try:
        # Una redirección a otro dominio (la descarga de /content) no lleva el Authorization:
        # requests lo quita solo.
        return requests.request(method, url, headers=headers, data=body, timeout=timeout)
    except requests.RequestException as exc:
        raise Offline(str(exc)) from exc


def _retry_after(response):
    value = (response.headers or {}).get("Retry-After")
    try:
        wait = float(value)
    except (TypeError, ValueError):
        wait = DEFAULT_WAIT
    return max(0.0, min(wait, MAX_WAIT))


def _error(response):
    try:
        err = (response.json() or {}).get("error") or {}
    except ValueError:
        err = {}
    return GraphError(response.status_code, err.get("code", ""), err.get("message", ""))


class Graph:
    def __init__(self, token_fn, transport=requests_transport, sleep=time.sleep):
        self.token_fn = token_fn
        self.transport = transport
        self.sleep = sleep

    def request(self, method, path, *, body=None, json=None, headers=None,
                scopes=SCOPES_BASE, auth=True):
        """Una petición con sus reintentos. `path` es relativo a v1.0 o una URL entera (un
        nextLink o una sesión de subida, que va sin `auth`)."""
        url = path if path.startswith("https://") else GRAPH + path
        extra = dict(headers or {})
        if json is not None:
            body = jsonlib.dumps(json).encode("utf-8")
            extra.setdefault("Content-Type", "application/json")
        fresh, waits = False, 0
        while True:
            sent = dict(extra)
            if auth:
                sent["Authorization"] = "Bearer " + self.token_fn(scopes, fresh)
            try:
                response = self.transport(method, url, sent, body, TIMEOUT)
            except Offline:
                raise
            except OSError as exc:
                raise Offline(str(exc)) from exc
            status = response.status_code
            if status == 401 and auth and not fresh:
                fresh = True
                continue
            if status in (429, 503) and waits < MAX_RETRIES:
                waits += 1
                self.sleep(_retry_after(response))
                continue
            if status >= 400:
                raise _error(response)
            return response

    def get(self, path, **kw):
        return self.request("GET", path, **kw).json()

    def get_all(self, path, **kw):
        """Todos los `value` de una lista, siguiendo `@odata.nextLink` hasta el final."""
        out, url = [], path
        for _ in range(MAX_PAGES):
            page = self.get(url, **kw)
            out.extend(page.get("value") or [])
            url = page.get("@odata.nextLink")
            if not url:
                return out
        return out

    def download(self, path, **kw):
        return self.request("GET", path, **kw).content

    def put(self, path, data, content_type="application/octet-stream", **kw):
        return self.request("PUT", path, body=data, headers={"Content-Type": content_type},
                            **kw).json()

    def post(self, path, payload, **kw):
        response = self.request("POST", path, json=payload, **kw)
        return response.json() if response.content else {}
