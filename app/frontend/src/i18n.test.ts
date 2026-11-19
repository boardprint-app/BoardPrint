// Idioma (plan D180, §10): toda clave que usa la interfaz existe en `es`, y una que falta
// enseña la clave, nunca un hueco.
import { describe, expect, it } from "vitest";
import { editNumber, fmtNumber, parseNumber, setLanguage, t } from "./i18n";
import { EN } from "./locales/en";
import { ES } from "./locales/es";

// el código de la interfaz como texto (Vite), sin los tests
const SOURCES = import.meta.glob(["./**/*.ts", "./**/*.tsx", "!./**/*.test.ts"],
                                 { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** Las líneas de un fuente sin sus comentarios (los de bloque dejan sus saltos de línea, así
 *  que la línea n sigue siendo la n). Lo que queda con una letra del español es texto que ve el
 *  usuario o un nombre: los dos van al catálogo. */
function sinComentarios(text: string): string[] {
  return text.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ""))
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1").split("\n");
}

describe("inglés (PLAN_PUBLICACION O11, §6)", () => {
  it("en.ts tiene todas las claves de es.ts y ninguna más", () => {
    const sobran = Object.keys(EN).filter((k) => !(k in ES));
    const faltan = Object.keys(ES).filter((k) => !(k in EN));
    expect({ faltan, sobran }).toEqual({ faltan: [], sobran: [] });
  });

  it("ningún fuente de la interfaz tiene texto en español fuera del catálogo", () => {
    // una línea que de verdad lo necesita (un nombre propio, un dato) lleva `i18n-ok`
    const hallados: string[] = [];
    for (const [path, text] of Object.entries(SOURCES)) {
      if (path.startsWith("./locales/")) continue;
      const original = text.split("\n");
      sinComentarios(text).forEach((line, i) => {
        if (/[áéíóúñÁÉÍÓÚÑ¿¡]/.test(line) && !original[i].includes("i18n-ok")) hallados.push(`${path}:${i + 1}`);
      });
    }
    expect(hallados).toEqual([]);
  });

  it("en inglés da el texto inglés, y una clave sin traducir da el español, nunca un hueco", () => {
    ES["prueba.solo_es"] = "Solo en español";
    try {
      setLanguage("en");
      expect(t("ajustes.cancelar")).toBe(EN["ajustes.cancelar"]);
      expect(t("prueba.solo_es")).toBe("Solo en español");
      setLanguage("klingon");
      expect(t("ajustes.cancelar")).toBe(ES["ajustes.cancelar"]);
    } finally {
      delete ES["prueba.solo_es"];
      setLanguage("es");
    }
  });
});

describe("claves de traducción", () => {
  it("toda clave que usa el código existe en es", () => {
    const used = new Set<string>();
    for (const text of Object.values(SOURCES)) {
      if (!/from "(\.\.?\/)+i18n"/.test(text)) continue;     // solo los que usan el t() de i18n
      for (const m of text.matchAll(/\bt\(\s*"([a-z0-9_.]+)"/g)) used.add(m[1]);
    }
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);     // el recorrido lee el código
    const missing = [...used].filter((k) => !(k in ES));
    expect(missing).toEqual([]);
  });

  it("una clave que falta enseña la clave, nunca un hueco", () => {
    expect(t("no.existe.nunca")).toBe("no.existe.nunca");
  });

  it("sustituye las variables y deja las que faltan", () => {
    expect(t("unidades.masa")).toBe("Masa");
    ES["prueba.vars"] = "{a} de {b}";
    expect(t("prueba.vars", { a: 3 })).toBe("3 de {b}");
    delete ES["prueba.vars"];
  });
});

describe("números en el idioma de la interfaz (O17)", () => {
  it("coma decimal en español y punto en inglés, en todo lo que se enseña", () => {
    setLanguage("es");
    expect(fmtNumber(0.6)).toBe("0,6");
    expect(fmtNumber(53.3)).toBe("53,3");
    setLanguage("en");
    expect(fmtNumber(0.6)).toBe("0.6");
    expect(fmtNumber(53.3)).toBe("53.3");
    setLanguage("es");
  });
  it("con las cifras que importan: cuatro significativas sin redondear la parte entera", () => {
    expect(fmtNumber(322.3773, { lang: "es" })).toBe("322,4");
    expect(fmtNumber(0.83391, { lang: "es" })).toBe("0,8339");
    expect(fmtNumber(19.86, { lang: "es" })).toBe("19,86");
    expect(fmtNumber(132, { lang: "es" })).toBe("132");
    expect(fmtNumber(12345.6, { lang: "en" })).toBe("12,346");
    expect(fmtNumber(0, { lang: "es" })).toBe("0");
  });
  it("un campo en pulgadas nunca enseña diez decimales, y lo escrito se lee con coma o punto", () => {
    expect(editNumber(600 / 25.4, "es")).toBe("23,622");
    expect(editNumber(600 / 25.4, "en")).toBe("23.622");
    expect(editNumber(12345.5, "es")).toBe("12345,5");      // sin separador de miles al editar
    expect(parseNumber("23,622")).toBe(23.622);
    expect(parseNumber(" 0.1 ")).toBe(0.1);
    expect(parseNumber("abc")).toBeNull();
    expect(parseNumber("")).toBeNull();
  });
});
