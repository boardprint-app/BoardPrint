// La herramienta *Tinta* (plan §10, D189): activarla, el pincel, el color de cada pincel y el
// grosor, y el atajo por defecto.
import { describe, expect, it } from "vitest";
import { DEFAULT_INK_TOOL, HIGHLIGHT_COLOR, INK_COLORS, pickColor, pickMode, pickSize, releaseInk, toggleInk,
         toolColor } from "./inkTool";
import { EXCALIDRAW_KEYS } from "./excalidrawKeys";
import { effectiveShortcuts, SHORTCUTS } from "./shortcuts";

describe("herramienta Tinta", () => {
  it("empieza suelta, con el rotulador en la tinta del skin y el grosor medio", () => {
    expect(DEFAULT_INK_TOOL).toMatchObject({ active: false, mode: "rotulador", size: 4 });
    expect(toolColor(DEFAULT_INK_TOOL)).toBe(INK_COLORS[0]);
  });
  it("el botón y el atajo la activan y la sueltan; soltarla suelta ya no cambia nada", () => {
    const on = toggleInk(DEFAULT_INK_TOOL);
    expect(on.active).toBe(true);
    expect(toggleInk(on).active).toBe(false);
    expect(releaseInk(on).active).toBe(false);
    expect(releaseInk(DEFAULT_INK_TOOL)).toBe(DEFAULT_INK_TOOL);
  });
  it("el subrayador coge el amarillo y cada pincel recuerda su color", () => {
    const hl = pickMode(DEFAULT_INK_TOOL, "subrayador");
    expect(hl.active).toBe(true);
    expect(toolColor(hl)).toBe(HIGHLIGHT_COLOR);
    const red = pickColor(pickMode(hl, "rotulador"), "#e03131");
    expect(toolColor(red)).toBe("#e03131");
    expect(toolColor(pickMode(red, "subrayador"))).toBe(HIGHLIGHT_COLOR);
    expect(toolColor(pickMode(pickMode(red, "subrayador"), "rotulador"))).toBe("#e03131");
  });
  it("con el borrador puesto, un color o un grosor vuelven al último pincel", () => {
    const er = pickMode(pickMode(DEFAULT_INK_TOOL, "pluma"), "borrador");
    expect(er).toMatchObject({ mode: "borrador", brush: "pluma" });
    expect(pickColor(er, "#1971c2")).toMatchObject({ mode: "pluma", colors: { pluma: "#1971c2" } });
    expect(pickSize(er, 8)).toMatchObject({ mode: "pluma", size: 8, active: true });
  });
  it("el atajo `tinta.activar` es M, libre en Excalidraw y sin chocar con otro de la app", () => {
    expect(SHORTCUTS.find((s) => s.id === "tinta.activar")?.default).toBe("M");
    expect(EXCALIDRAW_KEYS.some((k) => k.combo === "M")).toBe(false);
    expect(effectiveShortcuts({})["tinta.activar"]).toBe("M");
  });
});
