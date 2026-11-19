// Ancho del panel derecho (plan D60, D174): se arrastra por su borde izquierdo, nunca baja de
// 320 px y nunca pasa del 60 % de la ventana, ni deja la pizarra por debajo de `BOARD_MIN`
// (salvo que la ventana sea tan estrecha que no llegue al mínimo: entonces manda el mínimo).
// La pizarra también tiene su mínimo (D60): por debajo de ~880 px la barra de herramientas de
// abajo pisa el zoom y la ayuda, y por debajo de 730 Excalidraw pasa a su modo móvil y quita
// la barra de arriba. Se guarda en `settings.toml` por
// `/api/settings/panels` (`AgentPanel`), que tampoco guarda nada por debajo del mínimo.

export const PANEL_MIN = 320;
export const PANEL_MAX_SHARE = 0.6;
export const PANEL_DEFAULT = 420;
export const BOARD_MIN = 880;

/** El ancho que se pinta para `wanted` en una ventana de `viewport` px. */
export function clampPanel(wanted: number, viewport: number): number {
  const w = Number.isFinite(wanted) ? wanted : PANEL_DEFAULT;
  const max = Math.max(PANEL_MIN, Math.min(Math.floor(viewport * PANEL_MAX_SHARE), viewport - BOARD_MIN));
  return Math.round(Math.min(max, Math.max(PANEL_MIN, w)));
}
