"""Las herramientas del agente de onboarding (docs/PLAN_ONBOARDING.md §4, §7: N4, N7, N8, N9).

Ejecutar desde app/backend:  python -m unittest tests.test_agent_onboarding -v
"""
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from pizarra import library_import, profile_zip, supply, units
from pizarra.agent_onboarding import NAMES, SCHEMAS, OnboardingTools, excel_note
from pizarra.library import WorkspaceLibrary
from pizarra.onboarding import IMPORT, PENDING, OnboardingStore, Proposals, excel_event
from pizarra.storage import LocalWorkspace
from pizarra.supply_api import SupplyService
from pizarra.workspace_api import PROFILE_MAX

FICHA = """[meta]
key = "{key}"
type = "{type}"
status = "unverified"
manufacturer = "Infineon"
"""
RS = {"nombre": "RS", "dominio": "rs-online.com", "tipos": []}
FARNELL = {"nombre": "Farnell", "dominio": "farnell.com", "tipos": ["element"]}
PAGE = "https://www.ejemplo-maquinas.com/prusa-mk4"


class _Workspace(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        self.lib = WorkspaceLibrary(self.ws, ())
        self.lib.save("IRF540N", FICHA.format(key="IRF540N", type="element"))
        self.supply = SupplyService(lambda: self.ws, None, lambda: self.lib)
        self.supply.save_providers([RS])
        self.ws.save_manufacturing_profile("# Taller\n\n- Prusa MK4\n")
        self.ws.save_units(dict(units.SI))
        self.proposals = Proposals(self.ws, self.supply)
        self.cards = []
        self.tools = OnboardingTools(self.proposals, on_card=self.cards.append)

    def call(self, name, **args):
        out = self.tools.call(name, args)
        text = out["content"][0]["text"]
        return out.get("is_error", False), (text if out.get("is_error") else json.loads(text))

    def snapshot(self):
        """Todo lo configurable del workspace, byte a byte (perfil, proveedores, unidades en
        `workspace.toml` y la librería)."""
        base = self.root / "ws"
        return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*"))
                if p.is_file() and ("profile" in p.parts or p.name == "workspace.toml")}


class NingunaHerramientaEscribe(_Workspace):
    """N4: tras cualquier llamada, el perfil, los proveedores, las unidades y la librería
    quedan byte a byte igual. Lo único que cambia es la charla, en `.onboarding/`."""

    def test_ni_leer_ni_proponer_ni_un_rechazo_tocan_el_workspace(self):
        before = self.snapshot()
        self.assertLessEqual({"fabricacion.md", "proveedores.toml", "workspace.toml", "IRF540N.toml"},
                             {Path(k).name for k in before})      # la foto no está vacía
        calls = [
            ("leer_configuracion", {}),
            ("proponer_perfil", {"texto": "# Taller\n\n- Prusa MK4 (250×210×220 mm)\n", "motivo": "volumen"}),
            ("proponer_proveedores", {"proveedores": [FARNELL, RS], "motivo": "Farnell primero"}),
            ("proponer_unidades", {"unidades": {"longitud": "in"}, "motivo": "trabaja en pulgadas"}),
            ("proponer_unidades", {"unidades": {"longitud": "pies"}, "motivo": "no vale"}),
            ("proponer_perfil", {"texto": 3, "motivo": "no vale"}),
            ("proponer_importacion", {"mapeo": {"Ref": "key"}, "motivo": "sin Excel no vale"}),
            ("borrar_todo", {}),
        ]
        for name, args in calls:
            self.tools.call(name, args)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.cards), 3)

    def test_las_herramientas_son_las_cinco_del_plan_y_ninguna_guarda(self):
        self.assertEqual(set(NAMES), {"leer_configuracion", "proponer_perfil",
                                      "proponer_proveedores", "proponer_unidades",
                                      "proponer_importacion"})
        self.assertFalse([n for n in SCHEMAS if any(w in n for w in ("guardar", "save", "escribir"))])


