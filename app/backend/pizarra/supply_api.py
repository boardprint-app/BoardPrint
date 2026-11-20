"""Proveedores y ofertas del workspace: el servicio y sus rutas REST (docs/PLAN_APROVISIONAMIENTO.md §4,
A2, A6-A11).

    GET    /api/supply/providers                 {proveedores, tipos}
    PUT    /api/supply/providers  {proveedores}  {proveedores} | 422 con el motivo
    GET    /api/supply/offers?clave=             {exactas, equivalentes, caducidad_dias, consumo}
    POST   /api/supply/offers     {clave, oferta}   la oferta a mano guardada (A7)
    DELETE /api/supply/offers/{id}
    POST   /api/supply/offers/{id}/open      abre su URL guardada en el navegador del sistema
    POST   /api/supply/search     {clave}        {job}; 409 si ya se busca esa clave, 422 sin
                                                 ficha o sin proveedores para su tipo
    GET    /api/supply/search/{job}              {estado (buscando|hecha|tope|cancelada|error),
                                                 eventos, resultado?}: la interfaz lo
                                                 sondea (la Librería está en el inicio, sin WebSocket)
    POST   /api/supply/search/{job}/cancel

`SupplyService` es lo que se prueba (sin red: el agente se inyecta con `make_agent`); las rutas
solo lo envuelven. Lo usa también la herramienta `buscar_proveedores` del agente de diseño
(`search_now`), que paga en el proyecto (A11).

**Lo que se escribe** (A8): `proveedores.toml` al guardar la lista; `ofertas.json` al apuntar
una oferta a mano, al borrar una y al acabar cada búsqueda (bien, por el tope o cancelada: lo
apuntado se queda). Siempre bajo un cerrojo: leer, cambiar y escribir no se cruzan.
"""
import asyncio
import logging
import threading
import time
import uuid

from fastapi import Body, HTTPException
from pydantic import BaseModel

from pizarra import desktop, i18n, supply
from pizarra.agent_supply import SupplyAgent
from pizarra.library import WorkspaceLibrary, pack_libraries
from pizarra.storage import NotFound
from pizarra.validation import ValidationError

log = logging.getLogger(__name__)

JOB_KEEP_S = 600                # una búsqueda acabada se puede consultar 10 min


class ProvidersIn(BaseModel):
    proveedores: list


class OfferIn(BaseModel):
    clave: str
    oferta: dict


class SearchIn(BaseModel):
    clave: str


class Busy(Exception):
    """Ya se está buscando esa clave (409)."""


