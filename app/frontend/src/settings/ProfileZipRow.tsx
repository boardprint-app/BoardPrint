// Exportar e importar el perfil del workspace en un .zip (PLAN_LIBRERIA §5, L8-L10), bajo el
// perfil de fabricación en *Ajustes → General*. Exportar pide una carpeta (el diálogo lo abre
// el backend) y lleva el stock solo con la casilla, desmarcada al abrir. Importar pide el
// archivo, enseña el resumen (qué trae, qué sustituye, qué no vale y dónde queda la copia) y
// solo escribe con *Importar*; un 409 (el zip o el perfil cambiaron) se enseña tal cual.
import { useState } from "react";
import { t } from "../i18n";
import { apiFetch } from "../auth";
import { detail, importOrigin, importRows, type ProfileExport, type ProfileImportDone,
         type ProfileImportPlan } from "../profile";
import { rowLabel, useEscapeGuard } from "./common";

/** POST con JSON: lo que responde, o el motivo del rechazo. */
async function post<T>(url: string, body: unknown): Promise<T | string> {
  try {
    const r = await apiFetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const got = await r.json().catch(() => null);
    if (!r.ok || !got) return detail(got, r.status);
    return got as T;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

export function ProfileZipRow({ onImported }: { onImported: () => void }) {
  const [withStock, setWithStock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [plan, setPlan] = useState<ProfileImportPlan | null>(null);
  // con el resumen abierto, Escape lo cierra a él y no los ajustes
  useEscapeGuard(() => {
    if (!plan) return false;
    setPlan(null);
    return true;
  });

  const run = async <T,>(fn: () => Promise<T | string>, then: (got: T) => void) => {
    setBusy(true);
    setError(null);
    setNote(null);
    const got = await fn();
    setBusy(false);
    if (typeof got === "string") setError(got);
    else then(got);
  };

  const exportProfile = () => run<ProfileExport>(
    () => post("/api/profile/export", { con_stock: withStock }),
    (got) => {
      if (!got.file) return;
      const left = got.omitidas?.length ? ` ${t("ajustes.perfil_zip.omitidas", { claves: got.omitidas.join(", ") })}` : "";
      setNote(t("ajustes.perfil_zip.exportado", { ruta: got.file }) + left);
    });

  const inspect = () => run<ProfileImportPlan>(
    () => post("/api/profile/import/inspect", {}),
    (got) => { if (got.file) setPlan(got); });

  const apply = (p: ProfileImportPlan) => run<ProfileImportDone>(
    () => post("/api/profile/import/apply", { token: p.token }),
    (got) => {
      setPlan(null);
      setNote(t("ajustes.perfil_zip.importado", { ruta: got.copia }));
      onImported();
    });

  const origin = plan ? importOrigin(plan) : "";
  return (
    <div className="st-row" data-row="perfil_zip">
      <div className="st-row-text">
        <span className="st-row-title" id={rowLabel("perfil_zip")}>{t("ajustes.perfil_zip")}</span>
        <small className="st-row-hint">{t("ajustes.perfil_zip.nota")}</small>
      </div>
      <div className="st-row-ctl st-pz-ctl">
        <label className="st-switch">
          <input type="checkbox" checked={withStock} disabled={busy}
                 onChange={(e) => setWithStock(e.target.checked)} />
          <span>{t("ajustes.perfil_zip.con_stock")}</span>
        </label>
        <button type="button" className="pull-btn" disabled={busy} onClick={exportProfile}>
          {t("ajustes.perfil_zip.exportar")}
        </button>
        <button type="button" className="pull-btn" disabled={busy || plan !== null} onClick={inspect}>
          {t("ajustes.perfil_zip.importar")}
        </button>
      </div>
      {note && <p className="st-info st-pz-wide" role="status">{note}</p>}
      {plan && (
        <section className="st-confirm st-pz-wide st-pz-summary" aria-labelledby="st-pz-title">
          <h4 id="st-pz-title">{t("ajustes.perfil_zip.titulo", { nombre: plan.nombre })}</h4>
          {origin && <p className="st-muted">{origin}</p>}
          <p className="st-warn">{t("ajustes.perfil_zip.aviso")}</p>
          <dl className="st-pz-rows">
            {importRows(plan).map((r) => (
              <div key={r.label}><dt>{r.label}</dt><dd>{r.value}</dd></div>
            ))}
          </dl>
          {plan.invalid.length > 0 && (
            <div className="st-breaks">
              <b>{t("ajustes.perfil_zip.no_valen")}</b>
              <ul>
                {plan.invalid.map((i) => <li key={i.ruta + (i.clave ?? "")}><code>{i.ruta}</code>: {i.motivo}</li>)}
              </ul>
            </div>
          )}
          <div className="st-row-btns">
            <button type="button" className="pull-btn" disabled={busy} onClick={() => setPlan(null)}>
              {t("ajustes.perfil_zip.cancelar")}
            </button>
            <button type="button" className="pull-btn pull-apply" disabled={busy} onClick={() => apply(plan)}>
              {t("ajustes.perfil_zip.aceptar")}
            </button>
          </div>
        </section>
      )}
      {error && <p className="pull-error st-row-error" role="alert">{error}</p>}
    </div>
  );
}
