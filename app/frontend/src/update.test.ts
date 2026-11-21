// El actualizador en la interfaz (docs/PLAN_V020.md §4): el aviso sale solo con una versión
// nueva que no se dejó para luego, instalar solo con una versión nueva, y algo raro del backend
// cuenta como desconocido, nunca como un fallo.
import { describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { canInstall, notesOf, parseState, showBanner, statusText } from "./updateState";

describe("actualizador", () => {
  it("el aviso sale solo con una versión nueva que no se dejó para luego", () => {
    const nueva = { estado: "disponible" as const, version: "0.2.0", actual: "0.1.0" };
    expect(showBanner(nueva, null)).toBe(true);
    expect(showBanner(nueva, "0.2.0")).toBe(false);
    expect(showBanner(nueva, "0.1.5")).toBe(true);           // dejar una no deja la siguiente
    expect(showBanner({ estado: "al_dia", actual: "0.2.0" }, null)).toBe(false);
    expect(showBanner({ estado: "error", motivo: "sin red" }, null)).toBe(false);
    expect(showBanner({ estado: "disponible" }, null)).toBe(false);
  });

  it("el aviso enseña las notas del Release que trae el latest.json (PLAN_EXCEL §3.6)", () => {
    expect(notesOf({ estado: "disponible", version: "0.6.0", notas: "## New since v0.5.0\n- Link arrow\n" }))
      .toBe("## New since v0.5.0\n- Link arrow");
    // las líneas cortadas a mano de un párrafo o de un punto se unen; los puntos y títulos, no
    const wrapped = "Intro that\nwraps.\n\n## Title\n- **One** that\n  wraps\n- Two\n\n```\na\nb\n```";
    expect(notesOf({ estado: "disponible", version: "0.6.0", notas: wrapped }))
      .toBe("Intro that wraps.\n\n## Title\n- **One** that wraps\n- Two\n\n```\na\nb\n```");
    expect(notesOf({ estado: "disponible", version: "0.6.0", notas: "  " })).toBeNull();
    expect(notesOf({ estado: "disponible", version: "0.6.0", notas: null })).toBeNull();
    expect(notesOf({ estado: "disponible", version: "0.6.0" })).toBeNull();
  });

  it("instalar solo con una versión nueva y nada instalándose ya", () => {
    expect(canInstall({ estado: "disponible", version: "0.2.0" })).toBe(true);
    expect(canInstall({ estado: "instalando", version: "0.2.0" })).toBe(false);
    expect(canInstall({ estado: "al_dia" })).toBe(false);
  });

  it("algo raro del backend es desconocido, nunca un fallo", () => {
    expect(parseState(null)).toEqual({ estado: "desconocido" });
    expect(parseState([1])).toEqual({ estado: "desconocido" });
    expect(parseState({ estado: "borrar" })).toEqual({ estado: "desconocido" });
    expect(parseState({ estado: "al_dia", actual: "0.2.0" })).toEqual({ estado: "al_dia", actual: "0.2.0" });
  });

  it("cada estado tiene su frase, y en el navegador dice que es cosa de la app de escritorio", () => {
    setLanguage("es");
    expect(statusText({ estado: "disponible", version: "0.2.0", actual: "0.1.0" }, true)).toContain("0.2.0");
    expect(statusText({ estado: "al_dia", actual: "0.2.0" }, true)).toContain("0.2.0");
    expect(statusText({ estado: "error", motivo: "sin red" }, true)).toContain("sin red");
    expect(statusText({ estado: "desconocido" }, false)).not.toBe(statusText({ estado: "desconocido" }, true));
  });
});
