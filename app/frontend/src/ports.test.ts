// Conexiones entre enchufes (D88, R18): la flecha acaba exactamente en el enchufe, su recorrido
// solo tiene tramos horizontales y verticales, y solo se ofrece una entrada libre del mismo tipo.
// Y el color de cada tipo (§10 «Colores de puerto», P67).
import { describe, expect, it } from "vitest";
import { BIND_GAP, compatibleInputs, distToPolyline, elbowRoute, fixedPointFor, labelSpot, portColor, socketPoint,
         socketY, type PortTypes } from "./ports";

const orthogonal = (pts: { x: number; y: number }[]) =>
  pts.slice(1).every((p, i) => p.x === pts[i].x || p.y === pts[i].y);

describe("colores de puerto (P67)", () => {
  const ports: PortTypes = { "acme.pieza": { label: "pieza", color: "#123456" },
                             "acme.sin": { label: "sin color", color: null }, "acme.viejo": { label: "viejo" } };
  it("un tipo con color en el [ports] de su paquete se pinta siempre de ese color", () => {
    expect(portColor("acme.pieza", ports)).toBe("#123456");
    expect(portColor("acme.pieza", { ...ports, "cad.modelo": { label: "", color: null } })).toBe("#123456");
  });
  it("uno sin él, del de la paleta según su nombre, siempre el mismo", () => {
    for (const t of ["acme.sin", "acme.viejo", "acme.nadie"]) {
      expect(portColor(t, ports)).toMatch(/^#[0-9a-f]{6}$/);
      expect(portColor(t, ports)).toBe(portColor(t, {}));
    }
    expect(portColor("acme.sin", ports)).not.toBe(portColor("acme.pieza", ports));
  });
  it("los del núcleo tienen el suyo", () => {
    expect(portColor("cad.modelo", {})).toBe("#8d99a6");
    expect(portColor("archivo.step", {})).toBe(portColor("archivo", {}));
    expect(portColor("carpeta", {})).not.toBe(portColor("archivo", {}));
  });
});

describe("fixedPoint", () => {
  it("queda a 5 px por fuera del borde, a la altura del enchufe", () => {
    const [fx, fy] = fixedPointFor("out", 1, 280, 400);
    expect(fx * 280).toBeCloseTo(280 + BIND_GAP);
    expect(fy * 400).toBeCloseTo(socketY(1));
    const [ix] = fixedPointFor("in", 0, 280, 400);
    expect(ix * 280).toBeCloseTo(-BIND_GAP);
  });
  it("al crecer el bloque cambia la fracción, nunca la altura del enchufe", () => {
    const a = fixedPointFor("in", 0, 280, 220)[1] * 220;
    const b = fixedPointFor("in", 0, 280, 700)[1] * 700;
    expect(a).toBeCloseTo(b);
  });
  it("el punto de la escena es el mismo que da el fixedPoint", () => {
    const r = { x: 100, y: 50, width: 280, height: 300 };
    const [fx, fy] = fixedPointFor("out", 0, r.width, r.height);
    const p = socketPoint("out", 0, r);
    expect(p.x).toBeCloseTo(r.x + fx * r.width);
    expect(p.y).toBeCloseTo(r.y + fy * r.height);
  });
});

describe("recorrido en ángulo", () => {
  const src = { x: 0, y: 0, width: 280, height: 200 };
  it("hacia delante: tres tramos, o uno si están a la misma altura", () => {
    const dst = { x: 400, y: 100, width: 280, height: 200 };
    const r = elbowRoute({ x: 285, y: 50 }, { x: 395, y: 150 }, src, dst);
    expect(r).toHaveLength(4);
    expect(orthogonal(r)).toBe(true);
    expect(elbowRoute({ x: 285, y: 50 }, { x: 395, y: 50 }, src, dst)).toHaveLength(2);
  });
  it("hacia atrás rodea por debajo sin cruzar los bloques", () => {
    const dst = { x: 0, y: 300, width: 280, height: 200 };
    const r = elbowRoute({ x: 285, y: 50 }, { x: -5, y: 350 }, src, dst);
    expect(orthogonal(r)).toBe(true);
    expect(r[0]).toEqual({ x: 285, y: 50 });
    expect(r[r.length - 1]).toEqual({ x: -5, y: 350 });
    expect(r[2].y).toBe(250);           // por el hueco entre los dos
  });
});

describe("nombre sobre la línea", () => {
  it("va en mitad del tramo horizontal más largo", () => {
    expect(labelSpot([[0, 0], [40, 0], [40, 300], [200, 300]])).toEqual({ x: 120, y: 300 });
  });
  it("en una línea recta, en su mitad", () => {
    expect(labelSpot([[0, 0], [100, 0]])).toEqual({ x: 50, y: 0 });
  });
});

describe("entradas compatibles", () => {
  it("solo las libres del mismo tipo", () => {
    const ins = { a: "p.x", b: "p.x", c: "p.y" };
    expect(compatibleInputs("p.x", ins, [])).toEqual(["a", "b"]);
    expect(compatibleInputs("p.x", ins, ["a"])).toEqual(["b"]);
    expect(compatibleInputs("p.z", ins, [])).toEqual([]);
  });
});

describe("ratón sobre una conexión (R37)", () => {
  const pts = [[0, 0], [100, 0], [100, 50]] as const;
  it("mide hasta el tramo más cercano, con la flecha en su sitio", () => {
    expect(distToPolyline(pts, { x: 10, y: 10 }, { x: 60, y: 14 })).toBeCloseTo(4);
    expect(distToPolyline(pts, { x: 10, y: 10 }, { x: 116, y: 40 })).toBeCloseTo(6);
  });
  it("fuera de los extremos cuenta hasta el extremo", () => {
    expect(distToPolyline(pts, { x: 0, y: 0 }, { x: -3, y: -4 })).toBeCloseTo(5);
  });
});
