// El onboarding en la interfaz (docs/PLAN_ONBOARDING.md §3, §5, §7): cada tarjeta enseña el
// estado de su último `proposal_state` (el chat nunca se reescribe), el diff enseña justo lo que
// cambia, y *Empezar de nuevo* (el `agent_history` vacío) deja la ventana sin conversación.
import { describe, expect, it } from "vitest";
import { applyMessage, foldStates, lineDiff, providersDiff, unitsDiff, type OnboardingSnap } from "./onboarding";
import type { AgentEvent } from "./store";

const proposal = (id: string, que = "perfil"): AgentEvent =>
  ({ kind: "proposal", id, que, antes: "a", nuevo: "b", motivo: "m", estado: "pendiente" });
const SNAP: OnboardingSnap = { open: true, log: [], busy: false, state: null, problem: null, profileRev: 0 };

describe("estado de las propuestas (N5, N12)", () => {
  it("cada propuesta lleva el estado de su último proposal_state, que no se pinta aparte", () => {
    const log = foldStates([
      { kind: "user", text: "hola" }, proposal("p1"), proposal("p2", "unidades"),
      { kind: "proposal_state", id: "p1", estado: "caducada" },
      { kind: "proposal_state", id: "p2", estado: "descartada" },
      { kind: "proposal_state", id: "p1", estado: "guardada" },
      { kind: "proposal_state", id: "viejo", estado: "guardada" },     // de antes de empezar de nuevo
    ]);
    expect(log.map((e) => [e.kind, e.estado])).toEqual([
      ["user", undefined], ["proposal", "guardada"], ["proposal", "descartada"]]);
  });

  it("un proposal_state en directo cambia su tarjeta; un perfil guardado sube profileRev", () => {
    const s = { ...SNAP, log: [proposal("p1"), proposal("p2", "unidades")] };
    const a = applyMessage(s, { type: "agent", kind: "proposal_state", id: "p2", estado: "guardada" });
    expect(a.log?.map((e) => e.estado)).toEqual(["pendiente", "guardada"]);
    expect(a.profileRev).toBeUndefined();                          // unas unidades no son el perfil
    const b = applyMessage(s, { type: "agent", kind: "proposal_state", id: "p1", estado: "guardada" });
    expect(b.profileRev).toBe(1);
    expect(applyMessage(s, { type: "agent", kind: "proposal_state", id: "nada", estado: "guardada" })).toEqual({});
  });

  it("Empezar de nuevo: el agent_history vacío deja la ventana sin conversación", () => {
    const s = { ...SNAP, log: [proposal("p1"), { kind: "text", text: "x" } as AgentEvent], busy: false };
    const st = { usage: { agents: {}, total: { usd: 0.3 } }, limit: 1, remaining: 0.7, privacy_seen: true, busy: false };
    expect(applyMessage(s, { type: "agent_history", events: [], state: st })).toMatchObject({ log: [], busy: false });
  });

  it("ocupado desde su user hasta su done, error o stopped", () => {
    const user = applyMessage(SNAP, { type: "agent", kind: "user", text: "hola" });
    expect(user.busy).toBe(true);
    const s = { ...SNAP, ...user };
    expect(applyMessage(s, { type: "agent", kind: "tool", name: "leer_configuracion" }).busy).toBe(true);
    for (const kind of ["done", "error", "stopped"]) expect(applyMessage(s, { type: "agent", kind }).busy).toBe(false);
  });
});

describe("diff del perfil (§4.2)", () => {
  it("enseña lo quitado y lo añadido, y lo igual alrededor", () => {
    expect(lineDiff("# Taller\nfresadora\ntorno", "# Taller\nfresadora 5 ejes\ntorno")).toEqual([
      { op: "=", text: "# Taller" }, { op: "-", text: "fresadora" }, { op: "+", text: "fresadora 5 ejes" },
      { op: "=", text: "torno" }]);
  });

  it("de vacío a algo, todo añadido; las iguales lejos de un cambio se juntan", () => {
    expect(lineDiff("", "a\nb")).toEqual([{ op: "+", text: "a" }, { op: "+", text: "b" }]);
    const before = ["1", "2", "3", "4", "5", "6", "7"].join("\n");
    const after = ["1", "2", "3", "4", "5", "6", "siete"].join("\n");
    expect(lineDiff(before, after, 2)).toEqual([
      { op: "…", n: 4 }, { op: "=", text: "5" }, { op: "=", text: "6" },
      { op: "-", text: "7" }, { op: "+", text: "siete" }]);
  });
});

describe("diff de los proveedores (§4.3)", () => {
  const p = (dominio: string, nombre = dominio, tipos: string[] = []) => ({ nombre, dominio, tipos });

  it("marca nuevos, cambiados y quitados; los demás, iguales", () => {
    const d = providersDiff([p("rs.com"), p("misumi.es"), p("igus.es")],
                            [p("rs.com", "RS"), p("igus.es"), p("farnell.com")]);
    expect(d.rows.map((r) => [r.p.dominio, r.marks])).toEqual([
      ["rs.com", ["cambia"]], ["igus.es", []], ["farnell.com", ["nuevo"]]]);
    expect(d.removed.map((r) => r.dominio)).toEqual(["misumi.es"]);
  });

  it("mover uno al principio lo marca a él, no a todos los que bajan un puesto", () => {
    const d = providersDiff([p("a"), p("b"), p("c"), p("d")], [p("d"), p("a"), p("b"), p("c")]);
    expect(d.rows.map((r) => r.marks)).toEqual([["movido"], [], [], []]);
  });

  it("movido y renombrado lleva las dos marcas", () => {
    const d = providersDiff([p("a"), p("b"), p("c")], [p("c", "C nuevo"), p("a"), p("b")]);
    expect(d.rows.map((r) => r.marks)).toEqual([["movido", "cambia"], [], []]);
  });

  it("cambiar los tipos también es un cambio", () => {
    const d = providersDiff([p("a", "A", ["motor"])], [p("a", "A", ["motor", "reductora"])]);
    expect(d.rows[0].marks).toEqual(["cambia"]);
  });
});

describe("diff de las unidades (§4.4)", () => {
  it("las cinco magnitudes; marcadas solo las que cambian", () => {
    const rows = unitsDiff({ longitud: "mm", masa: "kg", fuerza: "N", par: "N·m", angulo: "°" },
                           { longitud: "in", masa: "kg", fuerza: "N", par: "N·m", angulo: "°" });
    expect(rows.map((r) => [r.m, r.antes, r.nuevo, r.changed])).toEqual([
      ["longitud", "mm", "in", true], ["masa", "kg", "kg", false], ["fuerza", "N", "N", false],
      ["par", "N·m", "N·m", false], ["angulo", "°", "°", false]]);
  });
});
