// Lo puro de *Dónde comprar* y de los proveedores (docs/PLAN_APROVISIONAMIENTO.md §2-§5): cómo se
// lee una oferta (precio con su cantidad, plazo, desconocido no es 0), lo que se manda al
// añadir una a mano (un campo numérico vacío es null, nunca 0), qué dice cada paso de la
// búsqueda y el orden de la lista de proveedores. Las llamadas, en `libraryApi.ts`.
import { getLanguage, numLocale, parseNumber, t } from "./i18n";

/** Un proveedor (A2): `tipos` vacío cubre todos los de la librería. */
export type Provider = { nombre: string; dominio: string; tipos: string[] };

/** Una oferta, como la da `GET /api/supply/offers` (backend: pizarra/supply.py). `precio` y
 *  `plazo_dias` null = desconocido (nunca 0). */
export type Offer = {
  id: string;
  clave: string;
  coincidencia: "exacta" | "equivalente";
  proveedor: string;
  dominio: string | null;
  referencia: string;
  fabricante: string;
  precio: number | null;
  moneda: string | null;
  por_cantidad: number;
  plazo_dias: number | null;
  disponibilidad: string;
  url: string | null;
  via: "pagina" | "buscador" | null;
  cita: string;
  origen: "agente" | "mano";
  fecha: string;
  nota: string;
  vigente: boolean;
};

export type Usage = { usd: number; busquedas: number };

export type OffersView = { exactas: Offer[]; equivalentes: Offer[]; caducidad_dias: number; consumo: Usage };

export type SearchEvent =
  | { kind: "search"; query: string }
  | { kind: "fetch"; url: string; ok: boolean }
  | { kind: "offer"; offer: Offer }
  | { kind: "rejected"; reason: string }
  | { kind: "text"; text: string };

export type SearchResult = {
  ofertas: Offer[]; consultas: string[]; abiertas: string[]; fallidas: string[]; rechazadas: string[];
  cost_usd: number | null; error?: string;
};

export type SearchJob = {
  id: string; clave: string; estado: "buscando" | "hecha" | "tope" | "cancelada" | "error";
  eventos: SearchEvent[]; resultado: SearchResult | null;
};

// ------------------------------------------------------------------ leer una oferta
/** Un precio con dos decimales al menos (2,95; 412,50) y hasta cuatro (0,0235). */
export const fmtPrice = (v: number) =>
  v.toLocaleString(numLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 });

/** «2,95 EUR / 1 ud.», «24,10 EUR / 10 uds.»; sin precio, «sin precio» (nunca 0). */
export function priceText(o: Pick<Offer, "precio" | "moneda" | "por_cantidad">): string {
  if (o.precio === null || o.precio === undefined) return t("libreria.ofertas.sin_precio");
  const n = o.por_cantidad || 1;
  return t(n === 1 ? "libreria.ofertas.precio_uno" : "libreria.ofertas.precio_n",
           { precio: fmtPrice(o.precio), moneda: o.moneda ?? "", n });
}

/** «plazo 15 días»; null, «plazo desconocido» (nunca 0). */
export function leadText(dias: number | null | undefined): string {
  if (dias === null || dias === undefined) return t("libreria.ofertas.plazo_desconocido");
  return t(dias === 1 ? "libreria.ofertas.plazo_uno" : "libreria.ofertas.plazo", { n: dias });
}

/** La fecha de una consulta para leer («20 nov 2026»); la ISO tal cual si no se entiende. */
export function dateText(iso: string): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return iso || "?";
  return d.toLocaleDateString(numLocale(getLanguage()), { day: "numeric", month: "short", year: "numeric" });
}

/** El host de una URL, para el enlace y el progreso; la URL entera si no se entiende. */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname || url;
  } catch {
    return url;
  }
}

/** «0,05 USD»: el gasto con dos decimales (y más si es menos de un céntimo). */
export function usdText(usd: number | null | undefined): string {
  const v = usd ?? 0;
  const max = v > 0 && v < 0.01 ? 4 : 2;
  return `${v.toLocaleString(numLocale(), { minimumFractionDigits: 2, maximumFractionDigits: max })} USD`;
}

// ------------------------------------------------------------------ oferta a mano (A7)
/** Lo escrito en el formulario de *Añadir oferta*, todo como texto. */
export type OfferDraft = {
  proveedor: string; referencia: string; precio: string; moneda: string; por_cantidad: string;
  plazo_dias: string; disponibilidad: string; url: string; nota: string;
  coincidencia: "exacta" | "equivalente";
};

export const emptyOfferDraft = (): OfferDraft => ({
  proveedor: "", referencia: "", precio: "", moneda: "EUR", por_cantidad: "", plazo_dias: "",
  disponibilidad: "", url: "", nota: "", coincidencia: "exacta",
});

const NUMERIC = ["precio", "por_cantidad", "plazo_dias"] as const;
const INTEGER = new Set<string>(["por_cantidad", "plazo_dias"]);

