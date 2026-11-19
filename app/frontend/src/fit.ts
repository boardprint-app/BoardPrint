// Encuadrar (Mayús+1, Mayús+2, Mayús+3) con los márgenes de la interfaz de verdad.
//
// Excalidraw 0.18 encuadra dejando por arriba el alto de su barra de herramientas
// (`.App-toolbar.bottom + 16`, en `getEditorUIOffsets`). Desde R37 esa barra está abajo: el
// margen de arriba se comía la pantalla entera, el zoom se iba al 10 % y todo quedaba fuera de
// la vista (prueba de punta a punta de FF 4.8). La app atiende esos tres atajos antes que
// Excalidraw y encuadra con `scrollToContent`, que acepta los márgenes. Son configurables
// (D185): la combinación sale de la tabla de shortcuts.ts.
import { matches, shortcut, SHORTCUTS } from "./shortcuts";

export type Box = { top: number; bottom: number; left: number; right: number };
export type Offsets = { top: number; right: number; bottom: number; left: number };

/** Lo que hace cada atajo, como en Excalidraw: 1, todo; 2, lo seleccionado (o todo) sin
 *  pasar del 100 %; 3, lo seleccionado (o todo) llenando la vista. */
export type FitKind = "all" | "selection" | "viewport";

export const FIT_PADDING = 16;

type KeyEv = { key?: string; code: string; shiftKey: boolean; ctrlKey: boolean; metaKey: boolean; altKey: boolean };

const FIT_ACTIONS: [string, FitKind][] = [["view.fit_all", "all"], ["view.fit_selection", "selection"],
                                          ["view.fit_viewport", "viewport"]];

/** El encuadre de una pulsación con los atajos de ahora (por defecto Mayús+1, 2 y 3). Las
 *  cifras casan por `code` (la tecla física): con Mayús, `key` es «!» o «"» según el teclado
 *  (`matches` en shortcuts.ts). */
export function fitShortcut(ev: KeyEv): FitKind | null {
  const own = FIT_ACTIONS.find(([id]) => matches(ev, shortcut(id)))?.[1];
  if (own) return own;
  // Mayús+1, 2 y 3 son también los de Excalidraw: si el usuario movió el encuadre a otra tecla
  // y ninguna acción de la app las usa, la app las sigue atendiendo con su encuadre, porque el
  // de Excalidraw deja el zoom al 10 % (R37, R49).
  const native = EXCALIDRAW_FIT[ev.code];
  if (!native || !ev.shiftKey || ev.ctrlKey || ev.metaKey || ev.altKey) return null;
  return SHORTCUTS.some((s) => matches(ev, shortcut(s.id))) ? null : native;
}

const EXCALIDRAW_FIT: Record<string, FitKind> = { Digit1: "all", Digit2: "selection", Digit3: "viewport" };

/** Márgenes para encuadrar en una vista de `width` × `height`, con las cajas relativas a ella:
 *  `top`, lo que cuelga de arriba (la fila del menú y la barra de la app, la píldora); `toolbar`,
 *  la barra de herramientas de abajo; `left`, el panel de propiedades; `right`, la barra
 *  lateral (la biblioteca). Lo que no está no quita sitio. */
export function canvasOffsets(view: { width: number; height: number },
                              ui: { top: Box[]; toolbar: Box | null; left: Box | null; right: Box | null }): Offsets {
  const p = FIT_PADDING;
  return {
    top: Math.max(0, ...ui.top.map((b) => b.bottom)) + p,
    bottom: (ui.toolbar ? Math.max(0, view.height - ui.toolbar.top) : 0) + p,
    left: (ui.left ? Math.max(0, ui.left.right) : 0) + p,
    right: (ui.right ? Math.max(0, view.width - ui.right.left) : 0) + p,
  };
}
