// Conexiones en la escena de Excalidraw (plan §3, D88, R18): una flecha en ángulo enganchada
// con `fixedPoint` al enchufe de salida y al de entrada, que guarda sus puertos en
// `customData = {kind: "connection", from, to}`. Lo puro (dónde está cada enchufe, el primer
// recorrido) está en ports.ts; aquí, lo que toca la escena.
//
// Las tarjetas de archivo y de carpeta (D131) son nodos como los bloques: una salida (`archivo`
// o `carpeta`) y, la carpeta, una entrada que recibe las salidas de un bloque (D109). Una flecha
// a una carpeta lleva `to: null`; con `from: null` copia todas las salidas del bloque.
import { CaptureUpdateAction, convertToExcalidrawElements, newElementWith } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import type { BlockType } from "./store";
import { BIND_GAP, elbowRoute, fixedPointFor, socketPoint, socketY, type Pt, type Rect, type Side } from "./ports";

type El = ExcalidrawElement;
type Cd = { kind?: string; blockType?: string; from?: string | null; to?: string | null };
const cd = (e: El) => (e.customData ?? {}) as Cd;

export const isConnection = (e: El) => e.type === "arrow" && cd(e).kind === "connection";
export const isBlockEl = (e: El) => e.type === "embeddable" && cd(e).kind === "block";
export const isCardEl = (e: El) => e.type === "embeddable" && (cd(e).kind === "file" || cd(e).kind === "folder");
export const isFolderEl = (e: El) => e.type === "embeddable" && cd(e).kind === "folder";
/** Bloques y tarjetas: lo que une una conexión. */
export const isNodeEl = (e: El) => isBlockEl(e) || isCardEl(e);

/** Puerto de salida de una tarjeta (`graph.SOURCE_PORT`). */
export const cardPort = (e: El) => (cd(e).kind === "folder" ? "carpeta" : "archivo");
/** Altura del enchufe de una tarjeta, desde arriba: en mitad de la etiqueta del archivo y del
 *  dibujo de la carpeta (FileCard.tsx). */
export const CARD_SOCKET_Y = { file: 20, folder: 62 } as const;

/** Índice del puerto en su lado (el orden en que se pintan los enchufes), o -1. Una salida
 *  `null` es la de una flecha a una carpeta que copia todas: sale del primer enchufe. */
export function portIndex(types: Record<string, BlockType>, block: El, side: Side, port: string | null): number {
  if (isCardEl(block)) {
    if (side === "out") return port === null || port === cardPort(block) ? 0 : -1;
    return isFolderEl(block) ? 0 : -1;
  }
  const ty = types[cd(block).blockType ?? ""];
  if (!ty) return -1;
  const names = Object.keys(side === "out" ? ty.outputs : ty.inputs);
  if (port === null) return side === "out" && names.length ? 0 : -1;
  return names.indexOf(port);
}

/** Altura del enchufe `index` del nodo, desde arriba. */
function sockY(el: El, index: number): number {
  return isCardEl(el) ? CARD_SOCKET_Y[cd(el).kind as "file" | "folder"] : socketY(index);
}

const binding = (el: El, side: Side, index: number) => ({
  elementId: el.id, focus: 0, gap: BIND_GAP,
  fixedPoint: fixedPointFor(side, index, el.width, el.height, sockY(el, index)),
});

// Lo que define el recorrido de la flecha: sus puntos relativos, su caja y sus enganches.
function geometry(src: El, oi: number, dst: El, ii: number) {
  const s = socketPoint("out", oi, src as Rect, sockY(src, oi));
  const e = socketPoint("in", ii, dst as Rect, sockY(dst, ii));
  const pts = elbowRoute(s, e, src as Rect, dst as Rect);
  const xs = pts.map((p: Pt) => p.x - s.x), ys = pts.map((p: Pt) => p.y - s.y);
  return {
    x: s.x, y: s.y,
    points: pts.map((p: Pt) => [p.x - s.x, p.y - s.y] as [number, number]),
    width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys),
    startBinding: binding(src, "out", oi), endBinding: binding(dst, "in", ii),
  };
}

