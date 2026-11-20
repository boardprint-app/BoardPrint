// Salidas de un bloque (plan §3, D96 3B). Un bloque con candados o archivos las reparte en
// pestañas — Fijados, Salidas, Archivos — dentro de un hueco de alto fijo que hace scroll: la
// tarjeta no crece al cambiar de pestaña. Uno sencillo (el Tubo) las enseña sin pestañas.
import { Fragment, useState, type ReactNode } from "react";
import { apiFetch } from "./auth";
import { send } from "./socket";
import { getStore, setStore, useStore, type Value } from "./store";
import { Thumb } from "./Thumb";
import { useUnits } from "./appSettings";
import { editNumber, fmtNumber, t } from "./i18n";
import { tp } from "./packI18n";
import { shownUnit, toShown } from "./units";
import { columnLabel, groupLabel, numericCell, outputView, setLock, tableLayout, tableColumns, tableRows, toggleLock,
         type Field, type Locks } from "./outputs";

const LOCK_OPEN = (
  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 7.5-2" />
  </svg>
);
export const LOCK_SHUT = (
  <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" fill="none" />
  </svg>
);

export function fmt(v: unknown): string {
  if (typeof v === "number") return fmtNumber(v);     // coma o punto según el idioma, 4 cifras
  if (typeof v === "boolean") return v ? t("bloques.salidas.si") : t("bloques.salidas.no");
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return t("bloques.salidas.filas", { n: v.length });
  // {nombre: valor} (los límites propuestos de Analizar, D121): «J2_max 22 · J3_max 125»
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>)
    .map(([k, x]) => `${k} ${fmt(x)}`).join(" · ") || "—";
  return String(v);
}

// La comparación va pegada a su cifra («≥ 2»): si la celda parte línea, nunca entre las dos.
const glue = (s: string) => s.replace(/^([<>≤≥=≈~±])\s/, "$1\u00a0");

type Props = { id: string; outputs: Record<string, Record<string, Value>>; locks: Locks; stale: boolean };
type Tab = "fijados" | "salidas" | "archivos";

