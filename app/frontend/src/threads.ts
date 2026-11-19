// Hilos anclados sobre la pizarra (plan D57, D165-D167, R43): reglas puras, sin React ni
// Excalidraw, de la capa de hilos (`ThreadLayer`). Un hilo no es un elemento de la escena
// (D166): su ventana va en píxeles de la pizarra (no se mueve con el zoom ni con el
// desplazamiento) y sus anclas, por `id`.
//
// - La mini ventana nunca baja de `THREAD_MIN` (260×170, D60, el prototipo) ni se sale de la
//   vista: si la vista es más pequeña que la ventana, gana el mínimo y se pega arriba a la
//   izquierda (la cabecera, que es por donde se arrastra, siempre queda a la vista).
// - Un hilo se pinta si alguna de sus anclas sigue en la escena: se calcula aquí contra la
//   escena viva (el `sin_anclaje` del backend llega tarde cuando se borra o se deshace).
// - Minimizado es una etiqueta junto a su primer ancla viva (encima, o debajo si arriba está la
//   barra); si varios hilos empiezan en el mismo elemento, sus etiquetas se apilan. Nunca tapa
//   la interfaz fija de la pizarra, y con el ancla fuera de la vista no sale (`labelSpots`).
import { thread as segment, type Box, type Pt } from "./anchors";
import { t } from "./i18n";

export type Rect = { x: number; y: number; w: number; h: number };
export type View = { width: number; height: number };
export type ThreadSize = "min" | "window" | "full";
export type Layout = Rect & { size: ThreadSize };

export const THREAD_MIN = { w: 260, h: 170 };
export const THREAD_DEFAULT = { w: 340, h: 260 };
export const MARGIN = 8;                 // lo que queda entre la ventana y el borde de la vista
export const LABEL_H = 40;               // alto de una etiqueta (para apilarlas)
export const LABEL_GAP = 6;

// La interfaz fija de la pizarra (paso 5b): lo que nada de los hilos tapa. Se mide del DOM
// (`measureChrome` en threadActions.ts: la barra de arriba con todos sus botones, también su
// segunda fila cuando no cabe en una, el Filtro, la barra de herramientas, el zoom y la ayuda
// de abajo), relativo a la pizarra; aquí solo se usa lo medido. `top`: por debajo de aquí
// empieza la franja libre (la barra de arriba más un respiro); `bottom`: ahí acaba; `zones`:
// cada rectángulo medido (el Filtro está dentro de la franja). Sin poder medir, valen las
// constantes de una barra de una fila a 1440×900 (`defaultChrome`).
export type Chrome = { top: number; bottom: number; zones: Rect[] };
export const CHROME_GAP = 8;            // respiro entre la interfaz fija y lo de los hilos
export const CHROME_TOP = 62;           // sin medir: barra de una fila (~54 px) y su respiro
export const CHROME_BOTTOM = 64;        // sin medir: herramientas, zoom y ayuda (~56 px)
const FILTER = { w: 100, h: 46 };

/** La interfaz fija sin medir: la de una barra de una fila a 1440×900. */
export function defaultChrome(view: View): Chrome {
  return {
    top: CHROME_TOP, bottom: view.height - CHROME_BOTTOM,
    zones: [{ x: view.width - FILTER.w, y: CHROME_TOP, w: FILTER.w, h: FILTER.h }],
  };
}

/** La interfaz fija a partir de lo medido: los rectángulos de la barra de arriba (`top`), los
 *  de abajo (`bottom`) y los demás (el Filtro). Sin nada medido arriba o abajo, ese lado es el
 *  de `defaultChrome`. */
export function chromeFrom(view: View, top: readonly Rect[], bottom: readonly Rect[], others: readonly Rect[]): Chrome {
  const real = (r: Rect) => r.w > 0 && r.h > 0;
  const t = top.filter(real), b = bottom.filter(real);
  return {
    top: t.length ? Math.ceil(Math.max(...t.map((r) => r.y + r.h)) + CHROME_GAP) : CHROME_TOP,
    bottom: b.length ? Math.floor(Math.min(...b.map((r) => r.y)) - CHROME_GAP) : view.height - CHROME_BOTTOM,
    zones: [...t, ...b, ...others.filter(real)],
  };
}

const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

/** La ventana dentro de la vista, nunca debajo de la barra de arriba y nunca por debajo de su
 *  mínimo (D60, D166). Con una vista más pequeña que la ventana, el tamaño baja hasta caber,
 *  pero nunca del mínimo. */
