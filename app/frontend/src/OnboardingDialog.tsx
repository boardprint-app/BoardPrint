// La ventana del agente de onboarding (docs/PLAN_ONBOARDING.md §3, N2, N4, N13; el estado y la
// lógica, en onboarding.ts y onboardingChat.ts). Modal y encima de todo (de Ajustes también, desde donde se abre):
// cabecera con el consumo del workspace y su tope, *Empezar de nuevo* y *Cerrar*; el mismo
// `ChatLog` que el agente de diseño, con su WebSocket (`/ws/onboarding`) y sus tarjetas de
// propuesta (lo de ahora y lo nuevo, *Guardar* / *Descartar*); debajo, la caja de escribir y
// *Elegir Excel…* (N7: la tarjeta de importación abre el importador de la Librería rellenado).
// Escape cierra; el agente, si trabajaba, sigue y se ve al volver a abrir.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChatLog, type CardCtx } from "./AgentChat";
import { usd } from "./AgentUsage";
import { t } from "./i18n";
import { lineDiff, providersDiff, unitsDiff, type OnboardingState, type Provider, type ProposalStatus } from "./onboarding";
import {
  chooseExcel, closeOnboarding, closeProposal, dropEvent, onboardingSend, openOnboarding, useOnboarding,
} from "./onboardingChat";
import { VALUE_PREFIX, type ImportInitial } from "./library";
import { openLibrary } from "./libraryOpen";
import { closeSettings, openSettings } from "./settings";
import type { AgentEvent } from "./store";
import "./agent.css";
import "./onboarding.css";

const CTX: CardCtx = {
  resend: (ev) => onboardingSend({ type: "agent_ask", text: ev.text }),
  drop: dropEvent,
  send: onboardingSend,
  render: (ev) => ev.kind === "proposal" ? <ProposalCard p={ev} />
    : ev.kind === "limit" ? <LimitCard ev={ev} />
    : ev.kind === "excel" ? <ExcelCard ev={ev} />
    : undefined,
};

export function OnboardingDialog() {
  const s = useOnboarding();
  if (!s.open) return null;
  return <OnboardingWindow />;
}

function OnboardingWindow() {
  const { log, busy, state, problem } = useOnboarding();
  const [text, setText] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);
  const [excelBusy, setExcelBusy] = useState(false);
  const [excelError, setExcelError] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const ready = state !== null && !problem;

  useEffect(() => input.current?.focus(), []);

  // Escape cierra esta, antes que nadie: Ajustes (si está debajo) no lo ve.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      closeOnboarding();
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, []);

  const submit = () => {
    const v = text.trim();
    if (!v || busy || !ready) return;
    onboardingSend({ type: "agent_ask", text: v });
    setText("");
  };

  return (
    <div className="ob-backdrop">
      <div className="ob" role="dialog" aria-modal="true" aria-labelledby="ob-title">
        <div className="ob-head">
          <h2 id="ob-title">{t("onboarding.titulo")}</h2>
          {state && <Usage state={state} />}
          <button className="ag-x" onClick={closeOnboarding} aria-label={t("onboarding.cerrar")} title={t("onboarding.cerrar")}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                 strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <div className="ob-bar">
          {confirmReset ? (
            <div className="ob-confirm" role="alert">
              <span>{t("onboarding.empezar_pregunta")}</span>
              <button className="ag-btn" onClick={() => setConfirmReset(false)}>{t("onboarding.empezar_no")}</button>
              <button className="ag-btn primary" disabled={busy} onClick={() => {
                onboardingSend({ type: "agent_reset" });
                setConfirmReset(false);
              }}>{t("onboarding.empezar_si")}</button>
            </div>
          ) : (
            <button className="ag-link" disabled={busy || !ready || log.length === 0} onClick={() => setConfirmReset(true)}>
              {t("onboarding.empezar")}
            </button>
          )}
        </div>
        {problem && <p className="ob-problem" role="status">{problem}</p>}
        {!state && !problem
          ? <p className="ob-problem ob-wait" role="status">{t("onboarding.conectando")}</p>
          : <ChatLog log={log} busy={busy} ctx={CTX} empty={t("onboarding.vacio")} />}
        <form className="ag-input" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <label htmlFor="ob-text" className="ag-sr">{t("onboarding.etiqueta")}</label>
          <textarea id="ob-text" ref={input} value={text} disabled={!ready}
                    placeholder={t("onboarding.placeholder")}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        submit();
                      }
                    }} />
          {excelError && <p className="ag-reject" role="alert">{excelError}</p>}
          <div className="ag-row">
            <span className="ag-note">{t("agente.chat.atajos")}</span>
            <button type="button" className="ag-btn" disabled={!ready || busy || excelBusy}
                    title={t("onboarding.excel.nota")} onClick={async () => {
                      setExcelBusy(true);
                      setExcelError(await chooseExcel());
                      setExcelBusy(false);
                    }}>
              {excelBusy ? t("onboarding.excel.abriendo") : t("onboarding.excel.elegir")}
            </button>
            {busy
              ? <button type="button" className="ag-btn" onClick={() => onboardingSend({ type: "agent_stop" })}>{t("agente.chat.parar")}</button>
              : <button type="submit" className="ag-btn primary" disabled={!ready || !text.trim()}>{t("agente.chat.enviar")}</button>}
          </div>
        </form>
      </div>
    </div>
  );
}

