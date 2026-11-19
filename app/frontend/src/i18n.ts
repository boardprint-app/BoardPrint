// Textos de la interfaz por clave (plan D41, D180, PLAN_PUBLICACION O11). `t("ajustes.titulo")`
// da el texto en el idioma de la app (`settings.toml`, `idioma`: «es» o «en»; sin ajuste, el del
// sistema), con `{var}` sustituidas. Una clave que falta en inglés enseña el texto en español, y
// una que falta en los dos, la propia clave: nunca un hueco. `t()` se llama al pintar, nunca al
// cargar un módulo: el idioma llega con los ajustes, después.
import { EN } from "./locales/en";
import { ES } from "./locales/es";

export type Lang = "es" | "en";
const CATALOGS: Record<Lang, Record<string, string>> = { es: ES, en: EN };
let lang: Lang = "es";

/** Los nombres de cada idioma en su propio idioma (el selector no los traduce). */
export const LANGUAGE_NAMES: Record<string, string> = { es: "Español", en: "English" };  // i18n-ok

export function setLanguage(l: string) {
  lang = (l in CATALOGS ? l : "es") as Lang;
  // El `lang` de la página (corrector, separación de palabras y lectores de pantalla).
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

export function getLanguage(): Lang {
  return lang;
}

export function t(key: string, vars?: Record<string, string | number>): string {
  const text = CATALOGS[lang][key] ?? ES[key];
  if (text === undefined) {
    if (import.meta.env?.DEV) console.warn(`[i18n] falta la clave ${key}`);
    return key;
  }
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, name: string) => (name in vars ? String(vars[name]) : m));
}

// ------------------------------------------------------------------ números (O17)
/** La configuración regional de los números: coma decimal en español, punto en inglés. */
export const numLocale = (l: Lang = lang) => (l === "en" ? "en-US" : "es-ES");

/** Un número para leer, en el formato del idioma y con las cifras que importan: `sig` cifras
 *  significativas sin redondear nunca la parte entera (322,3773 → 322,4; 0,83391 → 0,8339;
 *  12345,6 → 12.346) y como mucho `max` decimales. */
export function fmtNumber(v: number, opts: { sig?: number; max?: number; group?: boolean; lang?: Lang } = {}): string {
  const { sig = 4, max = 4, group = true } = opts;
  if (!Number.isFinite(v)) return String(v);
  const a = Math.abs(v);
  const int = a >= 1 ? Math.floor(Math.log10(a)) + 1 : 0;
  // miles agrupados desde 5 cifras (1844, 12.346), como manda la RAE y hace el inglés con «min2»
  // (`min2` es de Intl.NumberFormat v3: el `lib` de TypeScript aún no lo trae)
  const o = { useGrouping: group ? "min2" : false } as unknown as Intl.NumberFormatOptions;
  if (a !== 0 && a < 1) Object.assign(o, { maximumSignificantDigits: sig });
  else o.maximumFractionDigits = Math.max(0, Math.min(max, sig - int));
  return v.toLocaleString(numLocale(opts.lang), o);
}

/** Lo que va en un campo numérico al editarlo: más cifras que al leer (6 significativas), sin
 *  separador de miles y con la coma decimal en español. Se vuelve a leer con `parseNumber`. */
export const editNumber = (v: number, l: Lang = lang) => fmtNumber(v, { sig: 6, max: 6, group: false, lang: l });

/** Lo escrito en un campo numérico: admite coma o punto decimal. `null` si no es un número. */
export function parseNumber(text: string): number | null {
  const raw = text.trim().replace(/\s/g, "");
  if (!raw) return null;
  const n = Number(raw.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}
