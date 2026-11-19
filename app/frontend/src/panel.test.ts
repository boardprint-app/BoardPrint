// Tamaño mínimo (plan D60, §10) del panel derecho (D174): nunca por debajo de 320 px, ni al
// arrastrar ni con unos ajustes que guarden menos; nunca más del 60 % de la ventana, ni a costa
// de dejar la pizarra por debajo de su propio mínimo.
import { describe, expect, it } from "vitest";
import { BOARD_MIN, clampPanel, PANEL_DEFAULT } from "./panel";

describe("ancho del panel derecho", () => {
  it("nunca baja de 320 px", () => {
    expect(clampPanel(100, 1440)).toBe(320);
    expect(clampPanel(-40, 1440)).toBe(320);
    expect(clampPanel(319.6, 1440)).toBe(320);
  });

  it("nunca pasa del 60 % de la ventana", () => {
    expect(clampPanel(3000, 2560)).toBe(1536);
    expect(clampPanel(500, 1440)).toBe(500);
  });

  it("nunca deja la pizarra por debajo de su mínimo", () => {
    expect(clampPanel(1200, 1440)).toBe(1440 - BOARD_MIN);
    expect(clampPanel(1200, 1920)).toBe(1920 - BOARD_MIN);
  });

  it("en una ventana estrecha manda el mínimo, no el 60 %", () => {
    expect(clampPanel(400, 400)).toBe(320);
  });

  it("un ancho que no es un número es el de por defecto", () => {
    expect(clampPanel(Number.NaN, 1440)).toBe(PANEL_DEFAULT);
  });
});
