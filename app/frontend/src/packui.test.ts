// Protocolo de la interfaz propia (PLAN_PAQUETES §5, §10 «Protocolo de interfaz»): un
// `setParams` sale como el `set_params` de la tarjeta (la misma validación del backend); un
// mensaje que no es del protocolo, o que no viene de su marco, no cambia nada; la interfaz
// nunca elige el bloque al que habla.
import { describe, expect, it, vi } from "vitest";
import { clampHeight, connectorActionError, connectorCardWanted, connectorParams, connectorSetParams, FRAME_MAX_H, FRAME_MIN_H,
         frameState, frameUrl, handle, panelClosing, parse, PROTOCOL, theme, WHEEL_MAX, wheelInit, widgetPack, type Effects,
         type Wheel } from "./packui";
import type { BlockType } from "./store";

function fx(over: Partial<Effects> = {}) {
  const calls: [string, ...unknown[]][] = [];
  const rec = (name: string) => (...a: unknown[]) => { calls.push([name, ...a]); };
  const e: Effects = {
    ready: rec("ready"), setParams: rec("setParams"), run: rec("run"), resize: rec("resize"),
    toast: rec("toast"), reply: rec("reply"), ignore: rec("ignore"), wheel: rec("wheel"),
    openPanel: () => { calls.push(["openPanel"]); return true; }, closePanel: rec("closePanel"),
    preview: async (p) => { calls.push(["preview", p]); return { ok: 1 }; },
    action: async (n, a) => { calls.push(["action", n, a]); return { eco: a }; },
    ...over,
  };
  // Lo que cambia algo: todo menos apuntar lo ignorado.
  const effects = () => calls.filter(([n]) => n !== "ignore");
  return { e, calls, effects };
}

const v = PROTOCOL;

describe("parse", () => {
  it("exige la versión del protocolo", () => {
    expect(parse({ type: "run" })).toHaveProperty("ignored");
    expect(parse({ v: 2, type: "run" })).toHaveProperty("ignored");
    expect(parse({ v, type: "run" })).toEqual({ type: "run" });
  });

  it("descarta lo que no encaja con su tipo", () => {
    for (const bad of [null, "run", [], { v, type: "setParams", params: [1] }, { v, type: "setParams" },
                       { v, type: "action", id: 1 }, { v, type: "action", name: "x.y" },
                       { v, type: "action", id: "x".repeat(65), name: "x.y" },
                       { v, type: "preview", id: 1, params: "a" }, { v, type: "resize", height: "10" },
                       { v, type: "toast", text: "  " }, { v, type: "navigate", url: "https://x" }]) {
      expect(parse(bad)).toHaveProperty("ignored");
    }
  });

  it("acota el alto y el texto", () => {
    expect(parse({ v, type: "resize", height: 1 })).toEqual({ type: "resize", height: FRAME_MIN_H });
    expect(parse({ v, type: "resize", height: 1e9 })).toEqual({ type: "resize", height: FRAME_MAX_H });
    expect(clampHeight(123.6)).toBe(124);
    const t = parse({ v, type: "toast", text: "x".repeat(1000), kind: "raro" });
    expect(t).toMatchObject({ type: "toast", kind: "info" });
    expect((t as { text: string }).text).toHaveLength(300);
  });
});

describe("handle", () => {
  it("setParams pasa los parámetros tal cual, sin el bloque que diga el mensaje", async () => {
    const { e, effects } = fx();
    await handle({ v, type: "setParams", params: { a: "no es un número" }, block: "otro" }, true, e);
    expect(effects()).toEqual([["setParams", { a: "no es un número" }]]);
  });

  it("un mensaje desconocido no cambia nada y se apunta", async () => {
    const { e, calls, effects } = fx();
    await handle({ v, type: "borrarTodo" }, true, e);
    await handle({ type: "setParams", params: { a: 2 } }, true, e);     // sin versión
    expect(effects()).toEqual([]);
    expect(calls.map(([n]) => n)).toEqual(["ignore", "ignore"]);
  });

  it("lo que no viene de su marco ni se apunta", async () => {
    const { e, calls } = fx();
    await handle({ v, type: "setParams", params: { a: 2 } }, false, e);
    await handle({ v, type: "run" }, false, e);
    expect(calls).toEqual([]);
  });

  it("action responde con el resultado o con el motivo del fallo", async () => {
    const { e, calls } = fx({ action: vi.fn().mockRejectedValueOnce(new Error("la acción no es del paquete")) });
    await handle({ v, type: "action", id: 7, name: "ui_otro.secreto" }, true, e);
    expect(calls).toEqual([["reply", { v, type: "reply", id: 7, ok: false, error: "la acción no es del paquete" }]]);
    const ok = fx();
    await handle({ v, type: "action", id: "a", name: "ui_prueba.eco", args: { x: 1 } }, true, ok.e);
    expect(ok.calls).toEqual([["action", "ui_prueba.eco", { x: 1 }],
                              ["reply", { v, type: "reply", id: "a", ok: true, result: { eco: { x: 1 } } }]]);
  });

  it("openPanel sin panel declarado se apunta", async () => {
    const { e, calls } = fx({ openPanel: () => false });
    await handle({ v, type: "openPanel" }, true, e);
    expect(calls.map(([n]) => n)).toEqual(["ignore"]);
  });

  it("closePanel cierra el panel, y de otro marco no", async () => {
    const { e, calls } = fx();
    await handle({ v, type: "closePanel" }, true, e);
    await handle({ v, type: "closePanel" }, false, e);
    expect(calls).toEqual([["closePanel"]]);
  });
});

