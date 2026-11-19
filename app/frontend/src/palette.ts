// Lo que ofrecen la bandeja de bloques y el buscador de Ctrl+B (plan D91, D96 4B + 4C): las
// plantillas y los bloques de cada paquete, filtrados por lo que se escribe.
import type { BlockType } from "./store";

export type Template = { title: string; pack: string; description: string; blocks: unknown[]; links: unknown[] };
export type Item =
  | { kind: "template"; id: string; title: string; pack: string; description: string; count: number }
  | { kind: "block"; id: string; title: string; pack: string; description: string; requires: string[];
      input?: string; output?: string };

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

export function paletteItems(types: Record<string, BlockType>, templates: Record<string, Template>): Item[] {
  const tpl: Item[] = Object.entries(templates).map(([id, t]) => ({
    kind: "template", id, title: t.title, pack: t.pack, description: t.description, count: t.blocks.length,
  }));
  const blocks: Item[] = Object.entries(types).map(([id, t]) => ({
    kind: "block", id, title: t.title, pack: t.pack, description: t.description, requires: t.requires,
    input: Object.values(t.inputs)[0], output: Object.values(t.outputs)[0],
  }));
  return [...tpl, ...blocks];
}

/** Lo que casa con la búsqueda, sin tildes ni mayúsculas: primero lo que empieza por ella,
 * luego lo que la contiene en el título y al final en la descripción o el paquete. */
export function search(items: Item[], query: string): Item[] {
  const q = norm(query.trim());
  if (!q) return items;
  const score = (it: Item) => {
    const t = norm(it.title);
    if (t.startsWith(q)) return 0;
    if (t.includes(q)) return 1;
    if (norm(`${it.description} ${it.pack}`).includes(q)) return 2;
    return -1;
  };
  return items.map((it, i) => ({ it, s: score(it), i }))
    .filter((x) => x.s >= 0)
    .sort((a, b) => a.s - b.s || a.i - b.i)
    .map((x) => x.it);
}

/** Paquetes en el orden en que aparecen, para agrupar la bandeja. */
export function packsOf(items: Item[]): string[] {
  return [...new Set(items.map((i) => i.pack))];
}

/** Dónde nace un bloque nuevo puesto en `at` (su esquina de arriba a la izquierda): si ahí ya
 *  empieza otro (Ctrl+B dos veces sin mover el ratón, dos clics en la bandeja), un paso más
 *  abajo y a la derecha, como una cascada de ventanas, hasta un sitio sin otro igual. */
export const CASCADE = 32;
export function cascade(at: { x: number; y: number }, taken: { x: number; y: number }[],
                        step = CASCADE): { x: number; y: number } {
  const near = (p: { x: number; y: number }, q: { x: number; y: number }) =>
    Math.abs(p.x - q.x) < step / 2 && Math.abs(p.y - q.y) < step / 2;
  let p = { ...at };
  for (let i = 0; i < 100 && taken.some((q) => near(p, q)); i++) p = { x: p.x + step, y: p.y + step };
  return p;
}
