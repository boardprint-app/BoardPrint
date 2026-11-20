// La pestaña *Proveedores* de la Librería (docs/PLAN_APROVISIONAMIENTO.md §2, A2, A11): la lista
// ordenada en la que busca *Buscar en proveedores* (nombre, dominio y los tipos de ficha que
// cubre; ninguno marcado = todos), con añadir, quitar, subir y bajar, y guardar entera
// (`PUT /api/supply/providers`, todo o nada: el 422 trae el motivo). Debajo, lo gastado en
// búsquedas desde la Librería (`consumo` de `ofertas.json`).
import { useCallback, useEffect, useState } from "react";
import { t } from "../i18n";
import { fetchOffers, fetchProviders, saveProviders } from "../libraryApi";
import { rich } from "../settings/common";
import { cleanProviders, moveItem, providersChanged, toggleType, usdText, type Provider, type Usage } from "../supply";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const PROVIDERS_MAX = 20;             // el mismo que el backend (supply.PROVIDERS_MAX)

type Row = Provider & { id: number };

export function ProvidersTab({ hidden, onDirty }: { hidden: boolean; onDirty: (dirty: boolean) => void }) {
  const [saved, setSaved] = useState<Provider[] | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nextId, setNextId] = useState(1);

  const fill = useCallback((list: Provider[]) => {
    setSaved(list);
    setRows(list.map((p, i) => ({ ...p, id: i + 1 })));
    setNextId(list.length + 1);
  }, []);

  useEffect(() => {
    fetchProviders().then((r) => { setTypes(r.tipos); fill(r.proveedores); }, (e) => { setError(message(e)); setSaved([]); });
  }, [fill]);
  // Lo gastado se vuelve a leer cada vez que se enseña la pestaña (una búsqueda pudo acabar).
  useEffect(() => {
    if (hidden) return;
    fetchOffers("").then((v) => setUsage(v.consumo), () => {});
  }, [hidden]);

  const dirty = saved !== null && providersChanged(rows, saved);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);

  const edit = (id: number, patch: Partial<Provider>) => {
    setNotice(null);
    setError(null);
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };
  const add = () => {
    setNotice(null);
    setRows((prev) => [...prev, { id: nextId, nombre: "", dominio: "", tipos: [] }]);
    setNextId((n) => n + 1);
  };
  const move = (i: number, by: number) => { setNotice(null); setRows((prev) => moveItem(prev, i, by)); };
  const remove = (id: number) => { setNotice(null); setRows((prev) => prev.filter((r) => r.id !== id)); };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const got = await saveProviders(cleanProviders(rows));
      fill(got.proveedores);
      setNotice(t("libreria.proveedores.guardados"));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const nameOf = (r: Row, i: number) => r.nombre.trim() || String(i + 1);

  return (
    <div className="lb-prov" hidden={hidden}>
      <p className="lb-prov-intro">{rich(t("libreria.proveedores.intro"))}</p>
      <p className="lb-info">{rich(t("libreria.proveedores.pista"))}</p>

      {(dirty || busy) && (
        <div className="lb-dirty" role="status">
          <span>{t("libreria.proveedores.sin_guardar")}</span>
          <button className="pull-btn" onClick={() => { if (saved) fill(saved); setError(null); }} disabled={busy}>
            {t("libreria.descartar")}
          </button>
          <button className="pull-btn pull-apply" onClick={() => void save()} disabled={busy}>
            {busy ? t("libreria.proveedores.guardando") : t("libreria.proveedores.guardar")}
          </button>
        </div>
      )}
      {error && <p className="pull-error" role="alert">{error}</p>}
      {notice && !error && !dirty && <p className="lb-ok" role="status">{notice}</p>}

      <div className="lb-table-wrap lb-prov-wrap">
        {saved === null ? (
          <p className="lb-empty">{t("libreria.cargando")}</p>
        ) : (
          <table className="lb-table lb-prov-table">
            <thead>
              <tr>
                <th>{t("libreria.proveedores.col.orden")}</th>
                <th>{t("libreria.proveedores.col.nombre")}</th>
                <th>{t("libreria.proveedores.col.dominio")}</th>
                <th>{t("libreria.proveedores.col.tipos")}</th>
                <th><span className="sr-only">{t("libreria.col.acciones")}</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.id}>
                  <td className="lb-prov-n">{i + 1}</td>
                  <td>
                    <input className="lb-prov-name" value={r.nombre} disabled={busy} autoFocus={!r.nombre && !r.dominio}
                           aria-label={t("libreria.proveedores.nombre_de", { n: i + 1 })}
                           onChange={(e) => edit(r.id, { nombre: e.target.value })} />
                  </td>
                  <td>
                    <input className="lb-prov-domain" value={r.dominio} disabled={busy} spellCheck={false}
                           placeholder={t("libreria.proveedores.dominio_ph")}
                           aria-label={t("libreria.proveedores.dominio_de", { n: i + 1 })}
                           onChange={(e) => edit(r.id, { dominio: e.target.value })} />
                  </td>
                  <td>
                    {types.length ? (
                      <div className="lb-prov-types">
                        {types.map((ty) => (
                          <button key={ty} type="button" className={r.tipos.includes(ty) ? "lb-tab on" : "lb-tab"}
                                  aria-pressed={r.tipos.includes(ty)} disabled={busy}
                                  onClick={() => edit(r.id, { tipos: toggleType(r.tipos, ty, types) })}>{ty}</button>
                        ))}
                        {!r.tipos.length && <span className="lb-muted">({t("libreria.proveedores.todos")})</span>}
                      </div>
                    ) : (
                      <span className="lb-muted">{t("libreria.proveedores.sin_tipos")}</span>
                    )}
                  </td>
                  <td className="lb-prov-act">
                    <button className="lb-icon" disabled={busy || i === 0} onClick={() => move(i, -1)}
                            title={t("libreria.proveedores.subir", { nombre: nameOf(r, i) })}
                            aria-label={t("libreria.proveedores.subir", { nombre: nameOf(r, i) })}>↑</button>
                    <button className="lb-icon" disabled={busy || i === rows.length - 1} onClick={() => move(i, 1)}
                            title={t("libreria.proveedores.bajar", { nombre: nameOf(r, i) })}
                            aria-label={t("libreria.proveedores.bajar", { nombre: nameOf(r, i) })}>↓</button>
                    <button className="lb-icon" disabled={busy} onClick={() => remove(r.id)}
                            title={t("libreria.proveedores.quitar", { nombre: nameOf(r, i) })}
                            aria-label={t("libreria.proveedores.quitar", { nombre: nameOf(r, i) })}>×</button>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr className="lb-prov-empty"><td colSpan={5} className="lb-muted">{t("libreria.proveedores.vacia")}</td></tr>
              )}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={5} className="lb-add">
                  <button className="pull-btn" onClick={add} disabled={busy || rows.length >= PROVIDERS_MAX}
                          title={rows.length >= PROVIDERS_MAX ? t("libreria.proveedores.max", { max: PROVIDERS_MAX }) : undefined}>
                    {t("libreria.proveedores.anadir")}
                  </button>
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      {usage && (
        <p className="lb-prov-usage">
          {t(usage.busquedas === 1 ? "libreria.proveedores.consumo_uno" : "libreria.proveedores.consumo",
             { coste: usdText(usage.usd), n: usage.busquedas })}
          {" "}<span className="lb-muted">{t("libreria.proveedores.consumo_nota")}</span>
        </p>
      )}
    </div>
  );
}
