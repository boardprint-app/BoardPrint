// La animación de un post-it (D143, D175, R42; plan §10 «Animaciones en post-its»): el marco
// nunca ve la app, fuera de la vista no se monta y los colores son los del tema.
import { describe, expect, it } from "vitest";
import { animationUrl, FORBIDDEN_SANDBOX, FRAME_ATTRS, inView, SKIN_SOURCE, SKIN_VARS, skinMessage,
         VIEW_MARGIN } from "./animation";

const HASH = "a".repeat(64);

describe("el marco de la animación", () => {
  it("solo deja correr scripts: nunca allow-same-origin, ni navegar, ni ventanas, ni formularios", () => {
    const tokens = FRAME_ATTRS.sandbox.split(/\s+/);
    expect(tokens).toEqual(["allow-scripts"]);
    for (const bad of ["allow-same-origin", "allow-top-navigation", "allow-popups", "allow-forms"]) {
      expect(FORBIDDEN_SANDBOX).toContain(bad);
    }
    for (const bad of FORBIDDEN_SANDBOX) expect(tokens).not.toContain(bad);
  });
  it("no manda de dónde viene ni pide permisos", () => {
    expect(FRAME_ATTRS.referrerPolicy).toBe("no-referrer");
    expect(Object.keys(FRAME_ATTRS)).not.toContain("allow");
  });
  it("la URL es la de la animación, fuera de /api/ y sin token", () => {
    const url = animationUrl("p1", `${HASH}.html`)!;
    expect(url).toBe(`/animations/p1/${HASH}.html`);
    expect(url).not.toMatch(/token|\/api\//);
  });
  it("un nombre que no es el sha256 de un .html nunca llega a la URL", () => {
    for (const bad of ["../scene.json", `${HASH}.png`, `${HASH}.html?x=1`, "A".repeat(64) + ".html", "", undefined]) {
      expect(animationUrl("p1", bad)).toBeNull();
    }
    expect(animationUrl("", `${HASH}.html`)).toBeNull();
  });
});

describe("a la vista", () => {
  const v = { scrollX: 0, scrollY: 0, zoom: { value: 1 }, width: 1000, height: 800 };
  const postit = { x: 100, y: 100, width: 260, height: 400 };
  it("en el lienzo, se monta", () => {
    expect(inView(postit, v)).toBe(true);
  });
  it("lejos, fuera por cualquier lado, no se monta", () => {
    expect(inView({ ...postit, x: 5000 }, v)).toBe(false);
    expect(inView({ ...postit, x: -5000 }, v)).toBe(false);
    expect(inView({ ...postit, y: 5000 }, v)).toBe(false);
    expect(inView({ ...postit, y: -5000 }, v)).toBe(false);
  });
  it("al desplazar el lienzo hasta dejarlo fuera, deja de estar a la vista", () => {
    expect(inView(postit, { ...v, scrollX: -(100 + 260 + VIEW_MARGIN + 1) })).toBe(false);
    expect(inView(postit, { ...v, scrollX: -(100 + 260 + VIEW_MARGIN - 1) })).toBe(true);   // aún en el margen
  });
  it("el zoom cuenta: alejado entra, acercado sale", () => {
    const far = { ...postit, x: 1800 };                         // fuera a zoom 1
    expect(inView(far, v)).toBe(false);
    expect(inView(far, { ...v, zoom: { value: 0.5 } })).toBe(true);
    expect(inView({ ...postit, x: 700 }, { ...v, zoom: { value: 2 } })).toBe(false);
  });
  it("con el lienzo sin medir, nada está a la vista", () => {
    expect(inView(postit, { ...v, width: 0 })).toBe(false);
    expect(inView(postit, { ...v, zoom: { value: 0 } })).toBe(false);
  });
});

describe("colores del skin", () => {
  it("son las cinco variables que promete la guía del agente", () => {
    expect([...SKIN_VARS]).toEqual(["--bp-bg", "--bp-fg", "--bp-muted", "--bp-line", "--bp-accent"]);
    expect(skinMessage(() => "#000").type).toBe("skin");
  });
  it("salen de las del tema: el papel de su post-it y el acento del skin", () => {
    const theme: Record<string, string> = { "--pi": " #fff1a8", "--pi-fg": "#1e1e1e", "--pi-t": "#9a7a00",
                                            "--pi-b": "#c9a900", "--accent": "#ffd43b " };
    expect(skinMessage((n) => theme[n] ?? "")).toEqual({ type: "skin", vars: {
      "--bp-bg": "#fff1a8", "--bp-fg": "#1e1e1e", "--bp-muted": "#9a7a00", "--bp-line": "#c9a900",
      "--bp-accent": "#ffd43b" } });
    expect(SKIN_SOURCE["--bp-accent"]).toBe("--accent");
  });
  it("con otro skin, otros colores; una que falta va vacía (la animación usa su valor por defecto)", () => {
    const dark: Record<string, string> = { "--pi": "#3a3627", "--pi-fg": "#e6e8eb", "--accent": "#8ea2ff" };
    const m = skinMessage((n) => dark[n] ?? "");
    expect(m.vars["--bp-bg"]).toBe("#3a3627");
    expect(m.vars["--bp-accent"]).toBe("#8ea2ff");
    expect(m.vars["--bp-line"]).toBe("");
  });
});
