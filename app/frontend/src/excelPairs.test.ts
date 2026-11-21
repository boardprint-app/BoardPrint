// La flecha de enlace de una tarjeta de Excel a un bloque (docs/PLAN_EXCEL.md §3.6, R5): es la
// vista de `links` (una por pareja tarjeta-bloque, con cuántos enlaces), su menú solo ofrece
// parejas nombre → parámetro que casan en unidad, borrarla quita todos los de la pareja, y no
// es un elemento de la escena (no entra en el orden de ejecución). También el ancho del
// desplegable de un parámetro de lista (que no se corte).
import { describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import type { ExcelName, ParamLink } from "./excel";
import type { ParamSpec } from "./store";
import { dropOnBlock, linkPairs, linkRows, pairBody, pairLabel } from "./excelPairs";
import { choiceWidth } from "./block";

const name = (nombre: string, extra: Partial<ExcelName> = {}): ExcelName => ({
  nombre, hoja: "Datos", celda: "B3", where: "Datos!B3", valor: 1, formula: null,
  unidad: (/_(mm|cm|m|kg|g|N|kN|Nm|deg|s)$/.exec(nombre)?.[1]) ?? "", problema: null, motivo: null, ...extra,
});
const link = (card: string, nm: string): ParamLink => ({
  card, name: nm, where: "Datos!B3", unit: "", value: 1, reason: null, source: null,
});
const spec = (d: unknown, unit = "", extra: Partial<ParamSpec> = {}): ParamSpec =>
  ({ default: d, unit, label: "", choices: [], ...extra });

describe("la flecha es la vista de los enlaces", () => {
  it("una por pareja tarjeta-bloque, con cuántos enlaces", () => {
    const blocks = {
      tubo: { links: { L: link("xl", "L_m"), od: link("xl", "od_mm"), t: link("otro", "t_mm") } },
      viga: { links: { F: link("xl", "F_kN") } },
      nada: { links: null },
      suelto: {},
    };
    expect(linkPairs(blocks)).toEqual([
      { card: "otro", block: "tubo", params: ["t"] },
      { card: "xl", block: "tubo", params: ["L", "od"] },
      { card: "xl", block: "viga", params: ["F"] },
    ]);
  });

  it("enlazar la añade y quitar el último enlace la quita", () => {
    const one = { tubo: { links: { L: link("xl", "L_m") } } };
    expect(linkPairs(one)).toHaveLength(1);
    const two = { tubo: { links: { ...one.tubo.links, od: link("xl", "od_mm") } } };
    expect(linkPairs(two)).toEqual([{ card: "xl", block: "tubo", params: ["L", "od"] }]);
    expect(linkPairs({ tubo: { links: {} } })).toEqual([]);
  });

  it("la etiqueta dice cuántos", () => {
    setLanguage("es");
    expect(pairLabel(1)).toBe("1 enlace");
    expect(pairLabel(3)).toBe("3 enlaces");
    setLanguage("en");
    expect(pairLabel(1)).toBe("1 link");
    expect(pairLabel(3)).toBe("3 links");
    setLanguage("es");
  });
});

describe("el menú de enlace", () => {
  const params = {
    material: spec("al6061", "", { choices: ["al6061", "s355"], label: "Material" }),
    od: spec(40, "mm", { label: "Ø exterior" }),
    L: spec(300, "mm", { label: "Largo" }),
    F: spec(200, "N", { label: "Carga" }),
    pasos: spec(3, "", { label: "Pasos" }),
    destino: spec("", "", { widget: "otro.control" }),
    fijados: spec({}, ""),
  };
  const names = [name("L_m"), name("od_mm"), name("masa_kg"), name("rango_mm", { problema: "varias_celdas", valor: null }),
                 name("material", { valor: "s355" }), name("calc_mm", { problema: "calculando", valor: null })];

  it("solo ofrece las parejas que casan en unidad, nunca lo que no se admite", () => {
    const rows = linkRows(params, null, "xl", names);
    const offered = Object.fromEntries(rows.map((r) => [r.param, r.options.map((n) => n.nombre)]));
    expect(offered).toEqual({
      material: ["material"],
      od: ["L_m", "od_mm", "calc_mm"],
      L: ["L_m", "od_mm", "calc_mm"],
    });
    // ni la carga (nada en N), ni un número sin unidad, ni un control ni un objeto
    expect(rows.map((r) => r.param)).not.toContain("F");
    expect(rows.map((r) => r.param)).not.toContain("destino");
  });

  it("enseña lo ya enlazado: de esta tarjeta como elegido, de otra aparte", () => {
    const rows = linkRows(params, { L: link("xl", "L_m"), od: link("otro", "od_mm") }, "xl", names);
    const L = rows.find((r) => r.param === "L")!, od = rows.find((r) => r.param === "od")!;
    expect([L.current, L.other]).toEqual(["L_m", null]);
    expect([od.current, od.other]).toEqual([null, "otro"]);
  });

  it("Enlazar manda lo elegido; lo vacío o lo que no se ofrece, no", () => {
    const rows = linkRows(params, { L: link("xl", "L_m") }, "xl", names);
    expect(pairBody(rows, { L: "L_m", od: "od_mm", material: "" })).toEqual({ L: "L_m", od: "od_mm" });
    expect(pairBody(rows, { od: "masa_kg" })).toEqual({});
    expect(pairBody(rows, {})).toEqual({});
  });
});

describe("soltar del Excel en un bloque", () => {
  it("con una entrada que acepta el archivo, conexión; si no, el menú de enlace", () => {
    expect(dropOnBlock(true, 1)).toBe("connect");
    expect(dropOnBlock(true, 2)).toBe("inputs");
    expect(dropOnBlock(true, 0)).toBe("link");
    expect(dropOnBlock(false, 0)).toBe("none");       // otro archivo: como hasta ahora
  });
});

describe("el desplegable de un parámetro de lista no se corta", () => {
  it("se ensancha hasta el texto más largo, con tope", () => {
    expect(choiceWidth(["sí", "no"])).toBeNull();                       // cabe en el campo de siempre
    expect(choiceWidth(["Aluminum 6061-T6", "Steel S355"])).toBe(20);   // 16 + flecha
    expect(choiceWidth(["x".repeat(60)])).toBe(26);                     // con tope: lo demás, al pasar el ratón
    expect(choiceWidth([])).toBeNull();
  });
});
