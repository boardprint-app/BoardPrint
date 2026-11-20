"""Aprovisionamiento: los proveedores del usuario y las ofertas de cada ficha (docs/PLAN_APROVISIONAMIENTO.md
§2-§4, A1-A11, R1; D34 de PLAN_PIZARRA).

Aquí está lo determinista; el agente que busca (`agent_supply`) y las rutas (`supply_api`) lo
usan, nunca al revés.

- **Proveedores** (A2): lista ordenada de `{nombre, dominio, tipos}` en `profile/proveedores.toml`.
  `tipos` vacío = todos. El orden es la preferencia.
- **Dominios** (A1): `domain_of(url, dominios)` dice a qué dominio de la lista pertenece una URL
  (el mismo host o un subdominio), y es lo que usa `can_use_tool` para dejar pasar `WebFetch`.
- **Ofertas** (A4, A7-A10): por clave de ficha, `exacta` o `equivalente`, de `agente` o a `mano`,
  con su fecha. Un precio o plazo vacío es desconocido (None), nunca 0. Una oferta caducada se
  enseña con `vigente: false` y nunca se borra sola.
- **La prueba de una oferta del agente** (R1, `SearchLog`): su cita tiene que estar tal cual en
  lo que devolvió una herramienta en esa búsqueda (la página si `via` es `pagina`), y su URL
  se abrió o salió en los resultados. Si no, no se guarda.
"""
import datetime
import json
import re
import tomllib
import uuid
from urllib.parse import urlsplit

import tomli_w

from pizarra import i18n
from pizarra.validation import ValidationError

PROVIDERS_MAX = 20
DEFAULT_EXPIRY_DAYS, EXPIRY_MIN, EXPIRY_MAX = 7, 1, 90          # A10
DEFAULT_SEARCH_BUDGET_USD = 0.25                                # A5
SEARCHES_PER_MESSAGE = 5                                        # A6
MATCHES = ("exacta", "equivalente")                             # A4
ORIGINS = ("agente", "mano")                                    # A7
VIAS = ("pagina", "buscador")                                   # R1
TEXT_MAX = 400                                                  # cita, nota, disponibilidad
OFFERS_SCHEMA = 1
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_URL_IN_RESULTS = re.compile(r'"url"\s*:\s*"([^"]+)"')


def _err(key, **vars):
    return ValidationError(i18n.t(key, **vars))


# ------------------------------------------------------------------- proveedores (A2)
def normalize_domain(value):
    """`es.RS-online.com.` -> `es.rs-online.com`. Sin esquema, ruta, puerto ni usuario; otro
    valor es `ValidationError` con el motivo."""
    text = str(value or "").strip().lower().rstrip(".")
    if not text or not _DOMAIN.match(text):
        raise _err("proveedores.dominio_no_valido", dominio=repr(value))
    return text


def check_providers(items, types=None):
    """La lista que se guarda, en el orden en que llega. `types` (los de la librería), si se
    da, es lo que vale en `tipos`. Un dominio repetido, vacío o mal escrito (con esquema, ruta o
    puerto), un nombre vacío o más de `PROVIDERS_MAX` proveedores son `ValidationError`: no se
    guarda nada. Un subdominio de otro de la lista sí vale (`es.rs-online.com` y
    `rs-online.com` pueden ser dos proveedores)."""
    if not isinstance(items, list):
        raise _err("proveedores.no_es_lista")
    if len(items) > PROVIDERS_MAX:
        raise _err("proveedores.demasiados", max=PROVIDERS_MAX)
    out, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise _err("proveedores.no_es_lista")
        name = str(item.get("nombre") or "").strip()[:80]
        if not name:
            raise _err("proveedores.sin_nombre")
        domain = normalize_domain(item.get("dominio"))
        if domain in seen:
            raise _err("proveedores.dominio_repetido", dominio=domain)
        seen.add(domain)
        tipos = item.get("tipos") or []
        if not isinstance(tipos, list) or not all(isinstance(t, str) and t for t in tipos):
            raise _err("proveedores.tipos_no_validos", nombre=name)
        if types is not None:
            unknown = [t for t in tipos if t not in types]
            if unknown:
                raise _err("proveedores.tipo_desconocido", nombre=name, tipo=unknown[0])
        out.append({"nombre": name, "dominio": domain, "tipos": list(dict.fromkeys(tipos))})
    return out


