// Las tarjetas de la nube en la pizarra (docs/PLAN_M365.md §3, M6-M9): una tarjeta de archivo
// normal (FileCard.tsx) con `customData.m365`, más
// - la marca del servicio junto al nombre y, sin conexión, un «sin conexión» discreto, nunca un
//   error (M7);
// - con la local y la de la nube cambiadas, el aviso *Cambiada aquí y en la nube* con *Traer la
//   de la nube* (la local va a la papelera, tras confirmarlo) y *Guardar la mía en la nube* (M8);
// - en el menú de la tarjeta (CardMenu.tsx): *Abrir en la web* (un correo, *Abrir en Outlook*),
//   *Actualizar desde la nube* (no en un correo: no se sondea) y, en toda tarjeta de archivo,
//   *Guardar en OneDrive…* (M9, el selector de M365Panel.tsx).
import { useState, type ReactNode } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { t } from "./i18n";
import { setStore } from "./store";
import { cloudActions, cloudOf, conflictTarget, openSaveToCloud, stateMark, useM365View, type M365CardState,
         type M365Ref } from "./m365";
import { m365OpenWeb, m365Refresh, m365Upload } from "./m365Api";

const say = (text: string, kind: "info" | "error" = "info") => setStore({ notice: { text, kind, at: Date.now() } });
const fail = (error: string) => setStore({ lastError: error });

/** Lo que dice *Actualizar desde la nube* según cómo queda la tarjeta. */
function refreshed(state: M365CardState) {
  if (state === "al_dia") say(t("m365.tarjeta.al_dia"));
  else if (state === "descargada") say(t("m365.tarjeta.descargada"));
  else if (state === "conflicto") say(t("m365.tarjeta.conflicto_aviso"));
  else say(t("m365.tarjeta.sin_conexion_titulo"));
}

export const openCloud = async (ref: M365Ref) => {
  const r = await m365OpenWeb({ service: ref.service, drive_id: ref.drive_id, item_id: ref.item_id });
  if (!r.ok) fail(r.error);
};

const CLOUD = <path d="M7 18h10a4 4 0 00.6-7.96A6 6 0 006.1 9.2 4.5 4.5 0 007 18z" />;
const MAIL = <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></>;
const Glyph = ({ d, size = 14 }: { d: ReactNode; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

/** La marca de la nube en la fila de la tarjeta (y «sin conexión» si toca). */
export function CloudMark({ id, data }: { id: string; data: unknown }) {
  const { states } = useM365View();
  const ref = cloudOf(data);
  if (!ref) return null;
  const where = ref.service === "correo" ? t("m365.tarjeta.en_correo")
    : ref.service === "sharepoint" ? t("m365.tarjeta.en_sharepoint") : t("m365.tarjeta.en_onedrive");
  const offline = stateMark(states[id]) === "sin_conexion";
  return (
    <>
      {offline && <span className="fc-ext m365-offline" title={t("m365.tarjeta.sin_conexion_titulo")}>{t("m365.tarjeta.sin_conexion")}</span>}
      <span className={`m365-mark m365-${ref.service}`} title={where} aria-label={where} role="img">
        <Glyph d={ref.service === "correo" ? MAIL : CLOUD} />
      </span>
    </>
  );
}

/** *Cambiada aquí y en la nube* (M8): traer la de la nube (tras confirmarlo) o subir la mía. */
export function CloudConflict({ id, data }: { id: string; data: unknown }) {
  const { states } = useM365View();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = cloudOf(data);
  if (!ref || stateMark(states[id]) !== "conflicto") return null;
  const run = async (fn: () => Promise<void>) => { setBusy(true); await fn(); setBusy(false); setAsking(false); };
  const takeCloud = () => run(async () => {
    const r = await m365Refresh(id, true);
    if (r.ok) refreshed(r.value.state); else fail(r.error);
  });
  const saveMine = () => run(async () => {
    const r = await m365Upload(id, conflictTarget(ref));
    if (r.ok) say(t("m365.tarjeta.guardada", { name: r.value.name })); else fail(r.error);
  });
  return (
    <div className="m365-conflict" role="alert">
      <div className="m365-conflict-msg">⚠ {asking ? t("m365.tarjeta.confirmar_traer") : t("m365.tarjeta.conflicto")}</div>
      <div className="fc-btns">
        {asking ? (
          <>
            <button type="button" className="fbtn main" disabled={busy} onClick={() => void takeCloud()}>{t("m365.tarjeta.si_traer")}</button>
            <button type="button" className="fbtn" disabled={busy} onClick={() => setAsking(false)}>{t("m365.tarjeta.cancelar")}</button>
          </>
        ) : (
          <>
            <button type="button" className="fbtn main" disabled={busy} onClick={() => setAsking(true)}>{t("m365.tarjeta.traer_nube")}</button>
            <button type="button" className="fbtn" disabled={busy} onClick={() => void saveMine()}>{t("m365.tarjeta.guardar_mia")}</button>
          </>
        )}
      </div>
    </div>
  );
}

const Ico = ({ d }: { d: ReactNode }) => <Glyph d={d} size={16} />;
const OPEN = <path d="M14 3h7v7M21 3l-9 9M19 14v6H4V5h6" />;
const REFRESH = <><path d="M20 11a8 8 0 00-14.7-4.3L4 8" /><path d="M4 3v5h5" /><path d="M4 13a8 8 0 0014.7 4.3L20 16" /><path d="M20 21v-5h-5" /></>;

type ItemsProps = { id: string; name: string; api: ExcalidrawImperativeAPI | null; exists: boolean; onClose: () => void };

/** Lo de Microsoft 365 en el menú de una tarjeta de archivo. */
export function M365Items({ id, name, api, exists, onClose }: ItemsProps) {
  const ref = cloudOf(api?.getSceneElements().find((e) => e.id === id)?.customData);
  const act = (fn: () => unknown) => () => { onClose(); void fn(); };
  const can = ref ? cloudActions(ref) : null;
  return (
    <>
      {ref && (
        <button type="button" role="menuitem" className="it" onClick={act(() => openCloud(ref))}>
          <Ico d={OPEN} />{can?.outlook ? t("m365.tarjeta.abrir_outlook") : t("m365.tarjeta.abrir_web")}
        </button>
      )}
      {ref && can?.refresh && (
        <button type="button" role="menuitem" className="it" onClick={act(async () => {
          const r = await m365Refresh(id);
          if (r.ok) refreshed(r.value.state); else fail(r.error);
        })}>
          <Ico d={REFRESH} />{t("m365.tarjeta.actualizar")}
        </button>
      )}
      <button type="button" role="menuitem" className="it" disabled={!exists} onClick={act(() => openSaveToCloud(id, name))}>
        <Ico d={CLOUD} />{t("m365.guardar.menu")}
      </button>
    </>
  );
}
