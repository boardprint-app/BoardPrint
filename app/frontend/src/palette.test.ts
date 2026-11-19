// Bandeja y buscador (D91, D96): se encuentra un bloque por su nombre aunque se escriba sin
// tildes y lo que empieza por lo escrito va primero. Los atajos (D97), en shortcuts.test.ts.
import { describe, expect, it } from "vitest";
import { cascade, CASCADE, paletteItems, packsOf, search } from "./palette";

const ty = (title: string, pack: string, description = "") =>
  ({ title, pack, description, inputs: {}, outputs: {}, requires: [], params: {} });
const items = paletteItems(
  { "r.dim": ty("Dimensionado", "acme", "tubos y accionamientos"), "r.arq": ty("Arquitectura", "acme"),
    "d.tubo": ty("Tubo", "demo", "Sección de un tubo") },
  { "r.brazo": { title: "Brazo robótico", pack: "acme", description: "la cadena entera", blocks: [1, 2, 3], links: [] } });

describe("buscador", () => {
  it("sin búsqueda, todo: primero las plantillas", () => {
    expect(search(items, "").map((i) => i.id)).toEqual(["r.brazo", "r.dim", "r.arq", "d.tubo"]);
  });
  it("sin tildes ni mayúsculas, y lo que empieza por lo escrito primero", () => {
    expect(search(items, "ROBOTICO").map((i) => i.id)).toEqual(["r.brazo"]);
    expect(search(items, "tub").map((i) => i.id)).toEqual(["d.tubo", "r.dim"]);
  });
  it("nada si no casa", () => {
    expect(search(items, "xyz")).toEqual([]);
  });
  it("los paquetes en su orden", () => {
    expect(packsOf(items)).toEqual(["acme", "demo"]);
  });
});

describe("dónde nace un bloque", () => {
  it("dos bloques puestos en el mismo sitio nunca quedan uno encima del otro", () => {
    const first = cascade({ x: 100, y: 200 }, []);
    expect(first).toEqual({ x: 100, y: 200 });
    const second = cascade({ x: 100, y: 200 }, [first]);
    expect(second).toEqual({ x: 100 + CASCADE, y: 200 + CASCADE });
    expect(cascade({ x: 100, y: 200 }, [first, second])).toEqual({ x: 100 + 2 * CASCADE, y: 200 + 2 * CASCADE });
  });
  it("lejos de otro, donde se pidió", () => {
    expect(cascade({ x: 100, y: 200 }, [{ x: 400, y: 200 }])).toEqual({ x: 100, y: 200 });
  });
});
