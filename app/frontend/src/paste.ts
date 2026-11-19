// Lo que se pega con Ctrl+V (plan §3, D84, D137, D140): reglas puras, sin React ni Excalidraw.
//
// Una imagen pegada sobre un post-it entra en ese post-it, encima de su texto; en la pizarra es
// una foto suelta (`customData.kind = "image"`). Las dos guardan el nombre del archivo en
// `board/files/` y su tamaño natural, para que la foto se redimensione sin deformarse. Una URL
// pegada (sola, http o https) es un enlace (`kind = "link"`) con el dominio y un título. Lo
// demás (texto, la copia de elementos de Excalidraw) lo pega Excalidraw.

export const IMAGE_LINK = "https://pizarra.local/image/";
export const LINK_LINK = "https://pizarra.local/link/";
const CARD_FILL = "#ffffff01";    // como el backend (scene.CARD_FILL): se coge por todo el papel

export type ImageRef = { file: string; width: number; height: number };
export type Box = { x: number; y: number; width: number; height: number };

// ------------------------------------------------------------------------------- enlaces

/** La URL si el texto pegado es solo una URL http o https; si no, `null` (lo pega Excalidraw). */
export function pastedUrl(text: string | null | undefined): string | null {
  const t = (text ?? "").trim();
  if (!t || /\s/.test(t) || !/^https?:\/\//i.test(t)) return null;
  try {
    const u = new URL(t);
    return u.hostname ? t : null;
  } catch {
    return null;
  }
}

/** El dominio que enseña la píldora, sin `www.`. */
export function linkDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}

/** La inicial del dominio (D139, 5B): la del nombre, no la del subdominio (docs.google.com → G). */
export function linkInitial(domain: string): string {
  const labels = domain.split(".").filter(Boolean);
  const name = labels.length >= 2 ? labels[labels.length - 2] : labels[0] ?? "";
  return (name[0] ?? "?").toUpperCase();
}

const LETTER_COLORS = ["#1a73e8", "#c2410c", "#2f8a46", "#7a4fb0", "#b8860b", "#0b7285", "#c92a2a"];
/** Color de la inicial: fijo por dominio, para que el mismo sitio se reconozca siempre. */
export function letterColor(domain: string): string {
  let h = 0;
  for (const ch of domain) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return LETTER_COLORS[h % LETTER_COLORS.length];
}

// Lo que acaba una URL de un documento y no dice nada de él («…/d/<id>/edit»).
const GENERIC_TAIL = /^(edit|view|preview|index\.html?|default\.aspx)$/i;

/** El título por defecto (D137): el final de la URL, legible; sin camino, el dominio. */
export function linkTitle(url: string): string {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return url;
  }
  const parts = u.pathname.split("/").filter(Boolean);
  while (parts.length && GENERIC_TAIL.test(parts[parts.length - 1])) parts.pop();
  const last = parts[parts.length - 1];
  if (!last) return linkDomain(url);
  let s = last;
  try {
    s = decodeURIComponent(last);
  } catch { /* se queda como venía */ }
  return s.replace(/[-_+]+/g, " ").trim() || linkDomain(url);
}

// ------------------------------------------------------------------------------- imágenes

export const IMAGE_CAPTION = 26;     // alto del autor y la fecha, en tiza debajo de la foto (4C)
export const IMAGE_MAX_WIDTH = 360;  // una foto nueva nunca nace más ancha
export const IMAGE_MIN_WIDTH = 80;

/** Tamaño de una foto suelta nueva: su ancho natural hasta `IMAGE_MAX_WIDTH`, con la misma
 *  proporción, más el pie con el autor. */
export function imageBox(width: number, height: number): { width: number; height: number } {
  const w = Math.max(IMAGE_MIN_WIDTH, Math.min(IMAGE_MAX_WIDTH, Math.round(width) || IMAGE_MAX_WIDTH));
  return { width: w, height: Math.round(w * ratio(width, height)) + IMAGE_CAPTION };
}

const ratio = (w: number, h: number) => (w > 0 && h > 0 ? h / w : 0.75);

/** La caja de una foto suelta que no se deforma (D84): el alto lo da el ancho. Si se estira por
 *  arriba (se movió el borde de arriba y el de abajo no), se queda quieto el de abajo. `null`
 *  si ya está bien. */
export function keepRatio(prev: Box | undefined, cur: Box, img: Pick<ImageRef, "width" | "height">): Box | null {
  const height = Math.round(cur.width * ratio(img.width, img.height)) + IMAGE_CAPTION;
  if (Math.abs(height - cur.height) < 1) return null;
  const bottomFixed = !!prev && Math.abs(prev.y + prev.height - (cur.y + cur.height)) < 0.5
    && Math.abs(prev.y - cur.y) >= 0.5;
  return { ...cur, height, y: bottomFixed ? cur.y + cur.height - height : cur.y };
}

type El = Box & { id: string; type?: string; isDeleted?: boolean; customData?: Record<string, unknown> };

/** El post-it (visible) que hay debajo del punto, el de más arriba: ahí entra una imagen
 *  pegada (D140). `null`: va suelta a la pizarra. */
export function pasteOnto(elements: readonly El[], at: { x: number; y: number },
                          hidden: (e: El) => boolean = () => false): string | null {
  for (let i = elements.length - 1; i >= 0; i--) {
    const e = elements[i];
    if (e.isDeleted || e.customData?.kind !== "postit" || hidden(e)) continue;
    if (at.x >= e.x && at.x <= e.x + e.width && at.y >= e.y && at.y <= e.y + e.height) return e.id;
  }
  return null;
}

/** Elemento mínimo de una foto suelta o un enlace, centrado en `at`, para `restoreElements`
 *  (que completa lo demás, como con los que crea el backend). Con autor y fecha ya puestos. */
export function cardSkeleton(kind: "image" | "link", id: string, at: { x: number; y: number },
                             size: { width: number; height: number }, data: Record<string, unknown>,
                             now = new Date()) {
  return {
    id, type: "embeddable" as const,
    x: Math.round(at.x - size.width / 2), y: Math.round(at.y - size.height / 2),
    width: size.width, height: size.height, angle: 0,
    strokeColor: "transparent", backgroundColor: CARD_FILL, fillStyle: "solid" as const,
    strokeWidth: 1, roughness: 0, opacity: 100, roundness: null, locked: false,
    link: (kind === "image" ? IMAGE_LINK : LINK_LINK) + id,
    customData: { kind, ...data, author: "user", created: now.toISOString().replace(/\.\d+Z$/, "+00:00") },
  };
}

/** Ancho de la píldora de un enlace nuevo: lo que piden el título y el dominio, con tope. */
export function linkWidth(title: string, domain: string): number {
  // Medido en la app: el título (600 13px) ~6,2 px por letra, el dominio (12px) ~5,8; lo fijo
  // (inicial, huecos y bordes) ~64. La píldora se puede estirar después.
  return Math.max(180, Math.min(420, Math.round(64 + title.length * 6.4 + domain.length * 6)));
}
