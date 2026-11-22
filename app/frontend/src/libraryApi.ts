// Las llamadas de la *Librería* a `/api/library` (backend: pizarra/library_api.py) y a
// `/api/supply` (proveedores y ofertas, pizarra/supply_api.py). Lo puro, en `library.ts` y
// `supply.ts`.
import { apiFetch } from "./auth";
import { t } from "./i18n";
import type { FieldInfo, Ficha, ImportPlan, LibraryItem, StockEntry } from "./library";
import type { Offer, OffersView, Provider, SearchJob } from "./supply";

/** Un error del backend, con su código (409 = el resumen de importar ya no vale). */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const r = await apiFetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = data?.detail;
    const text = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d?.msg ?? String(d)).join("; ")
      : t("libreria.error_http", { status: r.status });
    throw new ApiError(text, r.status);
  }
  return data as T;
}

const q = (v: string) => encodeURIComponent(v);

export const fetchLibrary = (type = "") =>
  call<{ items: LibraryItem[]; types: string[] }>(`/api/library${type ? `?type=${q(type)}` : ""}`);

export const fetchFields = (type: string) =>
  call<{ type: string; fields: FieldInfo[] }>(`/api/library/fields?type=${q(type)}`);

export const fetchFicha = (key: string) => call<Ficha>(`/api/library/ficha/${q(key)}`);

export const deleteFicha = (key: string) => call<{ ok: boolean }>(`/api/library/ficha/${q(key)}`, "DELETE");

export const saveStock = (changes: Record<string, StockEntry | null>) =>
  call<{ stock: Record<string, StockEntry> }>("/api/library/stock", "PUT", changes);

export type Inspected = {
  file: string | null;
  sheets?: string[];
  sheet?: string;
  columns?: string[];
  sample?: Array<Record<string, unknown> & { _row: number }>;
  rows?: number;
};

/** Sin `path`, el backend abre el diálogo del sistema; `file: null` si se cancela. */
export const inspectImport = (path: string | null, sheet?: string) =>
  call<Inspected>("/api/library/import/inspect", "POST", { path: path || null, sheet: sheet || null });

export const planImport = (body: { path: string; sheet: string; type: string; mapping: Record<string, string> }) =>
  call<ImportPlan>("/api/library/import/plan", "POST",
                   { ...body, sheet: body.sheet || null, type: body.type.trim() || null });

export type ImportDone = { created: number; updated: number; unchanged: number; invalid: number; fichas: number; stock: number };

export const applyImport = (token: string) => call<ImportDone>("/api/library/import/apply", "POST", { token });

/** *Importar* desde el importador que abrió una propuesta del onboarding (PLAN_ONBOARDING N7):
 *  lo mismo que `applyImport`, y la propuesta queda guardada. */
export const applyProposalImport = (proposal: string, token: string) =>
  call<{ importado: ImportDone }>(`/api/onboarding/proposals/${encodeURIComponent(proposal)}/import`, "POST", { token })
    .then((r) => r.importado);

// ------------------------------------------------- proveedores y ofertas (PLAN_APROVISIONAMIENTO)
export const fetchProviders = () => call<{ proveedores: Provider[]; tipos: string[] }>("/api/supply/providers");

export const saveProviders = (proveedores: Provider[]) =>
  call<{ proveedores: Provider[] }>("/api/supply/providers", "PUT", { proveedores });

/** Con `clave` vacía no hay ofertas, pero sí `consumo` (lo gastado desde la Librería). */
export const fetchOffers = (clave: string) => call<OffersView>(`/api/supply/offers?clave=${q(clave)}`);

export const addOffer = (clave: string, oferta: Record<string, unknown>) =>
  call<Offer>("/api/supply/offers", "POST", { clave, oferta });

export const deleteOffer = (id: string) => call<{ ok: boolean }>(`/api/supply/offers/${q(id)}`, "DELETE");

/** Abre la URL guardada de la oferta en el navegador del sistema (la pone el backend, nunca la
 *  interfaz, como los enlaces de la pizarra). */
export const openOffer = (id: string) => call<{ ok: boolean }>(`/api/supply/offers/${q(id)}/open`, "POST", {});

export const startSearch = (clave: string) => call<{ job: string }>("/api/supply/search", "POST", { clave });

export const fetchSearch = (job: string) => call<SearchJob>(`/api/supply/search/${q(job)}`);

export const cancelSearch = (job: string) => call<SearchJob>(`/api/supply/search/${q(job)}/cancel`, "POST", {});
