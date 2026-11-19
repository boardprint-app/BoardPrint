// Unidades en pantalla (plan D40, D182). Por dentro todo va en la unidad de cada parámetro o
// salida (SI: mm, kg, N…) y **nada cambia en disco por elegir otra**: se convierte solo al
// pintar y al editar. Lo que se puede elegir por magnitud está también en el backend
// (`pizarra/units.py`): si cambia una lista, cambia la otra.

import { editNumber, parseNumber } from "./i18n";

export type Magnitude = "longitud" | "masa" | "fuerza" | "par" | "angulo";
export type UnitPrefs = Record<Magnitude, string>;

export const SI: UnitPrefs = { longitud: "mm", masa: "kg", fuerza: "N", par: "N·m", angulo: "°" };
export const IMPERIAL: UnitPrefs = { longitud: "in", masa: "lb", fuerza: "lbf", par: "lbf·in", angulo: "°" };

// Cada símbolo conocido: su magnitud y cuánto vale en la unidad base de esa magnitud (mm, kg,
// N, N·m, °). Los alias son como los escriben los bloques ("deg", "Nm").
const TABLE: Record<string, { m: Magnitude; f: number; show?: string }> = {
  mm: { m: "longitud", f: 1 }, cm: { m: "longitud", f: 10 }, m: { m: "longitud", f: 1000 },
  in: { m: "longitud", f: 25.4 },
  g: { m: "masa", f: 0.001 }, kg: { m: "masa", f: 1 }, lb: { m: "masa", f: 0.45359237 },
  N: { m: "fuerza", f: 1 }, kN: { m: "fuerza", f: 1000 }, lbf: { m: "fuerza", f: 4.4482216152605 },
  "N·m": { m: "par", f: 1 }, Nm: { m: "par", f: 1, show: "N·m" }, "N*m": { m: "par", f: 1, show: "N·m" },
  "N·mm": { m: "par", f: 0.001 }, Nmm: { m: "par", f: 0.001, show: "N·mm" },
  "lbf·in": { m: "par", f: 0.1129848290276167 },
  "°": { m: "angulo", f: 1 }, deg: { m: "angulo", f: 1, show: "°" },
  rad: { m: "angulo", f: 180 / Math.PI },
};

export const UNIT_CHOICES: Record<Magnitude, string[]> = {
  longitud: ["mm", "cm", "m", "in"], masa: ["g", "kg", "lb"], fuerza: ["N", "kN", "lbf"],
  par: ["N·m", "N·mm", "lbf·in"], angulo: ["°", "rad"],
};

/** La unidad en que se enseña algo guardado en `unit`; una que la tabla no conoce, tal cual. */
export function shownUnit(unit: string, prefs: UnitPrefs): string {
  const u = TABLE[unit];
  return u ? prefs[u.m] ?? unit : unit;
}

/** El valor guardado en `unit`, en la unidad de pantalla. */
export function toShown(value: number, unit: string, prefs: UnitPrefs): number {
  const from = TABLE[unit];
  const to = from && TABLE[prefs[from.m]];
  return from && to && from.m === to.m ? value * from.f / to.f : value;
}

/** Lo escrito en la unidad de pantalla, en la unidad guardada `unit`. */
export function fromShown(value: number, unit: string, prefs: UnitPrefs): number {
  const to = TABLE[unit];
  const from = to && TABLE[prefs[to.m]];
  return to && from && from.m === to.m ? value * from.f / to.f : value;
}

/** Lo que va en el campo al editar: en el formato del idioma (coma decimal en español) y con
 *  6 cifras significativas (25,4 mm son «1» in y 600 mm, «23,622» in; nunca diez decimales). */
export function editText(value: number, unit: string, prefs: UnitPrefs): string {
  return editNumber(toShown(value, unit, prefs));
}

/** Lo que se guarda al salir del campo. Si no se tocó el texto, el valor de antes tal cual:
 *  enseñar redondeado y volver a guardar no debe mover nada (sin deriva). null: no es un
 *  número, no se guarda. */
export function commitText(original: number, shownText: string, typed: string, unit: string,
                           prefs: UnitPrefs): number | null {
  if (typed.trim() === shownText.trim()) return original;
  const n = parseNumber(typed);
  return n === null ? null : fromShown(n, unit, prefs);
}

/** Unas unidades de `/api/settings` listas para usar: lo que falta o no vale, SI. */
export function cleanPrefs(raw: unknown): UnitPrefs {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const out = { ...SI };
  for (const m of Object.keys(SI) as Magnitude[]) {
    const v = r[m];
    if (typeof v === "string" && UNIT_CHOICES[m].includes(v)) out[m] = v;
  }
  return out;
}
