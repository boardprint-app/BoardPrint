// El aviso de versión nueva (docs/PLAN_V020.md §4, V9): sale al arrancar si el shell ha visto
// una, con *Instalar y reiniciar* y *Ahora no* (que la deja para luego hasta la siguiente). Con
// las notas del Release (las `notes` del `latest.json`, PLAN_EXCEL §3.6), *Novedades* las abre.
import { useEffect, useState } from "react";
import { t } from "./i18n";
import { Markdown } from "./ChatMarkdown";
import { canInstall, dismissUpdate, installUpdate, notesOf, refreshUpdate, showBanner, useUpdate } from "./update";

export function UpdateBanner() {
  const { state, dismissed } = useUpdate();
  const [open, setOpen] = useState(false);
  useEffect(() => { void refreshUpdate(); }, []);
  if (!showBanner(state, dismissed) && state.estado !== "instalando") return null;
  const notes = notesOf(state);
  return (
    <div className="update-banner" role="status">
      {state.estado === "instalando"
        ? <span>{t("actualizar.instalando", { version: state.version ?? "?" })}</span>
        : <>
            <span>{t("actualizar.aviso", { version: state.version ?? "?" })}</span>
            {notes && (
              <button className="pull-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
                {t("actualizar.novedades")}
              </button>
            )}
            <button className="pull-btn pull-apply" disabled={!canInstall(state)} onClick={() => void installUpdate()}>
              {t("actualizar.instalar")}
            </button>
            <button className="pull-btn" onClick={() => dismissUpdate(state.version ?? "")}>
              {t("actualizar.ahora_no")}
            </button>
          </>}
      {open && notes && state.estado !== "instalando" && (
        <div className="update-notes"><Markdown text={notes} /></div>
      )}
    </div>
  );
}
