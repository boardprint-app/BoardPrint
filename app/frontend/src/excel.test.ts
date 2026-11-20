// El Excel como datos en la interfaz (docs/PLAN_EXCEL.md §3.5, §4): *Tomar de Excel* solo
// ofrece nombres que casan en unidad y nunca lo que no se admite (X3, X4), y un parámetro
// enlazado no se edita a mano (R1).
import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { candidates, compatible, hasExcel, nameState, offers, unitProblem, type ExcelName } from "./excel";
import { setStore, getStore, type BlockState, type BlockType } from "./store";

// Sin DOM: el store y los ajustes se leen directamente (useSyncExternalStore pide en el
// servidor una instantánea que la app no da).
vi.mock("./store", async (orig) => {
  const m = await orig<typeof import("./store")>();
  return { ...m, useStore: () => m.getStore() };
});
vi.mock("./appSettings", async (orig) => {
  const m = await orig<typeof import("./appSettings")>();
  const { SI } = await import("./units");
  return { ...m, useUnits: () => SI };
});

const name = (nombre: string, extra: Partial<ExcelName> = {}): ExcelName => ({
  nombre, hoja: "Datos", celda: "B3", where: "Datos!B3", valor: 1, formula: null,
  unidad: (/_(mm|cm|m|kg|g|N|Nm|deg|s)$/.exec(nombre)?.[1]) ?? "", problema: null, motivo: null, ...extra,
});

describe("unidades del Excel (X4, las de excel_names.check_unit)", () => {
  it("casa la misma magnitud y niega lo demás con su motivo", () => {
    expect(compatible("m", "mm")).toBe(true);
    expect(compatible("Nm", "N·m")).toBe(true);
    expect(compatible("deg", "°")).toBe(true);
    expect(unitProblem("kg", "mm")).toBe("otra_magnitud");
    expect(unitProblem("", "mm")).toBe("sin_sufijo");
    expect(unitProblem("mm", "")).toBe("con_sufijo_sin_unidad");
    expect(unitProblem("mm", "furlong")).toBe("unidad_desconocida");
    expect(unitProblem("", "")).toBeNull();
  });
});

describe("Tomar de Excel solo ofrece lo que casa", () => {
  const sources = {
    hoja: { name: "datos.xlsx", names: [
      name("L_up_m", { valor: 0.3 }), name("masa_kg", { valor: 2 }), name("sin_unidad", { valor: 5 }),
      name("rango_mm", { valor: null, problema: "varias_celdas", where: null }),
      name("k_mm", { valor: null, problema: "constante", where: null }),
      name("roto_mm", { valor: null, problema: "ref_rota", where: null }),
      name("fx_mm", { valor: null, problema: "sin_valor", formula: "=B3*2" }),
      name("texto_mm", { valor: "abc" }),
    ] },
    otro: { name: "otro.xlsx", names: [name("masa_g", { valor: 300 })] },
    carpeta: { names: null },
  };

  it("un parámetro en mm: solo los nombres de longitud, y nunca lo no admitido", () => {
    const got = candidates(sources, { unit: "mm", kind: "number" });
    expect(got.map((g) => [g.card, g.cardName, g.names.map((n) => n.nombre)]))
      .toEqual([["hoja", "datos.xlsx", ["L_up_m", "fx_mm"]]]);
  });

  it("un parámetro en kg: los de masa de todas las tarjetas", () => {
    expect(candidates(sources, { unit: "kg", kind: "number" }).flatMap((g) => g.names.map((n) => n.nombre)))
      .toEqual(["masa_kg", "masa_g"]);
  });

  it("sin unidad, solo lo que no lleva sufijo; un texto, solo a un texto de su lista", () => {
    expect(candidates(sources, { unit: "", kind: "number" }).flatMap((g) => g.names.map((n) => n.nombre)))
      .toEqual(["sin_unidad"]);
    expect(offers(name("modo", { valor: "rapido" }), { unit: "", kind: "text", choices: ["rapido", "lento"] })).toBe(true);
    expect(offers(name("modo", { valor: "otro" }), { unit: "", kind: "text", choices: ["rapido", "lento"] })).toBe(false);
    expect(offers(name("modo", { valor: 3 }), { unit: "", kind: "text", choices: [] })).toBe(false);
  });

  it("calculando o sin valor se ofrece (R1); lo de X3, nunca", () => {
    expect(offers(name("fx_mm", { valor: null, problema: "calculando" }), { unit: "mm", kind: "number" })).toBe(true);
    for (const p of ["varias_celdas", "constante", "no_es_celda", "ref_rota"])
      expect(offers(name("x_mm", { valor: null, problema: p }), { unit: "mm", kind: "number" })).toBe(false);
  });

  it("el estado de cada nombre en la tarjeta", () => {
    expect(nameState(name("a_mm"))).toBe("ok");
    expect(nameState(name("a_mm", { valor: null, problema: "varias_celdas" }))).toBe("no_admitido");
    expect(nameState(name("a_mm", { valor: null, problema: "calculando" }))).toBe("calculando");
    expect(nameState(name("a_mm", { valor: null, problema: "vacia" }))).toBe("sin_valor");
    expect(hasExcel({ c: { names: null } })).toBe(false);
    expect(hasExcel({ c: { names: [] } })).toBe(true);
  });
});

