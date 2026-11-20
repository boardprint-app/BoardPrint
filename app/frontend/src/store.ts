// Estado compartido de bloques, fuera de React: Excalidraw llama a renderEmbeddable por su
// cuenta y cada bloque se suscribe aquí.
import { useSyncExternalStore } from "react";
import { t } from "./i18n";
import { FILTER_ALL, type PostitFilter } from "./postit";
import type { Proposal } from "./proposal";
import type { Compare } from "./versions";
import type { Template } from "./palette";
import type { SourceView } from "./cards";
import type { ParamLink } from "./excel";
import type { PortTypes } from "./ports";
import { isReviewEvent, reviewAfter, type ReviewMilestone, type ReviewState } from "./review";

export type Value = {
  value: unknown; unit: string; label?: string; source?: string;
  file?: string;                                   // cita un archivo de la carpeta del bloque
  image?: boolean;                                 // ese archivo es una imagen: miniatura (D114)
  group?: string; lock?: boolean; lockable?: boolean;   // valores del dimensionado (D86)
  hidden?: boolean;                                // ya lo enseña la tarjeta: no va en las salidas (T25)
  control?: string;                                // lo pinta ese control genérico (P52): `chart`, `view2d`
};
export type BlockState = {
  type: string;
  /** `en_cola` y `ejecutando` solo mientras hay una ejecución (no se guardan, plan §3). */
  status: "nunca" | "incompleto" | "error" | "al_dia" | "desactualizado" | "no_disponible"
    | "en_cola" | "ejecutando";
  params: Record<string, unknown> | null;
  /** Salidas por puerto: `{puerto: {campo: valor}}` (plan D94). */
  outputs: Record<string, Record<string, Value>> | null;
  error: string | null;
  /** Un error que pide confirmación (D112): la tarjeta pinta su botón y lo relanza con
   *  `options = {action: true}`, solo esa vez. */
  error_action?: { action: string; label: string } | null;
  /** Un bloque que trae (D116) tiene algo enviado: la tarjeta enseña Traer. */
  synced?: boolean;
  /** Entradas conectadas: `{puerto_de_entrada: {block, port}}`. */
  inputs: Record<string, { block: string; port: string }>;
  /** Por qué está `incompleto` (lo que falta), si lo está. */
  reason?: string | null;
  /** Parámetros que salen de un nombre de un Excel (PLAN_EXCEL §3.2): no se editan a mano. */
  links?: Record<string, ParamLink> | null;
};
/** `widget`: control especial. Los de la app (`archivo_step`) los pinta la tarjeta; uno
 *  `<paquete>.<x>` lo pinta la interfaz de ese paquete (el destino en Fusion, D113, P41). */
export type ParamSpec = { default: unknown; unit: string; label: string; choices: string[]; widget?: string;
                          choice_labels?: Record<string, string> };
export type BlockType = {
  title: string;
  pack: string;
  description: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  requires: string[];
  /** El conector con el que trabaja (PLAN_PAQUETES P41): el id de su paquete ("fusion"). Sus
   *  acciones (*Traer*, aplicar, fijar) son `<conector>.<acción>`. */
  connector?: string;
  /** Sabe *traer* de su herramienta (D116): la tarjeta enseña Traer. */
  pull?: boolean;
  /** Entradas opcionales (D122): el bloque se ejecuta sin ellas. */
  optional?: string[];
  /** Propone candados que la tarjeta ofrece fijar con un botón (D121). */
  fix?: { port: string; field: string; label: string } | null;
  /** Tiene vista previa (PLAN_TERMINALES T26): su editor la pide con lo que se escribe. */
  preview?: boolean;
  params: Record<string, ParamSpec>;
  /** Qué pintan su tarjeta y su panel (PLAN_PAQUETES §5, P45): `"ui"`, la interfaz propia del
   *  paquete; si no, controles genéricos. Panel vacío: no abre panel. */
  view?: { card: ViewSurface; panel: ViewSurface };
};
export type ViewSurface = "ui" | string[];
/** Un paquete cargado (o roto), de `catalog.packs`: su interfaz propia y sus acciones (§5). */
export type PackInfo = { id: string; name: string; version: string; error: string | null; ui?: string; actions?: string[];
                         /** Sus catálogos de traducción (O15): `{idioma: {texto de origen: traducción}}`, packI18n.ts. */
                         i18n?: Record<string, Record<string, string>> };
export type Problem = { arrow: string; reason: string };
/** Paquetes del proyecto que no cuadran con los instalados (PLAN_PAQUETES §3, P13, P25). */
export type PackIssues = {
  missing: { id: string; version: string; blocks: string[] }[];
  changed: { id: string; locked: string; installed: string }[];
};
export const NO_PACK_ISSUES: PackIssues = { missing: [], changed: [] };
/** Ejecución en curso del proyecto (D89, D92): una a la vez, la ven todas las ventanas. */
export type RunInfo = { block: string | null; fraction: number | null; message: string; queued: string[] };

