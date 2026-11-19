// Estado de la herramienta *Tinta* de la barra (plan D189): si está activa, qué pincel o el
// borrador, el color de cada pincel y el grosor. Vive fuera de React porque lo leen el botón
// (dentro de `renderTopRightUI` de Excalidraw) y la capa de la tinta. Las transiciones son
// funciones puras; `useInkTool`/`setInkTool` son el almacén.
import { useSyncExternalStore } from "react";
import type { Brush } from "./ink";

export type InkMode = Brush | "borrador";
export const INK_MODES: readonly InkMode[] = ["rotulador", "pluma", "subrayador", "borrador"];

// Los cinco colores (D189): la tinta del skin (la misma que el negro del lápiz de Excalidraw,
// que el tema oscuro aclara), rojo, azul, verde y el amarillo del subrayador.
export const INK_COLORS = ["#1e1e1e", "#e03131", "#1971c2", "#2f9e44", "#fab005"] as const;
export const HIGHLIGHT_COLOR = "#fab005";
// Los tres grosores, en px de la escena (el subrayador los multiplica por 3, ink.ts).
export const INK_SIZES = [2, 4, 8] as const;

export type InkToolState = {
  active: boolean;
  mode: InkMode;
  /** El último pincel elegido (con el borrador puesto, al que se vuelve al elegir un color). */
  brush: Brush;
  /** Cada pincel recuerda su color: el subrayador empieza en amarillo y los demás en la tinta. */
  colors: Record<Brush, string>;
  size: number;
};

export const DEFAULT_INK_TOOL: InkToolState = {
  active: false, mode: "rotulador", brush: "rotulador",
  colors: { rotulador: INK_COLORS[0], pluma: INK_COLORS[0], subrayador: HIGHLIGHT_COLOR },
  size: 4,
};

/** Activa o suelta la herramienta (el botón y el atajo). */
export const toggleInk = (s: InkToolState): InkToolState => ({ ...s, active: !s.active });
export const releaseInk = (s: InkToolState): InkToolState => (s.active ? { ...s, active: false } : s);

/** Elegir un pincel o el borrador en el menú también activa la herramienta. */
export function pickMode(s: InkToolState, mode: InkMode): InkToolState {
  return { ...s, active: true, mode, brush: mode === "borrador" ? s.brush : mode };
}

/** Un color es del pincel en uso; con el borrador puesto, vuelve al último pincel con ese color. */
export function pickColor(s: InkToolState, color: string): InkToolState {
  return { ...s, active: true, mode: s.brush, colors: { ...s.colors, [s.brush]: color } };
}

export function pickSize(s: InkToolState, size: number): InkToolState {
  return { ...s, active: true, size, mode: s.mode === "borrador" ? s.brush : s.mode };
}

/** El color con el que pinta ahora. */
export const toolColor = (s: InkToolState) => s.colors[s.brush];

// ------------------------------------------------------------------ almacén
let state = DEFAULT_INK_TOOL;
const listeners = new Set<() => void>();

export function getInkTool(): InkToolState {
  return state;
}

export function setInkTool(next: InkToolState | ((s: InkToolState) => InkToolState)) {
  const v = typeof next === "function" ? next(state) : next;
  if (v === state) return;
  state = v;
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => { listeners.delete(l); };
};

export function useInkTool(): InkToolState {
  return useSyncExternalStore(subscribe, getInkTool, getInkTool);
}
