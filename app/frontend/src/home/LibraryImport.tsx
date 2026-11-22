// *Importar CSV/Excel* de la *Librería* (docs/PLAN_V020.md V16; D33): el archivo, la hoja, el
// tipo de ficha (opcional: solo hace falta con campos de la ficha) y a qué campo va cada
// columna; después, el resumen del backend (qué se crea, qué se actualiza, qué fila no vale y
// por qué), y **nada se escribe hasta pulsar Importar**. Si entre tanto cambió el archivo o la
// librería (409), se pide otro resumen y se enseña. Cada campo de la ficha sale con la unidad y
// la descripción que declara su paquete (PLAN_LIBRERIA L4), y se avisa de los obligatorios que
// ninguna columna llena. Desde FF 7.6 se abre también rellenado (`initial`: el archivo, la hoja,
// el tipo y el mapeo que propuso el agente de onboarding, PLAN_ONBOARDING N7); entonces no se
// adivina nada, e *Importar* deja la propuesta guardada.
import { useEffect, useMemo, useRef, useState } from "react";
import { t } from "../i18n";
import {
  buildMapping, canApply, guessMapping, initialChoices, mappingTargets, missingRequired, NEW_FIELD, resolveChoices,
  showQuantity, shownUnit, STOCK_TARGETS, VALUE_PREFIX, type FieldInfo, type ImportInitial, type ImportPlan, type PlanRow,
} from "../library";
import {
  ApiError, applyImport, applyProposalImport, fetchFields, inspectImport, planImport, type Inspected,
} from "../libraryApi";
import { desktop } from "../packsApi";
import type { PackText } from "./usePackText";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const MAX_SHOWN = 400;                    // filas del resumen que se pintan (las cuentas, todas)

const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;

function targetLabel(target: string): string {
  if (target.startsWith(VALUE_PREFIX)) return target.slice(VALUE_PREFIX.length);
  return t(`libreria.destino.${target}`);
}

function cellText(v: unknown): string {
  if (v === null || v === undefined) return "";
  return String(v);
}

/** Lo que se dice de un campo en el selector y bajo él: «Nm · Par nominal en la salida», en el
 *  idioma de la app (texto del paquete, L5); vacío si no lo declara nadie. */
function fieldInfo(f: FieldInfo | undefined, packText: PackText): string {
  if (!f) return "";
  return [shownUnit(packText(f.paquete, f.unidad)), packText(f.paquete, f.descripcion)].filter(Boolean).join(" · ");
}

type Props = {
  types: string[]; packText: PackText; onDone: (message: string) => void | Promise<void>;
  initial?: ImportInitial | null;
};