export function BlockOutputs({ id, outputs, locks, stale }: Props) {
  const view = outputView(outputs);
  const prefs = useUnits();
  const { project, blocks, types } = useStore();
  const pid = project?.id;
  // Los textos de las salidas son del paquete del bloque: se traducen al pintar (O15); las
  // claves, los valores que se fijan y los que se comparan, nunca.
  const pack = types[blocks[id]?.type ?? ""]?.pack;
  const nameOf = (f: { label?: string; key: string }) => (f.label ? tp(pack, f.label) : f.key);
  const show = (v: unknown) => (typeof v === "string" && v ? tp(pack, v) : fmt(v));
  // Las imágenes (la captura de Fusion, D114) van arriba, fuera de las pestañas.
  const thumbs = pid ? view.images.map((f) => (
    <Thumb key={f.key} project={pid} block={id} file={f.file!} label={nameOf(f)} stamp={outputs} />
  )) : null;
  const tabbed = view.lockable || view.files.length > 0;
  const [tab, setTab] = useState<Tab>("salidas");
  const [showAll, setShowAll] = useState<Set<string>>(() => new Set());
  const nLocks = Object.keys(locks).length;
  const sendLocks = (next: Locks) => send({ type: "set_params", block: id, params: { locks: next } });
  const labelOf = (key: string) => {
    for (const fields of Object.values(outputs)) if (fields[key]) return nameOf({ ...fields[key], key });
    return key;
  };

  const row = (f: Field) => {
    const locked = f.key in locks;
    // en la unidad de pantalla (D182); un texto largo (o un {nombre: valor}) va en su línea
    const text = typeof f.value === "number" ? fmt(toShown(f.value, f.unit ?? "", prefs)) : show(f.value);
    return (
      <div key={`${f.port}.${f.key}`} className={`bo-row${locked ? " locked" : ""}${typeof f.value !== "number" && text.length > 24 ? " long" : ""}`}>
        <span title={nameOf(f)}>{nameOf(f)}</span>
        <b>{text} <em>{shownUnit(f.unit ?? "", prefs)}</em>{locked && <span className="bo-chip">{t("bloques.salidas.fijado")}</span>}</b>
        {f.lockable ? (
          <button className="bo-lock" type="button" onClick={() => sendLocks(toggleLock(locks, f.key, f.value))}
                  title={locked ? t("bloques.salidas.quitar_candado") : t("bloques.salidas.fijar_valor")}
                  aria-label={locked ? t("bloques.salidas.quitar_candado_de", { name: nameOf(f) })
                                     : t("bloques.salidas.fijar_de", { name: nameOf(f) })}>
            {locked ? LOCK_SHUT : LOCK_OPEN}
          </button>
        ) : <span />}
      </div>
    );
  };

  const table = (f: Field) => {
    const all = f.value as Record<string, unknown>[];
    // lo de texto largo («Por qué», «Origen») va debajo de su fila, a todo lo ancho
    const { inline: cols, below } = tableLayout(all, tableColumns(all));
    const { rows, bad, filtered } = tableRows(all, showAll.has(f.key));
    const cell = (v: unknown) => (typeof v === "boolean" ? (v ? "✓" : "✗") : glue(show(v)));
    const empty = (v: unknown) => v == null || v === "" || v === "—";
    const toggle = () => setShowAll((s) => {
      const n = new Set(s);
      if (n.has(f.key)) n.delete(f.key); else n.add(f.key);
      return n;
    });
    return (
      <details key={f.key} className="bo-grp" open={all.length <= 6 || bad > 0}>
        <summary>{nameOf(f)} ({all.length}){bad > 0 && <span className="bo-bad"> · {t("bloques.salidas.fallan", { n: bad })}</span>}</summary>
        {/* La tabla cabe en la tarjeta (styles.css .bo-tw) y su cabecera se queda arriba del
            hueco al bajar por las filas. */}
        <div className="bo-tw">
          <table className="bo-table">
            <thead><tr>{cols.map((c) => (
              <th key={c} className={rows.length && rows.every((r) => r[c] == null || numericCell(r[c])) ? "n" : ""}>{columnLabel(c, pack)}</th>
            ))}</tr></thead>
            <tbody>
              {rows.map((r, i) => {
                const notes = below.filter((c) => !empty(r[c]));
                return (
                  <Fragment key={i}>
                    <tr className={r.cumple === false ? "bad" : ""}>
                      {cols.map((c) => <td key={c} className={numericCell(r[c]) ? "n" : ""}>{cell(r[c])}</td>)}
                    </tr>
                    {notes.length > 0 && (
                      <tr className={`bo-sub${r.cumple === false ? " bad" : ""}`}>
                        <td colSpan={cols.length}>
                          {notes.map((c) => <span key={c}><b>{columnLabel(c, pack)}:</b> {cell(r[c])}</span>)}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        {(filtered || (bad > 0 && all.length > 6)) && (
          <button type="button" className="bo-more" onClick={toggle}>
            {filtered ? t("bloques.salidas.ver_todas", { n: all.length }) : t("bloques.salidas.ver_fallan")}
          </button>
        )}
      </details>
    );
  };

  const salidas = (
    <>
      {view.plain.map(row)}
      {view.tables.map(table)}
      {view.groups.map((g) => {
        const nl = g.fields.filter((f) => f.key in locks).length;
        return (
          <details key={g.name} className="bo-grp" open={nl > 0}>
            <summary>{groupLabel(g.name, pack)} ({g.fields.length}){nl > 0 && ` · ${t(nl > 1 ? "bloques.salidas.fijados_varios" : "bloques.salidas.fijados_uno", { n: nl })}`}</summary>
            {g.fields.map(row)}
          </details>
        );
      })}
    </>
  );

  const fijados = nLocks === 0
    ? <p className="bo-note">{t("bloques.salidas.nada_fijado")}</p>
    : Object.entries(locks).map(([key, value]) => (
      <div key={key} className="bo-row locked">
        <span title={labelOf(key)}>{labelOf(key)}</span>
        <input type="text" inputMode="decimal" defaultValue={editNumber(value)} aria-label={t("bloques.salidas.valor_fijado_de", { name: labelOf(key) })}
               onBlur={(e) => {
                 const next = setLock(locks, key, e.target.value);
                 if (next) { if (next[key] !== value) sendLocks(next); }
                 else e.target.value = editNumber(value);
               }} />
        <button className="bo-quitar" type="button" onClick={() => sendLocks(toggleLock(locks, key, value))}>{t("bloques.salidas.quitar")}</button>
      </div>
    ));

  const archivos = view.files.map((f) => (
    <div key={f.key} className="bo-row bo-file">
      <span>{nameOf(f)}</span>
      <b className="mono">{f.file}</b>
      <button className="bo-open" type="button" onClick={() => openFile(id, f.file!)}>{t("bloques.salidas.abrir")}</button>
    </div>
  ));

  // Sin pestañas, el mismo tope que con ellas: una tabla abierta a mano (20 filas de límites con
  // dos estados) haría crecer la tarjeta encima de la de debajo (e2e de FF 5.2).
  if (!tabbed) return <div className={`bo${stale ? " stale" : ""}`}>{thumbs}<div className="bo-pane">{salidas}</div></div>;
  return (
    <div className={`bo tabbed${stale ? " stale" : ""}`}>
      {thumbs}
      <div className="bo-tabs" role="tablist">
        {view.lockable && <Tabb on={tab === "fijados"} onClick={() => setTab("fijados")}>{t("bloques.salidas.tab_fijados", { n: nLocks })}</Tabb>}
        <Tabb on={tab === "salidas"} onClick={() => setTab("salidas")}>{t("bloques.salidas.tab_salidas")}</Tabb>
        {view.files.length > 0 && (
          <Tabb on={tab === "archivos"} onClick={() => setTab("archivos")}>{t("bloques.salidas.tab_archivos", { n: view.files.length })}</Tabb>)}
      </div>
      <div className={`bo-pane${view.lockable ? " fixed" : ""}`} role="tabpanel">
        {tab === "fijados" ? fijados : tab === "archivos" ? archivos : salidas}
      </div>
    </div>
  );
}

function Tabb({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" role="tab" aria-selected={on} className={on ? "on" : ""} onClick={onClick}>{children}</button>;
}

// *Abrir* un archivo de salida con el programa del sistema; la ruta la valida el backend (D93).
async function openFile(block: string, file: string) {
  const pid = getStore().project?.id;
  if (!pid) return;
  const r = await apiFetch(`/api/projects/${encodeURIComponent(pid)}/blocks/${encodeURIComponent(block)}/open`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file }),
  });
  if (!r.ok) setStore({ lastError: t("bloques.salidas.error_abrir", { file, detail: (await r.json().catch(() => ({}))).detail ?? r.status }) });
}
