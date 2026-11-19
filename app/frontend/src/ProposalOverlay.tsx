// Propuestas sobre lo que no es una tarjeta (D75): un texto suelto o una forma que el agente
// propone borrar. Excalidraw los pinta en su lienzo, así que el cambio no se puede marcar
// dentro: se recuadra el elemento y la pestaña lleva el texto con el diff. También la de una
// tarjeta de archivo (D176): la pestaña lleva el diff del archivo (`FileProposal`).
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { ProposalTab } from "./ProposalTab";
import { FileProposal } from "./OfficeMenu";
import { wordDiff } from "./proposal";
import { useStore } from "./store";
import { useSceneTick } from "./useSceneTick";
import { t } from "./i18n";

const isCard = (cd: unknown) => {
  const k = (cd as { kind?: string } | undefined)?.kind;
  return k === "postit" || k === "block";
};

export function ProposalOverlay({ api }: { api: ExcalidrawImperativeAPI }) {
  useSceneTick(api);
  const { proposals } = useStore();
  const st = api.getAppState();
  const z = st.zoom.value;
  const byId = new Map(api.getSceneElements().map((e) => [e.id, e]));
  return (
    <div className="prop-layer">
      {proposals.map((p) => {
        const e = byId.get(p.target);
        if (!e || isCard(e.customData)) return null;
        const x = (Math.min(e.x, e.x + e.width) + st.scrollX) * z;
        const y = (Math.min(e.y, e.y + e.height) + st.scrollY) * z;
        const w = Math.abs(e.width) * z, h = Math.abs(e.height) * z;
        return (
          <div key={p.id}>
            <div className={p.change.delete ? "prop-box del" : "prop-box"}
                 style={{ left: x - 6, top: y - 6, width: w + 12, height: h + 12 }} />
            <ProposalTab p={p} style={{ left: x - 6, top: y + h + 12 }} anchor={{ top: y - 6, bottom: y + h + 6 }}>
              {p.change.delete && <div className="ask-what">{t("agente.propuesta.borrar_elemento")}</div>}
              {p.change.text !== undefined && (
                <div className="ask-what">
                  {wordDiff(p.current.text ?? "", p.change.text).map((s, i) => (
                    <span key={i} className={s.kind === "same" ? undefined : s.kind === "del" ? "old" : "new"}>{s.text}</span>
                  ))}
                </div>
              )}
              {p.change.file && <FileProposal p={p} />}
            </ProposalTab>
          </div>
        );
      })}
    </div>
  );
}
