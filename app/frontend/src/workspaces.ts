// Varios workspaces (docs/PLAN_WORKSPACES.md W6, W7): el menú del chip en la pantalla de inicio,
// la lista en *Ajustes → General* y el diálogo *Nuevo workspace*. Aquí, lo que no es React ni
// red: qué se puede abrir o quitar, la carpeta por defecto, la petición de crear con su «desde»
// y qué hacer con la respuesta de abrir o crear. Las llamadas, en `workspacesApi.ts`.
//
// `GET /api/workspaces` da `{workspaces: [{id, nombre, ruta, abierto, falta}], carpeta_base}`;
// `POST /api/workspaces {nombre, ruta?, desde}` crea uno y lo abre; `POST /api/workspaces/abrir
// {id | ruta}` abre otro; `DELETE /api/workspaces/<id>` lo quita de la lista sin borrar nada.
// Abrir y crear rearrancan el servidor (W3): la ventana espera (`waitForRestart`) y recarga.
import { t } from "./i18n";
import { waitForRestart, type Health } from "./welcome";

export type WorkspaceEntry = { id: string; nombre: string; ruta: string; abierto: boolean; falta: boolean };
export type WorkspaceList = { workspaces: WorkspaceEntry[]; carpeta_base: string | null };

/** Lo que lleva una plantilla de sector (su manifiesto). */
export type TemplateContents = { fabricacion: boolean; fichas: number; proveedores: boolean };
export type ProfileTemplate = {
  id: string; titulo: string; descripcion: string; generica: boolean; lleva: TemplateContents;
};

/** Con qué empieza un workspace nuevo: vacío, una plantilla de sector o un perfil .zip ya
 *  inspeccionado (su token; sin token aún, no se puede crear). */
export type Start =
  | { kind: "vacio" }
  | { kind: "plantilla"; id: string }
  | { kind: "perfil"; token: string | null };

/** Se abre si no es el abierto y su carpeta está (W7: el que falta solo se quita). */
export const canOpen = (w: WorkspaceEntry) => !w.abierto && !w.falta;

/** Se quita de la lista cualquiera menos el abierto (W7). */
export const canRemove = (w: WorkspaceEntry) => !w.abierto;

/** Cómo sale en la lista: el abierto, uno que no se encuentra o uno que se puede abrir. */
export type EntryState = "abierto" | "falta" | "cerrado";
export const entryState = (w: WorkspaceEntry): EntryState =>
  w.abierto ? "abierto" : w.falta ? "falta" : "cerrado";

/** La carpeta por defecto de uno nuevo: `<carpeta_base>/<nombre>`, con la barra de la base
 *  (la de Windows si la base la usa). Sin base o sin nombre, vacía. */
export function defaultFolder(base: string | null | undefined, nombre: string): string {
  const name = nombre.trim();
  if (!base || !name) return "";
  const sep = base.includes("\\") ? "\\" : "/";
  return base.replace(/[\\/]+$/, "") + sep + name;
}

/** El «desde» de `POST /api/workspaces` (W4): `vacio`, `plantilla:<id>` o el token del perfil;
 *  null si es un perfil aún sin inspeccionar. */
export function desdeOf(start: Start): string | null {
  if (start.kind === "vacio") return "vacio";
  if (start.kind === "plantilla") return start.id ? `plantilla:${start.id}` : null;
  return start.token || null;
}

export type NewWorkspaceRequest = { nombre: string; ruta?: string; desde: string };

/** La petición de crear, o null si aún falta algo (nombre, carpeta o el perfil sin elegir).
 *  `carpeta` es la elegida con el diálogo; sin ella va la de por defecto, que calcula el
 *  backend con el mismo nombre que valida (por eso no se manda). */
export function newWorkspaceRequest(
  nombre: string, carpeta: string | null, base: string | null, start: Start,
): NewWorkspaceRequest | null {
  const name = nombre.trim();
  const desde = desdeOf(start);
  if (!name || desde === null) return null;
  const ruta = carpeta?.trim();
  if (!ruta && !base) return null;          // sin carpeta por defecto hay que elegir una
  return ruta ? { nombre: name, ruta, desde } : { nombre: name, desde };
}

/** Lo que trae una plantilla, en una frase («perfil de fabricación, 3 fichas»), o «nada». */
export function templateContents(lleva: TemplateContents): string {
  const parts: string[] = [];
  if (lleva.fabricacion) parts.push(t("workspaces.lleva.fabricacion"));
  if (lleva.fichas > 0) parts.push(t(lleva.fichas === 1 ? "workspaces.lleva.ficha" : "workspaces.lleva.fichas", { n: lleva.fichas }));
  if (lleva.proveedores) parts.push(t("workspaces.lleva.proveedores"));
  return parts.length ? parts.join(", ") : t("workspaces.lleva.nada");
}

/** La respuesta de abrir o crear (W3). */
export type SwitchResponse = {
  workspace: WorkspaceEntry; reinicio: boolean; al_abrir?: boolean;
};

/** En qué queda: recargar (el servidor ya volvió con el otro workspace), se abrirá al volver a
 *  abrir la app (sin quien rearranque), ya era el abierto, o el servidor no ha vuelto. */
export type SwitchOutcome = "recargar" | "al_abrir" | "mismo" | "no_vuelve";

export async function switchOutcome(
  got: SwitchResponse, health: () => Promise<Health>,
  wait: typeof waitForRestart = waitForRestart,
): Promise<SwitchOutcome> {
  if (!got.reinicio) return got.al_abrir ? "al_abrir" : "mismo";
  return (await wait(got.workspace.ruta, health)) ? "recargar" : "no_vuelve";
}

/** El texto de lo que no es recargar. */
export function outcomeText(o: Exclude<SwitchOutcome, "recargar">, nombre: string): string {
  return o === "al_abrir" ? t("workspaces.al_abrir", { nombre })
    : o === "mismo" ? t("workspaces.ya_abierto", { nombre }) : t("workspaces.no_vuelve");
}
