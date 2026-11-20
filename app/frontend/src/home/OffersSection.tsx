// *Dónde comprar* en la ficha de la Librería (docs/PLAN_APROVISIONAMIENTO.md §5, A3, A4, A7, A10,
// R1): las ofertas de la clave, en el orden que da el backend (exactas vigentes por proveedor,
// luego las caducadas), y aparte los equivalentes sin verificar. *Buscar en proveedores* lanza el
// agente en el backend y se sondea cada segundo (la Librería está en el inicio, sin WebSocket);
// *Añadir oferta* guarda una a mano. Lo puro (precio, plazo, el formulario), en `supply.ts`.
import { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { addOffer, cancelSearch, deleteOffer, fetchOffers, fetchSearch, openOffer, startSearch } from "../libraryApi";
import {
  dateText, emptyOfferDraft, eventText, hostOf, leadText, offerPayload, priceText, resultText,
  type Offer, type OfferDraft, type OffersView, type SearchJob,
} from "../supply";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const POLL_MS = 1000;

/** La búsqueda en curso de cada clave: cerrar la ficha no la para, y al volver a abrirla se
 *  sigue enseñando por dónde va. */
const RUNNING = new Map<string, string>();

export function OffersSection({ clave }: { clave: string }) {
  const [view, setView] = useState<OffersView | null>(null);
  const [job, setJob] = useState<SearchJob | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const live = useRef(true);
  useEffect(() => () => { live.current = false; }, []);

  const reload = useCallback(async () => {
    try {
      const v = await fetchOffers(clave);
      if (live.current) setView(v);
    } catch (e) {
      if (live.current) setError(message(e));
    }
  }, [clave]);
  useEffect(() => { void reload(); }, [reload]);

  // Una búsqueda que ya iba (se cerró la ficha y se vuelve a abrir): se sigue sondeando.
  useEffect(() => {
    const id = RUNNING.get(clave);
    if (!id) return;
    fetchSearch(id).then((j) => live.current && setJob(j), () => RUNNING.delete(clave));
  }, [clave]);

  // El sondeo: cada respuesta programa la siguiente hasta que la búsqueda acaba.
  useEffect(() => {
    if (!job || job.estado !== "buscando") return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await fetchSearch(job.id);
        if (!live.current) return;
        setJob(next);
        if (next.estado !== "buscando") {
          RUNNING.delete(clave);
          setCancelling(false);
          await reload();
        }
      } catch (e) {
        RUNNING.delete(clave);
        if (live.current) { setError(message(e)); setJob(null); setCancelling(false); }
      }
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [job, clave, reload]);

  const searching = job?.estado === "buscando";

  const search = async () => {
    setError(null);
    setNotice(null);
    try {
      const { job: id } = await startSearch(clave);
      RUNNING.set(clave, id);
      setJob({ id, clave, estado: "buscando", eventos: [], resultado: null });
    } catch (e) {
      setError(message(e));         // 409 ya buscando, 422 sin ficha o sin proveedores: su motivo
    }
  };

  const cancel = async () => {
    if (!job) return;
    setCancelling(true);
    try {
      setJob(await cancelSearch(job.id));
    } catch (e) {
      setError(message(e));
      setCancelling(false);
    }
  };

  const remove = async (o: Offer) => {
    setError(null);
    try {
      await deleteOffer(o.id);
      await reload();
    } catch (e) {
      setError(message(e));
    }
  };

  const open = async (o: Offer) => {
    try {
      await openOffer(o.id);
    } catch (e) {
      setError(message(e));
    }
  };

  const exact = view?.exactas ?? [];
  const equivalent = view?.equivalentes ?? [];
  const days = view?.caducidad_dias ?? 7;
  const item = (o: Offer) => <OfferItem key={o.id} offer={o} days={days} onDelete={remove} onOpen={open} />;

  return (
    <section className="lb-supply" aria-labelledby={`lb-supply-${clave}`}>
      <div className="lb-supply-head">
        <h4 id={`lb-supply-${clave}`}>{t("libreria.ofertas.titulo")}</h4>
        <button className="pull-btn" onClick={() => void search()} disabled={searching}
                title={t("libreria.ofertas.buscar_titulo")}>
          {t("libreria.ofertas.buscar")}
        </button>
        <button className="pull-btn" onClick={() => { setNotice(null); setAdding(true); }} disabled={adding}>
          {t("libreria.ofertas.anadir")}
        </button>
      </div>

      {job && <SearchProgress job={job} cancelling={cancelling} onCancel={() => void cancel()} />}
      {error && <p className="pull-error" role="alert">{error}</p>}
      {notice && !error && <p className="lb-ok" role="status">{notice}</p>}

      {adding && (
        <OfferForm clave={clave} onCancel={() => setAdding(false)}
                   onSaved={async (o) => {
                     setAdding(false);
                     setNotice(t("libreria.ofertas.guardada", { proveedor: o.proveedor }));
                     await reload();
                   }} />
      )}

      {view === null ? (
        !error && <p className="lb-muted">{t("libreria.cargando")}</p>
      ) : !exact.length && !equivalent.length ? (
        <p className="lb-muted">{t("libreria.ofertas.vacia")}</p>
      ) : (
        <>
          {exact.length > 0 && <ul className="lb-offers">{exact.map(item)}</ul>}
          {equivalent.length > 0 && (
            <details className="lb-equiv">
              <summary>{t("libreria.ofertas.equivalentes", { n: equivalent.length })}</summary>
              <p className="lb-muted lb-small">{t("libreria.ofertas.equivalentes_nota")}</p>
              <ul className="lb-offers">{equivalent.map(item)}</ul>
            </details>
          )}
        </>
      )}
      {view && <p className="lb-muted lb-small">{t("libreria.ofertas.caducidad", { n: days })}</p>}
    </section>
  );
}

/** Una oferta: proveedor y precio arriba; referencia, plazo y disponibilidad; de dónde sale
 *  (caducada, según el buscador, a mano) y cuándo se consultó; el enlace y la cita. */
function OfferItem({ offer: o, days, onDelete, onOpen }: {
  offer: Offer; days: number; onDelete: (o: Offer) => Promise<void>; onOpen: (o: Offer) => Promise<void>;
}) {
  const [confirm, setConfirm] = useState(false);
  const meta = [leadText(o.plazo_dias), o.disponibilidad].filter(Boolean).join(" · ");
  const ref = [o.referencia, o.fabricante].filter(Boolean).join(" · ");
  return (
    <li className={o.vigente ? "lb-offer" : "lb-offer lb-expired"}>
      <div className="lb-offer-top">
        <b className="lb-offer-prov">{o.proveedor}</b>
        <span className={o.precio === null ? "lb-offer-price lb-muted" : "lb-offer-price"}>{priceText(o)}</span>
        <button className="lb-icon" title={t("libreria.ofertas.borrar_de", { proveedor: o.proveedor })}
                aria-label={t("libreria.ofertas.borrar_de", { proveedor: o.proveedor })}
                onClick={() => setConfirm(true)}>×</button>
      </div>
      {ref && <div className="lb-offer-ref">{ref}</div>}
      <div className={o.plazo_dias === null ? "lb-offer-meta lb-muted" : "lb-offer-meta"}>{meta}</div>
      <div className="lb-offer-tags">
        {!o.vigente && (
          <span className="lb-badge lb-b-old" title={t("libreria.ofertas.caducada_titulo", { n: days })}>
            {t("libreria.ofertas.caducada")}
          </span>
        )}
        {o.via === "buscador" && (
          <span className="lb-badge lb-b-warn" title={t("libreria.ofertas.buscador_titulo")}>{t("libreria.ofertas.buscador")}</span>
        )}
        {o.origen === "mano" && <span className="lb-badge">{t("libreria.ofertas.a_mano")}</span>}
        <span className="lb-muted">{t("libreria.ofertas.consultado", { fecha: dateText(o.fecha) })}</span>
      </div>
      {o.url && (
        <button className="lb-offer-link" onClick={() => void onOpen(o)} title={t("libreria.ofertas.abrir", { url: o.url })}>
          {hostOf(o.url)} ↗
        </button>
      )}
      {o.cita && <p className="lb-offer-quote" title={t("libreria.ofertas.cita_titulo")}>{t("libreria.ofertas.cita", { cita: o.cita })}</p>}
      {o.nota && <p className="lb-offer-note lb-muted" title={o.nota}>{o.nota}</p>}
      {confirm && (
        <div className="lb-offer-confirm" role="alertdialog" aria-label={t("libreria.ofertas.borrar_pregunta")}>
          <span>{t("libreria.ofertas.borrar_pregunta")}</span>
          <button className="pull-btn" onClick={() => setConfirm(false)} autoFocus>{t("libreria.cancelar")}</button>
          <button className="pull-btn st-danger" onClick={() => void onDelete(o)}>{t("libreria.ofertas.borrar")}</button>
        </div>
      )}
    </li>
  );
}

/** Por dónde va la búsqueda (cada paso, el último resaltado) y *Cancelar*; al acabar, cuántas
 *  apuntó y lo gastado. */
function SearchProgress({ job, cancelling, onCancel }: { job: SearchJob; cancelling: boolean; onCancel: () => void }) {
  const log = useRef<HTMLOListElement>(null);
  const steps = job.eventos.map(eventText).filter(Boolean);
  useEffect(() => {
    const el = log.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [steps.length]);
  if (job.estado !== "buscando") {
    return <p className={job.estado === "error" ? "pull-error" : "lb-ok"} role="status">{resultText(job)}</p>;
  }
  return (
    <div className="lb-search" role="status" aria-live="polite">
      <div className="lb-search-head">
        <span className="lb-spin" aria-hidden="true" />
        <b>{t("libreria.ofertas.buscando")}</b>
        <button className="pull-btn" onClick={onCancel} disabled={cancelling}>
          {cancelling ? t("libreria.ofertas.cancelando") : t("libreria.cancelar")}
        </button>
      </div>
      {steps.length > 0 && (
        <ol className="lb-search-log" ref={log}>
          {steps.map((s, i) => <li key={i} className={i === steps.length - 1 ? "now" : undefined}>{s}</li>)}
        </ol>
      )}
    </div>
  );
}

type FormField = keyof OfferDraft;

/** *Añadir oferta* (A7): el proveedor es obligatorio; un número vacío se manda como null
 *  (desconocido), nunca 0. Lo que el backend rechaza sale con su motivo. */
function OfferForm({ clave, onCancel, onSaved }: {
  clave: string; onCancel: () => void; onSaved: (o: Offer) => Promise<void>;
}) {
  const [d, setD] = useState<OfferDraft>(emptyOfferDraft);
  const [errors, setErrors] = useState<Partial<Record<FormField, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (f: FormField, v: string) => {
    setD((p) => ({ ...p, [f]: v }));
    setErrors((p) => { const n = { ...p }; delete n[f]; return n; });
  };

  const submit = async () => {
    const got = offerPayload(d);
    if (!got.ok) { setErrors(got.errors); return; }
    setBusy(true);
    setError(null);
    try {
      await onSaved(await addOffer(clave, got.oferta));
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  };

  const field = (f: FormField, label: string, opts: { wide?: boolean; placeholder?: string; numeric?: boolean; required?: boolean } = {}) => (
    <label className={opts.wide ? "lb-form-f wide" : "lb-form-f"}>
      <span>{label}{opts.required && <small className="lb-muted"> · {t("libreria.ofertas.form.obligatorio")}</small>}</span>
      <input value={d[f]} placeholder={opts.placeholder} inputMode={opts.numeric ? "decimal" : undefined}
             aria-invalid={!!errors[f]} className={errors[f] ? "bad" : undefined} disabled={busy}
             autoFocus={f === "proveedor"} onChange={(e) => set(f, e.target.value)} />
      {errors[f] && <small className="lb-reason">{errors[f]}</small>}
    </label>
  );

  return (
    <form className="lb-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}
          onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); onCancel(); } }}>
      <b>{t("libreria.ofertas.form.titulo")}</b>
      <p className="lb-muted lb-small">{t("libreria.ofertas.form.intro")}</p>
      <div className="lb-form-grid">
        {field("proveedor", t("libreria.ofertas.form.proveedor"), { wide: true, required: true })}
        {field("referencia", t("libreria.ofertas.form.referencia"), { wide: true, placeholder: clave })}
        {field("precio", t("libreria.ofertas.form.precio"), { numeric: true, placeholder: t("libreria.ofertas.form.vacio_desconocido") })}
        {field("moneda", t("libreria.ofertas.form.moneda"))}
        {field("por_cantidad", t("libreria.ofertas.form.por_cantidad"), { numeric: true, placeholder: "1" })}
        {field("plazo_dias", t("libreria.ofertas.form.plazo"), { numeric: true, placeholder: t("libreria.ofertas.form.vacio_desconocido") })}
        {field("disponibilidad", t("libreria.ofertas.form.disponibilidad"), { wide: true, placeholder: t("libreria.ofertas.form.disponibilidad_ph") })}
        {field("url", t("libreria.ofertas.form.url"), { wide: true, placeholder: "https://…" })}
        {field("nota", t("libreria.ofertas.form.nota"), { wide: true })}
      </div>
      <fieldset className="lb-form-match">
        <legend>{t("libreria.ofertas.form.coincidencia")}</legend>
        {(["exacta", "equivalente"] as const).map((m) => (
          <label key={m} className="lb-check">
            <input type="radio" name="coincidencia" value={m} checked={d.coincidencia === m} disabled={busy}
                   onChange={() => setD((p) => ({ ...p, coincidencia: m }))} />
            {t(`libreria.ofertas.form.${m}`)}
          </label>
        ))}
      </fieldset>
      {error && <p className="pull-error" role="alert">{error}</p>}
      <div className="st-row-btns">
        <button type="button" className="pull-btn" onClick={onCancel} disabled={busy}>{t("libreria.cancelar")}</button>
        <button type="submit" className="pull-btn pull-apply" disabled={busy}>
          {busy ? t("libreria.ofertas.form.guardando") : t("libreria.ofertas.form.guardar")}
        </button>
      </div>
    </form>
  );
}
