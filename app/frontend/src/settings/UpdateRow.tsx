// *Ajustes → General → Actualizaciones* (docs/PLAN_V020.md §4): lo que sabe el shell, *Buscar
// actualizaciones* y, si hay una, *Instalar y reiniciar*.
import { useEffect, useState } from "react";
import { t } from "../i18n";
import { desktop } from "../packsApi";
import { canInstall, checkNow, installUpdate, refreshUpdate, statusText, useUpdate } from "../update";
import { Row } from "./common";

export function UpdateRow() {
  const { state } = useUpdate();
  const [checking, setChecking] = useState(false);
  useEffect(() => { void refreshUpdate(); }, []);
  return (
    <Row id="actualizar" title={t("actualizar.titulo")} hint={t("actualizar.nota")}>
      <p className="st-muted" role="status">{statusText(state, desktop)}</p>
      {desktop && (
        <div className="st-row-btns">
          <button className="pull-btn" disabled={checking || state.estado === "instalando"}
                  onClick={async () => { setChecking(true); try { await checkNow(); } finally { setChecking(false); } }}>
            {checking ? t("actualizar.buscando") : t("actualizar.buscar")}
          </button>
          {canInstall(state) && (
            <button className="pull-btn pull-apply" onClick={() => void installUpdate()}>
              {t("actualizar.instalar")}
            </button>
          )}
        </div>
      )}
    </Row>
  );
}
