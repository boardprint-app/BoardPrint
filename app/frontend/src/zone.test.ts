// `ver_zona` (D171): lo que se pinta de un recuadro o de unos elementos, sin las imágenes pegadas
// con *Excluir adjuntos*, y nunca un PNG de más de 1568 px de lado.
import { describe, expect, it } from "vitest";
import { MAX_SIDE, PADDING, zoneCrop, zoneScale, zoneSelection } from "./zone";

const el = (id: string, x: number, y: number, extra: object = {}) =>
  ({ id, type: "rectangle", x, y, width: 100, height: 50, ...extra });
const scene = [
  el("a", 0, 0),
  el("b", 500, 0),
  el("texto", 10, 10, { type: "text", containerId: "a" }),
  el("foto", 120, 0, { type: "embeddable", customData: { kind: "image", image: { file: "f.png" } } }),
  el("borrado", 0, 0, { isDeleted: true }),
  el("flecha", 200, 300, { type: "arrow", width: 0, height: 0, points: [[0, 0], [-250, -260]] }),
];
const ids = (xs: { id: string }[]) => xs.map((e) => e.id).sort();

describe("lo que entra en la zona", () => {
  it("un recuadro: lo vivo que lo toca, también una flecha que solo lo cruza", () => {
    expect(ids(zoneSelection(scene, { id: "1", rect: { x: 0, y: 0, width: 300, height: 60 } })))
      .toEqual(["a", "flecha", "foto", "texto"]);
  });
  it("unos elementos: esos y el texto que llevan dentro", () => {
    expect(ids(zoneSelection(scene, { id: "1", elements: ["a", "borrado"] }))).toEqual(["a", "texto"]);
  });
  it("con Excluir adjuntos, sin las imágenes pegadas", () => {
    const rect = { x: 0, y: 0, width: 300, height: 60 };
    expect(ids(zoneSelection(scene, { id: "1", rect, excludeImages: true })))
      .toEqual(["a", "flecha", "texto"]);
    expect(zoneSelection(scene, { id: "1", elements: ["foto"], excludeImages: true })).toEqual([]);
  });
});

describe("tamaño de la imagen", () => {
  it("nunca pasa de 1568 px de lado ni amplía más de ×2", () => {
    const big = { x: 0, y: 0, width: 10000, height: 3000 };
    expect(big.width * zoneScale(big, [0, 0, 10000, 3000])).toBeLessThanOrEqual(MAX_SIDE);
    const small = { x: 0, y: 0, width: 100, height: 50 };
    expect(zoneScale(small, [0, 0, 100, 50])).toBe(2);
  });
  it("el lienzo de lo pintado tampoco crece sin límite aunque el recuadro sea pequeño", () => {
    const s = zoneScale({ x: 0, y: 0, width: 100, height: 100 }, [0, 0, 50000, 100]);
    expect((50000 + 2 * PADDING) * s).toBeLessThanOrEqual(8192);
  });
  it("con elementos, el recuadro es su caja con margen; con recuadro, el pedido", () => {
    expect(zoneCrop({ id: "1" }, [10, 20, 110, 70]))
      .toEqual({ x: 10 - PADDING, y: 20 - PADDING, width: 100 + 2 * PADDING, height: 50 + 2 * PADDING });
    const rect = { x: 5, y: 5, width: 50, height: 50 };
    expect(zoneCrop({ id: "1", rect }, [0, 0, 999, 999])).toBe(rect);
  });
});
