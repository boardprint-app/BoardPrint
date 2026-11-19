import { describe, expect, it } from "vitest";
import { canvasOffsets, fitShortcut, FIT_PADDING as P } from "./fit";
import { setUserShortcuts } from "./shortcuts";

const key = (code: string, mods: Partial<{ shiftKey: boolean; ctrlKey: boolean; metaKey: boolean; altKey: boolean }> = {}) =>
  ({ code, shiftKey: true, ctrlKey: false, metaKey: false, altKey: false, ...mods });
const box = (top: number, bottom: number, left: number, right: number) => ({ top, bottom, left, right });

describe("atajos de encuadre", () => {
  it("Mayús+1, 2 y 3 por la tecla física", () => {
    expect(fitShortcut(key("Digit1"))).toBe("all");
    expect(fitShortcut(key("Digit2"))).toBe("selection");
    expect(fitShortcut(key("Digit3"))).toBe("viewport");
  });
  it("sin Mayús, con Ctrl o Alt, u otra tecla, no es un encuadre", () => {
    expect(fitShortcut(key("Digit1", { shiftKey: false }))).toBeNull();
    expect(fitShortcut(key("Digit1", { ctrlKey: true }))).toBeNull();
    expect(fitShortcut(key("Digit1", { metaKey: true }))).toBeNull();
    expect(fitShortcut(key("Digit2", { altKey: true }))).toBeNull();
    expect(fitShortcut(key("Digit4"))).toBeNull();
  });
});

describe("Mayús+1, 2 y 3 movidos a otra tecla (R49)", () => {
  it("siguen encuadrando con el de la app, nunca con el de Excalidraw", () => {
    setUserShortcuts({ "view.fit_all": "Alt+1" });
    expect(fitShortcut(key("Digit1"))).toBe("all");
    expect(fitShortcut(key("Digit1", { shiftKey: false, altKey: true }))).toBe("all");
    setUserShortcuts({});
  });
  it("no se los quitan a otra acción de la app que los usa", () => {
    setUserShortcuts({ "view.fit_all": "", "blocks.search": "Mayús+1" });
    expect(fitShortcut(key("Digit1"))).toBeNull();
    setUserShortcuts({});
  });
});

describe("márgenes de la interfaz", () => {
  const view = { width: 1440, height: 900 };

  it("la barra de herramientas abajo quita sitio por abajo, nunca por arriba", () => {
    // Medido en FF 4.8: la barra de Excalidraw en 840-884; arriba, la fila del menú hasta 76
    const o = canvasOffsets(view, { top: [box(16, 76, 0, 1440), box(16, 56, 68, 290)],
                                    toolbar: box(840, 884, 446, 994), left: null, right: null });
    expect(o).toEqual({ top: 76 + P, bottom: 900 - 840 + P, left: P, right: P });
    expect(900 - o.top - o.bottom).toBeGreaterThan(700);   // queda sitio para encuadrar
  });

  it("el panel de propiedades y la biblioteca quitan sitio a los lados", () => {
    const o = canvasOffsets(view, { top: [], toolbar: null, left: box(80, 820, 0, 216),
                                    right: box(0, 900, 1080, 1440) });
    expect(o).toEqual({ top: P, bottom: P, left: 216 + P, right: 360 + P });
  });
});
