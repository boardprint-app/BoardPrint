// Reglas de la tarjeta de un bloque (plan §3, D77) que no dependen de React ni de Excalidraw,
// y el reenvío de la rueda a su canvas (lo único que mira el DOM de Excalidraw).

export const BLOCK_MIN_WIDTH = 240;   // D60: caben etiqueta, campo y unidad de un parámetro
export const BLOCK_MIN_HEIGHT = 120;  // cabecera y un parámetro

/** Alto justo para el contenido: ni barra de scroll dentro ni menos que el mínimo. */
export const contentHeight = (content: number) => Math.max(BLOCK_MIN_HEIGHT, Math.ceil(content));

/** Alto de la tarjeta: sigue a su contenido en los dos sentidos (crece al salir una tabla o un
 *  error y vuelve a encoger al cerrarla, al acortarse las salidas o al quitarse el error).
 *  `fitted` es el último alto que la tarjeta se puso sola (`null` si aún ninguno): si el de
 *  ahora es otro, lo ha estirado el usuario y se respeta, pero nunca por debajo del contenido. */
export function blockHeight(current: number, content: number, fitted: number | null = null): number {
  const need = contentHeight(content);
  const stretched = fitted !== null && Math.abs(current - fitted) >= 1;
  return stretched ? Math.max(need, current) : need;
}

type Wheel = { deltaY: number; ctrlKey: boolean; metaKey: boolean };
type Scroll = { scrollTop: number; scrollHeight: number; clientHeight: number };

// La rueda encima de un bloque: Excalidraw solo desplaza el lienzo si el evento llega a su
// canvas, así que se le reenvía salvo cuando la tarjeta puede desplazarse en esa dirección.
// Con Ctrl (zoom) va siempre al lienzo.
export function wheelToCanvas(ev: Wheel, box: Scroll): boolean {
  if (ev.ctrlKey || ev.metaKey) return true;
  if (ev.deltaY < 0) return box.scrollTop <= 0;
  if (ev.deltaY > 0) return box.scrollTop + box.clientHeight >= box.scrollHeight - 1;
  return true;
}

/** Manda la rueda al canvas de Excalidraw de la pizarra en la que está `from`: desde la tarjeta
 *  (BlockView) y desde la interfaz propia de un paquete (PackFrame, P54). */
export function wheelOnCanvas(from: Element, init: WheelEventInit) {
  const canvas = from.closest(".excalidraw")?.querySelector("canvas.interactive");
  canvas?.dispatchEvent(new WheelEvent("wheel", { ...init, bubbles: true, cancelable: true }));
}

/** El desplegable de un parámetro de lista no se corta (PLAN_EXCEL §3.6): si su texto más largo
 *  no cabe en el campo de siempre (90 px, unos 10 caracteres), su ancho en `ch` (el texto y la
 *  flecha), con tope; lo que pase del tope se ve entero al pasar el ratón (`title`). Null:
 *  cabe. */
export function choiceWidth(labels: string[], fits = 10, max = 26): number | null {
  const longest = Math.max(0, ...labels.map((l) => [...l].length));
  return longest <= fits ? null : Math.min(longest + 4, max);
}
