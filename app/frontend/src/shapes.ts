// Reconocimiento de formas al dibujar con la tinta (plan §3, D83, D191): si al acabar un trazo el
// puntero se queda quieto, el trazo pasa a la forma ideal más parecida (recta, flecha, círculo,
// elipse, rectángulo o triángulo) sin dejar de ser tinta. Funciones puras, sin React ni
// Excalidraw: recta por mínimos cuadrados (ejes principales), esquinas por Ramer-Douglas-Peucker,
// círculo y elipse por ajuste del radio en sus ejes. Lo que no encaja se queda a mano (null).
import type { Box, Pt } from "./anchors";

export type Shape = "recta" | "flecha" | "círculo" | "elipse" | "rectángulo" | "triángulo";   // i18n-ok: id guardado
export const SHAPES: readonly Shape[] = ["recta", "flecha", "círculo", "elipse", "rectángulo", "triángulo"];   // i18n-ok: id guardado
export type Recognized = { shape: Shape; points: Pt[] };

const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);
const sub = (a: Pt, b: Pt): Pt => ({ x: a.x - b.x, y: a.y - b.y });
const dot = (a: Pt, b: Pt) => a.x * b.x + a.y * b.y;

export function pathLength(ps: readonly Pt[]): number {
  let l = 0;
  for (let i = 1; i < ps.length; i++) l += dist(ps[i - 1], ps[i]);
  return l;
}

export function bounds(ps: readonly Pt[]): Box {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of ps) {
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
  }
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

const sizeOf = (ps: readonly Pt[]) => {
  const b = bounds(ps);
  return Math.max(b.width, b.height);
};

/** Distancia de `p` al segmento `a`-`b`. */
export function segmentDistance(p: Pt, a: Pt, b: Pt): number {
  const ab = sub(b, a);
  const l2 = dot(ab, ab);
  const t = l2 ? Math.min(1, Math.max(0, dot(sub(p, a), ab) / l2)) : 0;
  return dist(p, { x: a.x + ab.x * t, y: a.y + ab.y * t });
}

/** Un trazo se da por cerrado si sus extremos quedan a menos del 20 % de su tamaño. */
export function isClosed(ps: readonly Pt[]): boolean {
  if (ps.length < 3) return false;
  const size = sizeOf(ps);
  return size > 0 && dist(ps[0], ps[ps.length - 1]) < 0.2 * size;
}

// Índices de los vértices que deja Ramer-Douglas-Peucker con tolerancia `eps` (iterativo).
export function rdp(ps: readonly Pt[], eps: number): number[] {
  if (ps.length < 3) return ps.map((_, i) => i);
  const keep = new Array(ps.length).fill(false);
  keep[0] = keep[ps.length - 1] = true;
  const stack: [number, number][] = [[0, ps.length - 1]];
  while (stack.length) {
    const [i, j] = stack.pop()!;
    let worst = -1, far = 0;
    for (let k = i + 1; k < j; k++) {
      const d = segmentDistance(ps[k], ps[i], ps[j]);
      if (d > far) { far = d; worst = k; }
    }
    if (worst >= 0 && far > eps) {
      keep[worst] = true;
      stack.push([i, worst], [worst, j]);
    }
  }
  return keep.flatMap((k, i) => (k ? [i] : []));
}

/** `n` puntos repartidos a la misma distancia por el recorrido. */
export function resample(ps: readonly Pt[], n: number): Pt[] {
  const total = pathLength(ps);
  if (ps.length < 2 || total === 0) return ps.slice(0, 1);
  const step = total / (n - 1);
  const out: Pt[] = [ps[0]];
  let acc = 0;
  for (let i = 1; i < ps.length && out.length < n; i++) {
    let a = ps[i - 1];
    const b = ps[i];
    let d = dist(a, b);
    while (acc + d >= step && out.length < n) {
      const t = (step - acc) / d;
      a = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
      out.push(a);
      d = dist(a, b);
      acc = 0;
    }
    acc += d;
  }
  while (out.length < n) out.push(ps[ps.length - 1]);
  return out;
}

// Centro y ejes principales (u el largo, v el corto) de una nube de puntos.
function axes(ps: readonly Pt[]): { c: Pt; u: Pt; v: Pt } {
  const c = ps.reduce((s, p) => ({ x: s.x + p.x / ps.length, y: s.y + p.y / ps.length }), { x: 0, y: 0 });
  let sxx = 0, syy = 0, sxy = 0;
  for (const p of ps) {
    const d = sub(p, c);
    sxx += d.x * d.x; syy += d.y * d.y; sxy += d.x * d.y;
  }
  const th = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  return { c, u: { x: Math.cos(th), y: Math.sin(th) }, v: { x: -Math.sin(th), y: Math.cos(th) } };
}

