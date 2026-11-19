// Fuentes (plan D184): siempre con respaldo; «sistema» es la de siempre; la de la pizarra va a
// los textos nuevos de Excalidraw con su id.
import { describe, expect, it } from "vitest";
import { boardFontId, fontVars } from "./fonts";

describe("fuentes", () => {
  it("«sistema» y Excalifont dejan las de siempre (se quita la variable)", () => {
    expect(fontVars({ interfaz: "sistema", pizarra: "Excalifont", chat: "sistema", numeros: "sistema" }))
      .toEqual({ "--f-ui": null, "--f-board": null, "--f-chat": null, "--f-num": null });
    expect(fontVars(null)["--f-ui"]).toBeNull();
  });
  it("una elegida lleva detrás la del sistema", () => {
    const v = fontVars({ interfaz: "Georgia", chat: "Cascadia", pizarra: "Nunito" });
    expect(v["--f-ui"]).toMatch(/^Georgia, system-ui/);
    expect(v["--f-chat"]).toMatch(/^"Cascadia Code", "Cascadia Mono", Cascadia, system-ui/);
    expect(v["--f-board"]).toMatch(/^Nunito, .*cursive$/);
  });
  it("una que no conoce, la de siempre", () => {
    expect(fontVars({ interfaz: "Papyrus" })["--f-ui"]).toBeNull();
  });
  it("el id de Excalidraw 0.18, Excalifont si no se conoce", () => {
    expect(boardFontId("Excalifont")).toBe(5);
    expect(boardFontId("Nunito")).toBe(6);
    expect(boardFontId("Comic Shanns")).toBe(8);
    expect(boardFontId("Liberation Sans")).toBe(9);
    expect(boardFontId("Cascadia")).toBe(3);
    expect(boardFontId("Papyrus")).toBe(5);
  });
});
