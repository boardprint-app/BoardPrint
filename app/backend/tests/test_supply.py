"""Aprovisionamiento: proveedores y ofertas (docs/PLAN_APROVISIONAMIENTO.md §6, A1-A11, R1).

Reglas que protegen:
- **Proveedores** (A2): nunca se guarda una lista con un dominio repetido, vacío o con esquema,
  ruta o puerto; el orden guardado es el que se envió; sin `tipos` cubre todos, con `tipos`
  nunca se usa para otro tipo.
- **Dominios** (A1): una URL es de un proveedor solo si su host es el dominio o un subdominio
  suyo; nunca `misumi-ec.com.evil.io` ni `xrs-online.com`, y da igual la mayúscula o el puerto.
- **Oferta del agente** (R1): nunca se guarda una cuya URL ni se abrió ni salió en los
  resultados, de un dominio que no es de su proveedor, con una cita que no está tal cual en lo
  que devolvió una herramienta (la página, si `via` es `pagina`), sin cita o con una moneda que
  no es ISO 4217. Una página que dio error no cuenta como abierta.
- **El precio está en la cita** (R3): nunca se guarda una oferta del agente cuyo precio no está
  escrito en su cita (con coma o punto decimal), aunque la cita sea literal.
- **Desconocido no es cero**: un precio o plazo vacío se guarda como None, nunca 0; un 0 es error.
- **Caducidad** (A10): una oferta con fecha + caducidad <= ahora sale con `vigente: false` y
  nunca se borra sola.
- **Buscar otra vez**: sustituye las del agente de esa clave y esos proveedores, nunca las de mano.
- **Equivalentes** (A4): un equivalente nunca es la mejor oferta ni evita volver a buscar.
- **Almacenamiento**: los dos ficheros van en `profile/`, y un `ofertas.json` roto vale vacío.

Ejecutar desde app/backend:  python -m unittest tests.test_supply -v
"""
import asyncio
import datetime
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from pizarra import supply
from pizarra.agent_supply import SupplyAgent
from pizarra.settings import Settings
from pizarra.library import WorkspaceLibrary
from pizarra.storage import LocalWorkspace, NotFound
from pizarra.supply_api import Busy, SupplyService
from pizarra.validation import ValidationError

TZ = datetime.timezone(datetime.timedelta(hours=1))
NOW = datetime.datetime(2026, 11, 20, 18, 0, tzinfo=TZ)
RS = {"nombre": "RS", "dominio": "rs-online.com", "tipos": []}
FARNELL = {"nombre": "Farnell", "dominio": "farnell.com", "tipos": ["element"]}
PROVS = [RS, FARNELL]
SEARCH_TEXT = ('Web search results for query: "IRF540N precio"  Links: [{"title":"IRF540N",'
               '"url":"https://uk.farnell.com/multicomp-pro/irf540n/dp/4472945"}]  '
               '- **Multicomp Pro (Farnell, Reino Unido):** £1.15 sin IVA por unidad.')
PAGE_URL = "https://uk.rs-online.com/web/p/mosfets/2449536"
PAGE_TEXT = "N-channel MOSFET IRF540N 33A 100V\nPrecio   2,95 € sin IVA (por unidad)"


def offer(**kw):
    base = {"coincidencia": "exacta", "referencia": "IRF540N", "precio": 2.95, "moneda": "EUR",
            "url": PAGE_URL, "via": "pagina", "cita": "Precio 2,95 € sin IVA"}
    base.update(kw)
    return base


def log_with_page_and_search():
    log = supply.SearchLog()
    log.page(PAGE_URL, PAGE_TEXT)
    log.search("IRF540N precio", SEARCH_TEXT)
    return log