class Proponer(_Workspace):
    """N4: una propuesta que no pasaría la escritura vuelve como error y no deja tarjeta."""

    def assert_rejected(self, name, **args):
        is_error, text = self.call(name, **args)
        self.assertTrue(is_error, text)
        self.assertEqual(self.cards, [])
        self.assertEqual(OnboardingStore(self.ws).proposals(), {})
        return text

    def test_proveedores_repetidos_o_con_un_tipo_que_no_hay_se_rechazan(self):
        self.assert_rejected("proponer_proveedores", proveedores=[RS, dict(RS, nombre="RS otra vez")],
                             motivo="x")
        self.assert_rejected("proponer_proveedores",
                             proveedores=[dict(FARNELL, tipos=["reductora"])], motivo="x")

    def test_una_unidad_que_no_existe_o_una_magnitud_desconocida_se_rechazan(self):
        self.assert_rejected("proponer_unidades", unidades={"longitud": "pies"}, motivo="x")
        self.assert_rejected("proponer_unidades", unidades={"temperatura": "K"}, motivo="x")
        self.assert_rejected("proponer_unidades", unidades={}, motivo="x")

    def test_un_perfil_demasiado_largo_o_que_no_es_texto_se_rechaza(self):
        text = self.assert_rejected("proponer_perfil", texto="x" * (PROFILE_MAX + 1), motivo="x")
        self.assertIn(str(PROFILE_MAX), text)
        self.assert_rejected("proponer_perfil", texto=["no"], motivo="x")

    def test_sin_motivo_o_sin_cambiar_nada_se_rechaza(self):
        self.assert_rejected("proponer_perfil", texto="# Otro\n", motivo="  ")
        self.assert_rejected("proponer_perfil", texto="# Taller\n\n- Prusa MK4\n", motivo="igual")
        self.assert_rejected("proponer_proveedores", proveedores=[RS], motivo="igual")
        self.assert_rejected("proponer_unidades", unidades={"longitud": "mm"}, motivo="igual")

    def test_una_que_vale_deja_su_tarjeta_con_lo_de_ahora_y_lo_nuevo(self):
        is_error, out = self.call("proponer_unidades", unidades={"longitud": "in"},
                                  motivo="pulgadas")
        self.assertFalse(is_error)
        self.assertEqual(out["estado"], PENDING)
        card = self.cards[0]
        self.assertEqual(card["id"], out["propuesta"])
        self.assertEqual((card["que"], card["estado"]), ("unidades", PENDING))
        self.assertEqual(card["antes"], units.SI)
        self.assertEqual(card["nuevo"], {**units.SI, "longitud": "in"})   # entera, no solo lo que cambia
        self.assertEqual(OnboardingStore(self.ws).proposals()[card["id"]]["nuevo"], card["nuevo"])

    def test_los_proveedores_van_como_los_guardaria_la_interfaz(self):
        _, out = self.call("proponer_proveedores", motivo="dos",
                           proveedores=[{"nombre": " Farnell ", "dominio": "Farnell.COM.",
                                         "tipos": ["element", "element"]}, RS])
        self.assertEqual(self.cards[0]["nuevo"], supply.check_providers([FARNELL, RS]))


class Citas(_Workspace):
    """N8: una fuente cuya cita no está en lo que devolvieron las herramientas rechaza la
    propuesta (la web llega en el paso 5; sin registro, ninguna cita se puede comprobar)."""

    def propose(self, fuentes, log=None):
        self.tools.log = log
        return self.call("proponer_perfil", texto="# Taller\n\n- Prusa MK4: 250×210×220 mm\n",
                         motivo="volumen de la ficha", fuentes=fuentes)

    def test_sin_registro_de_la_web_una_fuente_rechaza_la_propuesta(self):
        is_error, _ = self.propose([{"url": PAGE, "cita": "250 × 210 × 220 mm"}])
        self.assertTrue(is_error)
        self.assertEqual(self.cards, [])

    def test_la_cita_tiene_que_estar_en_la_pagina_abierta(self):
        log = supply.SearchLog()
        log.page(PAGE, "Build volume: 250 × 210 × 220 mm. Nozzle 0.4 mm.")
        self.assertTrue(self.propose([{"url": PAGE, "cita": "Build volume: 300 mm"}], log)[0])
        self.assertTrue(self.propose([{"url": "ftp://x.com/a", "cita": "Build volume"}], log)[0])
        is_error, _ = self.propose([{"url": PAGE, "cita": "build  volume: 250 × 210 × 220 mm"}], log)
        self.assertFalse(is_error)
        self.assertEqual(self.cards[0]["fuentes"],
                         [{"url": PAGE, "cita": "build volume: 250 × 210 × 220 mm"}])


