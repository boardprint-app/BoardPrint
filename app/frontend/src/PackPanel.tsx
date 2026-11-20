// Panel de un bloque (docs/PLAN_PAQUETES.md §5, P7): sobre la pizarra, como el de *Traer*
// (D116), con la interfaz propia del paquete en su `iframe` o con los controles genéricos que
// declara `pack.view(…, panel=[…])` (P52): Parámetros a la izquierda, lo demás a la derecha.
// Si el bloque tiene vista previa (T26), lo de la derecha es la vista previa con lo que se
// está escribiendo, sin ejecutar. Debajo, la parte del conector del bloque si la declara (P41:
// *Traer* de Fusion); un bloque sin panel propio abre solo esa. Y el aviso (`toast`) que manda
// una interfaz.
//
// Con una interfaz de paquete dentro, el panel no se cierra con un clic fuera, y con la del
// bloque tampoco con el *Cerrar* y el Escape de la app: los pone ella (P71, `panelClosing`).
import { useEffect } from "react";
import { send } from "./socket";
import { t } from "./i18n";
import { tp } from "./packI18n";
import { setStore, useStore, type BlockState, type BlockType } from "./store";
import { connectorPart, hasPanel, PackFrame } from "./PackFrame";
import { BlockParams, useParamDraft } from "./BlockParams";
import { BlockOutputs } from "./BlockOutputs";
import { ControlFields } from "./GenericControls";
import { asOutputs, layout } from "./controls";
import { panelClosing } from "./packui";
import { usePreview } from "./blockPreview";

const close = () => setStore({ packPanel: null });
const NOTICE_MS = 4000;

export function PackPanel() {
  const { packPanel, blocks, types, packs, run, connectorInfo } = useStore();
  const st = packPanel ? blocks[packPanel] : undefined;
  const ty = st ? types[st.type] : undefined;
  const mine = hasPanel(ty);
  const conn = connectorPart(ty, connectorInfo, "panel");
  const closing = panelClosing(ty, conn);
  useEffect(() => {
    if (!packPanel || !closing.chrome) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [packPanel, closing.chrome]);
  if (!packPanel) return null;
  if (!st || !ty || !(mine || conn)) return null;
  const pack = packs.find((p) => p.id === ty.pack);
  const own = mine && ty.view?.panel === "ui";
  return (
    <div className="pull-backdrop" onMouseDown={(e) => { if (closing.outside && e.target === e.currentTarget) close(); }}>
      <div className={`pull${own || conn ? " pp" : ""}${own ? " pp-own" : ""}`} role="dialog" aria-modal="true" aria-label={ty.title}>
        <header className="pull-head">
          <div>
            <h2>{ty.title}</h2>
            <p>{mine ? t("bloques.panel.paquete", { name: `${pack?.name ?? ty.pack}${pack?.version ? ` ${pack.version}` : ""}` })
              : t("bloques.panel.conector", { name: connectorInfo[ty.connector ?? ""]?.title ?? ty.connector ?? "" })}</p>
          </div>
          {mine && !own && (
            <button type="button" className="pull-btn"
                    disabled={run !== null || st.status === "incompleto" || st.status === "no_disponible"}
                    onClick={() => send({ type: "run", block: packPanel })}>
              {t("bloques.tarjeta.ejecutar")}
            </button>
          )}
          {closing.chrome && <button type="button" className="pull-btn" onClick={close}>{t("bloques.paleta.cerrar")}</button>}
        </header>
        {mine && (own ? <PackFrame id={packPanel} blockType={st.type} surface="panel" />
          : <GenericPanel id={packPanel} st={st} ty={ty} />)}
        {conn && <PackFrame id={packPanel} blockType={st.type} surface="panel" part="connector" />}
      </div>
    </div>
  );
}

function GenericPanel({ id, st, ty }: { id: string; st: BlockState; ty: BlockType }) {
  const { blocks } = useStore();
  const { params, setDraft, commit } = useParamDraft(id, st);
  const { above, below } = layout(ty.view?.panel, []);
  // Lo de delante puede cambiar con el panel abierto: la vista previa se vuelve a pedir.
  const upstream = JSON.stringify(st.inputs ?? {}) + Object.values(st.inputs ?? {})
    .map((i) => blocks[i.block]?.status).join();
  const pv = usePreview<unknown>(ty.preview ? id : null, ty.preview ? params : null, upstream);
  const live = asOutputs(pv.data);
  const outputs = (ty.preview ? live : null) ?? st.outputs;
  const stale = !live && st.status === "desactualizado";
  const note = !ty.preview ? null
    : pv.error ? { err: true, text: t("bloques.panel.sin_vista_previa", { error: tp(ty.pack, pv.error) }) }
    : live ? { err: false, text: t("bloques.panel.vista_previa_ahora") }
    : pv.data !== null ? { err: true, text: t("bloques.panel.vista_previa_mala") }
    : { err: false, text: t("bloques.panel.calculando_vista_previa") };
  return (
    <div className={`pg${above.length && below.length ? "" : " one"}`}
         onKeyDown={(e) => e.stopPropagation()}>
      {above.length > 0 && (
        <section className="pg-col">
          <h3>{t("bloques.panel.parametros")}</h3>
          <BlockParams id={id} ty={ty} st={st} params={params} setDraft={setDraft} commit={commit} />
        </section>
      )}
      {below.length > 0 && (
        <section className="pg-col">
          {note && <p className={`pg-note${note.err ? " err" : ""}`}>{note.text}</p>}
          {below.map((c) => c === "results" ? (outputs && (
            <BlockOutputs key={c} id={id} outputs={outputs} stale={stale}
                          locks={(params.locks as Record<string, number> | undefined) ?? {}} />
          )) : <ControlFields key={c} control={c} outputs={outputs} stale={stale} size="panel" pack={ty.pack} />)}
        </section>
      )}
    </div>
  );
}

export function PackNotice() {
  const { notice } = useStore();
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setStore({ notice: null }), NOTICE_MS);
    return () => clearTimeout(t);
  }, [notice]);
  if (!notice) return null;
  return <div className={`pack-notice${notice.kind === "error" ? " err" : ""}`} role="status">{notice.text}</div>;
}