class LosProveedores(unittest.TestCase):
    def test_el_orden_guardado_es_el_que_se_envio(self):
        out = supply.check_providers([FARNELL, RS])
        self.assertEqual([p["nombre"] for p in out], ["Farnell", "RS"])

    def test_el_dominio_se_normaliza_y_uno_con_esquema_ruta_o_puerto_no_vale(self):
        self.assertEqual(supply.normalize_domain(" ES.RS-Online.com. "), "es.rs-online.com")
        for bad in ("https://rs-online.com", "rs-online.com/es", "rs-online.com:443", "", "rs",
                    "user@rs-online.com", None):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                supply.normalize_domain(bad)

    def test_un_dominio_repetido_no_guarda_nada(self):
        with self.assertRaises(ValidationError):
            supply.check_providers([RS, dict(RS, nombre="RS otra vez", dominio="RS-online.com")])

    def test_un_subdominio_de_otro_si_vale(self):
        out = supply.check_providers([dict(RS, dominio="es.rs-online.com"), RS])
        self.assertEqual(len(out), 2)

    def test_sin_nombre_mas_de_veinte_o_un_tipo_desconocido_no_valen(self):
        with self.assertRaises(ValidationError):
            supply.check_providers([dict(RS, nombre=" ")])
        many = [{"nombre": f"P{i}", "dominio": f"p{i}.com"} for i in range(21)]
        with self.assertRaises(ValidationError):
            supply.check_providers(many)
        with self.assertRaises(ValidationError):
            supply.check_providers([FARNELL], types={"reducer"})

    def test_sin_tipos_cubre_todos_y_con_tipos_solo_esos(self):
        provs = supply.check_providers(PROVS)
        self.assertEqual([p["nombre"] for p in supply.providers_for(provs, "element")],
                         ["RS", "Farnell"])
        self.assertEqual([p["nombre"] for p in supply.providers_for(provs, "reducer")], ["RS"])

    def test_el_toml_se_lee_igual_que_se_escribe(self):
        provs = supply.check_providers(PROVS)
        self.assertEqual(supply.parse_providers(supply.dump_providers(provs)), provs)
        self.assertEqual(supply.parse_providers(None), [])
        with self.assertRaises(ValidationError):
            supply.parse_providers("esto = no es [toml")


class LosDominios(unittest.TestCase):
    def test_el_mismo_host_o_un_subdominio(self):
        d = ["rs-online.com", "misumi-ec.com"]
        self.assertEqual(supply.domain_of("https://rs-online.com/x", d), "rs-online.com")
        self.assertEqual(supply.domain_of("https://ES.RS-ONLINE.COM:443/web/p/1", d),
                         "rs-online.com")
        self.assertEqual(supply.domain_of("http://es.misumi-ec.com/vona2/", d), "misumi-ec.com")

    def test_nunca_un_subdominio_falso_ni_otro_esquema(self):
        d = ["rs-online.com", "misumi-ec.com"]
        for url in ("https://misumi-ec.com.evil.io/x", "https://xrs-online.com/",
                    "https://evil.io/?u=https://rs-online.com", "ftp://rs-online.com/x",
                    "rs-online.com/x", "https://user@evil.io/rs-online.com", "", None):
            with self.subTest(url=url):
                self.assertIsNone(supply.domain_of(url, d))


