// Tinta (plan §10, D188-D195): pinceles, la tinta en la escena, «quieto», el ancla a la tarjeta
// que marca y el borrador.
import { describe, expect, it } from "vitest";
import { anchorMap, followers } from "./anchors";
import {
  brushOf, erased, freedrawGeometry, inkAnchor, inkData, isHeld, normalizeInk, outline, paint,
  type InkPoint, type Sample,
} from "./ink";

// Ancho del contorno de un trazo horizontal entre x0 y x1.
function widthBetween(poly: number[][], x0: number, x1: number): number {
  const ys = poly.filter(([x]) => x >= x0 && x <= x1).map(([, y]) => y);
  return Math.max(...ys) - Math.min(...ys);
}

// Un trazo horizontal: la primera mitad despacio (2 px entre muestras) y la segunda deprisa (25 px).
const slowFast: InkPoint[] = [
  ...Array.from({ length: 100 }, (_, i) => [i * 2, 0] as InkPoint),
  ...Array.from({ length: 9 }, (_, i) => [200 + (i + 1) * 25, 0] as InkPoint),
];

describe("pinceles", () => {
  it("la pluma adelgaza al ir deprisa y el rotulador no", () => {
    const pen = outline(slowFast, "pluma", 8);
    const marker = outline(slowFast, "rotulador", 8);
    expect(widthBetween(pen, 300, 360)).toBeLessThan(0.8 * widthBetween(pen, 80, 140));
    expect(widthBetween(marker, 300, 360)).toBeGreaterThan(0.9 * widthBetween(marker, 80, 140));
  });

  it("con un lápiz, la pluma sigue su presión", () => {
    const pts: InkPoint[] = Array.from({ length: 80 }, (_, i) => [i * 3, 0, i < 40 ? 0.9 : 0.15]);
    const pen = outline(pts, "pluma", 8, true);
    expect(widthBetween(pen, 160, 200)).toBeLessThan(0.7 * widthBetween(pen, 40, 80));
  });

  it("el subrayador nunca se pinta opaco y multiplica", () => {
    for (const opacity of [0.05, 0.5, 1]) {
      const p = paint({ brush: "subrayador", size: 4, opacity });
      expect(p.opacity).toBeLessThan(0.5);
      expect(p.blend).toBe("multiply");
    }
    expect(paint({ brush: "rotulador", size: 4, opacity: 1 })).toMatchObject({ opacity: 1, grain: true });
  });

  it("un trazo de un solo punto pinta un punto, nunca nada", () => {
    for (const b of ["rotulador", "pluma", "subrayador"] as const) {
      const poly = outline([[10, 10]], b, 6);
      expect(poly.length, b).toBeGreaterThan(2);
    }
  });

  it("un pincel desconocido se pinta como rotulador", () => {
    expect(brushOf("acuarela")).toBe("rotulador");
    expect(brushOf(undefined)).toBe("rotulador");
    expect(brushOf("pluma")).toBe("pluma");
  });
});

const box = { x: 0, y: 0, width: 10, height: 10 };
const ink = (id: string, extra: Record<string, unknown> = {}) => ({
  ...box, id, type: "freedraw", opacity: 0,
  customData: { kind: "ink", ink: { brush: "rotulador", size: 4, opacity: 1 }, ...extra },
});

describe("tinta en la escena", () => {
  it("siempre va con opacity 0 y la que tenía pasa a customData.ink.opacity", () => {
    const e = { ...ink("a"), opacity: 60 };
    const n = normalizeInk(e);
    expect(n.opacity).toBe(0);
    expect((n.customData as { ink: { opacity: number } }).ink.opacity).toBeCloseTo(0.6);
    expect((n.customData as { kind: string }).kind).toBe("ink");
  });

  it("normalizar dos veces da lo mismo, y lo que ya está bien sale igual", () => {
    const n = normalizeInk({ ...ink("a"), opacity: 60 });
    expect(normalizeInk(n)).toBe(n);
  });

  it("un freedraw del lápiz de Excalidraw nunca se toca", () => {
    const pencil = { ...box, id: "p", type: "freedraw", opacity: 100 };
    expect(normalizeInk(pencil)).toBe(pencil);
    expect(inkData(pencil)).toBeNull();
  });

  it("lo que falta o no vale va por defecto", () => {
    const d = inkData({ ...box, id: "x", customData: { kind: "ink", ink: { brush: "?", size: -3, shape: "estrella" } } });
    expect(d).toEqual({ brush: "rotulador", size: 4, opacity: 1 });
  });

  it("la geometría parte del primer punto, como Excalidraw", () => {
    const g = freedrawGeometry([{ x: 10, y: 20 }, { x: 40, y: 10 }, { x: 25, y: 60 }]);
    expect(g).toMatchObject({ x: 10, y: 20, width: 30, height: 50 });
    expect(g.points[0]).toEqual([0, 0]);
  });
});

