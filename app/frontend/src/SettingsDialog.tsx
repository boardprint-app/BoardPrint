// La ventana *Ajustes* (docs/PLAN_PAQUETES.md P78; pestañas de docs/PLAN_PIZARRA.md D179):
// General, Apariencia, Atajos, Agentes, Paquetes y Avanzados, cada una en settings/ salvo
// Paquetes (§7), aquí: la lista con origen, versión, autor, código, librerías y error; instalar
// con su resumen y el aviso de que trae código (D25); exportar y desinstalar. No se cierra con
// un clic fuera: un resumen a medias se perdería (como P71); sí con Escape (en cualquier
// pestaña, salvo mientras Paquetes trabaja o se graba un atajo) o su botón.
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { loadAppSettings, useAppSettings, type AppSettings } from "./appSettings";
import { t } from "./i18n";
import { tpOwn } from "./packI18n";
import {
  baseName, itemNotes, originLabel, uninstallBlock, uninstallWarning,
  type InstalledPack, type Plan, type PlanItem, type Targets,
} from "./packs";
import { desktop, discard, exportPack, fetchPacks, inspect, install, uninstall, uploadFiles } from "./packsApi";
import { BLINK_MS, closeSettings, SETTINGS_TABS, useSettings, type InstallRequest, type SettingsTab } from "./settings";
import type { SkinId } from "./skins";
import { EscapeGuards, rich, useEscapeGuard } from "./settings/common";
import { GeneralTab } from "./settings/GeneralTab";
import { AppearanceTab } from "./settings/AppearanceTab";
import { ShortcutsTab } from "./settings/ShortcutsTab";
import { AgentsTab } from "./settings/AgentsTab";
import { AdvancedTab } from "./settings/AdvancedTab";
import "./settings.css";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

type SkinProps = { skin: SkinId; onSkin: (id: SkinId) => void };

export function SettingsDialog(props: SkinProps) {
  const s = useSettings();
  if (!s.open) return null;
  return <SettingsWindow request={s.install} seq={s.seq} tab={s.tab} highlight={s.highlight} {...props} />;
}

function SettingsWindow({ request, seq, tab: asked, highlight, skin, onSkin }: SkinProps & {
  request: InstallRequest | null; seq: number; tab: SettingsTab; highlight: string | null;
}) {
  const app = useAppSettings();
  const [tab, setTab] = useState<SettingsTab>(asked);
  const [failed, setFailed] = useState(false);
  const [guards] = useState(() => new Set<() => boolean>());
  const box = useRef<HTMLDivElement>(null);
  const tabName: Record<SettingsTab, string> = {
    general: t("ajustes.pestana.general"), apariencia: t("ajustes.pestana.apariencia"),
    atajos: t("ajustes.pestana.atajos"), agentes: t("ajustes.pestana.agentes"),
    paquetes: t("ajustes.pestana.paquetes"), avanzados: t("ajustes.pestana.avanzados"),
  };

  // Al abrir, lo último del backend (otra ventana pudo cambiar algo).
  useEffect(() => {
    void loadAppSettings().then((got) => setFailed(got === null));
  }, []);

  // Cada `openSettings(pestaña, fila)` con la ventana ya abierta cambia de pestaña.
  useEffect(() => setTab(asked), [asked, seq]);

  // La fila pedida, a la vista y con un parpadeo de medio segundo (D144, D187), cuando ya hay
  // ajustes que pintar y su pestaña se ve (con la ventana ya abierta, el cambio de pestaña llega
  // un render después). Una vez por petición: volver luego a la pestaña no la repite.
  const ready = app !== null;
  const blinked = useRef(-1);
  useEffect(() => {
    if (!highlight || !ready || tab !== asked || blinked.current === seq) return;
    const row = box.current?.querySelector<HTMLElement>(`[data-row="${CSS.escape(highlight)}"]`);
    if (!row) return;
    blinked.current = seq;
    row.scrollIntoView({ block: "center" });
    row.style.setProperty("--st-hl-ms", `${BLINK_MS}ms`);
    row.classList.add("st-hl");
    let done = false;
    const timer = window.setTimeout(() => {
      done = true;
      row.classList.remove("st-hl");
    }, BLINK_MS);
    return () => {
      window.clearTimeout(timer);
      row.classList.remove("st-hl");
      if (!done) blinked.current = -1;      // cortado a medias (StrictMode lo hace): se repite
    };
  }, [highlight, seq, ready, tab, asked]);

  // Escape cierra en cualquier pestaña, salvo si una se lo queda (Paquetes mientras trabaja) o
  // si ya lo usó algo de dentro (grabar un atajo lo cancela con `preventDefault`).
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if ([...guards].some((g) => g())) return;
      closeSettings();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [guards]);

  const panel = (id: SettingsTab, body: ReactNode) => (
    <section className="st-content" role="tabpanel" id={`st-panel-${id}`} aria-labelledby={`st-tab-${id}`}
             hidden={tab !== id}>
      {body}
    </section>
  );
  // Lo que pinta los ajustes, cuando ya han llegado.
  const needs = (render: (a: AppSettings) => ReactNode) =>
    app ? render(app) : <p className="st-busy" role="status">{failed ? t("ajustes.sin_backend") : t("ajustes.cargando")}</p>;

  return (
    <EscapeGuards.Provider value={guards}>
      <div className="st-backdrop">
        <div className="st" role="dialog" aria-modal="true" aria-labelledby="st-title" ref={box}>
          <div className="st-head">
            <h2 id="st-title">{t("ajustes.titulo")}</h2>
            <button className="pull-btn" onClick={closeSettings}>{t("ajustes.cerrar")}</button>
          </div>
          <div className="st-body">
            <nav className="st-nav" role="tablist" aria-orientation="vertical" aria-label={t("ajustes.secciones")}>
              {SETTINGS_TABS.map((id) => (
                <button key={id} id={`st-tab-${id}`} role="tab" aria-selected={tab === id}
                        aria-controls={`st-panel-${id}`} className={tab === id ? "st-tab on" : "st-tab"}
                        onClick={() => setTab(id)}>
                  {tabName[id]}
                </button>
              ))}
            </nav>
            {panel("general", needs((a) => <GeneralTab app={a} />))}
            {panel("apariencia", <AppearanceTab skin={skin} onSkin={onSkin} />)}
            {panel("atajos", needs((a) => <ShortcutsTab app={a} />))}
            {panel("agentes", needs((a) => <AgentsTab app={a} />))}
            {/* Paquetes, siempre montada: un resumen a medias no se pierde al cambiar de pestaña */}
            <PacksTab request={request} seq={seq} hidden={tab !== "paquetes"} />
            {panel("avanzados", needs((a) => <AdvancedTab app={a} />))}
          </div>
        </div>
      </div>
    </EscapeGuards.Provider>
  );
}

