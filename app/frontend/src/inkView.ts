// Cómo se ve la tinta (plan D188, D190): el contorno de cada trazo en la escena, el color que
// sale tras el filtro de tinta del skin, el paso de la escena a la pantalla y el `freedraw` que
// se mete en la escena al acabar un trazo. Funciones puras, sin React ni Excalidraw: las usan la
// capa de la tinta (InkLayer) y lo que pinta a un PNG (inkCanvas: `ver_zona` y la miniatura).
import { absolutePoints, freedrawGeometry, inkData, isInk, outline, paint, svgPath, type Brush,
         type InkData, type InkPoint } from "./ink";
import type { Pt } from "./anchors";
import type { Shape } from "./shapes";

// ------------------------------------------------------------------ color tras el filtro
// El lienzo de Excalidraw pinta los trazos con un filtro CSS: en los skins oscuros el de su tema
// oscuro (`THEME_FILTER`), en los claros con color el `inkFilter` del skin (R10). La tinta no
// puede llevar ese filtro en su capa (un filtro aísla la capa y el subrayador ya no multiplicaría
// con las tarjetas de debajo), así que se le aplica al color: los filtros que usan los skins son
// matrices de color, y salen igual que en el navegador (en sRGB, como los aplica Chrome).
export const DARK_THEME_FILTER = "invert(93%) hue-rotate(180deg)";

type Rgb = [number, number, number];
type M3 = [number, number, number, number, number, number, number, number, number];
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const mul = (m: M3, [r, g, b]: Rgb): Rgb => [
  clamp01(m[0] * r + m[1] * g + m[2] * b),
  clamp01(m[3] * r + m[4] * g + m[5] * b),
  clamp01(m[6] * r + m[7] * g + m[8] * b),
];

// Matrices de Filter Effects 1 (§ «feColorMatrix» y las funciones de `filter`).
function hueRotate(deg: number): M3 {
  const a = (deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  return [
    0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928,
    0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.14, 0.072 - c * 0.072 - s * 0.283,
    0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072,
  ];
}
function saturate(v: number): M3 {
  return [
    0.213 + 0.787 * v, 0.715 - 0.715 * v, 0.072 - 0.072 * v,
    0.213 - 0.213 * v, 0.715 + 0.285 * v, 0.072 - 0.072 * v,
    0.213 - 0.213 * v, 0.715 - 0.715 * v, 0.072 + 0.928 * v,
  ];
}

const amount = (arg: string) => (arg.trim().endsWith("%") ? parseFloat(arg) / 100 : parseFloat(arg));
const angle = (arg: string) => {
  const v = parseFloat(arg);
  return arg.includes("turn") ? v * 360 : arg.includes("rad") && !arg.includes("grad") ? (v * 180) / Math.PI : v;
};

export function parseHex(hex: string): Rgb | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})(?:[0-9a-f]{2})?$/i.exec(hex.trim());
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as Rgb;
}

const toHex = (c: Rgb) => "#" + c.map((v) => Math.round(clamp01(v) * 255).toString(16).padStart(2, "0")).join("");

/** El color que se ve de `color` tras un filtro CSS de funciones de color (invert, hue-rotate,
 *  brightness, saturate, contrast, grayscale). Un color o un filtro que no entiende sale igual. */
export function filterColor(color: string, filter: string | null | undefined): string {
  let c = parseHex(color);
  if (!c || !filter || filter === "none") return color;
  for (const [, fn, arg] of filter.matchAll(/([a-z-]+)\(([^)]*)\)/g)) {
    const v = amount(arg);
    switch (fn) {
      case "invert": c = c.map((x) => clamp01(v + x * (1 - 2 * v))) as Rgb; break;
      case "brightness": c = c.map((x) => clamp01(x * v)) as Rgb; break;
      case "contrast": c = c.map((x) => clamp01((x - 0.5) * v + 0.5)) as Rgb; break;
      case "saturate": c = mul(saturate(v), c); break;
      case "grayscale": c = mul(saturate(1 - Math.min(1, v)), c); break;
      case "hue-rotate": c = mul(hueRotate(angle(arg)), c); break;
      default: return color;
    }
  }
  return toHex(c);
}

