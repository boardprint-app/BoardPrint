// El perfil de fabricación del workspace en *Ajustes → General* (PLAN_V020 V8; el plan dice
// *Ajustes → Workspace*, pero no hay esa pestaña y General ya tiene la fila del workspace): un
// Markdown (máquinas, materiales, tolerancias, qué se externaliza y a quién) que leen los dos
// agentes. Se escribe en un cuadro, se guarda con su botón y dice si está guardado, sin
// guardar o si aún es la plantilla. Con cambios sin guardar, Escape no cierra los ajustes.
import { useEffect, useState } from "react";
import { t } from "../i18n";
import { apiFetch } from "../auth";
import { detail, profileStatus, statusText, type Profile } from "../profile";
import { rowLabel, useEscapeGuard } from "./common";

/** El perfil, o el motivo por el que no se pudo leer. */
async function loadProfile(): Promise<Profile | string> {
  try {
    const r = await apiFetch("/api/workspace/fabricacion");
    const body = await r.json().catch(() => null);
    if (!r.ok || !body) return detail(body, r.status);
    return body as Profile;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

/** Guarda el perfil: lo guardado, o el motivo del rechazo (el del 422, tal cual). */
async function saveProfile(texto: string): Promise<Profile | string> {
  try {
    const r = await apiFetch("/api/workspace/fabricacion", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto }),
    });
    const body = await r.json().catch(() => null);
    if (!r.ok || !body) return detail(body, r.status);
    return body as Profile;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}

export function ProfileRow() {
  const [saved, setSaved] = useState<Profile | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    void loadProfile().then((p) => {
      if (!live) return;
      if (typeof p === "string") setError(p);
      else { setSaved(p); setText(p.texto); }
    });
    return () => { live = false; };
  }, []);

  const status = profileStatus(text, saved);
  useEscapeGuard(() => saved !== null && status === "dirty");

  const save = async () => {
    setBusy(true);
    const got = await saveProfile(text);
    setBusy(false);
    if (typeof got === "string") return setError(got);
    setError(null);
    setSaved(got);
    setText(got.texto);
  };

  return (
    <div className="st-row st-wide" data-row="perfil_fabricacion">
      <div className="st-row-text">
        <span className="st-row-title" id={rowLabel("perfil_fabricacion")}>{t("ajustes.perfil")}</span>
        <small className="st-row-hint">{t("ajustes.perfil.nota")}</small>
      </div>
      <div className="st-profile">
        {saved === null && !error
          ? <span className="st-muted" role="status">{t("ajustes.cargando")}</span>
          : saved !== null && (
            <>
              <textarea aria-labelledby={rowLabel("perfil_fabricacion")} value={text} spellCheck={false}
                        disabled={busy} onChange={(e) => setText(e.target.value)} />
              <div className="st-profile-bar">
                <span className={`st-profile-state ${status === "dirty" ? "dirty" : status === "saved" ? "ok" : ""}`}
                      role="status">{statusText(status)}</span>
                {text !== saved.plantilla && (
                  <button type="button" className="pull-btn" disabled={busy} onClick={() => setText(saved.plantilla)}>
                    {t("ajustes.perfil.plantilla_boton")}
                  </button>
                )}
                <button type="button" className="pull-btn pull-apply" disabled={busy || (status !== "dirty" && saved.guardado)}
                        onClick={save}>{t("ajustes.perfil.guardar")}</button>
              </div>
            </>
          )}
      </div>
      {error && <p className="pull-error st-row-error" role="alert">{error}</p>}
    </div>
  );
}