describe("quieto", () => {
  const moving: Sample[] = Array.from({ length: 30 }, (_, i) => ({ x: i * 6, y: 0, t: i * 16 }));
  const end = moving[moving.length - 1];

  it("con el puntero pulsado 500 ms sin moverse más de 4 px es quieto", () => {
    const held = [...moving, { x: end.x + 2, y: 1, t: end.t + 200 }];
    expect(isHeld(held, end.t + 500, true)).toBe(true);
  });

  it("un trazo lento que sigue moviéndose nunca es quieto", () => {
    const slow: Sample[] = Array.from({ length: 60 }, (_, i) => ({ x: i * 5, y: 0, t: i * 100 }));
    expect(isHeld(slow, 59 * 100 + 90, true)).toBe(false);
  });

  it("ni antes de los 500 ms, ni si ya se ha soltado, ni si nunca se movió", () => {
    expect(isHeld(moving, end.t + 499, true)).toBe(false);
    expect(isHeld(moving, end.t + 900, false)).toBe(false);
    expect(isHeld([{ x: 0, y: 0, t: 0 }, { x: 1, y: 0, t: 10 }], 2000, true)).toBe(false);
  });
});

const card = (id: string, kind: string, x: number, y: number, w = 200, h = 120) => ({
  id, x, y, width: w, height: h, type: "embeddable", customData: { kind },
});

describe("ancla de la tinta", () => {
  const scene = [card("b1", "block", 0, 0), card("p1", "postit", 150, 60, 120, 120), card("b2", "block", 400, 0)];
  const across = (y: number, x0: number, x1: number) => Array.from({ length: 20 }, (_, i) => ({ x: x0 + ((x1 - x0) * i) / 19, y }));

  it("un trazo sobre una tarjeta se ancla a la de más arriba", () => {
    expect(inkAnchor(across(100, 160, 260), undefined, scene)).toBe("p1");
    expect(inkAnchor(across(30, 10, 120), undefined, scene)).toBe("b1");
  });

  it("una flecha, a la de su punta", () => {
    const arrow = [{ x: 300, y: 300 }, { x: 450, y: 60 }, { x: 430, y: 80 }, { x: 450, y: 60 }, { x: 460, y: 85 }];
    expect(inkAnchor(arrow, "flecha", scene)).toBe("b2");
  });

  it("una forma cerrada, a la que rodea", () => {
    const ring = Array.from({ length: 40 }, (_, i) => {
      const t = (i / 40) * 2 * Math.PI;
      return { x: 500 + Math.cos(t) * 150, y: 60 + Math.sin(t) * 100 };
    });
    expect(inkAnchor(ring, "círculo", scene)).toBe("b2");
  });

  it("en vacío, a nada; nunca a una forma o a otra tinta", () => {
    expect(inkAnchor(across(500, 0, 200), undefined, scene)).toBeNull();
    const rect = { id: "r", x: 0, y: 400, width: 300, height: 300, type: "rectangle" };
    expect(inkAnchor(across(500, 10, 200), undefined, [rect, ink("i")])).toBeNull();
  });

  it("mover la tarjeta mueve su tinta; borrar la tarjeta nunca borra la tinta", () => {
    const els = [card("b1", "block", 0, 0), ink("i1", { anchor: "b1" })];
    expect(followers(new Map([["b1", { x: 5, y: 7 }]]), anchorMap(els)).get("i1")).toEqual({ x: 5, y: 7 });
    const gone = [{ ...els[0], isDeleted: true }, els[1]];
    expect(anchorMap(gone).get("i1")).toBe("b1"); // conserva el id, como un post-it
  });
});

describe("borrador", () => {
  const stroke = (id: string, x: number, extra: Record<string, unknown> = {}) => ({
    ...ink(id), x, y: 0, points: [[0, 0], [0, 100]], ...extra,
  });

  it("borra solo la tinta que toca el recorrido, de cualquier autor", () => {
    const els = [stroke("a", 0), stroke("b", 200, { customData: { kind: "ink", author: "agent:design", ink: { size: 4 } } }), stroke("c", 400)];
    expect(erased([{ x: -20, y: 50 }, { x: 220, y: 50 }], els)).toEqual(["a", "b"]);
    expect(erased([{ x: 7, y: 50 }], els)).toEqual(["a"]);
    expect(erased([{ x: 20, y: 50 }], els)).toEqual([]);
  });

  it("borra un lado largo que cruza lejos de sus extremos", () => {
    const side = { ...ink("s"), x: 0, y: 0, points: [[0, 0], [400, 0]] };
    expect(erased([{ x: 200, y: -30 }, { x: 200, y: 30 }], [side])).toEqual(["s"]);
  });

  it("nunca borra una tarjeta, una forma ni un trazo del lápiz de Excalidraw", () => {
    const els = [
      card("b", "block", 0, 0),
      { id: "r", type: "rectangle", x: 0, y: 0, width: 100, height: 100 },
      { id: "p", type: "freedraw", x: 0, y: 0, width: 0, height: 100, points: [[0, 0], [0, 100]] },
    ];
    expect(erased([{ x: -20, y: 50 }, { x: 220, y: 50 }], els)).toEqual([]);
  });
});
