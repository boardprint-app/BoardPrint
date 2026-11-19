// Hilos sobre la pizarra (D166, R43, plan §10 «Hilos»): la mini ventana nunca queda por debajo
// de su mínimo (260×170) ni fuera de la vista; un hilo sin anclas vivas no se pinta.
import { describe, expect, it } from "vitest";
import { anchored, CHROME_BOTTOM, CHROME_GAP, CHROME_TOP, chromeFrom, clampWindow, defaultChrome, defaultWindow,
         fullThread, labelSpots, LABEL_H, LABEL_GAP, type Chrome,
         MARGIN, moveWindow, resizeWindow, THREAD_MIN, unplaced, wires, wiresInView } from "./threads";

const view = { width: 1000, height: 700 };
// Dentro de la vista y nunca debajo de la barra de arriba (la píldora, los colores, los botones).
const inside = (r: { x: number; y: number; w: number; h: number }, v = view) =>
  r.x >= MARGIN && r.y >= CHROME_TOP && r.x + r.w <= v.width - MARGIN && r.y + r.h <= v.height - MARGIN;

describe("la mini ventana nunca baja de 260×170 (D60, R43)", () => {
  it("al redimensionar hacia dentro se queda en el mínimo", () => {
    const r = resizeWindow({ x: 100, y: 100, w: 340, h: 260 }, { x: -500, y: -500 }, view);
    expect([r.w, r.h]).toEqual([260, 170]);
    expect([r.x, r.y]).toEqual([100, 100]);              // la esquina de arriba no se mueve
  });
  it("al llegar con un tamaño menor (otra ventana, un fichero viejo) se sube al mínimo", () => {
    const r = clampWindow({ x: 50, y: 50, w: 10, h: 0 }, view);
    expect([r.w, r.h]).toEqual([THREAD_MIN.w, THREAD_MIN.h]);
  });
  it("aunque la vista sea más pequeña que el mínimo: gana el mínimo, pegada arriba a la izquierda", () => {
    const tiny = { width: 200, height: 120 };
    const r = clampWindow({ x: 90, y: 90, w: 340, h: 260 }, tiny);
    expect([r.w, r.h]).toEqual([260, 170]);
    expect([r.x, r.y]).toEqual([MARGIN, CHROME_TOP]);     // la cabecera sigue a la vista, bajo la barra
  });
  it("con valores que no son números, el tamaño por defecto, no NaN", () => {
    const r = clampWindow({ x: NaN, y: Infinity, w: NaN, h: NaN }, view);
    expect(Object.values(r).every(Number.isFinite)).toBe(true);
    expect(inside(r)).toBe(true);
  });
});

describe("la mini ventana nunca queda fuera de la vista (D166)", () => {
  it("arrastrada más allá de cualquier borde, se queda dentro", () => {
    const start = { x: 300, y: 200, w: 340, h: 260 };
    for (const d of [{ x: -5000, y: 0 }, { x: 5000, y: 0 }, { x: 0, y: -5000 }, { x: 0, y: 5000 }, { x: 3000, y: 3000 }]) {
      const r = moveWindow(start, d, view);
      expect(inside(r)).toBe(true);
      expect([r.w, r.h]).toEqual([340, 260]);           // moverla no la encoge
    }
  });
  it("redimensionada más allá del borde, para en el borde", () => {
    const r = resizeWindow({ x: 600, y: 400, w: 300, h: 200 }, { x: 900, y: 900 }, view);
    expect(r.x + r.w).toBe(view.width - MARGIN);
    expect(r.y + r.h).toBe(view.height - MARGIN);
  });
  it("si la pizarra se estrecha (el panel se abre), la ventana se mete dentro", () => {
    const r = clampWindow({ x: 900, y: 600, w: 400, h: 300 }, { width: 700, height: 500 });
    expect(inside(r, { width: 700, height: 500 })).toBe(true);
  });
  it("y si no cabe, se encoge hasta caber, nunca por debajo del mínimo", () => {
    const v = { width: 400, height: 300 };
    const r = clampWindow({ x: 0, y: 0, w: 900, h: 900 }, v);
    expect([r.w, r.h]).toEqual([400 - 2 * MARGIN, 300 - CHROME_TOP - MARGIN]);
    expect(inside(r, v)).toBe(true);
  });
});

describe("dónde abre un hilo nuevo", () => {
  it("a la derecha de su primer ancla si cabe", () => {
    const r = defaultWindow({ x: 100, y: 120, width: 200, height: 80 }, view);
    expect(r.x).toBeGreaterThanOrEqual(300);
    expect(r.y).toBe(120);
  });
  it("a la izquierda si a la derecha no cabe, y siempre dentro", () => {
    const r = defaultWindow({ x: 800, y: 600, width: 150, height: 80 }, view);
    expect(r.x + r.w).toBeLessThanOrEqual(800);
    expect(inside(r)).toBe(true);
  });
  it("una ventana en (0, 0) es la del backend sin colocar; una colocada nunca está ahí", () => {
    expect(unplaced({ x: 0, y: 0 })).toBe(true);
    expect(unplaced(clampWindow({ x: 0, y: 0, w: 300, h: 200 }, view))).toBe(false);
  });
});

