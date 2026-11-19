// Ajustes → Paquetes (docs/PLAN_PAQUETES.md §7, P78-P84): lo que enseña la lista y el resumen
// de instalar. Las llamadas a `/api/packs`, en `packsApi.ts`.
import { t } from "./i18n";

export const PACK_SUFFIX = ".bppack";

/** Un paquete cargado o roto, como lo da `GET /api/packs`. */
export type InstalledPack = {
  id: string; name: string; version: string; author: string; description: string;
  origin: string; path: string; shadowed: string[]; error: string | null;
  requires: Record<string, string>; libraries: string[]; code: boolean;
  required_by: string[]; removable: boolean;
  /** Sus catálogos de traducción (O15), `{idioma: {texto de origen: traducción}}`. */
  i18n?: Record<string, Record<string, string>>;
};
export type Requirement = { id: string; spec: string; state: "instalado" | "en otro archivo" | "falta"; version: string | null };
/** Un paquete del resumen de instalar (`pack_install.Item`). */
export type PlanItem = {
  archive: string; id: string; name: string; version: string; author: string; description: string;
  requires: Requirement[]; libraries: string[]; blocks: string[];
  replaces: string | null; older: boolean; shadowed_by: string | null; problems: string[];
};
export type Plan = {
  token: string; target: string; target_dir: string; ok: boolean; items: PlanItem[];
  breaks: Record<string, string>;
};
export type Targets = Record<string, string>;

const ORIGINS = new Set(["desarrollo", "workspace", "usuario"]);

export const originLabel = (origin: string) => (ORIGINS.has(origin) ? t(`bloques.origen.${origin}`) : origin);

export function isPackFile(path: string): boolean {
  return path.toLowerCase().endsWith(PACK_SUFFIX);
}

/** Lo soltado sobre la ventana (P82): los `.bppack` van al resumen de instalar y nunca se
 *  convierten en tarjeta de archivo; lo demás, a la pizarra como siempre (D59). */
export function splitDrop<T extends string | { name: string }>(items: T[]): { packs: T[]; others: T[] } {
  const name = (x: T) => (typeof x === "string" ? x : x.name);
  return { packs: items.filter((x) => isPackFile(name(x))), others: items.filter((x) => !isPackFile(name(x))) };
}

export const baseName = (path: string) => path.split(/[\\/]/).pop() ?? path;

/** Por qué no se puede desinstalar (P84), o null si se puede. La lista enseña la copia que se
 *  usa, y esa no se quita mientras otro paquete cargado la pida (como `pack_install.uninstall`). */
export function uninstallBlock(p: InstalledPack): string | null {
  if (!p.removable) return t("bloques.paquetes.no_desinstalable", { origin: originLabel(p.origin).toLowerCase() });
  if (p.required_by.length > 0) {
    const who = p.required_by.join(", ");
    return t(p.required_by.length === 1 ? "bloques.paquetes.lo_pide_uno" : "bloques.paquetes.lo_pide_varios", { who });
  }
  return null;
}

/** Lo que dice el resumen de un paquete además de sus problemas: qué sustituye (P79) y si
 *  otra copia de más prioridad es la que se va a usar (§3). */
export function itemNotes(item: PlanItem, target: string): string[] {
  const out: string[] = [];
  if (item.replaces && item.older) {
    out.push(t("bloques.paquetes.anterior", { installed: item.replaces, version: item.version }));
  } else if (item.replaces) {
    out.push(t("bloques.paquetes.sustituye", { installed: item.replaces }));
  }
  if (item.shadowed_by) {
    out.push(t("bloques.paquetes.ya_esta", { where: originLabel(item.shadowed_by).toLowerCase(),
                                            target: originLabel(target).toLowerCase() }));
  }
  return out;
}

/** Lo que dice el aviso de desinstalar: en el workspace lo pierden todos (P84). */
export function uninstallWarning(p: InstalledPack): string {
  return p.origin === "workspace" ? t("bloques.paquetes.aviso_workspace") : t("bloques.paquetes.aviso");
}
