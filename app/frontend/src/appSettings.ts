// Los ajustes de la app tal como los da `GET /api/settings` (plan D179): idioma, unidades,
// ventana, fuentes, atajos, agentes, skin, bienvenida y dónde se guarda el workspace. Un solo
// almacén para toda la interfaz; se recarga al abrir, tras guardar y cuando otra ventana
// cambia algo (`{type: "settings"}` por el WebSocket).
import { useSyncExternalStore } from "react";
import { apiFetch } from "./auth";
import { setLanguage, t } from "./i18n";
import { setUserShortcuts } from "./shortcuts";
import { cleanPrefs, SI, type UnitPrefs } from "./units";

export type AppSettings = {
  idioma: string;
  unidades: UnitPrefs;
  ventana: { modo: string; escala: number };
  fuentes: Record<"interfaz" | "pizarra" | "chat" | "numeros", string>;
  atajos: Record<string, string>;
  agentes: { animaciones_automaticas: boolean; tope_proyecto_usd: number;
             acceso: "sesion" | "api_key"; api_key_guardada: boolean;
             /** El revisor (PLAN_V020 V5): apagado | a_demanda | hitos. */
             intrusividad_revisor?: string;
             /** El modelo de cada agente (V7): opus | sonnet | haiku. */
             modelo_diseno?: string; modelo_revisor?: string;
             /** El agente de proveedores (PLAN_APROVISIONAMIENTO A5): haiku por defecto, y lo
              *  que puede gastar cada búsqueda. */
             modelo_proveedores?: string; tope_busqueda_usd?: number;
             /** El agente de onboarding (PLAN_ONBOARDING N6): Sonnet por defecto, y su tope
              *  por workspace. */
             modelo_onboarding?: string; tope_onboarding_usd?: number };
  /** Días hasta que una oferta caduca (A10, de 1 a 90). */
  ofertas_caducidad_dias?: number;
  skin: string;
  bienvenida_vista: boolean;
  workspace: { nombre: string; ruta: string | null; nube: string | null } | null;
  opciones: {
    idiomas: string[];
    unidades: Record<string, string[]>;
    juegos_unidades: Record<string, UnitPrefs>;
    modos_ventana: string[];
    escala: { min: number; max: number; paso: number };
    fuentes: Record<string, string[]>;
    skins: string[];
    intrusividades_revisor?: string[];
    modelos?: string[];
    caducidad_ofertas?: { min: number; max: number };
  };
};

let current: AppSettings | null = null;
const listeners = new Set<() => void>();

function publish(next: AppSettings) {
  const before = current?.idioma;
  current = { ...next, unidades: cleanPrefs(next.unidades) };
  setLanguage(current.idioma);
  // otro idioma: se recarga la interfaz entera, también Excalidraw y lo pintado (O11)
  if (before !== undefined && before !== current.idioma) window.location.reload();
  setUserShortcuts(current.atajos);         // los atajos los lee shortcuts.ts al pulsar (D185)
  listeners.forEach((l) => l());
}

export async function loadAppSettings(): Promise<AppSettings | null> {
  try {
    const r = await apiFetch("/api/settings");
    if (r.ok) publish(await r.json());
  } catch {
    // sin backend: se queda lo que había (o los de por defecto)
  }
  return current;
}

/** Guarda solo lo que cambia. Devuelve null si fue bien o el motivo del rechazo (todo o
 *  nada: si una clave no vale, no se guarda ninguna). */
export async function saveAppSettings(changes: Record<string, unknown>): Promise<string | null> {
  try {
    const r = await apiFetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return typeof body.detail === "string" ? body.detail : t("ajustes.error_http", { estado: r.status });
    publish(body);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

/** Guarda o borra la API key de Anthropic (O9): va al almacén del sistema, nunca a los
 *  ajustes, y lo que vuelve son los ajustes sin la clave. Null si fue bien o el motivo. */
export async function saveApiKey(key: string | null): Promise<string | null> {
  try {
    const r = await apiFetch("/api/settings/api-key", key === null ? { method: "DELETE" } : {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clave: key }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return typeof body.detail === "string" ? body.detail : t("ajustes.error_http", { estado: r.status });
    publish(body);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

export function getAppSettings() {
  return current;
}

export function useAppSettings(): AppSettings | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}

/** Las unidades de pantalla (SI hasta que llegan los ajustes). */
export function useUnits(): UnitPrefs {
  return useAppSettings()?.unidades ?? SI;
}
