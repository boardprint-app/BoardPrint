// Salidas de un bloque en su tarjeta (plan §3, D96 3B): cómo se reparten en filas sueltas,
// grupos plegables, tablas (listas de filas) y archivos, y los candados del dimensionado.
import { t } from "./i18n";
import { tp } from "./packI18n";
import type { Value } from "./store";

export type Field = Value & { key: string; port: string };
export type OutputView = {
  plain: Field[];                          // valores sueltos, arriba
  groups: { name: string; fields: Field[] }[];   // con `group`, plegables
  tables: Field[];                         // `value` es una lista de filas
  files: Field[];                          // citan un archivo (`file`)
  images: Field[];                         // de esos, las imágenes: miniatura arriba (D114)
  lockable: boolean;                       // algún valor admite candado
  // Los de un control genérico (`chart`, `view2d`, P52): los pinta ese control, no Resultados.
  controls: Record<string, Field[]>;
};

export function outputView(outputs: Record<string, Record<string, Value>> | null): OutputView {
  const view: OutputView = { plain: [], groups: [], tables: [], files: [], images: [], lockable: false, controls: {} };
  const byGroup = new Map<string, Field[]>();
  // Un valor que va en varias salidas (el Dimensionado da `brazo` entero y salidas parciales con
  // parte de lo mismo, D99) se enseña una sola vez: la primera.
  const seen = new Set<string>();
  for (const [port, fields] of Object.entries(outputs ?? {})) {
    for (const [key, v] of Object.entries(fields)) {
      if (seen.has(key) || v.hidden) continue;   // lo enseña la tarjeta (T25)
      seen.add(key);
      const f: Field = { ...v, key, port };
      if (typeof v.control === "string" && v.control) {
        (view.controls[v.control] ??= []).push(f);
        continue;
      }
      if (v.lockable) view.lockable = true;
      if (typeof v.file === "string") {
        view.files.push(f);
        if (v.image) view.images.push(f);
      }
      else if (Array.isArray(v.value)) view.tables.push(f);
      else if (v.group) {
        if (!byGroup.has(v.group)) byGroup.set(v.group, []);
        byGroup.get(v.group)!.push(f);
      } else view.plain.push(f);
    }
  }
  view.groups = [...byGroup].map(([name, fields]) => ({ name, fields }));
  return view;
}

export type Locks = Record<string, number>;

/** Pone o quita el candado de un valor: con candado se fija al valor que tiene ahora. */
export function toggleLock(locks: Locks | undefined, key: string, value: unknown): Locks {
  const next = { ...(locks ?? {}) };
  if (key in next) delete next[key];
  else if (typeof value === "number" && Number.isFinite(value)) next[key] = value;
  return next;
}

/** Cambia el valor de un candado ya puesto; un valor que no es un número no se acepta. */
export function setLock(locks: Locks | undefined, key: string, raw: string): Locks | null {
  const x = Number(raw.replace(",", "."));
  if (raw.trim() === "" || !Number.isFinite(x)) return null;
  return { ...(locks ?? {}), [key]: x };
}

/** Columnas de una tabla: las claves de sus filas, en el orden en que aparecen, salvo «cumple»,
 *  que va la primera: en una tarjeta estrecha el veredicto se ve aunque lo de la derecha no
 *  quepa (e2e de FF 5.1). */
export function tableColumns(rows: unknown[]): string[] {
  const cols: string[] = [];
  for (const r of rows) {
    if (r && typeof r === "object") for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);
  }
  return cols.includes("cumple") ? ["cumple", ...cols.filter((c) => c !== "cumple")] : cols;
}

/** ¿Va la celda como un número (a la derecha y sin partir línea)? Un número, o un texto que solo
 *  es una cifra con su comparación o su unidad corta («≤ 1,00», «≥ 2», «12 %»): partido en dos
 *  líneas («≤» arriba, «1,00» abajo) no se lee. */
export function numericCell(v: unknown): boolean {
  if (typeof v === "number") return true;
  return typeof v === "string" && /^[<>≤≥=≈~±]?\s?[-−+]?\d[\d.,]*\s?(%|°|mm|kg|N|s)?$/.test(v.trim());
}

/** Columnas de una tabla que van en la fila y las que van debajo de ella, a todo lo ancho. La
 *  primera de texto (la que nombra la fila: «Comprobación») se queda en la fila; otra de texto
 *  con algún valor largo («Por qué», «Origen») va debajo: en una columna de 280 px partía cada
 *  palabra en varias líneas y estiraba la tabla (O17). */
