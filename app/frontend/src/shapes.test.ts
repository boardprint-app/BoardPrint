// Reconocimiento de formas (plan §10, D83, D191): con temblor de mano se reconoce cada forma;
// un garabato, una S, una espiral o una palabra a mano nunca se convierten; la forma ideal
// conserva la caja del trazo.
import { describe, expect, it } from "vitest";
import type { Pt } from "./anchors";
import { bounds, isClosed, recognize, type Shape } from "./shapes";

// Generador con semilla fija (mulberry32): los mismos trazos en cada ejecución.
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Puntos cada ~`step` px por una polilínea.
function along(vs: Pt[], step = 4): Pt[] {
  const out: Pt[] = [];
  for (let i = 1; i < vs.length; i++) {
    const a = vs[i - 1], b = vs[i];
    const n = Math.max(1, Math.round(Math.hypot(b.x - a.x, b.y - a.y) / step));
    for (let k = 0; k < n; k++) out.push({ x: a.x + ((b.x - a.x) * k) / n, y: a.y + ((b.y - a.y) * k) / n });
  }
  out.push(vs[vs.length - 1]);
  return out;
}

// Temblor de mano: un ruido fino más una ondulación lenta, de `amp` px.
function hand(ps: Pt[], seed: number, amp = 2): Pt[] {
  const r = rng(seed);
  const ph = r() * 6, ph2 = r() * 6;
  return ps.map((p, i) => ({
    x: p.x + (r() - 0.5) * amp + Math.sin(i / 9 + ph) * amp * 0.6,
    y: p.y + (r() - 0.5) * amp + Math.cos(i / 11 + ph2) * amp * 0.6,
  }));
}

const rot = (p: Pt, deg: number, c: Pt = { x: 0, y: 0 }): Pt => {
  const a = (deg * Math.PI) / 180;
  const dx = p.x - c.x, dy = p.y - c.y;
  return { x: c.x + dx * Math.cos(a) - dy * Math.sin(a), y: c.y + dx * Math.sin(a) + dy * Math.cos(a) };
};

function ellipse(cx: number, cy: number, a: number, b: number, start: number, sweep = 352, deg = 0): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i <= 70; i++) {
    const t = ((start + (sweep * i) / 70) * Math.PI) / 180;
    out.push(rot({ x: cx + a * Math.cos(t), y: cy + b * Math.sin(t) }, deg, { x: cx, y: cy }));
  }
  return out;
}

const samples: Record<Shape, (seed: number) => Pt[]> = {
  recta: (s) => hand(along([{ x: 10, y: 20 }, rot({ x: 230, y: 20 }, (s % 7) * 12, { x: 10, y: 20 })]), s),
  flecha: (s) =>
    hand(
      s % 2
        ? along([{ x: 0, y: 0 }, { x: 220, y: 10 }, { x: 186, y: -14 }])
        : along([{ x: 0, y: 0 }, { x: 220, y: 10 }, { x: 188, y: -12 }, { x: 220, y: 10 }, { x: 190, y: 34 }]),
      s,
    ),
  círculo: (s) => hand(ellipse(100, 100, 80, 80, s * 37), s, 3),
  elipse: (s) => hand(ellipse(100, 100, 130, 60, s * 41, 352, s * 15), s, 3),
  rectángulo: (s) => {
    const deg = s % 3 === 0 ? 0 : (s % 5) * 7 + 10;
    const c = { x: 100, y: 60 };
    const vs = [{ x: 0, y: 0 }, { x: 200, y: 0 }, { x: 200, y: 120 }, { x: 0, y: 120 }, { x: 0, y: 6 }].map((p) => rot(p, deg, c));
    return hand(along(vs), s);
  },
  triángulo: (s) =>
    hand(along([{ x: 0, y: 160 }, { x: 90, y: 0 }, { x: 190, y: 160 }, { x: 8, y: 158 }].map((p) => rot(p, s * 9, { x: 90, y: 100 }))), s),
};

