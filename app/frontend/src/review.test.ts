// El revisor en la interfaz (FF 6.1, PLAN_V020 V2-V6): sus eventos nunca entran en el chat de
// diseño, uno a la vez por proyecto, el botón *Revisar* dice por qué no se puede, y sus
// tarjetas vuelven a pedir la revisión con su foco.
import { afterEach, describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { getStore, pushAgentEvent, resetStore, type AgentEvent, type AgentState } from "./store";
import {
  designBusy, milestoneDetail, modeLabel, postitsLine, reviewAfter, reviewAsk, reviewBlock, reviewerBusy,
  reviewUserText,
} from "./review";

const usage = { input: 0, output: 0, cache_creation: 0, cache_read: 0, usd: 0, messages: 0 };
const agent = (over: Partial<AgentState> = {}): AgentState => ({
  usage: { agents: {}, total: usage }, limit: 5, limit_own: false, remaining: 5, exclude_attachments: false,
  privacy_seen: true, busy: false, thread: null, busy_agent: null, ...over,
});

afterEach(() => {
  resetStore();
  setLanguage("es");
});

describe("el chat de diseño nunca pinta lo del revisor (V3)", () => {
  it("un evento con agent revisor va a su conversación y no al chat", () => {
    pushAgentEvent({ kind: "user", text: "Revisa la pizarra", agent: "revisor" });
    pushAgentEvent({ kind: "text", text: "Nada que objetar", agent: "revisor" });
    const s = getStore();
    expect(s.agentLog).toEqual([]);
    expect(s.agentBusy).toBe(false);
    expect(s.reviewLog.map((e) => e.text)).toEqual(["Revisa la pizarra", "Nada que objetar"]);
    expect(s.reviewBusy).toBe(true);
  });
  it("los del de diseño siguen en el chat y no tocan al revisor", () => {
    pushAgentEvent({ kind: "user", text: "hola" });
    const s = getStore();
    expect(s.agentLog).toHaveLength(1);
    expect(s.agentBusy).toBe(true);
    expect(s.reviewLog).toEqual([]);
    expect(s.reviewBusy).toBe(false);
  });
});

describe("la conversación del revisor trabaja de su user a su final", () => {
  const step = (evs: AgentEvent[]) => evs.reduce((st, ev) => reviewAfter(st.log, st.busy, ev), { log: [] as AgentEvent[], busy: false });
  it("user la ocupa y done, error o stopped la liberan", () => {
    for (const end of ["done", "error", "stopped"] as const) {
      const st = step([{ kind: "user" }, { kind: "tool", name: "calcular" }, { kind: end }]);
      expect(st.busy).toBe(false);
      expect(st.log).toHaveLength(3);
    }
    expect(step([{ kind: "user" }, { kind: "tool", name: "leer_pizarra" }]).busy).toBe(true);
  });
  it("las tarjetas de privacidad y tope no la ponen a trabajar", () => {
    expect(step([{ kind: "privacy" }]).busy).toBe(false);
    expect(step([{ kind: "limit" }]).busy).toBe(false);
  });
});

describe("un agente a la vez por proyecto (V6)", () => {
  it("el chat de diseño no está ocupado cuando trabaja el revisor", () => {
    expect(designBusy(agent({ busy: true, busy_agent: "revisor" }))).toBe(false);
    expect(designBusy(agent({ busy: true, busy_agent: "diseno" }))).toBe(true);
    expect(designBusy(agent({ busy: true, thread: "h1", busy_agent: "diseno" }))).toBe(false);
    expect(designBusy(agent({ busy: true }))).toBe(true);        // un backend sin busy_agent
    expect(reviewerBusy(agent({ busy: true, busy_agent: "revisor" }))).toBe(true);
    expect(reviewerBusy(agent({ busy: false, busy_agent: null }))).toBe(false);
  });
});

describe("el botón Revisar dice por qué no se puede", () => {
  it("apagado, nunca se puede, aunque nadie trabaje", () => {
    expect(reviewBlock({ intrusiveness: "apagado", agent: agent(), threadBusy: null })).toBe("apagado");
  });
  it("con el de diseño trabajando, o con un hilo, espera", () => {
    expect(reviewBlock({ intrusiveness: "a_demanda", agent: agent({ busy: true, busy_agent: "diseno" }), threadBusy: null })).toBe("diseno");
    expect(reviewBlock({ intrusiveness: "a_demanda", agent: agent({ busy: true, thread: "h1", busy_agent: "diseno" }), threadBusy: "h1" })).toBe("hilo");
    expect(reviewBlock({ intrusiveness: "a_demanda", agent: agent(), threadBusy: "h1" })).toBe("hilo");
  });
  it("a demanda o en hitos, con nadie trabajando, se puede", () => {
    expect(reviewBlock({ intrusiveness: "a_demanda", agent: agent(), threadBusy: null })).toBeNull();
    expect(reviewBlock({ intrusiveness: "hitos", agent: agent(), threadBusy: null })).toBeNull();
    expect(reviewBlock({ intrusiveness: null, agent: null, threadBusy: null })).toBeNull();
  });
  it("con el propio revisor trabajando no es un bloqueo: es Cancelar", () => {
    expect(reviewBlock({ intrusiveness: "a_demanda", agent: agent({ busy: true, busy_agent: "revisor" }), threadBusy: null })).toBeNull();
  });
});

describe("review_ask lleva el foco solo si lo hay, y once solo si toca", () => {
  it("sin foco, ni la clave", () => {
    expect(reviewAsk("")).toEqual({ type: "review_ask" });
    expect(reviewAsk("   ")).toEqual({ type: "review_ask" });
    expect(reviewAsk(undefined, true)).toEqual({ type: "review_ask", once: true });
  });
  it("el foco sin espacios de más y como mucho 500 caracteres", () => {
    expect(reviewAsk("  la transmisión de J2 ")).toEqual({ type: "review_ask", foco: "la transmisión de J2" });
    expect((reviewAsk("x".repeat(600)).foco as string).length).toBe(500);
  });
});

describe("lo que pidió el ingeniero, en el idioma de la interfaz", () => {
  it("un hito enseña el nombre de la versión y lo cambiado desde la anterior", () => {
    const m = { version: "v2", name: "Con reductora", previous: { id: "v1", name: "Primera" }, changes: 3 };
    expect(reviewUserText({ kind: "user", agent: "revisor", milestone: m })).toBe("Revisión del hito «Con reductora»");
    expect(milestoneDetail(m)).toBe("3 cambios desde «Primera»");
    expect(milestoneDetail({ ...m, changes: 1 })).toBe("1 cambio desde «Primera»");
    expect(milestoneDetail({ ...m, previous: null })).toMatch(/primera versión con nombre/);
  });
  it("con foco, el foco; sin él, revisar la pizarra; en inglés, en inglés", () => {
    expect(reviewUserText({ kind: "user", agent: "revisor", foco: "J2" })).toBe("Revisa: J2");
    expect(reviewUserText({ kind: "user", agent: "revisor", text: "lo del backend" })).toBe("Revisa la pizarra");
    setLanguage("en");
    expect(reviewUserText({ kind: "user", agent: "revisor" })).toBe("Review the board");
    expect(modeLabel("hitos")).toBe("On demand and at milestones");
  });
});

describe("la métrica de sus post-its (§9)", () => {
  it("aceptados, descartados y abiertos, con los números del idioma", () => {
    const p = { abierto: 3, aceptado: 1200, descartado: 1, total: 1204 };
    expect(postitsLine(p)).toBe("Sus post-its: aceptados 1200 · descartados 1 · abiertos 3");
    expect(postitsLine({ ...p, aceptado: 12000 })).toContain("aceptados 12.000");
  });
  it("sin post-its, lo dice en vez de enseñar ceros", () => {
    expect(postitsLine({ abierto: 0, aceptado: 0, descartado: 0, total: 0 })).toBe("Aún no ha dejado post-its");
    expect(postitsLine(null)).toBe("Aún no ha dejado post-its");
  });
});
