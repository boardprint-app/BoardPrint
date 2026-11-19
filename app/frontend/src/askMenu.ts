// *Preguntar al agente* en el clic derecho de un post-it o una foto (plan D176). Ese menú es el
// de Excalidraw (copiar, ordenar, duplicar, bloquear y borrar, §3 «Tarjetas y Excalidraw"), que
// no admite entradas propias: su etiqueta pasa por su traductor, que no conoce la nuestra. Se
// añade arriba del todo en el DOM en cuanto Excalidraw lo pinta, y al pulsarla se cierra con
// `contextMenu: null`. Si otra versión de Excalidraw cambia el menú (`ul.context-menu` con
// `li > button.context-menu-item`), la entrada no sale y el menú sigue como siempre.
// Con varios elementos seleccionados y el clic sobre uno de ellos, el hilo se ancla a todos.
import { useEffect } from "react";
import { viewportCoordsToSceneCoords } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { askAgent } from "./threadActions";
import { askLabel } from "./CardMenu";

const MARK = "data-bp-ask";
const ASKS = new Set(["postit", "image"]);
const FRAMES = 12;            // fotogramas que se espera a que Excalidraw pinte su menú

function item(label: string, onClick: () => void): HTMLElement[] {
  const li = document.createElement("li");
  li.setAttribute(MARK, "");
  li.setAttribute("data-testid", "askAgent");
  const b = document.createElement("button");
  b.type = "button";
  b.className = "context-menu-item";
  const l = document.createElement("div");
  l.className = "context-menu-item__label";
  l.textContent = label;
  const k = document.createElement("kbd");
  k.className = "context-menu-item__shortcut";
  b.append(l, k);
  li.append(b);
  li.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
  const hr = document.createElement("hr");
  hr.className = "context-menu-item-separator";
  hr.setAttribute(MARK, "");
  return [li, hr];
}

export function useAskInContextMenu(api: ExcalidrawImperativeAPI | null) {
  useEffect(() => {
    if (!api) return;
    let raf = 0;
    const onMenu = (ev: MouseEvent) => {
      cancelAnimationFrame(raf);
      document.querySelectorAll(`[${MARK}]`).forEach((n) => n.remove());
      const t = ev.target as HTMLElement | null;
      if (!t?.closest?.(".excalidraw") || t.closest("input, textarea, [contenteditable]")) return;
      const st = api.getAppState();
      const p = viewportCoordsToSceneCoords({ clientX: ev.clientX, clientY: ev.clientY }, st);
      const hit = [...api.getSceneElements()].reverse().find((e) =>
        p.x >= e.x && p.x <= e.x + e.width && p.y >= e.y && p.y <= e.y + e.height);
      const kind = hit?.type === "embeddable" ? (hit.customData as { kind?: string } | undefined)?.kind : undefined;
      if (!hit || !kind || !ASKS.has(kind)) return;
      const sel = Object.keys(st.selectedElementIds);
      const ids = sel.length > 1 && sel.includes(hit.id) ? sel : [hit.id];
      let n = 0;
      const inject = () => {
        const menu = document.querySelector(".excalidraw .context-menu");
        if (!menu) {
          if (++n < FRAMES) raf = requestAnimationFrame(inject);
          return;
        }
        if (menu.querySelector(`[${MARK}]`)) return;
        menu.prepend(...item(askLabel(ids.length), () => {
          api.updateScene({ appState: { contextMenu: null } as never });
          askAgent(api, ids);
        }));
        // Excalidraw lo encajó en la ventana sin la entrada nueva: si ahora se sale por abajo, sube.
        const pop = menu.closest(".popover") as HTMLElement | null;
        const over = pop ? pop.getBoundingClientRect().bottom - (window.innerHeight - 8) : 0;
        if (pop && over > 0) pop.style.top = `${(parseFloat(pop.style.top) || 0) - over}px`;
      };
      raf = requestAnimationFrame(inject);
    };
    window.addEventListener("contextmenu", onMenu, true);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("contextmenu", onMenu, true);
    };
  }, [api]);
}
