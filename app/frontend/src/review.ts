// El revisor en la interfaz (FF 6.1, PLAN_V020 §3, V2-V6): lo que no es React. Sus eventos
// llegan por el mismo `{type: "agent"}` que los del de diseño, con `agent: "revisor"`, y van a
// su pestaña, nunca al chat de diseño ni a un hilo (V3). Un agente a la vez por proyecto (V6):
// `agent_state.busy_agent` dice cuál trabaja, y el botón *Revisar* dice por qué no se puede.
import { fmtNumber, t } from "./i18n";
import type { AgentEvent, AgentState } from "./store";

/** El `agent` de los eventos del revisor (y su consumo en `usage.agents`). */
export const REVIEWER = "revisor";
/** El de diseño, en `usage.agents` y en `busy_agent`. */
export const DESIGNER = "diseno";
/** Lo que se puede escribir como foco de una revisión (`agent_review.FOCO_MAX`). */
export const FOCO_MAX = 500;

export type Intrusiveness = "apagado" | "a_demanda" | "hitos";
export const INTRUSIVENESS: Intrusiveness[] = ["apagado", "a_demanda", "hitos"];
/** Cómo acabaron los post-its del revisor (la métrica de §9). */
export type ReviewPostits = { abierto: number; aceptado: number; descartado: number; total: number };
/** `review_state` (y `init.review`): la intrusividad, el modelo, si revisa y sus post-its. */
export type ReviewState = { intrusiveness: string; model: string; running: boolean; postits: ReviewPostits };
/** El `milestone` del `user` de una revisión de hito (V5): la versión guardada y la anterior. */
export type ReviewMilestone = {
  version: string; name: string | null; previous: { id: string; name: string | null } | null; changes: number;
};

const ENDS = new Set<AgentEvent["kind"]>(["done", "error", "stopped"]);

/** Un evento del revisor: va a su pestaña y nunca al chat de diseño ni a un hilo. */
export const isReviewEvent = (ev: { agent?: string }) => ev.agent === REVIEWER;

/** La conversación del revisor tras un evento: se añade al final, y `user` la pone a trabajar
 *  hasta su `done`, `error` o `stopped` (las tarjetas de privacidad y tope no la ocupan). */
export function reviewAfter(log: AgentEvent[], busy: boolean, ev: AgentEvent): { log: AgentEvent[]; busy: boolean } {
  return { log: [...log, ev], busy: ev.kind === "user" ? true : ENDS.has(ev.kind) ? false : busy };
}

/** El chat de diseño trabaja: el agente está ocupado con él (ni con un hilo ni con el revisor). */
export const designBusy = (st: AgentState | null | undefined) =>
  !!st?.busy && !st.thread && st.busy_agent !== REVIEWER;

/** El revisor trabaja, según `agent_state`. */
export const reviewerBusy = (st: AgentState | null | undefined) => !!st?.busy && st.busy_agent === REVIEWER;

/** Por qué no se puede pedir una revisión ahora, o null si se puede. */
export type ReviewBlock = "apagado" | "diseno" | "hilo" | null;

export function reviewBlock({ intrusiveness, agent, threadBusy }: {
  intrusiveness: string | null | undefined; agent: AgentState | null; threadBusy: string | null;
}): ReviewBlock {
  if (intrusiveness === "apagado") return "apagado";
  if (threadBusy || (agent?.busy && agent.thread)) return "hilo";
  if (agent?.busy && agent.busy_agent !== REVIEWER) return "diseno";
  return null;
}

/** El texto de por qué el botón *Revisar* está apagado. */
export function blockText(b: ReviewBlock): string {
  return b === "apagado" ? t("agente.revisor.bloqueo.apagado")
    : b === "hilo" ? t("agente.revisor.bloqueo.hilo")
      : b === "diseno" ? t("agente.revisor.bloqueo.diseno") : "";
}

/** Cómo revisa, en corto (la cabecera de su pestaña): apagado, a demanda o en hitos. */
export function modeLabel(mode: string): string {
  return mode === "apagado" ? t("agente.revisor.modo.apagado")
    : mode === "hitos" ? t("agente.revisor.modo.hitos") : t("agente.revisor.modo.a_demanda");
}

/** El mensaje `review_ask`: el foco sin espacios de más (vacío, sin foco) y `once` solo si toca. */
export function reviewAsk(foco: string | null | undefined, once = false): Record<string, unknown> {
  const f = (foco ?? "").trim().slice(0, FOCO_MAX);
  return { type: "review_ask", ...(f ? { foco: f } : {}), ...(once ? { once: true } : {}) };
}

/** Lo que pidió el ingeniero (el `user` de una revisión), en el idioma de la interfaz: el
 *  backend lo escribe en el suyo. */
export function reviewUserText(ev: AgentEvent): string {
  if (ev.milestone) return t("agente.revisor.hito", { nombre: ev.milestone.name ?? ev.milestone.version });
  if (ev.foco) return t("agente.revisor.pedido_foco", { foco: ev.foco });
  return t("agente.revisor.pedido");
}

/** Lo cambiado desde el hito anterior: «3 cambios desde «V1»», o la primera con nombre. */
export function milestoneDetail(m: ReviewMilestone): string {
  if (!m.previous) return t("agente.revisor.hito_primero");
  const n = fmtNumber(m.changes);
  const prev = m.previous.name ?? m.previous.id;
  return t(m.changes === 1 ? "agente.revisor.hito_cambio" : "agente.revisor.hito_cambios", { n, anterior: prev });
}

/** La línea de sus post-its (la métrica de §9): aceptados, descartados y abiertos. */
export function postitsLine(p: ReviewPostits | null | undefined): string {
  if (!p || !p.total) return t("agente.revisor.postits_ninguno");
  return t("agente.revisor.postits", {
    aceptados: fmtNumber(p.aceptado), descartados: fmtNumber(p.descartado), abiertos: fmtNumber(p.abierto),
  });
}

/** El nombre de cada agente en el consumo (`usage.agents`), o su clave si no se conoce. */
export function agentName(key: string): string {
  return key === DESIGNER ? t("agente.consumo.agente_diseno")
    : key === REVIEWER ? t("agente.consumo.agente_revisor") : key;
}
