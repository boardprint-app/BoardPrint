// Office con el agente (plan D176, FF 4.6 paso 7): lo puro de *Leer con el agente*, *Editar
// con el agente* y *Nuevo archivo*. Cada acción abre un hilo (o, sin nada a lo que anclarlo, el
// chat) con el encargo ya escrito: el texto de aquí. Las herramientas son del backend
// (`leer_archivo`, `proponer_cambio`, `crear_archivo`, `editar_archivo`); la interfaz solo
// dice qué se pide y sobre qué tarjeta o bloque.

import { getLanguage, t } from "./i18n";

/** Lo que el agente sabe leer (`read_files.py`) y lo que sabe editar (`office_write.py`). */
const READABLE = new Set(["pdf", "docx", "docm", "xlsx", "xlsm", "pptx", "pptm"]);
export const EDITABLE = { docx: "Word", xlsx: "Excel", pptx: "PowerPoint" } as const;
export type OfficeType = keyof typeof EDITABLE;

const extOf = (type: string) => (type.startsWith("archivo.") ? type.slice(8).toLowerCase() : "");

/** ¿Tiene *Leer con el agente* la tarjeta de este tipo (`archivo.<ext>`)? */
export const canRead = (type: string) => READABLE.has(extOf(type));
/** ¿Tiene *Editar con el agente*? Solo Word, Excel y PowerPoint de ahora (no el antiguo). */
export const canEdit = (type: string) => extOf(type) in EDITABLE;

type Card = { id: string; name: string };
type Block = { id: string; title: string };

const cite = (c: Card) => t("agente.office.citar", { id: c.id });

/** *Leer con el agente → a post-its* (D176): que lo lea y deje post-its anclados a la tarjeta. */
export function readToPostits(c: Card): string {
  return t("agente.office.encargo_postits", { nombre: c.name, id: c.id, citar: cite(c) });
}

/** *Leer con el agente → a la entrada de un bloque* (D176): que proponga sus parámetros con la
 *  fuente `archivo`; solo los que da el archivo. */
export function readToBlock(c: Card, b: Block): string {
  return t("agente.office.encargo_bloque", { nombre: c.name, id: c.id, bloque: b.title, bloque_id: b.id, citar: cite(c) });
}

/** *Editar con el agente* (D176): lo que pide el ingeniero, con la regla de la copia. */
export function editBrief(c: Card, what: string): string {
  return t("agente.office.encargo_editar", { nombre: c.name, id: c.id, que: what.trim() });
}

/** *Nuevo archivo* (D176): el encargo de `crear_archivo`. `anchored`: el hilo está anclado a
 *  lo seleccionado, que es de donde sale el contenido. */
export function newFileBrief(type: OfficeType, what: string, anchored: boolean): string {
  return t("agente.office.encargo_nuevo", { nombre_tipo: EDITABLE[type], tipo: type, que: what.trim(),
                                            anclado: anchored ? t("agente.office.encargo_nuevo_anclado") : "" });
}

/** El título del hilo de cada acción (D166: la etiqueta sobre la pizarra). */
export const briefTitle = {
  read: (c: Card) => t("agente.office.titulo_leer", { nombre: c.name }),
  edit: (c: Card) => t("agente.office.titulo_editar", { nombre: c.name }),
  create: (type: OfficeType) => t("agente.office.titulo_nuevo", { tipo: EDITABLE[type] }),
};

type El = { id: string; isDeleted?: boolean; customData?: unknown;
            startBinding?: { elementId?: string } | null; endBinding?: { elementId?: string } | null };

/** Los bloques a los que entra la tarjeta `card` (con una conexión, D131), en orden. */
export function connectedBlocks(elements: readonly El[], card: string, blocks: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const e of elements) {
    const kind = (e.customData as { kind?: string } | undefined)?.kind;
    if (e.isDeleted || kind !== "connection" || e.startBinding?.elementId !== card) continue;
    const to = e.endBinding?.elementId;
    if (to && to in blocks && !out.includes(to)) out.push(to);
  }
  return out;
}

/** Los bloques para elegir en *a la entrada de un bloque*: los conectados primero (marcados),
 *  luego el resto por título; como mucho `max`. */
export function blockChoices(all: readonly Block[], connected: readonly string[], max = 8): (Block & { connected: boolean })[] {
  const first = connected.map((id) => all.find((b) => b.id === id)).filter((b): b is Block => !!b);
  const rest = all.filter((b) => !connected.includes(b.id)).sort((a, b) => a.title.localeCompare(b.title, getLanguage()));
  return [...first.map((b) => ({ ...b, connected: true })), ...rest.map((b) => ({ ...b, connected: false }))].slice(0, max);
}

// ------------------------------------------------------------- propuesta de archivo

/** El cambio de una propuesta de archivo (`editar_archivo`): la copia y lo que cambia. */
export type FileDiffItem = { where: string; before: string; after: string };
export type FileChange = { nuevo: string; diff: FileDiffItem[] };

/** El nombre de un archivo a partir de su ruta guardada (con `/` o `\`). */
export const fileName = (p: string) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? p;
