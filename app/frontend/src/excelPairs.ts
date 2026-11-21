// Lo puro de la flecha de enlace de una tarjeta de Excel a un bloque (docs/PLAN_EXCEL.md §3.6,
// R5). La flecha **es la vista de `links`**: una por pareja tarjeta-bloque con enlaces, que no
// se guarda en la escena (no puede desincronizarse de los enlaces ni entra en el orden de
// ejecución: la dependencia ya la llevan los enlaces, §3.2). Su menú ofrece, por parámetro, los
// nombres de la tarjeta que casan (las reglas de *Tomar de Excel*, `excel.ts`). Lo que toca la
// escena y el DOM, en ExcelArrows.tsx.
import { t } from "./i18n";
import { offers, paramKind, type ExcelName, type ParamLink } from "./excel";
import type { ParamSpec } from "./store";

/** Una flecha: la tarjeta, el bloque y sus parámetros enlazados (ordenados). */
export type LinkPair = { card: string; block: string; params: string[] };

/** Las flechas de enlace de la pizarra: una por pareja tarjeta-bloque con algún enlace, en un
 *  orden fijo (por bloque y por tarjeta). */
export function linkPairs(blocks: Record<string, { links?: Record<string, ParamLink> | null }>): LinkPair[] {
  const out = new Map<string, LinkPair>();
  for (const [block, st] of Object.entries(blocks)) {
    for (const [param, l] of Object.entries(st.links ?? {})) {
      const key = `${block}\u0000${l.card}`;
      const pair = out.get(key) ?? { card: l.card, block, params: [] };
      pair.params.push(param);
      out.set(key, pair);
    }
  }
  return [...out.values()]
    .map((p) => ({ ...p, params: [...p.params].sort() }))
    .sort((a, b) => a.block.localeCompare(b.block) || a.card.localeCompare(b.card));
}

/** La etiqueta de la flecha: cuántos enlaces lleva. */
export const pairLabel = (n: number) => t(n === 1 ? "bloques.excel.flecha.uno" : "bloques.excel.flecha.varios", { n });

/** Una fila del menú de enlace: un parámetro con los nombres de la tarjeta que le valen.
 *  `current`: el nombre con que ya está enlazado a esta tarjeta; `other`: la tarjeta a la que
 *  lo está, si es otra (elegir aquí lo pasa a esta). */
export type LinkRow = { param: string; label: string; options: ExcelName[]; current: string | null; other: string | null };

/** Las filas del menú de enlace de la tarjeta `card` (con sus `names`) a un bloque con esos
 *  `params` y `links`: solo los parámetros que se pueden tomar de un Excel y tienen algún
 *  nombre que casa (o ya están enlazados a esta tarjeta). Nunca se ofrece lo de X3. */
export function linkRows(params: Record<string, ParamSpec>, links: Record<string, ParamLink> | null | undefined,
                         card: string, names: ExcelName[]): LinkRow[] {
  const rows: LinkRow[] = [];
  for (const [param, spec] of Object.entries(params)) {
    const kind = paramKind(spec);
    if (!kind) continue;
    const options = names.filter((n) => offers(n, kind));
    const l = links?.[param];
    const current = l && l.card === card ? l.name : null;
    if (!options.length && !current) continue;
    rows.push({ param, label: spec.label || param, options, current, other: l && l.card !== card ? l.card : null });
  }
  return rows;
}

/** Lo que *Enlazar* manda (`PUT …/links/<tarjeta>`): `{parámetro: nombre}` de lo elegido que se
 *  ofrece. Lo de esta tarjeta que no va aquí, el backend lo desenlaza. */
export function pairBody(rows: LinkRow[], chosen: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const n = chosen[r.param];
    if (n && r.options.some((o) => o.nombre === n)) out[r.param] = n;
  }
  return out;
}

/** Qué hace soltar en el cuerpo de un bloque la salida de una tarjeta de archivo: con una
 *  entrada libre que la acepta, la conexión de siempre (o el menú de entradas si hay varias);
 *  sin ninguna, de un Excel, el menú de enlace; de otro archivo, nada (se dice por qué). */
export function dropOnBlock(isExcel: boolean, accepting: number): "connect" | "inputs" | "link" | "none" {
  if (accepting === 1) return "connect";
  if (accepting > 1) return "inputs";
  return isExcel ? "link" : "none";
}
