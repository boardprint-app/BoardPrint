// Acciones de las tarjetas de archivo y de carpeta contra el backend (pizarra/files_api.py).
// Los diálogos del sistema los abre el backend (la interfaz no ve rutas, D129): la petición
// espera a que el usuario elija. Un fallo sale en el aviso de la pizarra (`lastError`).
import { apiFetch, token } from "./auth";
import { t } from "./i18n";
import { getStore, setStore } from "./store";

const base = () => `/api/projects/${encodeURIComponent(getStore().project?.id ?? "")}`;

async function call<T = unknown>(path: string, method = "POST", body?: unknown): Promise<T | null> {
  const r = await apiFetch(`${base()}${path}`, {
    method,
    ...(body !== undefined ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
  });
  if (!r.ok) {
    setStore({ lastError: (await r.json().catch(() => null))?.detail ?? t("lienzo.error.http", { status: r.status }) });
    return null;
  }
  return (await r.json()) as T;
}

const card = (id: string) => `/cards/${encodeURIComponent(id)}`;

/** Añadir archivos (diálogo de varios) o una carpeta en (x, y); con `paths`, las arrastradas.
 *  Lo que ya estaba en la pizarra no se repite (O17): vuelve en `existing`, se avisa y
 *  `onExisting` lo selecciona. */
export async function addCards(at: { x: number; y: number }, kind: "file" | "folder", paths?: string[],
                               onExisting?: (ids: string[]) => void) {
  const r = await call<{ ids: string[]; existing?: string[] }>("/cards", "POST", { kind, ...at, ...(paths ? { paths } : {}) });
  const existing = r?.existing ?? [];
  if (existing.length) {
    const text = existing.length === 1 ? t("lienzo.anadir.ya_esta") : t("lienzo.anadir.ya_estan", { n: existing.length });
    setStore({ notice: { text, kind: "info", at: Date.now() } });
    onExisting?.(existing);
  }
  return r;
}

/** *Abrir* (D141): con el programa por defecto (un STEP, en Fusion) o con «Abrir con». */
export const openCard = (id: string, withPicker = false) => call(`${card(id)}/open`, "POST", { with: withPicker });
export const revealCard = (id: string) => call(`${card(id)}/reveal`);
/** «Buscar de nuevo» / «Buscar otro archivo…» (D138): el diálogo, misma tarjeta. */
export const relocateCard = (id: string) => call(`${card(id)}/relocate`, "POST", {});
/** Calcular el hash de una carpeta de más de 500 MB (D136). */
export const confirmCard = (id: string) => call(`${card(id)}/confirm`);
/** *Guardar también en…* (D109): el diálogo, la tarjeta de la carpeta y su flecha. */
export const saveTo = (blockId: string) =>
  call<{ ids: string[] }>(`/blocks/${encodeURIComponent(blockId)}/save-to`, "POST", {});

/** *Tomar de Excel* (PLAN_EXCEL §3.2): enlaza el parámetro `param` del bloque con el nombre
 *  `name` de la tarjeta de Excel `card`; sin `card`, *Quitar enlace* (se queda el último
 *  valor). Uno que no vale sale en el aviso con el motivo del backend (422). */
export const linkParam = (block: string, param: string, card: string | null, name?: string) =>
  call<{ links: Record<string, unknown> }>(`/blocks/${encodeURIComponent(block)}/links`, "POST",
                                           card ? { param, card, name } : { param });

/** Qué campo de salida va al nombre `name` del Excel `cardId` (PLAN_EXCEL §3.3); `pick` null,
 *  nada. Uno que no vale (la unidad, una fórmula…) sale en el aviso con el motivo (422). */
export const setWrite = (cardId: string, name: string, pick: { block: string; port: string; field: string } | null) =>
  call<{ write: unknown }>(`${card(cardId)}/writes`, "POST", { name, ...(pick ?? {}) });
/** *Escribir copia*: la copia `_n` con su propuesta (el original nunca se escribe). */
export const writeCopy = (cardId: string) =>
  call<{ proposal: string; nuevo: string }>(`${card(cardId)}/write-copy`, "POST", {});

export type CardInfo = { id: string; kind: "file" | "folder"; path: string; name: string; folder: string;
                         exists: boolean; type: string; open_with: boolean };
export const cardInfo = (id: string) => call<CardInfo>(card(id), "GET");

export async function copyPath(id: string) {
  const info = await cardInfo(id);
  if (!info) return;
  try {
    await navigator.clipboard.writeText(info.path);
  } catch {
    setStore({ lastError: t("lienzo.portapapeles.error") });
  }
}

export type FolderContent = {
  entries: { path: string; kind: "file" | "dir"; size: number; marked: boolean | "all" | "none" | "some" }[];
  cut: boolean; everything: boolean;
};
export const folderContent = (id: string) => call<FolderContent>(`${card(id)}/content`, "GET");

// ------------------------------------------------------- imágenes y enlaces pegados (D84, D137)

/** Guarda una imagen pegada en `board/files/` y devuelve su nombre (`<sha256>.<ext>`). */
export async function uploadImage(file: Blob): Promise<string | null> {
  const r = await apiFetch(`${base()}/images`, {
    method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file,
  });
  if (!r.ok) {
    setStore({ lastError: (await r.json().catch(() => null))?.detail ?? t("lienzo.error.http", { status: r.status }) });
    return null;
  }
  return (await r.json()).file as string;
}

/** URL de una imagen de la pizarra para un `<img>`, que no manda cabeceras: con el token. */
export function imageUrl(file: string) {
  const q = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${base()}/images/${encodeURIComponent(file)}${q}`;
}

/** Abre el enlace en el navegador del sistema: el backend toma la URL de la escena. */
export const openLink = (id: string) => call(`/links/${encodeURIComponent(id)}/open`);
