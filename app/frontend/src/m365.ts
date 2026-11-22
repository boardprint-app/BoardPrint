// Microsoft 365 en la pizarra (docs/PLAN_M365.md §3, M6-M9, M14): lo puro del panel y de las
// tarjetas de la nube, y el estado de la vista que no es de la escena (el panel abierto, la
// tarjeta que se guarda en la nube y las marcas de cada tarjeta que manda el sondeo, M7).
// Las llamadas al backend, en m365Api.ts; la interfaz, en M365Panel.tsx y M365Card.tsx.
import { useSyncExternalStore } from "react";
import { getLanguage, numLocale, t } from "./i18n";

export type M365Service = "onedrive" | "sharepoint";

/** Una fila del panel: lo que da `item_view` del backend (m365_files.py). */
export type M365Item = {
  id: string; drive_id: string | null; name: string; folder: boolean; child_count: number | null;
  size: number; modified: string; web_url: string; ctag: string | null; service: M365Service;
};
/** Un sitio de SharePoint o una de sus bibliotecas de documentos. */
export type M365Site = { id: string; name: string; web_url: string };

/** Un correo de la bandeja (M10): lo que da `GET /api/m365/mail`. */
export type M365Mail = {
  id: string; subject: string; from: { name: string; address: string }; received: string;
  has_attachments: boolean; preview: string; web_link: string; read: boolean;
};
/** Una carpeta del correo, con cuántos tiene y sin leer. */
export type M365MailFolder = { id: string; name: string; total: number; unread: number };

/** `customData.m365` de una tarjeta que vino de la nube (M6) o del correo (M10, `correo`: no se
 *  sondea, y en la escena lleva `message_id` en vez de `item_id`; aquí va en `item_id`). */
export type M365Ref = {
  service: M365Service | "correo"; drive_id: string; item_id: string; name: string;
  ctag: string | null; web_url: string; sha256: string;
};
/** La marca de una tarjeta de la nube que manda el sondeo (M7, M8). */
export type M365CardState = "al_dia" | "descargada" | "conflicto" | "sin_conexion";
const CARD_STATES: M365CardState[] = ["al_dia", "descargada", "conflicto", "sin_conexion"];

/** La tarjeta de la nube de un `customData`, o null si no lo es (o le falta lo que hace falta
 *  para hablar con Graph). */
export function cloudOf(data: unknown): M365Ref | null {
  const m = (data as { m365?: Partial<M365Ref> & { message_id?: string } } | null | undefined)?.m365;
  if (!m || typeof m !== "object") return null;
  const service = m.service === "sharepoint" || m.service === "correo" ? m.service : "onedrive";
  // un correo no tiene unidad: su `item_id` es el id del mensaje (lo que pide `/api/m365/open`)
  const item = service === "correo" ? m.message_id ?? m.item_id : m.item_id;
  if (!item || (service !== "correo" && !m.drive_id)) return null;
  return { service, drive_id: String(m.drive_id ?? ""), item_id: String(item), name: String(m.name ?? ""),
           ctag: m.ctag ?? null, web_url: String(m.web_url ?? ""), sha256: String(m.sha256 ?? "") };
}

/** La marca que se ve en la tarjeta: el conflicto avisa (M8); sin conexión, discreta y nunca
 *  como error (M7); al día y recién descargada, nada. */
export function stateMark(state: M365CardState | undefined): "conflicto" | "sin_conexion" | null {
  return state === "conflicto" || state === "sin_conexion" ? state : null;
}

/** Las marcas que llegan por el WebSocket, solo las que se conocen. */
export function parseStates(cards: unknown): Record<string, M365CardState> {
  const out: Record<string, M365CardState> = {};
  if (!cards || typeof cards !== "object") return out;
  for (const [id, s] of Object.entries(cards as Record<string, unknown>)) {
    if (CARD_STATES.includes(s as M365CardState)) out[id] = s as M365CardState;
  }
  return out;
}

// ------------------------------------------------------------------ carpetas (migas)

/** Un paso de las migas: una carpeta de una unidad. `drive_id` e `item_id` null, la raíz de mi
 *  OneDrive; `item_id` «root», la raíz de una biblioteca de SharePoint. */
