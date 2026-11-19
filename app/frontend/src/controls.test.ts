// Controles genéricos (docs/PLAN_PAQUETES.md §5, P8, P52). Reglas:
// - El reparto de la tarjeta respeta lo declarado: Parámetros encima de Ejecutar, lo demás
//   debajo y en su orden; lo que la app no conoce, o la interfaz propia, no pinta ninguno.
// - Lo que no tiene la forma de una gráfica o de una vista 2D **no se pinta** (null).
// - Las marcas de un eje cubren todo el rango y son redondas.
// - La vista 2D va **a escala** (1 en x mide lo mismo que 1 en y) y cabe en su hueco.
// - Ningún nombre de la vista 2D pisa a otro ni se sale.
import { describe, expect, it } from "vitest";
import { asOutputs, chartData, chartFrame, layout, nearestPoint, niceTicks, placeLabels, planeData,
         planeFrame, type PlaneData } from "./controls";

describe("reparto de la tarjeta", () => {
  it("Parámetros encima, lo demás debajo y en el orden declarado", () => {
    expect(layout(["chart", "params", "results", "view2d"])).toEqual({ above: ["params"], below: ["chart", "results", "view2d"] });
  });
  it("sin vista (un backend viejo), la tarjeta de siempre; un panel sin declarar, nada", () => {
    expect(layout(undefined)).toEqual({ above: ["params"], below: ["results"] });
    expect(layout(undefined, [])).toEqual({ above: [], below: [] });
  });
  it("la interfaz propia y lo que la app no conoce no pintan ningún genérico", () => {
    expect(layout("ui")).toEqual({ above: [], below: [] });
    expect(layout(["arbol", "results"])).toEqual({ above: [], below: ["results"] });
  });
});

const ax = (label: string, unit = "mm") => ({ label, unit });

describe("datos de la gráfica", () => {
  const ok = { x: ax("x"), y: ax("y"), curves: [{ label: "a", points: [[0, 0], [1, 2]] }] };
  it("la de chart() del SDK se pinta", () => {
    expect(chartData(ok)?.curves[0].points).toEqual([[0, 0], [1, 2]]);
  });
  it("lo que no cuadra no se pinta", () => {
    for (const bad of [null, "x", [], { ...ok, curves: [] }, { ...ok, x: "x" }, { ...ok, y: { label: "y" } },
                       { ...ok, curves: [{ label: "a", points: [[0, 0]] }] },
                       { ...ok, curves: [{ label: "a", points: [[0, 0], [1, null]] }] },
                       { ...ok, curves: [{ label: "a", points: [[0, 0], [1, "2"]] }] },
                       { ...ok, curves: [{ label: 3, points: [[0, 0], [1, 2]] }] }]) {
      expect(chartData(bad)).toBeNull();
    }
  });
});

describe("datos de la vista 2D", () => {
  const base = { x: ax("x"), y: ax("z"), y_down: true };
  it("cajas, líneas y puntos; una caja con las esquinas al revés se ordena", () => {
    const d = planeData({ ...base, items: [{ box: [10, 5, 0, 0], label: "A", tone: "" }, { line: [[0, 0], [1, 1]] },
                                           { point: [2, 3], label: "TCP", tone: "warn" }] });
    expect(d?.yDown).toBe(true);
    expect(d?.items.map((i) => i.kind)).toEqual(["box", "line", "point"]);
    expect(d?.items[0]).toMatchObject({ box: [0, 0, 10, 5] });
  });
  it("lo que no cuadra no se pinta", () => {
    for (const items of [[], [{ circle: [0, 0, 1] }], [{ box: [0, 0, 1] }], [{ box: [0, 0, 1, 1], point: [0, 0] }],
                         [{ line: [[0, 0]] }], [{ point: [0, 0], tone: "rojo" }], ["caja"], [{ point: [0, NaN] }]]) {
      expect(planeData({ ...base, items })).toBeNull();
    }
  });
});

describe("marcas de los ejes", () => {
  it("cubren el rango, con un paso de 1, 2 o 5 por una potencia de diez", () => {
    for (const [lo, hi] of [[0, 0.3612], [0, 300], [-2.5, 7.1], [1234, 1290], [-0.004, -0.001]]) {
      const t = niceTicks(lo, hi);
      expect(t.lo).toBeLessThanOrEqual(lo);
      expect(t.hi).toBeGreaterThanOrEqual(hi);
      expect(t.ticks[0]).toBeCloseTo(t.lo);
      expect(t.ticks[t.ticks.length - 1]).toBeCloseTo(t.hi);
      const m = t.step / 10 ** Math.floor(Math.log10(t.step));
      expect([1, 2, 5, 10].some((k) => Math.abs(m - k) < 1e-9)).toBe(true);
    }
  });
  it("un rango de ancho cero se abre (una curva plana no queda en el borde)", () => {
    const t = niceTicks(0, 0);
    expect(t.lo).toBeLessThan(0);
    expect(t.hi).toBeGreaterThan(0);
  });
  it("la gráfica va de su primer punto a su último dentro del hueco", () => {
    const d = chartData({ x: ax("x"), y: ax("y"), curves: [{ label: "a", points: [[0, 0], [300, 0.36]] }] })!;
    const f = chartFrame(d, 300, 150, { l: 40, r: 10, t: 10, b: 30 });
    expect(f.px(0)).toBeCloseTo(40);
    expect(f.px(300)).toBeLessThanOrEqual(290 + 1e-9);
    expect(f.py(0)).toBeCloseTo(120);
  });
  it("la lectura del ratón es el punto más cercano en x", () => {
    expect(nearestPoint([[0, 0], [10, 1], [20, 4]], 13)).toEqual([10, 1]);
  });
});

