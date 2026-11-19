// Salidas en la tarjeta y enchufes (D96 1B, 3B): cada valor va a un sitio y solo a uno, un
// candado fija el valor que se ve, y un enchufe está siempre a la misma altura.
import { describe, expect, it } from "vitest";
import { alphaBox, columnLabel, groupLabel, numericCell, outputView, setLock, tableLayout, tableColumns, tableRows, toggleLock } from "./outputs";
import { HEAD_H, socketY } from "./ports";

const v = (value: unknown, extra = {}) => ({ value, unit: "", ...extra });

describe("reparto de las salidas", () => {
  const view = outputView({
    brazo: {
      arm_toml: v("arm.toml", { file: "arm.toml" }),
      iteraciones: v(3),
      OD_Brazo: v(80, { group: "tubos", lockable: true }),
      TW_Brazo: v(4, { group: "tubos", lockable: true, lock: true }),
      D_J1: v(95, { group: "alojamientos", lockable: true }),
      accionamientos: v([{ articulacion: "J1", accionamiento: "SW-17" }]),
    },
  });
  it("cada valor va a un solo sitio", () => {
    expect(view.files.map((f) => f.key)).toEqual(["arm_toml"]);
    expect(view.plain.map((f) => f.key)).toEqual(["iteraciones"]);
    expect(view.tables.map((f) => f.key)).toEqual(["accionamientos"]);
    expect(view.groups.map((g) => [g.name, g.fields.map((f) => f.key)])).toEqual([
      ["tubos", ["OD_Brazo", "TW_Brazo"]], ["alojamientos", ["D_J1"]]]);
  });
  it("lo de un control genérico (P52) no sale en Resultados: lo pinta su control", () => {
    const c = outputView({ voladizo: {
      flecha: v(0.4, { unit: "mm" }),
      elastica: v({ curves: [] }, { control: "chart" }),
      lado: v({ items: [] }, { control: "view2d" }),
      otra: v({ curves: [] }, { control: "chart", lockable: true, file: "x.png" }),
    } });
    expect([...c.plain, ...c.tables, ...c.files, ...c.groups.flatMap((g) => g.fields)].map((f) => f.key)).toEqual(["flecha"]);
    expect(c.lockable).toBe(false);
    expect(Object.fromEntries(Object.entries(c.controls).map(([k, fs]) => [k, fs.map((f) => f.key)])))
      .toEqual({ chart: ["elastica", "otra"], view2d: ["lado"] });
  });
  it("lo que ya enseña la tarjeta (hidden, T25) no sale en las salidas", () => {
    const t = outputView({ terminal: { vista: v({ cajas: [] }, { hidden: true }), cdg: v([0, 0, 9]), n: v(2, { hidden: true }) } });
    expect([...t.plain, ...t.tables].map((f) => f.key)).toEqual(["cdg"]);
  });
  it("sabe si hay candados", () => {
    expect(view.lockable).toBe(true);
    expect(outputView({ p: { a: v(1) } }).lockable).toBe(false);
  });
  it("un valor que va en varias salidas sale una sola vez", () => {
    const twice = outputView({ brazo: { OD: v(80, { group: "tubos" }) }, tubos: { OD: v(80, { group: "tubos" }) } });
    expect(twice.groups).toEqual([{ name: "tubos", fields: [{ ...v(80, { group: "tubos" }), key: "OD", port: "brazo" }] }]);
  });
  it("sin salidas, vacío", () => {
    expect(outputView(null)).toEqual({ plain: [], groups: [], tables: [], files: [], images: [], lockable: false, controls: {} });
  });
});

describe("candados", () => {
  it("poner un candado fija el valor de ahora y quitarlo lo suelta", () => {
    const on = toggleLock({}, "OD_Brazo", 80);
    expect(on).toEqual({ OD_Brazo: 80 });
    expect(toggleLock(on, "OD_Brazo", 90)).toEqual({});
  });
  it("nunca fija algo que no es un número", () => {
    expect(toggleLock({}, "x", "texto")).toEqual({});
    expect(toggleLock({}, "x", null)).toEqual({});
  });
  it("cambiar el valor fijado acepta coma decimal y rechaza lo que no es número", () => {
    expect(setLock({ a: 1 }, "a", "2,5")).toEqual({ a: 2.5 });
    expect(setLock({ a: 1 }, "a", "")).toBeNull();
    expect(setLock({ a: 1 }, "a", "abc")).toBeNull();
  });
});

describe("grupos", () => {
  it("los del detalle, por pieza e interfaz", () => {
    expect(groupLabel("pieza_L2")).toBe("Pieza: L2");
    expect(groupLabel("pieza_muneca")).toBe("Pieza: muñeca");
    expect(groupLabel("interfaz_J1")).toBe("Interfaz J1");
    expect(groupLabel("tubos")).toBe("Tubos");
  });
});