describe("recognize", () => {
  for (const shape of Object.keys(samples) as Shape[]) {
    it(`reconoce ${shape} con temblor de mano en 10 de 10 trazos`, () => {
      const got = Array.from({ length: 10 }, (_, i) => recognize(samples[shape](i + 1))?.shape ?? null);
      expect(got).toEqual(Array(10).fill(shape));
    });
  }

  it("la forma ideal conserva la caja del trazo con un 10 % de margen", () => {
    for (const shape of ["círculo", "elipse", "rectángulo", "triángulo", "recta"] as Shape[]) {
      for (let s = 1; s <= 5; s++) {
        const raw = samples[shape](s);
        const r = recognize(raw)!;
        const a = bounds(raw), b = bounds(r.points);
        const tol = 0.1 * Math.max(a.width, a.height);
        expect(Math.abs(a.x - b.x)).toBeLessThan(tol);
        expect(Math.abs(a.y - b.y)).toBeLessThan(tol);
        expect(Math.abs(a.x + a.width - (b.x + b.width))).toBeLessThan(tol);
        expect(Math.abs(a.y + a.height - (b.y + b.height))).toBeLessThan(tol);
      }
    }
  });

  it("un rectángulo casi recto sale recto", () => {
    const r = recognize(samples.rectángulo(3))!;
    expect(r.shape).toBe("rectángulo");
    expect(Math.abs(r.points[0].y - r.points[1].y)).toBeLessThan(1e-6);
  });

  it("una flecha acaba en su punta y lleva dos barbas", () => {
    const r = recognize(samples.flecha(2))!;
    expect(r.points).toHaveLength(5);
    expect(Math.hypot(r.points[1].x - 220, r.points[1].y - 10)).toBeLessThan(8);
  });

  // Prueba de punta a punta de FF 4.9: una flecha de ~550 px con la punta de ~40 px (del tamaño
  // de siempre) no salía, porque la punta se medía contra el largo del astil.
  it("reconoce una flecha larga con la punta de tamaño normal, en cualquier dirección", () => {
    const got = Array.from({ length: 10 }, (_, i) => {
      const deg = i * 36 + 7, len = 300 + i * 40, h = 25 + (i % 3) * 8, open = 0.4 + (i % 4) * 0.08;
      const a = { x: 0, y: 0 }, tip = rot({ x: len, y: 0 }, deg);
      const barb = (s: number) => rot({ x: len - h * Math.cos(open), y: s * h * Math.sin(open) }, deg);
      const vs = i % 2 ? [a, tip, barb(1)] : [a, tip, barb(1), tip, barb(-1)];
      return recognize(hand(along(vs), i + 1))?.shape ?? null;
    });
    expect(got).toEqual(Array(10).fill("flecha"));
  });

  it("nunca convierte un garabato, una S, una espiral ni una palabra a mano", () => {
    const r = rng(99);
    const scribble: Pt[] = [{ x: 0, y: 0 }];
    for (let i = 0; i < 40; i++) {
      const p = scribble[scribble.length - 1];
      scribble.push({ x: p.x + (r() - 0.5) * 80, y: p.y + (r() - 0.5) * 80 });
    }
    const s = Array.from({ length: 60 }, (_, i) => ({ x: i * 4, y: Math.sin((i / 59) * 2 * Math.PI) * 50 }));
    const spiral = Array.from({ length: 120 }, (_, i) => {
      const t = i / 12;
      return { x: Math.cos(t) * t * 10, y: Math.sin(t) * t * 10 };
    });
    // «ok» de un trazo: una o cerrada que sigue en una k con su subida y su bajada.
    const ok = [
      ...ellipse(20, 30, 18, 20, 180, 360),
      ...along([{ x: 2, y: 30 }, { x: 50, y: 30 }, { x: 52, y: -20 }, { x: 54, y: 50 }, { x: 54, y: 30 }, { x: 80, y: 10 }, { x: 62, y: 30 }, { x: 82, y: 52 }]),
    ];
    // Un zigzag que rellena una zona y vuelve al principio.
    const zig = along([{ x: 0, y: 0 }, { x: 100, y: 10 }, { x: 0, y: 20 }, { x: 100, y: 30 }, { x: 0, y: 40 }, { x: 100, y: 50 }, { x: 0, y: 60 }, { x: 4, y: 4 }]);
    for (const [name, ps] of [["garabato", scribble], ["S", s], ["espiral", spiral], ["ok", ok], ["zigzag", zig]] as const) {
      expect(recognize(hand(along(ps as Pt[]), 7)), name).toBeNull();
    }
  });

  it("un punto o un trazo diminuto no es nada", () => {
    expect(recognize([{ x: 1, y: 1 }])).toBeNull();
    expect(recognize(along([{ x: 0, y: 0 }, { x: 5, y: 3 }], 1))).toBeNull();
  });
});

describe("isClosed", () => {
  it("un círculo casi cerrado es cerrado; una recta y una U no", () => {
    expect(isClosed(ellipse(0, 0, 50, 50, 0, 340))).toBe(true);
    expect(isClosed(along([{ x: 0, y: 0 }, { x: 100, y: 0 }]))).toBe(false);
    expect(isClosed(along([{ x: 0, y: 0 }, { x: 0, y: 100 }, { x: 100, y: 100 }, { x: 100, y: 0 }]))).toBe(false);
  });
});
