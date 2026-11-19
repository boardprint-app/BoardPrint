// Atajos de la app (plan D97, D185): una tabla central con su valor por defecto; *Ajustes →
// Atajos* los cambia y se guardan en `settings.toml` (`[atajos]`, solo los cambiados; `""` es
// sin atajo). Una combinación se escribe «Ctrl+Mayús+B», en la forma canónica del backend
// (`normalize_combo` en pizarra/settings.py): Ctrl, Mayús y Alt en ese orden y una letra o una
// cifra. Ctrl vale también por Cmd en Mac.
import { t } from "./i18n";
import { EXCALIDRAW_KEYS } from "./excalidrawKeys";

/** `label` es la clave del texto (locales/es.ts). */
export type Shortcut = { id: string; label: string; default: string };

// Ctrl+X no sale: sigue siendo el de Excalidraw, que la app amplía a las tarjetas (D185).
export const SHORTCUTS: Shortcut[] = [
  { id: "blocks.search", label: "atajos.accion.blocks_search", default: "Ctrl+B" },
  { id: "view.fit_all", label: "atajos.accion.fit_all", default: "Mayús+1" },   // i18n-ok: combo canónico
  { id: "view.fit_selection", label: "atajos.accion.fit_selection", default: "Mayús+2" },   // i18n-ok: combo canónico
  { id: "view.fit_viewport", label: "atajos.accion.fit_viewport", default: "Mayús+3" },   // i18n-ok: combo canónico
  { id: "tinta.activar", label: "atajos.accion.tinta_activar", default: "M" },   // D189: libre en Excalidraw 0.18
];

type Combo = { ctrl: boolean; shift: boolean; alt: boolean; key: string };

export function parseCombo(combo: string): Combo {
  const parts = combo.split("+").map((p) => p.trim().toLowerCase());
  const key = parts[parts.length - 1];
  return {
    ctrl: parts.includes("ctrl") || parts.includes("cmd"),
    shift: parts.includes("mayús") || parts.includes("mayus") || parts.includes("shift"),   // i18n-ok: combo canónico
    alt: parts.includes("alt"),
    key,
  };
}

const MOD_ALIASES: Record<string, "ctrl" | "shift" | "alt"> = {
  ctrl: "ctrl", cmd: "ctrl", control: "ctrl", "mayús": "shift", mayus: "shift", shift: "shift",   // i18n-ok: combo canónico
  alt: "alt", option: "alt",
};

/** La forma canónica de un atajo, como `normalize_combo` del backend: «Ctrl+Mayús+Alt+B»; `""`
 *  es sin atajo; null si no es un atajo (un modificador repetido o desconocido, o una tecla
 *  que no es una letra o una cifra). */
export function normalizeCombo(combo: unknown): string | null {
  if (typeof combo !== "string") return null;
  if (combo.trim() === "") return "";
  const parts = combo.split("+").map((p) => p.trim().toLowerCase());
  const key = parts.pop() ?? "";
  const seen = new Set<string>();
  for (const p of parts) {
    const m = MOD_ALIASES[p];
    if (!m || seen.has(m)) return null;
    seen.add(m);
  }
  if (!/^[a-z0-9]$/.test(key)) return null;
  return [seen.has("ctrl") && "Ctrl", seen.has("shift") && "Mayús", seen.has("alt") && "Alt", key.toUpperCase()]   // i18n-ok: combo canónico
    .filter(Boolean).join("+");
}

type KeyEv = { key?: string; code?: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean };

/** La tecla de una pulsación, en minúscula: las cifras por la tecla física (`code`, Digit0-9),
 *  porque con Mayús `key` es «!» o «"» según el teclado; las letras por `key` (la letra que
 *  pone el teclado), y por la tecla física solo si `key` no es una letra latina (Alt en Mac,
 *  un teclado cirílico), como hace Excalidraw. null si no es una letra ni una cifra. */
function eventKey(ev: KeyEv): string | null {
  const digit = /^Digit([0-9])$/.exec(ev.code ?? "");
  if (digit) return digit[1];
  const k = (ev.key ?? "").toLowerCase();
  if (/^[a-z]$/.test(k)) return k;
  const letter = /^Key([A-Z])$/.exec(ev.code ?? "");
  return letter ? letter[1].toLowerCase() : null;
}

/** ¿La pulsación es esa combinación? Exacta: Ctrl+B no salta con Ctrl+Mayús+B. Sin atajo
 *  (`""`) nunca salta. */
export function matches(ev: KeyEv, combo: string): boolean {
  if (!combo) return false;
  const c = parseCombo(combo);
  return (ev.ctrlKey || ev.metaKey) === c.ctrl && ev.shiftKey === c.shift && ev.altKey === c.alt
    && eventKey(ev) === c.key;
}

/** La combinación de una pulsación en forma canónica, para grabar un atajo; null si la tecla
 *  no es una letra ni una cifra (p. ej. solo un modificador, que llega antes que la letra). */
export function comboFromEvent(ev: KeyEv): string | null {
  const key = eventKey(ev);
  if (key === null) return null;
  return normalizeCombo([ev.ctrlKey || ev.metaKey ? "Ctrl" : "", ev.shiftKey ? "Mayús" : "",   // i18n-ok: combo canónico
                         ev.altKey ? "Alt" : "", key].filter(Boolean).join("+"));
}