function PacksTab({ request, seq, hidden }: { request: InstallRequest | null; seq: number; hidden: boolean }) {
  const [packs, setPacks] = useState<InstalledPack[] | null>(null);
  const [targets, setTargets] = useState<Targets>({});
  const [plan, setPlan] = useState<Plan | null>(null);
  const [paths, setPaths] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);   // lo que se está haciendo
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLElement>(null);
  const planRef = useRef<Plan | null>(null);
  planRef.current = plan;

  const reload = useCallback(async () => {
    const got = await fetchPacks();
    setPacks(got.packs);
    setTargets(got.targets);
  }, []);

  const run = useCallback(async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    setError(null);
    setInfo(null);
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }, []);

  const review = useCallback((list: string[] | null, target: string) => run(t("paquetes.comprobando"), async () => {
    if (planRef.current) void discard(planRef.current.token);
    const got = await inspect(list, target);
    setPlan(got);
    if (got) setPaths(got.items.map((i) => i.archive));
  }), [run]);

  const fromFiles = useCallback((files: File[], target = "usuario") => run(t("paquetes.subiendo"), async () => {
    const list = await uploadFiles(files);
    await review(list, target);
  }), [run, review]);

  const pick = useCallback(() => {
    if (desktop) void review(null, plan?.target ?? "usuario");
    else picker.current?.click();
  }, [review, plan]);

  useEffect(() => {
    run(t("paquetes.cargando"), reload);
  }, [run, reload]);

  // Cerrar la ventana con un resumen a medias lo tira (y su carpeta en `.instalando/`)
  useEffect(() => () => {
    if (planRef.current) void discard(planRef.current.token);
  }, []);

  // Al pasar del resumen a la lista (o al revés) y con cada aviso, arriba: si no, el
  // «Instalado: …» queda fuera de la vista
  useEffect(() => {
    box.current?.scrollTo(0, 0);
  }, [plan?.token, info, error]);

  // Lo que pidió quien abrió la ventana: soltar archivos, el aviso del proyecto (P82)
  useEffect(() => {
    if (!request) return;
    if (request.paths?.length) void review(request.paths, "usuario");
    else if (request.files?.length) void fromFiles(request.files);
    else if (request.pick) pick();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seq]);

  // Escape cierra la ventana (SettingsWindow; el resumen lo tira el efecto de arriba al
  // desmontarse); mientras trabaja, no.
  useEscapeGuard(() => busy !== null);

  const cancelPlan = () => {
    if (plan) void discard(plan.token);
    setPlan(null);
  };
  const doInstall = () => plan && run(t("paquetes.instalando"), async () => {
    const done = await install(plan.token);
    setPlan(null);
    setPacks(done.packs);
    const names = done.installed.map((id) => {
      const p = done.packs.find((x) => x.id === id);
      return p ? tpOwn(p, p.name) : id;
    });
    setInfo(t("paquetes.instalado", { nombres: names.join(", ") }));
  });
  const doUninstall = (p: InstalledPack) => run(t("paquetes.desinstalando", { nombre: tpOwn(p, p.name) }), async () => {
    const done = await uninstall(p.id, p.origin);
    setConfirm(null);
    setPacks(done.packs);
    setInfo(t("paquetes.desinstalado", { nombre: tpOwn(p, p.name) }));
  });
  const doExport = (p: InstalledPack) => run(t("paquetes.exportando", { nombre: tpOwn(p, p.name) }), async () => {
    const path = await exportPack(p.id);
    if (path) setInfo(t("paquetes.exportado", { ruta: path }));
    else if (path === "") setInfo(t("paquetes.descargando", { nombre: tpOwn(p, p.name) }));
  });

  return (
    <section className="st-content" role="tabpanel" id="st-panel-paquetes" aria-labelledby="st-tab-paquetes"
             hidden={hidden} ref={box}>
      <input ref={picker} type="file" accept=".bppack" multiple hidden
             onChange={(e) => {
               const files = Array.from(e.target.files ?? []);
               e.target.value = "";
               if (files.length) void fromFiles(files, plan?.target ?? "usuario");
             }} />
      <div className="st-bar">
        <h3 id="st-packs">{t("ajustes.pestana.paquetes")}</h3>
        {!plan && <button className="pull-btn pull-apply" disabled={busy !== null} onClick={pick}>
          {t("paquetes.instalar_archivo")}
        </button>}
      </div>
      {busy && <p className="st-busy" role="status">{busy}</p>}
      {error && <p className="pull-error" role="alert">{error}</p>}
      {info && <p className="st-info" role="status">{info}</p>}
      {plan
        ? <Summary plan={plan} targets={targets} busy={busy !== null}
                   onTarget={(target) => review(paths, target)} onCancel={cancelPlan} onInstall={doInstall} />
        : packs && <PackList packs={packs} busy={busy !== null} confirm={confirm} onConfirm={setConfirm}
                             onUninstall={doUninstall} onExport={doExport} />}
    </section>
  );
}

