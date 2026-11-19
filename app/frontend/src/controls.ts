// Controles genéricos de la tarjeta y del panel de un bloque (docs/PLAN_PAQUETES.md §5, P8,
// P52): qué va dónde, y la cuenta de la gráfica x-y y de la vista 2D. Sin React: lo pintan
// GenericControls.tsx (y BlockView/PackPanel, que colocan los controles).
//
// Los datos de `chart` y `view2d` los arma el paquete con el SDK (`chart()`, `view2d()`), que ya
// los comprueba; aquí se vuelven a mirar porque llegan por JSON de un paquete cualquiera: lo que
// no cuadra no se pinta (null) y el control lo dice.
import type { Value, ViewSurface } from "./store";

export type Control = "params" | "results" | "chart" | "view2d";
const KNOWN: Control[] = ["params", "results", "chart", "view2d"];
export const DEFAULT_CARD: Control[] = ["params", "results"];

/** Dónde pinta cada control declarado (§5): `params` encima de Ejecutar, los demás debajo del
 *  error y en el orden en que se declaran, así Ejecutar no cambia de sitio (D96). `"ui"` (la
 *  interfaz propia) o vacío: ninguno. Un control que la app no conoce no se pinta. */
export function layout(surface: ViewSurface | undefined, fallback: Control[] = DEFAULT_CARD) {
  const list = surface === undefined ? fallback : surface === "ui" ? [] : surface;
  const known = list.filter((c): c is Control => (KNOWN as string[]).includes(c));
  return { above: known.filter((c) => c === "params"), below: known.filter((c) => c !== "params") };
}

// --- Datos -------------------------------------------------------------------------------

/** Lo que da una vista previa, si tiene la forma de unas salidas (`{puerto: {campo: {value}}}`):
 *  entonces el panel genérico la pinta en vez de lo último ejecutado. Si no, null. */
export function asOutputs(v: unknown): Record<string, Record<string, Value>> | null {
  if (!isObj(v) || !Object.keys(v).length) return null;
  for (const fields of Object.values(v)) {
    if (!isObj(fields)) return null;
    for (const f of Object.values(fields)) if (!isObj(f) || !("value" in f)) return null;
  }
  return v as Record<string, Record<string, Value>>;
}

export type Axis = { label: string; unit: string };
export type Pt = [number, number];
export type ChartData = { x: Axis; y: Axis; curves: { label: string; points: Pt[] }[] };
export type Tone = "" | "accent" | "muted" | "warn";
export type PlaneItem =
  | { kind: "box"; box: [number, number, number, number]; label: string; tone: Tone }
  | { kind: "line"; points: Pt[]; label: string; tone: Tone }
  | { kind: "point"; point: Pt; label: string; tone: Tone };
export type PlaneData = { x: Axis; y: Axis; yDown: boolean; items: PlaneItem[] };

const TONES = ["", "accent", "muted", "warn"];
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const nums = (v: unknown, n: number) => Array.isArray(v) && v.length === n && v.every(isNum);
const pts = (v: unknown, min: number): v is Pt[] =>
  Array.isArray(v) && v.length >= min && v.every((p) => nums(p, 2));

function axis(v: unknown): Axis | null {
  return isObj(v) && typeof v.label === "string" && typeof v.unit === "string" ? { label: v.label, unit: v.unit } : null;
}

/** La gráfica de un campo con `control: "chart"`, o null si no cuadra. */
export function chartData(v: unknown): ChartData | null {
  if (!isObj(v) || !Array.isArray(v.curves) || !v.curves.length) return null;
  const x = axis(v.x), y = axis(v.y);
  if (!x || !y) return null;
  const curves: ChartData["curves"] = [];
  for (const c of v.curves) {
    if (!isObj(c) || typeof c.label !== "string" || !pts(c.points, 2)) return null;
    curves.push({ label: c.label, points: c.points });
  }
  return { x, y, curves };
}

/** La vista 2D de un campo con `control: "view2d"`, o null si no cuadra. */
export function planeData(v: unknown): PlaneData | null {
  if (!isObj(v) || !Array.isArray(v.items) || !v.items.length) return null;
  const x = axis(v.x), y = axis(v.y);
  if (!x || !y) return null;
  const items: PlaneItem[] = [];
  for (const it of v.items) {
    if (!isObj(it) || typeof (it.label ?? "") !== "string" || !TONES.includes((it.tone ?? "") as string)) return null;
    const label = (it.label ?? "") as string, tone = (it.tone ?? "") as Tone;
    const kinds = ["box", "line", "point"].filter((k) => k in it);
    if (kinds.length !== 1) return null;
    if (kinds[0] === "box" && nums(it.box, 4)) {
      const [x0, y0, x1, y1] = it.box as number[];
      items.push({ kind: "box", box: [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)], label, tone });
    } else if (kinds[0] === "line" && pts(it.line, 2)) items.push({ kind: "line", points: it.line, label, tone });
    else if (kinds[0] === "point" && nums(it.point, 2)) items.push({ kind: "point", point: it.point as Pt, label, tone });
    else return null;
  }
  return { x, y, yDown: v.y_down === true, items };
}

// --- Ejes --------------------------------------------------------------------------------

export type Ticks = { lo: number; hi: number; step: number; ticks: number[] };

/** Marcas «redondas» (1, 2 o 5 por una potencia de diez) que cubren [lo, hi] con unas `n`
 *  divisiones. Un rango de ancho cero se abre lo justo para que la curva no quede en el borde. */
