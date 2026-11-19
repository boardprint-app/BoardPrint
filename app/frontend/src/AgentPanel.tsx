// Panel derecho definitivo (plan D56, D174): con el skin, redimensionable por su borde
// izquierdo (mínimo 320 px, máximo el 60 % de la ventana, `panel.ts`; el ancho en
// `settings.toml`, `[paneles] derecho`), con las pestañas *Agente de diseño* (el chat, D173),
// *Hilos* (la lista, `ThreadsTab`; los hilos en sí van sobre la pizarra, `ThreadLayer`) y
// *Versiones* (D76). Plegado, deja el botón flotante. Abierto, la pizarra se estrecha a su
// lado (`--rp-w` en `.app`), como en el prototipo: no tapa los controles de Excalidraw de la
// derecha.
import { useEffect, useRef, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { apiFetch } from "./auth";
import { useStore } from "./store";
import { VersionsTab } from "./VersionsTab";
import { AgentChat } from "./AgentChat";
import { ThreadsTab } from "./ThreadsTab";
import { clampPanel, PANEL_DEFAULT, PANEL_MIN } from "./panel";
import { t } from "./i18n";

type Tab = "agent" | "threads" | "versions";

type Props = { projectId: string; api: ExcalidrawImperativeAPI | null; beforeSave: () => Promise<void> };

export function AgentPanel({ projectId, api, beforeSave }: Props) {
  const { compare, threads, project } = useStore();
  const [open, setOpen] = useState(true);
  const [tab, setTab] = useState<Tab>("agent");
  const [wanted, setWanted] = useState(PANEL_DEFAULT);       // el guardado (o el arrastrado)
  const [viewport, setViewport] = useState(window.innerWidth);
  const [dragging, setDragging] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const fab = useRef<HTMLButtonElement>(null);
  const width = clampPanel(wanted, viewport);

  useEffect(() => {
    let live = true;
    apiFetch("/api/settings/panels")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => { if (live && b && Number(b.right)) setWanted(Number(b.right)); })
      .catch(() => undefined);
    const onResize = () => setViewport(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => {
      live = false;
      window.removeEventListener("resize", onResize);
    };
  }, []);

  // La pizarra deja sitio al panel (styles.css, `--rp-w`).
  useEffect(() => {
    const app = (ref.current ?? fab.current)?.closest(".app") as HTMLElement | null;
    app?.style.setProperty("--rp-w", open ? `${width}px` : "0px");
  }, [open, width]);

  const startDrag = (e: React.PointerEvent) => {
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    setDragging(true);
  };
  const onDrag = (e: React.PointerEvent) => {
    if (dragging) setWanted(clampPanel(window.innerWidth - e.clientX, window.innerWidth));
  };
  const endDrag = (e: React.PointerEvent) => {
    if (!dragging) return;
    setDragging(false);
    const w = clampPanel(window.innerWidth - e.clientX, window.innerWidth);
    setWanted(w);
    void apiFetch("/api/settings/panels", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ right: Math.max(PANEL_MIN, w) }),
    }).catch(() => undefined);
  };

  if (!open) {
    return <button ref={fab} className="ag-fab" onClick={() => setOpen(true)}>
      {compare ? t("agente.panel.versiones") : t("agente.panel.agente")}
    </button>;
  }
  const tabBtn = (id: Tab, label: string, extra?: string) => (
    <button role="tab" aria-selected={tab === id} className={tab === id ? "ag-tab on" : "ag-tab"}
            onClick={() => setTab(id)}>
      {label}{extra && <span className="ag-count">{extra}</span>}
    </button>
  );
  return (
    <aside ref={ref} className={dragging ? "ag-panel dragging" : "ag-panel"} style={{ width }}
           aria-label={t("agente.panel.aria")} onKeyDown={(e) => e.stopPropagation()}>
      <div className="ag-grip" role="separator" aria-orientation="vertical" aria-label={t("agente.panel.ancho")}
           aria-valuenow={width} aria-valuemin={PANEL_MIN}
           title={t("agente.panel.arrastra")}
           onPointerDown={startDrag} onPointerMove={onDrag} onPointerUp={endDrag}
           onPointerCancel={() => setDragging(false)} />
      <div className="ag-head">
        <strong>{t("agente.panel.conversacion")}</strong>
        <span className="ag-proj">{project?.name}</span>
        <button className="ag-x" onClick={() => setOpen(false)} aria-label={t("agente.panel.esconder")} title={t("agente.panel.esconder")}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
        </button>
      </div>
      <div className="ag-tabs" role="tablist">
        {tabBtn("agent", t("agente.panel.agente"))}
        {tabBtn("threads", t("agente.panel.hilos"), threads.length ? String(threads.length) : undefined)}
        {tabBtn("versions", t("agente.panel.versiones"))}
      </div>
      {tab === "versions" ? <VersionsTab projectId={projectId} api={api} beforeSave={beforeSave} />
        : tab === "threads" ? <ThreadsTab api={api} /> : <AgentChat />}
    </aside>
  );
}
