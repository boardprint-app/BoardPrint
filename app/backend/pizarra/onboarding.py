"""El onboarding del workspace: su conversación y las propuestas (docs/PLAN_ONBOARDING.md §5,
§6, N4, N5, N9).

- **La conversación** (N9): `OnboardingStore`, por el almacenamiento (`.onboarding/` en
  local): los eventos del chat, la sesión del SDK y el consumo, del workspace y no de un
  proyecto. *Empezar de nuevo* (`reset`) borra la charla y la sesión; el consumo se queda,
  porque el tope es del workspace (N6), y nada de lo guardado se toca.
- **Las propuestas** (N4): el agente no escribe nada. `Proposals.propose` valida lo que
  propone con **las mismas reglas que la escritura** y, si vale, deja en el chat
  `{"type": "agent", "kind": "proposal", id, que, antes, nuevo, motivo, fuentes, antes_huella,
  estado: "pendiente", at}`; si no vale, ValueError con el motivo y no deja nada.
- **Guardar** (N5): solo si lo de ahora tiene la misma huella que cuando se propuso, y por el
  camino de la interfaz (`workspace_api.save_profile`, `SupplyService.save_providers`,
  `settings_api.save`). Si lo de ahora cambió, la propuesta queda `caducada` y no escribe nada:
  el agente propone otra vez sobre lo nuevo. *Descartar* no escribe nada. Las dos son de una
  vez: el cambio de estado va al chat como `{"kind": "proposal_state", id, estado, at}` (el
  chat nunca se reescribe) y el agente lo lee en su turno siguiente (`take_notes`).

Qué se propone (`que`): `perfil` (el `fabricacion.md` entero), `proveedores` (la lista entera
en su orden) y `unidades` (las cinco magnitudes; lo que no se nombra se queda como está).

**La librería desde un Excel** (N7): *Elegir Excel…* deja en el chat un evento `excel` con sus
hojas, columnas y unas filas de muestra, que el agente recibe una vez (`take_excel`).
`propose_import` valida el mapeo con `library_import.check_mapping` sobre las columnas de esa
hoja y deja una propuesta `importacion` con `nuevo = {path, sheet, type, mapping}`. No se guarda
con *Guardar*: la tarjeta abre el importador rellenado, y es su *Importar* el que escribe
(`imported`, con el resumen de `library_import.plan`) y la deja guardada.
"""
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

from pizarra import i18n, library_import, settings_api, supply, units, workspace_api
from pizarra.agent_chat import _add, empty_usage, session_cost, valid_cost
from pizarra.storage import Conflict, NotFound, StorageError
from pizarra.storage.names import check_ficha_type

ONBOARDING = "onboarding"      # el agente, en los ajustes (`modelo_onboarding`, N6)
KINDS = ("perfil", "proveedores", "unidades")
IMPORT = "importacion"         # la propuesta de importar un Excel (N7): la escribe el importador
PENDING, SAVED, DISCARDED, STALE = "pendiente", "guardada", "descartada", "caducada"
REASON_MAX = 300               # caracteres del motivo de una propuesta
SOURCES_MAX = 10               # fuentes de una propuesta (N8)
QUOTE_MAX = 400                # caracteres de una cita
HISTORY_MAX = 2000             # eventos del chat que se mandan al abrir (los últimos)