/** El cuerpo de `POST /api/supply/offers` (`oferta`) a partir del formulario, o los errores
 *  por campo. Un número vacío va como null (desconocido), nunca 0; uno que no es positivo, o
 *  con decimales donde van unidades o días, es error aquí, antes de mandarlo. Sin precio, la
 *  moneda no se manda (no dice nada). */
export function offerPayload(d: OfferDraft):
    { ok: true; oferta: Record<string, unknown> } | { ok: false; errors: Partial<Record<keyof OfferDraft, string>> } {
  const errors: Partial<Record<keyof OfferDraft, string>> = {};
  const nums: Record<string, number | null> = {};
  for (const f of NUMERIC) {
    const raw = d[f].trim();
    if (!raw) { nums[f] = null; continue; }
    const n = parseNumber(raw);
    if (n === null || n <= 0 || (INTEGER.has(f) && !Number.isInteger(n))) {
      errors[f] = t(INTEGER.has(f) ? "libreria.ofertas.form.entero_no_valido" : "libreria.ofertas.form.numero_no_valido");
    } else nums[f] = n;
  }
  if (!d.proveedor.trim()) errors.proveedor = t("libreria.ofertas.form.falta_proveedor");
  const moneda = d.moneda.trim().toUpperCase();
  if (nums.precio !== null && nums.precio !== undefined && !/^[A-Z]{3}$/.test(moneda)) {
    errors.moneda = t("libreria.ofertas.form.moneda_no_valida");
  }
  if (Object.keys(errors).length) return { ok: false, errors };
  return {
    ok: true,
    oferta: {
      proveedor: d.proveedor.trim(), referencia: d.referencia.trim(),
      precio: nums.precio, moneda: nums.precio === null ? null : moneda,
      por_cantidad: nums.por_cantidad, plazo_dias: nums.plazo_dias,
      disponibilidad: d.disponibilidad.trim(), url: d.url.trim() || null, nota: d.nota.trim(),
      coincidencia: d.coincidencia,
    },
  };
}

// ------------------------------------------------------------------ la búsqueda
/** Lo que dice cada paso de la búsqueda, para el progreso. */
export function eventText(e: SearchEvent): string {
  switch (e.kind) {
    case "search": return t("libreria.ofertas.ev.buscando", { consulta: e.query ?? "" });
    case "fetch": return t(e.ok ? "libreria.ofertas.ev.abriendo" : "libreria.ofertas.ev.no_abre", { sitio: hostOf(e.url ?? "") });
    case "offer": return t("libreria.ofertas.ev.apuntada", {
      proveedor: e.offer?.proveedor ?? "?", precio: e.offer ? priceText(e.offer) : "" });
    case "rejected": return t("libreria.ofertas.ev.descartada", { motivo: e.reason ?? "" });
    case "text": return e.text ?? "";
  }
  return "";      // un paso que esta interfaz no conoce: no se dice nada
}

/** La línea de cuando acaba: cuántas apuntó, lo gastado y, si falló, por qué. */
export function resultText(job: SearchJob): string {
  const r = job.resultado;
  const n = r?.ofertas?.length ?? 0;
  const vars = { n, coste: usdText(r?.cost_usd) };
  if (job.estado === "cancelada") return t("libreria.ofertas.fin.cancelada", vars);
  if (job.estado === "tope") return t("libreria.ofertas.fin.tope", vars);
  if (job.estado === "error") return t("libreria.ofertas.fin.error", { ...vars, motivo: r?.error ?? "?" });
  return t(n === 0 ? "libreria.ofertas.fin.ninguna" : n === 1 ? "libreria.ofertas.fin.una" : "libreria.ofertas.fin.hecha", vars);
}

// ------------------------------------------------------------------ proveedores (A2)
/** La lista con el de `i` movido `by` puestos (−1 sube, +1 baja); igual si se sale. */
export function moveItem<T>(list: T[], i: number, by: number): T[] {
  const j = i + by;
  if (i < 0 || i >= list.length || j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

/** Marcar o desmarcar un tipo de un proveedor, en el orden de `all` (los de la librería). */
export function toggleType(tipos: string[], type: string, all: string[]): string[] {
  const on = new Set(tipos);
  if (on.has(type)) on.delete(type);
  else on.add(type);
  return [...all.filter((x) => on.has(x)), ...[...on].filter((x) => !all.includes(x))];
}

/** Lo que se manda al guardar: nombre y dominio sin espacios alrededor (el backend valida). */
export const cleanProviders = (list: Provider[]): Provider[] =>
  list.map((p) => ({ nombre: p.nombre.trim(), dominio: p.dominio.trim(), tipos: p.tipos }));

/** ¿Ha cambiado la lista desde lo guardado? (el orden cuenta). */
export const providersChanged = (a: Provider[], b: Provider[]) =>
  JSON.stringify(cleanProviders(a)) !== JSON.stringify(cleanProviders(b));
