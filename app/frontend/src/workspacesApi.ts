// Las llamadas de los workspaces (PLAN_WORKSPACES W6; la lógica, en `workspaces.ts`). Cada una
// da lo que responde el backend o lanza un Error con su `detail`, en el idioma de la app.
import { apiFetch } from "./auth";
import { detail, type ProfileImportPlan } from "./profile";
import type { Health } from "./welcome";
import {
  switchOutcome, type NewWorkspaceRequest, type ProfileTemplate, type SwitchOutcome, type SwitchResponse,
  type WorkspaceList,
} from "./workspaces";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await apiFetch(path, {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const got = await r.json().catch(() => null);
  if (!r.ok || got === null) throw new Error(detail(got, r.status));
  return got as T;
}

export const listWorkspaces = () => call<WorkspaceList>("GET", "/api/workspaces");
export const removeWorkspace = (id: string) =>
  call<{ workspaces: WorkspaceList["workspaces"] }>("DELETE", `/api/workspaces/${encodeURIComponent(id)}`);
export const listTemplates = async () =>
  (await call<{ plantillas: ProfileTemplate[] }>("GET", "/api/profile/templates")).plantillas;

/** El diálogo de carpeta del sistema (el de la bienvenida): la ruta, o null si se cancela. */
export const chooseFolder = async () =>
  (await call<{ ruta: string | null }>("POST", "/api/welcome/folder")).ruta;

/** Elegir un perfil .zip y su resumen para un workspace nuevo (W4); `file` null si se cancela. */
export const inspectProfileForNew = () =>
  call<ProfileImportPlan>("POST", "/api/profile/import/inspect", { destino: "nuevo" });

const health = async (): Promise<Health> => {
  const r = await apiFetch("/api/health", { cache: "no-store" });
  return r.ok ? await r.json() : null;
};

/** Tras abrir o crear: espera al servidor rearrancado y recarga la ventana (W3). Devuelve en
 *  qué quedó si no recarga (con «recargar», la ventana ya se está recargando). */
export async function settle(got: SwitchResponse): Promise<SwitchOutcome> {
  const o = await switchOutcome(got, health);
  if (o === "recargar") location.reload();
  return o;
}

/** Abre uno de la lista (`id`) o una carpeta que ya es un workspace (`ruta`). */
export const openWorkspace = (target: { id: string } | { ruta: string }) =>
  call<SwitchResponse>("POST", "/api/workspaces/abrir", target);

export const createWorkspace = (req: NewWorkspaceRequest) =>
  call<SwitchResponse>("POST", "/api/workspaces", req);
