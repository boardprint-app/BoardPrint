// Fuentes por tipo de texto (plan D54, D184): las de `settings.toml` (`[fuentes]`) como las
// variables CSS que usa la interfaz, puestas en <html> por Root. Siempre con respaldo: si la
// elegida no está en el equipo, la pila de siempre. «sistema» (y Excalifont en la pizarra) es
// la de siempre: la variable se quita y manda la de skins.css.

export type FontKind = "interfaz" | "pizarra" | "chat" | "numeros";

export const FONT_VARS: Record<FontKind, string> = {
  interfaz: "--f-ui", pizarra: "--f-board", chat: "--f-chat", numeros: "--f-num",
};

// Las pilas de skins.css: si cambian allí, aquí también.
const SYSTEM_STACK = 'system-ui, "Segoe UI", Roboto, sans-serif';
const BOARD_STACK = '"Segoe Print", "Comic Sans MS", cursive';

// El nombre CSS de cada fuente de la lista (pizarra/settings.py, FONT_CHOICES). Cascadia, en
// Windows, se instala como «Cascadia Code» o «Cascadia Mono»; «Cascadia» a secas es la que
// sirve Excalidraw (public/fonts), que vale de respaldo.
const FAMILY: Record<string, string> = {
  Arial: "Arial", Verdana: "Verdana", Georgia: "Georgia", Calibri: "Calibri", Consolas: "Consolas",
  Cascadia: '"Cascadia Code", "Cascadia Mono", Cascadia',
  Nunito: "Nunito", "Liberation Sans": '"Liberation Sans"', "Comic Shanns": '"Comic Shanns"',
};

/** El valor de cada variable para unas fuentes; null es «la de siempre» (se quita). */
export function fontVars(fuentes: Partial<Record<FontKind, string>> | null | undefined): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const kind of Object.keys(FONT_VARS) as FontKind[]) {
    const name = fuentes?.[kind];
    const family = name ? FAMILY[name] : undefined;
    out[FONT_VARS[kind]] = family ? `${family}, ${kind === "pizarra" ? BOARD_STACK : SYSTEM_STACK}` : null;
  }
  return out;
}

// `FONT_FAMILY` de Excalidraw 0.18 (excalidrawKeys.ts, EXCALIDRAW_VERSION): el id con que guarda
// la fuente de un texto. Copiado aquí para no cargar Excalidraw en los tests.
const BOARD_FONT_ID: Record<string, number> = {
  Cascadia: 3, Excalifont: 5, Nunito: 6, "Comic Shanns": 8, "Liberation Sans": 9,
};

/** La fuente de los textos nuevos de Excalidraw (`currentItemFontFamily`); Excalifont si no se
 *  conoce. Los textos ya dibujados no cambian (D184). */
export function boardFontId(name: string | null | undefined): number {
  return BOARD_FONT_ID[name ?? ""] ?? BOARD_FONT_ID.Excalifont;
}
