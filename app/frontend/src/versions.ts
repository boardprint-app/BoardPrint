// Versiones con nombre (plan §3, D76): lo que llega del backend y cómo se lee cada cambio de
// *Comparar* en la lista del panel.
import { KIND_LABEL, type PostitKind } from "./postit";
import type { BlockType } from "./store";
import { fmtNumber, getLanguage, t, type Lang } from "./i18n";

export type VersionInfo = { id: string; name: string; created: string; auto: boolean };

export type ChangeElement = {
  kind: string; type: string; x: number; y: number; width: number; height: number;
  text?: string; postitKind?: string; blockType?: string;
};

export type Change = {
  id: string;
  change: "added" | "removed" | "modified" | "minor";
  element: ChangeElement;
  fields?: Record<string, unknown>;
  moved?: boolean;
  resized?: boolean;
};

export type Compare = { a: string; b: string; aName: string; bName: string; changes: Change[] };

const short = (t: string | undefined, n = 40) => {
  const s = (t ?? "").replace(/\s+/g, " ").trim();
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
};

const other = (kind: string): string | undefined => ({
  text: t("agente.versiones.texto"), arrow: t("agente.versiones.flecha"), line: t("agente.versiones.linea"),
  freedraw: t("agente.versiones.trazo"), image: t("agente.versiones.imagen"), shape: t("agente.versiones.forma"),
  ink: t("agente.versiones.tinta"),   // un trazo de tinta encima de las tarjetas (D188)
} as Record<string, string>)[kind];

// Cómo se nombra un elemento: «Nota «La pinza va…»», «Bloque Tubo», «Texto «Montaje»».
export function elementName(e: ChangeElement, types: Record<string, BlockType>): string {
  if (e.kind === "postit") {
    const k = KIND_LABEL[(e.postitKind ?? "nota") as PostitKind] ?? t("agente.versiones.postit");
    return e.text?.trim() ? t("agente.versiones.con_texto", { nombre: k, texto: short(e.text) }) : k;
  }
  if (e.kind === "block") return t("agente.versiones.bloque", { titulo: types[e.blockType ?? ""]?.title ?? e.blockType ?? "" }).trim();
  const base = other(e.kind) ?? t("agente.versiones.elemento");
  return e.kind === "text" && e.text ? t("agente.versiones.con_texto", { nombre: base, texto: short(e.text) }) : base;
}

const fmt = (v: unknown) => (typeof v === "number" ? fmtNumber(v, { sig: 6 }) : String(v ?? "—"));

// Qué cambió dentro de un elemento modificado, en una línea.
export function fieldsText(c: Change, types: Record<string, BlockType>): string {
  const f = c.fields ?? {};
  const parts: string[] = [];
  const params = f.params as Record<string, [unknown, unknown]> | undefined;
  if (params) {
    const spec = types[c.element.blockType ?? ""]?.params ?? {};
    for (const [k, [a, b]] of Object.entries(params)) {
      const s = spec[k];
      parts.push(`${s?.label || k} ${fmt(a)} → ${fmt(b)}${s?.unit ? ` ${s.unit}` : ""}`);
    }
  }
  const kind = f.postitKind as [string, string] | undefined;
  if (kind) parts.push(`${KIND_LABEL[kind[0] as PostitKind] ?? kind[0]} → ${KIND_LABEL[kind[1] as PostitKind] ?? kind[1]}`);
  const state = f.state as [string, string] | undefined;
  if (state) parts.push(`${state[0]} → ${state[1]}`);
  if (f.text) parts.push(t("agente.versiones.texto_cambiado"));
  return parts.join(", ");
}

export const CHANGE_MARK: Record<Change["change"], string> = { added: "+", removed: "−", modified: "~", minor: "·" };

// La línea de la lista de *Comparar*.
export function changeLabel(c: Change, types: Record<string, BlockType>): string {
  const name = elementName(c.element, types);
  if (c.change === "modified") return `${name}: ${fieldsText(c, types)}`;
  if (c.change === "minor") {
    const what = c.moved && c.resized ? t("agente.versiones.movido_redimensionado")
      : c.resized ? t("agente.versiones.redimensionado") : t("agente.versiones.movido");
    return t("agente.versiones.menor", { nombre: name, que: what });
  }
  return name;
}

// Fecha corta de la lista, en el formato del idioma: «09/11 · 18:20» en español y
// «Nov 9 · 6:20 PM» en inglés (O17).
export function shortDate(iso: string, lang: Lang = getLanguage()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  if (lang === "en") {
    const day = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    // el espacio fino que pone Intl antes de PM, normal: el nombre por defecto de una versión sale de aquí
    return `${day} · ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`.replace(/\u202f/g, " ");
  }
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)} · ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// Al elegir para comparar: como mucho dos; el tercero deja fuera el más antiguo elegido.
export function toggleSelection(sel: readonly string[], id: string): string[] {
  if (sel.includes(id)) return sel.filter((x) => x !== id);
  return [...sel, id].slice(-2);
}
