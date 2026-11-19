// *Librería* de la pantalla de inicio (docs/PLAN_V020.md §5, V14-V16): la tabla de fichas del
// workspace y de los paquetes, por tipo, con su estado, de dónde salen y el stock editable en la
// misma fila; la ficha en solo lectura al pulsar una fila, y *Importar CSV/Excel*
// (`LibraryImport`). Lo puro (cantidades, qué stock ha cambiado), en `library.ts`.
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { fmtNumber, t } from "../i18n";
import {
  draftOf, filterItems, newRowDrafts, originText, showQuantity, shownUnit, stockChanges,
  type FieldInfo, type Ficha, type LibraryItem, type NewStockRow, type StockDraft,
} from "../library";
import { deleteFicha, fetchFicha, fetchFields, fetchLibrary, saveStock } from "../libraryApi";
import { LibraryImport } from "./LibraryImport";
import { usePackText, type PackText } from "./usePackText";
import "./library.css";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
type Field = keyof Exclude<StockDraft, null>;

export function LibraryDialog({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [types, setTypes] = useState<string[]>([]);
  const [tab, setTab] = useState("");
  const [filter, setFilter] = useState("");
  const [drafts, setDrafts] = useState<Record<string, StockDraft>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [askClose, setAskClose] = useState(false);
  // Las filas *Añadir clave* (PLAN_LIBRERIA L2): stock a una clave que no está en la tabla.
  const [added, setAdded] = useState<NewStockRow[]>([]);
  const nextId = useRef(1);
  const packText = usePackText();

  const load = useCallback(async () => {
    try {
      const got = await fetchLibrary();
      setItems(got.items);
      setTypes(got.types);
    } catch (e) {
      setError(message(e));
      setItems((old) => old ?? []);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const saved = useMemo(() => Object.fromEntries((items ?? []).map((i) => [i.key, i.stock])), [items]);
  // Las claves nuevas entran en los borradores como cualquier fila; las repetidas o que no
  // valen se quedan fuera (`keyErrors`, por fila) y no dejan guardar.
  const fresh = useMemo(() => newRowDrafts(added, (items ?? []).map((i) => i.key)), [added, items]);
  const keyErrors = fresh.errors;
  const { changes, errors } = useMemo(
    () => stockChanges(saved, { ...drafts, ...fresh.drafts }, new Set(Object.keys(fresh.drafts))),
    [saved, drafts, fresh]);
  const nChanges = Object.keys(changes).length;
  const dirty = nChanges > 0 || Object.keys(errors).length > 0 || Object.keys(keyErrors).length > 0;

  const close = useCallback(() => {
    if (dirty) setAskClose(true);
    else onClose();
  }, [dirty, onClose]);

  // Escape cierra (o pregunta, con stock sin guardar); mientras se importa, lo usa el asistente.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || importing) return;
      if (askClose) setAskClose(false);
      else if (selected) setSelected(null);
      else close();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [close, importing, askClose, selected]);

  // Si la tabla ya no tiene el tipo elegido (se borró su última ficha), a «Todos».
  useEffect(() => {
    if (tab && !types.includes(tab)) setTab("");
  }, [types, tab]);

  const edit = (it: LibraryItem, field: Field, value: string) => {
    setError(null);
    setDrafts((prev) => ({ ...prev, [it.key]: { ...(prev[it.key] ?? draftOf(it.stock)), [field]: value } }));
  };
  const undo = (key: string) => setDrafts((prev) => {
    const next = { ...prev };
    delete next[key];
    return next;
  });

  const addRow = () => {
    setNotice(null);
    setAdded((prev) => [...prev, { id: nextId.current++, key: "", ...draftOf(null) }]);
  };
  const editNew = (id: number, field: Field | "key", value: string) => {
    setError(null);
    setAdded((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  };

  const save = async () => {
    const rowErrors = added.filter((r) => keyErrors[r.id]).map((r) => `${r.key.trim() || "?"}: ${keyErrors[r.id]}`);
    if (Object.keys(errors).length || rowErrors.length) {
      setError([...Object.entries(errors).map(([k, m]) => `${k}: ${m}`), ...rowErrors].join("\n"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await saveStock(changes);
      setDrafts({});
      // Una clave nueva queda como «solo stock», sin tipo: solo sale en «Todos».
      if (Object.keys(fresh.drafts).length) setTab("");
      setAdded([]);
      setNotice(t(nChanges === 1 ? "libreria.stock_guardado_uno" : "libreria.stock_guardado", { n: nChanges }));
      await load();
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  };

  const shown = useMemo(() => filterItems((items ?? []).filter((i) => !tab || i.type === tab), filter),
                        [items, tab, filter]);
  const openRow = (e: MouseEvent, key: string) => {
    if ((e.target as HTMLElement).closest("input, button")) return;
    setSelected(key);
  };

  const countOf = (type: string) => (items ?? []).filter((i) => !type || i.type === type).length;

  return (
    <div className="lb-backdrop">
      <div className="lb" role="dialog" aria-modal="true" aria-labelledby="lb-title">
        <div className="lb-head">
          <div>
            <h2 id="lb-title">{importing ? t("libreria.importar.titulo") : t("libreria.titulo")}</h2>
            <p>{importing ? t("libreria.importar.subtitulo") : t("libreria.subtitulo")}</p>
          </div>
          {!importing && (
            <button className="pull-btn" onClick={() => { setNotice(null); setImporting(true); }} disabled={dirty}
                    title={dirty ? t("libreria.importar.antes_guardar") : undefined}>
              {t("libreria.importar.abrir")}
            </button>
          )}
          <button className="pull-btn" onClick={importing ? () => setImporting(false) : close}>
            {importing ? t("libreria.importar.volver") : t("libreria.cerrar")}
          </button>
        </div>

        {askClose && (
          <div className="lb-confirm" role="alertdialog" aria-label={t("libreria.sin_guardar_titulo")}>
            <p>{t(nChanges === 1 ? "libreria.sin_guardar_uno" : "libreria.sin_guardar", { n: Math.max(nChanges, 1) })}</p>
            <button className="pull-btn" onClick={() => setAskClose(false)} autoFocus>{t("libreria.seguir")}</button>
            <button className="pull-btn st-danger" onClick={onClose}>{t("libreria.descartar_cerrar")}</button>
          </div>
        )}

        {importing ? (
          <LibraryImport types={types} packText={packText}
                         onDone={async (text) => { setImporting(false); setNotice(text); await load(); }} />
        ) : (
          <>
            <div className="lb-bar">
              <div className="lb-tabs" role="tablist" aria-label={t("libreria.tipos")}>
                {["", ...types].map((ty) => (
                  <button key={ty || "*"} role="tab" aria-selected={tab === ty} className={tab === ty ? "lb-tab on" : "lb-tab"}
                          onClick={() => setTab(ty)}>
                    {ty || t("libreria.todos")} <span className="lb-n">{countOf(ty)}</span>
                  </button>
                ))}
              </div>
              <input className="lb-filter" type="search" value={filter} onChange={(e) => setFilter(e.target.value)}
                     placeholder={t("libreria.filtrar")} aria-label={t("libreria.filtrar")} />
            </div>

            {(dirty || saving) && (
              <div className="lb-dirty" role="status">
                <span>{t(nChanges === 1 ? "libreria.cambios_uno" : "libreria.cambios", { n: nChanges })}</span>
                <button className="pull-btn" onClick={() => { setDrafts({}); setAdded([]); setError(null); }} disabled={saving}>
                  {t("libreria.descartar")}
                </button>
                <button className="pull-btn pull-apply" onClick={() => void save()} disabled={saving || !nChanges}>
                  {saving ? t("libreria.guardando") : t("libreria.guardar_stock")}
                </button>
              </div>
            )}
            {error && <p className="pull-error lb-msg" role="alert">{error}</p>}
            {notice && !error && <p className="lb-ok lb-msg" role="status">{notice}</p>}

            <div className={selected ? "lb-main with-ficha" : "lb-main"}>
              <div className="lb-table-wrap">
                {items === null ? (
                  <p className="lb-empty">{t("libreria.cargando")}</p>
                ) : (
                  <>
                  {/* sin filas, el aviso y, debajo, la tabla vacía: *Añadir clave* sigue a mano */}
                  {!items.length ? (
                    <div className="lb-empty">
                      <p>{t("libreria.vacia")}</p>
                      <p className="lb-muted">{t("libreria.vacia_nota")}</p>
                    </div>
                  ) : !shown.length ? (
                    <p className="lb-empty">{t("libreria.nada")}</p>
                  ) : null}
                  <table className="lb-table">
                    <thead>
                      <tr>
                        <th>{t("libreria.col.clave")}</th>
                        <th>{t("libreria.col.fabricante")}</th>
                        <th>{t("libreria.col.clase")}</th>
                        {!tab && <th>{t("libreria.col.tipo")}</th>}
                        <th>{t("libreria.col.estado")}</th>
                        <th>{t("libreria.col.origen")}</th>
                        <th className="lb-num">{t("libreria.col.cantidad")}</th>
                        <th>{t("libreria.col.ubicacion")}</th>
                        <th>{t("libreria.col.fecha")}</th>
                        <th>{t("libreria.col.nota")}</th>
                        <th><span className="sr-only">{t("libreria.col.acciones")}</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((it) => {
                        const removing = it.key in drafts && drafts[it.key] === null;
                        const d = drafts[it.key] ?? draftOf(it.stock);
                        const changed = it.key in changes;
                        const bad = errors[it.key];
                        const cls = [selected === it.key && "sel", changed && "changed", removing && "removing"].filter(Boolean).join(" ");
                        const cell = (field: Field, label: string) => (
                          <input className={`lb-in-${field}`} value={d[field]} disabled={removing} aria-label={`${label} ${it.key}`}
                                 onChange={(e) => edit(it, field, e.target.value)} />
                        );
                        return (
                          <tr key={it.key} className={cls || undefined} onClick={(e) => openRow(e, it.key)}>
                            <td><button className="lb-key" onClick={() => setSelected(it.key)}>{it.key}</button></td>
                            <td>{it.manufacturer}</td>
                            <td>{it.kind}</td>
                            {!tab && <td className="lb-muted">{it.type}</td>}
                            <td><Status it={it} /></td>
                            <td className={it.overrides ? "lb-origin lb-over" : "lb-origin"}>{originText(it)}</td>
                            <td className="lb-num">
                              <input className={bad ? "lb-qty bad" : "lb-qty"} value={d.cantidad} disabled={removing}
                                     inputMode="decimal" placeholder={showQuantity(null)}
                                     title={bad ?? (d.cantidad.trim() ? undefined : t("libreria.cantidad_desconocida"))}
                                     aria-label={t("libreria.cantidad_de", { clave: it.key })} aria-invalid={!!bad}
                                     onChange={(e) => edit(it, "cantidad", e.target.value)} />
                            </td>
                            <td>{cell("ubicacion", t("libreria.col.ubicacion"))}</td>
                            <td>{cell("fecha", t("libreria.col.fecha"))}</td>
                            <td>{cell("nota", t("libreria.col.nota"))}</td>
                            <td className="lb-act">
                              {(it.key in drafts) ? (
                                <button className="lb-icon" title={t("libreria.deshacer")} aria-label={t("libreria.deshacer_de", { clave: it.key })}
                                        onClick={() => undo(it.key)}>↺</button>
                              ) : it.stock ? (
                                <button className="lb-icon" title={t("libreria.quitar_stock")} aria-label={t("libreria.quitar_stock_de", { clave: it.key })}
                                        onClick={() => setDrafts((p) => ({ ...p, [it.key]: null }))}>×</button>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                      {added.map((r) => {
                        const key = r.key.trim();
                        const bad = keyErrors[r.id];
                        const qtyBad = bad ? undefined : errors[key];
                        const cell = (field: Field, label: string) => (
                          <input className={`lb-in-${field}`} value={r[field]} aria-label={`${label} ${t("libreria.nueva.clave")}`}
                                 onChange={(e) => editNew(r.id, field, e.target.value)} />
                        );
                        return (
                          <tr key={`new-${r.id}`} className={key in changes ? "lb-new changed" : "lb-new"}>
                            <td>
                              <input className={bad ? "lb-in-key bad" : "lb-in-key"} value={r.key} autoFocus
                                     placeholder={t("libreria.nueva.placeholder")} aria-label={t("libreria.nueva.clave")}
                                     aria-invalid={!!bad} onChange={(e) => editNew(r.id, "key", e.target.value)} />
                            </td>
                            <td colSpan={tab ? 4 : 5}>
                              {bad ? <span className="lb-reason">{bad}</span> : <span className="lb-muted">{t("libreria.nueva.aviso")}</span>}
                            </td>
                            <td className="lb-num">
                              <input className={qtyBad ? "lb-qty bad" : "lb-qty"} value={r.cantidad}
                                     inputMode="decimal" placeholder={showQuantity(null)}
                                     title={qtyBad ?? (r.cantidad.trim() ? undefined : t("libreria.cantidad_desconocida"))}
                                     aria-label={t("libreria.cantidad_de", { clave: key || t("libreria.nueva.clave") })}
                                     aria-invalid={!!qtyBad} onChange={(e) => editNew(r.id, "cantidad", e.target.value)} />
                            </td>
                            <td>{cell("ubicacion", t("libreria.col.ubicacion"))}</td>
                            <td>{cell("fecha", t("libreria.col.fecha"))}</td>
                            <td>{cell("nota", t("libreria.col.nota"))}</td>
                            <td className="lb-act">
                              <button className="lb-icon" title={t("libreria.nueva.quitar")} aria-label={t("libreria.nueva.quitar")}
                                      onClick={() => setAdded((p) => p.filter((x) => x.id !== r.id))}>×</button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                    <tfoot>
                      <tr>
                        <td colSpan={tab ? 10 : 11} className="lb-add">
                          <button className="pull-btn" onClick={addRow} title={t("libreria.nueva.anadir_titulo")}>
                            {t("libreria.nueva.anadir")}
                          </button>
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                  </>
                )}
              </div>
              {selected && (
                <FichaPanel key={selected} itemKey={selected} item={(items ?? []).find((i) => i.key === selected) ?? null}
                            packText={packText}
                            onClose={() => setSelected(null)}
                            onDeleted={async () => {
                              setNotice(t("libreria.ficha.borrada", { clave: selected }));
                              await load();
                            }} />
              )}
            </div>
            <p className="lb-foot lb-muted">{t("libreria.nota_pie")}</p>
          </>
        )}
      </div>
    </div>
  );
}

function Status({ it }: { it: LibraryItem }) {
  if (it.error) return <span className="lb-badge lb-b-err" title={it.error}>{t("libreria.estado.error")}</span>;
  if (it.origin === "stock") return <span className="lb-muted">{showQuantity(null)}</span>;
  return it.status === "verified"
    ? <span className="lb-badge lb-b-ok" title={[it.verified_by, it.verified_on].filter(Boolean).join(" · ") || undefined}>
        {t("libreria.estado.verificada")}
      </span>
    : <span className="lb-badge">{t("libreria.estado.sin_verificar")}</span>;
}

/** Un valor de `[values]` para leer: un número en el idioma de la interfaz, una lista unida. */
function valueText(v: unknown): string {
  if (typeof v === "number") return fmtNumber(v);
  if (Array.isArray(v)) return v.map(valueText).join(", ");
  if (v !== null && typeof v === "object") return JSON.stringify(v);
  return String(v ?? "");
}

type ValueRow = { name: string; value: string; src: string; desc: string };

/** Las filas de `[values]`, cada valor con su unidad: la que lleve el propio valor (`unit`) o la
 *  que declara el esquema del paquete para ese campo (PLAN_LIBRERIA L3), con su descripción;
 *  las dos, en el idioma de la app (`packText`). */
function valueRows(data: Record<string, unknown> | null, fields: Record<string, FieldInfo>,
                   packText: PackText): ValueRow[] {
  const values = data?.values;
  if (!values || typeof values !== "object") return [];
  return Object.entries(values as Record<string, unknown>).map(([name, e]) => {
    const f = fields[name];
    const desc = f?.descripcion ? packText(f.paquete, f.descripcion) : "";
    const declared = f ? shownUnit(packText(f.paquete, f.unidad)) : "";
    if (e && typeof e === "object" && !Array.isArray(e) && "v" in e) {
      const o = e as Record<string, unknown>;
      const unit = typeof o.unit === "string" ? o.unit : declared;
      return { name, value: valueText(o.v) + (unit ? ` ${unit}` : ""), src: typeof o.src === "string" ? o.src : "", desc };
    }
    return { name, value: valueText(e) + (declared ? ` ${declared}` : ""), src: "", desc };
  });
}

function FichaPanel({ itemKey, item, packText, onClose, onDeleted }: {
  itemKey: string; item: LibraryItem | null; packText: PackText; onClose: () => void; onDeleted: () => Promise<void>;
}) {
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [fields, setFields] = useState<Record<string, FieldInfo>>({});
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const stockOnly = item?.origin === "stock";

  useEffect(() => {
    if (stockOnly) return;
    let live = true;
    fetchFicha(itemKey).then((f) => live && setFicha(f), (e) => live && setError(message(e)));
    return () => { live = false; };
  }, [itemKey, stockOnly]);

  // La unidad y la descripción de cada campo, las del esquema del tipo (sin él, ninguna).
  const fichaType = ficha?.type ?? "";
  useEffect(() => {
    if (!fichaType) return;
    let live = true;
    fetchFields(fichaType).then(
      (r) => { if (live) setFields(Object.fromEntries(r.fields.map((f) => [f.nombre, f]))); }, () => {});
    return () => { live = false; };
  }, [fichaType]);

  const remove = async () => {
    setBusy(true);
    try {
      await deleteFicha(itemKey);
      onClose();
      await onDeleted();
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  };

  const rows = valueRows(ficha?.data ?? null, fields, packText);
  const shownItem = ficha ?? item;
  return (
    <aside className="lb-ficha" aria-label={t("libreria.ficha.aria", { clave: itemKey })}>
      <div className="lb-ficha-head">
        <h3>{itemKey}</h3>
        <button className="pull-btn" onClick={onClose}>{t("libreria.cerrar")}</button>
      </div>
      {shownItem && (
        <p className="lb-ficha-meta">
          {shownItem.type && <span className="lb-chip">{shownItem.type}</span>}
          {!stockOnly && <Status it={shownItem} />}
          <span className="lb-muted">{originText(shownItem)}</span>
        </p>
      )}
      {stockOnly && <p className="lb-muted">{t("libreria.ficha.solo_stock")}</p>}
      {error && <p className="pull-error" role="alert">{error}</p>}
      {!stockOnly && !ficha && !error && <p className="lb-muted">{t("libreria.cargando")}</p>}
      {ficha && (
        <>
          {ficha.error && <p className="pull-error">{ficha.error}</p>}
          {(ficha.manufacturer || ficha.kind) && (
            <p className="lb-ficha-line">{[ficha.manufacturer, ficha.kind].filter(Boolean).join(" · ")}</p>
          )}
          {ficha.status === "verified" && (ficha.verified_by || ficha.verified_on) && (
            <p className="lb-muted">{t("libreria.ficha.verificada_por", { quien: ficha.verified_by || "?", cuando: ficha.verified_on || "?" })}</p>
          )}
          {rows.length > 0 && (
            <>
              <h4>{t("libreria.ficha.valores")}</h4>
              <table className="lb-values">
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.name}>
                      <th scope="row" title={r.desc || undefined}>{r.name}</th>
                      <td className="lb-num">{r.value}</td>
                      <td className="lb-muted lb-src">{r.src}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h4>{t("libreria.ficha.toml")}</h4>
          <pre className="lb-toml">{ficha.toml}</pre>
          {ficha.editable ? (
            confirm ? (
              <div className="lb-confirm-inline">
                <p>{t(ficha.overrides ? "libreria.ficha.borrar_tapa" : "libreria.ficha.borrar_pregunta",
                      { clave: itemKey, paquete: ficha.overrides ?? "" })}</p>
                <div className="st-row-btns">
                  <button className="pull-btn" onClick={() => setConfirm(false)} autoFocus>{t("libreria.cancelar")}</button>
                  <button className="pull-btn st-danger" onClick={() => void remove()} disabled={busy}>{t("libreria.ficha.borrar")}</button>
                </div>
              </div>
            ) : (
              <div className="st-row-btns">
                <button className="pull-btn" onClick={() => setConfirm(true)}>{t("libreria.ficha.borrar_menu")}</button>
              </div>
            )
          ) : (
            ficha.origin === "pack" && <p className="lb-muted">{t("libreria.ficha.de_paquete", { paquete: ficha.pack ?? "?" })}</p>
          )}
        </>
      )}
    </aside>
  );
}