export type Place = { label: string; drive_id: string | null; item_id: string | null };

export const oneDriveRoot = (): Place => ({ label: t("m365.panel.onedrive"), drive_id: null, item_id: null });
/** La raíz de una biblioteca de documentos de SharePoint. */
export const libraryRoot = (lib: M365Site): Place => ({ label: lib.name, drive_id: lib.id, item_id: "root" });

/** Entrar en una carpeta: las migas con ella al final. */
export const enter = (crumbs: Place[], folder: M365Item): Place[] =>
  [...crumbs, { label: folder.name, drive_id: folder.drive_id, item_id: folder.id }];

/** Volver a la miga `index` (la de la raíz es la 0); fuera de rango, se quedan como están. */
export const goTo = (crumbs: Place[], index: number): Place[] =>
  index >= 0 && index < crumbs.length ? crumbs.slice(0, index + 1) : crumbs;

/** La consulta de `GET /api/m365/drive` para una carpeta; sin ids, la raíz de mi OneDrive. */
export function driveQuery(place: Place, service: M365Service): string {
  const q = new URLSearchParams({ service });
  if (place.drive_id) q.set("drive_id", place.drive_id);
  if (place.item_id) q.set("item_id", place.item_id);
  return q.toString();
}

/** A dónde sube *Guardar en la nube* (M9) estando en `place`: sin unidad, a la raíz de mi
 *  OneDrive (el backend no necesita nada más). */
export function uploadTarget(place: Place, service: M365Service): { service: M365Service; drive_id?: string; folder_id?: string } {
  return place.drive_id && place.item_id
    ? { service, drive_id: place.drive_id, folder_id: place.item_id }
    : { service };
}

/** *Guardar la mía en la nube* en un conflicto (M8): de momento, a la raíz de la misma unidad,
 *  con otro nombre si ya está (M9). */
export const conflictTarget = (ref: M365Ref) =>
  ({ service: ref.service === "sharepoint" ? "sharepoint" as const : "onedrive" as const,
     drive_id: ref.drive_id, folder_id: "root" });

/** Qué ofrece el menú de una tarjeta de la nube: un correo se abre en Outlook y no se actualiza
 *  (no se sondea); un archivo, en la web y con *Actualizar desde la nube*. */
export const cloudActions = (ref: M365Ref) =>
  ({ outlook: ref.service === "correo", refresh: ref.service !== "correo" });

// ------------------------------------------------------------------ textos de una fila

/** La fecha de modificación para leer («21 nov 2026»); vacía si no se entiende. */
export function fmtModified(iso: string, lang = getLanguage()): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(numLocale(lang), { day: "numeric", month: "short", year: "numeric" });
}

// ------------------------------------------------------------------ estado de la vista

type M365View = {
  panel: boolean;                              // el panel del lienzo, abierto (M14)
  saving: { card: string; name: string } | null;   // *Guardar en OneDrive…* de esa tarjeta (M9)
  states: Record<string, M365CardState>;       // marcas del sondeo (M7, M8)
  tick: number;                                // sube al iniciar o cerrar sesión
};
const EMPTY: M365View = { panel: false, saving: null, states: {}, tick: 0 };
let view: M365View = EMPTY;
const listeners = new Set<() => void>();
function set(patch: Partial<M365View>) {
  view = { ...view, ...patch };
  listeners.forEach((l) => l());
}

export const openM365Panel = () => set({ panel: true });
export const closeM365Panel = () => set({ panel: false });
export const openSaveToCloud = (card: string, name: string) => set({ saving: { card, name } });
export const closeSaveToCloud = () => set({ saving: null });
export const getM365View = () => view;
/** Al abrir otro proyecto no queda nada del anterior. */
export const resetM365View = () => set({ ...EMPTY, tick: view.tick });

/** El mensaje `m365` del WebSocket: con `cards`, las marcas de todas las tarjetas de la nube;
 *  sin ellas, la cuenta ha cambiado (el panel vuelve a mirarla). */
export function handleM365Message(msg: { cards?: unknown }) {
  if (msg.cards !== undefined) set({ states: parseStates(msg.cards) });
  else set({ tick: view.tick + 1 });
}

export function useM365View(): M365View {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => view);
}
