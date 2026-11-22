"""Guardar y descartar las propuestas del agente de onboarding (docs/PLAN_ONBOARDING.md §5,
§7: N4, N5).

Ejecutar desde app/backend:  python -m unittest tests.test_onboarding_api -v
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pizarra import i18n, library_import, onboarding_api, supply, units
from pizarra.library import WorkspaceLibrary
from pizarra.onboarding import DISCARDED, PENDING, SAVED, STALE, OnboardingStore, Proposals, Stale
from pizarra.settings import Settings
from pizarra.storage import Conflict, LocalWorkspace, NotFound
from pizarra.supply_api import SupplyService

RS = {"nombre": "RS", "dominio": "rs-online.com", "tipos": []}
FARNELL = {"nombre": "Farnell", "dominio": "farnell.com", "tipos": []}
PROFILE = "# Taller\n\n- Prusa MK4\n"
NEW_PROFILE = "# Taller\n\n- Prusa MK4 (250×210×220 mm)\n- Fresado fuera\n"


class _Sessions:
    def all(self):
        return ["una ventana"]


class _Workspace(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.ws = LocalWorkspace.open(self.root / "ws", "Taller", trash=lambda p: None)
        self.lib = WorkspaceLibrary(self.ws, ())
        self.supply = SupplyService(lambda: self.ws, None, lambda: self.lib)
        self.supply.save_providers([RS])
        self.ws.save_manufacturing_profile(PROFILE)
        self.settings = Settings.load(self.root / "settings.toml")
        self.settings.language = "es"           # `settings_api.save` pone el idioma de la app
        self.addCleanup(i18n.set_language, "es")      # los demás tests leen en español
        self.sent = []
        self.proposals = Proposals(self.ws, self.supply, self.settings, _Sessions(), self._send)

    async def _send(self, session, msg):
        self.sent.append(msg)

    def files(self):
        base = self.root / "ws"
        return {p.name: p.read_bytes() for p in base.rglob("*")
                if p.is_file() and ("profile" in p.parts or p.name == "workspace.toml")}

    def state(self, pid):
        return OnboardingStore(self.ws).proposals()[pid]["estado"]


class Guardar(_Workspace):
    """N4, N5: guardar escribe exactamente lo propuesto por el camino de siempre; con lo de
    ahora cambiado, no escribe."""

    async def test_el_perfil_se_guarda_tal_cual(self):
        p = self.proposals.propose("perfil", NEW_PROFILE, "volumen")
        out = await self.proposals.save(p["id"])
        self.assertEqual(out["estado"], SAVED)
        self.assertEqual(self.ws.load_manufacturing_profile(), NEW_PROFILE)
        self.assertEqual(self.state(p["id"]), SAVED)

    async def test_los_proveedores_en_su_orden_como_los_guardaria_la_interfaz(self):
        p = self.proposals.propose("proveedores", [FARNELL, RS], "Farnell primero")
        await self.proposals.save(p["id"])
        self.assertEqual(self.supply.providers(), [FARNELL, RS])
        self.assertEqual(self.ws.load_providers_text(), supply.dump_providers([FARNELL, RS]))

    async def test_las_unidades_por_settings_api_avisan_a_las_ventanas_y_dejan_lo_demas(self):
        p = self.proposals.propose("unidades", {"longitud": "in"}, "pulgadas")
        await self.proposals.save(p["id"])
        self.assertEqual(units.clean(self.ws.load_units()), {**units.SI, "longitud": "in"})
        self.assertIn({"type": "settings"}, self.sent)
        self.assertEqual(LocalWorkspace.open(self.root / "ws").info().name, "Taller")

    async def test_con_lo_de_ahora_cambiado_se_rechaza_caduca_y_no_escribe(self):
        cases = [("perfil", NEW_PROFILE, lambda: self.ws.save_manufacturing_profile("# A mano\n")),
                 ("proveedores", [FARNELL], lambda: self.supply.save_providers([RS, FARNELL])),
                 ("unidades", {"masa": "g"}, lambda: self.ws.save_units({**units.SI, "masa": "lb"}))]
        for que, new, by_hand in cases:
            with self.subTest(que=que):
                p = self.proposals.propose(que, new, "x")
                by_hand()
                before = self.files()
                with self.assertRaises(Stale):
                    await self.proposals.save(p["id"])
                self.assertEqual(self.files(), before)
                self.assertEqual(self.state(p["id"]), STALE)

    async def test_un_proveedores_toml_roto_a_mano_tambien_cuenta_como_cambio(self):
        p = self.proposals.propose("proveedores", [FARNELL], "x")
        (self.root / "ws" / "profile" / "proveedores.toml").write_text("roto [", encoding="utf-8")
        with self.assertRaises(Stale):
            await self.proposals.save(p["id"])

    async def test_una_guardada_o_descartada_no_se_guarda_otra_vez(self):
        a = self.proposals.propose("perfil", NEW_PROFILE, "x")
        await self.proposals.save(a["id"])
        with self.assertRaises(Conflict):
            await self.proposals.save(a["id"])
        b = self.proposals.propose("unidades", {"masa": "g"}, "x")
        await self.proposals.discard(b["id"])
        with self.assertRaises(Conflict):
            await self.proposals.save(b["id"])
        with self.assertRaises(Conflict):
            await self.proposals.discard(b["id"])
        with self.assertRaises(NotFound):
            await self.proposals.save("no-existe")

    async def test_descartar_no_escribe_nada(self):
        p = self.proposals.propose("perfil", NEW_PROFILE, "x")
        before = self.files()
        out = await self.proposals.discard(p["id"])
        self.assertEqual(out["estado"], DISCARDED)
        self.assertEqual(self.files(), before)

    async def test_el_agente_sabe_en_su_turno_siguiente_que_paso_con_cada_una_una_sola_vez(self):
        a = self.proposals.propose("perfil", NEW_PROFILE, "x")
        b = self.proposals.propose("unidades", {"masa": "g"}, "x")
        c = self.proposals.propose("proveedores", [FARNELL], "x")
        await self.proposals.save(a["id"])
        await self.proposals.discard(b["id"])
        store = OnboardingStore(self.ws)
        self.assertEqual({(n["que"], n["estado"]) for n in store.take_notes()},
                         {("perfil", SAVED), ("unidades", DISCARDED)})
        self.assertEqual(store.take_notes(), [])
        self.assertEqual(self.state(c["id"]), PENDING)


class LasRutas(_Workspace):
    """Los códigos: 409 si caducó o ya no está pendiente (no el 400 que daría el manejador
    por tipo exacto de server.py), 404 si no existe."""

    def setUp(self):
        super().setUp()
        app = FastAPI()
        onboarding_api.register(app, need_workspace=lambda: self.ws, settings=self.settings,
                                sessions=None, broadcast=self._send, supply=self.supply)
        self.client = TestClient(app)
        self.routed = app.state.onboarding()

    def post(self, pid, action):
        return self.client.post(f"/api/onboarding/proposals/{pid}/{action}")

    def test_guardar_descartar_y_sus_codigos(self):
        p = self.routed.propose("perfil", NEW_PROFILE, "x")
        self.assertEqual(self.post(p["id"], "save").json()["estado"], SAVED)
        self.assertEqual(self.post(p["id"], "save").status_code, 409)
        q = self.routed.propose("perfil", PROFILE, "x")
        self.ws.save_manufacturing_profile("# A mano\n")
        self.assertEqual(self.post(q["id"], "save").status_code, 409)
        self.assertEqual(self.post("nada", "discard").status_code, 404)
        r = self.routed.propose("unidades", {"masa": "g"}, "x")
        self.assertEqual(self.post(r["id"], "discard").json()["estado"], DISCARDED)

    def stock_csv(self):
        csv = self.root / "Stock.csv"
        csv.write_text("Referencia,Cantidad\nIRF540N,12\n", encoding="utf-8")
        return csv

    def test_elegir_excel_deja_sus_columnas_en_el_chat_y_uno_que_no_vale_da_422(self):
        r = self.client.post("/api/onboarding/excel", json={"path": str(self.stock_csv())})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["columns"], ["Referencia", "Cantidad"])
        self.assertEqual(OnboardingStore(self.ws).excel()["id"], r.json()["id"])
        bad = self.client.post("/api/onboarding/excel", json={"path": str(self.root / "nada.xlsx")})
        self.assertEqual(bad.status_code, 422)

    def test_importar_desde_la_tarjeta_escribe_por_el_importador_y_la_deja_guardada(self):
        """N7: la importación la escribe el *Importar* del importador, nunca *Guardar*."""
        csv = self.stock_csv()
        self.client.post("/api/onboarding/excel", json={"path": str(csv)})
        p = self.routed.propose_import("", "", {"Referencia": "key", "Cantidad": "cantidad"}, "stock")
        self.assertEqual(self.post(p["id"], "save").status_code, 422)
        self.assertEqual(self.ws.load_stock(), {})
        plan = library_import.plan(self.supply.library(), str(csv), None, None, p["nuevo"]["mapping"])
        url = f"/api/onboarding/proposals/{p['id']}/import"
        r = self.client.post(url, json={"token": plan["token"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["estado"], SAVED)
        self.assertEqual(self.ws.load_stock()["IRF540N"]["cantidad"], 12)
        self.assertEqual(self.client.post(url, json={"token": plan["token"]}).status_code, 409)
        q = self.routed.propose("unidades", {"masa": "g"}, "x")
        self.assertEqual(self.client.post(f"/api/onboarding/proposals/{q['id']}/import",
                                          json={"token": plan["token"]}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
