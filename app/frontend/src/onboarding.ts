// Lo que no pinta ni conecta del agente de onboarding (docs/PLAN_ONBOARDING.md §3, §5): juntar
// cada propuesta con su último `proposal_state` (el chat nunca se reescribe), el estado tras cada
// mensaje de `/ws/onboarding` y los diffs de sus tarjetas. El estado y la conexión están en
// onboardingChat.ts; la ventana, en `OnboardingDialog.tsx`.
import type { AgentEvent, AgentUsage } from "./store";
import type { Magnitude, UnitPrefs } from "./units";

export type ProposalStatus = "pendiente" | "guardada" | "descartada" | "caducada";
export type ProposalKind = "perfil" | "proveedores" | "unidades";
export type Provider = { nombre: string; dominio: string; tipos: string[] };

/** `agent_state` del onboarding (`OnboardingChat.state`): lo gastado del workspace y su tope. */
export type OnboardingState = {
  usage: { agents: Record<string, AgentUsage>; total: AgentUsage };
  limit: number; remaining: number; privacy_seen: boolean; busy: boolean;
};

export type OnboardingSnap = {
  open: boolean;
  log: AgentEvent[];
  busy: boolean;
  state: OnboardingState | null;     // null: aún sin conectar
  problem: string | null;            // sin workspace, o el backend no contesta
  /** Sube cada vez que se guarda un perfil: la fila de *Ajustes → General* se vuelve a leer. */
  profileRev: number;
};

// ------------------------------------------------------------------ lógica pura

/** Los eventos tal como se pintan: cada `proposal_state` va a su propuesta (su `estado`) y no
 *  se pinta aparte. Uno de una propuesta que no está (de antes de *Empezar de nuevo*) se ignora. */
export function foldStates(events: AgentEvent[]): AgentEvent[] {
  const out: AgentEvent[] = [];
  const at = new Map<string, number>();
  for (const ev of events) {
    if (ev.kind === "proposal_state") {
      const i = ev.id ? at.get(ev.id) : undefined;
      if (i !== undefined) out[i] = { ...out[i], estado: ev.estado };
      continue;
    }
    if (ev.kind === "proposal" && ev.id) at.set(ev.id, out.length);
    out.push(ev);
  }
  return out;
}

/** El estado después de un mensaje de `/ws/onboarding` (sin tocar el de fuera). */
export function applyMessage(s: OnboardingSnap, msg: any): Partial<OnboardingSnap> {
  switch (msg?.type) {
    case "agent_history":
      return { log: foldStates(msg.events ?? []), state: msg.state ?? s.state, busy: !!msg.state?.busy, problem: null };
    case "agent_state":
      return { state: msg, busy: !!msg.busy };
    case "error":
      return { log: [...s.log, { kind: "error", text: String(msg.message ?? "") }] };
    case "agent": {
      const { type: _type, ...ev } = msg;
      if (ev.kind === "proposal_state") return stateChanged(s, ev.id, ev.estado);
      const busy = ev.kind === "user" ? true
        : ev.kind === "done" || ev.kind === "error" || ev.kind === "stopped" ? false : s.busy;
      return { log: [...s.log, ev as AgentEvent], busy };
    }
    default:
      return {};
  }
}

/** Una propuesta que cambia de estado: su tarjeta, y si es un perfil guardado, `profileRev`. */
export function stateChanged(s: OnboardingSnap, id: string, estado: ProposalStatus): Partial<OnboardingSnap> {
  let que: string | undefined;
  const log = s.log.map((ev) => {
    if (ev.kind !== "proposal" || ev.id !== id || ev.estado === estado) return ev;
    que = ev.que;
    return { ...ev, estado };
  });
  if (que === undefined) return {};
  return { log, ...(que === "perfil" && estado === "guardada" ? { profileRev: s.profileRev + 1 } : {}) };
}

export type DiffLine = { op: "=" | "-" | "+"; text: string } | { op: "…"; n: number };

