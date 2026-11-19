// El chat del agente de diseño (plan D173): sus mensajes en Markdown (`markdown.ts`), cada
// herramienta como una línea plegable con su nombre en castellano, «Pensando…» con la
// herramienta en curso y *Parar*; las tarjetas de privacidad (D169) y del tope (D168), y la
// de un paquete que propone (PLAN_PAQUETES P102). Lo de los hilos no se pinta aquí (store):
// lo pinta su ventana (`ThreadLayer`) con el mismo `ChatLog`, y sus tarjetas se reenvían al
// hilo (`CardCtx`).
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { send } from "./socket";
import { apiFetch } from "./auth";
import { openInstall } from "./settings";
import { getStore, setStore, useStore, type AgentEvent, type PackProposal, type ThreadDecision } from "./store";
import { Markdown } from "./ChatMarkdown";
import { AgentUsageBar, decimal, usd } from "./AgentUsage";
import { t } from "./i18n";

/** El nombre legible de cada herramienta, en el idioma de la interfaz (se calcula al pintar). */
const toolLabels = (): Record<string, string> => ({
  leer_pizarra: t("agente.herramienta.leer_pizarra"),
  leer_bloque: t("agente.herramienta.leer_bloque"),
  leer_archivo: t("agente.herramienta.leer_archivo"),
  crear_postit: t("agente.herramienta.crear_postit"),
  proponer_cambio: t("agente.herramienta.proponer_cambio"),
  crear_bloque: t("agente.herramienta.crear_bloque"),
  conectar: t("agente.herramienta.conectar"),
  poner_plantilla: t("agente.herramienta.poner_plantilla"),
  ejecutar_bloque: t("agente.herramienta.ejecutar_bloque"),
  ver_zona: t("agente.herramienta.ver_zona"),
  guia_animacion: t("agente.herramienta.guia_animacion"),
  proponer_decision: t("agente.herramienta.proponer_decision"),
  crear_archivo: t("agente.herramienta.crear_archivo"),
  editar_archivo: t("agente.herramienta.editar_archivo"),
  guia_paquetes: t("agente.herramienta.guia_paquetes"),
  crear_paquete: t("agente.herramienta.crear_paquete"),
  listar_paquete: t("agente.herramienta.listar_paquete"),
  leer_archivo_paquete: t("agente.herramienta.leer_archivo_paquete"),
  escribir_archivo_paquete: t("agente.herramienta.escribir_archivo_paquete"),
  validar_paquete: t("agente.herramienta.validar_paquete"),
  proponer_paquete: t("agente.herramienta.proponer_paquete"),
  duplicar_paquete: t("agente.herramienta.duplicar_paquete"),
});

/** El nombre legible de una herramienta, o su nombre si no se conoce. */
export const toolLabel = (name: string): string => toolLabels()[name] ?? name;

type Input = Record<string, any>;

/** El nombre legible de un bloque de la pizarra (su tipo), o su id si no está. */
function blockName(id: unknown): string {
  const { blocks, types } = getStore();
  const b = typeof id === "string" ? blocks[id] : undefined;
  return b ? types[b.type]?.title ?? b.type : String(id ?? "");
}

/** Lo que va entre paréntesis detrás del nombre de la herramienta. */
function toolHint(name: string, input: Input | undefined): string {
  if (!input) return "";
  switch (name) {
    case "crear_postit": return input.kind ?? "";
    case "crear_bloque": return input.tipo ?? "";
    case "poner_plantilla": return input.plantilla ?? "";
    case "conectar": return input.desde && input.hasta ? `${input.desde} → ${input.hasta}` : "";
    case "leer_bloque": return blockName(input.block) + (input.port ? ` · ${input.port}` : "");
    case "ejecutar_bloque": return blockName(input.bloque);
    case "leer_archivo": return input.file ?? "";
    case "crear_archivo": return input.nombre ?? "";
    default: return typeof input.id === "string" ? input.id : "";
  }
}

/** El nombre de cada tipo de fuente (D19), o el tipo tal cual si no se conoce. */
const sourceKind = (kind: string | undefined): string | undefined => ({
  bloque: t("agente.fuente.bloque"), ficha: t("agente.fuente.ficha"), dato_vivo: t("agente.fuente.dato_vivo"),
  calculo: t("agente.fuente.calculo"), archivo: t("agente.fuente.archivo"),
} as Record<string, string>)[kind ?? ""] ?? kind;

type Source = { kind?: string; ref?: string; file?: string; where?: string; url?: string; date?: string;
                formula?: string; inputs?: string[] };