export const LONG_TEXT = 24;
export function tableLayout(rows: Record<string, unknown>[], cols: string[]): { inline: string[]; below: string[] } {
  const textual = (c: string) => rows.some((r) => typeof r[c] === "string" && !numericCell(r[c]));
  const long = (c: string) => rows.some((r) => typeof r[c] === "string" && (r[c] as string).length > LONG_TEXT);
  const main = cols.find(textual);
  const below = cols.filter((c) => c !== main && textual(c) && long(c));
  return { inline: cols.filter((c) => !below.includes(c)), below };
}

/** Filas que se enseñan de una tabla: con más de 6 y alguna que falla (`cumple === false`),
 *  solo las que fallan, hasta que se piden todas (`all`). Así una tarjeta con 20 o 70
 *  comprobaciones no se hace interminable justo cuando hay algo que mirar. */
export function tableRows<R extends Record<string, unknown>>(rows: R[], all: boolean) {
  const failing = rows.filter((r) => r.cumple === false);
  const filtered = !all && failing.length > 0 && rows.length > 6;
  return { rows: filtered ? failing : rows, bad: failing.length, filtered };
}

// Nombre legible de un grupo del motor (los de arm.toml), del catálogo (`bloques.grupo.<g>`).
const GROUPS = new Set(["carga", "criterios", "material", "alojamientos", "herramienta", "geometria", "tubos",
                        "limites", "dinamica", "base"]);
// Los del brazo de detalle van por pieza e interfaz: «pieza_L2» → «Pieza: L2», «interfaz_J1» →
// «Interfaz J1». Lo que sale del nombre de la clave es texto del paquete `pack` (en español):
// se traduce con su catálogo (O15).
export function groupLabel(g: string, pack?: string): string {
  if (GROUPS.has(g)) return t(`bloques.grupo.${g}`);
  const pieza = /^pieza_(.+)$/.exec(g);
  if (pieza) return t("bloques.grupo.pieza", { name: pieza[1].replace(/_/g, " ").replace("muneca", t("bloques.grupo.muneca")) });
  const words = g.replace(/_/g, " ");
  return tp(pack, words.charAt(0).toUpperCase() + words.slice(1));
}

// Una columna de tabla con su nombre legible, del catálogo (`bloques.columna.<c>`).
const COLUMNS = new Set(["comprobacion", "valor", "limite", "cumple", "articulacion", "accionamiento", "utilizacion",
                         "tipo", "arquitectura", "puntuacion", "con_plantilla", "motivos", "motivo", "pieza", "cantidad",
                         "material", "componente", "donde", "nota", "tornillo"]);
// Las demás, del nombre de la clave: la primera en mayúscula, con su tilde si la lleva (las
// palabras de `bloques.palabra.<w>`), y la unidad del sufijo entre paréntesis
// («analitica_kg» → «Analítica (kg)», FF 5.2), traducido con el catálogo de `pack` (O15).
const WORDS = new Set(["analitica", "desvio", "modulo", "cuando", "ultimo"]);
const SUFFIX_UNIT: Record<string, string> = { kg: "kg", mm: "mm", pct: "%", nm: "N·m", s: "s" };
export function columnLabel(c: string, pack?: string): string {
  if (COLUMNS.has(c)) return t(`bloques.columna.${c}`);
  const parts = c.split("_").filter(Boolean);
  const unit = parts.length > 1 ? SUFFIX_UNIT[parts.at(-1)!] : undefined;
  const words = (unit ? parts.slice(0, -1) : parts).map((w) => (WORDS.has(w) ? t(`bloques.palabra.${w}`) : w)).join(" ");
  if (!words) return c;
  return tp(pack, `${words.charAt(0).toUpperCase()}${words.slice(1)}${unit ? ` (${unit})` : ""}`);
}

/** Recuadro de lo que no es transparente en una imagen RGBA (la captura de Fusion viene con
 *  fondo transparente y con mucho margen, D114), con un margen relativo; null si está vacía. */
export function alphaBox(data: ArrayLike<number>, w: number, h: number, margin = 0.04, min = 8):
  { x: number; y: number; w: number; h: number } | null {
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (data[(y * w + x) * 4 + 3] > min) {
        if (x < x0) x0 = x;
        if (x > x1) x1 = x;
        if (y < y0) y0 = y;
        if (y > y1) y1 = y;
      }
    }
  }
  if (x1 < 0) return null;
  const m = Math.round(Math.max(x1 - x0, y1 - y0) * margin);
  const x = Math.max(0, x0 - m), y = Math.max(0, y0 - m);
  return { x, y, w: Math.min(w, x1 + m + 1) - x, h: Math.min(h, y1 + m + 1) - y };
}
