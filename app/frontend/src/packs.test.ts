// Ajustes → Paquetes (PLAN_PAQUETES §7, P79, P82, P84): un `.bppack` soltado nunca se convierte
// en tarjeta, nunca se ofrece desinstalar lo que otro pide o lo de desarrollo, y el resumen
// dice siempre qué versión sustituye y qué copia se va a usar.
import { describe, expect, it } from "vitest";
import { itemNotes, splitDrop, uninstallBlock, uninstallWarning, type InstalledPack, type PlanItem } from "./packs";

const pack = (patch: Partial<InstalledPack> = {}): InstalledPack => ({
  id: "base", name: "Base", version: "1.0.0", author: "", description: "", origin: "usuario", path: "",
  shadowed: [], error: null, requires: {}, libraries: [], code: true, required_by: [], removable: true, ...patch,
});
const item = (patch: Partial<PlanItem> = {}): PlanItem => ({
  archive: "x.bppack", id: "p", name: "P", version: "1.1.0", author: "", description: "", requires: [],
  libraries: [], blocks: [], replaces: null, older: false, shadowed_by: null, problems: [], ...patch,
});

describe("soltar archivos (P82)", () => {
  it("un .bppack nunca va a la pizarra, sin mirar mayúsculas", () => {
    expect(splitDrop(["C:\\a\\robot-1.0.0.bppack", "C:\\a\\plano.step", "D:/x/OTRO.BPPACK"]))
      .toEqual({ packs: ["C:\\a\\robot-1.0.0.bppack", "D:/x/OTRO.BPPACK"], others: ["C:\\a\\plano.step"] });
  });
  it("también con archivos del navegador", () => {
    const f = (name: string) => ({ name });
    const got = splitDrop([f("a.bppack"), f("b.png")]);
    expect(got.packs.map((x) => x.name)).toEqual(["a.bppack"]);
    expect(got.others.map((x) => x.name)).toEqual(["b.png"]);
  });
  it("un archivo que solo lleva bppack en el nombre no es un paquete", () => {
    expect(splitDrop(["notas-bppack.txt"]).packs).toEqual([]);
  });
});

describe("desinstalar (P84)", () => {
  it("lo que otro cargado pide nunca se ofrece", () => {
    expect(uninstallBlock(pack({ required_by: ["robot"] }))).toMatch(/Lo pide robot/);
    expect(uninstallBlock(pack({ required_by: ["a", "b"] }))).toMatch(/esos$/);
  });
  it("desarrollo nunca", () => {
    expect(uninstallBlock(pack({ origin: "desarrollo", removable: false }))).toMatch(/desarrollo/);
  });
  it("lo demás, sí; y lo que otro pide, tampoco aunque haya otra copia debajo", () => {
    expect(uninstallBlock(pack())).toBeNull();
    expect(uninstallBlock(pack({ required_by: ["robot"], shadowed: ["usuario"] }))).toMatch(/Lo pide robot/);
  });
  it("en el workspace avisa de que lo pierden todos", () => {
    expect(uninstallWarning(pack({ origin: "workspace" }))).toMatch(/todos los que lo comparten/);
    expect(uninstallWarning(pack())).not.toMatch(/workspace/);
  });
});

describe("resumen de instalar (P79, §3)", () => {
  it("dice qué versión sustituye y si es una vuelta atrás", () => {
    expect(itemNotes(item({ replaces: "1.0.0" }), "usuario")).toEqual(["Sustituye la 1.0.0 instalada"]);
    expect(itemNotes(item({ replaces: "2.0.0", older: true }), "usuario"))
      .toEqual(["Es anterior a la instalada (2.0.0): se vuelve a la 1.1.0"]);
    expect(itemNotes(item(), "usuario")).toEqual([]);
  });
  it("si el workspace ya lo tiene, dice que se seguirá usando aquel", () => {
    expect(itemNotes(item({ shadowed_by: "workspace" }), "usuario")[0]).toMatch(/workspace, que manda sobre usuario/);
  });
});