function sourceText(s: Source): string {
  // `archivo:<id>` no dice nada a quien lee: basta con el nombre del archivo.
  const ref = s.ref?.startsWith("bloque:") ? blockName(s.ref.slice(7))
    : s.ref?.startsWith("archivo:") && s.file ? undefined : s.ref;
  return [ref, s.file, s.where, s.url, s.date].filter(Boolean).join(" · ");
}

/** Lo que dejó un post-it del agente: su texto, sus fuentes y sus cuentas (D19), como en el
 *  prototipo («Cálculo del agente, sin verificar»). */
function PostitSources({ input }: { input: Input }) {
  const sources: Source[] = Array.isArray(input.sources) ? input.sources : [];
  return (
    <div className="ag-postit">
      <span className={`ag-kind k-${input.kind}`}>{input.kind}</span> {String(input.text ?? "")}
      {sources.filter((s) => s.kind !== "calculo").length > 0 && (
        <ul className="ag-srcs">
          {sources.filter((s) => s.kind !== "calculo").map((s, i) => (
            <li key={i}><b>{sourceKind(s.kind)}</b> {sourceText(s)}</li>
          ))}
        </ul>
      )}
      {input.estimate && <div className="ag-est">{t("agente.postit.estimacion")}</div>}
    </div>
  );
}

function Calcs({ input }: { input: Input }) {
  const calcs: Source[] = Array.isArray(input.sources) ? input.sources.filter((s: Source) => s.kind === "calculo") : [];
  return <>{calcs.map((c, i) => (
    <div key={i} className="ag-calc">
      <div>{t("agente.calculo.titulo")}</div>
      <span className="num">{c.formula}</span>
      {c.inputs?.length ? <span className="ag-calc-in"> · {t("agente.calculo.con", { lista: c.inputs.map((r) => blockName(r.replace(/^bloque:/, ""))).join(", ") })}</span> : null}
    </div>
  ))}</>;
}

/** Una herramienta: plegada, su nombre; desplegada, lo que pidió y lo que le contestaron. */
function ToolLine({ ev, result }: { ev: AgentEvent; result?: AgentEvent }) {
  const name = ev.name ?? "";
  const hint = toolHint(name, ev.input);
  const failed = !!result?.error;
  const args = ev.input && Object.keys(ev.input).length
    ? JSON.stringify(ev.input, null, 1).slice(0, 1200) : "";
  return (
    <>
      <details className={failed ? "ag-tool bad" : "ag-tool"}>
        <summary>
          <span className="ag-arrow" aria-hidden="true">→</span> {toolLabel(name)}
          {hint && <span className="ag-hint-arg"> ({hint})</span>}
          {failed && <span className="ag-tool-bad"> · {t("agente.herramienta.rechazado")}</span>}
        </summary>
        <div className="ag-tool-body">
          {name === "crear_postit" && ev.input ? <PostitSources input={ev.input} />
            : args && <pre>{args}</pre>}
          {result?.text && <div className={failed ? "ag-reject" : "ag-tool-res"}>{result.text}</div>}
        </div>
      </details>
      {name === "crear_postit" && ev.input && !failed && <Calcs input={ev.input} />}
    </>
  );
}

/** La tarjeta de un paquete que propone el agente (PLAN_PAQUETES P102). *Instalar* exporta el
 *  borrador y abre el resumen de instalar de Ajustes, con su aviso y su destino (§7). */
