// Cómo se lee un post-it en su tarjeta (plan §3, D19, D52, D71). Antes de D71 lo escribía el
// backend dentro del texto; ahora lo decide la tarjeta.
import { describe, expect, it } from "vitest";
import { FILTER_ALL, filteredOut, nextKind, postitView, userEdit, type PostitData, type PostitKind } from "./postit";
import type { BlockState, BlockType } from "./store";

const types = { "demo.voladizo": { title: "Voladizo" } as BlockType };
const blocks = { b1: { type: "demo.voladizo" } as BlockState };

const pi = (over: Partial<PostitData> = {}): PostitData => ({
  kind: "postit", postitKind: "nota", state: "abierto", text: "ok", author: "agent:design",
  sources: [], estimate: false, anchor: null, ...over,
});

describe("postitView", () => {
  it("la fuente de un bloque se lee con el nombre del bloque, nunca con su id", () => {
    const v = postitView(pi({ sources: [{ kind: "bloque", ref: "bloque:b1" }] }), blocks, types);
    expect(v.sources).toEqual(["bloque Voladizo"]);
  });

  it("un bloque que ya no está se lee con su referencia", () => {
    const v = postitView(pi({ sources: [{ kind: "bloque", ref: "bloque:zz" }] }), blocks, types);
    expect(v.sources).toEqual(["bloque:zz"]);
  });

  it("un cálculo del agente se pinta como no verificado y enseña la cuenta con sus bloques", () => {
    const v = postitView(pi({ sources: [{ kind: "calculo", formula: " L/500 = 600 mm / 500 = 1,2 mm ",
                                          inputs: ["bloque:b1"] }] }), blocks, types);
    expect(v.unverified).toBe(true);
    expect(v.sources).toEqual(["cálculo del agente: L/500 = 600 mm / 500 = 1,2 mm (con bloque Voladizo)"]);
  });

  it("una estimación se pinta como no verificada", () => {
    expect(postitView(pi({ estimate: true }), blocks, types).unverified).toBe(true);
  });

  it("una fuente de bloque o de ficha se pinta normal", () => {
    const v = postitView(pi({ sources: [{ kind: "bloque", ref: "bloque:b1" },
                                        { kind: "ficha", ref: "library/motores/nema17" }] }), blocks, types);
    expect(v.unverified).toBe(false);
    expect(v.sources[1]).toBe("library/motores/nema17");
  });

  it("un tipo o estado desconocido se lee como nota abierta, sin romper la tarjeta", () => {
    const v = postitView(pi({ postitKind: "chiste" as never, state: "raro" as never }), blocks, types);
    expect([v.kind, v.state]).toEqual(["nota", "abierto"]);
  });

  it("el autor: del agente lo dice; del usuario editado, que vino del agente", () => {
    expect(postitView(pi(), blocks, types).author).toBe("Agente de diseño");
    expect(postitView(pi({ author: "user" }), blocks, types).author).toBe(null);
    expect(postitView(pi({ author: "user", origin: "agent:design" }), blocks, types).author)
      .toBe("del agente, editado");
  });
});

describe("cambios del usuario en un post-it (D72, D73)", () => {
  it("cambiar el texto de uno del agente lo pasa al usuario con origin", () => {
    const cd = userEdit(pi({ author: "agent:design" }), { text: "otro" });
    expect([cd.author, cd.origin, cd.text]).toEqual(["user", "agent:design", "otro"]);
  });
  it("cambiar el tipo también", () => {
    const cd = userEdit(pi({ author: "agent:design" }), { postitKind: "riesgo" });
    expect([cd.author, cd.origin]).toEqual(["user", "agent:design"]);
  });
  it("cambiar el estado nunca cambia el autor", () => {
    const cd = userEdit(pi({ author: "agent:design" }), { state: "aceptado" });
    expect([cd.author, cd.origin, cd.state]).toEqual(["agent:design", undefined, "aceptado"]);
  });
  it("dejar el mismo texto no cuenta como cambio", () => {
    expect(userEdit(pi({ author: "agent:design", text: "a" }), { text: "a" }).author).toBe("agent:design");
  });
  it("uno del usuario sigue siendo suyo y sin origin", () => {
    const cd = userEdit(pi({ author: "user" }), { text: "x" });
    expect([cd.author, cd.origin]).toEqual(["user", undefined]);
  });
  it("la etiqueta pasa por los cuatro tipos y vuelve", () => {
    let k: PostitKind = "nota";
    const seen: PostitKind[] = [k];
    for (let i = 0; i < 4; i++) seen.push(k = nextKind(k));
    expect(seen).toEqual(["nota", "sugerencia", "riesgo", "pregunta", "nota"]);
  });
});

describe("filtro de post-its (4C)", () => {
  it("por defecto se ve todo", () => {
    expect(filteredOut(FILTER_ALL, pi({ state: "descartado" }))).toBe(false);
  });
  it("oculta por tipo, descartados y autor de agente", () => {
    const f = { ...FILTER_ALL, kinds: { ...FILTER_ALL.kinds, riesgo: false }, discarded: false, agent: false };
    expect(filteredOut(f, pi({ author: "user", postitKind: "riesgo" }))).toBe(true);
    expect(filteredOut(f, pi({ author: "user", state: "descartado" }))).toBe(true);
    expect(filteredOut(f, pi({ author: "agent:review" }))).toBe(true);
    expect(filteredOut(f, pi({ author: "user", origin: "agent:design" }))).toBe(false);
    expect(filteredOut(f, pi({ author: "user", state: "aceptado" }))).toBe(false);
  });
  it("un tipo desconocido se filtra como nota", () => {
    const f = { ...FILTER_ALL, kinds: { ...FILTER_ALL.kinds, nota: false } };
    expect(filteredOut(f, pi({ author: "user", postitKind: "raro" as PostitKind }))).toBe(true);
  });
});
