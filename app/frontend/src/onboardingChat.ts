// La ventana del agente de onboarding (docs/PLAN_ONBOARDING.md §3, N2, N10): su estado
// (abierta, la conversación, el consumo) y la conexión con `/ws/onboarding` mientras está
// abierta, y *Guardar* / *Descartar* de sus tarjetas (§5). La lógica que no conecta, en
// onboarding.ts; la ventana, en `OnboardingDialog.tsx`.
import { useSyncExternalStore } from "react";
import { loadAppSettings } from "./appSettings";
import { apiFetch, wsOnboardingUrl } from "./auth";
import { t } from "./i18n";
import { applyMessage, stateChanged, type OnboardingSnap } from "./onboarding";
import type { AgentEvent } from "./store";

const EMPTY: OnboardingSnap = { open: false, log: [], busy: false, state: null, problem: null, profileRev: 0 };
let snap: OnboardingSnap = EMPTY;
const listeners = new Set<() => void>();

function set(patch: Partial<OnboardingSnap>) {
  snap = { ...snap, ...patch };
  listeners.forEach((l) => l());
}

export const getOnboarding = () => snap;

export function useOnboarding(): OnboardingSnap {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => snap,
  );
}

// ------------------------------------------------------------------ conexión

const GONE = new Set([4401, 4404]);       // sin token, o sin workspace abierto: no se reintenta
let ws: WebSocket | null = null;
let generation = 0;
const queue: string[] = [];

function connect() {
  const gen = ++generation;
  const sock = new WebSocket(wsOnboardingUrl());
  ws = sock;
  sock.onopen = () => {
    while (queue.length) sock.send(queue.shift()!);
  };
  sock.onmessage = (ev) => {
    if (gen !== generation) return;
    const msg = JSON.parse(ev.data);
    // sin workspace, el `error` llega justo antes del cierre 4404: va arriba, no al chat
    if (msg?.type === "error" && snap.state === null) return set({ problem: String(msg.message ?? "") });
    set(applyMessage(snap, msg));
  };
  sock.onclose = (ev) => {
    if (gen !== generation) return;        // cerrada desde aquí
    ws = null;
    if (GONE.has(ev.code)) return set({ state: null, busy: false, problem: snap.problem ?? t("onboarding.sin_workspace") });
    set({ problem: t("onboarding.desconectado") });
    setTimeout(() => gen === generation && snap.open && connect(), 1000);
  };
}

function disconnect() {
  generation++;
  queue.length = 0;
  const old = ws;
  ws = null;
  old?.close();
}

/** Abre la ventana y su conversación (la del workspace: la trae `agent_history` al conectar). */
export function openOnboarding() {
  if (snap.open) return;
  set({ ...EMPTY, open: true, profileRev: snap.profileRev });
  connect();
}

/** Cierra la ventana; el agente, si trabajaba, sigue en el backend y se ve al volver a abrir. */
export function closeOnboarding() {
  disconnect();
  set({ open: false });
}

export function onboardingSend(msg: object) {
  const data = JSON.stringify(msg);
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
  else queue.push(data);
}

/** Quita una tarjeta que no es conversación (privacidad, tope): no está en `chat.jsonl`. */
export const dropEvent = (ev: AgentEvent) => set({ log: snap.log.filter((e) => e !== ev) });

/** *Elegir Excel…* (N7): el diálogo del sistema en el backend, que deja el Excel en el chat; si
 *  se eligió uno, se le pide al agente que proponga cómo importarlo (sus columnas le llegan con
 *  la pregunta). Devuelve el motivo si no se pudo, o null. */
export async function chooseExcel(): Promise<string | null> {
  try {
    const r = await apiFetch("/api/onboarding/excel", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    const body = await r.json().catch(() => null);
    if (!r.ok) return typeof body?.detail === "string" ? body.detail : t("ajustes.error_http", { estado: r.status });
    if (body?.file) onboardingSend({ type: "agent_ask", text: t("onboarding.excel.pedido", { nombre: body.nombre ?? body.file }) });
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

/** *Guardar* o *Descartar* una propuesta (§5). Devuelve el motivo del rechazo, o null. El estado
 *  nuevo llega a todas las ventanas por el WebSocket; aquí se pone ya, por si no está. */
export async function closeProposal(p: AgentEvent, action: "save" | "discard"): Promise<string | null> {
  try {
    const r = await apiFetch(`/api/onboarding/proposals/${encodeURIComponent(p.id ?? "")}/${action}`, { method: "POST" });
    const body = await r.json().catch(() => null);
    if (!r.ok) {
      const detail = typeof body?.detail === "string" ? body.detail : t("ajustes.error_http", { estado: r.status });
      if (r.status === 409 || r.status === 404) onboardingSend({ type: "agent_history" });   // su estado de verdad
      return detail;
    }
    if (p.id && body?.estado) set(stateChanged(snap, p.id, body.estado));
    if (action === "save" && p.que === "unidades") void loadAppSettings();   // las unidades de la interfaz
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}
