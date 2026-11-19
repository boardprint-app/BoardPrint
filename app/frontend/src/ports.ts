// Enchufes de un bloque (plan §3, D88, D96 revisada): círculos del color de su tipo sobre el
// borde, entradas a la izquierda y salidas a la derecha. El primero, a la altura de la
// cabecera; los demás, uno debajo de otro por el borde. No ocupan sitio dentro de la tarjeta:
// el nombre del puerto va en la línea de la conexión y, al pasar el ratón, en el enchufe. Su
// sitio es fijo desde arriba de la tarjeta, para que una conexión (flecha en ángulo con
// `fixedPoint`, R18) sepa dónde acaba aunque la tarjeta crezca.

import { accepts } from "./cards";

export const HEAD_H = 37;      // alto de la cabecera, borde incluido (px)
export const SOCKET_H = 22;    // separación entre enchufes del mismo lado

/** Centro vertical del enchufe `index` (0, 1…), medido desde arriba de la tarjeta. */
export function socketY(index: number): number {
  return HEAD_H / 2 + index * SOCKET_H;
}

// El color de un tipo: el del `[ports]` de su paquete, que manda el catálogo (P67); los del
// núcleo, aquí; el resto, de una paleta fija según el nombre del tipo, siempre el mismo.
const CORE: Record<string, string> = { "cad.modelo": "#8d99a6", carpeta: "#c58a2a" };   // (artifact FF 4.8)
const PALETTE = ["#e0a526", "#2aa198", "#4a8cc7", "#c2559b", "#7f8f3a", "#d9653b", "#6f5bd6", "#3a9e5c"];

/** Los tipos de puerto del catálogo (`catalog.ports`): su nombre legible y su color. */
export type PortTypes = Record<string, { label: string; color?: string | null }>;

export function portColor(type: string, ports: PortTypes): string {
  const own = ports[type]?.color;
  if (own) return own;
  if (CORE[type]) return CORE[type];
  if (type === "archivo" || type.startsWith("archivo.")) return "#4263eb";   // archivos y carpetas
  let h = 0;
  for (const ch of type) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/** Puertos en el orden en que se pintan: el de la declaración del paquete. */
export function portList(ports: Record<string, string>): { name: string; type: string }[] {
  return Object.entries(ports).map(([name, type]) => ({ name, type }));
}


// ------------------------------------------------------------------ conexiones (D88, R18)
// Excalidraw solo respeta `fixedPoint` en las flechas en ángulo, y solo si el punto queda a
// FIXED_BINDING_DISTANCE (5 px) del contorno; si no, pega la flecha al contorno.
export const BIND_GAP = 5;

export type Pt = { x: number; y: number };
export type Rect = { x: number; y: number; width: number; height: number };
export type Side = "in" | "out";

/** `fixedPoint` (fracción del ancho y del alto) del enchufe `index` de un lado del bloque. Una
 *  tarjeta de archivo tiene su enchufe a otra altura (`y`, desde arriba, cards.ts). */
export function fixedPointFor(side: Side, index: number, width: number, height: number,
                              y = socketY(index)): [number, number] {
  const x = side === "out" ? width + BIND_GAP : -BIND_GAP;
  return [x / width, y / height];
}

/** Punto de la escena donde acaba la flecha en ese enchufe. */
export function socketPoint(side: Side, index: number, r: Rect, y = socketY(index)): Pt {
  return { x: side === "out" ? r.x + r.width + BIND_GAP : r.x - BIND_GAP, y: r.y + y };
}

/** Primer recorrido en ángulo de una conexión, de la salida (sale a la derecha) a la entrada
 * (entra por la izquierda). Hacia delante, tres tramos con el codo a mitad; hacia atrás (la
 * entrada queda a la izquierda de la salida), sale, rodea por el hueco de debajo y entra. Solo
 * tramos horizontales o verticales, como exige Excalidraw. */
export function elbowRoute(s: Pt, e: Pt, src: Rect, dst: Rect, pad = 20): Pt[] {
  let pts: Pt[];
  if (e.x - s.x >= 2 * pad) {
    const mx = Math.round((s.x + e.x) / 2);
    pts = [s, { x: mx, y: s.y }, { x: mx, y: e.y }, e];
  } else {
    const below = Math.max(src.y + src.height, dst.y + dst.height) + pad;
    const between = src.y + src.height < dst.y ? (src.y + src.height + dst.y) / 2
      : dst.y + dst.height < src.y ? (dst.y + dst.height + src.y) / 2 : below;
    const my = Math.round(between);
    pts = [s, { x: s.x + pad, y: s.y }, { x: s.x + pad, y: my }, { x: e.x - pad, y: my },
      { x: e.x - pad, y: e.y }, e];
  }
  // Sin puntos repetidos ni puntos en mitad de un tramo recto.
  const uniq = pts.filter((p, i) => i === 0 || p.x !== pts[i - 1].x || p.y !== pts[i - 1].y);
  return uniq.filter((p, i) => i === 0 || i === uniq.length - 1
    || !((uniq[i - 1].x === p.x && p.x === uniq[i + 1].x) || (uniq[i - 1].y === p.y && p.y === uniq[i + 1].y)));
}

/** Dónde va el nombre del puerto sobre una conexión: en mitad de su tramo horizontal más largo
 * (se lee mejor que en uno vertical); si no tiene ninguno, en mitad del más largo. Puntos
 * relativos a la flecha, como los guarda Excalidraw. */
export function labelSpot(points: readonly (readonly [number, number])[]): Pt {
  let best = -1, at: Pt = { x: points[0][0], y: points[0][1] };
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1], [x1, y1] = points[i];
    const len = Math.hypot(x1 - x0, y1 - y0) * (y0 === y1 ? 2 : 1);   // lo horizontal gana
    if (len > best) { best = len; at = { x: (x0 + x1) / 2, y: (y0 + y1) / 2 }; }
  }
  return at;
}

/** Entradas de `dstInputs` que admiten una salida de tipo `type` y están libres: del mismo
 *  tipo, o `archivo` para cualquier `archivo.*` (D132). */
export function compatibleInputs(type: string, dstInputs: Record<string, string>,
                                 taken: Iterable<string>): string[] {
  const busy = new Set(taken);
  return Object.entries(dstInputs).filter(([p, t]) => accepts(t, type) && !busy.has(p)).map(([p]) => p);
}

/** Distancia de `p` a la línea de puntos `points` (relativos a `origin`, como los guarda
 *  Excalidraw): para saber si el ratón está sobre una conexión y enseñar su nombre (R37). */
export function distToPolyline(points: readonly (readonly [number, number])[], origin: Pt, p: Pt): number {
  let best = Infinity;
  for (let i = 1; i < points.length; i++) {
    const ax = origin.x + points[i - 1][0], ay = origin.y + points[i - 1][1];
    const bx = origin.x + points[i][0], by = origin.y + points[i][1];
    const dx = bx - ax, dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, ((p.x - ax) * dx + (p.y - ay) * dy) / len2)) : 0;
    best = Math.min(best, Math.hypot(p.x - (ax + t * dx), p.y - (ay + t * dy)));
  }
  return best;
}
