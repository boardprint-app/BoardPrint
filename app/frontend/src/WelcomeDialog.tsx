// La ventana de la bienvenida (plan D186; el estado y la lógica en welcome.ts). Modal, encima
// del inicio o de la pizarra (y de Ajustes, si se abre desde allí): cuatro pasos con su
// indicador, *Atrás*/*Siguiente* y *Saltar* en todos; Escape es *Saltar*. Nunca bloquea: sin
// sesión de Claude Code o sin Fusion se sigue igual. Cada paso se monta al entrar en él (la
// sesión se comprueba al llegar; los programas se preguntan solo mientras se ven).
import { useCallback, useEffect, useRef, useState } from "react";
import { saveAppSettings, useAppSettings, type AppSettings } from "./appSettings";
import { apiFetch } from "./auth";
import { LANGUAGE_NAMES, t } from "./i18n";
import { openOnboarding } from "./onboardingChat";
import { IMPERIAL, SI, type UnitPrefs } from "./units";
import {
  connectorList, finishWelcome, goToStep, planLabel, LAST_STEP, nextStep, prevStep, sameFolder, useWelcome,
  waitForRestart, WELCOME_SEEN, WELCOME_STEPS, type ConnectorInfo, type WelcomeStep,
} from "./welcome";
import "./settings.css";
import "./welcome.css";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const CONNECTORS_POLL_MS = 3000;       // cada cuánto se preguntan los programas en su paso

async function post(path: string, body?: unknown) {
  const r = await apiFetch(path, {
    method: "POST",
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : t("ajustes.error_http", { estado: r.status }));
  return data;
}

export function WelcomeDialog() {
  const w = useWelcome();
  if (!w.open) return null;
  return <WelcomeWindow step={w.step} />;
}

function WelcomeWindow({ step }: { step: number }) {
  const app = useAppSettings();
  const box = useRef<HTMLDivElement>(null);
  // Mientras cambia de carpeta y espera al servidor, no se sale ni se cambia de paso.
  const [locked, setLocked] = useState(false);
  const lockedRef = useRef(false);
  lockedRef.current = locked;
  const id: WelcomeStep = WELCOME_STEPS[step];
  const stepName: Record<WelcomeStep, string> = {
    idioma: t("bienvenida.paso.idioma"), sesion: t("bienvenida.paso.sesion"),
    programas: t("bienvenida.paso.programas"), carpeta: t("bienvenida.paso.carpeta"),
  };

  const finish = useCallback(() => {
    if (!lockedRef.current) void finishWelcome(saveAppSettings);
  }, []);

  // El foco dentro: así los atajos de la pizarra no saltan con la ventana abierta (`typing`
  // excluye lo que está dentro de una ventana modal, R49).
  useEffect(() => box.current?.focus(), []);
  useEffect(() => box.current?.focus(), [step]);

  // Escape es *Saltar*, antes que nadie: ni Ajustes (si está debajo) ni Excalidraw lo ven.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      finish();
    };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [finish]);

  return (
    <div className="wl-backdrop">
      <div className="wl" role="dialog" aria-modal="true" aria-labelledby="wl-title" tabIndex={-1} ref={box}>
        <div className="wl-head">
          <h2 id="wl-title">{t("bienvenida.titulo")}</h2>
          <span className="wl-count">{t("bienvenida.paso_n", { n: step + 1, total: WELCOME_STEPS.length })}</span>
        </div>
        <ol className="wl-steps" aria-label={t("bienvenida.pasos")}>
          {WELCOME_STEPS.map((s, i) => (
            <li key={s} className={i === step ? "on" : i < step ? "done" : undefined}
                aria-current={i === step ? "step" : undefined}>
              <button disabled={locked} onClick={() => goToStep(i)}>
                <span className="wl-num">{i + 1}</span>{stepName[s]}
              </button>
            </li>
          ))}
        </ol>
        <section className="wl-body" aria-labelledby="wl-step-title">
          <h3 id="wl-step-title">{stepName[id]}</h3>
          {!app
            ? <p className="st-busy" role="status">{t("ajustes.cargando")}</p>
            : id === "idioma" ? <LanguageStep app={app} />
            : id === "sesion" ? <SessionStep />
            : id === "programas" ? <ProgramsStep />
            : <FolderStep app={app} onLock={setLocked} />}
        </section>
        <div className="wl-foot">
          <button className="pull-btn wl-skip" disabled={locked} onClick={finish}>{t("bienvenida.saltar")}</button>
          <button className="pull-btn" disabled={locked || step === 0} onClick={() => goToStep(prevStep(step))}>
            {t("bienvenida.atras")}
          </button>
          {step < LAST_STEP
            ? <button className="pull-btn pull-apply" disabled={locked} onClick={() => goToStep(nextStep(step))}>
                {t("bienvenida.siguiente")}
              </button>
            : <>
                {/* el agente de onboarding (PLAN_ONBOARDING N2): termina y abre su ventana */}
                {app?.workspace && (
                  <button className="pull-btn" disabled={locked} onClick={() => {
                    if (lockedRef.current) return;
                    void finishWelcome(saveAppSettings);
                    openOnboarding();
                  }}>{t("bienvenida.onboarding")}</button>
                )}
                <button className="pull-btn pull-apply" disabled={locked} onClick={finish}>{t("bienvenida.terminar")}</button>
              </>}
        </div>
      </div>
    </div>
  );
}