def parse_providers(text):
    """El TOML de `proveedores.toml` como lista (vacía si no hay texto). Uno roto o con un
    proveedor que no vale es `ValidationError`."""
    if not text:
        return []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _err("proveedores.ilegible", motivo=exc) from None
    return check_providers(data.get("proveedor", []))


def dump_providers(providers):
    return tomli_w.dumps({"esquema": 1, "proveedor": [
        {k: v for k, v in p.items() if not (k == "tipos" and not v)} for p in providers]})


def providers_for(providers, type_):
    """Los que cubren `type_`, en su orden: sin `tipos`, todos; con `tipos`, solo esos."""
    return [p for p in providers if not p["tipos"] or type_ in p["tipos"]]


def host_of(url):
    try:
        parts = urlsplit(str(url))
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host if parts.scheme in ("http", "https") else ""


def domain_of(url, domains):
    """El dominio de `domains` al que pertenece `url` (el mismo host o un subdominio suyo), o
    None. `misumi-ec.com.evil.io` no es de `misumi-ec.com`, ni `xrs-online.com` de
    `rs-online.com`."""
    host = host_of(url)
    if not host:
        return None
    for d in domains:
        if host == d or host.endswith("." + d):
            return d
    return None


# ------------------------------------------------------- lo que devolvieron las herramientas
def _norm(text):
    return " ".join(str(text).replace(" ", " ").split()).casefold()


class SearchLog:
    """Lo que pasó en una búsqueda (R1): las páginas abiertas con su texto, los resultados de
    `WebSearch` con sus URLs. Contra esto se comprueba una oferta del agente."""

    def __init__(self):
        self.pages = {}          # url -> texto (solo las que no dieron error)
        self.failed = set()      # url que dio error (403, sin respuesta)
        self.searches = []       # (consulta, texto, [urls])
        self.queries = []

    def page(self, url, text, is_error=False):
        if is_error:
            self.failed.add(url)
        else:
            self.pages[url] = self.pages.get(url, "") + "\n" + str(text)

    def search(self, query, text):
        self.queries.append(query)
        self.searches.append((query, str(text), _URL_IN_RESULTS.findall(str(text))))

    def result_urls(self):
        return {u for _, _, urls in self.searches for u in urls}

    def quoted_in_page(self, url, quote):
        return url in self.pages and _norm(quote) in _norm(self.pages[url])

    def quoted_anywhere(self, quote):
        q = _norm(quote)
        return any(q in _norm(t) for t in self.pages.values()) or \
            any(q in _norm(t) for _, t, _ in self.searches)


