// La tinta en la vista (plan §10, D188-D190): el color tras el filtro del skin, escena ↔
// pantalla, el trazo a pintar y el `freedraw` que entra en la escena.
import { describe, expect, it } from "vitest";
import { absolutePoints, inkData, normalizeInk } from "./ink";
import { cardInkFilter, DARK_THEME_FILTER, densify, filterColor, inkElement, inkPoints, inkStroke, skinInkFilter,
         toScreen, viewTransform } from "./inkView";
import { SKINS, skinOf } from "./skins";

const NEW = { brush: "rotulador" as const, color: "#e03131", size: 4, anchor: null, created: "2026-11-16T10:00:00+00:00",
              id: "abc", seed: 7, versionNonce: 9, updated: 1 };

describe("color tras el filtro del skin", () => {
  // Medido en Chrome (FF 4.9 paso 3): un trazo del lápiz de Excalidraw y uno de tinta del mismo
  // color, con el tema oscuro, dan el mismo píxel.
  it("con el tema oscuro sale el mismo color que el lienzo de Excalidraw en Chrome", () => {
    expect(filterColor("#e03131", DARK_THEME_FILTER)).toBe("#ff8383");
    expect(filterColor("#1e1e1e", DARK_THEME_FILTER)).toBe("#d3d3d3");
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(filterColor("#fab005", DARK_THEME_FILTER).slice(i, i + 2), 16));
    expect(Math.abs(r - 143) + Math.abs(g - 80) + Math.abs(b - 0)).toBeLessThanOrEqual(2);
  });
  it("sin filtro, o con uno que no entiende, el color sale igual", () => {
    expect(filterColor("#1971c2", "none")).toBe("#1971c2");
    expect(filterColor("#1971c2", undefined)).toBe("#1971c2");
    expect(filterColor("#1971c2", "blur(2px)")).toBe("#1971c2");
    expect(filterColor("transparent", DARK_THEME_FILTER)).toBe("transparent");
  });
  it("brightness y saturate de los skins claros con color oscurecen la tinta", () => {
    const corcho = SKINS.find((s) => s.id === "corcho")!;
    expect(filterColor("#ffffff", "brightness(.62)")).toBe("#9e9e9e");
    expect(filterColor("#808080", "saturate(1.5)")).toBe("#808080");    // un gris no se satura
    expect(filterColor("#fab005", skinInkFilter(corcho))).not.toBe("#fab005");
  });
  it("cada skin pone el filtro de su lienzo: tema oscuro, el suyo o ninguno", () => {
    for (const s of SKINS) {
      expect(skinInkFilter(s)).toBe(s.dark ? DARK_THEME_FILTER : s.inkFilter ?? "none");
    }
  });
});

describe("escena y pantalla", () => {
  it("un punto pasa a la pantalla como en la capa de hilos, (p + scroll) × zoom", () => {
    expect(toScreen({ x: 10, y: -5 }, { scrollX: 100, scrollY: 20, zoom: 2 })).toEqual({ x: 220, y: 30 });
  });
  it("la transformación del SVG hace lo mismo con todo el trazo", () => {
    const v = { scrollX: 100, scrollY: 20, zoom: 2 };
    expect(viewTransform(v)).toBe("matrix(2 0 0 2 200 40)");
  });
});

describe("el freedraw de un trazo", () => {
  it("lleva todo lo de Excalidraw 0.18, opacity 0 y la tinta en customData", () => {
    const e = inkElement({ ...NEW, points: [{ x: 100, y: 50 }, { x: 130, y: 70 }, { x: 160, y: 40 }],
                           shape: "triángulo", anchor: "blk" });
    expect(e).toMatchObject({ type: "freedraw", x: 100, y: 50, width: 60, height: 30, opacity: 0, strokeColor: "#e03131",
                              strokeWidth: 4, roundness: null, version: 1, seed: 7, versionNonce: 9, isDeleted: false,
                              lastCommittedPoint: null, simulatePressure: true, pressures: [] });
    expect(e.points[0]).toEqual([0, 0]);
    expect(e.customData).toEqual({ kind: "ink", ink: { brush: "rotulador", size: 4, opacity: 1, shape: "triángulo" },
                                   author: "user", created: NEW.created, anchor: "blk" });
    expect(absolutePoints(e)).toEqual([{ x: 100, y: 50 }, { x: 130, y: 70 }, { x: 160, y: 40 }]);
    expect(normalizeInk(e)).toBe(e);                 // ya está bien: no se toca
    expect(inkData(e)?.shape).toBe("triángulo");
  });
  it("sin ancla no lleva `anchor`; un clic suelto es un punto doble (Excalidraw no admite uno)", () => {
    const e = inkElement({ ...NEW, points: [{ x: 5, y: 5 }] });
    expect("anchor" in e.customData).toBe(false);
    expect(e.points).toEqual([[0, 0], [0, 0]]);
  });
  it("con un lápiz guarda su presión y no la simula; una forma ideal no la guarda", () => {
    const pts = [{ x: 0, y: 0 }, { x: 10, y: 0 }];
    const pen = inkElement({ ...NEW, brush: "pluma", points: pts, pressures: [0.2, 0.9] });
    expect(pen.pressures).toEqual([0.2, 0.9]);
    expect(pen.simulatePressure).toBe(false);
    expect(inkPoints(pen)).toEqual({ points: [[0, 0, 0.2], [10, 0, 0.9]], realPressure: true });
    const shape = inkElement({ ...NEW, brush: "pluma", points: pts, pressures: [0.2, 0.9], shape: "recta" });
    expect(shape.pressures).toEqual([]);
    expect(inkPoints(shape).realPressure).toBe(false);
  });
});