/** Lo que propone el agente al acabar un paquete (PLAN_PAQUETES P102): la tarjeta del chat. */
export type PackProposal = {
  id: string; name: string; version: string; description: string; author: string;
  blocks: string[]; libraries: string[]; requires: Record<string, string>;
  tests: { count: number; names: string[] };
};
export type AgentEvent = {
  kind: "user" | "text" | "tool" | "tool_result" | "done" | "error" | "pack_proposal"
      | "stopped" | "privacy" | "limit" | "decision_proposal" | "closed" | "reopened";
  pack?: PackProposal;
  text?: string;
  name?: string;
  input?: Record<string, any>;
  error?: boolean;
  turns?: number;
  seconds?: number;
  reason?: string;                    // done: ok | limit | stopped | max_turns | error (D168)
  usage?: AgentUsage;                 // done: lo del mensaje
  total?: AgentUsage;                 // done: lo del proyecto
  notice?: string;                    // privacy: qué se envía (D169)
  used?: number;                      // limit: consumo y tope en USD equivalentes
  limit?: number;
  thread?: string;                    // de un hilo (D165): el chat principal no lo pinta
  close_request?: boolean;            // privacy/limit/user de *Cerrar con decisión* (D167)
  decision?: ThreadDecision;          // decision_proposal y closed de un hilo
  agent?: string;                     // "revisor": de su pestaña, nunca del chat (FF 6.1, V3)
  foco?: string;                      // revisor: en qué fijarse (user, privacy, limit)
  milestone?: ReviewMilestone;        // revisor: el user de una revisión de hito (V5)
};
/** Consumo de un mensaje, un agente o el proyecto (D168): tokens y USD equivalentes. */
export type AgentUsage = {
  input: number; output: number; cache_creation: number; cache_read: number; usd: number; messages: number;
};
/** `agent_state` (`agent_chat.state`): consumo, tope y ajustes del agente del proyecto. */
export type AgentState = {
  usage: { agents: Record<string, AgentUsage>; total: AgentUsage };
  limit: number; limit_own: boolean; remaining: number;
  exclude_attachments: boolean; privacy_seen: boolean; busy: boolean; thread: string | null;
  /** Qué agente trabaja (V6: uno a la vez por proyecto). */
  busy_agent?: "diseno" | "revisor" | null;
};
/** La decisión de un hilo (D167): con cifras, fuentes o `estimate` (D19). */
export type ThreadDecision = { text: string; sources?: Record<string, any>[]; estimate?: boolean; at?: string };
/** Un hilo anclado (`agent_threads.py`, R43); su interfaz, `ThreadLayer` (D166). `layout` en
 *  píxeles de la pizarra (`threads.ts`). */
export type ThreadInfo = {
  id: string; title: string; anchors: string[]; state: "abierto" | "decidido" | "en_revision";
  decision?: ThreadDecision | null; proposed?: ThreadDecision | null;
  layout?: { size: "min" | "window" | "full"; x: number; y: number; w: number; h: number };
  messages: number; created?: string; updated?: string; missing?: string[]; sin_anclaje?: boolean;
};
/** *Cerrar con decisión* en curso (D167): esperando la propuesta del agente, editándola o
 *  guardándola (un error del backend, p. ej. cifras sin fuente, se enseña en el cuadro). */
export type ThreadClosing = {
  id: string; phase: "waiting" | "edit" | "saving"; text: string; sources: Record<string, any>[];
  estimate: boolean; error: string | null; note: string | null;
};

export type ProjectInfo = { id: string; name: string; path: string; folder: string };
/** Un conector (D35, D106), por el id de su paquete ("fusion"); `launching` mientras arranca tras «Abrir». */
export type Connector = { name: string; available: boolean; launching: boolean };
/** Lo que declara un conector (`catalog.connectors`, P41): si su paquete pone su parte de
 *  interfaz en la tarjeta y en el panel de los bloques que lo usan. */
export type ConnectorInfo = { title: string; card: boolean; panel: boolean };