function asLine(ps: readonly Pt[]): Recognized | null {
  const a = ps[0], b = ps[ps.length - 1];
  const chord = dist(a, b);
  if (chord < 10 || chord < 0.85 * pathLength(ps)) return null;
  const { c, u, v } = axes(resample(ps, 64));
  const dev = Math.max(...ps.map((p) => Math.abs(dot(sub(p, c), v))));
  if (dev > 0.06 * chord) return null;
  const on = (p: Pt) => {
    const t = dot(sub(p, c), u);
    return { x: c.x + u.x * t, y: c.y + u.y * t };
  };
  return { shape: "recta", points: [on(a), on(b)] };
}

// Una flecha de un solo trazo: una recta larga y, al final, un gancho de punta que vuelve hacia
// atrás y se aparta a un lado (una barba, o las dos pasando otra vez por la punta). La punta es el
// punto más lejano del inicio (las barbas vuelven hacia atrás), y el gancho se mide contra sí
// mismo, no contra el astil: la punta se dibuja del mismo tamaño sea cual sea el largo (en la
// prueba de punta a punta de FF 4.9, una flecha de ~550 px con la punta de ~40 no salía).
function asArrow(ps: readonly Pt[]): Recognized | null {
  const a = ps[0];
  let k = 0;
  ps.forEach((p, i) => { if (dist(a, p) > dist(a, ps[k])) k = i; });
  const tip = ps[k];
  const shaft = dist(a, tip);
  if (shaft < 20 || k === ps.length - 1) return null;
  const dir = { x: (tip.x - a.x) / shaft, y: (tip.y - a.y) / shaft };
  const n = { x: -dir.y, y: dir.x };
  const head = ps.slice(k + 1);
  const reach = Math.max(...head.map((p) => dist(p, tip)));
  if (reach < Math.max(0.03 * shaft, 8) || reach > 0.45 * shaft) return null;
  // El astil, recto; lo que está junto a la punta no cuenta (la primera barba de las dos).
  for (let i = 1; i < k; i++) {
    if (dist(ps[i], tip) > 1.5 * reach && segmentDistance(ps[i], a, tip) > 0.06 * shaft) return null;
  }
  let back = 0, side = 0;
  for (const p of head) {
    const d = sub(p, tip);
    const along = dot(d, dir);
    if (along > 0.25 * reach) return null;
    back += along / head.length;
    side = Math.max(side, Math.abs(dot(d, n)));
  }
  if (back > -0.25 * reach || side < 0.2 * reach) return null;
  const h = Math.min(0.25 * shaft, 60);
  const barb = (s: number): Pt => {
    const ang = (28 * Math.PI) / 180;
    const bx = -dir.x * Math.cos(ang) - s * -dir.y * Math.sin(ang);
    const by = -dir.y * Math.cos(ang) + s * -dir.x * Math.sin(ang);
    return { x: tip.x + bx * h, y: tip.y + by * h };
  };
  return { shape: "flecha", points: [a, tip, barb(1), tip, barb(-1)] };
}

// Ángulo interior en `b` (grados) del camino a-b-c.
function angleAt(a: Pt, b: Pt, c: Pt): number {
  const u = sub(a, b), w = sub(c, b);
  const cos = dot(u, w) / (Math.hypot(u.x, u.y) * Math.hypot(w.x, w.y) || 1);
  return (Math.acos(Math.max(-1, Math.min(1, cos))) * 180) / Math.PI;
}

// Las esquinas de un trazo cerrado: RDP desde el punto más alejado del centro (que es una
// esquina si las hay), quitando las casi rectas y juntando las muy cercanas.
function corners(loop: readonly Pt[], size: number): Pt[] {
  const { c } = axes(loop);
  let start = 0;
  loop.forEach((p, i) => { if (dist(p, c) > dist(loop[start], c)) start = i; });
  const ring = [...loop.slice(start), ...loop.slice(0, start), loop[start]];
  let cs = rdp(ring, 0.08 * size).slice(0, -1).map((i) => ring[i]);
  for (let changed = true; changed && cs.length > 2;) {
    changed = false;
    for (let i = 0; i < cs.length; i++) {
      const prev = cs[(i - 1 + cs.length) % cs.length], next = cs[(i + 1) % cs.length];
      if (dist(cs[i], next) < 0.12 * size || angleAt(prev, cs[i], next) > 150) {
        cs = cs.filter((_, j) => j !== i);
        changed = true;
        break;
      }
    }
  }
  return cs;
}