// 1. Idioma y unidades (D180, D182): lo mismo que *Ajustes → General*, en corto.
function LanguageStep({ app }: { app: AppSettings }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (changes: Record<string, unknown>) => {
    setBusy(true);
    setError(await saveAppSettings(changes));
    setBusy(false);
  };
  const units = app.unidades;
  const same = (p: UnitPrefs) => (Object.keys(p) as (keyof UnitPrefs)[]).every((m) => units[m] === p[m]);
  return (
    <>
      <p className="wl-intro">{t("bienvenida.idioma.intro")}</p>
      <div className="wl-field">
        <label htmlFor="wl-lang">{t("ajustes.idioma")}</label>
        <select id="wl-lang" value={app.idioma} disabled={busy} onChange={(e) => save({ idioma: e.target.value })}>
          {app.opciones.idiomas.map((l) => <option key={l} value={l}>{LANGUAGE_NAMES[l] ?? l}</option>)}
        </select>
      </div>
      <div className="wl-field">
        <span id="wl-units">{t("ajustes.unidades")}</span>
        <div className="st-presets" role="group" aria-labelledby="wl-units">
          <button className="pull-btn" aria-pressed={same(SI)} disabled={busy}
                  onClick={() => save({ unidades: SI })}>{t("unidades.si")}</button>
          <button className="pull-btn" aria-pressed={same(IMPERIAL)} disabled={busy}
                  onClick={() => save({ unidades: IMPERIAL })}>{t("unidades.imperial")}</button>
        </div>
      </div>
      <p className="wl-note">{t("ajustes.unidades.nota")} {t("bienvenida.idioma.afinar")}</p>
      {error && <p className="pull-error" role="alert">{error}</p>}
    </>
  );
}

type Session = { estado: "conectada" | "sin_sesion" | "no_comprobada" | "sin_cli"; cuenta?: string | null;
                 plan?: string | null; motivo?: string | null };

