// *Ajustes → General → Workspaces* (PLAN_WORKSPACES W6, W7): la lista de `settings.toml` con
// su carpeta; el abierto, marcado (y el aviso si está en una carpeta sincronizada), y en los
// demás *Abrir* (si su carpeta está) y *Quitar de la lista*, que nunca borra nada del disco.
// Abrir otro rearranca el servidor y la ventana recarga (W3).
import { useEffect, useState } from "react";
import type { AppSettings } from "../appSettings";
import { t } from "../i18n";
import { canOpen, canRemove, entryState, outcomeText, type WorkspaceEntry } from "../workspaces";
import { listWorkspaces, openWorkspace, removeWorkspace, settle } from "../workspacesApi";
import { rowLabel } from "./common";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function WorkspacesRow({ ws }: { ws: AppSettings["workspace"] }) {
  const [list, setList] = useState<WorkspaceEntry[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);          // el id con una acción en curso
  const [wait, setWait] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listWorkspaces().then((l) => setList(l.workspaces)).catch((e) => setError(message(e)));
  }, []);

  const act = async (id: string, fn: () => Promise<void>) => {
    setBusy(id);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(message(e));
      setWait(null);
    }
    setBusy(null);
  };

  const open = (w: WorkspaceEntry) => act(w.id, async () => {
    setWait(t("workspaces.abriendo", { nombre: w.nombre }));
    const got = await openWorkspace({ id: w.id });
    const outcome = await settle(got);
    if (outcome === "recargar") return new Promise<void>(() => {});   // la ventana se recarga
    setWait(null);
    setError(outcomeText(outcome, got.workspace.nombre));
  });

  const remove = (w: WorkspaceEntry) => act(w.id, async () => {
    setList((await removeWorkspace(w.id)).workspaces);
  });

  return (
    <div className="st-row" data-row="workspace">
      <div className="st-row-text">
        <span className="st-row-title" id={rowLabel("workspace")}>{t("ajustes.workspace")}</span>
        <small className="st-row-hint">{t("ajustes.workspace.nota")}</small>
      </div>
      <div className="st-row-ctl">
        {list === null && !error && <p className="st-busy">{t("workspaces.cargando")}</p>}
        {list && (
          <ul className="st-ws-list" aria-labelledby={rowLabel("workspace")}>
            {list.map((w) => {
              const state = entryState(w);
              return (
                <li key={w.id} className={`st-item st-ws${state === "falta" ? " st-broken" : ""}`}>
                  <div className="st-pack-head">
                    <b>{w.nombre}</b>
                    {state !== "cerrado" && (
                      <span className={`st-badge${state === "abierto" ? " st-ws-open" : " st-chip-warn"}`}>
                        {t(state === "abierto" ? "workspaces.abierto" : "workspaces.no_se_encuentra")}
                      </span>
                    )}
                    {!w.abierto && (
                      <span className="st-actions">
                        {canOpen(w) && (
                          <button className="pull-btn" disabled={busy !== null} onClick={() => open(w)}>
                            {t("workspaces.abrir")}
                          </button>
                        )}
                        {canRemove(w) && (
                          <button className="pull-btn" disabled={busy !== null} onClick={() => remove(w)}>
                            {t("workspaces.quitar")}
                          </button>
                        )}
                      </span>
                    )}
                  </div>
                  <code className="st-path">{w.ruta}</code>
                  {w.abierto && ws?.nube && (
                    <p className="st-warn st-cloud" role="note">{t("ajustes.workspace.nube", { servicio: ws.nube })}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {wait && <p className="st-busy" role="status">{wait}</p>}
      </div>
      {error && <p className="pull-error st-row-error" role="alert">{error}</p>}
    </div>
  );
}