/** El diff por líneas de dos textos (subsecuencia común más larga): lo quitado antes que lo
 *  añadido en cada cambio. Sin `context`, todas las líneas; con él, las iguales que quedan a más
 *  de `context` líneas de un cambio se juntan en `{op: "…", n}`. */
export function lineDiff(before: string, after: string, context?: number): DiffLine[] {
  const a = before === "" ? [] : before.split("\n");
  const b = after === "" ? [] : after.split("\n");
  const n = a.length, m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const out: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { out.push({ op: "=", text: a[i] }); i++; j++; }
    else if (i < n && (j >= m || lcs[i + 1][j] >= lcs[i][j + 1])) out.push({ op: "-", text: a[i++] });
    else out.push({ op: "+", text: b[j++] });
  }
  return context === undefined ? out : collapse(out, context);
}

function collapse(lines: DiffLine[], context: number): DiffLine[] {
  const near = lines.map(() => false);
  lines.forEach((l, i) => {
    if (l.op === "=") return;
    for (let k = Math.max(0, i - context); k <= Math.min(lines.length - 1, i + context); k++) near[k] = true;
  });
  const out: DiffLine[] = [];
  lines.forEach((l, i) => {
    if (near[i] || l.op !== "=") return out.push(l);
    const last = out[out.length - 1];
    if (last?.op === "…") last.n++;
    else out.push({ op: "…", n: 1 });
  });
  return out;
}

export type ProviderMark = "nuevo" | "movido" | "cambia";
export type ProvidersDiff = { rows: { p: Provider; marks: ProviderMark[] }[]; removed: Provider[] };

/** La lista nueva de proveedores en su orden con sus marcas: nuevo, o movido (su orden frente a
 *  los demás que ya estaban cambió) y cambiado (otro nombre o tipos), las dos si toca; ninguna
 *  si está igual. Y los quitados. Un
 *  proveedor es su dominio (es único, `supply.check_providers`). Se mueven los menos posibles:
 *  los que quedan fuera de la subsecuencia creciente más larga de sus posiciones de antes. */
export function providersDiff(before: Provider[], after: Provider[]): ProvidersDiff {
  const old = new Map(before.map((p, i) => [p.dominio, { p, i }]));
  const kept = after.filter((p) => old.has(p.dominio)).map((p) => old.get(p.dominio)!.i);
  const still = increasing(kept);
  const rows = after.map((p) => {
    const o = old.get(p.dominio);
    const marks: ProviderMark[] = [];
    if (!o) return { p, marks: ["nuevo"] as ProviderMark[] };
    if (!still.has(o.i)) marks.push("movido");
    if (o.p.nombre !== p.nombre || o.p.tipos.join("\n") !== p.tipos.join("\n")) marks.push("cambia");
    return { p, marks };
  });
  const now = new Set(after.map((p) => p.dominio));
  return { rows, removed: before.filter((p) => !now.has(p.dominio)) };
}

/** Los valores de la subsecuencia creciente más larga de `xs` (todos distintos). */
function increasing(xs: number[]): Set<number> {
  const len = xs.map(() => 1), prev = xs.map(() => -1);
  let best = -1;
  xs.forEach((x, i) => {
    for (let k = 0; k < i; k++)
      if (xs[k] < x && len[k] + 1 > len[i]) { len[i] = len[k] + 1; prev[i] = k; }
    if (best < 0 || len[i] > len[best]) best = i;
  });
  const out = new Set<number>();
  for (let i = best; i >= 0; i = prev[i]) out.add(xs[i]);
  return out;
}

export const MAGNITUDES: Magnitude[] = ["longitud", "masa", "fuerza", "par", "angulo"];

/** Las cinco magnitudes con su unidad de ahora y la nueva. */
export function unitsDiff(before: Partial<UnitPrefs>, after: Partial<UnitPrefs>) {
  return MAGNITUDES.map((m) => ({ m, antes: before[m] ?? "", nuevo: after[m] ?? before[m] ?? "",
                                  changed: (after[m] ?? before[m]) !== before[m] }));
}