describe("el trazo a pintar", () => {
  const el = inkElement({ ...NEW, points: [{ x: 0, y: 0 }, { x: 50, y: 0 }, { x: 100, y: 5 }] });
  it("con su contorno, el color del skin y la pintura de su pincel", () => {
    const s = inkStroke(el, DARK_THEME_FILTER)!;
    expect(s.d.startsWith("M")).toBe(true);
    expect(s).toMatchObject({ color: "#ff8383", opacity: 1, blend: "normal", grain: true, anchor: null });
  });
  it("anclada a una tarjeta conserva su color: las tarjetas no se invierten en los skins oscuros", () => {
    const onCard = { ...el, customData: { ...el.customData, anchor: "postit1" } };
    expect(inkStroke(onCard, DARK_THEME_FILTER)).toMatchObject({ color: "#e03131", anchor: "postit1" });
  });
  // Prueba de punta a punta de FF 4.9: en CAD las tarjetas son oscuras y la tinta negra anclada a
  // ellas (y la flecha o el círculo que las marca) no se veía.
  it("con las tarjetas oscuras (CAD), la anclada se aclara como la del lienzo; en los demás, no", () => {
    const onCard = { ...el, strokeColor: "#1e1e1e", customData: { ...el.customData, anchor: "b1" } };
    const cad = skinOf("cad");
    expect(inkStroke(onCard, skinInkFilter(cad), cardInkFilter(cad))).toMatchObject({ color: "#d3d3d3" });
    for (const s of SKINS.filter((k) => k.id !== "cad")) {
      expect(inkStroke(onCard, skinInkFilter(s), cardInkFilter(s))!.color, s.id).toBe("#1e1e1e");
    }
  });
  it("el subrayador, al 40 % y multiplicando", () => {
    const hl = inkElement({ ...NEW, brush: "subrayador", color: "#fab005", points: [{ x: 0, y: 0 }, { x: 80, y: 0 }] });
    expect(inkStroke(hl, "none")).toMatchObject({ color: "#fab005", opacity: 0.4, blend: "multiply", grain: false });
  });
  // Prueba de punta a punta de FF 4.9: multiplicando, en el lienzo oscuro salía una banda negra.
  it("el subrayador, sobre lo oscuro, aclara con su color; sobre una tarjeta clara, multiplica", () => {
    const hl = inkElement({ ...NEW, brush: "subrayador", color: "#fab005", points: [{ x: 0, y: 0 }, { x: 80, y: 0 }] });
    expect(inkStroke(hl, DARK_THEME_FILTER)).toMatchObject({ color: "#fab005", blend: "screen" });
    const onCard = { ...hl, customData: { ...hl.customData, anchor: "b1" } };
    expect(inkStroke(onCard, DARK_THEME_FILTER, "none")).toMatchObject({ color: "#fab005", blend: "multiply" });
    expect(inkStroke(onCard, DARK_THEME_FILTER, DARK_THEME_FILTER)).toMatchObject({ blend: "screen" });
  });
  it("lo borrado, lo que no es tinta y el lápiz de Excalidraw no se pintan", () => {
    expect(inkStroke({ ...el, isDeleted: true }, "none")).toBeNull();
    expect(inkStroke({ ...el, customData: {} }, "none")).toBeNull();
    expect(inkStroke({ ...el, type: "line" }, "none")).toBeNull();
  });
  it("una forma ideal se densifica sin perder sus esquinas", () => {
    const d = densify([[0, 0], [10, 0], [10, 10]], 2);
    expect(d).toContainEqual([10, 0]);
    expect(d[d.length - 1]).toEqual([10, 10]);
    expect(d.length).toBe(11);
    for (let i = 1; i < d.length; i++) expect(Math.hypot(d[i][0] - d[i - 1][0], d[i][1] - d[i - 1][1])).toBeLessThanOrEqual(2);
  });
});