/** El filtro que pone el skin a la tinta del lienzo: el del tema oscuro o el suyo. */
export const skinInkFilter = (skin: { dark: boolean; inkFilter?: string }) =>
  skin.dark ? DARK_THEME_FILTER : skin.inkFilter ?? "none";

/** El de la tinta anclada a una tarjeta: ninguno, salvo con las tarjetas oscuras (CAD), que se
 *  aclara como la del lienzo (la negra no se veía sobre ellas; prueba de punta a punta de FF 4.9). */
export const cardInkFilter = (skin: { darkCards?: boolean }) => (skin.darkCards ? DARK_THEME_FILTER : "none");

// ------------------------------------------------------------------ escena ↔ pantalla
export type View = { scrollX: number; scrollY: number; zoom: number };

/** Un punto de la escena en la pantalla (relativo al lienzo), como AnchorLayer. */
export const toScreen = (p: Pt, v: View): Pt => ({ x: (p.x + v.scrollX) * v.zoom, y: (p.y + v.scrollY) * v.zoom });

/** La misma transformación para un `<g>` de SVG que pinta en coordenadas de la escena: el
 *  contorno y su grosor escalan con el zoom. */
export const viewTransform = (v: View) => `matrix(${v.zoom} 0 0 ${v.zoom} ${v.scrollX * v.zoom} ${v.scrollY * v.zoom})`;

// ------------------------------------------------------------------ trazos a pintar
type InkEl = {
  id: string; x: number; y: number; width: number; height: number; version?: number;
  type?: string; isDeleted?: boolean; strokeColor?: string;
  points?: readonly (readonly number[])[]; pressures?: readonly number[]; simulatePressure?: boolean;
  customData?: Record<string, unknown>;
};

/** Los puntos de un trazo con la presión del lápiz si la guardó (una por punto y sin simular). */
export function inkPoints(e: InkEl): { points: InkPoint[]; realPressure: boolean } {
  const abs = absolutePoints(e);
  const pr = e.pressures ?? [];
  const realPressure = !e.simulatePressure && pr.length === abs.length && abs.length > 0;
  return { points: abs.map((p, i) => (realPressure ? [p.x, p.y, pr[i]] : [p.x, p.y])), realPressure };
}

/** Los puntos de una forma ideal con un punto cada `step` como mucho, sin perder sus esquinas:
 *  `perfect-freehand` suaviza siguiendo los puntos, y con los cinco de una flecha o un rectángulo
 *  se come las esquinas y tuerce los lados. Los trazos a mano ya son densos y salen igual. */
export function densify(ps: readonly (readonly (number | undefined)[])[], step = 2): number[][] {
  const out: number[][] = ps.length ? [[ps[0][0] ?? 0, ps[0][1] ?? 0]] : [];
  for (let i = 1; i < ps.length; i++) {
    const [x0 = 0, y0 = 0] = ps[i - 1], [x1 = 0, y1 = 0] = ps[i];
    const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / step));
    for (let k = 1; k <= n; k++) out.push([x0 + ((x1 - x0) * k) / n, y0 + ((y1 - y0) * k) / n]);
  }
  return out;
}

export type Blend = "normal" | "multiply" | "screen";
export type InkStroke = {
  id: string; d: string; color: string; opacity: number; blend: Blend; grain: boolean;
  ink: InkData; anchor: string | null;
};

/** Cómo se pinta un trazo con el filtro de la superficie que tiene debajo: el color con el filtro
 *  y la pintura de su pincel. El subrayador, sobre lo oscuro (el lienzo de los skins oscuros, las
 *  tarjetas de CAD), aclara («screen») con su color sin filtrar en vez de multiplicar: multiplicando,
 *  el amarillo salía una banda negra (prueba de punta a punta de FF 4.9). */
