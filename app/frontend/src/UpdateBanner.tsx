// El aviso de versión nueva (docs/PLAN_V020.md §4, V9): sale al arrancar si el shell ha visto
// una, con *Instalar y reiniciar* y *Ahora no* (que la deja para luego hasta la siguiente).
import { useEffect } from "react";
import { t } from "./i18n";
import { canInstall, dismissUpdate, installUpdate, refreshUpdate, showBanner, useUpdate } from "./update";

export function UpdateBanner() {
  const { state, dismissed } = useUpdate();
  useEffect(() => { void refreshUpdate(); }, []);
  if (!showBanner(state, dismissed) && state.estado !== "instalando") return null;
  return (
    <div className="update-banner" role="status">
      {state.estado === "instalando"
        ? <span>{t("actualizar.instalando", { version: state.version ?? "?" })}</span>
        : <>
            <span>{t("actualizar.aviso", { version: state.version ?? "?" })}</span>
            <button className="pull-btn pull-apply" disabled={!canInstall(state)} onClick={() => void installUpdate()}>
              {t("actualizar.instalar")}
            </button>
            <button className="pull-btn" onClick={() => dismissUpdate(state.version ?? "")}>
              {t("actualizar.ahora_no")}
            </button>
          </>}
    </div>
  );
}
