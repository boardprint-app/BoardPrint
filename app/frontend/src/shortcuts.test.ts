// Atajos (plan D97, D185, §10): un choque siempre sale con el nombre de lo otro; nunca quedan
// dos acciones con el mismo atajo; Ctrl+Mayús+B no choca con Ctrl+B; un atajo nunca salta
// mientras se escribe; unos atajos ilegibles dejan los de por defecto. Y la lista de Excalidraw
// vale solo para la versión instalada.
import { afterEach, describe, expect, it } from "vitest";
import pkg from "../package.json";
import { EXCALIDRAW_KEYS, EXCALIDRAW_VERSION } from "./excalidrawKeys";
import { fitShortcut } from "./fit";
import { ES } from "./locales/es";
import {
  assignChanges, clash, comboFromEvent, effectiveShortcuts, matches, normalizeCombo, parseCombo,
  setUserShortcuts, shortcut, SHORTCUTS, typing,
} from "./shortcuts";

type Mods = Partial<{ ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean }>;
const ev = (key: string, mods: Mods = {}, code?: string) =>
  ({ key, code: code ?? (/^[a-z]$/i.test(key) ? `Key${key.toUpperCase()}` : ""),
     ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods });

afterEach(() => setUserShortcuts({}));

describe("atajos", () => {
  it("Ctrl+B por defecto, y Cmd+B en Mac", () => {
    expect(shortcut("blocks.search")).toBe("Ctrl+B");
    expect(matches(ev("b", { ctrlKey: true }), "Ctrl+B")).toBe(true);
    expect(matches(ev("B", { metaKey: true }), "Ctrl+B")).toBe(true);
  });
  it("solo con la combinación exacta: Ctrl+Mayús+B no es Ctrl+B", () => {
    expect(matches(ev("b"), "Ctrl+B")).toBe(false);
    expect(matches(ev("b", { ctrlKey: true, shiftKey: true }), "Ctrl+B")).toBe(false);
    expect(matches(ev("B", { ctrlKey: true, shiftKey: true }), "Ctrl+Mayús+B")).toBe(true);
    expect(parseCombo("Ctrl+Mayús+K")).toEqual({ ctrl: true, shift: true, alt: false, key: "k" });
  });
  it("las cifras por la tecla física: con Mayús, `key` es «!»", () => {
    expect(matches(ev("!", { shiftKey: true }, "Digit1"), "Mayús+1")).toBe(true);
    expect(matches(ev("1", {}, "Digit1"), "Mayús+1")).toBe(false);
    expect(matches(ev("!", { shiftKey: true }, "Digit2"), "Mayús+1")).toBe(false);
  });
  it("una letra por la que pone el teclado, y por la tecla física si no es latina", () => {
    expect(matches(ev("q", { ctrlKey: true }, "KeyA"), "Ctrl+Q")).toBe(true);    // AZERTY
    expect(matches(ev("Ω", { altKey: true }, "KeyZ"), "Alt+Z")).toBe(true);      // Alt en Mac
  });
  it("sin atajo nunca salta", () => {
    expect(matches(ev("b", { ctrlKey: true }), "")).toBe(false);
  });
  it("nunca mientras se escribe, ni dentro de Ajustes", () => {
    // Sin DOM en los tests: basta con lo que usa `typing`, `closest`.
    const input = (type: string | null) => ({
      closest: (sel: string) => (sel === "input" ? { getAttribute: () => type } : null),
    });
    const inDialog = { closest: (sel: string) => (sel.includes("aria-modal") ? {} : null) };
    const onCanvas = { closest: () => null };
    expect(typing(input(null) as unknown as EventTarget)).toBe(true);        // <input> sin tipo
    expect(typing(input("number") as unknown as EventTarget)).toBe(true);
    expect(typing(inDialog as unknown as EventTarget)).toBe(true);
    expect(typing(onCanvas as unknown as EventTarget)).toBe(false);
  });
  it("con el foco en una herramienta de la barra de Excalidraw, los atajos siguen (e2e FF 4.7)", () => {
    const radio = { closest: (sel: string) => (sel === "input" ? { getAttribute: () => "radio" } : null) };
    expect(typing(radio as unknown as EventTarget)).toBe(false);
  });
  it("cada acción tiene su texto", () => {
    expect(SHORTCUTS.filter((s) => !(s.label in ES))).toEqual([]);
  });
});

describe("forma canónica y grabar", () => {
  it("como `normalize_combo` del backend", () => {
    expect(normalizeCombo("alt+shift+cmd+b")).toBe("Ctrl+Mayús+Alt+B");
    expect(normalizeCombo("mayus+1")).toBe("Mayús+1");
    expect(normalizeCombo("")).toBe("");
    expect(normalizeCombo("Ctrl+Ctrl+B")).toBeNull();
    expect(normalizeCombo("Ctrl+F1")).toBeNull();
    expect(normalizeCombo("Hiper+B")).toBeNull();
    expect(normalizeCombo(3)).toBeNull();
  });
  it("una pulsación da su combinación; un modificador solo, ninguna", () => {
    expect(comboFromEvent(ev("B", { ctrlKey: true, shiftKey: true }))).toBe("Ctrl+Mayús+B");
    expect(comboFromEvent(ev("\"", { shiftKey: true }, "Digit2"))).toBe("Mayús+2");
    expect(comboFromEvent(ev("Control", { ctrlKey: true }, "ControlLeft"))).toBeNull();
    expect(comboFromEvent(ev("F5", {}, "F5"))).toBeNull();
  });
});