export function clampWindow(r: Rect, view: View, chrome: Chrome = defaultChrome(view)): Rect {
  const num = (v: number, d: number) => (Number.isFinite(v) ? v : d);
  const top = chrome.top;
  const maxW = Math.max(THREAD_MIN.w, view.width - 2 * MARGIN);
  const maxH = Math.max(THREAD_MIN.h, view.height - top - MARGIN);
  const w = Math.min(maxW, Math.max(THREAD_MIN.w, num(r.w, THREAD_DEFAULT.w)));
  const h = Math.min(maxH, Math.max(THREAD_MIN.h, num(r.h, THREAD_DEFAULT.h)));
  const x = Math.max(MARGIN, Math.min(num(r.x, MARGIN), view.width - MARGIN - w));
  const y = Math.max(top, Math.min(num(r.y, top), view.height - MARGIN - h));
  return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
}

/** Arrastrar la cabecera `d` píxeles desde `start`. */
export function moveWindow(start: Rect, d: Pt, view: View, chrome?: Chrome): Rect {
  return clampWindow({ ...start, x: start.x + d.x, y: start.y + d.y }, view, chrome);
}

/** Arrastrar la esquina de abajo a la derecha: la de arriba a la izquierda no se mueve salvo
 *  que la vista no deje sitio, y el tamaño nunca baja del mínimo. */
export function resizeWindow(start: Rect, d: Pt, view: View, chrome?: Chrome): Rect {
  const w = Math.max(THREAD_MIN.w, Math.min(start.w + d.x, view.width - MARGIN - start.x));
  const h = Math.max(THREAD_MIN.h, Math.min(start.h + d.y, view.height - MARGIN - start.y));
  return clampWindow({ ...start, w, h }, view, chrome);
}

/** Una ventana que nunca se ha colocado: la del backend por defecto, en (0, 0). Una colocada
 *  por la interfaz nunca está ahí (`MARGIN`). */
export const unplaced = (l: Partial<Rect> | null | undefined) => !l || (!l.x && !l.y);

/** Dónde abre la ventana de un hilo nuevo: a la derecha de su primer ancla (en pantalla), y
 *  si no cabe, donde la deje `clampWindow`. */
export function defaultWindow(anchor: Box | null, view: View, size = THREAD_DEFAULT, chrome?: Chrome): Rect {
  if (!anchor) return clampWindow({ x: (view.width - size.w) / 2, y: (view.height - size.h) / 2, ...size }, view, chrome);
  const right = anchor.x + anchor.width + 24;
  const x = right + size.w <= view.width - MARGIN ? right : anchor.x - 24 - size.w;
  return clampWindow({ x, y: anchor.y, ...size }, view, chrome);
}

/** Las anclas que siguen en la escena. */
export const liveAnchors = (anchors: readonly string[], live: ReadonlySet<string>) =>
  anchors.filter((a) => live.has(a));

/** Si un hilo sale en la pizarra: con alguna de sus anclas en la escena (D166). */
export const anchored = (anchors: readonly string[], live: ReadonlySet<string>) =>
  anchors.some((a) => live.has(a));

/** Dónde va la etiqueta de cada hilo minimizado: encima de su primer ancla viva, alineada a
 *  su borde izquierdo (a la derecha taparía al vecino, que en una cadena de bloques está
 *  pegado), apiladas si comparten elemento, y nunca cortadas por los lados de la vista. Nunca
 *  tapa la interfaz fija (`chrome`) ni otra etiqueta: si encima no cabe (un ancla justo
 *  debajo de la barra de arriba), va debajo del ancla; si tampoco, no sale. Un ancla fuera de
 *  la vista (o escondida bajo una barra) no tiene etiqueta: pegada al borde no diría a qué va;
 *  el hilo sigue en la pestaña *Hilos*. `boxes`: el de cada ancla, en pantalla; `width`: lo
 *  que mide cada etiqueta. */
