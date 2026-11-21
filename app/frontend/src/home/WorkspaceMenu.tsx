// El chip del workspace en la pantalla de inicio (PLAN_WORKSPACES W6): un menú con la lista (el
// abierto marcado; uno cuya carpeta falta, «no se encuentra» y sin abrirse, W7), *Nuevo
// workspace…*, *Abrir carpeta…* (una que ya es un workspace, con el diálogo del sistema) y la
// lista en Ajustes. Abrir otro rearranca el servidor y la ventana recarga (W3); mientras,
// `onBusy` da el texto de la espera y lo que rechace el backend va a `onError`.
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { openSettings } from "../settings";
import { entryState, outcomeText, type WorkspaceEntry, type WorkspaceList } from "../workspaces";
import { chooseFolder, listWorkspaces, openWorkspace, settle } from "../workspacesApi";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

type Props = {
  label: string;                       // lo que dice el chip
  onNew: (base: string | null) => void;
  onBusy: (text: string | null) => void;
  onError: (text: string) => void;
  disabled?: boolean;
};

export function WorkspaceMenu({ label, onNew, onBusy, onError, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<WorkspaceList | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const chip = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    setList(null);
    listWorkspaces().then(setList).catch((e) => { setOpen(false); onError(message(e)); });
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) {
        setOpen(false);
        if (e instanceof KeyboardEvent) chip.current?.focus();
      }
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open, onError]);

  // con la lista ya pintada, el foco en la primera opción que se puede elegir
  useEffect(() => {
    if (list) box.current?.querySelector<HTMLButtonElement>(".ws-menu-list button:not(:disabled)")?.focus();
  }, [list]);

  const go = async (target: { id: string } | { ruta: string }, label: string) => {
    setOpen(false);
    onBusy(t("workspaces.abriendo", { nombre: label }));
    try {
      const got = await openWorkspace(target);
      const outcome = await settle(got);
      if (outcome === "recargar") return;              // la ventana se recarga
      onBusy(null);
      if (outcome !== "mismo") onError(outcomeText(outcome, got.workspace.nombre));
    } catch (e) {
      onBusy(null);
      onError(message(e));
    }
  };

  const openFolder = async () => {
    setOpen(false);
    try {
      const ruta = await chooseFolder();
      if (ruta) await go({ ruta }, ruta);
    } catch (e) {
      onError(t("bienvenida.carpeta.elegir_fallo", { motivo: message(e) }));
    }
  };

  const item = (w: WorkspaceEntry) => {
    const state = entryState(w);
    return (
      <li key={w.id}>
        <button role="menuitemradio" aria-checked={w.abierto} disabled={state === "falta"}
                className={`ws-menu-ws ws-${state}`}
                onClick={() => (w.abierto ? setOpen(false) : go({ id: w.id }, w.nombre))}>
          <span className="ws-menu-mark" aria-hidden="true">{w.abierto ? "✓" : ""}</span>
          <span className="ws-menu-text">
            <b>{w.nombre}</b>
            <small>{w.ruta}</small>
          </span>
          {state !== "cerrado" && (
            <span className="ws-menu-tag">{t(state === "abierto" ? "workspaces.abierto" : "workspaces.no_se_encuentra")}</span>
          )}
        </button>
      </li>
    );
  };

  return (
    <div className="ws-menu-wrap" ref={box}>
      <button ref={chip} className="ws-chip" aria-haspopup="menu" aria-expanded={open} disabled={disabled}
              onClick={() => setOpen((o) => !o)}>
        {label}
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
      </button>
      {open && (
        <div className="ws-menu" role="menu" aria-label={t("workspaces.menu")}>
          {list === null
            ? <p className="ws-menu-wait">{t("workspaces.cargando")}</p>
            : <ul className="ws-menu-list">{list.workspaces.map(item)}</ul>}
          <hr />
          <button role="menuitem" disabled={list === null}
                  onClick={() => { setOpen(false); onNew(list?.carpeta_base ?? null); }}>
            {t("workspaces.nuevo_menu")}
          </button>
          <button role="menuitem" onClick={openFolder}>{t("workspaces.abrir_carpeta")}</button>
          <button role="menuitem" onClick={() => { setOpen(false); openSettings("general", "workspace"); }}>
            {t("workspaces.en_ajustes")}
          </button>
        </div>
      )}
    </div>
  );
}