describe("qué hilos se pintan (D166: un hilo sin anclas no se pierde, pero no sale)", () => {
  const live = new Set(["a", "b"]);
  it("con alguna ancla viva, sí", () => expect(anchored(["zz", "b"], live)).toBe(true));
  it("con todas borradas, no (aunque el backend aún no lo sepa)", () => expect(anchored(["zz", "yy"], live)).toBe(false));
  it("pantalla completa, solo uno: el último que cambió, y nunca uno sin anclas", () => {
    const ts = [
      { id: "1", anchors: ["a"], layout: { size: "full" }, updated: "2026-11-15T10:00:00" },
      { id: "2", anchors: ["b"], layout: { size: "full" }, updated: "2026-11-15T11:00:00" },
      { id: "3", anchors: ["zz"], layout: { size: "full" }, updated: "2026-11-15T12:00:00" },
    ];
    expect(fullThread(ts, live, (t) => t.anchors)?.id).toBe("2");
  });
});

describe("la etiqueta de un hilo minimizado va junto a su primer elemento", () => {
  const boxes = new Map([["a", { x: 100, y: 250, width: 200, height: 100 }], ["b", { x: 500, y: 300, width: 80, height: 40 }]]);
  const w = () => 200;
  it("encima de su primer ancla viva, alineada a su izquierda", () => {
    const s = labelSpots([{ id: "h", anchors: ["zz", "b", "a"] }], boxes, view, w);
    expect(s.get("h")).toEqual({ x: 500, y: 300 - LABEL_H - LABEL_GAP });
  });
  it("dos hilos en el mismo elemento no se pisan: se apilan", () => {
    const s = labelSpots([{ id: "h1", anchors: ["a"] }, { id: "h2", anchors: ["a", "b"] }], boxes, view, w);
    expect(s.get("h1")!.y - s.get("h2")!.y).toBe(LABEL_H + LABEL_GAP);
  });
  it("nunca cortada por los lados de la vista (un archivo pegado al panel)", () => {
    const edge = new Map([["a", { x: 950, y: 200, width: 200, height: 40 }], ["b", { x: -50, y: 200, width: 100, height: 40 }]]);
    const s = labelSpots([{ id: "h1", anchors: ["a"] }, { id: "h2", anchors: ["b"] }], edge, view, w);
    expect(s.get("h1")!.x + 200).toBeLessThanOrEqual(view.width - MARGIN);
    expect(s.get("h2")!.x).toBe(MARGIN);
  });
  it("sin anclas vivas, sin etiqueta", () =>
    expect(labelSpots([{ id: "h", anchors: ["zz"] }], boxes, view, w).has("h")).toBe(false));
});

describe("el hilo de la ventana a cada ancla", () => {
  it("una línea por ancla, de borde a borde", () => {
    const w = wires({ x: 0, y: 0, width: 100, height: 100 },
                    [{ x: 300, y: 0, width: 50, height: 50 }, { x: 0, y: 300, width: 50, height: 50 }]);
    expect(w).toHaveLength(2);
    expect(w[0].from.x).toBe(100);
    expect(w[0].to.x).toBe(300);
  });
  it("si la ventana tapa el ancla, sin línea", () =>
    expect(wires({ x: 0, y: 0, width: 400, height: 400 }, [{ x: 10, y: 10, width: 50, height: 50 }])).toHaveLength(0));
});

// Paso 5b: la interfaz fija de la pizarra (barra de arriba, Filtro, herramientas y zoom de abajo)
// nunca queda tapada por una etiqueta, y una etiqueta de un ancla fuera de la vista no se pinta.
// La interfaz se mide del DOM (`measureChrome`): la regla vale con la de una fila sin medir y con
// una barra partida en dos filas, como la deja *Nuevo archivo* a 1440×900 con el panel abierto.
const twoRows = chromeFrom(view,
  [{ x: 16, y: 16, w: 36, h: 36 }, { x: 68, y: 16, w: 230, h: 40 }, { x: 294, y: 16, w: 690, h: 69 }],
  [{ x: 325, y: 640, w: 350, h: 44 }, { x: 16, y: 648, w: 214, h: 36 }, { x: 948, y: 648, w: 36, h: 36 }],
  [{ x: 912, y: 93, w: 72, h: 31 }]);
const CHROMES: [string, Chrome][] = [["una fila, sin medir", defaultChrome(view)], ["la barra en dos filas", twoRows]];

describe("lo medido del DOM", () => {
  it("la franja libre empieza debajo de la fila más baja de la barra y acaba encima de lo de abajo", () => {
    expect(twoRows.top).toBe(16 + 69 + CHROME_GAP);
    expect(twoRows.bottom).toBe(640 - CHROME_GAP);
  });
  it("sin nada medido, las constantes", () =>
    expect(chromeFrom(view, [], [{ x: 0, y: 0, w: 0, h: 0 }], [])).toMatchObject({ top: CHROME_TOP, bottom: view.height - CHROME_BOTTOM }));
});

