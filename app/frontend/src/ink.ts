// Tinta encima de las tarjetas (plan §3, D82, D188-D195): un trazo de tinta es un `freedraw`
// de la escena con `customData.kind = "ink"` y `opacity 0`, así que Excalidraw lo guarda y lo
// deshace pero no lo pinta; lo pinta la capa de encima (AnchorLayer) con `perfect-freehand`.
// Reglas puras, sin React ni Excalidraw: pinceles, normalizar, «quieto», ancla y borrador.
import { getStroke, type StrokeOptions } from "perfect-freehand";
import type { Box, Pt } from "./anchors";
import { bounds, isClosed, segmentDistance, SHAPES, type Shape } from "./shapes";

export type Brush = "rotulador" | "pluma" | "subrayador";
export const BRUSHES: readonly Brush[] = ["rotulador", "pluma", "subrayador"];
export const brushOf = (v: unknown): Brush => (BRUSHES.includes(v as Brush) ? (v as Brush) : "rotulador");

/** Lo que guarda `customData.ink`: `size` en px de la escena y `opacity` de 0 a 1. */
export type InkData = { brush: Brush; size: number; opacity: number; shape?: Shape };

type El = Box & { id: string; type?: string; isDeleted?: boolean; opacity?: number; customData?: Record<string, unknown> };
type Stroke = El & { points?: readonly (readonly number[])[] };

export const isInk = (e: { customData?: Record<string, unknown> }) => e.customData?.kind === "ink";

/** Los datos de tinta de un elemento, con lo que falte o no valga por defecto (null si no es tinta). */
export function inkData(e: El): InkData | null {
  if (!isInk(e)) return null;
  const raw = (e.customData?.ink ?? {}) as Record<string, unknown>;
  const size = Number(raw.size);
  const opacity = Number(raw.opacity);
  const shape = SHAPES.includes(raw.shape as Shape) ? (raw.shape as Shape) : undefined;
  return {
    brush: brushOf(raw.brush),
    size: Number.isFinite(size) && size > 0 ? Math.min(size, 200) : 4,
    opacity: Number.isFinite(opacity) ? Math.min(1, Math.max(0.05, opacity)) : 1,
    ...(shape ? { shape } : {}),
  };
}

/** Un trazo de tinta siempre va con `opacity 0` (no lo pinta Excalidraw): si alguien se la sube
 *  en su panel, pasa a `customData.ink.opacity`. Lo que no es tinta, o ya está bien, sale igual. */
export function normalizeInk<T extends El>(e: T): T {
  if (!isInk(e) || !e.opacity) return e;
  const ink = { ...((e.customData?.ink ?? {}) as object), opacity: Math.min(1, e.opacity / 100) };
  return { ...e, opacity: 0, customData: { ...e.customData, ink } };
}

// Parámetros de `perfect-freehand` por pincel (D190). La pluma adelgaza con la presión del
// lápiz o, con ratón, con la velocidad; el rotulador casi no; el subrayador es ancho y plano.
export function strokeOptions(brush: Brush, size: number, realPressure = false): StrokeOptions {
  switch (brush) {
    case "pluma":
      return { size, thinning: 0.7, smoothing: 0.6, streamline: 0.45, simulatePressure: !realPressure,
        start: { taper: size * 2 }, end: { taper: size * 2 } };
    case "subrayador":
      return { size: size * 3, thinning: 0, smoothing: 0.5, streamline: 0.5, simulatePressure: false,
        start: { cap: false }, end: { cap: false } };
    default:
      return { size, thinning: 0.08, smoothing: 0.5, streamline: 0.5, simulatePressure: false };
  }
}

/** Un punto del trazo: x, y y, si es un lápiz, su presión (0-1). */
export type InkPoint = [number, number, number?];

/** El contorno del trazo (polígono en las mismas coordenadas que los puntos). */
export function outline(points: readonly InkPoint[], brush: Brush, size: number, realPressure = false): number[][] {
  const ps = points.map(([x, y, p]) => [x, y, p ?? 0.5]);
  return getStroke(ps, { ...strokeOptions(brush, size, realPressure), last: true });
}

/** El contorno como `d` de un `<path>` SVG (curvas por los puntos medios). */
export function svgPath(poly: readonly number[][]): string {
  if (!poly.length) return "";
  if (poly.length < 3) return `M${poly[0][0]},${poly[0][1]}Z`;
  const mid = (a: number[], b: number[]) => `${((a[0] + b[0]) / 2).toFixed(2)},${((a[1] + b[1]) / 2).toFixed(2)}`;
  let d = `M${mid(poly[0], poly[1])} Q`;
  for (let i = 1; i < poly.length; i++) d += `${poly[i][0].toFixed(2)},${poly[i][1].toFixed(2)} ${mid(poly[i], poly[(i + 1) % poly.length])} `;
  return d + "Z";
}

