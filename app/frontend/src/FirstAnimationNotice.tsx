// El aviso de la primera animación (plan D187; el estado en animationNotice.ts): abajo, en el
// centro del lienzo, como el aviso de los paquetes, sin tapar la barra de herramientas de
// Excalidraw (arriba) ni el panel del agente (a la derecha). Se quita al salir de la pizarra.
import { useEffect } from "react";
import { goToAnimationSettings, hideAnimationNotice, useAnimationNotice } from "./animationNotice";
import { t } from "./i18n";

export function FirstAnimationNotice() {
  const shown = useAnimationNotice();
  useEffect(() => hideAnimationNotice, []);       // otro proyecto no hereda el aviso
  if (!shown) return null;
  return (
    <div className="anim-notice" role="status">
      <span>{t("aviso_animacion.texto")}</span>
      <span className="anim-notice-btns">
        <button className="pull-btn pull-apply" onClick={goToAnimationSettings}>{t("aviso_animacion.ir")}</button>
        <button className="pull-btn" onClick={hideAnimationNotice}>{t("aviso_animacion.entendido")}</button>
      </span>
    </div>
  );
}