export function surfacePaint(ink: InkData, color: string, filter: string | null | undefined):
    { color: string; opacity: number; blend: Blend; grain: boolean } {
  const p = paint(ink);
  if (p.blend === "multiply" && filter === DARK_THEME_FILTER) return { ...p, blend: "screen", color };
  return { ...p, color: filterColor(color, filter) };
}

/** El trazo de un elemento de tinta, listo para pintar en coordenadas de la escena (null si no es
 *  tinta, está borrado o no tiene puntos). `color` ya va con el filtro del skin, salvo si está
 *  anclada a una tarjeta, que va con `cardFilter`: las tarjetas claras no se invierten en los
 *  skins oscuros, así que la tinta que las marca conserva su color (el rojo sigue rojo sobre un
 *  post-it amarillo, R53); las oscuras (CAD) sí la aclaran (`cardInkFilter`). */
export function inkStroke(e: InkEl, filter: string | null | undefined,
                          cardFilter: string | null | undefined = "none"): InkStroke | null {
  if (e.isDeleted || e.type !== "freedraw" || !isInk(e)) return null;
  const ink = inkData(e as Parameters<typeof inkData>[0])!;
  const { points, realPressure } = inkPoints(e);
  if (!points.length) return null;
  const pts = points.length === 1 ? [points[0], points[0]] : ink.shape ? (densify(points) as InkPoint[]) : points;
  const d = svgPath(outline(pts, ink.brush, ink.size, realPressure));
  const anchor = typeof e.customData?.anchor === "string" ? (e.customData.anchor as string) : null;
  const color = e.strokeColor ?? "#1e1e1e";
  return { id: e.id, d, ...surfacePaint(ink, color, anchor ? cardFilter : filter), ink, anchor };
}

// ------------------------------------------------------------------ el elemento nuevo
export type NewInk = {
  points: readonly Pt[];
  pressures?: readonly number[];      // del lápiz, una por punto; sin ellas, sin presión real
  brush: Brush;
  color: string;
  size: number;
  shape?: Shape;
  anchor: string | null;
  created: string;                    // ISO, como lo sella App (D72)
  id: string;
  seed: number;
  versionNonce: number;
  updated: number;
};

/** El `freedraw` de un trazo de tinta (D188), con todos los campos de Excalidraw 0.18: con
 *  `opacity 0` (lo pinta la capa), el origen en el primer punto y autor y fecha ya puestos. */
export function inkElement(n: NewInk) {
  const pts = n.points.length === 1 ? [n.points[0], n.points[0]] : n.points;
  const geo = freedrawGeometry(pts);
  const real = !n.shape && !!n.pressures && n.pressures.length === n.points.length;
  const pressures = real ? (n.points.length === 1 ? [n.pressures![0], n.pressures![0]] : [...n.pressures!]) : [];
  return {
    id: n.id, type: "freedraw" as const,
    x: geo.x, y: geo.y, width: geo.width, height: geo.height,
    angle: 0, strokeColor: n.color, backgroundColor: "transparent", fillStyle: "solid" as const,
    strokeWidth: n.size, strokeStyle: "solid" as const, roughness: 0, opacity: 0,
    groupIds: [] as string[], frameId: null, index: null, roundness: null,
    seed: n.seed, version: 1, versionNonce: n.versionNonce, isDeleted: false,
    boundElements: null, updated: n.updated, link: null, locked: false,
    points: geo.points, pressures, simulatePressure: !real, lastCommittedPoint: null,
    customData: {
      kind: "ink",
      ink: { brush: n.brush, size: n.size, opacity: 1, ...(n.shape ? { shape: n.shape } : {}) },
      author: "user", created: n.created,
      ...(n.anchor ? { anchor: n.anchor } : {}),
    },
  };
}
