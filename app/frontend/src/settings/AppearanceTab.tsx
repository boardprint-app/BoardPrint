// *Ajustes → Apariencia* (plan D79, D179): los cinco skins con su muestra. Elegir uno lo cambia
// al momento (Root, `onSkin`), como el menú de la píldora, que sigue ahí de acceso rápido.
import { t } from "../i18n";
import { SKINS, type SkinId } from "../skins";
import { Row, rowLabel, TabHead } from "./common";

export function AppearanceTab({ skin, onSkin }: { skin: SkinId; onSkin: (id: SkinId) => void }) {
  // El nombre de cada skin en el idioma de la app; uno nuevo sin clave, con el de skins.ts.
  const skinName: Record<string, string> = {
    escuela: t("skin.escuela"), corcho: t("skin.corcho"), laboratorio: t("skin.laboratorio"),
    cad: t("skin.cad"), calma: t("skin.calma"),
  };
  return (
    <>
      <TabHead id="st-apariencia" title={t("ajustes.pestana.apariencia")} />
      <Row id="skin" title={t("ajustes.skin")} hint={t("ajustes.skin.nota")}>
        <div className="st-skins" role="radiogroup" aria-labelledby={rowLabel("skin")}>
          {SKINS.map((s) => (
            <button key={s.id} role="radio" aria-checked={s.id === skin}
                    className={s.id === skin ? "st-skin on" : "st-skin"} onClick={() => onSkin(s.id)}>
              <span className={`st-skin-sample skin-swatch swatch-${s.id}`} aria-hidden="true" />
              <span className="st-skin-name">{skinName[s.id] ?? s.name}</span>
              {s.dark && <small>{t("ajustes.skin.oscuro")}</small>}
            </button>
          ))}
        </div>
      </Row>
    </>
  );
}
