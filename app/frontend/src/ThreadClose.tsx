// *Cerrar con decisión* (plan D167, R43): el agente propone una frase (`proponer_decision`)
// y aquí se edita y se guarda. Las fuentes de la propuesta se enseñan (no se editan); sin
// ellas, una decisión con cifras solo se guarda «marcada como estimación» (D19): el backend
// rechaza la que no, y su motivo sale en el cuadro.
import { useEffect, useRef } from "react";
import { getStore, setStore, useStore } from "./store";
import { cancelClose, saveDecision, writeDecisionMyself } from "./threadActions";
import { sourceLine } from "./AgentChat";
import { t } from "./i18n";

export function ThreadClose() {
  const { threadClosing: c, threads } = useStore();
  const box = useRef<HTMLTextAreaElement>(null);
  const th = c ? threads.find((x) => x.id === c.id) : undefined;

  useEffect(() => {
    if (c?.phase === "edit") box.current?.focus();
  }, [c?.phase]);

  if (!c) return null;
  const edit = (patch: Partial<typeof c>) => {
    const cur = getStore().threadClosing;
    if (cur) setStore({ threadClosing: { ...cur, ...patch, error: null } });
  };
  const figures = /\d/.test(c.text);
  return (
    <div className="th-close-back" onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Escape") cancelClose(); }}>
      <section className="th-close" role="dialog" aria-modal="true" aria-labelledby="th-close-h">
        <h2 id="th-close-h">{t("agente.hilo.cerrar")}</h2>
        <div className="th-close-sub">{th?.title}</div>
        {c.phase === "waiting" ? (
          <>
            <div className="ag-busy"><span className="ag-dots" aria-hidden="true" />{t("agente.cierre.resumiendo")}</div>
            <div className="ag-card-btns">
              <button type="button" className="ag-btn" onClick={cancelClose}>{t("agente.cancelar")}</button>
              <button type="button" className="ag-btn" onClick={writeDecisionMyself}>{t("agente.cierre.escribirla")}</button>
            </div>
          </>
        ) : (
          <>
            {c.note && <p className="ag-note">{c.note}</p>}
            <label className="th-close-label" htmlFor="th-close-text">{t("agente.cierre.frase")}</label>
            <textarea id="th-close-text" ref={box} value={c.text} disabled={c.phase === "saving"}
                      onChange={(e) => edit({ text: e.target.value })}
                      onKeyDown={(e) => { if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); saveDecision(); } }} />
            <div className="th-close-label">{t("agente.cierre.fuentes")}</div>
            {c.sources.length > 0
              ? <ul className="ag-srcs th-close-srcs">{c.sources.map((s, i) => <li key={i}>{sourceLine(s)}</li>)}</ul>
              : <p className="ag-note">{figures ? t("agente.cierre.sin_fuentes_cifras") : t("agente.cierre.sin_fuentes")}</p>}
            <label className="ag-check">
              <input type="checkbox" checked={c.estimate} disabled={c.phase === "saving"}
                     onChange={(e) => edit({ estimate: e.target.checked })} />
              <span>{t("agente.cierre.marcar")}</span>
            </label>
            {c.error && <p className="ag-reject" role="alert">{c.error}</p>}
            <div className="ag-card-btns">
              <button type="button" className="ag-btn" onClick={cancelClose}>{t("agente.cancelar")}</button>
              <button type="button" className="ag-btn primary" disabled={!c.text.trim() || c.phase === "saving"}
                      onClick={saveDecision}>{t("agente.cierre.guardar")}</button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
