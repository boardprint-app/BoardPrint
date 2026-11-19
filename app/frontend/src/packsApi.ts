// Las llamadas de Ajustes → Paquetes a `/api/packs` (backend: pizarra/pack_install_api.py).
import { apiFetch, token } from "./auth";
import type { InstalledPack, Plan, Targets } from "./packs";

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await apiFetch(path, init);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(body?.detail ?? `${r.status} ${r.statusText}`);
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

/** En la app de escritorio el backend abre los diálogos del sistema (como *Archivo*, D59);
 *  en el navegador no hay rutas: se suben los archivos y se descarga lo exportado. */
export const desktop = token !== null;

export const fetchPacks = () => call<{ packs: InstalledPack[]; targets: Targets }>("/api/packs");

export async function uploadFiles(files: File[]): Promise<string[]> {
  const paths: string[] = [];
  for (const f of files) {
    const got = await call<{ path: string }>(`/api/packs/uploads?name=${encodeURIComponent(f.name)}`,
      { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: f });
    paths.push(got.path);
  }
  return paths;
}

/** Sin `paths`, el backend abre el diálogo del sistema; `null` si se cancela. */
export async function inspect(paths: string[] | null, target: string): Promise<Plan | null> {
  const got = await call<Plan | { cancelled: true }>("/api/packs/inspect", json({ paths, target }));
  return "cancelled" in got ? null : got;
}

export const discard = (t: string) => apiFetch(`/api/packs/inspect/${t}`, { method: "DELETE" }).catch(() => undefined);

export const install = (t: string) =>
  call<{ installed: string[]; packs: InstalledPack[] }>("/api/packs/install", json({ token: t }));

export const uninstall = (id: string, origin: string) =>
  call<{ packs: InstalledPack[] }>(`/api/packs/${id}/uninstall`, json({ origin }));

/** En el escritorio, a la carpeta que se elija (devuelve la ruta, o null si se cancela); en el
 *  navegador, una descarga. */
export async function exportPack(id: string): Promise<string | null> {
  if (desktop) {
    const got = await call<{ path?: string; cancelled?: boolean }>(`/api/packs/${id}/export`, json({}));
    return got.path ?? null;
  }
  const a = document.createElement("a");
  a.href = `/api/packs/${id}/export`;
  a.download = "";
  a.click();
  return "";
}