// P41: la parte del conector va en otro marco atado al mismo bloque. Solo cambia los
// parámetros que dibuja (los de un control de su paquete) y solo llama a sus acciones.
describe("la parte del conector", () => {
  const ty: BlockType = {
    title: "Mecanizar en el CNC", pack: "acme", description: "", requires: ["cnc"], connector: "cnc",
    inputs: {}, outputs: {}, pull: true, fix: { port: "a", field: "b", label: "Fijar" },
    params: {
      destino: { default: null, unit: "", label: "Destino", choices: [], widget: "cnc.destino" },
      documento: { default: "", unit: "", label: "Documento", choices: [] },
      robot: { default: null, unit: "", label: "Robot", choices: [], widget: "acme.robot" },
      archivo: { default: "", unit: "", label: "STEP", choices: [], widget: "archivo_step" },
    },
  };

  it("el paquete de un control es lo de antes del punto; los de la app no tienen", () => {
    expect([widgetPack("cnc.destino"), widgetPack("archivo_step"), widgetPack(""), widgetPack(undefined),
            widgetPack(".raro")]).toEqual(["cnc", null, null, null, null]);
  });

  it("dibuja solo los parámetros con un control de su paquete", () => {
    expect(connectorParams(ty)).toEqual(["destino"]);
    expect(connectorParams({ ...ty, connector: undefined })).toEqual([]);
  });

  it("va en la tarjeta solo si el bloque tiene algo del conector", () => {
    const { destino: _, ...rest } = ty.params;
    const bare = { ...ty, params: rest, pull: false, fix: null };
    expect([connectorCardWanted(ty), connectorCardWanted(bare), connectorCardWanted({ ...bare, pull: true }),
            connectorCardWanted({ ...bare, fix: ty.fix })]).toEqual([true, false, true, true]);
  });

  it("solo cambia sus parámetros: lo demás se descarta y nunca sale", () => {
    expect(connectorSetParams(ty, { destino: { project: "P" }, documento: "otro", locks: { a: 1 }, robot: "x" }))
      .toEqual({ keep: { destino: { project: "P" } }, dropped: ["documento", "locks", "robot"] });
  });

  it("solo llama a las acciones de su paquete", () => {
    expect(connectorActionError(ty, "cnc.pull")).toBeNull();
    for (const name of ["acme.secreto", "cncx.pull", "cnc", "otro.cnc.pull"]) {
      expect(connectorActionError(ty, name)).toMatch(/solo llama a sus acciones/);
    }
    expect(connectorActionError({ ...ty, connector: undefined }, "cnc.pull")).not.toBeNull();
  });

  it("ve si su programa responde, si hay una ejecución y el nombre del proyecto, y nada de otros bloques", () => {
    const st = { type: "acme.mecanizar", status: "al_dia" as const, params: {}, outputs: null,
                 error: null, synced: true, inputs: { dis: { block: "secreto", port: "p" } } };
    const env = { part: "connector" as const, connector: { id: "cnc", available: true, launching: false },
                  busy: true, project: "Brazo" };
    const s = frameState("b1", "acme.mecanizar", ty, st, "card", theme("escuela", true, {}, "card"), env);
    expect([s.part, s.connector, s.busy, s.project, s.pull, s.synced, s.fix])
      .toEqual(["connector", env.connector, true, "Brazo", true, true, ty.fix]);
    expect(JSON.stringify(s)).not.toContain("secreto");
    const plain = frameState("b1", "acme.mecanizar", ty, undefined, "card", theme("escuela", true, {}, "card"));
    expect([plain.part, plain.connector, plain.busy, plain.synced]).toEqual(["block", null, false, false]);
  });
});