/** Une la salida `outPort` de `src` con la entrada `inPort` de `dst` (`null` en una carpeta):
 *  entra en deshacer. */
export function addConnection(api: ExcalidrawImperativeAPI, types: Record<string, BlockType>,
                              src: El, outPort: string | null, dst: El, inPort: string | null) {
  const oi = portIndex(types, src, "out", outPort), ii = portIndex(types, dst, "in", inPort);
  if (oi < 0 || ii < 0) return;
  const g = geometry(src, oi, dst, ii);
  const [base] = convertToExcalidrawElements([{ type: "arrow", x: g.x, y: g.y } as never]);
  const arrow = {
    ...base, ...g, elbowed: true, roundness: null, fixedSegments: null,
    startIsSpecial: null, endIsSpecial: null, startArrowhead: null, endArrowhead: "arrow",
    customData: { kind: "connection", from: outPort, to: inPort },
  } as unknown as El;
  const link = (el: El) => newElementWith(el, {
    boundElements: [...(el.boundElements ?? []), { id: arrow.id, type: "arrow" }],
  } as never);
  const elements = api.getSceneElementsIncludingDeleted().map((e) =>
    e.id === src.id ? link(e) : e.id === dst.id ? link(e) : e);
  api.updateScene({ elements: [...elements, arrow], captureUpdate: CaptureUpdateAction.IMMEDIATELY });
}

const near = (a: number, b: number) => Math.abs(a - b) < 0.5;

/** Las conexiones que no acaban en su enchufe vuelven a él: al crecer un bloque (el enchufe
 * está a una distancia fija de arriba, la fracción cambia) y las flechas del spike, que no eran
 * en ángulo. Mientras Excalidraw arrastra un bloque, él mismo las mantiene en su sitio. No entra
 * en deshacer: es una consecuencia de otro cambio. Devuelve si ha tocado algo. */
export function syncConnections(api: ExcalidrawImperativeAPI, types: Record<string, BlockType>): boolean {
  const all = api.getSceneElementsIncludingDeleted();
  const byId = new Map(all.map((e) => [e.id, e]));
  const fixed = new Map<string, El>();
  for (const a of all) {
    if (a.isDeleted || !isConnection(a)) continue;
    const arrow = a as El & { startBinding?: { elementId: string } | null; endBinding?: { elementId: string } | null;
      points: readonly (readonly [number, number])[]; elbowed?: boolean };
    const src = arrow.startBinding && byId.get(arrow.startBinding.elementId);
    const dst = arrow.endBinding && byId.get(arrow.endBinding.elementId);
    const { from, to } = cd(a);
    if (!src || !dst || src.isDeleted || dst.isDeleted || !isNodeEl(src) || !isNodeEl(dst)) continue;
    // A una carpeta, sin entrada; de un bloque, siempre con su salida salvo a una carpeta.
    if ((to ?? null) === null ? !isFolderEl(dst) : isFolderEl(dst)) continue;
    if ((from ?? null) === null && !isFolderEl(dst) && !isCardEl(src)) continue;
    const oi = portIndex(types, src, "out", from ?? null), ii = portIndex(types, dst, "in", to ?? null);
    if (oi < 0 || ii < 0) continue;
    const s = socketPoint("out", oi, src as Rect, sockY(src, oi)), e = socketPoint("in", ii, dst as Rect, sockY(dst, ii));
    const first = arrow.points[0], last = arrow.points[arrow.points.length - 1];
    const ok = arrow.elbowed
      && near(arrow.x + first[0], s.x) && near(arrow.y + first[1], s.y)
      && near(arrow.x + last[0], e.x) && near(arrow.y + last[1], e.y);
    if (ok) continue;
    fixed.set(a.id, newElementWith(a, {
      ...geometry(src, oi, dst, ii), elbowed: true, roundness: null, fixedSegments: null,
    } as never));
  }
  if (!fixed.size) return false;
  api.updateScene({ elements: all.map((e) => fixed.get(e.id) ?? e), captureUpdate: CaptureUpdateAction.NEVER });
  return true;
}
