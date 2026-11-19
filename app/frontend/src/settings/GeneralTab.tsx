// *Ajustes → General* (plan D179): idioma (D180), unidades en pantalla (D182, del workspace),
// modo de ventana y escala (D183, los aplica el shell), dónde se guarda el workspace (D186,
// solo lectura aquí: se cambia en la bienvenida) y volver a ver la bienvenida.
import type { AppSettings } from "../appSettings";
import { desktop } from "../packsApi";
import { LANGUAGE_NAMES, t } from "../i18n";
import { IMPERIAL, SI, UNIT_CHOICES, type Magnitude, type UnitPrefs } from "../units";
import { openWelcome } from "../welcome";
import { Row, rowLabel, TabHead, useSaver } from "./common";

const MAGNITUDES = Object.keys(SI) as Magnitude[];

export function GeneralTab({ app }: { app: AppSettings }) {
  const { save, errors, busy } = useSaver();
  const units = app.unidades;
  const same = (p: UnitPrefs) => MAGNITUDES.every((m) => units[m] === p[m]);
  const { min, max, paso } = app.opciones.escala;
  const scales: number[] = [];
  for (let s = min; s <= max; s += paso) scales.push(s);
  const magName: Record<Magnitude, string> = {
    longitud: t("unidades.longitud"), masa: t("unidades.masa"), fuerza: t("unidades.fuerza"),
    par: t("unidades.par"), angulo: t("unidades.angulo"),
  };
  const modeName: Record<string, string> = {
    maximizada: t("ajustes.ventana.maximizada"), pantalla_completa: t("ajustes.ventana.pantalla_completa"),
    sin_bordes: t("ajustes.ventana.sin_bordes"), ventana: t("ajustes.ventana.ventana"),
  };
  // La ventana y la escala las aplica la app de escritorio (main.rs); el navegador no.
  const shellNote = desktop ? undefined : t("ajustes.ventana.nota_navegador");
  const ws = app.workspace;

  return (
    <>
      <TabHead id="st-general" title={t("ajustes.pestana.general")} />
      <Row id="idioma" title={t("ajustes.idioma")} hint={t("ajustes.idioma.nota")} error={errors.idioma}>
        <select aria-labelledby={rowLabel("idioma")} value={app.idioma} disabled={busy === "idioma"}
                onChange={(e) => save("idioma", { idioma: e.target.value })}>
          {app.opciones.idiomas.map((l) => <option key={l} value={l}>{LANGUAGE_NAMES[l] ?? l}</option>)}
        </select>
      </Row>
      <Row id="unidades" title={t("ajustes.unidades")} hint={t("ajustes.unidades.nota")} error={errors.unidades}>
        <div className="st-units">
          {MAGNITUDES.map((m) => (
            <label key={m} className="st-unit">
              <span>{magName[m]}</span>
              <select value={units[m]} disabled={busy === "unidades"}
                      onChange={(e) => save("unidades", { unidades: { [m]: e.target.value } })}>
                {UNIT_CHOICES[m].map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </label>
          ))}
        </div>
        <div className="st-presets">
          <button className="pull-btn" aria-pressed={same(SI)} disabled={busy === "unidades"}
                  onClick={() => save("unidades", { unidades: SI })}>{t("unidades.si")}</button>
          <button className="pull-btn" aria-pressed={same(IMPERIAL)} disabled={busy === "unidades"}
                  onClick={() => save("unidades", { unidades: IMPERIAL })}>{t("unidades.imperial")}</button>
        </div>
      </Row>
      <Row id="ventana.modo" title={t("ajustes.ventana.modo")} hint={shellNote} error={errors["ventana.modo"]}>
        <select aria-labelledby={rowLabel("ventana.modo")} value={app.ventana.modo}
                disabled={busy === "ventana.modo"}
                onChange={(e) => save("ventana.modo", { ventana: { modo: e.target.value } })}>
          {app.opciones.modos_ventana.map((m) => <option key={m} value={m}>{modeName[m] ?? m}</option>)}
        </select>
      </Row>
      <Row id="ventana.escala" title={t("ajustes.ventana.escala")} hint={shellNote ?? t("ajustes.ventana.escala_nota")}
           error={errors["ventana.escala"]}>
        <select aria-labelledby={rowLabel("ventana.escala")} value={app.ventana.escala}
                disabled={busy === "ventana.escala"}
                onChange={(e) => save("ventana.escala", { ventana: { escala: Number(e.target.value) } })}>
          {scales.map((s) => <option key={s} value={s}>{s} %</option>)}
        </select>
      </Row>
      <Row id="workspace" title={t("ajustes.workspace")} hint={t("ajustes.workspace.nota")}>
        {ws?.ruta
          ? <code className="st-path">{ws.ruta}</code>
          : <span className="st-muted">{t("ajustes.workspace.sin_ruta")}</span>}
        {ws?.nube && <p className="st-warn st-cloud" role="note">{t("ajustes.workspace.nube", { servicio: ws.nube })}</p>}
      </Row>
      <Row id="bienvenida" title={t("ajustes.bienvenida")} hint={t("ajustes.bienvenida.nota")} error={errors.bienvenida}>
        <button className="pull-btn" disabled={busy === "bienvenida"}
                onClick={async () => { if (await save("bienvenida", { bienvenida_vista: false })) openWelcome(); }}>
          {t("ajustes.bienvenida.boton")}
        </button>
      </Row>
    </>
  );
}
