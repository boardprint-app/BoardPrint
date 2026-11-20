// Tarjetas de archivo y de carpeta (plan §3, D59, D109, D110, D131-D142): lo puro, sin React.
// La fuente de verdad es el backend (pizarra/files.py, graph.py); aquí solo lo que la interfaz
// necesita saber al momento: si un enchufe acepta a otro mientras se arrastra (D132), qué
// casillas salen marcadas en la vista de una carpeta mientras se edita (D142) y qué dice la
// etiqueta de una flecha a una carpeta (D109). Las reglas son las mismas que en Python.
import { getLanguage, t } from "./i18n";
import type { ExcelName, ExcelWrite } from "./excel";

export const FILE = "archivo";
export const FOLDER = "carpeta";

export type CardKind = "file" | "folder";
/** Lo que el backend cuenta de una tarjeta (`Board.sources_view`, mensaje `blocks`). */
export type SourceView = {
  checked: boolean; ok: boolean; reason: string | null; type: string; hash: string | null;
  size: number; mtime_ns: number; files: number; total: number; peek: string[];
  big: boolean; notice: string | null;
  /** El nombre del archivo (para los menús que no ven la escena: *Tomar de Excel*). */
  name?: string;
  /** Un Excel: sus nombres definidos (PLAN_EXCEL §3.5); null si no es un Excel o aún no se
   *  ha leído. `names_error`: no se pudo leer. */
  names?: ExcelName[] | null; names_error?: string | null;
  /** Un Excel con flechas de escritura o algo elegido (§3.3): qué va a cada nombre y si se
   *  puede escribir la copia; null si no. */
  write?: ExcelWrite | null;
};

// ------------------------------------------------------------------ tipos (D132)
/** ¿Admite una entrada de `input` una salida de `output`? Iguales (D88), salvo `archivo`,
 *  que admite cualquier `archivo.*`. Como `graph.accepts`. */
export function accepts(input: string, output: string): boolean {
  return input === output || (input === FILE && (output === FILE || output.startsWith(FILE + ".")));
}

/** Extensión que se enseña en el icono de un tipo (`archivo.step` → `STEP`). */
export function typeLabel(type: string): string {
  const ext = type.startsWith(FILE + ".") ? type.slice(FILE.length + 1) : "";
  return ext ? ext.toUpperCase().slice(0, 4) : "";
}

// Familia del icono: el color de su banda (artifact «Archivos FF 4.8»).
const FAMILY: Record<string, string> = {
  step: "stp", iges: "stp", igs: "stp", stl: "stp", f3d: "stp",
  pdf: "pdf",
  doc: "doc", docx: "doc", odt: "doc", rtf: "doc",
  xls: "xls", xlsx: "xls", xlsm: "xls", csv: "xls", ods: "xls",
  ppt: "ppt", pptx: "ppt", odp: "ppt",
  png: "img", jpg: "img", gif: "img", webp: "img", svg: "img", bmp: "img", tiff: "img",
};
export function typeFamily(type: string): string {
  return FAMILY[typeLabel(type).toLowerCase()] ?? FAMILY[type.split(".")[1] ?? ""] ?? "gen";
}

/** Tamaño legible, en el formato de la app (coma decimal): 340 kB, 2,4 MB, 112 MB. */
export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["kB", "MB", "GB", "TB"];
  let v = bytes / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  const s = v < 10 ? v.toFixed(1) : Math.round(v).toString();
  const sep = getLanguage() === "en" ? "." : ",";      // la coma decimal, en español
  return `${s.replace(".", sep).replace(/[.,]0$/, "")} ${units[i]}`;
}

/** La tarjeta de archivo conectada a una entrada `archivo…` de un bloque (`inputs`, sus tipos;
 *  `connected`, lo conectado a cada una), que manda sobre su parámetro de archivo (D133), o null. */
export function linkedFile(inputs: Record<string, string>,
                           connected: Record<string, { block: string }> | undefined): string | null {
  const port = Object.entries(inputs).find(([n, type]) => accepts(FILE, type) && connected?.[n]);
  return port ? connected![port[0]].block : null;
}

// ------------------------------------------------------------------ lo que entra (D136, D142)
/** Lo desmarcado de una carpeta: rutas relativas (con `/`) quitadas y patrones por el nombre. */
export type Content = { exclude: string[]; patterns: string[] };
export const EVERYTHING: Content = { exclude: [], patterns: [] };

export function contentOf(raw: unknown): Content {
  const c = (raw ?? {}) as Partial<Content>;
  return {
    exclude: (c.exclude ?? []).map((x) => String(x).replace(/^\/+|\/+$/g, "")),
    patterns: (c.patterns ?? []).map(String).filter((p) => p.trim()),
  };
}

export const isEverything = (c: Content) => !c.exclude.length && !c.patterns.length;

