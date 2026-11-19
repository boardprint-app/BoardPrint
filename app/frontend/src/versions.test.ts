// Cómo se lee la lista de *Comparar* (D76) y la selección de dos versiones.
import { describe, expect, it } from "vitest";
import { changeLabel, shortDate, toggleSelection, type Change } from "./versions";
import type { BlockType } from "./store";

const types = {
  "demo.tubo": { title: "Tubo", params: { L: { label: "Largo", unit: "mm", default: 300, choices: [] } } } as unknown as BlockType,
};
const el = (over: Partial<Change["element"]> = {}) =>
  ({ kind: "postit", type: "embeddable", x: 0, y: 0, width: 1, height: 1, postitKind: "pregunta", text: "¿Los 50 N incluyen la pinza?", ...over });

describe("changeLabel", () => {
  it("un añadido o quitado se nombra por su tipo y su texto", () => {
    expect(changeLabel({ id: "a", change: "added", element: el() }, types)).toBe("Pregunta «¿Los 50 N incluyen la pinza?»");
    expect(changeLabel({ id: "b", change: "removed", element: el({ kind: "block", blockType: "demo.tubo" }) }, types)).toBe("Bloque Tubo");
    expect(changeLabel({ id: "i", change: "added", element: el({ kind: "ink", type: "freedraw" }) }, types)).toBe("Tinta");
  });
  it("un parámetro cambiado sale con su nombre, el valor de antes, el de después y su unidad", () => {
    const c: Change = { id: "t", change: "modified", element: el({ kind: "block", blockType: "demo.tubo" }),
                        fields: { params: { L: [300, 250] } } };
    expect(changeLabel(c, types)).toBe("Bloque Tubo: Largo 300 → 250 mm");
  });
  it("tipo, estado y texto de un post-it", () => {
    const c: Change = { id: "p", change: "modified", element: el({ postitKind: "riesgo", text: "x" }),
                        fields: { postitKind: ["nota", "riesgo"], state: ["abierto", "aceptado"], text: ["a", "x"] } };
    expect(changeLabel(c, types)).toBe("Riesgo «x»: Nota → Riesgo, abierto → aceptado, texto cambiado");
  });
  it("mover o redimensionar es un cambio menor", () => {
    expect(changeLabel({ id: "n", change: "minor", element: el({ postitKind: "nota", text: "" }), moved: true }, types))
      .toBe("Nota movido (cambio menor)");
    expect(changeLabel({ id: "f", change: "minor", element: el({ kind: "shape", type: "rectangle" }), moved: true, resized: true }, types))
      .toBe("Forma movido y redimensionado (cambio menor)");
  });
  it("un texto largo se corta", () => {
    const long = "a".repeat(80);
    expect(changeLabel({ id: "t", change: "added", element: el({ kind: "text", type: "text", text: long }) }, types))
      .toBe(`Texto «${"a".repeat(39)}…»`);
  });
});

describe("toggleSelection", () => {
  it("como mucho dos; el tercero deja fuera el primero, y volver a pulsar quita", () => {
    expect(toggleSelection(["a", "b"], "c")).toEqual(["b", "c"]);
    expect(toggleSelection(["a", "b"], "a")).toEqual(["b"]);
    expect(toggleSelection([], "a")).toEqual(["a"]);
  });
});

describe("fecha de una versión", () => {
  const iso = new Date(2026, 10, 17, 18, 42).toISOString();   // hora local
  it("en el formato del idioma: día/mes y 24 h en español, mes con nombre y AM/PM en inglés", () => {
    expect(shortDate(iso, "es")).toBe("17/11 · 18:42");
    expect(shortDate(iso, "en")).toMatch(/^Nov 17 · 6:42\s?PM$/);
  });
  it("una fecha ilegible no enseña nada", () => {
    expect(shortDate("ayer", "en")).toBe("");
  });
});