function polygonError(loop: readonly Pt[], cs: readonly Pt[]): number {
  let sum = 0;
  for (const p of loop) {
    let best = Infinity;
    for (let i = 0; i < cs.length; i++) best = Math.min(best, segmentDistance(p, cs[i], cs[(i + 1) % cs.length]));
    sum += best;
  }
  return sum / loop.length;
}

// El rectángulo ideal de cuatro esquinas: el giro, la media de los de sus lados (módulo 90°,
// recto si queda a menos de 8°), y los lados, la media de las dos esquinas de cada uno.
function idealRect(cs: readonly Pt[]): Pt[] {
  let sx = 0, sy = 0;
  for (let i = 0; i < 4; i++) {
    const d = sub(cs[(i + 1) % 4], cs[i]);
    const a = 4 * Math.atan2(d.y, d.x);
    sx += Math.cos(a); sy += Math.sin(a);
  }
  let th = Math.atan2(sy, sx) / 4;
  if (Math.abs(th) < (8 * Math.PI) / 180) th = 0;
  const u = { x: Math.cos(th), y: Math.sin(th) }, v = { x: -Math.sin(th), y: Math.cos(th) };
  const us = cs.map((p) => dot(p, u)).sort((p, q) => p - q);
  const vs = cs.map((p) => dot(p, v)).sort((p, q) => p - q);
  const u0 = (us[0] + us[1]) / 2, u1 = (us[2] + us[3]) / 2;
  const v0 = (vs[0] + vs[1]) / 2, v1 = (vs[2] + vs[3]) / 2;
  const at = (a: number, b: number): Pt => ({ x: u.x * a + v.x * b, y: u.y * a + v.y * b });
  return [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1), at(u0, v0)];
}

function asClosed(ps: readonly Pt[]): Recognized | null {
  const size = sizeOf(ps);
  const loop = resample([...ps, ps[0]], 96).slice(0, -1);
  const cs = corners(loop, size);
  if ((cs.length === 3 || cs.length === 4) && polygonError(loop, cs) < 0.035 * size) {
    if (cs.length === 3) return { shape: "triángulo", points: [...cs, cs[0]] };   // i18n-ok: id guardado
    return { shape: "rectángulo", points: idealRect(cs) };   // i18n-ok: id guardado
  }
  const { c, u, v } = axes(loop);
  const pu = loop.map((p) => dot(sub(p, c), u)), pv = loop.map((p) => dot(sub(p, c), v));
  const a = Math.sqrt((2 * pu.reduce((s, x) => s + x * x, 0)) / loop.length);
  const b = Math.sqrt((2 * pv.reduce((s, x) => s + x * x, 0)) / loop.length);
  if (!a || b < 0.2 * a) return null;
  const err = pu.reduce((s, x, i) => s + Math.abs(Math.hypot(x / a, pv[i] / b) - 1), 0) / loop.length;
  if (err > 0.1) return null;
  const round = a / b <= 1.15;
  const ra = round ? (a + b) / 2 : a, rb = round ? (a + b) / 2 : b;
  const points: Pt[] = [];
  for (let i = 0; i <= 48; i++) {
    const t = (2 * Math.PI * i) / 48;
    const ca = ra * Math.cos(t), sb = rb * Math.sin(t);
    points.push({ x: c.x + u.x * ca + v.x * sb, y: c.y + u.y * ca + v.y * sb });
  }
  return { shape: round ? "círculo" : "elipse", points };   // i18n-ok: id guardado
}

/** La forma ideal del trazo (puntos en la escena), o null si no se parece a ninguna. */
export function recognize(raw: readonly Pt[]): Recognized | null {
  const ps = raw.filter((p, i) => i === 0 || dist(p, raw[i - 1]) > 0.5);
  if (ps.length < 4 || sizeOf(ps) < 10) return null;
  // La flecha antes que la recta: una flecha larga con una sola barba también es casi recta.
  return isClosed(ps) ? asClosed(ps) : asArrow(ps) ?? asLine(ps);
}
