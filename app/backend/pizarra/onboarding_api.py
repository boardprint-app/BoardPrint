"""Las rutas del agente de onboarding (docs/PLAN_ONBOARDING.md §5, §6, N4, N5, N10).

    POST /api/onboarding/proposals/{id}/save      la propuesta guardada | 409 si lo de ahora
                                                  cambió (queda caducada) o ya no está
                                                  pendiente | 404 | 422 si ya no valdría
    POST /api/onboarding/proposals/{id}/discard   la propuesta descartada | 409 | 404
    POST /api/onboarding/proposals/{id}/import {token}
                                                  *Importar* del importador abierto desde una
                                                  propuesta `importacion` (N7): aplica el
                                                  resumen y la deja guardada | 409 si el archivo
                                                  o la librería cambiaron | 404 | 422
    POST /api/onboarding/excel {path?, sheet?}    *Elegir Excel…* (N7): sin ruta, el diálogo del
                                                  sistema; deja en el chat `{kind: "excel", id,
                                                  file, nombre, sheets, sheet, columns, sample,
                                                  rows}` y lo devuelve | {"file": null} si se
                                                  cancela | 422 si no se puede leer

Guardar escribe por el mismo camino que la interfaz (`onboarding.Proposals.save`); el estado
nuevo va a las ventanas del chat como `{"type": "agent", "kind": "proposal_state", id, estado}`.

    WS /ws/onboarding?token=…      la conversación del workspace (`agent_onboarding.OnboardingChat`)
  cliente -> servidor: los del chat de diseño (`agent_chat.py`)
    {"type": "agent_ask", "text"} | {"type": "agent_stop"} | {"type": "agent_history"}
    {"type": "agent_privacy_ok"}
    {"type": "agent_reset"}                    *Empezar de nuevo*: charla y sesión fuera
  servidor -> cliente
    {"type": "agent_history", "events", "state"}   al abrir, al pedirlo y tras *Empezar de nuevo*
    {"type": "agent", "kind", "at", ...}       user|text|tool|tool_result|done|error|stopped,
                                               proposal (la tarjeta, §5) y proposal_state; sin
                                               guardar y solo a quien preguntó, privacy y limit
    {"type": "agent_state", "usage", "limit", "remaining", "privacy_seen", "busy"}
    {"type": "error", "message"}               un mensaje que no vale; la conexión sigue
Sin workspace abierto: `error` y se cierra con 4404.
"""
import asyncio
import json

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from pizarra import desktop, i18n, library_import

from pizarra.agent_onboarding import OnboardingAgent, OnboardingChat
from pizarra.onboarding import Proposals, excel_event
from pizarra.storage import Conflict, NotFound, StorageError
from pizarra.validation import ValidationError


class ImportIn(BaseModel):
    token: str


class ExcelIn(BaseModel):
    path: str | None = None
    sheet: str | None = None


def register(app, *, need_workspace, settings, sessions, broadcast, supply,
             ws_ok=lambda ws: True, claude_cli=None):
    """`supply` es el `SupplyService` de `supply_api` (`app.state.supply`); `ws_ok(ws)`, si
    el WebSocket trae el token y viene de esta máquina (`server.py`)."""
    state = {}

    def proposals():
        ws = need_workspace()
        if state.get("ws") is not ws:          # uno por workspace: su cerrojo es el de todos
            state.update(ws=ws, proposals=Proposals(ws, supply, settings, sessions, broadcast))
        return state["proposals"]

    def chat():
        p = proposals()
        if state.get("chat_of") is not p:      # el chat, sobre las mismas propuestas
            state.update(chat_of=p, chat=OnboardingChat(
                p, settings, lambda on_card: OnboardingAgent(p, on_card, cli_path=claude_cli,
                                                             settings=settings)))
        return state["chat"]

    async def run(fn, proposal_id, *args):
        try:
            return await fn(proposal_id, *args)
        except NotFound as exc:
            raise HTTPException(404, str(exc))
        except Conflict as exc:               # también `Stale` (el de server.py mira el tipo exacto)
            raise HTTPException(409, str(exc))
        except ValueError as exc:             # ya no valdría, o el almacenamiento falló
            raise HTTPException(422, str(exc))
        finally:                              # guardada, descartada o caducada: a las ventanas
            await chat().proposal_changed(proposal_id)

    @app.post("/api/onboarding/proposals/{proposal_id}/save")
    async def save_proposal(proposal_id: str):
        return await run(proposals().save, proposal_id)

    @app.post("/api/onboarding/proposals/{proposal_id}/discard")
    async def discard_proposal(proposal_id: str):
        return await run(proposals().discard, proposal_id)

    @app.post("/api/onboarding/proposals/{proposal_id}/import")
    async def import_proposal(proposal_id: str, body: ImportIn):
        return await run(proposals().imported, proposal_id, body.token, supply.library())

    @app.post("/api/onboarding/excel")
    async def choose_excel(body: ExcelIn):
        c = chat()                            # sin workspace, 503 de `need_workspace`
        path = body.path
        if not path:
            path = await asyncio.to_thread(
                desktop.choose_file, i18n.t("dialogo.importar_libreria"),
                [(i18n.t("dialogo.hojas_calculo"), "*.xlsx;*.xlsm;*.csv;*.tsv"),
                 (i18n.t("dialogo.todos"), "*.*")])
            if not path:
                return {"file": None}
        try:
            got = await asyncio.to_thread(library_import.inspect, path, body.sheet)
        except ValueError as exc:             # no es una hoja de cálculo, no existe, ilegible
            raise HTTPException(422, str(exc))
        event = excel_event(got)
        await c.emit(event)                   # al chat y a las ventanas; el agente, al preguntar
        return event

    @app.websocket("/ws/onboarding")
    async def ws_onboarding(ws: WebSocket):
        if not ws_ok(ws):
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            c = chat()
        except HTTPException as exc:          # sin workspace abierto
            await ws.send_json({"type": "error", "message": str(exc.detail)})
            await ws.close(code=4404)
            return
        c.clients.add(ws)
        try:
            await ws.send_json(c.history_msg())
            while True:
                raw = await ws.receive()
                if raw["type"] == "websocket.disconnect":
                    break
                # Un mensaje mal formado se contesta con un error; nunca cierra la conexión (R6).
                try:
                    msg = json.loads(raw.get("text") or "")
                    if not isinstance(msg, dict) or not str(msg.get("type", "")).startswith("agent_"):
                        raise ValidationError("se esperaba un mensaje agent_… en JSON")
                    await c.handle(ws, msg)
                except (ValidationError, StorageError, KeyError, ValueError, TypeError,
                        OSError) as exc:
                    await ws.send_json({"type": "error",
                                        "message": f"{type(exc).__name__}: {exc}"})
        except (WebSocketDisconnect, RuntimeError):     # RuntimeError: cerrada desde aquí
            pass
        finally:
            c.clients.discard(ws)

    app.state.onboarding = proposals
    app.state.onboarding_chat = chat