export function niceTicks(lo: number, hi: number, n = 5): Ticks {
  if (hi < lo) [lo, hi] = [hi, lo];
  if (hi === lo) {
    const d = Math.abs(lo) * 0.1 || 1;
    lo -= d; hi += d;
  }
  const raw = (hi - lo) / Math.max(n, 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let i = 0, t = a; t <= b + step * 1e-6; i++, t = a + i * step) ticks.push(+t.toPrecision(12));
  return { lo: a, hi: b, step, ticks };
}

export type Pad = { l: number; r: number; t: number; b: number };

/** Escalas de la gráfica en un hueco de `w` × `h` px: de un valor a su píxel. */
export function chartFrame(d: ChartData, w: number, h: number, pad: Pad) {
  const all = d.curves.flatMap((c) => c.points);
  const xs = niceTicks(Math.min(...all.map((p) => p[0])), Math.max(...all.map((p) => p[0])), Math.max(2, Math.round(w / 70)));
  const ys = niceTicks(Math.min(...all.map((p) => p[1])), Math.max(...all.map((p) => p[1])), Math.max(2, Math.round(h / 40)));
  const iw = Math.max(w - pad.l - pad.r, 1), ih = Math.max(h - pad.t - pad.b, 1);
  const px = (x: number) => pad.l + ((x - xs.lo) / (xs.hi - xs.lo)) * iw;
  const py = (y: number) => pad.t + ih - ((y - ys.lo) / (ys.hi - ys.lo)) * ih;
  return { xs, ys, px, py, iw, ih };
}

/** El punto de `points` más cerca de `x` en horizontal (la lectura al pasar el ratón). */
export function nearestPoint(points: Pt[], x: number): Pt {
  let best = points[0];
  for (const p of points) if (Math.abs(p[0] - x) < Math.abs(best[0] - x)) best = p;
  return best;
}

// --- Vista 2D ----------------------------------------------------------------------------

function planeBounds(d: PlaneData) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const add = ([x, y]: Pt) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); };
  for (const it of d.items) {
    if (it.kind === "box") { add([it.box[0], it.box[1]]); add([it.box[2], it.box[3]]); }
    else if (it.kind === "line") it.points.forEach(add);
    else add(it.point);
  }
  return { x0, y0, x1, y1 };
}

/** Escala de la vista 2D **a escala** (1 en x mide lo mismo que 1 en y) para un ancho `w` px:
 *  cabe entera dentro de `w` × `maxH`, y el alto sale de la forma (entre `minH` y `maxH`). */
export function planeFrame(d: PlaneData, w: number, maxH: number, pad = 8, minH = 40) {
  const b = planeBounds(d);
  const dx = b.x1 - b.x0, dy = b.y1 - b.y0;
  // Un solo punto, o todo en una línea: la escala la pone el lado que tiene medida.
  const k = Math.min(dx > 0 ? (w - 2 * pad) / dx : Infinity, dy > 0 ? (maxH - 2 * pad) / dy : Infinity);
  const scale = Number.isFinite(k) && k > 0 ? k : 1;
  const h = Math.min(maxH, Math.max(minH, dy * scale + 2 * pad));
  // Centrado en el hueco que sobra.
  const ox = (w - dx * scale) / 2, oy = (h - dy * scale) / 2;
  const px = (x: number) => ox + (x - b.x0) * scale;
  const py = (y: number) => (d.yDown ? oy + (y - b.y0) * scale : h - oy - (y - b.y0) * scale);
  return { w, h, scale, px, py };
}

export type Label = { text: string; x: number; y: number; anchor: "start" | "end"; item: number };
export const LABEL_H = 12;
export const charW = 5.6;            // ancho medio de un carácter a 10 px

type Rect = { x0: number; y0: number; x1: number; y1: number };
const hits = (a: Rect, b: Rect) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

/** Dónde va el nombre de cada elemento, en píxeles: una caja, arriba a la izquierda por
 *  dentro (si cabe); un punto, a su derecha (a su izquierda si se sale); una línea, en su
 *  último punto. **Ningún nombre pisa a otro ni se sale de la vista**: el que no cabe no se
 *  pinta (queda en la ayuda del elemento). */
export function placeLabels(d: PlaneData, f: ReturnType<typeof planeFrame>): Label[] {
  const placed: Rect[] = [];
  const out: Label[] = [];
  d.items.forEach((it, i) => {
    if (!it.label) return;
    const tw = it.label.length * charW;
    let x: number, y: number, anchor: Label["anchor"] = "start";
    if (it.kind === "box") {
      const left = f.px(it.box[0]), right = f.px(it.box[2]);
      const top = Math.min(f.py(it.box[1]), f.py(it.box[3])), bottom = Math.max(f.py(it.box[1]), f.py(it.box[3]));
      if (right - left < tw + 8 || bottom - top < LABEL_H + 4) return;
      x = left + 4; y = top + 3;
    } else {
      const [px, py] = it.kind === "point" ? it.point : it.points[it.points.length - 1];
      x = f.px(px) + 5; y = f.py(py) - LABEL_H / 2;
      if (x + tw > f.w) { x = f.px(px) - 5; anchor = "end"; }
    }
    const r: Rect = anchor === "start" ? { x0: x, y0: y, x1: x + tw, y1: y + LABEL_H } : { x0: x - tw, y0: y, x1: x, y1: y + LABEL_H };
    if (r.x0 < 0 || r.x1 > f.w || r.y0 < 0 || r.y1 > f.h || placed.some((p) => hits(p, r))) return;
    placed.push(r);
    out.push({ text: it.label, x, y, anchor, item: i });
  });
  return out;
}