// Patrón de `fnmatch` (*, ?, [abc], [!abc]) a expresión regular.
function globRe(pattern: string): RegExp {
  let re = "";
  for (let i = 0; i < pattern.length; i++) {
    const ch = pattern[i];
    if (ch === "*") re += ".*";
    else if (ch === "?") re += ".";
    else if (ch === "[") {
      const j = pattern.indexOf("]", i + 2);
      if (j < 0) { re += "\\["; continue; }
      let body = pattern.slice(i + 1, j).replace(/\\/g, "\\\\");
      if (body.startsWith("!")) body = "^" + body.slice(1);
      re += `[${body}]`;
      i = j;
    } else re += ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(`^${re}$`, "s");
}

/** ¿Cumple el nombre el patrón? Sin distinguir mayúsculas, como `Content.marks`. */
export function globMatch(name: string, pattern: string): boolean {
  return globRe(pattern.toLowerCase()).test(name.toLowerCase());
}

const under = (rel: string, x: string) => rel === x || rel.startsWith(x + "/");

/** ¿Entra el archivo de ruta relativa `rel`? Como `files.Content.marks`. */
export function marks(rel: string, c: Content): boolean {
  if (c.exclude.some((x) => under(rel, x))) return false;
  if (c.patterns.length) {
    const name = rel.slice(rel.lastIndexOf("/") + 1);
    return c.patterns.some((p) => globMatch(name, p));
  }
  return true;
}

/** ¿Lo deja fuera un patrón, aunque no esté desmarcado? Su casilla no se puede marcar. */
export const outOfPattern = (rel: string, c: Content) =>
  !c.exclude.some((x) => under(rel, x)) && !marks(rel, c);

/** Una entrada de la vista (`GET …/content`): `marked` es `true|false` en un archivo y
 *  `all|none|some` en una subcarpeta (la casilla de tres estados). */
export type Entry = { path: string; kind: "file" | "dir"; size: number; mtime?: number;
                      marked: boolean | "all" | "none" | "some" };

/** Las casillas de la vista con lo marcado de ahora (mientras se edita, sin ir al backend). */
export function markTree(entries: Entry[], c: Content): Entry[] {
  const count = new Map<string, [number, number]>();
  for (const e of entries) {
    if (e.kind !== "file") continue;
    const m = marks(e.path, c);
    for (let p = parentOf(e.path); p; p = parentOf(p)) {
      const n = count.get(p) ?? [0, 0];
      n[m ? 0 : 1]++;
      count.set(p, n);
    }
  }
  return entries.map((e) => {
    if (e.kind === "file") return { ...e, marked: marks(e.path, c) };
    const [yes, no] = count.get(e.path) ?? [0, 0];
    const off = c.exclude.some((x) => under(e.path, x)) || (no > 0 && yes === 0);
    return { ...e, marked: off ? "none" : yes && no ? "some" : "all" };
  });
}

function parentOf(rel: string): string {
  const i = rel.lastIndexOf("/");
  return i < 0 ? "" : rel.slice(0, i);
}

/** Orden de la lista en árbol: cada subcarpeta seguida de lo suyo, subcarpetas antes que
 *  archivos y por nombre en cada nivel (el backend da las subcarpetas de un nivel juntas). */
export function treeOrder(entries: Entry[]): Entry[] {
  const key = (e: Entry) => {
    const parts = e.path.split("/");
    // Cada tramo lleva delante si es carpeta (0) o archivo (1): solo el último puede ser archivo.
    return parts.map((p, i) => `${i < parts.length - 1 || e.kind === "dir" ? 0 : 1}${p.toLowerCase()}`);
  };
  const keys = new Map(entries.map((e) => [e.path, key(e)]));
  return [...entries].sort((a, b) => {
    const ka = keys.get(a.path)!, kb = keys.get(b.path)!;
    for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
      if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
    }
    return ka.length - kb.length;
  });
}

/** Pulsar la casilla de `path`: lo marcado lo quita; lo desmarcado o a medias lo marca entero.
 *  Marcar algo de dentro de una subcarpeta quitada quita esa subcarpeta y desmarca, uno a uno,
 *  sus hermanos de camino (lo demás sigue fuera). Nunca toca los patrones. */
export function toggle(entries: Entry[], c: Content, path: string): Content {
  const now = markTree(entries, c).find((e) => e.path === path);
  if (!now) return c;
  const on = now.marked === true || now.marked === "all";
  if (on) {
    return { ...c, exclude: [...c.exclude.filter((x) => !under(x, path)), path].sort() };
  }
  let exclude = c.exclude.filter((x) => !under(x, path));
  // Una subcarpeta de encima quitada: se cambia por sus hijos que no van hacia `path`.
  for (const top of exclude.filter((x) => under(path, x))) {
    exclude = exclude.filter((x) => x !== top);
    let level = top;
    for (const seg of path.slice(top.length + 1).split("/")) {
      const next = `${level}/${seg}`;
      for (const e of entries) {
        if (parentOf(e.path) === level && e.path !== next) exclude.push(e.path);
      }
      level = next;
    }
  }
  return { ...c, exclude: [...new Set(exclude)].sort() };
}