class LaOfertaDelAgente(unittest.TestCase):
    def setUp(self):
        self.provs = supply.check_providers(PROVS)
        self.log = log_with_page_and_search()

    def check(self, **kw):
        return supply.check_agent_offer(offer(**kw), "IRF540N", self.provs, self.log, NOW)

    def test_de_una_pagina_abierta_con_la_cita_dentro_se_guarda(self):
        o = self.check()
        self.assertEqual((o["proveedor"], o["dominio"], o["via"], o["origen"]),
                         ("RS", "rs-online.com", "pagina", "agente"))
        self.assertEqual(o["fecha"], "2026-11-20T18:00:00+01:00")

    def test_la_cita_se_compara_sin_espacios_ni_mayusculas_pero_tiene_que_estar(self):
        self.check(cita="precio  2,95 €   SIN IVA")
        with self.assertRaises(ValidationError):
            self.check(cita="Precio 2,59 € sin IVA")

    def test_una_pagina_que_no_se_abrio_o_dio_error_no_cuenta(self):
        with self.assertRaises(ValidationError):
            self.check(url="https://uk.rs-online.com/web/p/otra/1")
        self.log.page("https://uk.rs-online.com/web/p/403", "The server returned HTTP 403",
                      is_error=True)
        with self.assertRaises(ValidationError):
            self.check(url="https://uk.rs-online.com/web/p/403", cita="HTTP 403")

    def test_via_pagina_no_vale_con_una_cita_que_solo_esta_en_el_buscador(self):
        with self.assertRaises(ValidationError):
            self.check(cita="£1.15 sin IVA por unidad")

    def test_del_buscador_con_la_url_en_los_resultados_y_la_cita_en_lo_devuelto(self):
        o = self.check(url="https://uk.farnell.com/multicomp-pro/irf540n/dp/4472945",
                       via="buscador", cita="£1.15 sin IVA por unidad", moneda="GBP",
                       precio=1.15)
        self.assertEqual((o["proveedor"], o["via"]), ("Farnell", "buscador"))

    def test_del_buscador_con_una_url_que_no_salio_no_se_guarda(self):
        with self.assertRaises(ValidationError):
            self.check(url="https://uk.farnell.com/otra/dp/1", via="buscador",
                       cita="£1.15 sin IVA por unidad", moneda="GBP")

    def test_de_un_dominio_fuera_de_los_proveedores_de_la_busqueda_no_se_guarda(self):
        self.log.page("https://www.amazon.es/irf540n", PAGE_TEXT)
        with self.assertRaises(ValidationError):
            self.check(url="https://www.amazon.es/irf540n")
        with self.assertRaises(ValidationError):    # Farnell no cubre reducer: no está en la búsqueda
            supply.check_agent_offer(
                offer(url="https://uk.farnell.com/multicomp-pro/irf540n/dp/4472945",
                      via="buscador", cita="£1.15 sin IVA por unidad", moneda="GBP"),
                "CSF-14", supply.providers_for(self.provs, "reducer"), self.log, NOW)

    def test_el_precio_tiene_que_estar_escrito_en_la_cita(self):
        # R3: la cita literal de los tramos y el precio de otro tramo (el más barato)
        self.log.page(PAGE_URL, "1,48 € por unidad para 1, bajando a 1,03 € desde 100")
        self.check(precio=1.48, cita="1,48 € por unidad para 1")
        with self.assertRaises(ValidationError):
            self.check(precio=0.857, cita="1,48 € por unidad para 1")
        self.check(precio=None, cita="1,48 € por unidad para 1")       # sin precio, sin cifra que mirar

    def test_el_precio_se_lee_con_coma_o_punto_y_con_miles(self):
        for price, quote in ((2.95, "2,95 €"), (2.95, "€2.95"), (1234.5, "1.234,50 €"),
                             (1234.5, "$1,234.50"), (464.01, "about €464.01 excl."),
                             (12.0, "12 € Unidad"), (2.95, "2,950 €")):
            with self.subTest(quote=quote):
                self.assertTrue(supply.price_in(price, quote))
        for price, quote in ((0.857, "1,48 €"), (2.59, "2,95 €"), (12.5, "12 €")):
            with self.subTest(quote=quote):
                self.assertFalse(supply.price_in(price, quote))

    def test_sin_cita_con_moneda_rara_o_via_desconocida_no_se_guarda(self):
        for kw in ({"cita": ""}, {"moneda": "euros"}, {"moneda": ""}, {"via": "intuicion"},
                   {"coincidencia": "parecida"}):
            with self.subTest(**kw), self.assertRaises(ValidationError):
                self.check(**kw)


class DesconocidoNoEsCero(unittest.TestCase):
    def test_vacio_es_none_y_cero_es_error(self):
        o = supply.check_manual_offer({"proveedor": "Comercial", "precio": None,
                                       "plazo_dias": ""}, "CSF-14", NOW)
        self.assertIsNone(o["precio"])
        self.assertIsNone(o["plazo_dias"])
        self.assertIsNone(o["moneda"])
        for kw in ({"precio": 0, "moneda": "EUR"}, {"plazo_dias": 0}, {"precio": -3, "moneda": "EUR"},
                   {"precio": "12", "moneda": "EUR"}, {"plazo_dias": True}):
            with self.subTest(**kw), self.assertRaises(ValidationError):
                supply.check_manual_offer(dict({"proveedor": "Comercial"}, **kw), "CSF-14", NOW)

    def test_a_mano_necesita_proveedor_y_una_url_http(self):
        o = supply.check_manual_offer({"proveedor": "Comercial", "precio": 380, "moneda": "eur",
                                       "url": "https://www.harmonicdrive.de/x"}, "CSF-14", NOW)
        self.assertEqual((o["origen"], o["moneda"], o["dominio"]),
                         ("mano", "EUR", "www.harmonicdrive.de"))
        with self.assertRaises(ValidationError):
            supply.check_manual_offer({"proveedor": ""}, "CSF-14", NOW)
        with self.assertRaises(ValidationError):
            supply.check_manual_offer({"proveedor": "X", "url": "javascript:alert(1)"}, "C", NOW)


