// Lo puro de la *Librería* (docs/PLAN_V020.md §5, V14-V16; D33): leer y escribir cantidades,
// qué stock ha cambiado, el mapeo de columnas al importar y qué filas del resumen se escriben.
// Las llamadas al backend, en `libraryApi.ts` (importa `auth.ts`, que vitest no puede cargar).
import { editNumber, fmtNumber, t } from "./i18n";

/** Una entrada de stock: `cantidad` null es «desconocida» (D33), nunca 0. */
export type StockEntry = { cantidad: number | null; ubicacion: string; fecha: string; nota: string };

/** Una fila de la librería, como la da `GET /api/library` (backend: pizarra/library.py). */
export type LibraryItem = {
  key: string;
  type: string;
  kind: string;
  manufacturer: string;
  status: "unverified" | "verified" | string;
  verified_by: string;
  verified_on: string;
  fields: number;
  origin: "workspace" | "pack" | "stock";
  pack: string | null;
  overrides: string | null;
  editable: boolean;
  error: string | null;
  stock: StockEntry | null;
};

export type Ficha = LibraryItem & { toml: string; data: Record<string, unknown> | null };

// ----------------------------------------------------------------- cantidades
/** Lo escrito en el campo de la cantidad: vacío es desconocida (null), nunca 0; un número ≥ 0
 *  con coma o punto decimal. `ok: false` si no es una cantidad. */
export function parseQuantity(text: string): { ok: true; value: number | null } | { ok: false } {
  const raw = text.trim().replace(/\s/g, "");
  if (!raw) return { ok: true, value: null };
  if (!/^\d*([.,]\d*)?$/.test(raw) || raw === "." || raw === ",") return { ok: false };
  const n = Number(raw.replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? { ok: true, value: n } : { ok: false };
}

/** La cantidad para leer: «—» si es desconocida (distinto de «0»). */
export const showQuantity = (q: number | null | undefined): string =>
  q === null || q === undefined ? "—" : fmtNumber(q);

/** La cantidad en el campo para editarla: vacío si es desconocida. */
export const editQuantity = (q: number | null | undefined): string =>
  q === null || q === undefined ? "" : editNumber(q);

// ---------------------------------------------------------------------- stock
/** Lo que el usuario tiene escrito en las celdas de stock de una clave (la cantidad, como
 *  texto), o null para quitarla del stock. */
export type StockDraft = { cantidad: string; ubicacion: string; fecha: string; nota: string } | null;

export const STOCK_TEXT = ["ubicacion", "fecha", "nota"] as const;

/** El borrador de una clave a partir de lo guardado. */
export function draftOf(entry: StockEntry | null | undefined): Exclude<StockDraft, null> {
  return {
    cantidad: editQuantity(entry?.cantidad),
    ubicacion: entry?.ubicacion ?? "", fecha: entry?.fecha ?? "", nota: entry?.nota ?? "",
  };
}

const sameEntry = (a: StockEntry, b: StockEntry) =>
  a.cantidad === b.cantidad && STOCK_TEXT.every((c) => a[c] === b[c]);

/** Lo que hay que mandar a `PUT /api/library/stock`: solo las claves que han cambiado de verdad
 *  respecto a lo guardado (una celda tocada y dejada como estaba no se manda), y los errores de
 *  cantidad por clave (con alguno, no se manda nada). Una clave sin stock cuyo borrador está
 *  vacío no crea una entrada vacía, salvo las de `fresh` (las de *Añadir clave*: apuntarla ya
 *  es el cambio, con la cantidad desconocida); quitar una que no tenía stock tampoco se manda.
 *  Una clave que no está en `saved` es una sin stock. */
export function stockChanges(saved: Record<string, StockEntry | null | undefined>,
                             drafts: Record<string, StockDraft>,
                             fresh: ReadonlySet<string> = new Set()):
    { changes: Record<string, StockEntry | null>; errors: Record<string, string> } {
  const changes: Record<string, StockEntry | null> = {};
  const errors: Record<string, string> = {};
  for (const [key, draft] of Object.entries(drafts)) {
    const old = saved[key] ?? null;
    if (draft === null) {
      if (old !== null) changes[key] = null;
      continue;
    }
    const q = parseQuantity(draft.cantidad);
    if (!q.ok) {
      errors[key] = t("libreria.cantidad_no_valida", { valor: draft.cantidad.trim() });
      continue;
    }
    const entry: StockEntry = {
      cantidad: q.value, ubicacion: draft.ubicacion.trim(), fecha: draft.fecha.trim(), nota: draft.nota.trim(),
    };
    if (old === null) {
      if (!fresh.has(key) && entry.cantidad === null && STOCK_TEXT.every((c) => !entry[c])) continue;
    } else if (sameEntry(old, entry)) continue;
    changes[key] = entry;
  }
  return { changes, errors };
}

// ------------------------------------------------------------ añadir una clave
/** La regla de `check_ficha_key` (backend: pizarra/storage/names.py), que la vuelve a aplicar
 *  (422): letras, cifras, `.`, `_`, `+` y `-`, empezando por letra o cifra, sin acabar en punto,
 *  hasta 100 caracteres y sin un nombre reservado de Windows antes del primer punto. */
export const FICHA_KEY_MAX = 100;
const WINDOWS_RESERVED = new Set(["CON", "PRN", "AUX", "NUL",
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].flatMap((i) => [`COM${i}`, `LPT${i}`])]);
export const validFichaKey = (key: string): boolean =>
  key.length > 0 && key.length <= FICHA_KEY_MAX && /^[A-Za-z0-9][A-Za-z0-9._+-]*$/.test(key)
  && !key.endsWith(".") && !WINDOWS_RESERVED.has(key.split(".")[0].toUpperCase());