/** *Nada*: fuera todo lo de primer nivel. *Todo* es `EVERYTHING`. */
export function nothing(entries: Entry[], c: Content): Content {
  return { ...c, exclude: entries.filter((e) => !e.path.includes("/")).map((e) => e.path).sort() };
}

/** Patrones escritos en el campo, separados por espacios, comas o punto y coma. */
export function parsePatterns(text: string): string[] {
  return text.split(/[\s,;]+/).map((p) => p.trim()).filter(Boolean);
}

/** «Entran 9 de 14 archivos · 21 MB». */
export function summary(entries: Entry[], c: Content): { marked: number; total: number; size: number } {
  let marked = 0, total = 0, size = 0;
  for (const e of entries) {
    if (e.kind !== "file") continue;
    total++;
    if (marks(e.path, c)) { marked++; size += e.size; }
  }
  return { marked, total, size };
}

/** Chip de la tarjeta de una carpeta cuando no entra todo (D139): «*.pdf · 9 de 14». */
export function folderChip(c: Content, view: Pick<SourceView, "files" | "total" | "checked"> | undefined): string | null {
  if (isEverything(c)) return null;
  const parts = [c.patterns.join(" "),
                 view?.checked ? t("lienzo.carpeta.de", { files: view.files, total: view.total }) : ""].filter(Boolean);
  return parts.join(" · ") || t("lienzo.carpeta.seleccion");
}

// ------------------------------------------------------------------ salidas a una carpeta (D109)
/** Archivos que da un bloque por su salida `port` (o por todas, con `null`): los campos que
 *  citan un archivo de su carpeta. */
export function outputFiles(outputs: Record<string, Record<string, { file?: string }>> | null | undefined,
                            port: string | null): string[] {
  const names = new Set<string>();
  for (const [p, fields] of Object.entries(outputs ?? {})) {
    if (port !== null && p !== port) continue;
    for (const f of Object.values(fields ?? {})) if (f && typeof f.file === "string") names.add(f.file);
  }
  return [...names].sort();
}

/** Etiqueta de la flecha: cuántos archivos y si alguno sobrescribe. Por defecto, ninguno. */
export function copyLabel(names: string[], overwrite: readonly string[] | undefined): string {
  if (!names.length) return t("lienzo.copia.sus_archivos");
  const over = names.filter((n) => overwrite?.includes(n)).length;
  const archivos = t(names.length === 1 ? "lienzo.copia.archivos_uno" : "lienzo.copia.archivos_varios", { n: names.length });
  return over
    ? t(over === 1 ? "lienzo.copia.sobrescribe_uno" : "lienzo.copia.sobrescribe_varios", { archivos, n: over })
    : t("lienzo.copia.nuevo", { archivos });
}

/** Cambia un archivo entre sobrescribir y archivo nuevo `_n`. */
export function setOverwrite(overwrite: readonly string[] | undefined, name: string, on: boolean): string[] {
  const rest = (overwrite ?? []).filter((n) => n !== name);
  return on ? [...rest, name].sort() : rest;
}

// ------------------------------------------------------------------ previsualizar (D135)
export type PreviewKind = "step" | "pdf" | "image" | "text" | "html";
const PREVIEW: Record<string, PreviewKind> = {
  step: "step", pdf: "pdf",
  png: "image", jpg: "image", gif: "image", webp: "image", svg: "image", bmp: "image",
  txt: "text", md: "text", csv: "text", tsv: "text", json: "text", toml: "text", yaml: "text",
  ini: "text", cfg: "text", log: "text", py: "text", xml: "text",
  html: "html",
};
/** Cómo se previsualiza un archivo de ese tipo, o `null`: Word, Excel, PowerPoint y lo que la
 *  app no sabe pintar solo tienen *Abrir* (D135). */
export function previewKind(type: string): PreviewKind | null {
  return type.startsWith(FILE + ".") ? PREVIEW[type.slice(FILE.length + 1)] ?? null : null;
}

/** Hasta dónde se enseña un texto: más, y solo tiene *Abrir*. */
export const TEXT_PREVIEW_MAX = 2 * 1024 * 1024;

/** Dónde abrir el menú de una tarjeta para que quepa entero en la ventana, con su tamaño
 * medido (crece al abrir *Editar con el agente*). Si es más alto que la ventana, arriba del
 * todo: el menú se desplaza dentro (`max-height` en cards.css). */
export function menuPlace(at: { x: number; y: number }, size: { width: number; height: number },
                          view: { width: number; height: number }, margin = 8): { left: number; top: number } {
  const fit = (p: number, s: number, v: number) => Math.max(margin, Math.min(p, v - s - margin));
  return { left: fit(at.x, size.width, view.width), top: fit(at.y, size.height, view.height) };
}
