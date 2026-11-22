// Quién abre la *Librería* (PLAN_V020 §5): antes era estado de la pantalla de inicio; desde FF 7.6
// vive en `Root`, porque también la abre la tarjeta de importación del onboarding
// (PLAN_ONBOARDING N7, riesgo 3) con el importador ya rellenado, y al cerrarla se vuelve al chat.
import { useSyncExternalStore } from "react";
import type { ImportInitial } from "./library";

export type LibraryOpen = { open: boolean; initial: ImportInitial | null; back: (() => void) | null; seq: number };

let state: LibraryOpen = { open: false, initial: null, back: null, seq: 0 };
const listeners = new Set<() => void>();

function set(patch: Partial<LibraryOpen>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

/** Abre la *Librería*; con `initial`, en el importador rellenado. `back`, lo que se hace al
 *  cerrarla (volver al chat del onboarding). */
export const openLibrary = (initial: ImportInitial | null = null, back: (() => void) | null = null) =>
  set({ open: true, initial, back, seq: state.seq + 1 });

export function closeLibrary() {
  const back = state.back;
  set({ open: false, initial: null, back: null });
  back?.();
}

export function useLibraryOpen(): LibraryOpen {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
  );
}
