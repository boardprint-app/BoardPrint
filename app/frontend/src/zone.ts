// `ver_zona` del agente (plan §4, D171): el backend pide por el WebSocket la imagen de un
// recuadro de la escena o de unos elementos (`zone_request`) y esta ventana la pinta
// (`zoneRender.ts`) y la devuelve (`zone_image`, backend/pizarra/zone.py). Aquí, lo que no
// necesita Excalidraw: qué se pinta y a qué escala.

export type Rect = { x: number; y: number; width: number; height: number };
export type ZoneRequest = {
  id: string;
  rect?: Rect;
  elements?: string[];
  maxSide?: number;
  excludeImages?: boolean;    // *Excluir adjuntos* (D169): sin las imágenes pegadas
};
type El = {
  id: string; type: string; x: number; y: number; width: number; height: number;
  isDeleted?: boolean; containerId?: string | null; points?: readonly (readonly number[])[];
  customData?: Record<string, unknown> | null;
};

export const MAX_SIDE = 1568;    // como zone.MAX_SIDE del backend
export const PADDING = 10;       // alrededor de los elementos pedidos
const MAX_SCALE = 2;             // un recuadro pequeño no se amplía más
const CANVAS_MAX = 8192;         // px del lienzo intermedio: el navegador no pinta uno mayor

/** Una imagen pegada (D84, D140): como `agent_board_tools.is_pasted_image`. */
export function isPastedImage(e: El): boolean {
  return e.type === "image" || e.customData?.kind === "image";
}

/** La caja de un elemento en la escena, sin rotación (basta para saber si toca el recuadro). */
export function box(e: El): Rect {
  if (e.points?.length) {
    const xs = e.points.map((p) => e.x + p[0]), ys = e.points.map((p) => e.y + p[1]);
    const x = Math.min(...xs), y = Math.min(...ys);
    return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y };
  }
  return { x: e.x, y: e.y, width: e.width, height: e.height };
}

const touches = (a: Rect, b: Rect) =>
  a.x <= b.x + b.width && b.x <= a.x + a.width && a.y <= b.y + b.height && b.y <= a.y + a.height;

/** Lo que se pinta: lo vivo que toca el recuadro, o los elementos pedidos con el texto que llevan
 * dentro; sin las imágenes pegadas si se excluyen. */
export function zoneSelection<T extends El>(all: readonly T[], req: ZoneRequest): T[] {
  const live = all.filter((e) => !e.isDeleted);
  let picked: T[] = [];
  if (req.elements) {
    const ids = new Set(req.elements);
    picked = live.filter((e) => ids.has(e.id) || (e.containerId != null && ids.has(e.containerId)));
  } else if (req.rect) {
    const r = req.rect;
    picked = live.filter((e) => touches(box(e), r));
  }
  return req.excludeImages ? picked.filter((e) => !isPastedImage(e)) : picked;
}

/** El recuadro de la imagen: el pedido o, con elementos, su caja (`bounds`: x0, y0, x1, y1) con
 * un margen. */
export function zoneCrop(req: ZoneRequest, bounds: readonly [number, number, number, number]): Rect {
  const [x0, y0, x1, y1] = bounds;
  return req.rect ?? { x: x0 - PADDING, y: y0 - PADDING, width: x1 - x0 + 2 * PADDING,
                       height: y1 - y0 + 2 * PADDING };
}

/** La escala de la escena a píxeles: el lado más largo del recuadro en `maxSide` como mucho, sin
 * ampliar más de ×2 y sin que el lienzo de todo lo pintado (`bounds` con el margen) pase de
 * `CANVAS_MAX`. */
export function zoneScale(crop: Rect, bounds: readonly [number, number, number, number],
                          maxSide = MAX_SIDE): number {
  const [x0, y0, x1, y1] = bounds;
  const drawn = Math.max(x1 - x0, y1 - y0) + 2 * PADDING;
  return Math.min(MAX_SCALE, maxSide / Math.max(crop.width, crop.height), CANVAS_MAX / drawn);
}
