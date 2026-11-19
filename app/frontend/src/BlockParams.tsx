// Control genérico *Parámetros* de un bloque (docs/PLAN_PAQUETES.md §5, P8): la tabla de la
// tarjeta (D96), con los controles especiales de cada parámetro (`widget`, D113). Lo usan la
// tarjeta (BlockView) y el panel genérico (PackPanel), cada uno con su borrador. Un control
// `<paquete>.<x>` no lo pinta la app: lo pinta la interfaz de ese paquete (P41, la parte del
// conector: el destino y el documento en Fusion).
import { useEffect, useState } from "react";
import { send } from "./socket";
import { t } from "./i18n";
import { fmt } from "./BlockOutputs";
import { ArchivoStep } from "./ArchivoStep";
import { linkedFile } from "./cards";
import { widgetPack } from "./packui";
import type { Proposal } from "./proposal";
import type { BlockState, BlockType } from "./store";
import { useUnits } from "./appSettings";
import { commitText, editText, shownUnit, toShown, type UnitPrefs } from "./units";

// Sugerencia de un campo de texto vacío: lo que el bloque dio en una salida del mismo sentido
// (el *Documento* de Construir en Fusion enseña el nombre que tiene ahora, D115).
const HINT_FROM: Record<string, string> = { documento: "documento" };
function textHint(outputs: BlockState["outputs"], name: string) {
  const key = HINT_FROM[name];
  for (const fields of Object.values(outputs ?? {})) {
    const v = key ? fields[key]?.value : undefined;
    if (typeof v === "string" && v) return v;
  }
  return t("bloques.params.por_defecto");
}

/** Los parámetros de un bloque con lo que se está escribiendo encima, y cómo se envían. */
export function useParamDraft(id: string, st: BlockState | undefined) {
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  // Cuando el servidor manda parámetros nuevos, solo se descarta lo editado que ya confirma
  // (mismo valor). Si se borrara todo, una actualización por otro campo pisaría el que se
  // está escribiendo y al salir se enviaría el valor antiguo.
  useEffect(() => {
    setDraft((d) => {
      const next: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(d)) {
        if (String(st?.params?.[k]) !== String(v)) next[k] = v;
      }
      return next;
    });
  }, [st?.params]);
  const params = { ...(st?.params ?? {}), ...draft };
  const commit = (name: string, value: unknown) => {
    setDraft((d) => ({ ...d, [name]: value }));
    send({ type: "set_params", block: id, params: { [name]: value } });
  };
  return { draft, params, setDraft, commit };
}

type Props = {
  ty: BlockType;
  st: BlockState | undefined;
  params: Record<string, unknown>;
  setDraft: (f: (d: Record<string, unknown>) => Record<string, unknown>) => void;
  commit: (name: string, value: unknown) => void;
  prop?: Proposal | null;
};

/** El valor de un parámetro numérico como se enseña (en la unidad de pantalla, D182). */
function shownNumber(v: unknown, unit: string, prefs: UnitPrefs) {
  return typeof v === "number" ? toShown(v, unit, prefs) : v;
}

export function BlockParams({ ty, st, params, setDraft, commit, prop }: Props) {
  const prefs = useUnits();
  // Un número se edita en la unidad de pantalla: el borrador guarda lo escrito y, al salir,
  // vuelve a la del parámetro; sin tocar el texto, el valor de antes tal cual (sin deriva).
  const numberField = (name: string, fallback: unknown, unit: string, optional: boolean) => {
    const v = params[name] ?? fallback;               // texto mientras se escribe; si no, número
    const saved = st?.params?.[name] ?? fallback;
    const base = typeof v === "number" ? v : typeof saved === "number" ? saved : null;
    const shown = base === null ? "" : editText(base, unit, prefs);
    return (
      <input type="text" inputMode="decimal" value={typeof v === "string" ? v : shown}
             placeholder={optional ? t("bloques.params.sin_dato") : undefined}
             onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
             onBlur={(e) => {
               if (optional && e.target.value.trim() === "") return commit(name, null);
               const out = commitText(base ?? NaN, shown, e.target.value, unit, prefs);
               if (out !== null && !Number.isNaN(out)) commit(name, out);
               // lo que no es un número no se guarda: vuelve el valor de antes
               else setDraft((d) => Object.fromEntries(Object.entries(d).filter(([k]) => k !== name)));
             }} />
    );
  };
  return (
    <div className="block-params">
      {/* Un parámetro que no es número ni texto (los fijados del Dimensionado, el árbol de
          un terminal) no se edita aquí: tiene su pestaña o su editor (D96). Uno que vale
          null por defecto es un número opcional: vacío = sin dato (PLAN_TERMINALES). */}
      {Object.entries(ty.params).filter(([, spec]) => !widgetPack(spec.widget)
                                               && (spec.widget || spec.default === null
                                                   || typeof spec.default !== "object")).map(([name, spec]) => (
        <label key={name} className={spec.widget || (typeof spec.default === "string" && !spec.choices.length) ? "wide" : undefined}>
          <span>{spec.label || name}</span>
          {spec.widget === "archivo_step" ? (
            <ArchivoStep value={String(params[name] ?? "")} onChange={(p) => commit(name, p)}
                         linked={linkedFile(ty.inputs, st?.inputs)} />
          ) : spec.choices.length ? (
            <select value={String(params[name] ?? spec.default)}
                    onChange={(e) => commit(name, e.target.value)}>
              {spec.choices.map((c) => <option key={c} value={c}>{spec.choice_labels?.[c] ?? c}</option>)}
            </select>
          ) : typeof spec.default === "string" ? (
            // Texto (D115: el nombre del documento). Vacío = el de por defecto, que se ve
            // como sugerencia con el que tiene ahora si ya se envió.
            <input type="text" value={String(params[name] ?? "")}
                   placeholder={textHint(st?.outputs ?? null, name)}
                   onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
                   onBlur={(e) => commit(name, e.target.value.trim())} />
          ) : spec.default === null ? (
            numberField(name, null, spec.unit, true)
          ) : (
            numberField(name, spec.default, spec.unit, false)
          )}
          <em>{shownUnit(spec.unit, prefs)}</em>
          {/* Propuesta (2A): el valor de ahora tachado y el propuesto resaltado. */}
          {prop?.change.params && name in prop.change.params && (
            <span className="prop-param">
              <span className="old">{fmt(shownNumber(prop.current.params?.[name], spec.unit, prefs))}</span>{" "}
              <span className="new">{fmt(shownNumber(prop.change.params[name], spec.unit, prefs))}</span> {shownUnit(spec.unit, prefs)}
            </span>
          )}
        </label>
      ))}
    </div>
  );
}