def fingerprint(value):
    """La huella de lo de ahora (N5): igual si y solo si el valor es el mismo."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ la conversación
class OnboardingStore:
    """`.onboarding/` del workspace `ws`, siempre por el almacenamiento (N9)."""

    def __init__(self, ws):
        self.ws = ws

    def history(self):
        return self.ws.load_onboarding_chat()[-HISTORY_MAX:]

    def append(self, event):
        self.ws.append_onboarding_chat([event])

    def reset(self):
        """*Empezar de nuevo*: la charla y la sesión fuera; el consumo y lo guardado, no."""
        self.ws.clear_onboarding_chat()

    # ---------------------------------------------------------------- propuestas
    def proposals(self):
        """{id: propuesta} con su estado de ahora, en el orden en que se hicieron."""
        out = {}
        for ev in self.ws.load_onboarding_chat():
            if ev.get("type") != "agent":
                continue
            if ev.get("kind") == "proposal" and isinstance(ev.get("id"), str):
                out[ev["id"]] = dict(ev)
            elif ev.get("kind") == "proposal_state" and ev.get("id") in out:
                out[ev["id"]]["estado"] = ev.get("estado")
        return out

    def set_state(self, proposal_id, estado):
        self.append({"type": "agent", "kind": "proposal_state", "id": proposal_id,
                     "estado": estado, "at": time.time()})

    def take_notes(self):
        """Lo que el agente aún no sabe de sus propuestas (N5): `[{id, que, estado}]` de las
        que se guardaron, descartaron o caducaron desde su último turno. Cada una se da una
        sola vez."""
        session = self.ws.load_onboarding_file("session")
        told = set(session.get("avisadas") or []) if isinstance(session.get("avisadas"), list) else set()
        notes = [{"id": p["id"], "que": p.get("que"), "estado": p["estado"]}
                 for p in self.proposals().values()
                 if p.get("estado") != PENDING and p["id"] not in told]
        if notes:
            session["avisadas"] = sorted(told | {n["id"] for n in notes})
            self.ws.save_onboarding_file("session", session)
        return notes

    # ---------------------------------------------------------------- el Excel (N7)
    def excel(self):
        """El último Excel elegido con *Elegir Excel…* (su evento `excel`), o None."""
        last = None
        for ev in self.ws.load_onboarding_chat():
            if ev.get("type") == "agent" and ev.get("kind") == "excel":
                last = ev
        return last

    def take_excel(self):
        """El Excel elegido si el agente aún no lo ha visto, o None: se le da una sola vez."""
        ex = self.excel()
        if ex is None:
            return None
        session = self.ws.load_onboarding_file("session")
        if session.get("excel_visto") == ex.get("id"):
            return None
        session["excel_visto"] = ex.get("id")
        self.ws.save_onboarding_file("session", session)
        return ex

    # ------------------------------------------------------------------ sesión
    def session_id(self):
        sid = self.ws.load_onboarding_file("session").get("session_id")
        return sid if isinstance(sid, str) and sid else None

    def set_session_id(self, session_id):
        if not session_id or session_id == self.session_id():
            return
        data = self.ws.load_onboarding_file("session")
        data.update(session_id=session_id, at=time.time())
        self.ws.save_onboarding_file("session", data)

    def message_cost(self, session_id, cumulative):
        """El coste de un mensaje: el `total_cost_usd` del SDK es el acumulado de la sesión
        reanudada, y se le resta el último de esa sesión (`agent_chat.session_cost`)."""
        if not valid_cost(cumulative):
            return None
        data = self.ws.load_onboarding_file("session")
        cost, new = session_cost(data, session_id, cumulative)
        if new is not None:
            self.ws.save_onboarding_file("session", new)
        return cost

    # ----------------------------------------------------------------- consumo
    def usage(self):
        raw = self.ws.load_onboarding_file("usage").get("total")
        return _add(empty_usage(), raw if isinstance(raw, dict) else {})

    def add_usage(self, used):
        total = _add(self.usage(), used)
        self.ws.save_onboarding_file("usage", {"schema": 1, "total": total})
        return total


# ------------------------------------------------------------------ las propuestas
class Stale(Conflict):
    """Lo de ahora cambió desde la propuesta (N5): no se guarda (409)."""


class Proposals:
    """Proponer, guardar y descartar. `supply` es el `SupplyService` del workspace (sus
    proveedores y su escritura); `settings`, `sessions` y `broadcast`, lo que necesita
    `settings_api.save` para las unidades."""

    def __init__(self, ws, supply_service, settings=None, sessions=None, broadcast=None):
        self.ws = ws
        self.supply = supply_service
        self.settings = settings
        self.sessions = sessions
        self.broadcast = broadcast
        self.store = OnboardingStore(ws)
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- lo de ahora
    def current(self, que):
        """Lo de ahora de `que`, como lo ve la tarjeta (y lo que se compara en la huella)."""
        if que == "perfil":
            return self.ws.load_manufacturing_profile()
        if que == "proveedores":
            return self.supply.providers()
        if que == "unidades":
            return units.clean(self.ws.load_units())
        raise ValueError(i18n.t("onboarding.que_desconocido", que=repr(que)))

    def _raw(self, que):
        """Lo que hay guardado tal cual: un `proveedores.toml` roto a mano también cuenta como
        cambio, aunque `current` lo lea como lista vacía."""
        if que == "proveedores":
            return self.ws.load_providers_text()
        return self.current(que)

    def fingerprint(self, que):
        return fingerprint(self._raw(que))

    # ---------------------------------------------------------------- proponer
    def check(self, que, value):
        """Lo que se guardaría, con las reglas de la escritura (N4); ValueError si no vale o
        si no cambia nada."""
        if que == "perfil":
            new = workspace_api.check_profile(value)
        elif que == "proveedores":
            new = supply.check_providers(value, set(self.supply.library().types()))
        elif que == "unidades":
            if not isinstance(value, dict) or not value:
                raise ValueError(i18n.t("onboarding.unidades_vacias"))
            new = {**self.current("unidades"), **units.validate(value)}
        else:
            raise ValueError(i18n.t("onboarding.que_desconocido", que=repr(que)))
        if new == self.current(que):
            raise ValueError(i18n.t("onboarding.sin_cambios"))
        return new

    def propose(self, que, value, motivo, fuentes=None, log=None):
        """Valida y deja la tarjeta en el chat; devuelve su evento. `log` es lo que devolvieron
        las herramientas en este turno (`supply.SearchLog`), contra lo que se comprueba cada
        cita (N8): sin él, ninguna fuente se puede comprobar."""
        new = self.check(que, value)
        reason = _reason(motivo)
        event = {"type": "agent", "kind": "proposal", "id": uuid.uuid4().hex[:12], "que": que,
                 "antes": self.current(que), "nuevo": new, "motivo": reason,
                 "fuentes": check_sources(fuentes, log), "antes_huella": self.fingerprint(que),
                 "estado": PENDING, "at": time.time()}
        self.store.append(event)
        return event

    def propose_import(self, hoja, tipo, mapeo, motivo):
        """`proponer_importacion` (N7): a qué campo va cada columna del Excel elegido, con las
        reglas del importador (`check_mapping` sobre las columnas de esa hoja). Sin Excel
        elegido, ValueError. Deja la tarjeta y devuelve su evento."""
        ex = self.store.excel()
        if ex is None:
            raise ValueError(i18n.t("onboarding.sin_excel"))
        chosen = ex.get("sheet") or ""
        sheets = ex.get("sheets") or []
        sheet = (str(hoja or "").strip() or chosen) if sheets else chosen    # un CSV no tiene hojas
        if sheets and sheet not in sheets:
            raise ValueError(i18n.t("onboarding.hoja_no_existe", hoja=repr(sheet),
                                    hojas=", ".join(sheets)))
        if sheet == chosen:
            columns = ex.get("columns") or []
        else:
            columns = library_import.inspect(ex["file"], sheet or None)["columns"]
        mapping = library_import.check_mapping(mapeo, columns)
        type_ = str(tipo or "").strip()
        if type_:
            check_ficha_type(type_)
        elif any(t in library_import.META_TARGETS or t.startswith(library_import.VALUE_PREFIX)
                 for t in mapping.values()):
            raise ValueError(i18n.t("onboarding.importacion_sin_tipo"))
        event = {"type": "agent", "kind": "proposal", "id": uuid.uuid4().hex[:12], "que": IMPORT,
                 "antes": None, "nuevo": {"path": ex["file"], "sheet": sheet, "type": type_,
                                          "mapping": mapping},
                 "motivo": _reason(motivo), "fuentes": [], "antes_huella": None,
                 "estado": PENDING, "at": time.time()}
        self.store.append(event)
        return event

    # ------------------------------------------------------- guardar y descartar
    def _pending(self, proposal_id):
        p = self.store.proposals().get(proposal_id)
        if p is None:
            raise NotFound(i18n.t("onboarding.no_existe", id=proposal_id))
        if p.get("estado") != PENDING:
            raise Conflict(i18n.t("onboarding.ya_cerrada", estado=p.get("estado")))
        return p

    async def save(self, proposal_id):
        """Escribe lo propuesto por el camino de la interfaz, si lo de ahora no ha cambiado
        (N5). Devuelve la propuesta guardada. `Stale` (y la propuesta queda caducada) si
        cambió; Conflict si ya no está pendiente; NotFound si no existe."""
        async with self._lock:          # dos *Guardar* a la vez: el segundo ve la primera
            p = self._pending(proposal_id)
            if p.get("que") == IMPORT:     # la escribe el importador (`imported`), no Guardar
                raise ValueError(i18n.t("onboarding.importacion_desde_importador"))
            if self.fingerprint(p["que"]) != p.get("antes_huella"):
                self.store.set_state(proposal_id, STALE)
                raise Stale(i18n.t("onboarding.caducada"))
            await self._write(p["que"], p["nuevo"])
            self.store.set_state(proposal_id, SAVED)
            return {**p, "estado": SAVED}

    async def _write(self, que, new):
        if que == "perfil":
            workspace_api.save_profile(self.ws, new)
        elif que == "proveedores":
            self.supply.save_providers(new)
        elif que == "unidades":
            if self.settings is None:
                raise StorageError(i18n.t("ajustes.sin_workspace"))
            await settings_api.save(self.settings, self.ws, self.sessions, self.broadcast,
                                    {"unidades": new})

    async def imported(self, proposal_id, token, library):
        """*Importar* del importador abierto desde la tarjeta (N7): aplica su resumen
        (`library_import.apply`, que da Conflict si el archivo o la librería cambiaron) y deja
        la propuesta guardada. Devuelve lo que contó la importación en `importado`."""
        async with self._lock:
            p = self._pending(proposal_id)
            if p.get("que") != IMPORT:
                raise ValueError(i18n.t("onboarding.no_es_importacion"))
            result = await asyncio.to_thread(library_import.apply, library, token)
            self.store.set_state(proposal_id, SAVED)
            return {**p, "estado": SAVED, "importado": result}

    async def discard(self, proposal_id):
        async with self._lock:
            p = self._pending(proposal_id)
            self.store.set_state(proposal_id, DISCARDED)
            return {**p, "estado": DISCARDED}


def excel_event(got):
    """El evento `excel` del chat (N7) con lo que dio `library_import.inspect`."""
    return {"type": "agent", "kind": "excel", "id": uuid.uuid4().hex[:12],
            "nombre": Path(got["file"]).name, **got, "at": round(time.time(), 3)}


def _reason(motivo):
    """El motivo de una propuesta en una línea; ValueError si no hay."""
    reason = " ".join(str(motivo or "").split())
    if not reason:
        raise ValueError(i18n.t("onboarding.sin_motivo"))
    return reason[:REASON_MAX]


def check_sources(fuentes, log):
    """Las fuentes de una propuesta (N8): `[{url, cita}]`, con la URL `http(s)` y la cita tal
    cual en lo que devolvieron las herramientas (`log`): en esa página si se abrió, o en los
    resultados del buscador si la URL salió en ellos. Una que no se puede comprobar rechaza
    la propuesta entera (ValueError)."""
    if fuentes in (None, []):
        return []
    if not isinstance(fuentes, list) or len(fuentes) > SOURCES_MAX:
        raise ValueError(i18n.t("onboarding.fuentes_no_validas", max=SOURCES_MAX))
    out = []
    for f in fuentes:
        url = str(f.get("url") or "").strip() if isinstance(f, dict) else ""
        quote = " ".join(str(f.get("cita") or "").split())[:QUOTE_MAX] if isinstance(f, dict) else ""
        if not supply.host_of(url) or not quote:
            raise ValueError(i18n.t("onboarding.fuente_no_valida", url=repr(url)))
        found = log is not None and (log.quoted_in_page(url, quote) or (
            url in log.result_urls() and log.quoted_anywhere(quote)))
        if not found:
            raise ValueError(i18n.t("onboarding.cita_sin_comprobar", url=url))
        out.append({"url": url, "cita": quote})
    return out