def dated(days_ago, **kw):
    o = dict(clave="IRF540N", coincidencia="exacta", origen="agente", dominio="rs-online.com",
             proveedor="RS", via="pagina",
             fecha=(NOW - datetime.timedelta(days=days_ago)).isoformat())
    o.update(kw)
    return o


class LaCaducidad(unittest.TestCase):
    def test_vigente_hasta_el_ultimo_instante_y_caducada_despues(self):
        self.assertTrue(supply.is_current(dated(6.99), 7, NOW))
        self.assertFalse(supply.is_current(dated(7), 7, NOW))
        self.assertFalse(supply.is_current({"fecha": "ayer"}, 7, NOW))

    def test_una_caducada_sale_con_vigente_false_y_no_se_borra(self):
        offers = [dated(30, id="vieja")]
        out = supply.offers_for(offers, "IRF540N", PROVS, 7, NOW)
        self.assertEqual([(o["id"], o["vigente"]) for o in out["exactas"]], [("vieja", False)])
        self.assertEqual(len(offers), 1)
        self.assertIsNone(supply.best_offer(offers, "IRF540N", PROVS, 7, NOW))
        self.assertTrue(supply.needs_search(offers, "IRF540N", PROVS, 7, NOW))

    def test_la_caducidad_va_de_uno_a_noventa_dias(self):
        self.assertEqual(supply.check_expiry_days(7), 7)
        for bad in (0, 91, 7.5, "7", True):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                supply.check_expiry_days(bad)


class ElOrdenYLosEquivalentes(unittest.TestCase):
    def test_vigentes_por_orden_de_proveedor_y_pagina_antes_que_buscador(self):
        offers = [dated(1, id="farnell", dominio="farnell.com", proveedor="Farnell"),
                  dated(1, id="rs_buscador", via="buscador"),
                  dated(2, id="rs_pagina"),
                  dated(20, id="rs_caducada")]
        out = supply.offers_for(offers, "IRF540N", PROVS, 7, NOW)
        self.assertEqual([o["id"] for o in out["exactas"]],
                         ["rs_pagina", "rs_buscador", "farnell", "rs_caducada"])

    def test_un_equivalente_nunca_es_la_mejor_ni_evita_buscar(self):
        offers = [dated(1, id="eq", coincidencia="equivalente")]
        self.assertIsNone(supply.best_offer(offers, "IRF540N", PROVS, 7, NOW))
        self.assertTrue(supply.needs_search(offers, "IRF540N", PROVS, 7, NOW))
        out = supply.offers_for(offers, "IRF540N", PROVS, 7, NOW)
        self.assertEqual(([o["id"] for o in out["equivalentes"]], out["exactas"]), (["eq"], []))

    def test_una_exacta_vigente_evita_volver_a_buscar(self):
        offers = [dated(1, id="ok")]
        self.assertEqual(supply.best_offer(offers, "IRF540N", PROVS, 7, NOW)["id"], "ok")
        self.assertFalse(supply.needs_search(offers, "IRF540N", PROVS, 7, NOW))


class BuscarOtraVez(unittest.TestCase):
    def test_sustituye_las_del_agente_de_esa_clave_y_esos_proveedores_y_nunca_las_de_mano(self):
        offers = [dated(1, id="rs"), dated(1, id="farnell", dominio="farnell.com"),
                  dated(1, id="mano", origen="mano"), dated(1, id="otra", clave="CSF-14")]
        out = supply.replace_agent_offers(offers, "IRF540N", ["rs-online.com"],
                                          [dated(0, id="nueva")])
        self.assertEqual(sorted(o["id"] for o in out), ["farnell", "mano", "nueva", "otra"])