export function LibraryImport({ types, packText, onDone, initial = null }: Props) {
  const [path, setPath] = useState("");
  const [got, setGot] = useState<Inspected | null>(null);
  const [sheet, setSheet] = useState("");
  const [type, setType] = useState("");
  const [fields, setFields] = useState<FieldInfo[]>([]);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [newFields, setNewFields] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [busy, setBusy] = useState<"" | "inspect" | "plan" | "apply">("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [onlyBad, setOnlyBad] = useState(false);
  // Rellenado (`initial`): el mapeo se pone cuando llegan las columnas y los campos de su tipo,
  // y hasta elegir otro archivo no se adivina ninguna columna.
  const [seed, setSeed] = useState<ImportInitial | null>(initial);
  const [fieldsType, setFieldsType] = useState("");
  const noGuess = useRef(!!initial);

  const withType = !!type.trim();
  const names = useMemo(() => fields.map((f) => f.nombre), [fields]);
  const targets = useMemo(() => mappingTargets(names, withType), [names, withType]);
  const fieldOf = useMemo(() => new Map(fields.map((f) => [VALUE_PREFIX + f.nombre, f])), [fields]);
  const declared = fields.filter((f) => f.declarado);

  // Los campos del tipo escrito, los que declara su paquete y los que ya usan sus fichas (con un
  // respiro mientras se escribe).
  useEffect(() => {
    const ty = type.trim();
    if (!ty) { setFields([]); return; }
    let live = true;
    const timer = window.setTimeout(() => {
      fetchFields(ty).then((f) => { if (live) { setFields(f.fields); setFieldsType(ty); } },
                           () => { if (live) { setFields([]); setFieldsType(ty); } });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [type]);

  // Sin tipo no hay campos de ficha: las columnas que iban a uno se quedan sin destino.
  useEffect(() => {
    if (withType) return;
    setChoices((prev) => {
      const drop = Object.entries(prev).filter(([, v]) => v && !targets.includes(v));
      if (!drop.length) return prev;
      return { ...prev, ...Object.fromEntries(drop.map(([k]) => [k, ""])) };
    });
  }, [withType, targets]);

  // Con los campos del tipo recién llegados, las columnas aún sin destino que se llaman como uno
  // van a él (lo que el usuario ya eligió no se toca).
  const columnsKey = (got?.columns ?? []).join("\n");
  useEffect(() => {
    if (noGuess.current) return;
    const cols = columnsKey ? columnsKey.split("\n") : [];
    const guess = guessMapping(cols, targets);
    setChoices((prev) => {
      const used = new Set(Object.values(prev).filter(Boolean));
      const add = cols.filter((c) => !prev[c] && guess[c] && !used.has(guess[c]));
      return add.length ? { ...prev, ...Object.fromEntries(add.map((c) => [c, guess[c]])) } : prev;
    });
  }, [targets, columnsKey]);

  // Rellenado: se abre su archivo con su tipo, y su mapeo se pone con los campos de ese tipo ya
  // llegados (uno que el tipo aún no tiene, como campo nuevo).
  useEffect(() => {
    if (!initial) return;
    setType(initial.type);
    void open(initial.path, initial.sheet || undefined, true);
  }, []);                                     // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!seed || !got) return;
    if (seed.type.trim() && fieldsType !== seed.type.trim()) return;
    const start = initialChoices(seed.mapping, got.columns ?? [], targets);
    setChoices(start.choices);
    setNewFields(start.newFields);
    setSeed(null);
  }, [seed, got, fieldsType, targets]);

  // Cualquier cambio de lo elegido deja el resumen viejo sin valor.
  useEffect(() => { setPlan(null); setInfo(null); }, [sheet, type, choices, newFields]);

  const open = async (p: string | null, sh?: string, seeded = false) => {
    if (!seeded) noGuess.current = false;
    setBusy("inspect");
    setError(null);
    try {
      const r = await inspectImport(p, sh);
      if (!r.file) return;                                  // diálogo cancelado
      setGot(r);
      setPath(r.file);
      setSheet(r.sheet ?? "");
      const cols = r.columns ?? [];
      const guess = guessMapping(cols, mappingTargets(names, withType));
      // Al cambiar de hoja se conserva lo elegido en las columnas que siguen ahí.
      setChoices((prev) => Object.fromEntries(cols.map((c) => [c, c in prev ? prev[c] : guess[c]])));
    } catch (e) {
      setError(message(e) + (p ? "" : `\n${t("libreria.importar.sin_dialogo")}`));
    } finally {
      setBusy("");
    }
  };

  const makePlan = async () => {
    setError(null);
    const resolved = resolveChoices(choices, newFields);
    if (!resolved.ok) { setError(resolved.error); return null; }
    const m = buildMapping(resolved.choices, type);
    if (!m.ok) { setError(m.error); return null; }
    setBusy("plan");
    try {
      const p = await planImport({ path: got?.file ?? path, sheet, type, mapping: m.mapping });
      setPlan(p);
      setOnlyBad(false);
      return p;
    } catch (e) {
      setError(message(e));
      return null;
    } finally {
      setBusy("");
    }
  };

  const apply = async () => {
    if (!plan) return;
    setBusy("apply");
    setError(null);
    try {
      // el archivo que propuso el agente: la propuesta queda guardada al importar (N7)
      const proposal = initial?.proposal && plan.file === initial.path ? initial.proposal : null;
      const r = proposal ? await applyProposalImport(proposal, plan.token) : await applyImport(plan.token);
      await onDone(t("libreria.importar.hecho", { creadas: r.created, actualizadas: r.updated, invalidas: r.invalid }));
    } catch (e) {
      setBusy("");
      if (e instanceof ApiError && e.status === 409) {
        const fresh = await makePlan();
        if (fresh) setInfo(t("libreria.importar.replan"));
      } else {
        setError(message(e));
      }
    }
  };

  const step = !got ? 1 : !plan ? 2 : 3;
  // Los obligatorios del tipo sin columna (un aviso: la ficha nueva se crea igual, sin ellos).
  const resolvedNow = resolveChoices(choices, newFields);
  const missing = withType ? missingRequired(fields, resolvedNow.ok ? resolvedNow.choices : choices) : [];
  const columns = got?.columns ?? [];
  const sample = got?.sample ?? [];

  return (
    <div className="lb-import">
      <ol className="lb-steps" aria-label={t("libreria.importar.pasos")}>
        {[t("libreria.importar.paso_archivo"), t("libreria.importar.paso_columnas"), t("libreria.importar.paso_resumen")]
          .map((label, i) => (
            <li key={label} className={step === i + 1 ? "on" : step > i + 1 ? "done" : undefined}
                aria-current={step === i + 1 ? "step" : undefined}>
              <span className="lb-step-n">{i + 1}</span>{label}
            </li>
          ))}
      </ol>

      {step === 1 && (
        <section className="lb-pick">
          <p>{t("libreria.importar.elige")}</p>
          <p className="lb-muted">{t("libreria.importar.nada_hasta")}</p>
          <div className="st-row-btns lb-left">
            <button className="pull-btn pull-apply" disabled={!!busy} onClick={() => void open(null)}>
              {busy === "inspect" ? t("libreria.importar.abriendo") : t("libreria.importar.elegir")}
            </button>
          </div>
          <form className="lb-path" onSubmit={(e) => { e.preventDefault(); if (path.trim()) void open(path.trim()); }}>
            <label>
              {t("libreria.importar.ruta")}
              <input value={path} onChange={(e) => setPath(e.target.value)} placeholder={t("libreria.importar.ruta_ejemplo")} />
            </label>
            <button className="pull-btn" type="submit" disabled={!!busy || !path.trim()}>{t("libreria.importar.abrir_ruta")}</button>
          </form>
          {!desktop && <p className="lb-muted">{t("libreria.importar.navegador")}</p>}
        </section>
      )}

      {got && (
        <div className="lb-file">
          <span><b>{baseName(got.file ?? "")}</b> <span className="lb-muted">{got.file}</span></span>
          <span className="lb-muted">{t(got.rows === 1 ? "libreria.importar.filas_uno" : "libreria.importar.filas", { n: got.rows ?? 0 })}</span>
          <button className="pull-btn" disabled={!!busy}
                  onClick={() => { setGot(null); setPlan(null); setChoices({}); setNewFields({}); setError(null); setSeed(null); }}>
            {t("libreria.importar.otro")}
          </button>
        </div>
      )}

      {step === 2 && got && (
        <section className="lb-map">
          <div className="lb-map-opts">
            {(got.sheets?.length ?? 0) > 0 && (
              <label>
                {t("libreria.importar.hoja")}
                <select value={sheet} disabled={!!busy} onChange={(e) => void open(got.file, e.target.value)}>
                  {got.sheets!.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
            )}
            <label>
              {t("libreria.importar.tipo")}
              <input list="lb-types" value={type} onChange={(e) => setType(e.target.value)}
                     placeholder={t("libreria.importar.tipo_ninguno")} />
              <datalist id="lb-types">{types.map((ty) => <option key={ty} value={ty} />)}</datalist>
            </label>
            <p className="lb-muted lb-map-hint">
              {withType
                ? (declared.length ? t("libreria.importar.tipo_declarados", { n: declared.length, tipo: type.trim(),
                                       obligatorios: declared.filter((f) => f.obligatorio).length })
                   : fields.length ? t("libreria.importar.tipo_campos", { n: fields.length, tipo: type.trim() })
                   : t("libreria.importar.tipo_nuevo", { tipo: type.trim() }))
                : t("libreria.importar.tipo_nota")}
            </p>
          </div>

          <table className="lb-table lb-map-table">
            <thead>
              <tr>
                <th>{t("libreria.importar.columna")}</th>
                <th>{t("libreria.importar.muestra")}</th>
                <th>{t("libreria.importar.va_a")}</th>
              </tr>
            </thead>
            <tbody>
              {columns.map((col) => (
                <tr key={col} className={choices[col] ? "mapped" : undefined}>
                  <th scope="row">{col}</th>
                  <td className="lb-sample">
                    {sample.slice(0, 3).map((r) => cellText(r[col])).filter(Boolean).join(" · ") || <span className="lb-muted">{t("libreria.importar.vacia")}</span>}
                  </td>
                  <td>
                    <div className="lb-target">
                      <select value={choices[col] ?? ""} aria-label={t("libreria.importar.destino_de", { columna: col })}
                              onChange={(e) => setChoices((p) => ({ ...p, [col]: e.target.value }))}>
                        <option value="">{t("libreria.importar.no_importar")}</option>
                        <option value="key">{targetLabel("key")}</option>
                        <optgroup label={t("libreria.importar.grupo_stock")}>
                          {STOCK_TARGETS.map((x) => <option key={x} value={x}>{targetLabel(x)}</option>)}
                        </optgroup>
                        {withType && (
                          <optgroup label={t("libreria.importar.grupo_ficha", { tipo: type.trim() })}>
                            <option value="manufacturer">{targetLabel("manufacturer")}</option>
                            <option value="kind">{targetLabel("kind")}</option>
                            {targets.filter((x) => x.startsWith(VALUE_PREFIX)).map((x) => {
                              const f = fieldOf.get(x);
                              const about = fieldInfo(f, packText);
                              return (
                                <option key={x} value={x} title={about || undefined}>
                                  {targetLabel(x)}{f?.obligatorio ? " *" : ""}{about ? ` — ${about}` : ""}
                                </option>
                              );
                            })}
                            <option value={NEW_FIELD}>{t("libreria.importar.campo_nuevo")}</option>
                          </optgroup>
                        )}
                      </select>
                      {fieldOf.has(choices[col] ?? "") && (
                        <span className="lb-field-info">
                          {fieldInfo(fieldOf.get(choices[col] ?? ""), packText)}
                          {fieldOf.get(choices[col] ?? "")?.obligatorio && <span className="lb-badge">{t("libreria.importar.obligatorio")}</span>}
                        </span>
                      )}
                      {choices[col] === NEW_FIELD && (
                        <input value={newFields[col] ?? ""} placeholder={t("libreria.importar.campo_nombre")}
                               aria-label={t("libreria.importar.campo_nombre_de", { columna: col })}
                               onChange={(e) => setNewFields((p) => ({ ...p, [col]: e.target.value }))} />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {missing.length > 0 && (
            <p className="lb-info lb-missing" role="status">
              {t("libreria.importar.obligatorios_sin_columna", { tipo: type.trim(), n: missing.length })}{" "}
              {missing.map((f, i) => (
                <span key={f.nombre}>{i > 0 && ", "}<code title={fieldInfo(f, packText) || undefined}>{f.nombre}</code></span>
              ))}
            </p>
          )}
        </section>
      )}

      {step === 3 && plan && <PlanView plan={plan} onlyBad={onlyBad} setOnlyBad={setOnlyBad} />}

      {info && <p className="lb-info" role="status">{info}</p>}
      {error && <p className="pull-error" role="alert">{error}</p>}

      {step > 1 && (
        <div className="lb-import-foot">
          {step === 2 ? (
            <button className="pull-btn pull-apply" disabled={!!busy} onClick={() => void makePlan()}>
              {busy === "plan" ? t("libreria.importar.calculando") : t("libreria.importar.ver_resumen")}
            </button>
          ) : (
            <>
              <button className="pull-btn" disabled={!!busy} onClick={() => setPlan(null)}>{t("libreria.importar.cambiar_mapeo")}</button>
              <button className="pull-btn pull-apply" disabled={!!busy || !canApply(plan)} onClick={() => void apply()}>
                {busy === "apply" ? t("libreria.importar.importando")
                  : busy === "plan" ? t("libreria.importar.calculando") : t("libreria.importar.importar")}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const STATES: PlanRow["state"][] = ["create", "update", "unchanged", "invalid"];

function PlanView({ plan, onlyBad, setOnlyBad }: { plan: ImportPlan; onlyBad: boolean; setOnlyBad: (v: boolean) => void }) {
  const rows = onlyBad ? plan.rows.filter((r) => r.state === "invalid") : plan.rows;
  const what = (r: PlanRow) => [
    r.ficha && t(`libreria.importar.ficha_${r.ficha}`),
    r.stock && t(`libreria.importar.stock_${r.stock}`, { cantidad: showQuantity(r.cantidad) }),
  ].filter(Boolean).join(" · ");
  return (
    <section className="lb-plan">
      <div className="lb-counts">
        {STATES.map((s) => (
          <span key={s} className={`lb-count lb-s-${s}`}>
            <b>{plan.counts[s]}</b> {t(`libreria.importar.cuenta_${s}`)}
          </span>
        ))}
      </div>
      <p className="lb-muted">
        {canApplyText(plan)}
      </p>
      {plan.counts.invalid > 0 && (
        <label className="lb-check">
          <input type="checkbox" checked={onlyBad} onChange={(e) => setOnlyBad(e.target.checked)} />
          {t("libreria.importar.solo_malas", { n: plan.counts.invalid })}
        </label>
      )}
      <div className="lb-plan-wrap">
        <table className="lb-table lb-plan-table">
          <thead>
            <tr>
              <th className="lb-num">{t("libreria.importar.fila")}</th>
              <th>{t("libreria.col.clave")}</th>
              <th>{t("libreria.importar.estado")}</th>
              <th>{t("libreria.importar.que")}</th>
              <th>{t("libreria.importar.motivo")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, MAX_SHOWN).map((r) => (
              <tr key={r.row} className={`lb-s-${r.state}`}>
                <td className="lb-num">{r.row}</td>
                <td>{r.key ?? <span className="lb-muted">{showQuantity(null)}</span>}</td>
                <td><span className={`lb-badge lb-s-${r.state}`}>{t(`libreria.importar.estado_${r.state}`)}</span></td>
                <td>{what(r)}</td>
                <td>
                  {r.reason && <span className="lb-reason">{r.reason}</span>}
                  {r.warnings.map((w) => <span key={w} className="lb-warn">{w}</span>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > MAX_SHOWN && (
          <p className="lb-muted">{t("libreria.importar.mas_filas", { n: rows.length - MAX_SHOWN })}</p>
        )}
      </div>
    </section>
  );
}

function canApplyText(plan: ImportPlan): string {
  if (!canApply(plan)) return t("libreria.importar.nada_que_escribir");
  return t("libreria.importar.escribe", { fichas: plan.writes.fichas, stock: plan.writes.stock, archivo: baseName(plan.file) });
}
