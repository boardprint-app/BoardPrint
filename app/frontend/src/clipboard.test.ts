// Copiar un bloque lleva sus parámetros (D85); sin bloques, copia Excalidraw como siempre.
import { describe, expect, it } from "vitest";
import { cardsClipboard } from "./clipboard";

const block = (id: string, extra = {}) => ({
  id, type: "embeddable", customData: { kind: "block", blockType: "demo.tubo" }, ...extra,
});
const rect = (id: string, extra = {}) => ({ id, type: "rectangle", ...extra });
const params: Record<string, Record<string, unknown>> = { b1: { L: 450 } };
const parse = (s: string | null) => JSON.parse(s!) as { type: string; elements: any[] };

describe("copiar con bloques", () => {
  it("sin ningún bloque seleccionado no hace nada (copia Excalidraw)", () => {
    expect(cardsClipboard([block("b1"), rect("r")], new Set(["r"]), (id) => params[id])).toBeNull();
  });
  it("el bloque copiado lleva sus parámetros, en el formato de Excalidraw", () => {
    const c = parse(cardsClipboard([block("b1"), rect("r")], new Set(["b1"]), (id) => params[id]));
    expect(c.type).toBe("excalidraw/clipboard");
    expect(c.elements.map((e) => e.id)).toEqual(["b1"]);
    expect(c.elements[0].customData).toEqual({ kind: "block", blockType: "demo.tubo", params: { L: 450 } });
  });
  it("copia también lo demás seleccionado y el texto ligado, nunca lo borrado", () => {
    const els = [block("b1"), rect("r"), { id: "t", type: "text", containerId: "r" },
                 rect("x", { isDeleted: true }), rect("fuera")];
    const c = parse(cardsClipboard(els, new Set(["b1", "r", "x"]), (id) => params[id]));
    expect(c.elements.map((e) => e.id)).toEqual(["b1", "r", "t"]);
  });
  it("un bloque sin estado se copia sin parámetros (el pegado nace con los de defecto)", () => {
    const c = parse(cardsClipboard([block("b2")], new Set(["b2"]), (id) => params[id]));
    expect(c.elements[0].customData.params).toBeUndefined();
  });
  it("lo que estaba en un marco que no se copia sale del marco", () => {
    const c = parse(cardsClipboard([block("b1", { frameId: "f" })], new Set(["b1"]), (id) => params[id]));
    expect(c.elements[0].frameId).toBeNull();
  });
});
