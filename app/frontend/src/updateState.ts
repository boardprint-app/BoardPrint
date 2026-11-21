// Lo puro del actualizador (docs/PLAN_V020.md §4): qué se enseña y qué se puede pedir según lo
// que sabe el shell. El estado compartido y las llamadas al backend, en `update.ts`.
import { t } from "./i18n";

export type UpdateState = {
  estado: "disponible" | "al_dia" | "instalando" | "error" | "desconocido";
  version?: string;
  actual?: string;
  notas?: string | null;
  fecha?: string | null;
  motivo?: string;
};

export const UNKNOWN: UpdateState = { estado: "desconocido" };

/** ¿Se enseña el aviso? Solo con una versión nueva que el usuario no haya dejado para luego. */
export function showBanner(s: UpdateState, dismissed: string | null): boolean {
  return s.estado === "disponible" && !!s.version && s.version !== dismissed;
}

/** Las notas del Release que trae el `latest.json` (PLAN_EXCEL §3.6), o null si no hay. Vienen
 *  en Markdown con las líneas cortadas a mano (como `docs/releases/`): una línea que sigue un
 *  párrafo o un punto de una lista se une a la anterior, porque el Markdown del chat pinta cada
 *  salto de línea. */
export function notesOf(s: UpdateState): string | null {
  const n = typeof s.notas === "string" ? s.notas.trim() : "";
  return n ? unwrap(n) : null;
}

const STARTS_BLOCK = /^\s*([-*+]\s|\d+[.)]\s|#|>|\||```)/;

function unwrap(md: string): string {
  const out: string[] = [];
  let fence = false;
  for (const line of md.split(/\r?\n/)) {
    const prev = out.length ? out[out.length - 1] : "";
    if (/^\s*```/.test(line)) fence = !fence;
    else if (!fence && line.trim() && prev.trim() && !STARTS_BLOCK.test(line) && !/^\s*(#|```|\|)/.test(prev)) {
      out[out.length - 1] = `${prev.trimEnd()} ${line.trim()}`;
      continue;
    }
    out.push(line);
  }
  return out.join("\n");
}

/** ¿Se puede pedir instalar? Solo con una versión nueva y nada instalándose ya. */
export const canInstall = (s: UpdateState): boolean => s.estado === "disponible" && !!s.version;

/** La frase de *Ajustes → General* para lo que sabe el shell. */
export function statusText(s: UpdateState, desktop: boolean): string {
  switch (s.estado) {
    case "disponible": return t("actualizar.disponible", { version: s.version ?? "?", actual: s.actual ?? "?" });
    case "al_dia": return t("actualizar.al_dia", { actual: s.actual ?? "?" });
    case "instalando": return t("actualizar.instalando", { version: s.version ?? "?" });
    case "error": return t("actualizar.error", { motivo: s.motivo ?? "?" });
    default: return desktop ? t("actualizar.desconocido") : t("actualizar.solo_escritorio");
  }
}

/** Lee lo que vino del backend; algo raro cuenta como «desconocido», nunca como un fallo. */
export function parseState(got: unknown): UpdateState {
  if (!got || typeof got !== "object") return UNKNOWN;
  const s = got as UpdateState;
  return ["disponible", "al_dia", "instalando", "error", "desconocido"].includes(s.estado) ? s : UNKNOWN;
}

