// *Ajustes → Agentes* (plan D144, D168, D179): «Animaciones automáticas» (la fila
// `animaciones_automaticas`, la que marca el aviso de la primera animación) y el tope por
// proyecto por defecto, en dólares equivalentes (cada proyecto lo cambia en su panel). Y cómo
// entra el agente (PLAN_PUBLICACION O9): la sesión de Claude Code o una API key de Anthropic,
// que se guarda en el almacén del sistema y nunca vuelve a la interfaz.
import { useEffect, useState } from "react";
import { saveApiKey, type AppSettings } from "../appSettings";
import { t } from "../i18n";
import { Row, rowLabel, TabHead, useSaver } from "./common";

export function AgentsTab({ app }: { app: AppSettings }) {
  const { save, errors, busy } = useSaver();
  const saved = app.agentes.tope_proyecto_usd;
  const [limit, setLimit] = useState(String(saved));
  useEffect(() => setLimit(String(saved)), [saved]);
  const commitLimit = () => {
    const n = Number(limit.replace(",", "."));
    // Sin cambios no se guarda, salvo para quitar el error de un intento anterior.
    if (limit.trim() === String(saved) && !errors.tope_proyecto_usd) return;
    // Un número que no vale lo rechaza el backend con su motivo, junto a la fila.
    void save("tope_proyecto_usd", { agentes: { tope_proyecto_usd: Number.isFinite(n) && limit.trim() ? n : limit } });
  };

  return (
    <>
      <TabHead id="st-agentes" title={t("ajustes.pestana.agentes")} />
      <AccessRow app={app} />
      <Row id="animaciones_automaticas" title={t("ajustes.agentes.animaciones")}
           hint={t("ajustes.agentes.animaciones_nota")} error={errors.animaciones_automaticas}>
        <label className="st-switch">
          <input type="checkbox" aria-labelledby={rowLabel("animaciones_automaticas")}
                 checked={app.agentes.animaciones_automaticas} disabled={busy === "animaciones_automaticas"}
                 onChange={(e) => save("animaciones_automaticas",
                                       { agentes: { animaciones_automaticas: e.target.checked } })} />
          <span>{app.agentes.animaciones_automaticas ? t("ajustes.activadas") : t("ajustes.desactivadas")}</span>
        </label>
      </Row>
      <Row id="tope_proyecto_usd" title={t("ajustes.agentes.tope")} hint={t("ajustes.agentes.tope_nota")}
           error={errors.tope_proyecto_usd}>
        <label className="st-money">
          <input type="number" min="0" step="0.5" inputMode="decimal" value={limit}
                 aria-labelledby={rowLabel("tope_proyecto_usd")} disabled={busy === "tope_proyecto_usd"}
                 onChange={(e) => setLimit(e.target.value)} onBlur={commitLimit}
                 onKeyDown={(e) => { if (e.key === "Enter") commitLimit(); }} />
          <span>{t("ajustes.agentes.usd")}</span>
        </label>
      </Row>
    </>
  );
}

/** El acceso del agente: la sesión o la API key, con el campo de la clave cuando toca. */
function AccessRow({ app }: { app: AppSettings }) {
  const { save, errors, busy } = useSaver();
  const [key, setKey] = useState("");
  const [keyError, setKeyError] = useState<string | null>(null);
  const [keyBusy, setKeyBusy] = useState(false);
  const access = app.agentes.acceso;
  const storeKey = async (value: string | null) => {
    setKeyBusy(true);
    const why = await saveApiKey(value);
    setKeyBusy(false);
    setKeyError(why);
    if (!why) setKey("");
  };
  return (
    <Row id="acceso" title={t("ajustes.agentes.acceso")} hint={t("ajustes.agentes.acceso_nota")}
         error={errors.acceso ?? keyError ?? undefined}>
      <div className="st-access">
        <select aria-labelledby={rowLabel("acceso")} value={access} disabled={busy === "acceso"}
                onChange={(e) => save("acceso", { agentes: { acceso: e.target.value } })}>
          <option value="sesion">{t("ajustes.agentes.acceso.sesion")}</option>
          <option value="api_key">{t("ajustes.agentes.acceso.api_key")}</option>
        </select>
        {access === "api_key" && (
          app.agentes.api_key_guardada ? (
            <span className="st-key">
              <span>{t("ajustes.agentes.clave_guardada")}</span>
              <button type="button" className="pull-btn" disabled={keyBusy} onClick={() => storeKey(null)}>
                {t("ajustes.agentes.clave_borrar")}
              </button>
            </span>
          ) : (
            <form className="st-key" onSubmit={(e) => { e.preventDefault(); if (key.trim()) void storeKey(key.trim()); }}>
              <input type="password" autoComplete="off" spellCheck={false} value={key}
                     placeholder="sk-ant-…" aria-label={t("ajustes.agentes.clave")}
                     onChange={(e) => setKey(e.target.value)} disabled={keyBusy} />
              <button type="submit" className="pull-btn" disabled={keyBusy || !key.trim()}>{t("ajustes.agentes.clave_guardar")}</button>
            </form>
          )
        )}
      </div>
    </Row>
  );
}
