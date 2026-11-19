// Propuestas del agente (plan §3, D75, diseño 2A): qué llega del backend y cómo se enseña el
// cambio dentro del elemento (lo quitado tachado, lo nuevo resaltado).
import type { FileChange } from "./office";
import { fmtNumber, t } from "./i18n";

export type ProposalChange = {
  text?: string;
  postitKind?: string;
  params?: Record<string, unknown>;
  delete?: boolean;
  file?: FileChange;            // propuesta de archivo (`editar_archivo`, D176): la copia y su diff
};

export type Proposal = {
  id: string;
  author: string;
  target: string;
  change: ProposalChange;
  reason: string;
  sources: { kind: string; ref?: string; formula?: string; url?: string }[];
  estimate: boolean;
  // lo que hay ahora en esos campos: es el «antes» que se enseña (en una de archivo, la ruta)
  current: Omit<ProposalChange, "file"> & { file?: string };
  stale: boolean;               // el elemento cambió desde la propuesta (desfasada)
};

export type Seg = { kind: "same" | "del" | "ins"; text: string };

// Diff por palabras (con sus espacios) entre el texto de ahora y el propuesto. Junta los
// tramos seguidos del mismo tipo. Si los textos son muy largos, todo se quita y todo se pone.
export function wordDiff(before: string, after: string): Seg[] {
  const a = before.split(/(\s+)/).filter(Boolean);
  const b = after.split(/(\s+)/).filter(Boolean);
  const out: Seg[] = [];
  const push = (kind: Seg["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  if (a.length * b.length > 250_000) {
    if (before) push("del", before);
    if (after) push("ins", after);
    return out;
  }
  // Tabla de la subsecuencia común más larga, desde el final.
  const L = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    }
  }
  const ops: Seg[] = [];
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { ops.push({ kind: "same", text: a[i] }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) ops.push({ kind: "del", text: a[i++] });
    else ops.push({ kind: "ins", text: b[j++] });
  }
  while (i < a.length) ops.push({ kind: "del", text: a[i++] });
  while (j < b.length) ops.push({ kind: "ins", text: b[j++] });
  // Un espacio igual entre dos cambios es parte del cambio: cada tramo cambiado sale como un
  // bloque quitado y uno nuevo, no en trocitos palabra a palabra.
  for (let k = 0; k < ops.length; ) {
    if (ops[k].kind === "same") { push("same", ops[k].text); k++; continue; }
    let del = "", ins = "", end = k;
    for (let m = k; m < ops.length; m++) {
      const o = ops[m];
      const gap = o.kind === "same" && !o.text.trim() && m + 1 < ops.length && ops[m + 1].kind !== "same";
      if (o.kind === "same" && !gap) break;
      if (o.kind !== "ins") del += o.text;
      if (o.kind !== "del") ins += o.text;
      end = m + 1;
    }
    if (del) push("del", del);
    if (ins) push("ins", ins);
    k = end;
  }
  return out;
}

// La propuesta pendiente de un elemento (como mucho hay una, la regla es del backend).
export function proposalFor(proposals: readonly Proposal[], id: string): Proposal | undefined {
  return proposals.find((p) => p.target === id);
}

// Para la píldora: la siguiente o la anterior en la lista, dando la vuelta.
export function cycle(n: number, i: number, step: 1 | -1): number {
  return n ? (((i + step) % n) + n) % n : 0;
}

// ------------------------------------------------- parámetros lista de nodos (D177)

// Un parámetro cuyo valor es una lista de objetos con `id` (el `arbol` del *Diseño del
// terminal*, o cualquier otro) se enseña por elemento, nunca como un bloque de JSON: los
// añadidos, los quitados y los modificados con los campos que cambian. Se casan por `id`, así
// que cambiar el orden no es cambiar nada.

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isPrim = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);
const itemId = (v: unknown) => (isObj(v) && (typeof v.id === "string" || typeof v.id === "number") ? String(v.id) : null);

/** Lista (no vacía) de objetos con `id`, todos distintos. */
export function isIdList(v: unknown): v is Obj[] {
  if (!Array.isArray(v) || !v.length) return false;
  const ids = v.map(itemId);
  return ids.every((i) => i !== null) && new Set(ids).size === ids.length;
}

/** Igualdad por contenido (el orden de las claves de un objeto no cuenta). */
export function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => same(x, b[i]));
  if (isObj(a) && isObj(b)) {
    const ka = Object.keys(a).filter((k) => a[k] !== undefined);
    const kb = Object.keys(b).filter((k) => b[k] !== undefined);
    return ka.length === kb.length && ka.every((k) => same(a[k], b[k]));
  }
  return false;
}

/** Cómo cambia un campo: un valor por otro; dentro de un objeto (`params`, `colocar`…), qué
 *  claves; en una lista de valores sueltos (`componentes`), qué entra y qué sale. */
export type FieldDiff =
  | { field: string; kind: "value"; before: unknown; after: unknown }
  | { field: string; kind: "keys"; keys: { key: string; before: unknown; after: unknown }[] }
  | { field: string; kind: "items"; added: unknown[]; removed: unknown[] };