export function labelSpots<T extends { id: string; anchors: string[] }>(
  threads: readonly T[], boxes: ReadonlyMap<string, Box>, view: View, width: (t: T) => number,
  chrome: Chrome = defaultChrome(view)): Map<string, Pt> {
  const out = new Map<string, Pt>();
  const used = new Map<string, number>();
  const free = { x: 0, y: chrome.top, w: view.width, h: chrome.bottom - chrome.top };
  const placed: Rect[] = [];
  const fits = (r: Rect) => r.x >= 0 && r.x + r.w <= view.width && r.y >= chrome.top && r.y + r.h <= chrome.bottom
    && !chrome.zones.some((c) => overlaps(r, c)) && !placed.some((p) => overlaps(r, p));
  for (const t of threads) {
    const first = t.anchors.find((a) => boxes.has(a));
    if (!first) continue;
    const b = boxes.get(first)!;
    if (!overlaps({ x: b.x, y: b.y, w: b.width, h: b.height }, free)) continue;
    const n = used.get(first) ?? 0;
    used.set(first, n + 1);
    const w = width(t);
    const x = Math.round(Math.max(MARGIN, Math.min(b.x, view.width - MARGIN - w)));
    const above = Math.round(b.y - (n + 1) * (LABEL_H + LABEL_GAP));
    const below = Math.round(b.y + b.height + LABEL_GAP + n * (LABEL_H + LABEL_GAP));
    const y = [above, below].find((yy) => fits({ x, y: yy, w, h: LABEL_H }));
    if (y === undefined) continue;
    out.set(t.id, { x, y });
    placed.push({ x, y, w, h: LABEL_H });
  }
  return out;
}

/** El hilo discontinuo de la ventana (o la etiqueta) a cada ancla: de borde a borde, como los
 *  anclajes (R14). Nada si se tocan o se solapan. */
export function wires(from: Box, anchors: readonly Box[]): { from: Pt; to: Pt }[] {
  return anchors.map((a) => segment(from, a)).filter((s): s is { from: Pt; to: Pt } => s !== null);
}

/** `wires`, sin las que irían a un ancla escondida bajo la barra de arriba o la de abajo (o
 *  fuera de la vista por ahí): cruzarían por encima de la interfaz fija (paso 5b). La etiqueta
 *  y la ventana ya están entre las dos barras, así que una línea entre dos puntos de esa
 *  franja no las cruza. */
export function wiresInView(from: Box, anchors: readonly Box[], view: View,
                            chrome: Chrome = defaultChrome(view)): { from: Pt; to: Pt }[] {
  const inBand = (p: Pt) => p.y >= chrome.top && p.y <= chrome.bottom;
  return wires(from, anchors).filter((w) => inBand(w.from) && inBand(w.to));
}

/** De la escena a la pantalla (la pizarra), con el desplazamiento y el zoom de Excalidraw. */
export function toScreen(e: Box, st: { scrollX: number; scrollY: number; zoom: number }): Box {
  return { x: (e.x + st.scrollX) * st.zoom, y: (e.y + st.scrollY) * st.zoom,
           width: e.width * st.zoom, height: e.height * st.zoom };
}

/** Qué hilo va a pantalla completa: solo uno, el último que cambió si hay varios. */
export function fullThread<T extends { id: string; layout?: { size?: string } | null; updated?: unknown }>(
  threads: readonly T[], live: ReadonlySet<string>, anchorsOf: (t: T) => string[]): T | null {
  const full = threads.filter((t) => t.layout?.size === "full" && anchored(anchorsOf(t), live));
  return full.length ? full.reduce((a, b) => (String(b.updated ?? "") > String(a.updated ?? "") ? b : a)) : null;
}

/** Un nombre corto de un elemento para la cabecera del hilo: el texto de su post-it, el
 *  nombre de su archivo, el título de su bloque… */
export function anchorName(e: { type?: string; customData?: Record<string, unknown> } | undefined,
                           blockTitle: (type: string) => string | undefined): string {
  if (!e) return "—";
  const cd = e.customData ?? {};
  const cut = (s: string, n = 28) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);
  switch (cd.kind) {
    case "postit": return cut(String(cd.text ?? "").replace(/\s+/g, " ").trim() || t("agente.ancla.postit"));
    case "file": case "folder": return cut(String(cd.path ?? "").split(/[\\/]/).pop() || String(cd.kind));
    case "block": return cut(blockTitle(String(cd.blockType ?? "")) ?? String(cd.blockType ?? t("agente.ancla.bloque")));
    case "image": return t("agente.ancla.imagen");
    case "link": return cut(String(cd.title ?? cd.url ?? t("agente.ancla.enlace")));
    default: return e.type === "text" ? t("agente.ancla.texto") : e.type ?? t("agente.ancla.elemento");
  }
}