class Importacion(_Workspace):
    """N7: `proponer_importacion` solo con un Excel elegido antes y con las reglas del
    importador; la tarjeta lleva lo que abre el importador, y nada se escribe."""

    def setUp(self):
        super().setUp()
        self.csv = self.root / "Stock.csv"
        self.csv.write_text("Referencia,Cantidad,Fabricante,Notas\nIRF540N,12,Infineon,\n"
                            "BC547,30,ON,caja 3\n", encoding="utf-8")

    def choose(self):
        """Lo que deja *Elegir Excel…* en el chat (`POST /api/onboarding/excel`)."""
        event = excel_event(library_import.inspect(str(self.csv)))
        self.ws.append_onboarding_chat([event])
        return event

    def test_sin_excel_elegido_antes_se_rechaza_y_no_deja_tarjeta(self):
        bad, text = self.call("proponer_importacion", mapeo={"Referencia": "key"}, motivo="x")
        self.assertTrue(bad)
        self.assertIn("Elegir Excel", text)
        self.assertEqual(self.cards, [])

    def test_un_mapeo_que_el_importador_no_aceptaria_se_rechaza(self):
        self.choose()
        for mapeo, tipo in [({"Cantidad": "cantidad"}, ""),                     # sin key
                            ({"Ref": "key"}, ""),                                # no hay esa columna
                            ({"Referencia": "key", "Cantidad": "precio"}, ""),   # destino que no hay
                            ({"Referencia": "key", "Fabricante": "manufacturer"}, ""),  # sin tipo
                            ({"Referencia": "key"}, "Tipo Raro")]:               # tipo que no vale
            bad, _ = self.call("proponer_importacion", mapeo=mapeo, tipo=tipo, motivo="x")
            self.assertTrue(bad, mapeo)
        self.assertEqual(self.cards, [])

    def test_una_que_vale_deja_la_tarjeta_para_el_importador_y_no_escribe_nada(self):
        self.choose()
        before = self.snapshot()
        bad, out = self.call("proponer_importacion", tipo="element",
                             mapeo={"Referencia": "key", "Cantidad": "cantidad",
                                    "Fabricante": "manufacturer", "Notas": ""},
                             motivo="la referencia es la clave y la cantidad, el stock")
        self.assertFalse(bad, out)
        [card] = self.cards
        self.assertEqual(card["que"], IMPORT)
        self.assertEqual(card["nuevo"], {"path": str(self.csv), "sheet": "", "type": "element",
                                         "mapping": {"Referencia": "key", "Cantidad": "cantidad",
                                                     "Fabricante": "manufacturer"}})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.ws.load_stock(), {})

    def test_el_agente_recibe_cada_excel_elegido_una_sola_vez(self):
        store = OnboardingStore(self.ws)
        self.assertIsNone(store.take_excel())
        first = self.choose()
        got = store.take_excel()
        self.assertEqual(got["id"], first["id"])
        self.assertIsNone(store.take_excel())
        note = excel_note(got)
        for text in ("Stock.csv", "Referencia", "BC547"):
            self.assertIn(text, note)
        second = self.choose()
        self.assertEqual(store.take_excel()["id"], second["id"])


class LeerConfiguracion(_Workspace):
    def test_da_lo_de_ahora_con_sus_opciones_y_las_propuestas(self):
        self.call("proponer_unidades", unidades={"masa": "g"}, motivo="gramos")
        _, out = self.call("leer_configuracion")
        self.assertEqual(out["perfil"]["texto"], "# Taller\n\n- Prusa MK4\n")
        self.assertNotIn("plantilla", out["perfil"])
        self.assertEqual(out["proveedores"], [RS])
        self.assertEqual(out["tipos_libreria"], ["element"])
        self.assertEqual(out["unidades"]["ahora"], units.SI)
        self.assertIn("in", out["unidades"]["opciones"]["longitud"])
        self.assertEqual([(p["que"], p["estado"]) for p in out["propuestas"]], [("unidades", PENDING)])

    def test_sin_perfil_da_la_plantilla_para_empezar(self):
        (self.root / "ws" / "profile" / "fabricacion.md").unlink()
        _, out = self.call("leer_configuracion")
        self.assertIsNone(out["perfil"]["texto"])
        self.assertTrue(out["perfil"]["plantilla"])


class Historial(_Workspace):
    """N9: la conversación es del workspace, sigue tras cerrar y abrir, y *Empezar de nuevo*
    borra charla y sesión y nunca lo guardado; `.onboarding/` no sale en el árbol ni en el
    perfil .zip."""

    def test_sigue_tras_cerrar_y_abrir_el_workspace(self):
        self.call("proponer_unidades", unidades={"longitud": "cm"}, motivo="cm")
        store = OnboardingStore(self.ws)
        store.set_session_id("ses-1")
        reopened = OnboardingStore(LocalWorkspace.open(self.root / "ws"))
        self.assertEqual(reopened.session_id(), "ses-1")
        self.assertEqual([e["kind"] for e in reopened.history()], ["proposal"])

    def test_empezar_de_nuevo_borra_charla_y_sesion_y_nunca_lo_guardado_ni_el_consumo(self):
        store = OnboardingStore(self.ws)
        self.call("proponer_unidades", unidades={"longitud": "cm"}, motivo="cm")
        store.set_session_id("ses-1")
        store.add_usage({"input": 10, "usd": 0.2, "messages": 1})
        before = self.snapshot()
        store.reset()
        self.assertEqual(store.history(), [])
        self.assertIsNone(store.session_id())
        self.assertEqual(store.usage()["usd"], 0.2)       # el tope es del workspace (N6)
        self.assertEqual(self.snapshot(), before)

    def test_onboarding_no_sale_en_la_lista_de_proyectos_ni_en_el_perfil_zip(self):
        self.call("proponer_unidades", unidades={"longitud": "cm"}, motivo="cm")
        self.assertTrue((self.root / "ws" / ".onboarding" / "chat.jsonl").is_file())
        self.assertEqual(LocalWorkspace.open(self.root / "ws").tree().children, [])
        out = self.root / "zip"
        out.mkdir()
        made = profile_zip.export(self.ws, out)
        with zipfile.ZipFile(made["file"]) as z:
            self.assertFalse([n for n in z.namelist() if "onboarding" in n or n.endswith(".jsonl")])


if __name__ == "__main__":
    unittest.main()