// 2. La sesión de Claude Code (R4): `claude auth status`, sin gastar tokens.
function SessionStep() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [login, setLogin] = useState<"abierto" | "fallo" | null>(null);
  const check = useCallback(async () => {
    setChecking(true);
    try {
      setSession(await post("/api/welcome/session"));
    } catch (e) {
      setSession({ estado: "no_comprobada", motivo: message(e) });
    } finally {
      setChecking(false);
    }
  }, []);
  useEffect(() => { void check(); }, [check]);
  const openLogin = async () => {
    try {
      setLogin((await post("/api/welcome/login")).ok ? "abierto" : "fallo");
    } catch {
      setLogin("fallo");
    }
  };

  return (
    <>
      <p className="wl-intro">{t("bienvenida.sesion.intro")}</p>
      {checking || !session
        ? <p className="wl-state wl-wait" role="status">{t("bienvenida.sesion.comprobando")}</p>
        : session.estado === "conectada"
          ? <div className="wl-state wl-ok" role="status">
              <b>{session.cuenta ? t("bienvenida.sesion.conectada", { cuenta: session.cuenta })
                                 : t("bienvenida.sesion.conectada_sin_cuenta")}</b>
              {session.plan && <span>{t("bienvenida.sesion.plan", { plan: planLabel(session.plan) })}</span>}
            </div>
          : session.estado === "sin_cli"
            ? <div className="wl-state wl-off" role="status">
                <b>{t("bienvenida.sesion.sin_cli")}</b>
                <span>{t("bienvenida.sesion.sin_cli_nota")}</span>
              </div>
          : session.estado === "sin_sesion"
            ? <div className="wl-state wl-off" role="status">
                <b>{t("bienvenida.sesion.sin_sesion")}</b>
                <span>{t("bienvenida.sesion.sin_sesion_nota")}</span>
              </div>
            : <div className="wl-state wl-off" role="status">
                <b>{t("bienvenida.sesion.no_comprobada")}</b>
                {session.motivo && <span>{t("bienvenida.sesion.motivo", { motivo: session.motivo })}</span>}
              </div>}
      {!checking && session && session.estado !== "conectada" && (
        <div className="wl-actions">
          {session.estado === "sin_sesion" && (
            <button className="pull-btn pull-apply" onClick={openLogin}>{t("bienvenida.sesion.iniciar")}</button>
          )}
          {session.estado === "sin_cli" && (
            <button className="pull-btn pull-apply" onClick={() => void post("/api/welcome/install").catch(() => {})}>
              {t("bienvenida.sesion.instalar")}
            </button>
          )}
          <button className="pull-btn" onClick={() => { setLogin(null); void check(); }}>
            {t("bienvenida.sesion.otra_vez")}
          </button>
        </div>
      )}
      {login === "abierto" && <p className="st-info" role="status">{t("bienvenida.sesion.login_abierto")}</p>}
      {login === "fallo" && <p className="pull-error" role="alert">{t("bienvenida.sesion.login_fallo")}</p>}
      {!checking && session && session.estado !== "conectada" && (
        <p className="wl-note">{t("bienvenida.sesion.opcional")}</p>
      )}
    </>
  );
}

// 3. Los programas conectados (D106): Fusion hoy. El estado de cada conector, refrescado
// mientras el paso se ve; *Abrir* como en un bloque (BlockView, `OpenConnector`).
function ProgramsStep() {
  const [connectors, setConnectors] = useState<Record<string, ConnectorInfo> | null>(null);
  const [failed, setFailed] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch("/api/connectors");
      if (!r.ok) throw new Error(t("ajustes.error_http", { estado: r.status }));
      setConnectors(await r.json());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), CONNECTORS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);
  const list = connectorList(connectors);

  return (
    <>
      <p className="wl-intro">{t("bienvenida.programas.intro")}</p>
      {connectors === null
        ? <p className={failed ? "pull-error" : "wl-state wl-wait"} role="status">
            {failed ? t("bienvenida.programas.sin_backend") : t("bienvenida.programas.preguntando")}
          </p>
        : list.length === 0
          ? <div className="wl-state wl-off" role="status"><b>{t("bienvenida.programas.ninguno")}</b>
              <span>{t("bienvenida.programas.ninguno_nota")}</span></div>
          : list.map((c) => <ProgramRow key={c.id} {...c} onLaunched={refresh} />)}
    </>
  );
}

function ProgramRow({ id, name, state, onLaunched }: {
  id: string; name: string; state: "disponible" | "abriendose" | "cerrado"; onLaunched: () => void;
}) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = async () => {
    setError(null);
    setOpening(true);
    try {
      await post(`/api/connectors/${encodeURIComponent(id)}/launch`);
    } catch (e) {
      setError(message(e));            // p. ej. «No encuentro Fusion instalado en este equipo»
    }
    setOpening(false);
    onLaunched();
  };
  return (
    <div className="wl-program">
      {state === "disponible"
        ? <div className="wl-state wl-ok" role="status"><b>{t("bienvenida.programas.disponible", { nombre: name })}</b></div>
        : state === "abriendose" || opening
          ? <div className="wl-state wl-wait" role="status"><b>{t("bienvenida.programas.abriendose", { nombre: name })}</b></div>
          : <div className="wl-state wl-off" role="status"><b>{t("bienvenida.programas.cerrado", { nombre: name })}</b>
              <span>{t("bienvenida.programas.cerrado_nota", { nombre: name })}</span></div>}
      {state === "cerrado" && !opening && (
        <div className="wl-actions">
          <button className="pull-btn pull-apply" onClick={open}>{t("bienvenida.programas.abrir", { nombre: name })}</button>
        </div>
      )}
      {error && <p className="pull-error" role="alert">{error}</p>}
    </div>
  );
}