class ElAlmacenamiento(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_los_dos_ficheros_van_en_profile(self):
        self.assertIsNone(self.ws.load_providers_text())
        self.assertIsNone(self.ws.load_offers_text())
        self.ws.save_providers_text(supply.dump_providers(supply.check_providers(PROVS)))
        data = supply.add_usage(supply.empty_offers(), 0.0123)
        self.ws.save_offers_text(supply.dump_offers(data))
        self.assertTrue((self.root / "ws" / "profile" / "proveedores.toml").is_file())
        self.assertTrue((self.root / "ws" / "profile" / "ofertas.json").is_file())
        self.assertEqual(len(supply.parse_providers(self.ws.load_providers_text())), 2)
        self.assertEqual(supply.parse_offers(self.ws.load_offers_text())["consumo"],
                         {"usd": 0.0123, "busquedas": 1})

    def test_un_ofertas_json_roto_o_de_otro_esquema_vale_vacio(self):
        for text in ("{roto", '{"esquema": 99, "ofertas": [{"clave": "X"}]}', "[]", None):
            with self.subTest(text=text):
                self.assertEqual(supply.parse_offers(text), supply.empty_offers())


class ElAgenteDeProveedores(unittest.TestCase):
    """A1 y R1 en el agente: lo que deja pasar `can_use_tool` y lo que cuenta como devuelto."""

    def setUp(self):
        self.agent = SupplyAgent("IRF540N", {"meta": {"key": "IRF540N", "manufacturer": "Infineon"}},
                                 supply.check_providers(PROVS), now=NOW)

    def test_websearch_siempre_lleva_los_dominios_de_la_lista_aunque_pida_otros(self):
        for asked in ({"query": "x"}, {"query": "x", "allowed_domains": []},
                      {"query": "x", "allowed_domains": ["amazon.es"], "blocked_domains": ["rs-online.com"]}):
            with self.subTest(asked=asked):
                out = self.agent.decide("WebSearch", asked)
                self.assertEqual(out["allowed_domains"], ["rs-online.com", "farnell.com"])
                self.assertNotIn("blocked_domains", out)
                self.assertEqual(out["query"], "x")

    def test_webfetch_solo_a_los_dominios_de_la_lista_y_ninguna_otra_herramienta(self):
        self.assertIsNotNone(self.agent.decide("WebFetch", {"url": "https://uk.RS-online.com/p/1"}))
        for url in ("https://www.amazon.es/", "https://farnell.com.evil.io/", "file:///c:/x"):
            with self.subTest(url=url):
                self.assertIsNone(self.agent.decide("WebFetch", {"url": url}))
        for name in ("Bash", "Read", "Write", "mcp__otro__x"):
            with self.subTest(name=name):
                self.assertIsNone(self.agent.decide(name, {}))

    def test_cuenta_lo_que_devolvio_la_herramienta_no_lo_que_dice_el_agente(self):
        a = self.agent
        a.on_tool_use("t1", "WebFetch", {"url": PAGE_URL})
        a.on_tool_result("t1", "The server returned HTTP 403 Forbidden.", True)
        ok, why = a.note_offer(offer())
        self.assertFalse(ok)
        self.assertEqual(a.found, [])
        a.on_tool_use("t2", "WebFetch", {"url": PAGE_URL})
        a.on_tool_result("t2", PAGE_TEXT, False)
        ok, o = a.note_offer(offer())
        self.assertTrue(ok)
        self.assertEqual([x["id"] for x in a.found], [o["id"]])
        a.on_tool_use("t3", "WebSearch", {"query": "IRF540N precio"})
        a.on_tool_result("t3", SEARCH_TEXT, False)
        ok, _ = a.note_offer(offer(url="https://uk.farnell.com/multicomp-pro/irf540n/dp/4472945",
                                   via="buscador", cita="£1.15 sin IVA", moneda="GBP", precio=1.15))
        self.assertTrue(ok)
        self.assertEqual(a.log.queries, ["IRF540N precio"])

    def test_el_mensaje_lleva_la_ficha_y_los_proveedores_por_orden(self):
        from pizarra.agent_supply import user_message
        text = user_message("IRF540N", self.agent.data, self.agent.providers)
        self.assertIn("Infineon", text)
        self.assertLess(text.index("1. RS: rs-online.com"), text.index("2. Farnell: farnell.com"))


FICHA = """[meta]
key = "{key}"
type = "{type}"
status = "unverified"
manufacturer = "Infineon"
"""


class FakeAgent:
    """Hace de SupplyAgent: apunta lo que se le dice, o espera a que lo corten."""
    plan = []           # ofertas que apunta (clase: lo fija cada test)
    wait = False

    def __init__(self, clave, data, providers, settings=None, cli_path=None, budget_usd=None):
        self.clave, self.providers, self.budget_usd = clave, providers, budget_usd
        self.found, self.rejected, self.log = [], [], supply.SearchLog()
        self.started = asyncio.Event()
        self._stop = asyncio.Event()

    async def run(self, emit=None):
        self.started.set()
        for o in self.plan:
            self.found.append(dict(o, clave=self.clave))
            if emit:
                await emit({"kind": "offer", "offer": o})
        if self.wait:
            await self._stop.wait()
            return {"ofertas": list(self.found), "cost_usd": 0.01, "subtype": "interrupted"}
        return {"ofertas": list(self.found), "cost_usd": 0.04, "subtype": "success"}

    async def interrupt(self):
        self._stop.set()


class ElServicio(unittest.IsolatedAsyncioTestCase):
    """§4 y A6, A11: la búsqueda en segundo plano, lo que guarda y quién paga."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        self.lib = WorkspaceLibrary(self.ws, ())
        self.lib.save("IRF540N", FICHA.format(key="IRF540N", type="element"))
        self.lib.save("CSF-14", FICHA.format(key="CSF-14", type="reducer"))
        self.svc = SupplyService(lambda: self.ws, None, lambda: self.lib, make_agent=FakeAgent)
        self.svc.save_providers(PROVS)
        FakeAgent.plan, FakeAgent.wait = [], False

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def agent_offer(self, id_, dominio="rs-online.com"):
        return dict(dated(0, id=id_, dominio=dominio), fecha=supply.now_iso())

    async def finish(self, job_id):
        await self.svc.jobs[job_id]["task"]
        return self.svc.job(job_id)

    async def test_la_busqueda_guarda_lo_apuntado_y_lo_gastado_en_la_libreria(self):
        FakeAgent.plan = [self.agent_offer("a1")]
        job = await self.finish(self.svc.start("IRF540N"))
        self.assertEqual(job["estado"], "hecha")
        out = self.svc.offers("IRF540N")
        self.assertEqual([o["id"] for o in out["exactas"]], ["a1"])
        self.assertTrue(out["exactas"][0]["vigente"])
        self.assertEqual(out["consumo"], {"usd": 0.04, "busquedas": 1})

    async def test_buscar_otra_vez_sustituye_las_del_agente_y_deja_las_de_mano(self):
        self.svc.add_manual("IRF540N", {"proveedor": "Comercial", "precio": 2, "moneda": "EUR"})
        FakeAgent.plan = [self.agent_offer("vieja")]
        await self.finish(self.svc.start("IRF540N"))
        FakeAgent.plan = [self.agent_offer("nueva")]
        await self.finish(self.svc.start("IRF540N"))
        ids = [o["id"] for o in self.svc.offers("IRF540N")["exactas"]]
        self.assertIn("nueva", ids)
        self.assertNotIn("vieja", ids)
        self.assertEqual(sum(1 for o in self.svc._load()["ofertas"] if o["origen"] == "mano"), 1)

    async def test_una_segunda_busqueda_de_la_misma_clave_es_busy_y_cancelar_guarda_lo_apuntado(self):
        FakeAgent.plan, FakeAgent.wait = [self.agent_offer("parcial")], True
        job_id = self.svc.start("IRF540N")
        await self.svc.jobs[job_id]["agent"].started.wait()
        with self.assertRaises(Busy):
            self.svc.start("IRF540N")
        await self.svc.cancel(job_id)
        job = await self.finish(job_id)
        self.assertEqual(job["estado"], "cancelada")
        self.assertEqual([o["id"] for o in self.svc.offers("IRF540N")["exactas"]], ["parcial"])

    async def test_la_que_corta_el_tope_acaba_en_tope_y_guarda_lo_apuntado(self):
        FakeAgent.plan = [self.agent_offer("antes_del_tope")]
        orig = FakeAgent.run

        async def run_topped(agent, emit=None):
            r = await orig(agent, emit)
            return dict(r, subtype="error_max_budget_usd")
        FakeAgent.run = run_topped
        try:
            job = await self.finish(self.svc.start("IRF540N"))
        finally:
            FakeAgent.run = orig
        self.assertEqual(job["estado"], "tope")
        self.assertEqual([o["id"] for o in self.svc.offers("IRF540N")["exactas"]], ["antes_del_tope"])

    async def test_sin_ficha_o_sin_proveedores_para_su_tipo_no_arranca(self):
        self.svc.save_providers([FARNELL])         # Farnell solo cubre element
        with self.assertRaises(ValidationError):
            self.svc.start("CSF-14")
        with self.assertRaises(ValidationError):
            self.svc.start("NO-EXISTE")
        self.assertEqual(self.svc.jobs, {})

    async def test_un_tipo_que_la_libreria_no_tiene_no_se_guarda(self):
        with self.assertRaises(ValidationError):
            self.svc.save_providers([dict(RS, tipos=["muelle_gas"])])

    async def test_el_agente_de_diseno_no_busca_lo_que_ya_tiene_exacta_vigente_y_paga_el_proyecto(self):
        FakeAgent.plan = [self.agent_offer("a1")]
        paid = []
        r = await self.svc.search_now("IRF540N", lambda usd, usage: paid.append(usd))
        self.assertTrue(r["buscada"])
        self.assertEqual(r["mejor"]["id"], "a1")
        self.assertEqual(paid, [0.04])
        self.assertEqual(self.svc.offers("IRF540N")["consumo"]["busquedas"], 0)
        r = await self.svc.search_now("IRF540N", lambda usd, usage: paid.append(usd))
        self.assertFalse(r["buscada"])
        self.assertEqual(paid, [0.04])

    async def test_borrar_una_oferta_y_una_que_no_existe(self):
        o = self.svc.add_manual("IRF540N", {"proveedor": "Comercial"})
        self.svc.delete(o["id"])
        self.assertEqual(self.svc.offers("IRF540N")["exactas"], [])
        with self.assertRaises(NotFound):
            self.svc.delete(o["id"])

    async def test_abrir_una_oferta_usa_la_url_guardada_y_solo_http(self):
        con = self.svc.add_manual("IRF540N", {"proveedor": "RS", "url": "https://es.rs-online.com/p/1"})
        sin = self.svc.add_manual("IRF540N", {"proveedor": "Comercial"})
        self.assertEqual(self.svc.offer_url(con["id"]), "https://es.rs-online.com/p/1")
        with self.assertRaises(ValidationError):
            self.svc.offer_url(sin["id"])
        with self.assertRaises(NotFound):
            self.svc.offer_url("no-existe")


class ElAgenteDeDiseno(unittest.IsolatedAsyncioTestCase):
    """A6: `buscar_proveedores` como mucho 5 por mensaje, nunca lo que tiene exacta vigente, y
    con lo que queda del tope; `buscar_libreria` da la mejor exacta vigente y nunca otra."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        self.lib = WorkspaceLibrary(self.ws, ())
        for i in range(7):
            self.lib.save(f"P{i}", FICHA.format(key=f"P{i}", type="element"))
        self.svc = SupplyService(lambda: self.ws, None, lambda: self.lib, make_agent=FakeAgent)
        self.svc.save_providers(PROVS)
        FakeAgent.plan, FakeAgent.wait = [], False
        self.paid = []

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def searches(self, left=None):
        from pizarra.agent import SupplySearches
        return SupplySearches(self.svc, lambda usd, usage: self.paid.append(usd), lambda: left)

    @staticmethod
    def result(r):
        return json.loads(r["content"][0]["text"])

    async def test_como_mucho_cinco_busquedas_por_mensaje(self):
        s = self.searches()
        r = self.result(await s.run({"claves": ["P0", "P1", "P2", "P3"]}))
        self.assertEqual(r["quedan"], 1)
        r = self.result(await s.run({"claves": ["P4", "P5"]}))
        self.assertEqual([("error" in x) for x in r["resultados"]], [False, True])
        self.assertEqual(len(self.paid), 5)

    async def test_lo_que_tiene_exacta_vigente_no_se_busca_ni_gasta(self):
        FakeAgent.plan = [dict(dated(0, id="ok"), fecha=supply.now_iso())]
        s = self.searches()
        await s.run({"claves": ["P0"]})
        r = self.result(await s.run({"claves": ["P0"]}))
        self.assertFalse(r["resultados"][0]["buscada"])
        self.assertEqual((len(self.paid), r["quedan"]), (1, 4))

    async def test_sin_tope_del_proyecto_no_busca_y_con_poco_lo_pasa_al_agente(self):
        r = self.result(await self.searches(left=0.0).run({"claves": ["P0"]}))
        self.assertIn("error", r["resultados"][0])
        self.assertEqual(self.paid, [])
        seen = []
        orig = self.svc.make_agent
        self.svc.make_agent = lambda *a, **kw: seen.append(kw.get("budget_usd")) or orig(*a, **kw)
        await self.searches(left=0.1).run({"claves": ["P1"]})
        self.assertEqual(seen, [0.1])

    async def test_buscar_libreria_da_la_mejor_exacta_vigente_y_nunca_un_equivalente(self):
        from pizarra import agent as agent_mod

        class B:
            ws, registry = self.ws, None
        data = supply.empty_offers()
        data["ofertas"] = [dict(dated(0, id="eq", clave="P0", coincidencia="equivalente"),
                                fecha=supply.now_iso()),
                           dict(dated(30, id="vieja", clave="P1")),
                           dict(dated(0, id="buena", clave="P2", precio=3.0, moneda="EUR"),
                                fecha=supply.now_iso())]
        self.ws.save_offers_text(supply.dump_offers(data))
        out = json.loads(agent_mod.tool_buscar_libreria(B, {"type": "element"})["content"][0]["text"])
        by_key = {r["key"]: r for r in out["results"]}
        self.assertNotIn("oferta", by_key["P0"])
        self.assertNotIn("oferta", by_key["P1"])
        self.assertEqual(by_key["P2"]["oferta"]["precio"], 3.0)


class ElPerfilZip(unittest.TestCase):
    """§2, A8: el perfil .zip lleva los proveedores y nunca las ofertas; importar uno sin
    proveedores no borra los de ahora."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.a = LocalWorkspace.open(self.root / "a", "A", trash=lambda p: None)
        self.b = LocalWorkspace.open(self.root / "b", "B", trash=lambda p: None)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def export_import(self, src, dst):
        from pizarra import profile_zip
        out = profile_zip.export(src, self.root, con_stock=False)
        names = zipfile.ZipFile(out["file"]).namelist()
        plan = profile_zip.plan(dst, out["file"])
        profile_zip.apply(dst, plan["token"])
        Path(out["file"]).unlink()
        return names

    def test_lleva_los_proveedores_y_nunca_las_ofertas(self):
        self.a.save_providers_text(supply.dump_providers(supply.check_providers(PROVS)))
        data = supply.empty_offers()
        data["ofertas"] = [dated(0, id="x")]
        self.a.save_offers_text(supply.dump_offers(data))
        names = self.export_import(self.a, self.b)
        self.assertIn("perfil/proveedores.toml", names)
        self.assertFalse(any("ofertas" in n for n in names))
        self.assertEqual(len(supply.parse_providers(self.b.load_providers_text())), 2)
        self.assertIsNone(self.b.load_offers_text())

    def test_importar_uno_sin_proveedores_no_borra_los_de_ahora(self):
        self.b.save_providers_text(supply.dump_providers(supply.check_providers([RS])))
        self.export_import(self.a, self.b)
        self.assertEqual([p["nombre"] for p in supply.parse_providers(self.b.load_providers_text())],
                         ["RS"])


class LosAjustes(unittest.TestCase):
    """A5, A10: el agente de proveedores con Haiku y 0,25 USD, y 7 días, salvo que se cambien."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.settings = Settings.load(self.root / "settings.toml")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_por_defecto_haiku_025_y_7_dias_sin_tocar_los_otros_agentes(self):
        s = self.settings
        self.assertEqual((s.saved_model("proveedores"), s.saved_model("diseno"),
                          s.saved_model("revisor")), ("haiku", "opus", "opus"))
        self.assertEqual((s.search_limit_usd, s.offers_expiry_days), (0.25, 7))

    def test_se_cambian_se_guardan_y_un_valor_malo_no_entra(self):
        s = self.settings
        s.set_agent_model("proveedores", "sonnet")
        s.search_limit_usd = 0.6
        s.offers_expiry_days = 14
        s.save()
        t = Settings.load(self.root / "settings.toml")
        self.assertEqual((t.saved_model("proveedores"), t.search_limit_usd, t.offers_expiry_days),
                         ("sonnet", 0.6, 14))
        for bad in (0, 91, "7"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                t.offers_expiry_days = bad
        with self.assertRaises(ValueError):
            t.search_limit_usd = -1


if __name__ == "__main__":
    unittest.main()
