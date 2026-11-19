// *Ajustes → Avanzados* (plan D54, D184): la fuente de cada tipo de texto, de una lista fija
// (el navegador no deja listar las instaladas). En la pizarra, solo las que Excalidraw sabe
// medir; cambian los post-its y los textos nuevos de Excalidraw, no los ya dibujados.
import type { CSSProperties } from "react";
import type { AppSettings } from "../appSettings";
import { FONT_VARS, fontVars, type FontKind } from "../fonts";
import { t } from "../i18n";
import { Row, rowLabel, TabHead, useSaver } from "./common";

export function AdvancedTab({ app }: { app: AppSettings }) {
  const { save, errors, busy } = useSaver();
  const kindName: Record<FontKind, string> = {
    interfaz: t("ajustes.fuentes.interfaz"), pizarra: t("ajustes.fuentes.pizarra"),
    chat: t("ajustes.fuentes.chat"), numeros: t("ajustes.fuentes.numeros"),
  };
  const kindHint: Record<FontKind, string> = {
    interfaz: t("ajustes.fuentes.interfaz_nota"), pizarra: t("ajustes.fuentes.pizarra_nota"),
    chat: t("ajustes.fuentes.chat_nota"), numeros: t("ajustes.fuentes.numeros_nota"),
  };
  // Las que sabe la interfaz, en su orden; una que traiga un backend más nuevo, al final.
  const kinds = [...(Object.keys(FONT_VARS) as FontKind[]).filter((k) => k in app.opciones.fuentes),
                 ...Object.keys(app.opciones.fuentes).filter((k) => !(k in FONT_VARS))] as FontKind[];

  return (
    <>
      <TabHead id="st-avanzados" title={t("ajustes.pestana.avanzados")} />
      <p className="st-intro">{t("ajustes.fuentes.intro")}</p>
      {kinds.map((kind) => {
        const id = `fuentes.${kind}`;
        const value = app.fuentes[kind] ?? "";
        // La muestra con la fuente elegida y su respaldo; «sistema», la de siempre.
        const sample = fontVars({ [kind]: value })[FONT_VARS[kind] ?? ""];
        return (
          <Row key={kind} id={id} title={kindName[kind] ?? kind} hint={kindHint[kind]} error={errors[id]}>
            <select aria-labelledby={rowLabel(id)} value={value} disabled={busy === id}
                    onChange={(e) => save(id, { fuentes: { [kind]: e.target.value } })}>
              {app.opciones.fuentes[kind].map((f) => (
                <option key={f} value={f}>{f === "sistema" ? t("ajustes.fuentes.sistema") : f}</option>
              ))}
            </select>
            <span className="st-font-sample"
                  style={{ fontFamily: sample ?? `var(${FONT_VARS[kind] ?? "--f-ui"})` } as CSSProperties}>
              {t("ajustes.fuentes.muestra")}
            </span>
          </Row>
        );
      })}
    </>
  );
}