type Snapshot = {
  project: ProjectInfo | null;
  savedAt: number | null;
  blocks: Record<string, BlockState>;
  types: Record<string, BlockType>;
  ports: PortTypes;                           // tipos de puerto: su nombre legible y su color
  packs: PackInfo[];                          // paquetes cargados (PLAN_PAQUETES §5)
  templates: Record<string, Template>;        // plantillas de los paquetes (D91)
  problems: Problem[];
  packIssues: PackIssues;
  run: RunInfo | null;
  connectors: Record<string, Connector>;
  connectorInfo: Record<string, ConnectorInfo>;
  lastError: string | null;
  agentLog: AgentEvent[];
  agentBusy: boolean;             // el chat principal tiene un mensaje en curso
  agentState: AgentState | null;  // consumo, tope y ajustes (D168, D169)
  reviewLog: AgentEvent[];        // la conversación del revisor (FF 6.1, `review_history`)
  reviewBusy: boolean;            // el revisor está con una revisión
  reviewState: ReviewState | null;   // intrusividad, modelo y sus post-its (`review_state`)
  threads: ThreadInfo[];          // hilos del proyecto (D165)
  threadLogs: Record<string, AgentEvent[]>;   // los mensajes de cada hilo abierto (thread_history)
  threadBusy: string | null;      // el hilo con una pregunta en curso (una a la vez, R43)
  threadFocus: string | null;     // hilo recién creado: su caja de texto se lleva el foco (D176)
  threadClosing: ThreadClosing | null;
  editingPostit: string | null;   // post-it con el cuadro de texto abierto (D71)
  editingLink: string | null;     // enlace con su título en edición (D137)
  postitFilter: PostitFilter;     // qué post-its se ven (D80, 4C): de la vista, nunca de la escena
  proposals: Proposal[];          // propuestas pendientes de los agentes (D75)
  versionsTick: number;           // sube cuando otra ventana cambia la lista de versiones (D76)
  compare: Compare | null;        // comparación abierta en la pestaña Versiones
  compareFocus: string | null;    // cambio elegido en esa lista
  packPanel: string | null;       // bloque con el panel de su paquete abierto (PLAN_PAQUETES §5)
  notice: { text: string; kind: "info" | "error"; at: number } | null;   // aviso de una interfaz (`toast`)
  sources: Record<string, SourceView>;   // estado de las tarjetas de archivo (D134, D147)
  folderView: string | null;      // tarjeta de carpeta con su vista abierta (D139)
  preview: string | null;         // tarjeta de archivo con *Previsualizar* abierto (D135)
};

const EMPTY: Snapshot = {
  project: null, savedAt: null,
  blocks: {}, types: {}, ports: {}, packs: [], templates: {}, problems: [], packIssues: NO_PACK_ISSUES, run: null, connectors: {}, connectorInfo: {}, lastError: null, agentLog: [], agentBusy: false,
  agentState: null, reviewLog: [], reviewBusy: false, reviewState: null, threads: [], threadLogs: {}, threadBusy: null, threadFocus: null, threadClosing: null,
  editingPostit: null, editingLink: null, postitFilter: FILTER_ALL, proposals: [], versionsTick: 0, compare: null,
  compareFocus: null, packPanel: null, notice: null, sources: {}, folderView: null, preview: null,
};

let snap: Snapshot = EMPTY;

// Al cambiar de proyecto no queda nada del anterior (bloques, chat del agente, avisos).
export function resetStore() {
  snap = EMPTY;
  listeners.forEach((l) => l());
}

export function pushAgentEvent(ev: AgentEvent) {
  if (isReviewEvent(ev)) {                     // lo del revisor va a su pestaña (V3)
    const next = reviewAfter(snap.reviewLog, snap.reviewBusy, ev);
    return setStore({ reviewLog: next.log, reviewBusy: next.busy });
  }
  if (ev.thread) return pushThreadEvent(ev);   // lo de un hilo va en su ventana, no en el chat
  const busy = ev.kind === "user" ? true
    : ev.kind === "done" || ev.kind === "error" || ev.kind === "stopped" ? false : snap.agentBusy;
  setStore({ agentLog: [...snap.agentLog, ev], agentBusy: busy });
}

/** Un evento de un hilo: a su conversación si ya se cargó (si no, la trae `thread_history` al
 *  abrirlo), y lleva la cuenta de qué hilo tiene el agente y de *Cerrar con decisión*. */
function pushThreadEvent(ev: AgentEvent) {
  const id = ev.thread!;
  const patch: Partial<Snapshot> = {};
  const log = snap.threadLogs[id];
  if (log) patch.threadLogs = { ...snap.threadLogs, [id]: [...log, ev] };
  if (ev.kind === "user") patch.threadBusy = id;
  else if ((ev.kind === "done" || ev.kind === "error" || ev.kind === "stopped") && snap.threadBusy === id) patch.threadBusy = null;
  const c = snap.threadClosing;
  if (c && c.id === id) {
    if (ev.kind === "decision_proposal" && ev.decision && c.phase === "waiting") {
      patch.threadClosing = { ...c, phase: "edit", text: ev.decision.text, sources: ev.decision.sources ?? [],
                              estimate: !!ev.decision.estimate, note: null };
    } else if ((ev.kind === "done" || ev.kind === "error" || ev.kind === "stopped") && c.phase === "waiting") {
      patch.threadClosing = { ...c, phase: "edit",
                              note: t("lienzo.hilo.sin_frase") };

    } else if (ev.kind === "privacy" || ev.kind === "limit") {
      patch.threadClosing = null;          // la tarjeta sale en el hilo; desde ella se vuelve a pedir
    }
  }
  setStore(patch);
}
const listeners = new Set<() => void>();

export function setStore(patch: Partial<Snapshot>) {
  snap = { ...snap, ...patch };
  listeners.forEach((l) => l());
}

export function useStore(): Snapshot {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => snap,
  );
}

// Lectura puntual fuera de React (p. ej. al dibujar la miniatura).
export function getStore(): Snapshot {
  return snap;
}