type Picked = { ruta: string; nube: string | null };

// 4. Dónde se guarda (D186, R3): la carpeta del workspace, elegir otra y cambiar a ella. La de
// antes nunca se toca; el servidor rearranca en el mismo puerto y la ventana recarga.
function FolderStep({ app, onLock }: { app: AppSettings; onLock: (on: boolean) => void }) {
  const ws = app.workspace;
  const [picked, setPicked] = useState<Picked | null>(null);
  const [busy, setBusy] = useState<"elegir" | "cambiar" | "esperar" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const isCurrent = !!picked && sameFolder(picked.ruta, ws?.ruta);

  const choose = async () => {
    setBusy("elegir");
    setError(null);
    setInfo(null);
    try {
      const got = await post("/api/welcome/folder");
      if (got.ruta) setPicked({ ruta: got.ruta, nube: got.nube ?? null });
    } catch (e) {
      setError(t("bienvenida.carpeta.elegir_fallo", { motivo: message(e) }));
    }
    setBusy(null);
  };

  const use = async () => {
    if (!picked) return;
    setBusy("cambiar");
    setError(null);
    setInfo(null);
    onLock(true);
    // Antes del cambio: tras recargar, la bienvenida no vuelve a salir (el servidor de después
    // lee el mismo settings.toml).
    await saveAppSettings({ ...WELCOME_SEEN });
    try {
      const got = await post("/api/welcome/workspace", { ruta: picked.ruta });
      if (got.reinicio) {
        setBusy("esperar");
        const back = await waitForRestart(picked.ruta, async () => {
          const r = await apiFetch("/api/health", { cache: "no-store" });
          return r.ok ? await r.json() : null;
        });
        if (back) {
          location.reload();
          return;
        }
        setError(t("bienvenida.carpeta.no_vuelve"));
      } else {
        setInfo(got.al_abrir ? t("bienvenida.carpeta.al_abrir") : t("bienvenida.carpeta.misma"));
        if (!got.al_abrir) setPicked(null);
      }
    } catch (e) {
      setError(message(e));
    }
    setBusy(null);
    onLock(false);
  };

  return (
    <>
      <p className="wl-intro">{t("bienvenida.carpeta.intro")}</p>
      <div className="wl-folder">
        <span className="wl-label">{t("bienvenida.carpeta.actual")}</span>
        {ws?.ruta
          ? <code className="st-path">{ws.ruta}</code>
          : <span className="st-muted">{t("ajustes.workspace.sin_ruta")}</span>}
        {ws?.nube && <p className="st-warn st-cloud" role="note">{t("ajustes.workspace.nube", { servicio: ws.nube })}</p>}
      </div>
      {picked && (
        <div className="wl-folder">
          <span className="wl-label">{t("bienvenida.carpeta.elegida")}</span>
          <code className="st-path">{picked.ruta}</code>
          {picked.nube && <p className="st-warn st-cloud" role="note">{t("ajustes.workspace.nube", { servicio: picked.nube })}</p>}
          {isCurrent && <p className="wl-note">{t("bienvenida.carpeta.es_la_actual")}</p>}
        </div>
      )}
      <div className="wl-actions">
        <button className="pull-btn" disabled={busy !== null} onClick={choose}>{t("bienvenida.carpeta.elegir")}</button>
        {picked && (
          <button className="pull-btn pull-apply" disabled={busy !== null || isCurrent} onClick={use}>
            {t("bienvenida.carpeta.usar")}
          </button>
        )}
      </div>
      <p className="wl-note">{t("bienvenida.carpeta.nota")}</p>
      {busy === "cambiar" && <p className="st-busy" role="status">{t("bienvenida.carpeta.cambiando")}</p>}
      {busy === "esperar" && <p className="st-busy" role="status">{t("bienvenida.carpeta.esperando")}</p>}
      {info && <p className="st-info" role="status">{info}</p>}
      {error && <p className="pull-error" role="alert">{error}</p>}
    </>
  );
}