/** Una fila *Añadir clave* (PLAN_LIBRERIA L2): la clave que se escribe y su stock. `id` la
 *  distingue mientras la clave cambia. */
export type NewStockRow = { id: number; key: string } & Exclude<StockDraft, null>;

/** Los borradores de las filas *Añadir clave*, por clave (sin espacios a los lados), y el error
 *  de cada fila que no se puede mandar, por `id`: sin clave, con una que no vale, o repetida
 *  (ya en la tabla o en otra fila nueva, sin mayúsculas: en Windows serían el mismo fichero).
 *  De una clave repetida no va ninguna de las filas. Una fila sin nada escrito no cuenta. */
export function newRowDrafts(rows: NewStockRow[], taken: Iterable<string>):
    { drafts: Record<string, Exclude<StockDraft, null>>; errors: Record<number, string> } {
  const fold = (k: string) => k.toLowerCase();
  const inTable = new Set(Array.from(taken, fold));
  const count = new Map<string, number>();
  for (const r of rows) {
    const k = fold(r.key.trim());
    if (k) count.set(k, (count.get(k) ?? 0) + 1);
  }
  const drafts: Record<string, Exclude<StockDraft, null>> = {};
  const errors: Record<number, string> = {};
  for (const r of rows) {
    const key = r.key.trim();
    const { cantidad, ubicacion, fecha, nota } = r;
    if (!key) {
      if ([cantidad, ubicacion, fecha, nota].some((v) => v.trim())) errors[r.id] = t("libreria.nueva.sin_clave");
    } else if (!validFichaKey(key)) {
      errors[r.id] = t("libreria.nueva.no_valida", { clave: key, max: FICHA_KEY_MAX });
    } else if (inTable.has(fold(key))) {
      errors[r.id] = t("libreria.nueva.ya_en_tabla", { clave: key });
    } else if ((count.get(fold(key)) ?? 0) > 1) {
      errors[r.id] = t("libreria.nueva.repetida", { clave: key });
    } else {
      drafts[key] = { cantidad, ubicacion, fecha, nota };
    }
  }
  return { drafts, errors };
}

// --------------------------------------------------------------------- la tabla
/** Las filas que tienen el texto en la clave, el fabricante, la clase o el tipo (todas las
 *  palabras, sin mayúsculas). */
