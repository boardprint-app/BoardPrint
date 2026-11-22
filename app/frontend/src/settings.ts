// La ventana *Ajustes* (docs/PLAN_PAQUETES.md P78): se abre desde la pantalla de inicio, desde
// la píldora de la pizarra, desde el aviso de un paquete que falta y al soltar un `.bppack`
// (P82). Vive fuera de la pizarra, en `Root`: su estado no es el de ningún proyecto.
// Desde FF 4.7, con pestañas (D179): `openSettings(pestaña, fila)` abre una con una fila marcada
// (su `data-row`), p. ej. «Animaciones automáticas» desde el aviso de la primera animación.
import { useSyncExternalStore } from "react";

/** Qué instalar al abrir: rutas (escritorio: soltadas o del diálogo), archivos (navegador) o
 *  `pick`, que pide elegirlos. */
export type InstallRequest = { paths?: string[]; files?: File[]; pick?: boolean };
export type SettingsTab = "general" | "apariencia" | "atajos" | "agentes" | "cuentas" | "paquetes" | "avanzados";
export const SETTINGS_TABS: SettingsTab[] = ["general", "apariencia", "atajos", "agentes", "cuentas", "paquetes", "avanzados"];
export type SettingsState = {
  open: boolean; tab: SettingsTab; highlight: string | null; install: InstallRequest | null; seq: number;
};

let state: SettingsState = { open: false, tab: "general", highlight: null, install: null, seq: 0 };
const listeners = new Set<() => void>();

function set(patch: Partial<SettingsState>) {
  state = { ...state, ...patch, seq: state.seq + 1 };
  listeners.forEach((l) => l());
}

/** Abre *Ajustes* en `tab` (General si no se dice) y marca la fila `highlight` (su `data-row`). */
export const openSettings = (tab: SettingsTab = "general", highlight: string | null = null) =>
  set({ open: true, tab, highlight, install: null });
export const openInstall = (install: InstallRequest) =>
  set({ open: true, tab: "paquetes", highlight: null, install });
export const closeSettings = () => set({ open: false, install: null, highlight: null });
export const getSettings = () => state;

/** La fila marcada parpadea una vez durante medio segundo (D144, D187): se ve dónde está sin
 *  quedarse encendida. `settings.css` lo lee de `--st-hl-ms`. */
export const BLINK_MS = 500;

export function useSettings(): SettingsState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
  );
}
