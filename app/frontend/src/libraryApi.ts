// Las llamadas de la *Librería* a `/api/library` (backend: pizarra/library_api.py). Lo puro,
// en `library.ts`.
import { apiFetch } from "./auth";
import { t } from "./i18n";
import type { FieldInfo, Ficha, ImportPlan, LibraryItem, StockEntry } from "./library";

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

export const applyImport = (token: string) =>
  call<{ created: number; updated: number; unchanged: number; invalid: number; fichas: number; stock: number }>(
    "/api/library/import/apply", "POST", { token });
