// *Nuevo workspace* (PLAN_WORKSPACES W6): el nombre, la carpeta (por defecto
// `<carpeta_base>/<nombre>`, que se cambia con el diálogo del sistema) y con qué empieza: vacío,
// una plantilla de sector (`GET /api/profile/templates`) o un perfil .zip, con el resumen de lo
// que trae antes de crear (el de *Importar perfil*, hacia un workspace nuevo). *Crear y abrir*
// lo crea, el servidor rearranca con él y la ventana recarga (W3). Lo que rechaza el backend
// sale dentro del diálogo, que se queda abierto para corregir.
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { importOrigin, importRows, type ProfileImportPlan } from "../profile";
import {
  defaultFolder, newWorkspaceRequest, outcomeText, templateContents, type ProfileTemplate, type Start,
} from "../workspaces";
import { chooseFolder, createWorkspace, inspectProfileForNew, listTemplates, settle } from "../workspacesApi";
import { Dialog } from "./Dialogs";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

type Choice = "vacio" | `plantilla:${string}` | "perfil";

export function NewWorkspaceDialog({ base, onClose }: { base: string | null; onClose: () => void }) {
  const [name, setName] = useState("");
  const [folder, setFolder] = useState<string | null>(null);       // la elegida; null: la de por defecto
  const [templates, setTemplates] = useState<ProfileTemplate[] | null>(null);
  const [choice, setChoice] = useState<Choice>("vacio");
  const [plan, setPlan] = useState<ProfileImportPlan | null>(null);
  const [busy, setBusy] = useState<"carpeta" | "perfil" | "crear" | "esperar" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    listTemplates().then(setTemplates).catch((e) => { setTemplates([]); setError(message(e)); });
  }, []);

  const start: Start = choice === "vacio" ? { kind: "vacio" }
    : choice === "perfil" ? { kind: "perfil", token: plan?.token ?? null }
      : { kind: "plantilla", id: choice.slice("plantilla:".length) };
  const req = newWorkspaceRequest(name, folder, base, start);
  const shownFolder = folder ?? defaultFolder(base, name);
  const locked = busy === "crear" || busy === "esperar";
  const close = () => { if (!locked) onClose(); };

  const run = async (what: NonNullable<typeof busy>, fn: () => Promise<void>) => {
    setBusy(what);
    setError(null);
    setInfo(null);
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    }
    setBusy(null);
  };

  const pickFolder = () => run("carpeta", async () => {
    const got = await chooseFolder();
    if (got) setFolder(got);
  });

  const pickProfile = () => run("perfil", async () => {
    const got = await inspectProfileForNew();
    if (got.file) setPlan(got);
  });

  // Mientras crea y espera al servidor rearrancado, el diálogo no se cierra.
  const create = () => req && run("crear", async () => {
    const got = await createWorkspace(req);
    setBusy("esperar");
    const outcome = await settle(got);
    if (outcome === "recargar") return new Promise<void>(() => {});   // la ventana se recarga
    setInfo(outcomeText(outcome, got.workspace.nombre));
  });

  const generic = plan?.manifest.generica === true;
  return (
    <Dialog title={t("workspaces.nuevo.titulo")} onClose={close} className="dialog-wide nw">
      <form onSubmit={(e) => { e.preventDefault(); void create(); }} style={{ display: "contents" }}>
        <label>
          {t("workspaces.nuevo.nombre")}
          <input ref={input} value={name} disabled={locked} onChange={(e) => setName(e.target.value)} />
        </label>

        <div className="nw-field">
          <span className="nw-label">{t("workspaces.nuevo.carpeta")}</span>
          <div className="nw-folder">
            {shownFolder
              ? <code className="nw-path">{shownFolder}</code>
              : <span className="nw-muted">{t(base ? "workspaces.nuevo.carpeta_sin_nombre" : "workspaces.nuevo.carpeta_elige")}</span>}
            <button type="button" className="btn-outline" disabled={busy !== null} onClick={pickFolder}>
              {t("workspaces.nuevo.cambiar_carpeta")}
            </button>
          </div>
          {folder !== null && base && (
            <button type="button" className="nw-link" disabled={busy !== null} onClick={() => setFolder(null)}>
              {t("workspaces.nuevo.carpeta_por_defecto")}
            </button>
          )}
        </div>

        <fieldset className="nw-start" disabled={locked}>
          <legend className="nw-label">{t("workspaces.nuevo.empezar")}</legend>
          <label className="nw-choice">
            <input type="radio" name="nw-start" checked={choice === "vacio"} onChange={() => setChoice("vacio")} />
            <span>
              <b>{t("workspaces.nuevo.vacio")}</b>
              <small>{t("workspaces.nuevo.vacio_nota")}</small>
            </span>
          </label>
          {templates === null && <p className="nw-muted">{t("workspaces.nuevo.cargando_plantillas")}</p>}
          {templates?.map((tp) => (
            <label key={tp.id} className="nw-choice">
              <input type="radio" name="nw-start" checked={choice === `plantilla:${tp.id}`}
                     onChange={() => setChoice(`plantilla:${tp.id}`)} />
              <span>
                <b>
                  {t("workspaces.nuevo.plantilla", { titulo: tp.titulo })}
                  {tp.generica && <em className="nw-badge">{t("workspaces.nuevo.generica")}</em>}
                </b>
                <small>{tp.descripcion}</small>
                <small>{t("workspaces.nuevo.trae", { que: templateContents(tp.lleva) })}</small>
              </span>
            </label>
          ))}
          <label className="nw-choice">
            <input type="radio" name="nw-start" checked={choice === "perfil"} onChange={() => setChoice("perfil")} />
            <span>
              <b>{t("workspaces.nuevo.perfil")}</b>
              <small>{t("workspaces.nuevo.perfil_nota")}</small>
            </span>
          </label>
          {choice === "perfil" && (
            <div className="nw-profile">
              <button type="button" className="btn-outline" disabled={busy !== null} onClick={pickProfile}>
                {t(plan ? "workspaces.nuevo.perfil_otro" : "workspaces.nuevo.perfil_elegir")}
              </button>
              {plan && (
                <section className="nw-summary" aria-labelledby="nw-summary-title">
                  <h3 id="nw-summary-title">{plan.nombre}</h3>
                  {importOrigin(plan) && <p className="nw-muted">{importOrigin(plan)}</p>}
                  {generic && <p className="nw-warn">{t("workspaces.nuevo.perfil_generico")}</p>}
                  <dl className="nw-rows">
                    {importRows(plan).map((r) => (
                      <div key={r.label}><dt>{r.label}</dt><dd>{r.value}</dd></div>
                    ))}
                  </dl>
                  {plan.invalid.length > 0 && (
                    <div className="nw-breaks">
                      <b>{t("ajustes.perfil_zip.no_valen")}</b>
                      <ul>
                        {plan.invalid.map((i) => <li key={i.ruta + (i.clave ?? "")}><code>{i.ruta}</code>: {i.motivo}</li>)}
                      </ul>
                    </div>
                  )}
                </section>
              )}
            </div>
          )}
        </fieldset>

        <p className="nw-muted">{t("workspaces.nuevo.nota")}</p>
        {busy === "crear" && <p role="status">{t("workspaces.nuevo.creando")}</p>}
        {busy === "esperar" && <p role="status">{t("workspaces.esperando")}</p>}
        {info && <p role="status">{info}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="btn-row">
          <button type="button" className="btn-outline" disabled={locked} onClick={onClose}>{t("lienzo.inicio.cancelar")}</button>
          <button type="submit" className="btn-paper" disabled={busy !== null || req === null}>
            {t("workspaces.nuevo.crear")}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
