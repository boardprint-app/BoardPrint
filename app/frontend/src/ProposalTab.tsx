// Pestaña de una propuesta (plan §3, D75, diseño 2A): cuelga debajo del elemento con quién la
// hace, el motivo, sus fuentes y Aceptar / Rechazar. Si el elemento cambió desde la propuesta
// (desfasada), lo dice: lo que se enseña es contra lo que hay ahora, y aceptar aplica eso.
// Cabe en la ventana (prueba de punta a punta de FF 4.6, `tabFit`): debajo si cabe, si no encima,
// y si no, en el lado con más sitio con el contenido desplazándose y los botones a la vista.
// `anchor` (la caja del elemento en px de la capa) solo en la de ProposalOverlay; en una
// tarjeta, la caja es la de la tarjeta, que la contiene.
import { useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";
import { send } from "./socket";
import { AUTHOR_LABEL } from "./postit";
import { tabFit, type Proposal, type TabFit } from "./proposal";
import { measureChrome } from "./threadActions";
import { t } from "./i18n";

type Props = { p: Proposal; children?: ReactNode; style?: CSSProperties; anchor?: { top: number; bottom: number } };

export function ProposalTab({ p, children, style, anchor }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<TabFit>({ above: false, maxHeight: null });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const host = (anchor ? el.offsetParent : el.parentElement) as HTMLElement | null;
      if (!host) return;
      const hr = host.getBoundingClientRect();
      const scale = el.offsetHeight ? el.getBoundingClientRect().height / el.offsetHeight : 1;
      const top = anchor ? hr.top + anchor.top : hr.top;
      const bottom = anchor ? hr.top + anchor.bottom : hr.bottom;
      const body = el.querySelector<HTMLElement>(".ask-body");
      const natural = (el.offsetHeight + (body ? body.scrollHeight - body.clientHeight : 0)) * scale;
      const layer = document.querySelector(".th-layer")?.getBoundingClientRect();
      const chrome = measureChrome();          // la barra de arriba y la de abajo, medidas
      const area = layer ? { top: layer.y + chrome.top, bottom: layer.y + chrome.bottom }
                         : { top: 8, bottom: window.innerHeight - 8 };
      const next = tabFit(top, bottom, natural, area, scale);
      if (next.top !== undefined) next.top = Math.round((next.top - hr.top) / (scale || 1));
      setFit((f) => (f.above === next.above && f.maxHeight === next.maxHeight && f.top === next.top ? f : next));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  });
  const placed: CSSProperties = { ...style, ...(fit.maxHeight !== null ? { maxHeight: fit.maxHeight } : {}),
    ...(fit.above ? (anchor ? { top: anchor.top - 12, transform: "translateY(-100%)" }
                            : { top: "auto", bottom: "calc(100% + 12px)" }) : {}),
    ...(fit.top !== undefined ? { top: fit.top, bottom: "auto", transform: "none" } : {}) };
  const sources = (p.sources ?? []).map((s) => s.formula ? t("agente.propuesta.fuente_calculo", { formula: s.formula }) : s.ref ?? s.url ?? s.kind);
  // El foco vuelve a la pizarra: el botón desaparece al pulsarlo (R13).
  const act = (ev: MouseEvent<HTMLButtonElement>, msg: object) => {
    const board = ev.currentTarget.closest<HTMLElement>(".excalidraw") ?? document.querySelector<HTMLElement>(".excalidraw");
    send(msg);
    board?.focus();
  };
  return (
    <div ref={ref} className={fit.above ? "ask above" : "ask"} style={placed} role="group" aria-label={t("agente.propuesta.aria")}
         onPointerDown={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <div className="ask-body">
      <div className="ask-why">
        <b>{AUTHOR_LABEL[p.author] ?? p.author}</b>
        {p.stale && <span className="ask-stale">{t("agente.propuesta.desfasada")}</span>}
        <span>{p.reason}</span>
        {(sources.length > 0 || p.estimate) && (
          <span className="ask-src">
            {sources.length > 0 && t("agente.propuesta.fuente", { lista: sources.join("; ") })}
            {p.estimate && (sources.length ? " · " : "") + t("agente.propuesta.estimacion")}
          </span>
        )}
      </div>
      {children}
      </div>
      <div className="ask-row">
        <button className="ask-ok" onClick={(e) => act(e, { type: "proposal_accept", id: p.id, seen: p.current })}>
          {t("agente.propuesta.aceptar")}
        </button>
        <button className="ask-no" onClick={(e) => act(e, { type: "proposal_reject", id: p.id })}>{t("agente.propuesta.rechazar")}</button>
      </div>
    </div>
  );
}
