// La animación de un post-it (plan §3, D143, D175, R42): lo puro de su `iframe`. La escribe el
// agente, así que corre aislada: `sandbox="allow-scripts"` y nada más (sin `allow-same-origin`
// su origen es opaco y no ve la app, ni su almacenamiento, ni `parent.document`; sin
// `allow-top-navigation`, `allow-popups` ni `allow-forms`, no saca al usuario de la app ni abre
// ventanas). La CSP sin red y `sandbox allow-scripts` también llegan como cabecera con el HTML
// (`files_api.get_animation`), que se sirve fuera de `/api/` y sin token: el token en la URL
// del marco lo leería el script en `location`.
//
// Fuera de la vista se desmonta (D175): pausarla con un mensaje no vale, una animación ajena
// puede ignorarlo. Los colores del skin le llegan por `postMessage`, como promete la guía del
// agente (`agent_prompt.ANIMATION_GUIDE`): `{type: "skin", vars: {--bp-bg, --bp-fg,
// --bp-muted, --bp-line, --bp-accent}}`, al cargar y al cambiar de skin.

export type AnimationRef = { file: string; width: number; height: number };

// El nombre es el sha256 del HTML (`board/files/<sha256>.html`): nada más llega a la URL.
const NAME = /^[0-9a-f]{64}\.html$/;

/** Ruta de la animación para el `src` del marco, o null si el nombre no es de una animación. */
export function animationUrl(projectId: string, file: string | undefined | null): string | null {
  if (!projectId || !file || !NAME.test(file)) return null;
  return `/animations/${encodeURIComponent(projectId)}/${file}`;
}

/** Los atributos fijos del marco. `sandbox` solo deja correr scripts; sin `allow` de
 *  permisos (cámara, micrófono, pantalla completa…) y sin mandar de dónde viene. */
export const FRAME_ATTRS = {
  sandbox: "allow-scripts",
  referrerPolicy: "no-referrer",
} as const;

/** Lo que el `sandbox` del marco nunca puede llevar: con cualquiera de ellos, el HTML del
 *  agente vería la app o sacaría de ella al usuario. */
export const FORBIDDEN_SANDBOX = ["allow-same-origin", "allow-top-navigation",
  "allow-top-navigation-by-user-activation", "allow-popups", "allow-popups-to-escape-sandbox",
  "allow-forms", "allow-modals", "allow-downloads"] as const;

// ------------------------------------------------------------------------------ a la vista

/** Lo de Excalidraw que dice qué se ve: desplazamiento y zoom de la escena, y el tamaño del
 *  lienzo en px de pantalla. */
export type View = { scrollX: number; scrollY: number; zoom: { value: number }; width: number; height: number };
export type Rect = { x: number; y: number; width: number; height: number };

/** Margen alrededor del lienzo, en px de pantalla: al desplazar poco no se desmonta y se
 *  vuelve a montar (el HTML vuelve a empezar), y lo que entra ya está cargado. */
export const VIEW_MARGIN = 160;

/** El post-it (en coordenadas de la escena) toca el lienzo visible con su margen. Se mira la
 *  caja entera del post-it: la animación va dentro. */
export function inView(el: Rect, v: View, margin = VIEW_MARGIN): boolean {
  const z = v.zoom.value;
  if (!(z > 0) || !(v.width > 0) || !(v.height > 0)) return false;
  const left = (Math.min(el.x, el.x + el.width) + v.scrollX) * z;
  const top = (Math.min(el.y, el.y + el.height) + v.scrollY) * z;
  const right = left + Math.abs(el.width) * z;
  const bottom = top + Math.abs(el.height) * z;
  return right > -margin && left < v.width + margin && bottom > -margin && top < v.height + margin;
}

// --------------------------------------------------------------------------- colores del skin

/** Las variables que promete la guía del agente, en su orden. */
export const SKIN_VARS = ["--bp-bg", "--bp-fg", "--bp-muted", "--bp-line", "--bp-accent"] as const;

/** De dónde sale cada una: la animación va sobre el papel de su post-it (skins.css y
 *  styles.css `.postit`), así que fondo, tinta, tinta suave y línea son las del post-it de
 *  ese tipo; el acento, el del skin. */
export const SKIN_SOURCE: Record<(typeof SKIN_VARS)[number], string> = {
  "--bp-bg": "--pi",          // el papel del post-it de su tipo
  "--bp-fg": "--pi-fg",       // su tinta
  "--bp-muted": "--pi-t",     // la de la etiqueta del tipo
  "--bp-line": "--pi-b",      // su borde
  "--bp-accent": "--accent",  // el acento del skin
};

export type SkinMessage = { type: "skin"; vars: Record<(typeof SKIN_VARS)[number], string> };

/** El mensaje del skin con las variables ya calculadas por el navegador (`read`, p. ej.
 *  `getComputedStyle(postit).getPropertyValue`). Una que no está sale vacía: la animación
 *  usa entonces su valor por defecto de `var()`. */
export function skinMessage(read: (name: string) => string): SkinMessage {
  const vars = Object.fromEntries(SKIN_VARS.map((k) => [k, (read(SKIN_SOURCE[k]) ?? "").trim()]));
  return { type: "skin", vars: vars as SkinMessage["vars"] };
}
