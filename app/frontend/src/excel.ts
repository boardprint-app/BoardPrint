// El Excel como datos de la pizarra en la interfaz (docs/PLAN_EXCEL.md §3.5): los nombres de
// una tarjeta de Excel y qué parámetro de un bloque puede tomar cada uno (*Tomar de Excel*).
// Las reglas de unidad son las del backend (`pizarra/excel_names.py`, `check_unit`): si cambia
// una tabla, cambia la otra. El backend vuelve a comprobarlo todo al enlazar (un 422 con el
// motivo); aquí solo se decide qué se ofrece, y nunca se ofrece lo que él negaría. También lo
// puro de escribir las salidas en una copia (§3.3): dónde, qué campo y si el botón deja.
import { t } from "./i18n";
import type { ParamSpec } from "./store";

/** Un nombre definido del Excel, como lo da `sources_view()[tarjeta].names`. */
export type ExcelName = {
  nombre: string;              // la clave: el nombre del libro o `Hoja!nombre` (R1)
  hoja: string | null; celda: string | null; where: string | null;
  valor: unknown; unidad: string; formula: string | null;
  problema: string | null; motivo: string | null;
};

/** Un parámetro enlazado, como lo da `blocks_view().blocks[b].links[parámetro]`. */
export type ParamLink = {
  card: string; name: string; where: string | null; unit: string; value: unknown;
  reason: string | null;
  source: { kind: string; ref: string; where: string | null } | null;
};

// Lo que no se enlaza nunca (X3). Lo demás con `problema` (vacía, error, sin valor,
// calculando) se enlaza y deja el bloque `incompleto` hasta que tenga valor (R1).
export const NOT_ADMITTED = new Set(["varias_celdas", "constante", "no_es_celda", "ref_rota"]);

// La magnitud de cada unidad, como `UNITS` de excel_names.py (los alias de los bloques
// incluidos: "deg", "Nm").
const MAGNITUDE: Record<string, string> = {
  mm: "longitud", cm: "longitud", m: "longitud", in: "longitud", ft: "longitud",
  g: "masa", kg: "masa", lb: "masa",
  N: "fuerza", kN: "fuerza", lbf: "fuerza",
  "N·m": "par", Nm: "par", "N*m": "par", "N·mm": "par", Nmm: "par", "kN·m": "par", kNm: "par",
  "lbf·in": "par",
  "°": "angulo", deg: "angulo", rad: "angulo",
  s: "tiempo", ms: "tiempo",
};

/** El motivo (código de `excel.unidad.<código>` del backend) por el que un nombre con el
 *  sufijo `sfx` no puede ir a un parámetro en `unit`, o null si puede (X4). */
export function unitProblem(sfx: string, unit: string): string | null {
  sfx = sfx || "";
  unit = unit || "";
  if (!unit) return sfx ? "con_sufijo_sin_unidad" : null;
  if (!(unit in MAGNITUDE)) return "unidad_desconocida";
  if (!sfx) return "sin_sufijo";
  return MAGNITUDE[sfx] === MAGNITUDE[unit] ? null : "otra_magnitud";
}

export const compatible = (sfx: string, unit: string) => unitProblem(sfx, unit) === null;

/** Lo que necesita saber *Tomar de Excel* de un parámetro: su unidad, si es número o texto y,
 *  si es una lista, sus valores. */
export type ParamKind = { unit: string; kind: "number" | "text"; choices?: string[] };

/** Lo que *Tomar de Excel* necesita de un parámetro, o null si no se puede tomar de un Excel
 *  (un control especial, un sí/no, una lista de nodos). */
export function paramKind(spec: ParamSpec): ParamKind | null {
  if (spec.widget) return null;
  if (spec.default === null || typeof spec.default === "number") return { unit: spec.unit, kind: "number" };
  if (typeof spec.default === "string") return { unit: spec.unit, kind: "text", choices: spec.choices };
  return null;
}

/** ¿Puede el nombre `n` dar valor a un parámetro así? Nunca lo de X3; la unidad tiene que
 *  casar; y un valor que ya se conoce, ser del tipo del parámetro (un texto, solo a un texto y
 *  de su lista si la tiene). Uno sin valor todavía se puede enlazar (R1). */
export function offers(n: ExcelName, p: ParamKind): boolean {
  if (n.problema && NOT_ADMITTED.has(n.problema)) return false;
  if (!compatible(n.unidad, p.unit)) return false;
  const v = n.valor;
  if (v === null || v === undefined) return true;
  if (p.kind === "number") return typeof v === "number" && Number.isFinite(v);
  if (typeof v !== "string") return false;
  return !p.choices?.length || p.choices.includes(v);
}

/** Una tarjeta de Excel con sus nombres (lo que hace falta de `SourceView`). */
export type ExcelCard = { names?: ExcelName[] | null; name?: string };

/** Lo que ofrece *Tomar de Excel* a un parámetro: por tarjeta de Excel de la pizarra (con
 *  nombres leídos), los nombres que casan. Sin las tarjetas que no ofrecen ninguno. */
export function candidates(sources: Record<string, ExcelCard>, p: ParamKind) {
  const out: { card: string; cardName: string; names: ExcelName[] }[] = [];
  for (const [card, view] of Object.entries(sources)) {
    const names = (view.names ?? []).filter((n) => offers(n, p));
    if (names.length) out.push({ card, cardName: view.name ?? card, names });
  }
  return out;
}

/** ¿Hay alguna tarjeta de Excel con sus nombres leídos en la pizarra? (si no, el parámetro no
 *  enseña *Tomar de Excel*). */