class SupplyService:
    def __init__(self, workspace, settings, library, cli_path=None, make_agent=SupplyAgent):
        """`workspace()` y `library()` devuelven los de ahora (pueden cambiar al abrir otro)."""
        self.workspace = workspace
        self.settings = settings
        self.library = library
        self.cli_path = cli_path
        self.make_agent = make_agent
        self.jobs = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ proveedores
    def providers(self):
        try:
            return supply.parse_providers(self.workspace().load_providers_text())
        except ValidationError as exc:      # uno roto a mano: se dice en el registro, lista vacía
            log.warning("[proveedores] %s", exc)
            return []

    def providers_view(self):
        return {"proveedores": self.providers(), "tipos": self.library().types()}

    def save_providers(self, items):
        clean = supply.check_providers(items, set(self.library().types()))
        self.workspace().save_providers_text(supply.dump_providers(clean))
        return {"proveedores": clean}

    # ------------------------------------------------------------------ ofertas
    def _load(self):
        return supply.parse_offers(self.workspace().load_offers_text())

    def _save(self, data):
        self.workspace().save_offers_text(supply.dump_offers(data))

    def days(self):
        return self.settings.offers_expiry_days if self.settings is not None \
            else supply.DEFAULT_EXPIRY_DAYS

    def offers(self, clave, now=None):
        data = self._load()
        out = supply.offers_for(data["ofertas"], clave, self.providers(), self.days(), now)
        return dict(out, caducidad_dias=self.days(), consumo=data["consumo"])

    def best(self, clave, now=None):
        return supply.best_offer(self._load()["ofertas"], clave, self.providers(), self.days(), now)

    def add_manual(self, clave, data, now=None):
        self._ficha(clave)
        offer = supply.check_manual_offer(data, clave, now)
        with self._lock:
            d = self._load()
            d["ofertas"].append(offer)
            self._save(d)
        return offer

    def delete(self, offer_id):
        with self._lock:
            d = self._load()
            kept = [o for o in d["ofertas"] if o.get("id") != offer_id]
            if len(kept) == len(d["ofertas"]):
                raise NotFound(i18n.t("ofertas.no_existe", id=offer_id))
            d["ofertas"] = kept
            self._save(d)

    def offer_url(self, offer_id):
        """La URL guardada de una oferta, para abrirla en el navegador: la del fichero, nunca
        una que llegue de la interfaz, y solo http o https (como los enlaces de la pizarra)."""
        offer = next((o for o in self._load()["ofertas"] if o.get("id") == offer_id), None)
        if offer is None:
            raise NotFound(i18n.t("ofertas.no_existe", id=offer_id))
        url = str(offer.get("url") or "")
        if not supply.host_of(url):
            raise ValidationError(i18n.t("ofertas.url_no_valida", url=repr(url)))
        return url

    # ------------------------------------------------------------------ buscar
    def _ficha(self, clave):
        found = self.library().ficha_data(clave)
        if found is None or not isinstance(found[2], dict):
            raise ValidationError(i18n.t("proveedores.sin_ficha", clave=clave))
        return found[2]

    def prepare(self, clave):
        """La ficha y los proveedores que cubren su tipo, o `ValidationError` (sin ficha, sin
        proveedores) / `Busy` (ya se busca)."""
        data = self._ficha(clave)
        type_ = str((data.get("meta") or {}).get("type") or "")
        providers = supply.providers_for(self.providers(), type_)
        if not providers:
            raise ValidationError(i18n.t("proveedores.ninguno_para_tipo", tipo=type_ or "?"))
        if any(j["clave"] == clave and j["estado"] == "buscando" for j in self.jobs.values()):
            raise Busy(i18n.t("proveedores.ya_buscando", clave=clave))
        return data, providers

    def store_result(self, clave, providers, result, pay_here=True):
        """Lo apuntado sustituye las del agente de esos proveedores (§3); el gasto, a `consumo`
        si se buscó desde la Librería (A11)."""
        with self._lock:
            d = self._load()
            d["ofertas"] = supply.replace_agent_offers(
                d["ofertas"], clave, [p["dominio"] for p in providers], result.get("ofertas", []))
            if pay_here:
                supply.add_usage(d, result.get("cost_usd"))
            self._save(d)

    def _agent(self, clave, data, providers, budget_usd=None):
        kw = {"budget_usd": budget_usd} if budget_usd is not None else {}
        return self.make_agent(clave, data, providers, settings=self.settings,
                               cli_path=self.cli_path, **kw)

    def start(self, clave):
        """Lanza la búsqueda en segundo plano y devuelve su id (desde la Librería)."""
        data, providers = self.prepare(clave)
        self._forget_old()
        job_id = uuid.uuid4().hex[:12]
        agent = self._agent(clave, data, providers)
        job = {"id": job_id, "clave": clave, "estado": "buscando", "eventos": [],
               "resultado": None, "agent": agent, "providers": providers, "fin": None}
        self.jobs[job_id] = job

        async def emit(event):
            job["eventos"].append(event)

        async def go():
            try:
                result = await agent.run(emit)
                job["estado"] = "hecha"
            except asyncio.CancelledError:
                result = self._partial(agent)
                job["estado"] = "cancelada"
            except Exception as exc:            # el CLI, la sesión, la red: se dice y se guarda lo apuntado
                log.exception("[proveedores] la búsqueda de %s falló", clave)
                result = dict(self._partial(agent), error=str(exc))
                job["estado"] = "error"
            if job.get("cancelled") and job["estado"] == "hecha":
                job["estado"] = "cancelada"
            elif job["estado"] == "hecha" and str(result.get("subtype") or "").startswith(
                    "error_max_budget"):
                job["estado"] = "tope"          # la cortó el tope de búsqueda (A5)
            self.store_result(clave, providers, result)
            job["resultado"] = result
            job["fin"] = time.monotonic()

        job["task"] = asyncio.get_running_loop().create_task(go())
        return job_id

    @staticmethod
    def _partial(agent):
        return {"ofertas": list(agent.found), "consultas": list(agent.log.queries),
                "abiertas": sorted(agent.log.pages), "fallidas": sorted(agent.log.failed),
                "rechazadas": list(agent.rejected), "cost_usd": 0.0}

    def job(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise NotFound(job_id)
        return {k: job[k] for k in ("id", "clave", "estado", "eventos", "resultado")}

    async def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise NotFound(job_id)
        if job["estado"] != "buscando":
            return self.job(job_id)
        job["cancelled"] = True
        try:
            await job["agent"].interrupt()
        except Exception:                       # aún no había arrancado: se corta la tarea
            job["task"].cancel()
        return self.job(job_id)

    def _forget_old(self):
        now = time.monotonic()
        for k in [k for k, j in self.jobs.items() if j["fin"] and now - j["fin"] > JOB_KEEP_S]:
            del self.jobs[k]

    async def search_now(self, clave, on_cost=None, budget_usd=None):
        """La búsqueda entera, esperando (la herramienta del agente de diseño, A6). El gasto no
        va a `consumo`: lo paga el proyecto con `on_cost(usd, usage)` (A11). `budget_usd`, si se
        da y es menor, sustituye al tope de búsqueda (lo que queda del proyecto). Si la clave ya
        tiene una exacta vigente, no busca y la devuelve."""
        best = self.best(clave)
        if best is not None:
            return {"clave": clave, "buscada": False, "mejor": best}
        data, providers = self.prepare(clave)
        limit = self.settings.search_limit_usd if self.settings is not None \
            else supply.DEFAULT_SEARCH_BUDGET_USD
        agent = self._agent(clave, data, providers,
                            None if budget_usd is None else max(0.01, min(limit, budget_usd)))
        job_id = uuid.uuid4().hex[:12]
        self.jobs[job_id] = {"id": job_id, "clave": clave, "estado": "buscando", "eventos": [],
                             "resultado": None, "agent": agent, "providers": providers,
                             "fin": None}
        try:
            result = await agent.run()
        finally:
            self.jobs[job_id]["estado"] = "hecha"
            self.jobs[job_id]["fin"] = time.monotonic()
        self.store_result(clave, providers, result, pay_here=False)
        if on_cost is not None:
            on_cost(result.get("cost_usd") or 0.0, result.get("usage"))
        return {"clave": clave, "buscada": True, "mejor": self.best(clave),
                "ofertas": result.get("ofertas", []), "cost_usd": result.get("cost_usd")}


def register(app, *, need_workspace, settings, registry=None, cli_path=None):
    def library():
        return WorkspaceLibrary(need_workspace(), pack_libraries(registry() if registry else None))

    service = SupplyService(need_workspace, settings, library, cli_path=cli_path)
    app.state.supply = service

    def checked(fn, *args):
        try:
            return fn(*args)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))
        except Busy as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/supply/providers")
    def get_providers():
        return service.providers_view()

    @app.put("/api/supply/providers")
    def put_providers(p: ProvidersIn):
        return checked(service.save_providers, p.proveedores)

    @app.get("/api/supply/offers")
    def get_offers(clave: str):
        return service.offers(clave)

    @app.post("/api/supply/offers")
    def post_offer(o: OfferIn):
        return checked(service.add_manual, o.clave, o.oferta)

    @app.delete("/api/supply/offers/{offer_id}")
    def delete_offer(offer_id: str):
        service.delete(offer_id)
        return {"ok": True}

    @app.post("/api/supply/offers/{offer_id}/open")
    def open_offer(offer_id: str, _body: dict = Body(default={})):
        desktop.open_url(checked(service.offer_url, offer_id))
        return {"ok": True}

    @app.post("/api/supply/search")
    async def post_search(s: SearchIn):
        return {"job": checked(service.start, s.clave)}

    @app.get("/api/supply/search/{job_id}")
    def get_search(job_id: str):
        return service.job(job_id)

    @app.post("/api/supply/search/{job_id}/cancel")
    async def post_cancel(job_id: str, _body: dict = Body(default={})):
        return await service.cancel(job_id)

    return service