function PackList({ packs, busy, confirm, onConfirm, onUninstall, onExport }: {
  packs: InstalledPack[]; busy: boolean; confirm: string | null;
  onConfirm: (id: string | null) => void; onUninstall: (p: InstalledPack) => void;
  onExport: (p: InstalledPack) => void;
}) {
  if (packs.length === 0) {
    return (
      <div className="st-empty">
        <p><b>{t("paquetes.ninguno")}</b></p>
        <p>{rich(t("paquetes.ninguno_nota"))}</p>
      </div>
    );
  }
  return (
    <ul className="st-packs">
      {packs.map((p) => {
        const blocked = uninstallBlock(p);
        return (
          <li key={p.id} className={p.error ? "st-pack st-broken" : "st-pack"}>
            <div className="st-pack-head">
              <b>{tpOwn(p, p.name)}</b>
              {p.version && <span className="st-ver">{p.version}</span>}
              <span className={`st-badge st-o-${p.origin}`}>{originLabel(p.origin)}</span>
              <span className="st-actions">
                <button className="pull-btn" disabled={busy || p.error !== null} onClick={() => onExport(p)}
                        title={p.error ? t("paquetes.exportar_roto") : t("paquetes.exportar_titulo")}>
                  {t("paquetes.exportar")}
                </button>
                <button className="pull-btn" disabled={busy || blocked !== null} title={blocked ?? undefined}
                        onClick={() => onConfirm(p.id)}>{t("paquetes.desinstalar")}</button>
              </span>
            </div>
            <div className="st-meta">{[p.id, p.author].filter(Boolean).join(" · ")}</div>
            {p.description && <p className="st-desc">{tpOwn(p, p.description)}</p>}
            <div className="st-chips">
              {p.code && <span className="st-chip">{t("paquetes.trae_codigo")}</span>}
              <span className="st-chip">
                {p.libraries.length ? t("paquetes.librerias", { lista: p.libraries.join(", ") }) : t("paquetes.sin_librerias")}
              </span>
              {Object.entries(p.requires).map(([d, spec]) => (
                <span key={d} className="st-chip">{t("paquetes.pide", { id: d, version: spec })}</span>
              ))}
              {p.required_by.length > 0 && (
                <span className="st-chip">{t("paquetes.lo_pide", { lista: p.required_by.join(", ") })}</span>
              )}
              {p.shadowed.map((o) => (
                <span key={o} className="st-chip st-chip-warn">
                  {t("paquetes.tambien_en", { origen: originLabel(o).toLowerCase() })}
                </span>
              ))}
            </div>
            {p.error && <p className="pull-error">{p.error}</p>}
            {confirm === p.id && (
              <div className="st-confirm" role="alertdialog" aria-label={t("paquetes.desinstalar_nombre", { nombre: tpOwn(p, p.name) })}>
                <p>{rich(t("paquetes.desinstalar_pregunta", {
                  nombre: tpOwn(p, p.name), origen: originLabel(p.origin).toLowerCase(), aviso: uninstallWarning(p),
                }))}</p>
                <div className="st-row-btns">
                  <button className="pull-btn" onClick={() => onConfirm(null)}>{t("ajustes.cancelar")}</button>
                  <button className="pull-btn st-danger" disabled={busy} onClick={() => onUninstall(p)}>
                    {t("paquetes.desinstalar")}
                  </button>
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Summary({ plan, targets, busy, onTarget, onCancel, onInstall }: {
  plan: Plan; targets: Targets; busy: boolean; onTarget: (t: string) => void;
  onCancel: () => void; onInstall: () => void;
}) {
  const n = plan.items.length;
  const breaks = Object.entries(plan.breaks);
  return (
    <div className="st-summary">
      <h4>{n === 1 ? t("paquetes.instalar_uno") : t("paquetes.instalar_varios", { n })}</h4>
      <div className="st-warn" role="note">
        {rich(n === 1 ? t("paquetes.aviso_codigo_uno") : t("paquetes.aviso_codigo_varios"))}
      </div>
      <fieldset className="st-target">
        <legend>{t("paquetes.donde")}</legend>
        {Object.entries(targets).sort(([a], [b]) => (a === "usuario" ? -1 : b === "usuario" ? 1 : 0)).map(([tg, dir]) => (
          <label key={tg}>
            <input type="radio" name="st-target" checked={plan.target === tg} disabled={busy}
                   onChange={() => onTarget(tg)} />
            <span>{rich(t(tg === "workspace" ? "paquetes.destino_workspace" : "paquetes.destino_usuario",
                          { origen: originLabel(tg) }))}
              <small>{dir}</small></span>
          </label>
        ))}
      </fieldset>
      {plan.items.map((it, i) => <SummaryItem key={`${it.archive}-${i}`} item={it} target={plan.target} />)}
      {breaks.length > 0 && (
        <div className="st-breaks">
          <b>{t("paquetes.dejaria_de_cargar")}</b>
          <ul>{breaks.map(([id, why]) => <li key={id}><b>{id}</b>: {why}</li>)}</ul>
        </div>
      )}
      <div className="st-row-btns">
        <button className="pull-btn" disabled={busy} onClick={onCancel}>{t("ajustes.cancelar")}</button>
        <button className="pull-btn pull-apply" disabled={busy || !plan.ok} onClick={onInstall}>
          {plan.ok ? t("paquetes.instalar") : t("paquetes.no_se_puede")}
        </button>
      </div>
    </div>
  );
}

/** El estado de una dependencia en el resumen (`Requirement.state`, dato del backend). */
const stateName = (state: string) => ({
  instalado: t("paquetes.estado.instalado"), "en otro archivo": t("paquetes.estado.otro_archivo"),
  falta: t("paquetes.estado.falta"),
} as Record<string, string>)[state] ?? state;

function SummaryItem({ item, target }: { item: PlanItem; target: string }) {
  const notes = itemNotes(item, target);
  return (
    <article className={item.problems.length ? "st-item st-broken" : "st-item"}>
      <div className="st-pack-head">
        <b>{item.name || baseName(item.archive)}</b>
        {item.version && <span className="st-ver">{item.version}</span>}
        <span className="st-file">{baseName(item.archive)}</span>
      </div>
      {(item.id || item.author) && <div className="st-meta">{[item.id, item.author].filter(Boolean).join(" · ")}</div>}
      {item.description && <p className="st-desc">{item.description}</p>}
      {notes.map((note) => <p key={note} className="st-note">{note}.</p>)}
      {item.blocks.length > 0 && (
        <p className="st-line"><span>{t("paquetes.bloques")}</span><span className="st-val">{item.blocks.join(", ")}</span></p>
      )}
      {item.requires.length > 0 && (
        <p className="st-line"><span>{t("paquetes.pide_titulo")}</span>
          <span className="st-val">
            {item.requires.map((r) => (
              <span key={r.id} className={`st-chip st-r-${r.state === "falta" ? "no" : "ok"}`}>
                {r.id} {r.spec} · {stateName(r.state)}{r.version ? ` (${r.version})` : ""}
              </span>
            ))}
          </span>
        </p>
      )}
      <p className="st-line"><span>{t("paquetes.librerias_titulo")}</span>
        <span className="st-val">{item.libraries.length ? item.libraries.join(", ") : t("paquetes.ninguna")}</span></p>
      {item.problems.length > 0 && (
        <ul className="st-problems">{item.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}
    </article>
  );
}
