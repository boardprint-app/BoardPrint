// El panel Microsoft 365 del lienzo (docs/PLAN_M365.md §3, M14) y el selector de carpeta de
// *Guardar en OneDrive…* (M9). Se abre desde *Añadir archivo* de la barra (CardMenu.tsx) y va a
// la izquierda, con el aspecto de la bandeja de bloques (BlockPalette.tsx). Tres pestañas:
// - OneDrive: migas por carpetas y buscar; cada archivo, *Llevar a la pizarra* (M6).
// - SharePoint: sitios → bibliotecas → carpetas, con su permiso aparte (M4): sin él, el panel
//   lleva a *Ajustes → Cuentas*.
// - Correo: carpeta, buscar y cada correo a la pizarra como `.eml`, con o sin adjuntos (M10).
// Sin sesión, el panel lleva a *Ajustes → Cuentas*. Lo que se trae cae en el centro de la vista
// (en cascada si se traen varios seguidos); lo que ya estaba se selecciona (O17).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { t } from "./i18n";
import { fmtSize } from "./cards";
import { cascade } from "./palette";
import { FileIcon, FolderIcon } from "./FileCard";
import { openSettings } from "./settings";
import { setStore } from "./store";
import {
  closeM365Panel, closeSaveToCloud, enter, fmtModified, goTo, libraryRoot, oneDriveRoot, uploadTarget,
  useM365View, type M365Item, type M365Mail, type M365MailFolder, type M365Service, type M365Site, type Place,
} from "./m365";
import {
  m365Bring, m365BringMail, m365Drive, m365Mail, m365MailFolders, m365OpenWeb, m365Search, m365SiteDrives,
  m365Sites, m365State, m365Upload, type M365State, type M365Uploaded,
} from "./m365Api";
import "./m365.css";

type At = () => { x: number; y: number };
type Bring = (fn: (at: { x: number; y: number }) => Promise<BringResult>) => Promise<string | null>;
type BringResult = { ok: true; value: { ids: string[]; existing: string[]; notes?: string[] } } | { ok: false; error: string };

const SEARCH_DELAY = 350;   // ms sin teclear antes de buscar

/** Un texto que espera a que se deje de teclear. */
function useDebounced(value: string, ms = SEARCH_DELAY) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** La cuenta de Microsoft 365 mientras `active` (el panel o el selector abiertos), otra vez al
 *  iniciar o cerrar sesión (el `m365` del WebSocket). */
function useAccount(active: boolean) {
  const { tick } = useM365View();
  const [state, setState] = useState<M365State | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!active) return;
    let live = true;
    void m365State().then((r) => {
      if (!live) return;
      if (r.ok) { setState(r.value); setError(null); } else setError(r.error);
    });
    return () => { live = false; };
  }, [tick, active]);
  return { state, error };
}

const extType = (name: string) => {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? `archivo.${name.slice(dot + 1).toLowerCase()}` : "archivo";
};

