// El aviso de la primera animación de un proyecto (plan D144, D187). Lo decide el backend: al
// crear el agente la primera con «Animaciones automáticas» activado manda `animation_notice`
// por el WebSocket del proyecto (una sola vez por proyecto, marcado en `project.toml`), y la
// pizarra lo enseña abajo con *Ir a Ajustes* y *Entendido*. Aquí, si se ve y qué hace cada botón;
// lo pinta `FirstAnimationNotice.tsx`.
import { useSyncExternalStore } from "react";
import { openSettings } from "./settings";

/** La pestaña y la fila (su `data-row`) a las que lleva *Ir a Ajustes* (R49). */
export const NOTICE_TAB = "agentes" as const;
export const NOTICE_ROW = "animaciones_automaticas";

let shown = false;
const listeners = new Set<() => void>();

function set(next: boolean) {
  if (shown === next) return;
  shown = next;
  listeners.forEach((l) => l());
}

export const showAnimationNotice = () => set(true);
export const hideAnimationNotice = () => set(false);
export const animationNoticeShown = () => shown;

/** *Ir a Ajustes*: abre *Agentes* con la fila marcada (parpadea, `BLINK_MS`) y quita el aviso. */
export function goToAnimationSettings() {
  openSettings(NOTICE_TAB, NOTICE_ROW);
  hideAnimationNotice();
}

export function useAnimationNotice(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => shown,
  );
}
