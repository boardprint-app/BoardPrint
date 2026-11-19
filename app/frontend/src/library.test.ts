// La *Librería* en la interfaz (docs/PLAN_V020.md §5, §7, V16; D33): una cantidad vacía es
// «desconocida», no 0; solo se manda el stock que ha cambiado; un mapeo sin `key` no pide
// resumen, y solo se escriben las filas que crean o actualizan algo. Campos por tipo
// (PLAN_LIBRERIA L4): el selector sigue el orden del esquema, se avisa de los obligatorios que
// ninguna columna llena, y una unidad «-» (sin dimensión) o vacía (texto) no se pinta.
import { describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import {
  buildMapping, canApply, draftOf, editQuantity, filterItems, guessMapping, mappingTargets,
  missingRequired, NEW_FIELD, newRowDrafts, originText, parseQuantity, resolveChoices, showQuantity,
  shownUnit, stockChanges, validFichaKey, writtenRows,
  type FieldInfo, type ImportPlan, type LibraryItem, type NewStockRow, type StockEntry,
} from "./library";

const entry = (cantidad: number | null, extra: Partial<StockEntry> = {}): StockEntry =>
  ({ cantidad, ubicacion: "", fecha: "", nota: "", ...extra });

describe("cantidad del stock (D33)", () => {
  it("una cantidad vacía es desconocida, nunca 0", () => {
    expect(parseQuantity("")).toEqual({ ok: true, value: null });
    expect(parseQuantity("   ")).toEqual({ ok: true, value: null });
    expect(parseQuantity("0")).toEqual({ ok: true, value: 0 });
    expect(showQuantity(null)).toBe("—");
    expect(showQuantity(0)).toBe("0");
    expect(editQuantity(null)).toBe("");
    expect(editQuantity(0)).toBe("0");
  });

  it("se lee con coma o punto decimal, y lo que no es una cantidad ≥ 0 no vale", () => {
    expect(parseQuantity("2,5")).toEqual({ ok: true, value: 2.5 });
    expect(parseQuantity(" 1.5 ")).toEqual({ ok: true, value: 1.5 });
    expect(parseQuantity("12")).toEqual({ ok: true, value: 12 });
    for (const bad of ["-1", "abc", "1,2,3", ",", "1e3", "3 uds"]) expect(parseQuantity(bad)).toEqual({ ok: false });
  });

  it("se enseña en el idioma de la interfaz", () => {
    setLanguage("es");
    expect(showQuantity(2.5)).toBe("2,5");
    expect(editQuantity(2.5)).toBe("2,5");
    setLanguage("en");
    expect(showQuantity(2.5)).toBe("2.5");
    setLanguage("es");
  });
});

describe("guardar el stock: solo las claves que han cambiado", () => {
  const saved = { a: entry(3, { ubicacion: "C1" }), b: entry(null) };

  it("una celda tocada y dejada como estaba no se manda", () => {
    const got = stockChanges(saved, { a: draftOf(saved.a), b: { ...draftOf(saved.b), ubicacion: " " } });
    expect(got).toEqual({ changes: {}, errors: {} });
  });

  it("solo va la clave cambiada, con la cantidad leída y vaciar la cantidad la deja desconocida", () => {
    const got = stockChanges(saved, { a: { ...draftOf(saved.a), cantidad: "" }, b: draftOf(saved.b) });
    expect(got.changes).toEqual({ a: entry(null, { ubicacion: "C1" }) });
    expect(stockChanges(saved, { b: { ...draftOf(saved.b), cantidad: "4,5" } }).changes)
      .toEqual({ b: entry(4.5) });
  });

  it("quitar del stock manda null, y solo si la clave tenía stock", () => {
    expect(stockChanges(saved, { a: null, nueva: null }).changes).toEqual({ a: null });
  });

  it("una clave sin stock con todo vacío no crea una entrada vacía; con algo escrito, sí", () => {
    expect(stockChanges(saved, { c: draftOf(null) }).changes).toEqual({});
    expect(stockChanges(saved, { c: { ...draftOf(null), ubicacion: "Cajón 2" } }).changes)
      .toEqual({ c: entry(null, { ubicacion: "Cajón 2" }) });
    expect(stockChanges(saved, { c: { ...draftOf(null), cantidad: "0" } }).changes).toEqual({ c: entry(0) });
  });

  it("una cantidad mala es un error de su clave y no se manda", () => {
    const got = stockChanges(saved, { a: { ...draftOf(saved.a), cantidad: "-2" }, b: { ...draftOf(saved.b), cantidad: "1" } });
    expect(Object.keys(got.errors)).toEqual(["a"]);
    expect(got.changes).toEqual({ b: entry(1) });
  });
});

describe("stock a una clave nueva (PLAN_LIBRERIA L2)", () => {
  const saved = { a: entry(3), "SHG-20": entry(null) };
  const taken = Object.keys(saved);
  let id = 0;
  const row = (key: string, extra: Partial<NewStockRow> = {}): NewStockRow =>
    ({ id: ++id, key, ...draftOf(null), ...extra });
  // Lo que se manda con las filas nuevas, como lo junta el diálogo.
  const send = (rows: NewStockRow[]) => {
    const fresh = newRowDrafts(rows, taken);
    return { ...stockChanges(saved, fresh.drafts, new Set(Object.keys(fresh.drafts))), rowErrors: fresh.errors };
  };

  it("una fila añadida entra en stockChanges aunque la clave no esté en la tabla", () => {
    expect(send([row(" HD-17 ", { cantidad: "2", ubicacion: "C3" })]).changes)
      .toEqual({ "HD-17": entry(2, { ubicacion: "C3" }) });
  });

  it("apuntar solo la clave ya es el cambio: va con la cantidad desconocida", () => {
    expect(send([row("m3x10")]).changes).toEqual({ m3x10: entry(null) });
  });

  it("una clave que ya está en la tabla nunca se envía, tampoco con otras mayúsculas", () => {
    for (const k of ["a", "shg-20"]) {
      const got = send([row(k, { cantidad: "5" })]);
      expect(got.changes).toEqual({});
      expect(Object.keys(got.rowErrors)).toHaveLength(1);
    }
  });

  it("una clave en dos filas nuevas no va por ninguna, y las dos quedan marcadas", () => {
    const rows = [row("X-1", { cantidad: "1" }), row("x-1", { cantidad: "2" }), row("Y-1")];
    const got = send(rows);
    expect(got.changes).toEqual({ "Y-1": entry(null) });
    expect(Object.keys(got.rowErrors).map(Number)).toEqual([rows[0].id, rows[1].id]);
  });

  it("una clave que no vale nunca se envía", () => {
    for (const k of ["con", "COM1.x", ".a", "a.", "a b", "ñu", "a/b", "-a", "x".repeat(101)]) {
      expect(validFichaKey(k)).toBe(false);
      const got = send([row(k, { cantidad: "1" })]);
      expect(got.changes).toEqual({});
      expect(Object.keys(got.rowErrors)).toHaveLength(1);
    }
    for (const k of ["SHG-20-100-2UH", "m3x10", "a.b_c+d", "CONSOLA", "x".repeat(100)]) expect(validFichaKey(k)).toBe(true);
  });

  it("una fila en blanco no cuenta; con stock y sin clave, es un error", () => {
    expect(send([row("  ")])).toEqual({ changes: {}, errors: {}, rowErrors: {} });
    const r = row("", { nota: "pedir" });
    expect(Object.keys(send([r]).rowErrors)).toEqual([String(r.id)]);
  });

  it("una cantidad mala en una fila nueva es un error de su clave y no se manda", () => {
    const got = send([row("HD-17", { cantidad: "-1" })]);
    expect(got.changes).toEqual({});
    expect(Object.keys(got.errors)).toEqual(["HD-17"]);
  });
});

describe("mapeo de columnas al importar (V16)", () => {
  it("un mapeo sin key no se puede pedir", () => {
    const got = buildMapping({ Cant: "cantidad", Sitio: "ubicacion" }, "");
    expect(got.ok).toBe(false);
  });

  it("las columnas sin destino no van y un destino en dos columnas no vale", () => {
    expect(buildMapping({ Ref: "key", Cant: "cantidad", Otra: "" }, ""))
      .toEqual({ ok: true, mapping: { Ref: "key", Cant: "cantidad" }, needsType: false });
    expect(buildMapping({ Ref: "key", A: "cantidad", B: "cantidad" }, "").ok).toBe(false);
  });

  it("con campos de ficha hace falta el tipo; solo stock, no", () => {
    expect(buildMapping({ Ref: "key", Rel: "values.ratio" }, "").ok).toBe(false);
    expect(buildMapping({ Ref: "key", Rel: "values.ratio" }, "gearbox"))
      .toEqual({ ok: true, mapping: { Ref: "key", Rel: "values.ratio" }, needsType: true });
    expect(buildMapping({ Ref: "key", Marca: "manufacturer" }, " ").ok).toBe(false);
  });

  it("sin tipo solo se ofrecen la clave y el stock; con tipo, también la ficha y sus campos", () => {
    expect(mappingTargets(["ratio"], false)).toEqual(["key", "cantidad", "ubicacion", "fecha", "nota"]);
    expect(mappingTargets(["ratio"], true)).toContain("values.ratio");
    expect(mappingTargets(["ratio"], true)).toContain("manufacturer");
  });

  it("un campo nuevo va como values.<nombre>, y con un nombre que no vale no se manda", () => {
    expect(resolveChoices({ Ref: "key", Par: NEW_FIELD }, { Par: " par_max " }))
      .toEqual({ ok: true, choices: { Ref: "key", Par: "values.par_max" } });
    expect(resolveChoices({ Par: NEW_FIELD }, { Par: "par máx" }).ok).toBe(false);
    expect(resolveChoices({ Par: NEW_FIELD }, {}).ok).toBe(false);
    expect(resolveChoices({ Par: NEW_FIELD }, { Par: "2x" }).ok).toBe(false);
  });

  it("el primer mapeo adivina por el nombre de la columna, sin repetir destino", () => {
    const targets = mappingTargets(["ratio"], true);
    expect(guessMapping(["Clave", "Cantidad", "Ubicación", "Ratio", "Otra", "KEY"], targets))
      .toEqual({ Clave: "key", Cantidad: "cantidad", "Ubicación": "ubicacion", Ratio: "values.ratio", Otra: "", KEY: "" });
  });
});

const field = (nombre: string, extra: Partial<FieldInfo> = {}): FieldInfo => ({
  nombre, unidad: "", descripcion: "", obligatorio: false, min: null, max: null,
  declarado: true, paquete: "pk", ...extra,
});

describe("campos por tipo (PLAN_LIBRERIA L4)", () => {
  const fields = [field("ratio", { unidad: "-", obligatorio: true }), field("T_rated", { unidad: "Nm", obligatorio: true }),
                  field("mass", { unidad: "kg" }), field("color", { declarado: false, paquete: null, obligatorio: true })];

  it("el selector ofrece los campos en el orden del esquema, no por nombre", () => {
    const targets = mappingTargets(fields.map((f) => f.nombre), true).filter((x) => x.startsWith("values."));
    expect(targets).toEqual(["values.ratio", "values.T_rated", "values.mass", "values.color"]);
  });

  it("avisa de los obligatorios declarados que ninguna columna llena", () => {
    expect(missingRequired(fields, {}).map((f) => f.nombre)).toEqual(["ratio", "T_rated"]);
    expect(missingRequired(fields, { "Relación": "values.ratio", "Marca": "" }).map((f) => f.nombre)).toEqual(["T_rated"]);
    expect(missingRequired(fields, { A: "values.ratio", B: "values.T_rated" })).toEqual([]);
  });

  it("un campo nuevo con el nombre de un obligatorio también lo llena", () => {
    const r = resolveChoices({ Par: NEW_FIELD }, { Par: "T_rated" });
    expect(r.ok && missingRequired(fields, r.choices).map((f) => f.nombre)).toEqual(["ratio"]);
  });

  it("lo que nadie declara nunca es obligatorio", () => {
    expect(missingRequired([field("color", { declarado: false, obligatorio: true })], {})).toEqual([]);
  });

  it("sin dimensión («-») o texto («») no se pinta unidad", () => {
    expect([shownUnit("-"), shownUnit(""), shownUnit(null), shownUnit(" Nm "), shownUnit("x10-4 kgm2")])
      .toEqual(["", "", "", "Nm", "x10-4 kgm2"]);
  });
});

describe("qué escribe Importar", () => {
  const plan = (rows: ImportPlan["rows"], writes = { fichas: 0, stock: 1 }): ImportPlan => ({
    token: "t", file: "s.csv", sheet: "", type: "", mapping: { k: "key" }, rows,
    counts: { create: 0, update: 0, unchanged: 0, invalid: 0 }, writes,
  });
  const row = (n: number, state: ImportPlan["rows"][number]["state"]) =>
    ({ row: n, key: `k${n}`, state, ficha: null, stock: null, warnings: [] });

  it("solo las filas que crean o actualizan; las malas y las sin cambios se saltan", () => {
    const p = plan([row(2, "create"), row(3, "invalid"), row(4, "unchanged"), row(5, "update")]);
    expect(writtenRows(p).map((r) => r.row)).toEqual([2, 5]);
    expect(canApply(p)).toBe(true);
  });

  it("un resumen que no escribe nada no se puede importar", () => {
    expect(canApply(plan([row(2, "invalid"), row(3, "unchanged")], { fichas: 0, stock: 0 }))).toBe(false);
    expect(canApply(null)).toBe(false);
  });
});

describe("la tabla", () => {
  const item = (over: Partial<LibraryItem>): LibraryItem => ({
    key: "k", type: "gearbox", kind: "", manufacturer: "", status: "unverified", verified_by: "",
    verified_on: "", fields: 0, origin: "workspace", pack: null, overrides: null, editable: true,
    error: null, stock: null, ...over,
  });

  it("el origen dice de qué paquete es, si tapa la de un paquete y si solo hay stock", () => {
    setLanguage("es");
    expect(originText(item({ origin: "pack", pack: "kit_demo", editable: false }))).toContain("kit_demo");
    expect(originText(item({ overrides: "kit_demo" }))).toContain("kit_demo");
    expect(originText(item({ origin: "stock" }))).not.toBe(originText(item({})));
  });

  it("el filtro busca todas las palabras en clave, fabricante y clase", () => {
    const items = [item({ key: "hd-csf-17", manufacturer: "Harmonic Drive" }), item({ key: "m3x10", kind: "tornillo" })];
    expect(filterItems(items, "harmonic 17").map((i) => i.key)).toEqual(["hd-csf-17"]);
    expect(filterItems(items, "TORNI").map((i) => i.key)).toEqual(["m3x10"]);
    expect(filterItems(items, "  ")).toHaveLength(2);
  });
});