describe("choques", () => {
  it("con otra acción de la app, con su nombre", () => {
    const c = clash("blocks.search", "Mayús+1", {});
    expect(c).toEqual({ con: "app", nombre: ES["atajos.accion.fit_all"], id: "view.fit_all" });
  });
  it("con Excalidraw, con el nombre de lo que pierde la tecla", () => {
    expect(clash("blocks.search", "R", {})).toEqual({ con: "excalidraw", nombre: ES["excalidraw.rectangulo"] });
    expect(clash("blocks.search", "Ctrl+Z", {})).toEqual({ con: "excalidraw", nombre: ES["excalidraw.deshacer"] });
  });
  it("un choque siempre sale con un nombre", () => {
    for (const k of EXCALIDRAW_KEYS) {
      const c = clash("blocks.search", k.combo, {});
      expect(c?.nombre, k.combo).toBeTruthy();
      expect(c?.nombre).not.toBe(k.name);          // traducido, no la clave
    }
  });
  it("Ctrl+Mayús+B no choca con Ctrl+B, ni una acción consigo misma", () => {
    expect(clash("view.fit_all", "Ctrl+Mayús+B", {})).toBeNull();
    expect(clash("blocks.search", "Ctrl+B", {})).toBeNull();
  });
  it("encuadrar con Mayús+1 no choca con el encuadre de Excalidraw, que atiende la app", () => {
    expect(clash("view.fit_all", "Mayús+1", {})).toBeNull();
    expect(clash("blocks.search", "Mayús+1", { "view.fit_all": "" })?.con).toBe("excalidraw");
  });
  it("un atajo quitado ya no choca", () => {
    expect(clash("blocks.search", "Mayús+2", { "view.fit_selection": "" })?.con).toBe("excalidraw");
    expect(clash("view.fit_all", "Ctrl+B", { "blocks.search": "" })).toBeNull();
  });
});

describe("nunca dos acciones con el mismo atajo", () => {
  const noRepeats = (m: Record<string, string>) => {
    const used = Object.values(m).filter(Boolean);
    expect(new Set(used).size).toBe(used.length);
  };
  it("al confirmar un choque con la app, la otra se queda sin atajo en el mismo cambio", () => {
    const changes = assignChanges("blocks.search", "Mayús+1", {});
    expect(changes).toEqual({ "blocks.search": "Mayús+1", "view.fit_all": "" });
    noRepeats(effectiveShortcuts(changes));
  });
  it("con Excalidraw solo cambia esa acción", () => {
    expect(assignChanges("blocks.search", "R", {})).toEqual({ "blocks.search": "R" });
  });
  it("en cadena, sin repetidos", () => {
    let mine: Record<string, string> = {};
    for (const [a, c] of [["blocks.search", "Mayús+2"], ["view.fit_all", "Mayús+2"], ["view.fit_viewport", "Ctrl+B"]]) {
      mine = { ...mine, ...assignChanges(a, c, mine) };
      noRepeats(effectiveShortcuts(mine));
    }
    expect(effectiveShortcuts(mine)).toEqual({ "blocks.search": "", "view.fit_all": "Mayús+2",
                                               "view.fit_selection": "", "view.fit_viewport": "Ctrl+B",
                                               "tinta.activar": "M" });
  });
  it("un settings.toml editado a mano: manda el del usuario y la otra se queda sin atajo", () => {
    const m = effectiveShortcuts({ "blocks.search": "Mayús+1" });
    expect(m["blocks.search"]).toBe("Mayús+1");
    expect(m["view.fit_all"]).toBe("");
    noRepeats(m);
    // dos del usuario iguales: las dos vuelven al de por defecto
    noRepeats(effectiveShortcuts({ "blocks.search": "Ctrl+K", "view.fit_all": "Ctrl+K" }));
  });
});

describe("atajos ilegibles", () => {
  it("dejan los de por defecto", () => {
    const defaults = Object.fromEntries(SHORTCUTS.map((s) => [s.id, s.default]));
    expect(effectiveShortcuts(null)).toEqual(defaults);
    expect(effectiveShortcuts("Ctrl+B")).toEqual(defaults);
    expect(effectiveShortcuts({ "blocks.search": "Ctrl+F1", "view.fit_all": 7 })).toEqual(defaults);
  });
  it("los del usuario mandan al pulsar, y el encuadre los sigue", () => {
    setUserShortcuts({ "view.fit_all": "Alt+1", "blocks.search": "" });
    expect(shortcut("blocks.search")).toBe("");
    const key = (code: string, mods: Mods) => ({ code, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods });
    expect(fitShortcut(key("Digit1", { altKey: true }))).toBe("all");
    // Mayús+1 ya no es de ninguna acción: la app lo sigue atendiendo, no Excalidraw (R49)
    expect(fitShortcut(key("Digit1", { shiftKey: true }))).toBe("all");
    expect(fitShortcut(key("Digit2", { shiftKey: true }))).toBe("selection");
  });
});

describe("atajos de Excalidraw", () => {
  it("la lista es de la versión instalada (si cambia, se repasa excalidrawKeys.ts)", () => {
    expect(pkg.dependencies["@excalidraw/excalidraw"]).toBe(EXCALIDRAW_VERSION);
  });
  it("en forma canónica, sin repetidos y con su texto", () => {
    for (const k of EXCALIDRAW_KEYS) {
      expect(normalizeCombo(k.combo), k.combo).toBe(k.combo);
      expect(k.name in ES, k.name).toBe(true);
    }
    const combos = EXCALIDRAW_KEYS.map((k) => k.combo);
    expect(new Set(combos).size).toBe(combos.length);
  });
  it("los que atiende la app son de acciones que existen", () => {
    const ids = new Set(SHORTCUTS.map((s) => s.id));
    expect(EXCALIDRAW_KEYS.filter((k) => k.app && !ids.has(k.app))).toEqual([]);
  });
});