describe("tablas", () => {
  it("las columnas son las claves de las filas, sin repetir", () => {
    expect(tableColumns([{ a: 1, b: 2 }, { b: 3, c: 4 }])).toEqual(["a", "b", "c"]);
  });
  it("«cumple» va siempre la primera: el veredicto se ve aunque la tabla no quepa", () => {
    expect(tableColumns([{ a: 1, b: 2, cumple: true }])).toEqual(["cumple", "a", "b"]);
  });
  const rows = Array.from({ length: 20 }, (_, i) => ({ i, cumple: i % 5 === 0 ? false : i === 7 ? null : true }));
  it("una tabla larga con fallos enseña solo las filas que fallan, hasta pedirlas todas", () => {
    const shown = tableRows(rows, false);
    expect(shown.rows.map((r) => r.i)).toEqual([0, 5, 10, 15]);
    expect(shown).toMatchObject({ bad: 4, filtered: true });
    expect(tableRows(rows, true)).toMatchObject({ bad: 4, filtered: false });
    expect(tableRows(rows, true).rows).toHaveLength(20);
  });
  it("sin fallos, o con pocas filas, se enseñan todas", () => {
    expect(tableRows(rows.map((r) => ({ ...r, cumple: true })), false).rows).toHaveLength(20);
    expect(tableRows(rows.slice(0, 6), false)).toMatchObject({ bad: 2, filtered: false });
    expect(tableRows([{ a: 1 }, { a: 2 }], false)).toMatchObject({ bad: 0, filtered: false });
  });
});

describe("enchufes", () => {
  it("cada enchufe está a una altura fija desde arriba, crezca lo que crezca la tarjeta", () => {
    expect(socketY(1) - socketY(0)).toBe(socketY(2) - socketY(1));
  });
  it("el primero, a la altura de la cabecera: no ocupan sitio dentro de la tarjeta", () => {
    expect(socketY(0)).toBe(HEAD_H / 2);
  });
});

describe("miniatura de una captura (D114)", () => {
  const img = (w: number, h: number, on: [number, number][]) => {
    const d = new Uint8ClampedArray(w * h * 4);
    for (const [x, y] of on) d[(y * w + x) * 4 + 3] = 255;
    return d;
  };

  it("recorta a lo que se ve, con margen, sin salirse de la imagen", () => {
    expect(alphaBox(img(100, 50, [[40, 10], [59, 29]]), 100, 50, 0.1)).toEqual({ x: 38, y: 8, w: 24, h: 24 });
    expect(alphaBox(img(10, 10, [[0, 0], [9, 9]]), 10, 10, 0.5)).toEqual({ x: 0, y: 0, w: 10, h: 10 });
  });

  it("una imagen transparente entera no se recorta a nada", () => {
    expect(alphaBox(img(4, 4, []), 4, 4)).toBeNull();
  });

  it("una imagen de un bloque va también a Archivos", () => {
    const v = outputView({ m: { captura: { value: "c.png", unit: "", file: "c.png", image: true } } });
    expect(v.images.map((f) => f.key)).toEqual(["captura"]);
    expect(v.files.map((f) => f.key)).toEqual(["captura"]);
  });
});

describe("columnLabel", () => {
  it("las conocidas, con su nombre; las demás, de la clave con tilde y la unidad del sufijo", () => {
    expect(columnLabel("cumple")).toBe("Cumple");
    expect(columnLabel("analitica_kg")).toBe("Analítica (kg)");
    expect(columnLabel("desvio_pct")).toBe("Desvío (%)");
    expect(columnLabel("magnitud")).toBe("Magnitud");
    expect(columnLabel("cuando")).toBe("Cuándo");
    expect(columnLabel("masa_kg")).toBe("Masa (kg)");
    expect(columnLabel("kg")).toBe("Kg");                       // sin nombre delante no es sufijo
  });
});

describe("celdas de una tabla de salidas", () => {
  it("un texto largo que no nombra la fila va debajo de ella, no en una columna estrecha", () => {
    const rows = [
      { cumple: true, comprobacion: "J1: accionamiento (motor pico)", valor: 0.83, limite: "≤ 1,00", motivo: "—" },
      { cumple: false, comprobacion: "J2: tornillos de salida", valor: 131.7, limite: "≤ 614",
        motivo: "si desliza, la articulación pierde posición; más tornillos" },
    ];
    expect(tableLayout(rows, tableColumns(rows))).toEqual({
      inline: ["cumple", "comprobacion", "valor", "limite"], below: ["motivo"] });
    // un texto corto se queda en su columna
    const short = [{ pieza: "L2", material: "aluminio", cantidad: 2 }];
    expect(tableLayout(short, tableColumns(short))).toEqual({ inline: ["pieza", "material", "cantidad"], below: [] });
  });
  it("una cifra con su comparación nunca parte línea; un texto, sí", () => {
    for (const v of [0.8339, "≤ 1,00", "≥ 2", "12 %", "-3.5", "322,3773"]) expect(numericCell(v)).toBe(true);
    for (const v of ["J1: accionamiento (motor pico)", "—", "", null, true, "dato del usuario (Requisitos)"]) {
      expect(numericCell(v)).toBe(false);
    }
  });
});
