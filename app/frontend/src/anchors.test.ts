// Anclajes (D74): qué se puede anclar, quién sigue a quién y por dónde va el hilo.
import { describe, expect, it } from "vitest";
import { anchorMap, canAnchor, elementAt, followers, movedBetween, thread } from "./anchors";

const el = (id: string, extra: Record<string, unknown> = {}) =>
  ({ id, x: 0, y: 0, width: 100, height: 50, ...extra });
const postit = (id: string, anchor: string | null, extra: Record<string, unknown> = {}) =>
  el(id, { customData: { kind: "postit", anchor }, ...extra });

describe("una foto suelta se ancla como un post-it (D140)", () => {
  const foto = (id: string, anchor: string | null) => el(id, { customData: { kind: "image", anchor } });
  it("sigue a lo que va anclada", () =>
    expect([...anchorMap([el("b"), foto("f", "b")])]).toEqual([["f", "b"]]));
  it("y con las mismas reglas: un ciclo entre foto y post-it, nunca", () =>
    expect(canAnchor("p", "f", [postit("p", null), foto("f", "p")])).toBe(false));
  it("lo que no es post-it ni foto no se ancla aunque lleve `anchor`", () =>
    expect(anchorMap([el("x", { customData: { kind: "file", anchor: "b" } })]).size).toBe(0));
});

describe("canAnchor", () => {
  const els = [el("b"), postit("p1", "b"), postit("p2", "p1"), el("gone", { isDeleted: true })];
  it("a un elemento que existe, sí", () => expect(canAnchor("p2", "b", els)).toBe(true));
  it("a sí mismo, nunca", () => expect(canAnchor("p1", "p1", els)).toBe(false));
  it("a algo que no existe o está borrado, nunca", () => {
    expect(canAnchor("p1", "zz", els)).toBe(false);
    expect(canAnchor("p1", "gone", els)).toBe(false);
  });
  it("si cierra un ciclo, nunca", () => expect(canAnchor("p1", "p2", els)).toBe(false));
});

describe("followers", () => {
  const anchors = anchorMap([el("b"), postit("p1", "b"), postit("p2", "p1"), postit("p3", "x")]);
  it("mover un elemento mueve sus anclados y los de estos, la misma distancia", () => {
    const f = followers(new Map([["b", { x: 10, y: -5 }]]), anchors);
    expect(Object.fromEntries(f)).toEqual({ p1: { x: 10, y: -5 }, p2: { x: 10, y: -5 } });
  });
  it("nunca mueve otra vez lo que el usuario arrastra a la vez", () => {
    const f = followers(new Map([["b", { x: 10, y: 0 }], ["p1", { x: 10, y: 0 }]]), anchors);
    expect([...f.keys()]).toEqual(["p2"]);
  });
  it("un ciclo nunca entra en bucle", () => {
    const loop = new Map([["a", "c"], ["c", "a"]]);
    const f = followers(new Map([["a", { x: 1, y: 1 }]]), loop);
    expect(Object.fromEntries(f)).toEqual({ c: { x: 1, y: 1 } });
  });
  it("lo que no está anclado a lo movido no se mueve", () => {
    expect(followers(new Map([["zz", { x: 1, y: 1 }]]), anchors).size).toBe(0);
  });
});

describe("movedBetween", () => {
  it("cuenta lo que cambió de sitio, nunca lo nuevo ni lo borrado", () => {
    const before = new Map([["a", { x: 0, y: 0 }], ["b", { x: 5, y: 5 }], ["c", { x: 0, y: 0 }]]);
    const now = [el("a", { x: 3, y: 4 }), el("b", { x: 5, y: 5 }), el("c", { x: 9, isDeleted: true }), el("n", { x: 7 })];
    expect(Object.fromEntries(movedBetween(before, now))).toEqual({ a: { x: 3, y: 4 } });
  });
});

describe("thread", () => {
  it("une los bordes más cercanos del post-it y del elemento", () => {
    const t = thread({ x: 0, y: 200, width: 100, height: 80 }, { x: 0, y: 0, width: 300, height: 100 });
    expect(t).toEqual({ from: { x: 100, y: 200 }, to: { x: 100, y: 100 } });
    const side = thread({ x: 400, y: 0, width: 100, height: 100 }, { x: 0, y: 0, width: 300, height: 100 });
    expect(side).toEqual({ from: { x: 400, y: 50 }, to: { x: 300, y: 50 } });
  });
  it("si están uno encima del otro o se tocan, no hay hilo", () => {
    expect(thread({ x: 10, y: 10, width: 50, height: 50 }, { x: 0, y: 0, width: 300, height: 100 })).toBeNull();
    expect(thread({ x: 300, y: 0, width: 50, height: 50 }, { x: 0, y: 0, width: 300, height: 100 })).toBeNull();
  });
});

describe("elementAt", () => {
  it("da el de más arriba bajo el punto, sin los que se saltan", () => {
    const els = [el("abajo"), el("arriba"), el("borrado", { isDeleted: true })];
    expect(elementAt(els, { x: 10, y: 10 }, () => false)?.id).toBe("arriba");
    expect(elementAt(els, { x: 10, y: 10 }, (e) => e.id === "arriba")?.id).toBe("abajo");
    expect(elementAt(els, { x: 500, y: 10 }, () => false)).toBeNull();
  });
});