export type ItemDiff =
  | { id: string; kind: "added"; item: Obj }
  | { id: string; kind: "removed"; item: Obj }
  | { id: string; kind: "changed"; fields: FieldDiff[] };

export type ListDiff = { items: ItemDiff[]; unchanged: number };

function fieldDiff(field: string, a: unknown, b: unknown): FieldDiff {
  if ((isObj(a) || a === undefined) && (isObj(b) || b === undefined)) {
    const x = (a ?? {}) as Obj, y = (b ?? {}) as Obj;
    const keys = [...new Set([...Object.keys(x), ...Object.keys(y)])].filter((k) => !same(x[k], y[k]));
    return { field, kind: "keys", keys: keys.map((key) => ({ key, before: x[key], after: y[key] })) };
  }
  const list = (v: unknown) => Array.isArray(v) && v.every(isPrim);
  if ((list(a) || a === undefined) && (list(b) || b === undefined)) {
    const x = (a ?? []) as unknown[], y = (b ?? []) as unknown[];
    return { field, kind: "items", added: y.filter((v) => !x.some((w) => same(v, w))),
             removed: x.filter((v) => !y.some((w) => same(v, w))) };
  }
  return { field, kind: "value", before: a, after: b };
}

/** El diff por `id` de dos listas de objetos, o null si el valor propuesto no es una lista de
 *  objetos con `id` (entonces se enseña como hasta ahora). El de ahora puede faltar o estar
 *  vacío (todo es añadido); el propuesto vacío, con uno de ahora que sí lo es, lo quita todo. */
export function listDiff(before: unknown, after: unknown): ListDiff | null {
  const emptyOrNone = (v: unknown) => v == null || (Array.isArray(v) && !v.length);
  if (!(isIdList(after) && (isIdList(before) || emptyOrNone(before)))
      && !(isIdList(before) && emptyOrNone(after))) return null;
  const a = isIdList(before) ? before : [], b = isIdList(after) ? after : [];
  const old = new Map(a.map((x) => [itemId(x)!, x]));
  const now = new Set(b.map((x) => itemId(x)!));
  const items: ItemDiff[] = [];
  let unchanged = 0;
  for (const y of b) {
    const id = itemId(y)!;
    const x = old.get(id);
    if (!x) { items.push({ id, kind: "added", item: y }); continue; }
    const fields = [...new Set([...Object.keys(x), ...Object.keys(y)])]
      .filter((k) => k !== "id" && !same(x[k], y[k])).map((k) => fieldDiff(k, x[k], y[k]));
    if (fields.length) items.push({ id, kind: "changed", fields });
    else unchanged++;
  }
  for (const x of a) if (!now.has(itemId(x)!)) items.push({ id: itemId(x)!, kind: "removed", item: x });
  return { items, unchanged };
}

/** Un valor en una línea, para leerlo (nunca JSON): un objeto como `clave: valor, …`, una
 *  lista separada por comas, lo que falta como «—». */
export function brief(v: unknown, depth = 0): string {
  if (v === undefined || v === null || v === "") return "—";
  if (typeof v === "boolean") return v ? t("agente.si") : t("agente.no");
  if (typeof v === "number") {
    return fmtNumber(v, { sig: 6, max: 6, group: false });        // la coma decimal, en español
  }
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.length ? (depth > 1 ? "…" : v.map((x) => brief(x, depth + 1)).join(", ")) : "—";
  if (isObj(v)) {
    const e = Object.entries(v).filter(([, x]) => x !== undefined);
    if (!e.length) return "—";
    if (depth > 1) return "…";
    const inner = e.map(([k, x]) => `${k}: ${brief(x, depth + 1)}`).join(", ");
    return depth ? `(${inner})` : inner;          // uno dentro de otro, entre paréntesis
  }
  return String(v);
}

export type TabFit = { above: boolean; maxHeight: number | null; top?: number };

/** Dónde va el recuadro de una propuesta para que quepa en la pizarra (prueba de punta a punta
 * de FF 4.6): debajo de su elemento si cabe, si no encima, y si no cabe en ninguno, en el lado
 * con más sitio con `maxHeight` (en px de la tarjeta, que puede ir a escala) y el contenido
 * desplazándose dentro; si tampoco hay sitio para el mínimo, encima de la parte de abajo del
 * elemento (`top`). `top`, `bottom`, `natural` y `area` (lo libre entre la barra de arriba y la
 * de abajo) en px de la pantalla. */
export function tabFit(top: number, bottom: number, natural: number, area: { top: number; bottom: number },
                       scale = 1, gap = 12, min = 160): TabFit {
  const below = area.bottom - (bottom + gap);
  const above = top - gap - area.top;
  if (natural <= below) return { above: false, maxHeight: null };
  if (natural <= above) return { above: true, maxHeight: null };
  const up = above > below;
  const room = Math.max(above, below);
  if (room >= min) return { above: up, maxHeight: Math.round(room / (scale || 1)) };
  // Ni encima ni debajo: el mínimo, apoyado en el borde de abajo de la pizarra y tapando la
  // parte de abajo del elemento (`top`, en px de la pantalla).
  return { above: false, maxHeight: Math.round(min / (scale || 1)), top: area.bottom - min };
}
