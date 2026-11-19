// Mismas reglas que tests/test_sessions.py (EnvioParcial) en el backend (plan §10, D69).
import { describe, expect, it } from "vitest";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { mergeElements } from "./merge";

const el = (id: string, version = 1, index?: string | null) =>
  ({ id, version, index: index ?? null }) as unknown as ExcalidrawElement;
const ids = (els: readonly ExcalidrawElement[]) => els.map((e) => e.id);

describe("mergeElements", () => {
  it("lo que no viene se queda como estaba y en su sitio", () => {
    const out = mergeElements([el("a"), el("b"), el("c")], [el("b", 2)]);
    expect(ids(out)).toEqual(["a", "b", "c"]);
    expect(out[1].version).toBe(2);
  });

  it("lo nuevo va al final", () => {
    expect(ids(mergeElements([el("a"), el("b")], [el("z"), el("a", 2)]))).toEqual(["a", "b", "z"]);
  });

  it("el orden de dibujo lo da el índice: traer al frente en otra ventana se ve igual", () => {
    const local = [el("a", 1, "a0"), el("b", 1, "a1"), el("c", 1, "a2")];
    expect(ids(mergeElements(local, [el("a", 2, "a3")]))).toEqual(["b", "c", "a"]);
  });

  it("sin índice en todos, se respeta el orden de llegada", () => {
    const local = [el("a", 1, "a0"), el("b", 1, "a1")];
    expect(ids(mergeElements(local, [el("nuevo")]))).toEqual(["a", "b", "nuevo"]);
  });
});