/** Lo gastado por el onboarding del workspace frente a su tope (N6). */
function Usage({ state }: { state: OnboardingState }) {
  const used = state.usage.total.usd;
  const share = state.limit > 0 ? Math.min(1, used / state.limit) : 0;
  const level = share >= 1 ? "full" : share >= 0.8 ? "high" : "";
  return (
    <span className="ob-usage" title={t("onboarding.consumo")}>
      <span className={`ag-meter ${level}`} aria-hidden="true"><i style={{ width: `${share * 100}%` }} /></span>
      <span className="ag-usage-num">{t("agente.consumo.num", { usado: usd(used), tope: usd(state.limit) })}</span>
    </span>
  );
}

/** El tope alcanzado (N13): sin *Seguir solo este mensaje*; se sube en *Ajustes → Agentes*. */
function LimitCard({ ev }: { ev: AgentEvent }) {
  return (
    <div className="ag-card warn" role="alert">
      <div className="ag-card-title">{t("onboarding.tope.titulo")}</div>
      <p>{t("onboarding.tope.texto", { usado: usd(ev.used ?? 0), tope: usd(ev.limit ?? 0) })}</p>
      <div className="ag-card-btns">
        <button className="ag-btn primary" onClick={() => {
          dropEvent(ev);
          closeOnboarding();
          openSettings("agentes", "tope_onboarding_usd");
        }}>{t("onboarding.tope.ajustes")}</button>
      </div>
    </div>
  );
}

const queLabel = (que?: string) => ({
  perfil: t("onboarding.que.perfil"), proveedores: t("onboarding.que.proveedores"), unidades: t("onboarding.que.unidades"),
  importacion: t("onboarding.que.importacion"),
} as Record<string, string>)[que ?? ""] ?? que ?? "";

/** El Excel elegido con *Elegir Excel…* (N7): lo que el agente va a ver de él. */
function ExcelCard({ ev }: { ev: AgentEvent }) {
  const columns = ev.columns ?? [];
  return (
    <div className="ag-card ob-excel">
      <div className="ag-card-title">{t("onboarding.excel.titulo", { nombre: ev.nombre ?? "" })}</div>
      <p className="ag-note">
        {[ev.sheet && t("onboarding.excel.hoja", { hoja: ev.sheet }),
          t(ev.rows === 1 ? "libreria.importar.filas_uno" : "libreria.importar.filas", { n: ev.rows ?? 0 }),
          t("onboarding.excel.columnas", { n: columns.length })].filter(Boolean).join(" · ")}
      </p>
      <p className="ob-cols">{columns.join(" · ")}</p>
    </div>
  );
}

const statusLabel = (s: ProposalStatus) => t(`onboarding.estado.${s}`);

/** Una propuesta (N4): qué, por qué, lo de ahora y lo nuevo, sus fuentes y *Guardar* /
 *  *Descartar* mientras está pendiente. Guardada, descartada o caducada, solo su estado. */
function ProposalCard({ p }: { p: AgentEvent }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status: ProposalStatus = p.estado ?? "pendiente";
  const act = async (action: "save" | "discard") => {
    setBusy(true);
    setError(await closeProposal(p, action));
    setBusy(false);
  };
  const sources = Array.isArray(p.fuentes) ? p.fuentes : [];
  let diff: ReactNode = null;
  if (p.que === "perfil") diff = <ProfileDiff before={String(p.antes ?? "")} after={String(p.nuevo ?? "")} />;
  else if (p.que === "proveedores") diff = <ProvidersView before={p.antes ?? []} after={p.nuevo ?? []} />;
  else if (p.que === "unidades") diff = <UnitsView before={p.antes ?? {}} after={p.nuevo ?? {}} />;
  else if (p.que === "importacion") diff = <ImportView n={p.nuevo ?? {}} />;
  const importer = p.que === "importacion";
  return (
    <div className={`ag-card ob-card s-${status}`}>
      <div className="ob-card-head">
        <span className="ag-card-title">{queLabel(p.que)}</span>
        <span className={`ob-state s-${status}`}>{statusLabel(status)}</span>
      </div>
      {p.motivo && <p>{p.motivo}</p>}
      {diff}
      {sources.length > 0 && (
        <div className="ob-srcs">
          <b>{t("onboarding.tarjeta.fuentes")}</b>
          <ul className="ag-srcs">{sources.map((s, i) => (
            <li key={i}><span className="ob-url">{s.url}</span> {t("onboarding.tarjeta.cita", { cita: s.cita })}</li>
          ))}</ul>
        </div>
      )}
      {status === "caducada" && <p className="ag-meta warn">{t("onboarding.tarjeta.caducada")}</p>}
      {/* cerrada (caducada, o ya guardada desde otra ventana), lo dice su estado */}
      {error && status === "pendiente" && <p className="ag-reject" role="alert">{error}</p>}
      {status === "pendiente" && (
        <div className="ag-card-btns">
          <button className="ag-btn" disabled={busy} onClick={() => act("discard")}>{t("onboarding.tarjeta.descartar")}</button>
          {importer ? (
            <button className="ag-btn primary" disabled={busy} onClick={() => {
              // la Librería va debajo del chat y de Ajustes (z 900): los dos se cierran, y al
              // cerrarla se vuelve al chat
              closeOnboarding();
              closeSettings();
              openLibrary({ ...(p.nuevo as ImportInitial), proposal: p.id }, openOnboarding);
            }}>{t("onboarding.tarjeta.importador")}</button>
          ) : (
            <button className="ag-btn primary" disabled={busy} onClick={() => act("save")}>{t("onboarding.tarjeta.guardar")}</button>
          )}
        </div>
      )}
    </div>
  );
}

