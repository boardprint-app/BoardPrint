// La pestaña *Revisor* del panel del agente (FF 6.1, PLAN_V020 §3, V2-V6): *Revisar* con un
// foco opcional («la transmisión de J2»), lo que dijo (el mismo `ChatLog` que el de diseño, con
// sus tarjetas de privacidad y tope reenviadas con `review_ask`), *Cancelar* mientras revisa y
// la cuenta de sus post-its aceptados, descartados y abiertos (la métrica de §9). Apagado, o con
// el de diseño trabajando (uno a la vez, V6), el botón dice por qué no.
import { useState } from "react";
import { send } from "./socket";
import { getStore, setStore, useStore } from "./store";
import { ChatLog, type CardCtx } from "./AgentChat";
import { AgentUsageBar } from "./AgentUsage";
import { blockText, FOCO_MAX, modeLabel, postitsLine, reviewAsk, reviewBlock } from "./review";
import { openSettings } from "./settings";
import { useAppSettings } from "./appSettings";
import { t } from "./i18n";

/** Sus tarjetas de privacidad y tope vuelven a pedir la revisión con su foco. */
const REVIEW_CTX: CardCtx = {
  resend: (ev, once) => send(reviewAsk(ev.foco, once)),
  drop: (ev) => setStore({ reviewLog: getStore().reviewLog.filter((e) => e !== ev) }),
};

export function ReviewTab() {
  const { reviewLog, reviewBusy, reviewState, agentState, threadBusy } = useStore();
  const app = useAppSettings();
  const [foco, setFoco] = useState("");
  // La intrusividad, la de los ajustes (se recargan al cambiarla, también desde otra ventana);
  // `review_state` solo llega al abrir y al acabar cada revisión.
  const mode = app?.agentes.intrusividad_revisor ?? reviewState?.intrusiveness ?? "a_demanda";
  const block = reviewBusy ? null : reviewBlock({ intrusiveness: mode, agent: agentState, threadBusy });

  const submit = () => {
    if (reviewBusy || block) return;
    send(reviewAsk(foco));
    setFoco("");
  };

  return (
    <>
      <AgentUsageBar />
      <div className="rv-head">
        <span className="rv-postits" title={t("agente.revisor.postits_titulo")}>{postitsLine(reviewState?.postits)}</span>
        <button type="button" className="ag-link rv-mode" onClick={() => openSettings("agentes", "intrusividad_revisor")}
                title={t("agente.revisor.modo_titulo")}>
          {modeLabel(mode)}
        </button>
      </div>
      <ChatLog log={reviewLog} busy={reviewBusy} ctx={REVIEW_CTX} empty={t("agente.revisor.vacio")} />
      <form className="ag-input rv-input" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label htmlFor="rv-foco" className="ag-sr">{t("agente.revisor.foco_etiqueta")}</label>
        <input id="rv-foco" className="rv-foco" value={foco} maxLength={FOCO_MAX} disabled={reviewBusy || !!block}
               placeholder={t("agente.revisor.foco_placeholder")} onChange={(e) => setFoco(e.target.value)} />
        {block && <p className="rv-why" role="note">{blockText(block)}</p>}
        <div className="ag-row">
          <span className="ag-note">{reviewBusy ? t("agente.revisor.revisando") : block ? "" : t("agente.revisor.nota")}</span>
          {block === "apagado" && (
            <button type="button" className="ag-btn" onClick={() => openSettings("agentes", "intrusividad_revisor")}>
              {t("agente.revisor.activar")}
            </button>
          )}
          {reviewBusy
            ? <button type="button" className="ag-btn" onClick={() => send({ type: "review_cancel" })}>{t("agente.revisor.cancelar")}</button>
            : <button type="submit" className="ag-btn primary" disabled={!!block}>{t("agente.revisor.revisar")}</button>}
        </div>
      </form>
    </>
  );
}
