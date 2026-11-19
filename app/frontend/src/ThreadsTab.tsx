// La pestaña *Hilos* del panel derecho (plan D57, D166): todos los hilos del proyecto con su
// estado, sus mensajes y su decisión. Clic en uno anclado: se abre en ventana y la vista va a
// sus anclas. Uno sin anclas en la escena (borradas, aunque el backend aún no lo sepa) no sale
// en la pizarra: aquí se lee plegado («sin anclaje») y se puede borrar.
import { useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { useStore, type ThreadInfo } from "./store";
import { useSceneTick } from "./useSceneTick";
import { anchored, anchorName, liveAnchors } from "./threads";
import { deleteThread, loadThread, openThread } from "./threadActions";
import { ChatLog } from "./AgentChat";
import { messages, stateLabel, threadCtx } from "./ThreadLayer";
import { t } from "./i18n";

function Unanchored({ th }: { th: ThreadInfo }) {
  const { threadLogs } = useStore();
  const [confirm, setConfirm] = useState(false);
  const log = threadLogs[th.id];
  return (
    <div className="ag-thread-more">
      {log ? <ChatLog className="ag-thread-log" log={log} busy={false} ctx={threadCtx(th.id)} />
        : <div className="ag-note">{t("agente.cargando")}</div>}
      {confirm ? (
        <div className="ag-card-btns">
          <span className="ag-note">{t("agente.hilos.borrar_pregunta")}</span>
          <button type="button" className="ag-btn" onClick={() => setConfirm(false)}>{t("agente.cancelar")}</button>
          <button type="button" className="ag-btn danger" onClick={() => deleteThread(th.id)}>{t("agente.borrar")}</button>
        </div>
      ) : (
        <div className="ag-card-btns">
          <button type="button" className="ag-btn" onClick={() => setConfirm(true)}>{t("agente.hilo.borrar")}</button>
        </div>
      )}
    </div>
  );
}

function List({ api, live, names }: {
  api: ExcalidrawImperativeAPI | null; live: Set<string> | null; names: (ids: string[]) => string;
}) {
  const { threads } = useStore();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="ag-log">
      {threads.length === 0 ? (
        <div className="ag-empty">{t("agente.hilos.vacio")} <i>{t("agente.hilos.preguntar")}</i>.</div>
      ) : <p className="ag-note">{t("agente.hilos.nota")}</p>}
      {threads.map((th) => {
        const on = live ? anchored(th.anchors, live) : !th.sin_anclaje;
        const ids = live ? liveAnchors(th.anchors, live) : th.anchors;
        const click = () => {
          if (on) openThread(api, th.id, "window", true);
          else { loadThread(th.id); setOpen((o) => (o === th.id ? null : th.id)); }
        };
        return (
          <div key={th.id} className={on ? "ag-thread" : "ag-thread lost"}>
            <button type="button" className="ag-thread-main" onClick={click} aria-expanded={on ? undefined : open === th.id}
                    title={on ? t("agente.hilos.abrir_titulo") : t("agente.hilos.ver_titulo")}>
              <span className="ag-thread-top">
                <span className={`th-dot st-${th.state}`} />
                <b>{th.title}</b>
                <span className={`ag-chip st-${th.state}`}>{stateLabel(th.state)}</span>
              </span>
              <span className="ag-note">
                {on ? t("agente.hilo.anclado", { anclas: names(ids) }) : <span className="ag-lost">{t("agente.hilos.sin_anclaje")}</span>}
                {" · "}{messages(th.messages)}
              </span>
              {th.decision && <span className="ag-thread-dec"><b>{t("agente.hilos.decision")}</b> {th.decision.text}</span>}
            </button>
            {on && (
              <div className="ag-thread-btns">
                <button type="button" className="ag-btn small" onClick={() => openThread(api, th.id, "window", true)}>{t("agente.hilos.ver")}</button>
                <button type="button" className="ag-btn small" onClick={() => openThread(api, th.id, "full", true)}>{t("agente.hilo.pantalla_completa")}</button>
              </div>
            )}
            {!on && open === th.id && <Unanchored th={th} />}
          </div>
        );
      })}
    </div>
  );
}

function LiveList({ api }: { api: ExcalidrawImperativeAPI }) {
  const { types } = useStore();
  useSceneTick(api);
  const els = api.getSceneElements();
  const byId = new Map(els.map((e) => [e.id, e]));
  const names = (ids: string[]) =>
    ids.map((a) => anchorName(byId.get(a) as never, (ty) => types[ty]?.title)).join(" ↔ ");
  return <List api={api} live={new Set(byId.keys())} names={names} />;
}

export function ThreadsTab({ api }: { api: ExcalidrawImperativeAPI | null }) {
  return api ? <LiveList api={api} /> : <List api={null} live={null} names={(ids) => t(ids.length === 1 ? "agente.hilos.elementos_uno" : "agente.hilos.elementos_varios", { n: ids.length })} />;
}