// P54: la rueda que nace en el marco no llega a la app; el puente de la página la manda y la
// tarjeta la pasa al lienzo, sin que la página pueda apuntar fuera de su marco.
describe("la rueda de la página", () => {
  const w = { v, type: "wheel", dx: 0, dy: 120, mode: 0, x: 100, y: 50, ctrl: true, meta: false, shift: false, alt: false };

  it("llega al lienzo tal cual, sea cual sea el bloque que diga", async () => {
    const { e, effects } = fx();
    await handle({ ...w, block: "otro" }, true, e);
    expect(effects()).toEqual([["wheel", { dx: 0, dy: 120, mode: 0, x: 100, y: 50, ctrl: true, meta: false, shift: false, alt: false }]]);
  });

  it("acota los desplazamientos y descarta lo que no son números", () => {
    const big = parse({ ...w, dx: -1e9, dy: 1e9, mode: 7, ctrl: "sí" }) as { wheel: Wheel };
    expect(big.wheel).toMatchObject({ dx: -WHEEL_MAX, dy: WHEEL_MAX, mode: 0, ctrl: false });
    for (const bad of [{ ...w, dy: "120" }, { ...w, x: NaN }, { ...w, y: Infinity }, { v, type: "wheel" }]) {
      expect(parse(bad)).toHaveProperty("ignored");
    }
  });

  it("pasa a la pantalla con la escala del zoom y nunca sale del marco", () => {
    const rect = { left: 400, top: 200, width: 130, height: 60 };       // 260 px de página al 50 %
    const ok = wheelInit({ ...(w as unknown as Wheel), x: 100, y: 50 }, rect, 260);
    expect(ok).toMatchObject({ clientX: 450, clientY: 225, deltaY: 120, ctrlKey: true });
    const out = wheelInit({ ...(w as unknown as Wheel), x: -5000, y: 9000 }, rect, 260);
    expect(out).toMatchObject({ clientX: 400, clientY: 260 });
    expect(wheelInit({ ...(w as unknown as Wheel), x: 10, y: 10 }, rect, 0).clientX).toBe(410);
  });

  it("de otro marco ni se apunta", async () => {
    const { e, calls } = fx();
    await handle(w, false, e);
    expect(calls).toEqual([]);
  });
});

describe("lo que ve la interfaz", () => {
  const ty: BlockType = {
    title: "Con interfaz", pack: "ui_prueba", description: "", requires: [],
    inputs: { carga: "carga", extra: "carga" }, outputs: { out: "ui_prueba.t" }, optional: ["extra"],
    params: { a: { default: 1, unit: "mm", label: "A", choices: [] } },
  };

  it("solo su bloque: parámetros con los de por defecto, y de las entradas si están conectadas", () => {
    const st = { type: "ui_prueba.b", status: "al_dia" as const, params: {}, outputs: null, error: null,
                 inputs: { carga: { block: "secreto", port: "p" } } };
    const s = frameState("b1", "ui_prueba.b", ty, st, "card", theme("escuela", true, {}, "card"));
    expect(s.block).toEqual({ id: "b1", type: "ui_prueba.b", title: "Con interfaz" });
    expect(s.params).toEqual({ a: 1 });
    expect(s.inputs).toEqual({ carga: { type: "carga", connected: true, optional: false },
                               extra: { type: "carga", connected: false, optional: true } });
    expect(JSON.stringify(s)).not.toContain("secreto");
  });

  it("el tema lleva las variables de su sitio y la hoja base", () => {
    const vars = { "--paper": "#efe6cf", "--paper-fg": "#2a2116", "--ui-bg": "#232329", "--ui-fg": "#e3e3e8" };
    expect(theme("escuela", true, vars, "card").vars["--bp-bg"]).toBe("#efe6cf");
    const panel = theme("escuela", true, vars, "panel");
    expect(panel.vars["--bp-fg"]).toBe("#e3e3e8");
    expect(panel.css).toMatch(/^:root \{.*--bp-fg: #e3e3e8;/);
    expect(panel.css).toContain("font: 13px/1.35 var(--f-ui)");
  });

  it("la URL es la de la ui/ del paquete", () => {
    expect(frameUrl("ui_prueba", "ui/index.html")).toBe("/packs/ui_prueba/ui/index.html");
    expect(frameUrl("p", "ui/sub dir/a.html")).toBe("/packs/p/ui/sub%20dir/a.html");
  });
});

// §10 «Panel propio» (P71): un panel con interfaz propia nunca se cierra con un clic fuera; uno
// solo con controles genéricos, sí.
describe("cómo se cierra un panel", () => {
  const ty = (panel: unknown) => ({ view: { card: ["params"], panel } }) as unknown as BlockType;

  it("con interfaz propia, nunca con un clic fuera ni con lo de la app", () => {
    expect(panelClosing(ty("ui"), false)).toEqual({ outside: false, chrome: false });
    expect(panelClosing(ty("ui"), true)).toEqual({ outside: false, chrome: false });
  });

  it("con la parte de un conector, tampoco con un clic fuera; su Cerrar y Escape, sí", () => {
    expect(panelClosing(ty([]), true)).toEqual({ outside: false, chrome: true });
    expect(panelClosing(ty(["params", "results"]), true)).toEqual({ outside: false, chrome: true });
  });

  it("solo con controles genéricos, con todo", () => {
    expect(panelClosing(ty(["params", "results"]), false)).toEqual({ outside: true, chrome: true });
  });
});