describe("vista 2D a escala", () => {
  const tubo: PlaneData = { x: ax("x"), y: ax("y"), yDown: false, items: [
    { kind: "box", box: [0, -20, 300, 20], label: "Ø40 × 300", tone: "" },
    { kind: "box", box: [0, -17, 300, 17], label: "hueco", tone: "muted" },
  ] };
  it("1 mm en x mide lo mismo que 1 mm en y, y cabe en el hueco", () => {
    const f = planeFrame(tubo, 280, 140);
    expect(Math.abs(f.px(300) - f.px(0))).toBeCloseTo(300 * f.scale);
    expect(Math.abs(f.py(20) - f.py(-20))).toBeCloseTo(40 * f.scale);
    expect(f.px(0)).toBeGreaterThanOrEqual(0);
    expect(f.px(300)).toBeLessThanOrEqual(280);
    expect(f.h).toBeLessThanOrEqual(140);
  });
  it("una forma alta la limita el alto, no el ancho", () => {
    const alto: PlaneData = { ...tubo, items: [{ kind: "box", box: [0, 0, 10, 1000], label: "", tone: "" }] };
    const f = planeFrame(alto, 280, 140);
    expect(f.h).toBe(140);
    expect(Math.abs(f.py(1000) - f.py(0))).toBeLessThanOrEqual(140);
  });
  it("con y hacia abajo, una y mayor queda más abajo; si no, más arriba", () => {
    const up = planeFrame(tubo, 280, 140), down = planeFrame({ ...tubo, yDown: true }, 280, 140);
    expect(up.py(20)).toBeLessThan(up.py(-20));
    expect(down.py(20)).toBeGreaterThan(down.py(-20));
  });
  it("un solo punto no rompe la escala", () => {
    const f = planeFrame({ ...tubo, items: [{ kind: "point", point: [5, 5], label: "", tone: "" }] }, 200, 100);
    expect(Number.isFinite(f.px(5)) && Number.isFinite(f.py(5))).toBe(true);
  });
});

describe("nombres de la vista 2D", () => {
  const rects = (d: PlaneData, w: number, h: number) => {
    const f = planeFrame(d, w, h);
    return { f, ls: placeLabels(d, f) };
  };
  it("ninguno pisa a otro ni se sale: el de la caja de dentro, pegada a la de fuera, no se pinta", () => {
    const d: PlaneData = { x: ax("x"), y: ax("y"), yDown: false, items: [
      { kind: "box", box: [0, -20, 300, 20], label: "Ø40 × 300", tone: "" },
      { kind: "box", box: [0, -17, 300, 17], label: "hueco", tone: "muted" },
      { kind: "point", point: [300, 0], label: "F", tone: "warn" },
    ] };
    const { f, ls } = rects(d, 280, 140);
    expect(ls.map((l) => l.text)).toContain("Ø40 × 300");
    expect(ls.map((l) => l.text)).not.toContain("hueco");
    const boxes = ls.map((l) => {
      const w = l.text.length * 5.6;
      return l.anchor === "start" ? [l.x, l.y, l.x + w, l.y + 12] : [l.x - w, l.y, l.x, l.y + 12];
    });
    for (const [x0, y0, x1, y1] of boxes) {
      expect(x0).toBeGreaterThanOrEqual(0); expect(x1).toBeLessThanOrEqual(f.w);
      expect(y0).toBeGreaterThanOrEqual(0); expect(y1).toBeLessThanOrEqual(f.h);
    }
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const [a, b] = [boxes[i], boxes[j]];
      expect(a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]).toBe(false);
    }
  });
  it("un punto en el borde derecho pone su nombre a la izquierda", () => {
    const d: PlaneData = { x: ax("x"), y: ax("y"), yDown: false, items: [
      { kind: "box", box: [0, 0, 100, 100], label: "", tone: "" },
      { kind: "point", point: [100, 50], label: "TCP", tone: "" },
    ] };
    expect(rects(d, 200, 200).ls[0].anchor).toBe("end");
  });
});

describe("la vista previa en el panel", () => {
  it("se usa si tiene la forma de unas salidas", () => {
    expect(asOutputs({ voladizo: { flecha: { value: 1, unit: "mm" } } })).not.toBeNull();
    for (const bad of [null, {}, [], { voladizo: 3 }, { voladizo: { flecha: 1 } }, { arbol: [] }]) {
      expect(asOutputs(bad)).toBeNull();
    }
  });
});