function PackCard({ pack }: { pack: PackProposal }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const install = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/packs/drafts/${pack.id}/export`, { method: "POST" });
      const body = await r.json().catch(() => null);
      if (!r.ok) throw new Error(body?.detail ?? `${r.status}`);
      openInstall({ paths: [body.path] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="ag-card ag-pack">
      <div className="ag-pack-head"><b>{pack.name}</b> <span>{pack.version}</span></div>
      {pack.description && <p>{pack.description}</p>}
      <dl>
        <dt>{t("agente.paquete.bloques")}</dt><dd>{pack.blocks.join(", ") || "—"}</dd>
        <dt>{t("agente.paquete.librerias")}</dt><dd>{pack.libraries.join(", ") || t("agente.paquete.ninguna")}</dd>
        {Object.keys(pack.requires).length > 0 && (
          <><dt>{t("agente.paquete.pide")}</dt><dd>{Object.entries(pack.requires).map(([k, v]) => `${k} ${v}`).join(", ")}</dd></>
        )}
        <dt>{t("agente.paquete.tests")}</dt>
        <dd>{t("agente.paquete.tests_verde", { n: pack.tests.count })}{pack.tests.names.length > 0 && (
          <ul>{pack.tests.names.map((n) => <li key={n}>{n.replace(/^test_/, "").replace(/_/g, " ")}</li>)}</ul>
        )}</dd>
      </dl>
      {error && <p className="ag-reject">{error}</p>}
      <div className="ag-card-btns"><button className="ag-btn primary" disabled={busy} onClick={install}>{t("agente.paquete.instalar")}</button></div>
    </div>
  );
}

/** Qué hacen las tarjetas de privacidad y tope de una conversación: volver a mandar su
 *  pregunta (al chat o al hilo) y quitarse (no son conversación: no se guardan). */
export type CardCtx = { resend: (ev: AgentEvent, once?: boolean) => void; drop: (ev: AgentEvent) => void };

const MAIN_CTX: CardCtx = {
  resend: (ev, once) => send({ type: "agent_ask", text: ev.text, ...(once ? { once: true } : {}) }),
  drop: (ev) => setStore({ agentLog: getStore().agentLog.filter((e) => e !== ev) }),
};

function PrivacyCard({ ev, ctx }: { ev: AgentEvent; ctx: CardCtx }) {
  return (
    <div className="ag-card" role="alert">
      <div className="ag-card-title">{t("agente.privacidad.titulo")}</div>
      <p>{ev.notice}</p>
      <div className="ag-card-btns">
        <button className="ag-btn primary" onClick={() => {
          send({ type: "agent_privacy_ok" });
          if (ev.text) ctx.resend(ev);
          ctx.drop(ev);
        }}>{t("agente.privacidad.entendido")}</button>
      </div>
    </div>
  );
}

function LimitCard({ ev, ctx }: { ev: AgentEvent; ctx: CardCtx }) {
  const limit = ev.limit ?? 5;
  const raised = Math.max(limit * 2, (ev.used ?? 0) + 1);
  return (
    <div className="ag-card warn" role="alert">
      <div className="ag-card-title">{t("agente.tope.titulo")}</div>
      <p>{t("agente.tope.texto", { usado: usd(ev.used ?? 0), tope: usd(limit) })}</p>
      <div className="ag-card-btns">
        <button className="ag-btn" onClick={() => {
          ctx.resend(ev, true);
          ctx.drop(ev);
        }}>{t("agente.tope.seguir_uno")}</button>
        <button className="ag-btn primary" onClick={() => {
          send({ type: "agent_settings", limit: Math.ceil(raised) });
          ctx.resend(ev);
          ctx.drop(ev);
        }}>{t("agente.tope.subir", { n: Math.ceil(raised) })}</button>
      </div>
    </div>
  );
}

const reasons = (): Record<string, string> => ({
  stopped: t("agente.fin.parado"), limit: t("agente.fin.parado_tope"), max_turns: t("agente.fin.max_vueltas"),
  error: t("agente.fin.error"),
});

function DoneLine({ ev }: { ev: AgentEvent }) {
  const why = ev.reason && ev.reason !== "ok";
  const parts = [why ? ev.text ?? reasons()[ev.reason!] ?? ev.reason : t("agente.fin.listo")];
  if (ev.turns != null) parts.push(t(ev.turns === 1 ? "agente.fin.vuelta_uno" : "agente.fin.vuelta_varios", { n: ev.turns }));
  if (ev.seconds != null) parts.push(`${decimal(ev.seconds)} s`);
  if (ev.usage) parts.push(t("agente.usd_eq", { n: usd(ev.usage.usd) }));
  return <div className={why ? "ag-meta warn" : "ag-meta"}>{parts.join(" · ")}</div>;
}

/** La decisión de un hilo (D167) con sus fuentes, o «estimación» si va sin ellas (D19). */
export function DecisionBox({ d, label, children }: { d: ThreadDecision; label?: string; children?: ReactNode }) {
  const sources: Source[] = (d.sources ?? []) as Source[];
  return (
    <div className="ag-decision">
      <div><b>{label ?? t("agente.decision.etiqueta")}</b> · {d.text}</div>
      {sources.length > 0 && (
        <ul className="ag-srcs">{sources.map((s, i) => (
          <li key={i}><b>{sourceKind(s.kind)}</b> {s.kind === "calculo" ? s.formula : sourceText(s)}</li>
        ))}</ul>
      )}
      {d.estimate && <div className="ag-est">{t("agente.decision.estimacion")}</div>}
      {children}
    </div>
  );
}

export function sourceLine(s: Record<string, any>): string {
  const src = s as Source;
  return `${sourceKind(src.kind) ?? ""} ${src.kind === "calculo" ? src.formula ?? "" : sourceText(src)}`.trim();
}

function Line({ ev, result, ctx }: { ev: AgentEvent; result?: AgentEvent; ctx: CardCtx }) {
  switch (ev.kind) {
    case "user":
      return <div className="ag-user">{ev.text}</div>;
    case "text":
      return <div className="ag-text"><Markdown text={ev.text ?? ""} /></div>;
    case "tool":
      return <ToolLine ev={ev} result={result} />;
    case "done":
      return <DoneLine ev={ev} />;
    case "stopped":
      return <div className="ag-meta warn">{ev.text}</div>;
    case "privacy":
      return <PrivacyCard ev={ev} ctx={ctx} />;
    case "limit":
      return <LimitCard ev={ev} ctx={ctx} />;
    case "decision_proposal":
      return ev.decision ? <DecisionBox d={ev.decision} label={t("agente.decision.propone")} /> : null;
    case "closed":
      return ev.decision ? <DecisionBox d={ev.decision} label={t("agente.decision.cerrado")} /> : null;
    case "reopened":
      return <div className="ag-meta warn">{t("agente.decision.reabierto")}</div>;
    case "error":
      return <div className="ag-reject">{t("agente.error", { texto: ev.text ?? "" })}</div>;
    case "pack_proposal":
      return ev.pack ? <PackCard pack={ev.pack} /> : null;
    default:
      return null;     // tool_result: va dentro de su herramienta
  }
}

/** Empareja cada `tool_result` con su herramienta: llegan en el mismo orden. */
function pairResults(log: AgentEvent[]): Map<number, AgentEvent> {
  const out = new Map<number, AgentEvent>();
  let open: number[] = [];
  log.forEach((ev, i) => {
    if (ev.kind === "tool") open.push(i);
    else if (ev.kind === "tool_result" && open.length) out.set(open.shift()!, ev);
    else if (ev.kind === "user" || ev.kind === "done") open = [];
  });
  return out;
}

/** La herramienta en curso (sin respuesta aún) del último mensaje, para «Pensando…». */
function currentTool(log: AgentEvent[], results: Map<number, AgentEvent>): string | null {
  for (let i = log.length - 1; i >= 0; i--) {
    const ev = log[i];
    if (ev.kind === "user") return null;
    if (ev.kind === "tool") return results.has(i) ? null : ev.name ? toolLabel(ev.name) : null;
  }
  return null;
}

/** Una conversación con el agente (el chat o un hilo): sus líneas, «Pensando…» y el final
 *  a la vista cuando llega algo. */
export function ChatLog({ log, busy, ctx = MAIN_CTX, empty, className = "ag-log" }: {
  log: AgentEvent[]; busy: boolean; ctx?: CardCtx; empty?: ReactNode; className?: string;
}) {
  const end = useRef<HTMLDivElement>(null);
  const results = useMemo(() => pairResults(log), [log]);
  const tool = busy ? currentTool(log, results) : null;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [log.length, busy]);
  return (
    <div className={className} aria-live="polite">
      {log.length === 0 && empty && <div className="ag-empty">{empty}</div>}
      {log.map((ev, i) => <Line key={i} ev={ev} result={results.get(i)} ctx={ctx} />)}
      {busy && (
        <div className="ag-busy"><span className="ag-dots" aria-hidden="true" />{t("agente.pensando")}{tool && <i> {tool}</i>}</div>
      )}
      <div ref={end} />
    </div>
  );
}

export function AgentChat() {
  const { agentLog, agentBusy, agentState, threadBusy } = useStore();
  const [text, setText] = useState("");
  // Otro agente (un hilo) con su mensaje: aquí no se puede preguntar hasta que acabe (R43).
  const elsewhere = !!threadBusy || (!!agentState?.busy && !!agentState.thread);

  const submit = () => {
    const v = text.trim();
    if (!v || agentBusy || elsewhere) return;
    send({ type: "agent_ask", text: v });
    setText("");
  };

  return (
    <>
      <AgentUsageBar />
      <ChatLog log={agentLog} busy={agentBusy} empty={t("agente.chat.vacio")} />
      <form className="ag-input" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label htmlFor="ag-text" className="ag-sr">{t("agente.chat.etiqueta")}</label>
        <textarea
          id="ag-text"
          value={text}
          placeholder={t("agente.chat.placeholder")}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="ag-row">
          <span className="ag-note">{elsewhere ? t("agente.chat.ocupado_hilo") : t("agente.chat.atajos")}</span>
          {agentBusy
            ? <button type="button" className="ag-btn" onClick={() => send({ type: "agent_stop" })}>{t("agente.chat.parar")}</button>
            : <button type="submit" className="ag-btn primary" disabled={elsewhere || !text.trim()}>{t("agente.chat.enviar")}</button>}
        </div>
      </form>
    </>
  );
}