/** Los atajos que valen, `{acción: combinación}` (`""` = sin atajo), a partir de los que cambió
 *  el usuario. Uno ilegible deja el de por defecto. Nunca dos acciones con el mismo: si uno
 *  del usuario coincide con el de por defecto de otra acción (un `settings.toml` editado a
 *  mano), manda el del usuario y la otra queda sin atajo; si dos del usuario coinciden (el
 *  backend ya no los da), las dos vuelven al de por defecto. */
export function effectiveShortcuts(user: unknown): Record<string, string> {
  const raw = (user && typeof user === "object" ? user : {}) as Record<string, unknown>;
  const mine: Record<string, string> = {};
  for (const s of SHORTCUTS) {
    const c = normalizeCombo(raw[s.id]);
    if (c !== null) mine[s.id] = c;
  }
  const count = new Map<string, number>();
  Object.values(mine).forEach((c) => c && count.set(c, (count.get(c) ?? 0) + 1));
  for (const [id, c] of Object.entries(mine)) if (c && count.get(c)! > 1) delete mine[id];
  const taken = new Set(Object.values(mine).filter(Boolean));
  const out: Record<string, string> = {};
  for (const s of SHORTCUTS) out[s.id] = s.id in mine ? mine[s.id] : taken.has(s.default) ? "" : s.default;
  return out;
}

// Los del usuario, de `/api/settings` (appSettings.ts los pone al llegar). Aquí y no leyendo
// el almacén: este módulo no tira de `auth` ni del backend (se usa en los tests tal cual).
let user: Record<string, string> = {};

export function setUserShortcuts(atajos: unknown) {
  user = (atajos && typeof atajos === "object" ? atajos : {}) as Record<string, string>;
}

/** La combinación de un atajo: la del usuario o la de por defecto; `""` si se quitó. */
export function shortcut(id: string): string {
  return effectiveShortcuts(user)[id] ?? "";
}

/** Una combinación canónica tal como se enseña, en el idioma de la interfaz («Mayús+1» es
 *  «Shift+1» en inglés). Lo guardado sigue en la forma canónica. */
export function comboLabel(combo: string): string {
  return combo.split("+").map((p) => (p === "Mayús" ? t("lienzo.tecla.mayus") : p)).join("+");   // i18n-ok: combo canónico
}

/** Con qué choca una combinación: otra acción de la app (con su id) o un atajo de Excalidraw.
 *  `nombre` es el de lo otro, ya traducido. */
export type Clash = { con: "app"; nombre: string; id: string } | { con: "excalidraw"; nombre: string };

/** Lo que pisa `combo` si se le da a `action` con los atajos del usuario `atajos`: primero
 *  otra acción de la app; si no, Excalidraw. Los de Excalidraw que ya atiende la propia app
 *  (encuadrar con Mayús+1, 2 y 3, fit.ts) no son choque para esa acción. */
export function clash(action: string, combo: string, atajos: unknown): Clash | null {
  const c = normalizeCombo(combo);
  if (!c) return null;
  const now = effectiveShortcuts(atajos);
  const other = SHORTCUTS.find((s) => s.id !== action && now[s.id] === c);
  if (other) return { con: "app", nombre: t(other.label), id: other.id };
  const ex = excalidrawClash(action, c);
  return ex ? { con: "excalidraw", nombre: ex } : null;
}

/** El atajo de Excalidraw que pierde su tecla si `action` usa `combo`, ya traducido; null si
 *  ninguno. */
export function excalidrawClash(action: string, combo: string): string | null {
  const hit = EXCALIDRAW_KEYS.find((k) => k.combo === combo && k.app !== action);
  return hit ? t(hit.name) : null;
}

/** Lo que se manda en `PUT /api/settings` (`atajos`) para dar `combo` a `action`: si choca con
 *  otra acción de la app, esa queda sin atajo en el mismo cambio (D97), y así nunca quedan dos
 *  con el mismo. */
export function assignChanges(action: string, combo: string, atajos: unknown): Record<string, string> {
  const c = normalizeCombo(combo) ?? "";
  const hit = c ? clash(action, c, atajos) : null;
  return hit?.con === "app" ? { [action]: c, [hit.id]: "" } : { [action]: c };
}

/** Campos donde no se escribe: tras pulsar una herramienta de la barra de Excalidraw (un
 *  `radio`), el foco se queda en ella y los atajos tienen que seguir siendo de la app (si no,
 *  Mayús+1 iba al encuadre de Excalidraw, R37, y una letra asignada a la herramienta). */
const NOT_TEXT = new Set(["radio", "checkbox", "button", "submit", "reset", "range", "color"]);

/** No se dispara un atajo mientras se escribe en un campo, un texto o un post-it, ni dentro de
 *  una ventana modal (Ajustes: el atajo que se está grabando no debe hacer lo que hace). */
export function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (el?.closest?.("textarea, select, [contenteditable=''], [contenteditable='true'], [aria-modal='true']"))
    return true;
  const input = el?.closest?.("input") as HTMLInputElement | null | undefined;
  return !!input && !NOT_TEXT.has((input.getAttribute?.("type") ?? "text").toLowerCase());
}