export const hasExcel = (sources: Record<string, ExcelCard>) =>
  Object.values(sources).some((v) => Array.isArray(v.names));

/** El enlace de un parámetro, o null: uno enlazado no se edita a mano (R1, `set_params` lo
 *  niega), solo se quita el enlace. */
export function linkOf(links: Record<string, ParamLink> | null | undefined, param: string): ParamLink | null {
  return links?.[param] ?? null;
}

/** Cómo se enseña el estado de un nombre en la tarjeta: con valor, sin valor todavía, o no
 *  admitido (en gris, con su motivo). */
export function nameState(n: ExcelName): "ok" | "calculando" | "sin_valor" | "no_admitido" {
  if (n.problema && NOT_ADMITTED.has(n.problema)) return "no_admitido";
  if (n.problema === "calculando") return "calculando";
  if (n.problema || n.valor === null || n.valor === undefined) return "sin_valor";
  return "ok";
}

// ------------------------------------------------- escribir en una copia (PLAN_EXCEL §3.3)

/** Lo que va a un nombre, como lo da `sources_view()[tarjeta].write.rows[nombre]`: `value` ya en
 *  la unidad del sufijo; con `reason`, no se puede escribir. */
export type WriteRow = { block: string; port: string; field: string; value: unknown; unit: string; reason: string | null };
/** Lo que la tarjeta de un Excel enseña para escribir (`excel_write.view`). */
export type ExcelWrite = {
  writers: { id: string; title: string }[];
  rows: Record<string, WriteRow>;
  ready: boolean; reason: string | null;
  pending: string | null;           // la propuesta que espera a que se acepte o se rechace
};

/** ¿Es un Excel que recibe flechas de escritura (`.xlsx`, `.xlsm`, X9)? */
export const isExcelPath = (path: string) => /\.xls[xm]$/i.test(path.trim());

/** El motivo (código de `excel.escribir.unidad.<código>` del backend) por el que un campo en
 *  `unit` no se puede escribir en un nombre con el sufijo `sfx`, o null (`check_write`). */
export function writeProblem(unit: string, sfx: string): string | null {
  unit = unit || "";
  sfx = sfx || "";
  if (!sfx) return unit ? "sin_sufijo" : null;
  if (!unit) return "sin_unidad";
  if (!(unit in MAGNITUDE)) return "unidad_desconocida";
  return MAGNITUDE[unit] === MAGNITUDE[sfx] ? null : "otra_magnitud";
}

/** ¿Se puede escribir en el nombre? Una celda admitida (X3) que no es una fórmula: escribir
 *  encima la borraría (R4). */
export const writeTarget = (n: ExcelName) => !(n.problema && NOT_ADMITTED.has(n.problema)) && n.formula === null;

/** Un campo de salida que se ofrece a un nombre, con el motivo si no casa en unidad. */
export type WriteChoice = { block: string; title: string; port: string; field: string; unit: string; value: unknown;
                            label?: string; problem: string | null };

type Outputs = Record<string, Record<string, { value: unknown; unit: string; label?: string; file?: string; control?: string }>> | null;
const isScalar = (v: unknown) => typeof v === "number" || typeof v === "string" || typeof v === "boolean";

/** Lo que se ofrece al nombre `n`: los campos de la última salida de los bloques con flecha de
 *  escritura que son un valor (nunca uno que cita un archivo ni un control: una vista 2D, una
 *  gráfica), cada uno con su `problem` de unidad (o `no_es_numero` si hay que convertir un
 *  texto); los que casan, primero. Un bloque sin resultado no ofrece nada. */
export function writeChoices(n: ExcelName, writers: { id: string; title: string }[],
                             blocks: Record<string, { outputs: Outputs }>): WriteChoice[] {
  const out: WriteChoice[] = [];
  for (const w of writers) {
    for (const [port, fields] of Object.entries(blocks[w.id]?.outputs ?? {})) {
      for (const [field, f] of Object.entries(fields ?? {})) {
        if (!f || typeof f !== "object" || f.file !== undefined || f.control || !isScalar(f.value)) continue;
        const unit = f.unit ?? "";
        let problem = writeProblem(unit, n.unidad);
        if (!problem && n.unidad && typeof f.value !== "number") problem = "no_es_numero";
        out.push({ block: w.id, title: w.title, port, field, unit, value: f.value, label: f.label, problem });
      }
    }
  }
  return [...out.filter((c) => !c.problem), ...out.filter((c) => c.problem)];
}

/** El botón «Escribir copia»: deja solo con lo que dice el backend (`ready`) y con cada bloque
 *  de lo elegido al día aquí también (la vista del backend puede ir por detrás de una
 *  ejecución o de un parámetro cambiado). `reason`, lo que se enseña al lado. */
export function writeButton(write: ExcelWrite | null | undefined,
                            blocks: Record<string, { status: string }>): { disabled: boolean; reason: string | null } {
  if (!write) return { disabled: true, reason: null };
  if (!write.ready) return { disabled: true, reason: write.reason };
  for (const r of Object.values(write.rows)) {
    const s = blocks[r.block]?.status;
    if (s !== "al_dia") {
      const title = write.writers.find((w) => w.id === r.block)?.title ?? r.block;
      return { disabled: true, reason: t(s === "ejecutando" || s === "en_cola" ? "bloques.excel.escribir.ocupado"
        : s === "desactualizado" ? "bloques.excel.escribir.desactualizado" : "bloques.excel.escribir.sin_resultado", { title }) };
    }
  }
  return { disabled: false, reason: null };
}