export function M365Panel({ at, onExisting }: { at: At; onExisting: (ids: string[]) => void }) {
  const { panel } = useM365View();
  const [tab, setTab] = useState<"onedrive" | "sharepoint" | "correo">("onedrive");
  const { state, error } = useAccount(panel);
  const recent = useRef<{ x: number; y: number; at: number }[]>([]);

  // Esc cierra el panel (salvo escribiendo en un campo, que ya tiene su Esc).
  useEffect(() => {
    if (!panel) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") closeM365Panel(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [panel]);
  if (!panel) return null;

  // Traer algo: al centro de la vista, en cascada con lo recién traído. Devuelve el fallo, si lo hay.
  const bring: Bring = async (fn) => {
    const now = Date.now();
    recent.current = recent.current.filter((p) => now - p.at < 5000);
    const spot = cascade(at(), recent.current);
    recent.current.push({ ...spot, at: now });
    const r = await fn(spot);
    if (!r.ok) return r.error;
    const { existing, notes = [] } = r.value;
    const texts = [...notes];
    if (existing.length) {
      texts.unshift(existing.length === 1 ? t("lienzo.anadir.ya_esta") : t("lienzo.anadir.ya_estan", { n: existing.length }));
      onExisting(existing);
    }
    if (texts.length) setStore({ notice: { text: texts.join(" · "), kind: "info", at: Date.now() } });
    return null;
  };

  const account = state?.account ?? null;
  return (
    <aside className="bk-tray m365-tray" aria-label={t("m365.titulo")} onKeyDown={(e) => e.stopPropagation()}>
      <div className="bk-head"><b>{t("m365.titulo")}</b>
        <button type="button" onClick={closeM365Panel} aria-label={t("m365.panel.cerrar_panel")} title={t("m365.panel.cerrar")}>×</button>
      </div>
      {state === null && !error && <p className="bk-none">{t("m365.cargando")}</p>}
      {error && <p className="pull-error m365-err" role="alert">{error}</p>}
      {state && !state.configured && <p className="bk-none">{t("m365.panel.sin_configurar")}</p>}
      {state?.configured && !account && (
        <div className="m365-gate">
          <p>{t("m365.panel.sin_sesion")}</p>
          <button type="button" className="pull-btn pull-apply" onClick={() => openSettings("cuentas", "m365.cuenta")}>
            {t("m365.panel.ir_cuentas")}
          </button>
        </div>
      )}
      {state?.configured && account && (
        <>
          <div className="ag-tabs m365-tabs" role="tablist">
            {(["onedrive", "sharepoint", "correo"] as const).map((id) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id}
                      className={tab === id ? "ag-tab on" : "ag-tab"} onClick={() => setTab(id)}>
                {id === "onedrive" ? t("m365.panel.onedrive") : id === "sharepoint" ? t("m365.panel.sharepoint") : t("m365.panel.correo")}
              </button>
            ))}
          </div>
          {tab === "onedrive" && <DriveBrowser mode="files" bring={bring} />}
          {tab === "sharepoint" && <SharePointTab allowed={state.sharepoint} bring={bring} />}
          {tab === "correo" && <MailTab bring={bring} />}
          <p className="bk-hint">{t("m365.panel.ayuda")}</p>
        </>
      )}
    </aside>
  );
}

// ------------------------------------------------------------------ carpetas de una unidad

/** Las migas: cada paso vuelve a esa carpeta; el último es donde se está. */
function Crumbs({ crumbs, onGo, head }: { crumbs: Place[]; onGo: (i: number) => void; head?: ReactNode }) {
  return (
    <nav className="fv-crumbs m365-crumbs" aria-label={t("m365.panel.migas")}>
      {head}
      {crumbs.map((c, i) => (
        <span key={i} className="fv-crumbpart">
          {(i > 0 || head) && <span aria-hidden="true">›</span>}
          {i === crumbs.length - 1 ? <strong title={c.label}>{c.label}</strong>
            : <button type="button" className="fv-crumb" title={c.label} onClick={() => onGo(i)}>{c.label}</button>}
        </span>
      ))}
    </nav>
  );
}

/** Una fila de la nube: carpeta (se entra con un clic) o archivo, con su tamaño y su fecha. */
function ItemRow({ item, onOpen, action }: { item: M365Item; onOpen: () => void; action?: ReactNode }) {
  const meta = item.folder
    ? (item.child_count === 1 ? t("m365.panel.n_elementos_uno") : t("m365.panel.n_elementos", { n: item.child_count ?? 0 }))
    : fmtSize(item.size);
  const date = fmtModified(item.modified);
  const body = (
    <>
      {item.folder ? <FolderIcon small /> : <FileIcon type={extType(item.name)} size="sm" />}
      <span className="bk-txt"><span className="m365-name" title={item.name}>{item.name}</span>
        <small>{[meta, date].filter(Boolean).join(" · ")}</small></span>
    </>
  );
  return (
    <div className={`m365-row${item.folder ? " dir" : ""}`}>
      {item.folder
        ? <button type="button" className="m365-open" onClick={onOpen} aria-label={t("m365.panel.abrir_carpeta", { name: item.name })}>{body}</button>
        : <div className="m365-open">{body}</div>}
      {action}
    </div>
  );
}

/** Lo de dentro de una carpeta (o lo que se busca), con su espera y su fallo. */
function useListing<T>(load: () => Promise<{ ok: true; value: { items: T[] } } | { ok: false; error: string }>, key: string) {
  const [items, setItems] = useState<T[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setItems(null);
    setError(null);
    void load().then((r) => {
      if (!live) return;
      if (r.ok) setItems(r.value.items); else setError(r.error);
    });
    return () => { live = false; };
    // `load` cambia en cada pintado: lo que cuenta es la clave
  }, [key]);
  return { items, error };
}