/** Cómo se pinta: el subrayador nunca opaco y multiplicando, para no tapar lo de debajo. */
export function paint(ink: InkData): { opacity: number; blend: "normal" | "multiply"; grain: boolean } {
  if (ink.brush === "subrayador") return { opacity: Math.min(ink.opacity, 1) * 0.4, blend: "multiply", grain: false };
  return { opacity: ink.opacity, blend: "normal", grain: ink.brush === "rotulador" };
}

// «Quieto» (D191): el puntero sigue pulsado y no se ha movido más de HOLD_PX en HOLD_MS.
export const HOLD_MS = 500;
export const HOLD_PX = 4;
export type Sample = Pt & { t: number };

export function isHeld(samples: readonly Sample[], now: number, pressed: boolean): boolean {
  if (!pressed || samples.length < 2) return false;
  const last = samples[samples.length - 1];
  let since = samples[0].t;
  for (let i = samples.length - 1; i >= 0; i--) {
    if (Math.hypot(samples[i].x - last.x, samples[i].y - last.y) > HOLD_PX) {
      since = samples[i + 1].t;
      break;
    }
    if (i === 0) return false; // nunca se movió: es un punto, no el final de un trazo
  }
  return now - since >= HOLD_MS;
}

// Las tarjetas que puede marcar la tinta (D192): las que pinta la app encima del lienzo.
export const CARD_KINDS = new Set(["postit", "block", "file", "folder", "image", "link"]);
const isCard = (e: El) => !e.isDeleted && CARD_KINDS.has(String(e.customData?.kind));

const inside = (b: Box, p: Pt) => p.x >= b.x && p.x <= b.x + b.width && p.y >= b.y && p.y <= b.y + b.height;

// Fracción del área de `a` que queda dentro de `b`.
function overlap(a: Box, b: Box): number {
  const w = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
  return w > 0 && h > 0 && a.width * a.height > 0 ? (w * h) / (a.width * a.height) : 0;
}

/** A qué tarjeta se ancla un trazo al acabarlo (D192): una flecha, a la de su punta; una forma
 *  cerrada, a la que rodea; si no, a la de más arriba con la mayoría de sus puntos. */
export function inkAnchor(points: readonly Pt[], shape: Shape | undefined, elements: readonly El[]): string | null {
  if (!points.length) return null;
  const cards = elements.filter(isCard).reverse();
  if (shape === "flecha") {
    const tip = points[1] ?? points[points.length - 1];
    return cards.find((c) => inside(c, tip))?.id ?? null;
  }
  const closed = shape ? shape !== "recta" : isClosed(points);
  if (closed) {
    const box = bounds(points);
    const around = cards.find((c) => overlap(c, box) >= 0.6);
    if (around) return around.id;
  }
  return cards.find((c) => points.filter((p) => inside(c, p)).length > points.length / 2)?.id ?? null;
}

/** Los puntos de un `freedraw` en la escena. */
export const absolutePoints = (e: Stroke): Pt[] => (e.points ?? []).map(([x, y]) => ({ x: e.x + x, y: e.y + y }));

/** La geometría de un `freedraw` para unos puntos de la escena: origen en el primero, como Excalidraw. */
export function freedrawGeometry(points: readonly Pt[]) {
  const o = points[0] ?? { x: 0, y: 0 };
  const rel = points.map((p) => [p.x - o.x, p.y - o.y] as [number, number]);
  const b = bounds(rel.map(([x, y]) => ({ x, y })));
  return { x: o.x, y: o.y, width: b.width, height: b.height, points: rel };
}

const cross = (o: Pt, a: Pt, b: Pt) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);

// Dos segmentos se tocan si se cruzan o si pasan a menos de `r` (los lados largos de una forma
// reconocida se cruzan con el borrador lejos de sus extremos).
function segmentsClose(a: Pt, b: Pt, c: Pt, d: Pt, r: number): boolean {
  if (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) return true;
  return Math.min(segmentDistance(a, c, d), segmentDistance(b, c, d), segmentDistance(c, a, b), segmentDistance(d, a, b)) <= r;
}

/** Los trazos de tinta que borra un recorrido del borrador (D195): los que pasan a menos de su
 *  medio grosor más `margin` px. Nunca una tarjeta, una forma ni un trazo del lápiz de Excalidraw. */
export function erased(path: readonly Pt[], elements: readonly Stroke[], margin = 6): string[] {
  const out: string[] = [];
  const route = path.length === 1 ? [path[0], path[0]] : path;
  for (const e of elements) {
    if (e.isDeleted || e.type !== "freedraw" || !isInk(e)) continue;
    const ink = inkData(e)!;
    const r = (ink.brush === "subrayador" ? ink.size * 3 : ink.size) / 2 + margin;
    const ps = absolutePoints(e);
    const pts = ps.length === 1 ? [ps[0], ps[0]] : ps;
    hit: for (let i = 1; i < route.length; i++)
      for (let j = 1; j < pts.length; j++)
        if (segmentsClose(route[i - 1], route[i], pts[j - 1], pts[j], r)) {
          out.push(e.id);
          break hit;
        }
  }
  return out;
}
