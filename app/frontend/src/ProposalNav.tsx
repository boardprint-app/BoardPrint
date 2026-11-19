// Cuenta de propuestas pendientes en la píldora del proyecto (D80, 2A): ‹ › salta de una a
// otra, centra su elemento y lo selecciona.
import { useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { cycle } from "./proposal";
import { useStore } from "./store";
import { t } from "./i18n";

export function ProposalNav({ api }: { api: ExcalidrawImperativeAPI | null }) {
  const { proposals } = useStore();
  const [i, setI] = useState(0);
  const n = proposals.length;
  if (!n || !api) return null;
  const go = (k: number) => {
    setI(k);
    const p = proposals[k];
    const el = p && api.getSceneElements().find((e) => e.id === p.target);
    if (!el) return;
    api.scrollToContent(el, { animate: true, duration: 300 });
    api.updateScene({ appState: { selectedElementIds: { [el.id]: true } } });
  };
  const cur = Math.min(i, n - 1);
  return (
    <span className="pill-props">
      <button className="pp-go" onClick={() => go(cur)} title={t("agente.propuesta.ir")}
              aria-label={t(n > 1 ? "agente.propuesta.cuenta_varios" : "agente.propuesta.cuenta_uno", { n })}>
        <i className="pp-dot" aria-hidden="true" />
        {/* con la barra compactada (toolbar.ts, nivel 2), solo la cifra: el texto, en aria-label */}
        <span className="pp-text">{t(n > 1 ? "agente.propuesta.cuenta_varios" : "agente.propuesta.cuenta_uno", { n })}</span>
        <span className="pp-n" aria-hidden="true">{n}</span>
      </button>
      {n > 1 && (
        <>
          <button className="pp-step" aria-label={t("agente.propuesta.anterior")} onClick={() => go(cycle(n, cur, -1))}>‹</button>
          <button className="pp-step" aria-label={t("agente.propuesta.siguiente")} onClick={() => go(cycle(n, cur, 1))}>›</button>
        </>
      )}
    </span>
  );
}