/** El botón *Llevar a la pizarra* de una fila, con su espera. */
function BringButton({ onBring, label = t("m365.panel.llevar") }: { onBring: () => Promise<void>; label?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="fbtn m365-bring" disabled={busy}
            onClick={async () => { setBusy(true); await onBring(); setBusy(false); }}>
      {busy ? t("m365.panel.llevando") : label}
    </button>
  );
}

type BrowserProps = {
  mode: "files" | "folders";                 // `folders`: el selector de *Guardar en…* (M9)
  service?: M365Service;
  start?: Place[];                           // las migas de salida (SharePoint: la biblioteca)
  head?: ReactNode;                          // lo que va antes de las migas (SharePoint: Sitios)
  bring?: Bring;
  onPlace?: (place: Place) => void;          // la carpeta en la que se está (modo `folders`)
  onError?: (error: string) => ReactNode;    // lo que se añade a un fallo (SharePoint: el permiso)
};

/** Las carpetas de una unidad con sus migas, y en OneDrive, buscar. */
export function DriveBrowser({ mode, service = "onedrive", start, head, bring, onPlace, onError }: BrowserProps) {
  const [crumbs, setCrumbs] = useState<Place[]>(() => start ?? [oneDriveRoot()]);
  const [q, setQ] = useState("");
  const query = useDebounced(q.trim());
  const [rowError, setRowError] = useState<string | null>(null);
  const place = crumbs[crumbs.length - 1];
  const searching = service === "onedrive" && query !== "";
  const { items, error } = useListing<M365Item>(
    () => (searching ? m365Search(query) : m365Drive(place, service)),
    searching ? `q:${query}` : `${service}:${place.drive_id}:${place.item_id}`);
  useEffect(() => { onPlace?.(place); }, [place, onPlace]);

  const shown = (items ?? []).filter((i) => mode === "files" || i.folder);
  const open = (item: M365Item) => {
    setRowError(null);
    // desde la búsqueda no se sabe el camino: la carpeta cuelga de la raíz
    setCrumbs((c) => enter(searching ? c.slice(0, 1) : c, item));
    setQ("");
  };
  const fail = error ?? rowError;
  return (
    <div className="m365-browser">
      {service === "onedrive" && (
        <input className="bk-search" placeholder={t("m365.panel.buscar_onedrive")} value={q}
               onChange={(e) => setQ(e.target.value)} aria-label={t("m365.panel.buscar_onedrive")} />
      )}
      {!searching && <Crumbs crumbs={crumbs} head={head} onGo={(i) => setCrumbs((c) => goTo(c, i))} />}
      {searching && <div className="bk-group">{t("m365.panel.resultados")}</div>}
      <div className="bk-list m365-list">
        {fail && <div className="pull-error m365-err" role="alert">{fail}{onError?.(fail)}</div>}
        {!fail && items === null && <p className="bk-none">{t("m365.panel.cargando")}</p>}
        {items !== null && !shown.length && (
          <p className="bk-none">{searching ? t("m365.panel.sin_resultados", { q: query })
            : mode === "folders" ? t("m365.guardar.sin_carpetas") : t("m365.panel.vacia")}</p>
        )}
        {shown.map((item) => (
          <ItemRow key={`${item.drive_id}:${item.id}`} item={item} onOpen={() => open(item)}
                   action={mode === "files" && !item.folder && bring ? (
                     <BringButton onBring={async () => {
                       setRowError(await bring((at) => m365Bring({ ...item, service: item.service ?? service }, at)));
                     }} />
                   ) : undefined} />
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ SharePoint (M4)

/** Lo que se añade a un fallo de SharePoint: casi siempre es el permiso, que se da en Ajustes. */
const toAccounts = () => (
  <button type="button" className="pull-btn" onClick={() => openSettings("cuentas", "m365.sharepoint")}>
    {t("m365.sp.ir_permiso")}
  </button>
);

function SharePointTab({ allowed, bring }: { allowed: boolean; bring: Bring }) {
  const [q, setQ] = useState("");
  const query = useDebounced(q.trim());
  const [site, setSite] = useState<M365Site | null>(null);
  const [library, setLibrary] = useState<M365Site | null>(null);
  if (!allowed) {
    return (
      <div className="m365-gate">
        <p>{t("m365.sp.sin_permiso")}</p>
        {toAccounts()}
      </div>
    );
  }
  const sitesCrumb = (
    <button type="button" className="fv-crumb" onClick={() => { setSite(null); setLibrary(null); }}>{t("m365.sp.sitios")}</button>
  );
  if (site && library) {
    const siteCrumb = <>{sitesCrumb}<span aria-hidden="true">›</span>
      <button type="button" className="fv-crumb" title={site.name} onClick={() => setLibrary(null)}>{site.name}</button></>;
    return <DriveBrowser key={library.id} mode="files" service="sharepoint" start={[libraryRoot(library)]}
                         head={siteCrumb} bring={bring} onError={toAccounts} />;
  }
  if (site) return <Libraries site={site} head={sitesCrumb} onPick={setLibrary} />;
  return (
    <div className="m365-browser">
      <input className="bk-search" placeholder={t("m365.sp.buscar")} value={q} aria-label={t("m365.sp.buscar")}
             onChange={(e) => setQ(e.target.value)} />
      <div className="bk-group">{query ? t("m365.sp.sitios") : t("m365.sp.seguidos")}</div>
      <SiteList load={() => m365Sites(query)} keyOf={`s:${query}`} empty={t("m365.sp.sin_sitios")} onPick={setSite} />
    </div>
  );
}

function Libraries({ site, head, onPick }: { site: M365Site; head: ReactNode; onPick: (lib: M365Site) => void }) {
  return (
    <div className="m365-browser">
      <nav className="fv-crumbs m365-crumbs" aria-label={t("m365.panel.migas")}>
        {head}<span aria-hidden="true">›</span><strong title={site.name}>{site.name}</strong>
      </nav>
      <div className="bk-group">{t("m365.sp.bibliotecas")}</div>
      <SiteList load={() => m365SiteDrives(site.id)} keyOf={`d:${site.id}`} empty={t("m365.sp.sin_bibliotecas")} onPick={onPick} />
    </div>
  );
}

function SiteList({ load, keyOf, empty, onPick }: {
  load: () => ReturnType<typeof m365Sites>; keyOf: string; empty: string; onPick: (s: M365Site) => void;
}) {
  const { items, error } = useListing<M365Site>(load, keyOf);
  return (
    <div className="bk-list m365-list">
      {error && <div className="pull-error m365-err" role="alert">{error}{toAccounts()}</div>}
      {!error && items === null && <p className="bk-none">{t("m365.panel.cargando")}</p>}
      {items !== null && !items.length && <p className="bk-none">{empty}</p>}
      {(items ?? []).map((s) => (
        <div key={s.id} className="m365-row dir">
          <button type="button" className="m365-open" onClick={() => onPick(s)}>
            <FolderIcon small /><span className="bk-txt"><span className="m365-name" title={s.name}>{s.name}</span></span>
          </button>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ correo (M10)

/** La pestaña Correo: carpeta, buscar en todo el buzón y cada correo a la pizarra. */
export function MailTab({ bring }: { bring: Bring }) {
  const [folder, setFolder] = useState("inbox");
  const [folders, setFolders] = useState<M365MailFolder[]>([]);
  const [q, setQ] = useState("");
  const query = useDebounced(q.trim());
  const [rowError, setRowError] = useState<string | null>(null);
  useEffect(() => {
    void m365MailFolders().then((r) => { if (r.ok) setFolders(r.value.items); });
  }, []);
  const { items, error } = useListing<M365Mail>(() => m365Mail(folder, query), `${folder}:${query}`);
  const fail = error ?? rowError;
  const take = (m: M365Mail, attachments: boolean) => async () => {
    setRowError(await bring((at) => m365BringMail(m.id, attachments, at)));
  };
  return (
    <div className="m365-browser">
      <div className="m365-mailbar">
        <select className="bk-search m365-folder" value={folder} aria-label={t("m365.correo.carpeta")}
                onChange={(e) => setFolder(e.target.value)}>
          {!folders.some((f) => f.id === folder) && <option value={folder}>{t("m365.correo.bandeja")}</option>}
          {folders.map((f) => (
            <option key={f.id} value={f.id}>{f.unread ? t("m365.correo.carpeta_sin_leer", { name: f.name, n: f.unread }) : f.name}</option>
          ))}
        </select>
        <input className="bk-search" placeholder={t("m365.correo.buscar")} value={q} aria-label={t("m365.correo.buscar")}
               onChange={(e) => setQ(e.target.value)} />
      </div>
      {query && <div className="bk-group">{t("m365.correo.en_todo")}</div>}
      <div className="bk-list m365-list">
        {fail && <div className="pull-error m365-err" role="alert">{fail}</div>}
        {!fail && items === null && <p className="bk-none">{t("m365.panel.cargando")}</p>}
        {items !== null && !items.length && (
          <p className="bk-none">{query ? t("m365.panel.sin_resultados", { q: query }) : t("m365.correo.sin_correos")}</p>
        )}
        {(items ?? []).map((m) => (
          <div key={m.id} className={`m365-mail${m.read ? "" : " unread"}`}>
            <div className="m365-mail-top">
              <span className="m365-from" title={m.from.address}>{m.from.name || m.from.address}</span>
              {m.has_attachments && <span className="m365-clip" title={t("m365.correo.tiene_adjuntos")}
                                          aria-label={t("m365.correo.tiene_adjuntos")}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                     strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M21 11l-8.5 8.5a5 5 0 01-7-7L14 4a3.5 3.5 0 015 5l-8.5 8.5a2 2 0 01-3-3L15 7" />
                </svg></span>}
              <span className="m365-date">{fmtModified(m.received)}</span>
            </div>
            <div className="m365-subject" title={m.subject}>{m.subject || t("m365.correo.sin_asunto")}</div>
            {m.preview && <div className="m365-preview">{m.preview}</div>}
            <div className="m365-mail-btns">
              <BringButton onBring={take(m, false)} />
              {m.has_attachments && <BringButton onBring={take(m, true)} label={t("m365.correo.con_adjuntos")} />}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Guardar en OneDrive… (M9)

/** El selector de carpeta de *Guardar en OneDrive…*: las carpetas de OneDrive y *Guardar aquí*.
 *  La nube le cambia el nombre si ya hay uno igual (nunca escribe encima); se enseña el que
 *  queda, con *Abrir en la web*. */
export function SaveToCloudDialog() {
  const { saving } = useM365View();
  const [place, setPlace] = useState<Place | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<M365Uploaded | null>(null);
  const { state, error: accountError } = useAccount(saving !== null);
  useEffect(() => { setDone(null); setError(null); setBusy(false); }, [saving?.card]);
  useEffect(() => {
    if (!saving) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") closeSaveToCloud(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [saving]);
  if (!saving) return null;
  const save = async () => {
    if (!place) return;
    setBusy(true);
    setError(null);
    const r = await m365Upload(saving.card, uploadTarget(place, "onedrive"));
    setBusy(false);
    if (r.ok) setDone(r.value); else setError(r.error);
  };
  const account = state?.account ?? null;
  return (
    <div className="pull-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) closeSaveToCloud(); }}
         onKeyDown={(e) => e.stopPropagation()}>
      <div className="pull m365-pick" role="dialog" aria-modal="true" aria-label={t("m365.guardar.titulo")}>
        <header className="pull-head">
          <div>
            <h2>{t("m365.guardar.titulo")}</h2>
            <p>{t("m365.guardar.explicacion", { name: saving.name })}</p>
          </div>
          <button type="button" className="pull-btn" onClick={closeSaveToCloud}>{t("m365.guardar.cerrar")}</button>
        </header>
        <div className="m365-pick-body">
          {accountError && <p className="pull-error" role="alert">{accountError}</p>}
          {state && !account && (
            <div className="m365-gate">
              <p>{state.configured ? t("m365.panel.sin_sesion") : t("m365.panel.sin_configurar")}</p>
              {state.configured && (
                <button type="button" className="pull-btn pull-apply"
                        onClick={() => { closeSaveToCloud(); openSettings("cuentas", "m365.cuenta"); }}>
                  {t("m365.panel.ir_cuentas")}
                </button>
              )}
            </div>
          )}
          {account && !done && <DriveBrowser mode="folders" onPlace={setPlace} />}
          {done && (
            <div className="m365-done" role="status">
              <span>{t("m365.guardar.hecho")}</span> <b>{done.name}</b>
              {done.drive_id && done.item_id && (
                <button type="button" className="fv-crumb"
                        onClick={() => void m365OpenWeb({ drive_id: done.drive_id!, item_id: done.item_id!, service: "onedrive" })
                          .then((r) => { if (!r.ok) setError(r.error); })}>
                  {t("m365.tarjeta.abrir_web")}
                </button>
              )}
            </div>
          )}
          {error && <p className="pull-error" role="alert">{error}</p>}
        </div>
        {account && !done && (
          <footer className="m365-pick-foot">
            <span className="m365-where">{place ? t("m365.guardar.en", { carpeta: place.label }) : ""}</span>
            <button type="button" className="pull-btn pull-apply" disabled={!place || busy} onClick={() => void save()}>
              {busy ? t("m365.guardar.subiendo") : t("m365.guardar.aqui")}
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}
