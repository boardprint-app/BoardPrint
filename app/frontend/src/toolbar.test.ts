// La barra de arriba cabe en una fila junto a la píldora del proyecto (O17).
import { describe, expect, it } from "vitest";
import { barDensity } from "./toolbar";

describe("barra de arriba", () => {
  it("a 1440 px con el panel derecho abierto, solo iconos: cabe en una fila y deja ver el nombre", () => {
    expect(barDensity(1440 - 420)).toBe(2);
  });
  it("a 1440 px sin panel, solo los botones de herramienta se quedan en icono", () => {
    expect(barDensity(1440)).toBe(1);
  });
  it("con sitio de sobra, todo con su texto", () => {
    expect(barDensity(1920)).toBe(0);
    expect(barDensity(1920 - 420)).toBe(0);
  });
});