describe.each(CHROMES)("una etiqueta de hilo nunca tapa la interfaz fija de la pizarra (%s)", (_name, chrome) => {
  const w = () => 220;
  const hits = (p: { x: number; y: number }, r: { x: number; y: number; w: number; h: number }) =>
    p.x < r.x + r.w && p.x + 220 > r.x && p.y < r.y + r.h && p.y + LABEL_H > r.y;
  const spot = (b: { x: number; y: number; width: number; height: number }, n = 1) =>
    labelSpots(Array.from({ length: n }, (_, i) => ({ id: `h${i}`, anchors: ["a"] })), new Map([["a", b]]), view, w, chrome);

  it("en ningún sitio de la vista, ni apiladas", () => {
    for (let x = -200; x <= view.width; x += 37) {
      for (let y = -200; y <= view.height; y += 23) {
        for (const p of spot({ x, y, width: 180, height: 90 }, 3).values()) {
          for (const c of chrome.zones) expect(hits(p, c), `ancla en ${x},${y}: ${JSON.stringify(p)}`).toBe(false);
          expect(p.y).toBeGreaterThanOrEqual(chrome.top);
          expect(p.y + LABEL_H).toBeLessThanOrEqual(chrome.bottom);
        }
      }
    }
  });
  it("un ancla justo debajo de la barra de arriba (de su fila más baja): la etiqueta va debajo del ancla", () => {
    const b = { x: 200, y: chrome.top + 4, width: 180, height: 90 };
    expect(spot(b).get("h0")!.y).toBeGreaterThanOrEqual(b.y + b.height);
  });
  it("un ancla fuera de la vista por arriba o por la izquierda: sin etiqueta (el hilo sigue en la pestaña)", () => {
    expect(spot({ x: 200, y: -300, width: 180, height: 90 }).size).toBe(0);
    expect(spot({ x: -400, y: 300, width: 180, height: 90 }).size).toBe(0);
    expect(spot({ x: 200, y: view.height + 20, width: 180, height: 90 }).size).toBe(0);
  });
  it("dos etiquetas de anclas distintas tampoco se pisan (debajo de una, encima de la otra)", () => {
    // Un bloque pegado a la barra (su etiqueta va debajo) con un post-it justo debajo.
    const boxes = new Map([["blq", { x: 30, y: chrome.top + 2, width: 250, height: 200 }],
                           ["pst", { x: 30, y: chrome.top + 280, width: 230, height: 150 }]]);
    const s = labelSpots([{ id: "p", anchors: ["pst"] }, { id: "b", anchors: ["blq"] }], boxes, view, w, chrome);
    const ps = [...s.values()];
    for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++) {
      expect(ps[i].y + LABEL_H <= ps[j].y || ps[j].y + LABEL_H <= ps[i].y || ps[i].x + 220 <= ps[j].x
             || ps[j].x + 220 <= ps[i].x).toBe(true);
    }
    expect(s.has("p")).toBe(true);
  });
  it("un ancla escondida bajo la barra de arriba cuenta como fuera de la vista", () =>
    expect(spot({ x: 200, y: 10, width: 180, height: chrome.top - 20 }).size).toBe(0));
  it("una ventana nunca se pone debajo de la barra de arriba", () => {
    for (const y of [-500, 0, 20, chrome.top - 1]) {
      expect(clampWindow({ x: 100, y, w: 340, h: 260 }, view, chrome).y).toBeGreaterThanOrEqual(chrome.top);
      expect(moveWindow({ x: 100, y: 300, w: 340, h: 260 }, { x: 0, y: y - 300 }, view, chrome).y).toBeGreaterThanOrEqual(chrome.top);
    }
  });
});

describe.each(CHROMES)("la línea de un hilo nunca cruza por encima de la barra de arriba ni de la de abajo (%s)", (_n, chrome) => {
  const from = { x: 100, y: 200, width: 220, height: LABEL_H };
  it("a un ancla escondida bajo la barra de arriba (o fuera por arriba), sin línea", () => {
    expect(wiresInView(from, [{ x: 400, y: 0, width: 200, height: chrome.top - 10 }], view, chrome)).toHaveLength(0);
    expect(wiresInView(from, [{ x: 400, y: -400, width: 200, height: 100 }], view, chrome)).toHaveLength(0);
  });
  it("a un ancla en la vista, sí", () =>
    expect(wiresInView(from, [{ x: 400, y: 300, width: 200, height: 100 }], view, chrome)).toHaveLength(1));
  it("ningún tramo pasa por la barra de arriba ni por la de abajo", () => {
    for (let y = -300; y < view.height; y += 17) {
      for (const w of wiresInView(from, [{ x: 500, y, width: 120, height: 60 }], view, chrome)) {
        expect(Math.min(w.from.y, w.to.y)).toBeGreaterThanOrEqual(chrome.top);
        expect(Math.max(w.from.y, w.to.y)).toBeLessThanOrEqual(chrome.bottom);
      }
    }
  });
});