describe("un parámetro enlazado no se edita a mano (R1)", () => {
  const ty = {
    title: "Tubo", pack: "prueba", inputs: {}, outputs: {}, requires: [],
    params: {
      largo: { default: 100, unit: "mm", label: "Largo", choices: [] },
      ancho: { default: 20, unit: "mm", label: "Ancho", choices: [] },
    },
  } as unknown as BlockType;
  const st = {
    type: "prueba.tubo", status: "al_dia", params: { largo: 300, ancho: 20 }, outputs: null, error: null,
    inputs: {},
    links: { largo: { card: "hoja", name: "L_up_m", where: "Datos!B3", unit: "m", value: 300, reason: null,
                      source: { kind: "archivo", ref: "archivo:hoja", where: "Datos!B3" } } },
  } as BlockState;

  it("el enlazado enseña su valor con candado, la celda y Quitar enlace, sin campo", async () => {
    vi.stubGlobal("location", new URL("http://127.0.0.1/"));     // auth.ts lee la URL al cargar
    const before = getStore().sources;
    setStore({ sources: { hoja: { name: "datos.xlsx", names: [name("L_up_m", { valor: 0.3 })] } as never } });
    try {
      const { BlockParams } = await import("./BlockParams");
      const html = renderToStaticMarkup(createElement(BlockParams, {
        id: "b1", ty, st, params: st.params!, setDraft: () => undefined, commit: () => undefined,
      }));
      const row = (p: string) => {
        const at = html.indexOf(`data-param="${p}"`);
        const next = html.indexOf("data-param=", at + 1);
        return html.slice(at, next < 0 ? undefined : next);
      };
      expect(row("largo")).not.toMatch(/<input|<select/);
      expect(row("largo")).toContain("Datos!B3");
      expect(row("largo")).toContain("datos.xlsx");
      expect(row("largo")).toContain("300");
      expect(row("largo")).toContain("bp-unlink");
      // el otro sigue editándose, con su Tomar de Excel
      expect(row("ancho")).toMatch(/<input/);
      expect(row("ancho")).toContain("xl-take");
      // sin valor del Excel, el que quedó en el parámetro no se enseña como suyo (X5)
      const bad = { ...st, links: { largo: { ...st.links!.largo, where: null, value: 300, reason: "falta" } } };
      const html2 = renderToStaticMarkup(createElement(BlockParams, {
        id: "b1", ty, st: bad, params: st.params!, setDraft: () => undefined, commit: () => undefined,
      }));
      expect(html2).not.toMatch(/bp-lockval[^>]*>.*?300/);
      expect(html2).toContain("Datos!B3");          // la celda, de la tarjeta
    } finally {
      setStore({ sources: before });
      vi.unstubAllGlobals();
    }
  });
});