export function filterItems(items: LibraryItem[], text: string): LibraryItem[] {
  const words = text.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return items;
  return items.filter((it) => {
    const hay = [it.key, it.manufacturer, it.kind, it.type, it.pack ?? ""].join(" ").toLocaleLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** De dónde sale la fila, para la columna *Origen*. */
export function originText(it: LibraryItem): string {
  if (it.origin === "pack") return t("libreria.origen.paquete", { paquete: it.pack ?? "?" });
  if (it.origin === "stock") return t("libreria.origen.solo_stock");
  return it.overrides
    ? t("libreria.origen.tapa", { paquete: it.overrides })
    : t("libreria.origen.workspace");
}

// --------------------------------------------------------------------- importar
/** A qué campo puede ir una columna (backend: pizarra/library_import.py). */
export const META_TARGETS = ["manufacturer", "kind"] as const;
export const STOCK_TARGETS = ["cantidad", "ubicacion", "fecha", "nota"] as const;
export const VALUE_PREFIX = "values.";

/** Los destinos que se ofrecen al mapear, con los campos `values.<f>` del tipo elegido. Sin
 *  tipo de ficha, solo la clave y el stock: los de la ficha necesitan el tipo. */
export function mappingTargets(fields: string[], withType: boolean): string[] {
  const out: string[] = ["key", ...STOCK_TARGETS];
  if (withType) out.push(...META_TARGETS, ...fields.map((f) => VALUE_PREFIX + f));
  return out;
}

/** Un campo de `[values]` de un tipo, como lo da `GET /api/library/fields` (PLAN_LIBRERIA L4):
 *  los que declara el esquema de un paquete (`declarado`, con su `paquete`) primero y en su
 *  orden; después los que usan las fichas y nadie declara. `descripcion` y `unidad` son texto
 *  del paquete: se pintan con su catálogo (`tp`, L5). */
export type FieldInfo = {
  nombre: string;
  unidad: string;
  descripcion: string;
  obligatorio: boolean;
  min: number | null;
  max: number | null;
  declarado: boolean;
  paquete: string | null;
};

/** La unidad para pintar junto a un valor: nada si el campo es texto ("") o no tiene dimensión
 *  ("-"). */
export const shownUnit = (unit: string | null | undefined): string => {
  const u = (unit ?? "").trim();
  return u === "-" ? "" : u;
};

/** Los obligatorios que declara el paquete y ninguna columna llena (`choices` ya con los campos
 *  nuevos resueltos, `values.<campo>`), en el orden del esquema. Es un aviso: una ficha nueva se
 *  crea igual, sin ellos. */
export function missingRequired(fields: FieldInfo[], choices: Record<string, string>): FieldInfo[] {
  const used = new Set(Object.values(choices).filter(Boolean));
  return fields.filter((f) => f.declarado && f.obligatorio && !used.has(VALUE_PREFIX + f.nombre));
}

/** ¿El destino escribe en la ficha (y necesita tipo)? */
export const isFichaTarget = (target: string) =>
  (META_TARGETS as readonly string[]).includes(target) || target.startsWith(VALUE_PREFIX);

/** El nombre de un campo nuevo de `[values]` vale si es como los de las fichas (letras sin
 *  tilde, cifras y `_`, sin empezar por cifra). */
export const validFieldName = (name: string) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);

/** En el selector de una columna, «campo nuevo de la ficha»: su nombre va aparte. */
export const NEW_FIELD = "__new__";

/** Lo elegido en cada columna con los campos nuevos ya como `values.<nombre>`; un nombre que no
 *  vale es un error (no se manda a medias). */
export function resolveChoices(choices: Record<string, string>, newFields: Record<string, string>):
    { ok: true; choices: Record<string, string> } | { ok: false; error: string } {
  const out: Record<string, string> = {};
  for (const [column, target] of Object.entries(choices)) {
    if (target !== NEW_FIELD) {
      out[column] = target;
      continue;
    }
    const name = (newFields[column] ?? "").trim();
    if (!validFieldName(name)) return { ok: false, error: t("libreria.importar.campo_no_valido", { columna: column, campo: name }) };
    out[column] = VALUE_PREFIX + name;
  }
  return { ok: true, choices: out };
}

/** El importador abierto ya rellenado (PLAN_ONBOARDING N7): el Excel, la hoja, el tipo y el
 *  mapeo que propuso el agente; `proposal`, la propuesta que se guarda al importar. */
export type ImportInitial = {
  path: string; sheet: string; type: string; mapping: Record<string, string>; proposal?: string;
};

/** Lo elegido en cada columna a partir de un mapeo ya hecho: su destino si se ofrece, un campo
 *  de la ficha que el tipo aún no tiene como campo nuevo con su nombre, y nada en las demás.
 *  Lo del mapeo que no es una columna de esta hoja no se pinta. */
export function initialChoices(mapping: Record<string, string>, columns: string[], targets: string[]):
    { choices: Record<string, string>; newFields: Record<string, string> } {
  const choices: Record<string, string> = {};
  const newFields: Record<string, string> = {};
  for (const col of columns) {
    const target = mapping[col] ?? "";
    if (!target || targets.includes(target)) choices[col] = target;
    else if (target.startsWith(VALUE_PREFIX)) {
      choices[col] = NEW_FIELD;
      newFields[col] = target.slice(VALUE_PREFIX.length);
    } else choices[col] = "";
  }
  return { choices, newFields };
}

export type MappingResult =
  | { ok: true; mapping: Record<string, string>; needsType: boolean }
  | { ok: false; error: string };

/** El `mapping` para `POST /api/library/import/plan` a partir de lo elegido en cada columna
 *  (vacío = no se importa). Sin una columna a `key` no se puede pedir el resumen; un destino en
 *  dos columnas, tampoco; con campos de ficha, hace falta el tipo. */
export function buildMapping(choices: Record<string, string>, type: string): MappingResult {
  const mapping: Record<string, string> = {};
  const used = new Map<string, string>();
  for (const [column, target] of Object.entries(choices)) {
    if (!target) continue;
    const other = used.get(target);
    if (other !== undefined) {
      return { ok: false, error: t("libreria.importar.destino_repetido", { campo: target, a: other, b: column }) };
    }
    used.set(target, column);
    mapping[column] = target;
  }
  if (!used.has("key")) return { ok: false, error: t("libreria.importar.sin_clave") };
  const needsType = Object.values(mapping).some(isFichaTarget);
  if (needsType && !type.trim()) return { ok: false, error: t("libreria.importar.sin_tipo") };
  return { ok: true, mapping, needsType };
}

/** Un primer mapeo: cada columna cuyo nombre es el de un destino (sin mayúsculas ni tildes;
 *  `clave`/`key`, `cantidad`/`qty`…) va a él; las demás, a ninguno. */
export function guessMapping(columns: string[], targets: string[]): Record<string, string> {
  const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const alias: Record<string, string> = {
    key: "key", clave: "key", ref: "key", referencia: "key", codigo: "key", sku: "key",
    cantidad: "cantidad", qty: "cantidad", quantity: "cantidad", unidades: "cantidad", uds: "cantidad", stock: "cantidad",
    ubicacion: "ubicacion", location: "ubicacion", sitio: "ubicacion", lugar: "ubicacion", fecha: "fecha", date: "fecha",
    nota: "nota", note: "nota", notas: "nota", notes: "nota", comentario: "nota", fabricante: "manufacturer", manufacturer: "manufacturer", marca: "manufacturer",
    kind: "kind", clase: "kind",
  };
  const out: Record<string, string> = {};
  const taken = new Set<string>();
  for (const col of columns) {
    const n = norm(col);
    const target = alias[n] ?? targets.find((x) => x.startsWith(VALUE_PREFIX) && norm(x.slice(VALUE_PREFIX.length)) === n);
    if (target && targets.includes(target) && !taken.has(target)) {
      out[col] = target;
      taken.add(target);
    } else out[col] = "";
  }
  return out;
}

export type PlanRow = {
  row: number;
  key: string | null;
  state: "create" | "update" | "unchanged" | "invalid";
  ficha: "create" | "update" | null;
  stock: "create" | "update" | null;
  cantidad?: number | null;
  reason?: string;
  warnings: string[];
};

export type ImportPlan = {
  token: string;
  file: string;
  sheet: string;
  type: string;
  mapping: Record<string, string>;
  rows: PlanRow[];
  counts: { create: number; update: number; unchanged: number; invalid: number };
  writes: { fichas: number; stock: number };
};

/** Las filas que escribe *Importar*: las que crean o actualizan algo. Las que no valen o no
 *  cambian nada se saltan (una fila mala nunca tumba las buenas). */
export const writtenRows = (plan: ImportPlan): PlanRow[] =>
  plan.rows.filter((r) => r.state === "create" || r.state === "update");

/** ¿Se puede pulsar *Importar*? Solo si el resumen escribe algo. */
export const canApply = (plan: ImportPlan | null): boolean =>
  !!plan && plan.writes.fichas + plan.writes.stock > 0 && writtenRows(plan).length > 0;
