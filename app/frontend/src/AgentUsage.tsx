// Consumo y tope del agente en el panel (plan D168, R41) y *Excluir adjuntos* (D169): lo
// gastado del proyecto frente al tope, en tokens y dólares equivalentes, el tope propio del
// proyecto (o el de los ajustes) y la casilla. Todo sale de `agent_state` y se cambia con
// `agent_settings`; el backend valida (un tope tiene que ser mayor que cero).
import { useEffect, useState } from "react";
import { send } from "./socket";
import { useStore } from "./store";
import { getLanguage, t } from "./i18n";
import { agentName } from "./review";

// Los números, con la coma o el punto del idioma de la interfaz (se crean al usarlos: el
// idioma llega con los ajustes, después de cargar el módulo).
const FORMATS = new Map<string, { num2: Intl.NumberFormat; num1: Intl.NumberFormat }>();
function formats() {
  const locale = getLanguage() === "en" ? "en-US" : "es-ES";
  let f = FORMATS.get(locale);
  if (!f) {
    f = { num2: new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
          num1: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }) };
    FORMATS.set(locale, f);
  }
  return f;
}

/** Dólares equivalentes con dos decimales, con el separador del idioma (0,42 o 0.42). */
export const usd = (n: number) => formats().num2.format(n);

/** Un número tal cual, con la coma decimal en español (1,5) y el punto en inglés (1.5). */
export const decimal = (n: number) => (getLanguage() === "es" ? String(n).replace(".", ",") : String(n));

/** Tokens en corto: 950, 12,3 k, 1,2 M. */
export function tokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${formats().num1.format(n / 1000)} k`;
  return `${formats().num1.format(n / 1_000_000)} M`;
}

export function AgentUsageBar() {
  const { agentState: st } = useStore();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  useEffect(() => {
    if (st) setDraft(st.limit_own ? decimal(st.limit) : "");
  }, [st?.limit, st?.limit_own]);
  if (!st) return null;
  const tot = st.usage.total;
  const used = tot.usd;
  const share = st.limit > 0 ? Math.min(1, used / st.limit) : 0;
  const level = share >= 1 ? "full" : share >= 0.8 ? "high" : "";

  const saveLimit = () => {
    const v = Number(draft.replace(",", ".").trim());
    if (!draft.trim()) {
      if (st.limit_own) send({ type: "agent_settings", limit: null });
      return;
    }
    if (Number.isFinite(v) && v > 0 && v !== st.limit) send({ type: "agent_settings", limit: v });
    else setDraft(st.limit_own ? decimal(st.limit) : "");
  };

  return (
    <div className={open ? "ag-usage open" : "ag-usage"}>
      <button className="ag-usage-row" aria-expanded={open} onClick={() => setOpen(!open)}
              title={t("agente.consumo.titulo")}>
        <span className="ag-usage-label">{t("agente.consumo.etiqueta")}</span>
        <span className={`ag-meter ${level}`} aria-hidden="true"><i style={{ width: `${share * 100}%` }} /></span>
        <span className="ag-usage-num">{t("agente.consumo.num", { usado: usd(used), tope: usd(st.limit) })}</span>
        {st.exclude_attachments && <span className="ag-chip" title={t("agente.consumo.chip_titulo")}>{t("agente.consumo.sin_adjuntos")}</span>}
        <span className="ag-chev" aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="ag-usage-body">
          <div className="ag-usage-tokens">
            {t("agente.consumo.tokens", {
              entrada: tokens(tot.input + tot.cache_creation), salida: tokens(tot.output), cache: tokens(tot.cache_read),
              mensajes: t(tot.messages === 1 ? "agente.mensajes_uno" : "agente.mensajes_varios", { n: tot.messages }),
            })}
          </div>
          {/* lo de cada agente (diseño y revisor, V7), si ya ha gastado más de uno */}
          {Object.keys(st.usage.agents ?? {}).length > 1 && (
            <div className="ag-usage-tokens">
              {Object.entries(st.usage.agents).map(([k, u]) => t("agente.consumo.de_agente", { agente: agentName(k), usd: usd(u.usd) })).join(" · ")}
            </div>
          )}
          <p className="ag-note">{t("agente.consumo.nota")}</p>
          <label className="ag-field">
            <span>{t("agente.consumo.tope")}</span>
            <input inputMode="decimal" value={draft} placeholder={usd(st.limit)}
                   onChange={(e) => setDraft(e.target.value)} onBlur={saveLimit}
                   onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
            <span>USD</span>
          </label>
          {st.limit_own ? (
            <button className="ag-link" onClick={() => send({ type: "agent_settings", limit: null })}>
              {t("agente.consumo.usar_ajustes")}
            </button>
          ) : <p className="ag-note">{t("agente.consumo.sin_tope", { tope: usd(st.limit) })}</p>}
          <label className="ag-check">
            <input type="checkbox" checked={st.exclude_attachments}
                   onChange={(e) => send({ type: "agent_settings", exclude_attachments: e.target.checked })} />
            <span><b>{t("agente.consumo.excluir")}</b>: {t("agente.consumo.excluir_nota")}</span>
          </label>
        </div>
      )}
    </div>
  );
}
