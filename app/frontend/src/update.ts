// El actualizador visto desde la interfaz (docs/PLAN_V020.md §4, V9-V13). Lo hace el shell;
// el backend da lo que sabe (`GET /api/update`, lo que dejó el shell en `update.json`) y le
// pasa lo que pide el usuario (`POST /api/update/check` o `/install`). El shell avisa además con
// el evento `pizarra-update` en cuanto ve una versión nueva. **Instalar solo lo pide el
// usuario**: nada de aquí lo hace por su cuenta.
import { useSyncExternalStore } from "react";
import { apiFetch } from "./auth";

import { parseState, UNKNOWN, type UpdateState } from "./updateState";

export { canInstall, notesOf, showBanner, statusText, type UpdateState } from "./updateState";

const DISMISSED = "boardprint.update.dismissed";

// ------------------------------------------------------------------ estado compartido
let current: UpdateState = UNKNOWN;
let dismissed: string | null = null;
const listeners = new Set<() => void>();
let snapshot: { state: UpdateState; dismissed: string | null } = { state: current, dismissed };

function publish() {
  snapshot = { state: current, dismissed };
  for (const l of listeners) l();
}

try { dismissed = localStorage.getItem(DISMISSED); } catch { /* sin almacenamiento */ }

export async function refreshUpdate(): Promise<UpdateState> {
  try {
    const r = await apiFetch("/api/update");
    current = r.ok ? parseState(await r.json()) : UNKNOWN;
  } catch {
    current = UNKNOWN;
  }
  publish();
  return current;
}

/** Pide al shell que busque, y espera (hasta `waitMs`) a que deje una respuesta distinta. */
export async function checkNow(waitMs = 20000): Promise<UpdateState> {
  const before = JSON.stringify(current);
  await apiFetch("/api/update/check", { method: "POST" });
  const until = Date.now() + waitMs;
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 1000));
    if (JSON.stringify(await refreshUpdate()) !== before) break;
  }
  return current;
}

export async function installUpdate(): Promise<void> {
  await apiFetch("/api/update/install", { method: "POST" });
  current = { ...current, estado: "instalando" };
  publish();
}

export function dismissUpdate(version: string) {
  dismissed = version;
  try { localStorage.setItem(DISMISSED, version); } catch { /* sin almacenamiento */ }
  publish();
}

if (typeof window !== "undefined") {
  window.addEventListener("pizarra-update", (e) => {
    current = parseState((e as CustomEvent).detail);
    publish();
  });
}

export function useUpdate() {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l); },
    () => snapshot,
  );
}