# ------------------------------------------------------------------------- ofertas
def now_iso(now=None):
    return (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds")


def _parse_date(value):
    try:
        d = datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.astimezone()


def is_current(offer, days, now=None):
    """Vigente si `fecha` + `days` días > ahora (A10). Sin fecha legible, nunca."""
    d = _parse_date(offer.get("fecha"))
    now = now or datetime.datetime.now().astimezone()
    return d is not None and d + datetime.timedelta(days=days) > now


def check_expiry_days(value):
    if isinstance(value, bool) or not isinstance(value, int) or \
            not EXPIRY_MIN <= value <= EXPIRY_MAX:
        raise _err("proveedores.caducidad_no_valida", min=EXPIRY_MIN, max=EXPIRY_MAX,
                   valor=repr(value))
    return value


def _number(value, field, integer=False):
    """None (desconocido) o un número positivo; 0, negativo o texto es error. Nunca se
    convierte un vacío en 0 (como la cantidad del stock, D33)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value <= 0:
        raise _err("ofertas.numero_no_valido", campo=field, valor=repr(value))
    return int(value) if integer else float(value)


def _text(value, limit=TEXT_MAX):
    return " ".join(str(value or "").split())[:limit]


def _common(data, clave):
    if not isinstance(data, dict):
        raise _err("ofertas.no_es_objeto")
    match = data.get("coincidencia", "exacta")
    if match not in MATCHES:
        raise _err("ofertas.coincidencia_no_valida", valor=repr(match))
    currency = str(data.get("moneda") or "").strip().upper()
    precio = _number(data.get("precio"), "precio")
    if precio is not None and not _CURRENCY.match(currency):
        raise _err("ofertas.moneda_no_valida", valor=repr(data.get("moneda")))
    if currency and not _CURRENCY.match(currency):
        raise _err("ofertas.moneda_no_valida", valor=repr(data.get("moneda")))
    return {"id": uuid.uuid4().hex[:12], "clave": clave, "coincidencia": match,
            "proveedor": _text(data.get("proveedor"), 80),
            "referencia": _text(data.get("referencia"), 120),
            "fabricante": _text(data.get("fabricante"), 120),
            "precio": precio, "moneda": currency or None,
            "por_cantidad": _number(data.get("por_cantidad"), "por_cantidad", True) or 1,
            "plazo_dias": _number(data.get("plazo_dias"), "plazo_dias", True),
            "disponibilidad": _text(data.get("disponibilidad")),
            "nota": _text(data.get("nota"))}


def check_manual_offer(data, clave, now=None):
    """Una oferta a mano (A7): proveedor obligatorio; la URL, si la hay, http(s)."""
    offer = _common(data, clave)
    if not offer["proveedor"]:
        raise _err("ofertas.sin_proveedor")
    url = str(data.get("url") or "").strip()
    if url and not host_of(url):
        raise _err("ofertas.url_no_valida", url=repr(url))
    offer.update({"dominio": host_of(url) or None, "url": url or None,
                  "via": None, "cita": _text(data.get("cita")), "origen": "mano",
                  "fecha": now_iso(now)})
    return offer


_NUMBER = re.compile(r"\d[\d.,   ]*\d|\d")


def _readings(token):
    """Lo que puede valer «1.234,50», «1,234.50», «0,857» o «12»: con coma decimal y con punto
    decimal (una cifra de la web no dice cuál de los dos usa)."""
    t = re.sub(r"[   ]", "", token)
    out = set()
    for dec, thou in ((",", "."), (".", ",")):
        try:
            out.add(float(t.replace(thou, "").replace(dec, ".")))
        except ValueError:
            pass
    return out


def price_in(price, quote):
    """¿Está `price` escrito en `quote` (R3)? Con coma o punto decimal, con o sin miles y con
    ceros de más («2,950» vale para 2.95). Así un precio que el agente saca de otro tramo, o que se
    inventa, no pasa aunque la cita sea literal."""
    return any(abs(v - price) < 0.0005 for tok in _NUMBER.findall(str(quote))
               for v in _readings(tok))


def check_agent_offer(data, clave, providers, log, now=None):
    """Una oferta que apunta el agente (R1). Se guarda solo si:
    - su `url` es de uno de `providers` (los de la búsqueda) y el proveedor es ese;
    - `via: pagina`: la URL se abrió sin error y la cita está en esa página;
      `via: buscador`: la URL salió en los resultados de un `WebSearch` y la cita está en lo
      que devolvió alguna herramienta;
    - la cita no está vacía; la moneda es ISO 4217; precio y plazo, positivos o vacíos;
    - el precio, si lo hay, está escrito en la cita (R3: no el de otro tramo).
    Si no, `ValidationError` con el motivo, que se le devuelve al agente."""
    offer = _common(data, clave)
    url = str(data.get("url") or "").strip()
    domain = domain_of(url, [p["dominio"] for p in providers])
    if domain is None:
        raise _err("ofertas.dominio_fuera", url=repr(url))
    provider = next(p for p in providers if p["dominio"] == domain)
    quote = _text(data.get("cita"))
    if not quote:
        raise _err("ofertas.sin_cita")
    via = data.get("via")
    if via == "pagina":
        if url not in log.pages:
            raise _err("ofertas.pagina_no_abierta", url=url)
        if not log.quoted_in_page(url, quote):
            raise _err("ofertas.cita_no_esta", url=url)
    elif via == "buscador":
        if url not in log.result_urls():
            raise _err("ofertas.url_no_en_resultados", url=url)
        if not log.quoted_anywhere(quote):
            raise _err("ofertas.cita_no_esta", url=url)
    else:
        raise _err("ofertas.via_no_valida", valor=repr(via))
    if offer["precio"] is not None and not price_in(offer["precio"], quote):
        raise _err("ofertas.precio_no_en_cita", precio=offer["precio"])
    offer.update({"proveedor": provider["nombre"], "dominio": domain, "url": url, "via": via,
                  "cita": quote, "origen": "agente", "fecha": now_iso(now)})
    return offer


def replace_agent_offers(offers, clave, domains, new):
    """Buscar otra vez (§3): quita las del agente de `clave` en `domains` y añade `new`. Las
    de `mano` nunca se tocan."""
    domains = set(domains)
    kept = [o for o in offers
            if not (o.get("clave") == clave and o.get("origen") == "agente"
                    and o.get("dominio") in domains)]
    return kept + list(new)


def _provider_rank(providers):
    order = {p["dominio"]: i for i, p in enumerate(providers)}
    names = {p["nombre"].casefold(): i for i, p in enumerate(providers)}
    return lambda o: order.get(o.get("dominio"),
                               names.get(str(o.get("proveedor", "")).casefold(), len(order)))


def offers_for(offers, clave, providers, days, now=None):
    """Las ofertas de `clave` con `vigente`, en el orden de §3: exactas vigentes por orden de
    proveedor (una de `pagina` antes que una de `buscador`), exactas caducadas, y aparte los
    equivalentes. -> {exactas, equivalentes}."""
    rank = _provider_rank(providers)
    mine = [dict(o, vigente=is_current(o, days, now)) for o in offers if o.get("clave") == clave]
    key = lambda o: (not o["vigente"], rank(o), o.get("via") == "buscador",   # noqa: E731
                     -(_parse_date(o.get("fecha")) or datetime.datetime.min.replace(
                         tzinfo=datetime.timezone.utc)).timestamp())
    return {"exactas": sorted((o for o in mine if o["coincidencia"] == "exacta"), key=key),
            "equivalentes": sorted((o for o in mine if o["coincidencia"] == "equivalente"),
                                   key=key)}


def best_offer(offers, clave, providers, days, now=None):
    """La mejor exacta vigente de `clave`, o None. Un equivalente nunca lo es (A4)."""
    exact = offers_for(offers, clave, providers, days, now)["exactas"]
    return exact[0] if exact and exact[0]["vigente"] else None


def needs_search(offers, clave, providers, days, now=None):
    """¿Hay que buscarla? No si tiene una exacta vigente (A6); un equivalente no cuenta."""
    return best_offer(offers, clave, providers, days, now) is None


# --------------------------------------------------------- el fichero de ofertas (A8)
def empty_offers():
    return {"esquema": OFFERS_SCHEMA, "ofertas": [], "consumo": {"usd": 0.0, "busquedas": 0}}


def parse_offers(text):
    """`ofertas.json` -> dict. Uno ilegible o de un esquema que no se entiende vale vacío (es
    una caché: nunca para la app). Las ofertas sin clave se descartan."""
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("esquema") != OFFERS_SCHEMA:
        return empty_offers()
    offers = [o for o in data.get("ofertas") or [] if isinstance(o, dict) and o.get("clave")]
    usage = data.get("consumo") if isinstance(data.get("consumo"), dict) else {}
    return {"esquema": OFFERS_SCHEMA, "ofertas": offers,
            "consumo": {"usd": float(usage.get("usd") or 0.0),
                        "busquedas": int(usage.get("busquedas") or 0)}}


def dump_offers(data):
    return json.dumps(data, ensure_ascii=False, indent=1)


def add_usage(data, usd):
    data["consumo"]["usd"] = round(data["consumo"]["usd"] + float(usd or 0.0), 6)
    data["consumo"]["busquedas"] += 1
    return data
