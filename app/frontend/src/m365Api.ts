// Microsoft 365 desde la interfaz (docs/PLAN_M365.md §3): la cuenta de *Ajustes → Cuentas*.
// El backend abre el navegador del sistema para iniciar sesión (M2) y espera a que vuelva.
import { apiFetch } from "./auth";
import { t } from "./i18n";
import { driveQuery, type M365CardState, type M365Item, type M365Mail, type M365MailFolder, type M365Service,
         type M365Site, type Place } from "./m365";
import { getStore } from "./store";

export type M365Account = { username: string; name: string; kind: "personal" | "trabajo" };
export type M365State = { configured: boolean; account: M365Account | null; sharepoint: boolean };

type Result<T> = { ok: true; value: T } | { ok: false; error: string };

async function call<T>(path: string, init?: RequestInit): Promise<Result<T>> {
  try {
    const r = await apiFetch(path, init);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      return { ok: false, error: typeof body.detail === "string" ? body.detail : t("ajustes.error_http", { estado: r.status }) };
    }
    return { ok: true, value: body as T };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

const post = (body?: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
});

export const m365State = () => call<M365State>("/api/m365");
export const m365SignIn = (sharepoint = false) => call<M365State>("/api/m365/sign-in", post({ sharepoint }));
export const m365SignOut = () => call<M365State>("/api/m365/sign-out", post());

// ------------------------------------------------------- el panel y las tarjetas (M6-M9, M14)

const project = () => `/api/projects/${encodeURIComponent(getStore().project?.id ?? "")}`;
const cloudCard = (id: string) => `${project()}/m365/cards/${encodeURIComponent(id)}`;

/** Lo de dentro de una carpeta (sin ids, la raíz de mi OneDrive); las carpetas, primero. */
export const m365Drive = (place: Place, service: M365Service) =>
  call<{ items: M365Item[] }>(`/api/m365/drive?${driveQuery(place, service)}`);
export const m365Search = (q: string) =>
  call<{ items: M365Item[] }>(`/api/m365/drive/search?q=${encodeURIComponent(q)}`);
/** Sitios de SharePoint (sin texto, los que sigo) y las bibliotecas de uno (M4). */
export const m365Sites = (q: string) => call<{ items: M365Site[] }>(`/api/m365/sites?q=${encodeURIComponent(q)}`);
export const m365SiteDrives = (siteId: string) =>
  call<{ items: M365Site[] }>(`/api/m365/sites/${encodeURIComponent(siteId)}/drives`);

/** *Llevar a la pizarra* (M6): la tarjeta nueva llega por el WebSocket; la que ya estaba vuelve
 *  en `existing`, como en `POST /cards`. */
export const m365Bring = (item: { drive_id: string | null; id: string; service: M365Service }, at: { x: number; y: number } | null) =>
  call<{ ids: string[]; existing: string[] }>(`${project()}/m365/bring`,
    post({ drive_id: item.drive_id, item_id: item.id, service: item.service, x: at?.x ?? null, y: at?.y ?? null }));
/** *Actualizar desde la nube*; con `force`, *Traer la de la nube* (la local, a la papelera, M8). */
export const m365Refresh = (cardId: string, force = false) =>
  call<{ state: M365CardState }>(`${cloudCard(cardId)}/refresh`, post({ force }));
/** *Guardar en la nube* (M9): una copia de la tarjeta; la nube le cambia el nombre si ya está. */
export type M365Uploaded = { name: string; web_url: string; drive_id?: string; item_id?: string };
export const m365Upload = (cardId: string, target: { service: M365Service; drive_id?: string; folder_id?: string }) =>
  call<M365Uploaded>(`${cloudCard(cardId)}/upload`, post(target));
/** *Abrir en la web* (un archivo: su `webUrl`) o *Abrir en Outlook* (`correo`, `item_id` = el id
 *  del mensaje: su `webLink`): el backend se lo pide a Graph y lo abre en el navegador del
 *  sistema; la interfaz nunca manda la URL que se abre, como en los enlaces (D137). */
export const m365OpenWeb = (item: { drive_id: string; item_id: string; service: M365Service | "correo" }) =>
  call<{ ok: boolean }>("/api/m365/open", post(item));

// ------------------------------------------------------- el correo (M10)

export const m365MailFolders = () => call<{ items: M365MailFolder[] }>("/api/m365/mail/folders");
/** Los correos de una carpeta; con `q`, la búsqueda en todo el buzón. */
export const m365Mail = (folder: string, q: string) =>
  call<{ items: M365Mail[] }>(`/api/m365/mail?${new URLSearchParams({ folder, q }).toString()}`);
/** Un correo a la pizarra como `.eml` y, con `attachments`, sus adjuntos debajo. `notes`: lo
 *  que hay que decir (p. ej. un adjunto enlazado que no se ha descargado). */
export const m365BringMail = (messageId: string, attachments: boolean, at: { x: number; y: number } | null) =>
  call<{ ids: string[]; existing: string[]; notes?: string[] }>(`${project()}/m365/mail/bring`,
    post({ message_id: messageId, attachments, x: at?.x ?? null, y: at?.y ?? null }));
