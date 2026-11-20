// Escribir las salidas en una copia del Excel en la interfaz (docs/PLAN_EXCEL.md §3.3, §3.5, X4,
// R4): solo se escribe en un nombre admitido que no es una fórmula, la unidad del campo tiene
// que casar con el sufijo del nombre, y «Escribir copia» no deja con un bloque sin resultado,
// desactualizado o ejecutándose, aunque la vista del backend vaya por detrás.
import { describe, expect, it } from "vitest";
import { isExcelPath, writeButton, writeChoices, writeProblem, writeTarget, type ExcelName, type ExcelWrite } from "./excel";
import type { BlockState } from "./store";

const name = (nombre: string, extra: Partial<ExcelName> = {}): ExcelName => ({
  nombre, hoja: "Datos", celda: "B3", where: "Datos!B3", valor: 1, formula: null,
  unidad: (/_(mm|cm|m|kg|g|N|Nm|deg|s)$/.exec(nombre)?.[1]) ?? "", problema: null, motivo: null, ...extra,
});

const block = (status: BlockState["status"], outputs: BlockState["outputs"] = null) =>
  ({ type: "prueba.viga", status, params: {}, outputs, error: null, inputs: {} }) as BlockState;

const viga = block("al_dia", {
  x: { L: { value: 300, unit: "mm" }, masa: { value: 2, unit: "kg" }, n: { value: 4, unit: "" },
       informe: { value: "informe.html", unit: "", file: "informe.html" },
       vista: { value: { items: [] }, unit: "", control: "view2d", label: "Vista lateral" } },
});

describe("la unidad del campo al sufijo del nombre (excel_names.check_write)", () => {
  it("casa la misma magnitud y niega lo demás con su motivo", () => {
    expect(writeProblem("mm", "m")).toBeNull();
    expect(writeProblem("", "")).toBeNull();
    expect(writeProblem("mm", "kg")).toBe("otra_magnitud");
    expect(writeProblem("mm", "")).toBe("sin_sufijo");
    expect(writeProblem("", "mm")).toBe("sin_unidad");
    expect(writeProblem("furlong", "mm")).toBe("unidad_desconocida");
  });
});

describe("dónde se puede escribir (R4)", () => {
  it("en una celda admitida que no es una fórmula; nunca encima de una fórmula ni en lo de X3", () => {
    expect(writeTarget(name("res_m"))).toBe(true);
    expect(writeTarget(name("vacia_m", { valor: null, problema: "vacia" }))).toBe(true);
    expect(writeTarget(name("doble_m", { formula: "=B10*2" }))).toBe(false);
    for (const p of ["varias_celdas", "constante", "no_es_celda", "ref_rota"])
      expect(writeTarget(name("x_m", { valor: null, problema: p }))).toBe(false);
  });

  it("solo los .xlsx y .xlsm reciben una flecha de escritura", () => {
    expect(isExcelPath("C:\\datos\\Datos.XLSX")).toBe(true);
    expect(isExcelPath("macro.xlsm")).toBe(true);
    expect(isExcelPath("viejo.xls")).toBe(false);
    expect(isExcelPath("notas.txt")).toBe(false);
  });
});

describe("qué salidas se ofrecen a un nombre", () => {
  const writers = [{ id: "b1", title: "Viga" }];

  it("los campos de los bloques con flecha, con el motivo de los que no casan en unidad", () => {
    const got = writeChoices(name("res_m"), writers, { b1: viga });
    // los que casan, primero
    expect(got.map((c) => [c.port, c.field, c.problem])).toEqual([
      ["x", "L", null], ["x", "masa", "otra_magnitud"], ["x", "n", "sin_unidad"],
    ]);
    expect(writeChoices(name("masa_g"), writers, { b1: viga }).map((c) => c.field)).toEqual(["masa", "L", "n"]);
    expect(got[0]).toMatchObject({ block: "b1", title: "Viga", unit: "mm", value: 300 });
  });

  it("un campo que es un archivo o un control (no un valor) nunca se ofrece, y un bloque sin resultado no ofrece nada", () => {
    expect(writeChoices(name("x"), writers, { b1: viga }).map((c) => c.field)).not.toContain("informe");
    expect(writeChoices(name("x"), writers, { b1: viga }).map((c) => c.field)).not.toContain("vista");
    expect(writeChoices(name("res_m"), writers, { b1: block("nunca") })).toEqual([]);
  });
});

describe("Escribir copia no deja sin resultado ni con el bloque desactualizado", () => {
  const ok: ExcelWrite = {
    writers: [{ id: "b1", title: "Viga" }], ready: true, reason: null, pending: null,
    rows: { res_m: { block: "b1", port: "x", field: "L", value: 0.3, unit: "m", reason: null } },
  };

  it("todo al día: deja", () => {
    expect(writeButton(ok, { b1: viga })).toEqual({ disabled: false, reason: null });
  });

  it("el backend dice por qué no (sin resultado, desactualizado): no deja y lo enseña", () => {
    const why = "res_m ← Viga · x · L: Viga está desactualizado: ejecútalo antes de escribir";
    expect(writeButton({ ...ok, ready: false, reason: why }, { b1: viga })).toEqual({ disabled: true, reason: why });
  });

  it("aunque la vista del backend vaya por detrás, un bloque que no está al día no deja", () => {
    for (const s of ["desactualizado", "nunca", "error", "incompleto", "ejecutando", "en_cola"] as const) {
      const got = writeButton(ok, { b1: { ...viga, status: s } });
      expect(got.disabled, s).toBe(true);
      expect(got.reason, s).toBeTruthy();
    }
  });

  it("sin nada elegido o sin vista, no deja", () => {
    expect(writeButton(null, {}).disabled).toBe(true);
    expect(writeButton({ ...ok, rows: {}, ready: false, reason: "elige" }, { b1: viga })).toEqual({ disabled: true, reason: "elige" });
  });
});