/** El perfil: las líneas quitadas y añadidas, con dos de contexto alrededor de cada cambio. */
function ProfileDiff({ before, after }: { before: string; after: string }) {
  return (
    <div className="ob-diff" role="group" aria-label={t("onboarding.que.perfil")}>
      {lineDiff(before, after, 2).map((l, i) => l.op === "…"
        ? <div key={i} className="d-gap">{t(l.n === 1 ? "onboarding.tarjeta.iguales_uno" : "onboarding.tarjeta.iguales_varias", { n: l.n })}</div>
        : <div key={i} className={l.op === "+" ? "d-add" : l.op === "-" ? "d-del" : "d-eq"}>
            <span aria-hidden="true">{l.op === "=" ? " " : l.op}</span>{l.text || " "}
          </div>)}
    </div>
  );
}

const providerLine = (p: Provider) => `${p.nombre} · ${p.dominio} · ${p.tipos.length ? p.tipos.join(", ") : t("onboarding.prov.todos_tipos")}`;

/** Los proveedores: la lista nueva en su orden (la preferencia) con lo nuevo, lo movido y lo
 *  que cambia marcado, y debajo los que se quitan. */
function ProvidersView({ before, after }: { before: Provider[]; after: Provider[] }) {
  const { rows, removed } = providersDiff(before, after);
  return (
    <div className="ob-provs">
      {rows.length === 0 ? <p className="ag-note">{t("onboarding.prov.ninguno")}</p> : (
        <ol>{rows.map(({ p, marks }) => (
          <li key={p.dominio} className={marks.includes("nuevo") ? "m-nuevo" : undefined}>
            {providerLine(p)}
            {marks.map((m) => <span key={m} className={`ob-mark m-${m}`}>{t(`onboarding.prov.${m}`)}</span>)}
          </li>
        ))}</ol>
      )}
      {removed.length > 0 && (
        <div className="ob-removed">
          <b>{t("onboarding.prov.quitados")}</b>
          <ul>{removed.map((p) => <li key={p.dominio}><del>{providerLine(p)}</del></li>)}</ul>
        </div>
      )}
    </div>
  );
}

/** Las unidades: las cinco magnitudes, la de ahora y la nueva, con las que cambian marcadas. */
function UnitsView({ before, after }: { before: Record<string, string>; after: Record<string, string> }) {
  return (
    <table className="ob-units">
      <thead><tr>
        <th>{t("onboarding.unid.magnitud")}</th><th>{t("onboarding.unid.ahora")}</th><th>{t("onboarding.unid.nueva")}</th>
      </tr></thead>
      <tbody>{unitsDiff(before, after).map((r) => (
        <tr key={r.m} className={r.changed ? "changed" : undefined}>
          <td>{t(`unidades.${r.m}`)}</td><td>{r.antes}</td><td>{r.nuevo}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}

const targetName = (target: string) =>
  target.startsWith(VALUE_PREFIX) ? target.slice(VALUE_PREFIX.length) : t(`libreria.destino.${target}`);

/** La importación propuesta (N7): el archivo, la hoja, el tipo y a qué va cada columna. */
function ImportView({ n }: { n: Partial<ImportInitial> }) {
  const name = (n.path ?? "").split(/[\\/]/).pop() ?? "";
  return (
    <div className="ob-import">
      <p className="ag-note">
        {[name, n.sheet && t("onboarding.excel.hoja", { hoja: n.sheet }),
          n.type ? t("onboarding.importacion.tipo", { tipo: n.type }) : t("onboarding.importacion.sin_tipo")]
          .filter(Boolean).join(" · ")}
      </p>
      <table className="ob-units">
        <thead><tr><th>{t("libreria.importar.columna")}</th><th>{t("libreria.importar.va_a")}</th></tr></thead>
        <tbody>{Object.entries(n.mapping ?? {}).map(([col, target]) => (
          <tr key={col}><td>{col}</td><td>{targetName(target)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}
