// La animación interactiva de un post-it (plan §3, D143, D175), encima de su texto como una
// imagen (D140). Lo puro y el porqué del aislamiento están en animation.ts.
//
// El ratón: con el post-it seleccionado, el marco lo recibe (deslizadores, botones, arrastrar);
// sin seleccionar, `pointer-events: none` (styles.css) y un clic encima selecciona y mueve el
// post-it como siempre. Lo mismo la rueda: sin seleccionar llega al lienzo. Con el post-it
// seleccionado, la rueda encima del marco se la queda el marco: el puente de la rueda de las
// interfaces de paquete (PLAN_PAQUETES P54) es un script que el núcleo mete en cada página que
// sirve, y aquí la página es el HTML del agente tal cual; desde fuera, un marco de origen opaco
// no deja escuchar su rueda. Basta con quitar la selección con un clic fuera (Esc no llega
// después de tocar la animación: el teclado lo tiene el marco).
//
// Fuera de la vista (`inView`, con margen) no hay marco: un hueco del mismo tamaño con un
// rótulo. Al volver a entrar se monta otra vez y la animación empieza de nuevo.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { animationUrl, FRAME_ATTRS, skinMessage, type AnimationRef } from "./animation";
import { t } from "./i18n";
import { readSkin, subscribeSkin } from "./skinWatch";
import { useStore } from "./store";

type Props = { anim: AnimationRef; kind: string; visible: boolean };

export function PostitAnimation({ anim, kind, visible }: Props) {
  const projectId = useStore().project?.id ?? "";
  const skin = useSyncExternalStore(subscribeSkin, readSkin);
  const frame = useRef<HTMLIFrameElement>(null);
  const loaded = useRef(false);
  const src = animationUrl(projectId, anim.file);

  // Los colores se leen del post-it ya pintado (su tipo y el skin): `--pi` es el papel de su tipo.
  const sendSkin = () => {
    const f = frame.current;
    const postit = f?.closest<HTMLElement>(".postit");
    if (!f?.contentWindow || !postit) return;
    const cs = getComputedStyle(postit);
    f.contentWindow.postMessage(skinMessage((n) => cs.getPropertyValue(n)), "*");   // origen opaco
  };
  useEffect(() => { if (loaded.current) sendSkin(); }, [skin, kind]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!visible) loaded.current = false; }, [visible]);

  if (!src) return null;
  const ratio = `${anim.width || 240} / ${anim.height || 180}`;
  return (
    <div className="postit-anim" style={{ aspectRatio: ratio }}>
      {visible ? (
        <iframe ref={frame} key={src} src={src} title={t("lienzo.animacion.titulo")} {...FRAME_ATTRS}
                onLoad={() => { loaded.current = true; sendSkin(); }} />
      ) : (
        <span className="postit-anim-off">{t("lienzo.animacion.fuera")}</span>

      )}
    </div>
  );
}
