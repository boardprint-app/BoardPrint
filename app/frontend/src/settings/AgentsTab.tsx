// *Ajustes → Agentes* (plan D144, D168, D179): «Animaciones automáticas» (la fila
// `animaciones_automaticas`, la que marca el aviso de la primera animación) y el tope por
// proyecto por defecto, en dólares equivalentes (cada proyecto lo cambia en su panel). Y cómo
// entra el agente (PLAN_PUBLICACION O9): la sesión de Claude Code o una API key de Anthropic,
// que se guarda en el almacén del sistema y nunca vuelve a la interfaz. Desde FF 6.1, la
// intrusividad del revisor (PLAN_V020 V5) y el modelo de cada agente (V7). Desde FF 8.1, el
// agente de proveedores: su modelo y el tope de cada búsqueda (PLAN_APROVISIONAMIENTO A5).
import { useEffect, useState } from "react";
import { saveApiKey, type AppSettings } from "../appSettings";
import { t } from "../i18n";
import { INTRUSIVENESS } from "../review";
import { Row, rowLabel, TabHead, useSaver } from "./common";

export function AgentsTab({ app }: { app: AppSettings }) {
  const { save, errors, busy } = useSaver();

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
      <LimitRow id="tope_proyecto_usd" saved={app.agentes.tope_proyecto_usd} step="0.5"
                title={t("ajustes.agentes.tope")} hint={t("ajustes.agentes.tope_nota")} />
      <ReviewerRow app={app} />
      <ModelRow app={app} agent="diseno" title={t("ajustes.agentes.modelo_diseno")} />
      <ModelRow app={app} agent="revisor" title={t("ajustes.agentes.modelo_revisor")} />
      <ModelRow app={app} agent="proveedores" title={t("ajustes.agentes.modelo_proveedores")}
                hint={t("ajustes.agentes.modelo_proveedores_nota")} />
      <LimitRow id="tope_busqueda_usd" saved={app.agentes.tope_busqueda_usd ?? 0.25} step="0.05"
                title={t("ajustes.agentes.tope_busqueda")} hint={t("ajustes.agentes.tope_busqueda_nota")} />
    </>
  );
}

/** Un tope en dólares equivalentes de `agentes` (el del proyecto, D168; el de cada búsqueda en
 *  proveedores, A5): se guarda al salir del campo o con Enter. */
function LimitRow({ id, saved, step, title, hint }: {
  id: "tope_proyecto_usd" | "tope_busqueda_usd"; saved: number; step: string; title: string; hint: string;
}) {
  const { save, errors, busy } = useSaver();
  const [limit, setLimit] = useState(String(saved));
  useEffect(() => setLimit(String(saved)), [saved]);
  const commitLimit = () => {
    const n = Number(limit.replace(",", "."));
    // Sin cambios no se guarda, salvo para quitar el error de un intento anterior.
    if (limit.trim() === String(saved) && !errors[id]) return;
    // Un número que no vale lo rechaza el backend con su motivo, junto a la fila.
    void save(id, { agentes: { [id]: Number.isFinite(n) && limit.trim() ? n : limit } });
  };
  return (
    <Row id={id} title={title} hint={hint} error={errors[id]}>
      <label className="st-money">
        <input type="number" min="0" step={step} inputMode="decimal" value={limit}
               aria-labelledby={rowLabel(id)} disabled={busy === id}
               onChange={(e) => setLimit(e.target.value)} onBlur={commitLimit}
               onKeyDown={(e) => { if (e.key === "Enter") commitLimit(); }} />
        <span>{t("ajustes.agentes.usd")}</span>
      </label>
    </Row>
  );
}

/** Cuándo revisa el revisor (V5): cada opción con su frase. */
function ReviewerRow({ app }: { app: AppSettings }) {
  const { save, errors, busy } = useSaver();
  const value = app.agentes.intrusividad_revisor ?? "a_demanda";
  const options = app.opciones.intrusividades_revisor ?? INTRUSIVENESS;
  const label: Record<string, string> = {
    apagado: t("ajustes.agentes.intrusividad.apagado"), a_demanda: t("ajustes.agentes.intrusividad.a_demanda"),
    hitos: t("ajustes.agentes.intrusividad.hitos"),
  };
  const note: Record<string, string> = {
    apagado: t("ajustes.agentes.intrusividad.apagado_nota"), a_demanda: t("ajustes.agentes.intrusividad.a_demanda_nota"),
    hitos: t("ajustes.agentes.intrusividad.hitos_nota"),
  };
  return (
    <Row id="intrusividad_revisor" title={t("ajustes.agentes.intrusividad")} hint={t("ajustes.agentes.intrusividad_nota")}
         error={errors.intrusividad_revisor}>
      <div className="st-choices" role="radiogroup" aria-labelledby={rowLabel("intrusividad_revisor")}>
        {options.map((o) => (
          <label key={o} className="st-choice">
            <input type="radio" name="intrusividad_revisor" value={o} checked={value === o}
                   disabled={busy === "intrusividad_revisor"}
                   onChange={() => save("intrusividad_revisor", { agentes: { intrusividad_revisor: o } })} />
            <span><b>{label[o] ?? o}</b><small>{note[o] ?? ""}</small></span>
          </label>
        ))}
      </div>
    </Row>
  );
}

/** El modelo de un agente (V7): Opus, Sonnet, más barato, o Haiku, el que menos (el de
 *  proveedores, Haiku por defecto, A5). */
function ModelRow({ app, agent, title, hint }: {
  app: AppSettings; agent: "diseno" | "revisor" | "proveedores"; title: string; hint?: string;
}) {
  const { save, errors, busy } = useSaver();
  const id = `modelo_${agent}` as const;
  const value = app.agentes[id] ?? (agent === "proveedores" ? "haiku" : "opus");
  const label: Record<string, string> = {
    opus: t("ajustes.agentes.modelo.opus"), sonnet: t("ajustes.agentes.modelo.sonnet"),
    haiku: t("ajustes.agentes.modelo.haiku"),
  };
  return (
    <Row id={id} title={title} hint={hint ?? t("ajustes.agentes.modelo_nota")} error={errors[id]}>
      <select aria-labelledby={rowLabel(id)} value={value} disabled={busy === id}
              onChange={(e) => save(id, { agentes: { [id]: e.target.value } })}>
        {(app.opciones.modelos ?? ["opus", "sonnet"]).map((m) => <option key={m} value={m}>{label[m] ?? m}</option>)}
      </select>
    </Row>
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
