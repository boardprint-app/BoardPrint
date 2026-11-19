// Lector de Markdown propio y mínimo para el chat del agente (plan D173): párrafos, títulos,
// **negrita**, *cursiva*, `código`, bloques de código, listas, tablas y separadores. Da un
// árbol de nodos que pinta `Markdown.tsx` con elementos de React: nada de lo que escribe el
// agente llega nunca a ser HTML (un `<script>` sale como texto). Lo que no reconoce (enlaces,
// citas, HTML) se queda como texto tal cual. Es puro: sin DOM ni React, con su test.

export type Inline =
  | string
  | { t: "b"; c: Inline[] }
  | { t: "i"; c: Inline[] }
  | { t: "code"; text: string }
  | { t: "br" };

export type Align = "left" | "center" | "right" | null;

export type Block =
  | { t: "p"; c: Inline[] }
  | { t: "h"; level: number; c: Inline[] }
  | { t: "ul"; items: ListItem[] }
  | { t: "ol"; start: number; items: ListItem[] }
  | { t: "code"; lang: string; text: string }
  | { t: "table"; align: Align[]; head: Inline[][]; rows: Inline[][][] }
  | { t: "hr" };

/** Un elemento de lista; `depth` es su sangría (0, 1, …): las sublistas se pintan sangradas. */
export type ListItem = { c: Inline[]; depth: number };

const FENCE = /^\s{0,3}(`{3,}|~{3,})\s*([\w+-]*)/;
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** El texto del agente en bloques. */
export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push({ t: "p", c: parseInline(para.join("\n")) });
    para = [];
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      flush();
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      flush();
      const mark = fence[1];
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith(mark)) body.push(lines[i++]);
      i++;                                   // la valla de cierre (si no la hay, hasta el final)
      out.push({ t: "code", lang: fence[2] ?? "", text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      out.push({ t: "h", level: heading[1].length, c: parseInline(heading[2]) });
      i++;
      continue;
    }
    if (HR.test(line)) {
      flush();
      out.push({ t: "hr" });
      i++;
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])
        && lines[i + 1].includes("-")) {
      flush();
      const head = splitRow(line);
      const align = splitRow(lines[i + 1]).map(alignOf);
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        const cells = splitRow(lines[i++]);
        // Todas las filas con las columnas de la cabecera: ni de más ni de menos.
        rows.push(head.map((_h, k) => parseInline(cells[k] ?? "")));
      }
      out.push({ t: "table", align: head.map((_h, k) => align[k] ?? null),
                 head: head.map((h) => parseInline(h)), rows });
      continue;
    }
    const bullet = BULLET.exec(line);
    const numbered = bullet ? null : NUMBERED.exec(line);
    if (bullet || numbered) {
      flush();
      const ordered = !!numbered;
      const base = (bullet ?? numbered)![1].length;
      const items: ListItem[] = [];
      let text: string[] = [];
      let depth = 0;
      const push = () => {
        if (text.length) items.push({ c: parseInline(text.join("\n")), depth });
        text = [];
      };
      while (i < lines.length) {
        const l = lines[i];
        const b = BULLET.exec(l);
        const n = b ? null : NUMBERED.exec(l);
        const m = b ?? n;
        if (m && !HR.test(l)) {
          push();
          depth = Math.max(0, Math.floor((m[1].length - base) / 2));
          text = [n ? n[3] : b![2]];
        } else if (l.trim() && /^\s+/.test(l) && text.length) {
          text.push(l.trim());               // continuación de un elemento, sangrada
        } else {
          break;
        }
        i++;
      }
      push();
      out.push(ordered ? { t: "ol", start: Number(numbered![2]), items } : { t: "ul", items });
      continue;
    }
    para.push(line);
    i++;
  }
  flush();
  return out;
}

/** Las celdas de una fila de tabla, sin las barras de los extremos. `\|` es una barra dentro
 *  de una celda. */
function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells: string[] = [];
  let cur = "";
  for (let k = 0; k < s.length; k++) {
    if (s[k] === "\\" && s[k + 1] === "|") {
      cur += "|";
      k++;
    } else if (s[k] === "|") {
      cells.push(cur.trim());
      cur = "";
    } else {
      cur += s[k];
    }
  }
  cells.push(cur.trim());
  return cells;
}

function alignOf(sep: string): Align {
  const s = sep.trim();
  const l = s.startsWith(":"), r = s.endsWith(":");
  return l && r ? "center" : r ? "right" : l ? "left" : null;
}

const ESCAPABLE = "\\`*_{}[]()#+-.!|<>~";
const isWord = (ch: string | undefined) => !!ch && /[\p{L}\p{N}]/u.test(ch);

/** El texto de un párrafo, una celda o un elemento de lista, con su formato. */
export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let text = "";
  const pushText = () => {
    if (text) out.push(text);
    text = "";
  };
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === "\\" && i + 1 < src.length && ESCAPABLE.includes(src[i + 1])) {
      text += src[i + 1];
      i += 2;
      continue;
    }
    if (ch === "\n") {
      pushText();
      out.push({ t: "br" });
      i++;
      continue;
    }
    if (ch === "`") {
      let run = 1;
      while (src[i + run] === "`") run++;
      const fence = "`".repeat(run);
      const end = src.indexOf(fence, i + run);
      if (end > i + run) {
        pushText();
        out.push({ t: "code", text: src.slice(i + run, end).replace(/\n/g, " ") });
        i = end + run;
        continue;
      }
      text += fence;
      i += run;
      continue;
    }
    if ((ch === "*" || ch === "_") && src[i + 1] === ch) {
      const mark = ch + ch;
      const end = closing(src, mark, i + 2);
      if (end !== -1 && (ch === "*" || !isWord(src[i - 1]))) {
        pushText();
        out.push({ t: "b", c: parseInline(src.slice(i + 2, end)) });
        i = end + 2;
        continue;
      }
      text += mark;
      i += 2;
      continue;
    }
    if (ch === "*" || ch === "_") {
      // `_` solo como cursiva al borde de una palabra: `leer_pizarra` se queda como está.
      const end = closing(src, ch, i + 1);
      if (end !== -1 && (ch === "*" || (!isWord(src[i - 1]) && !isWord(src[end + 1])))) {
        pushText();
        out.push({ t: "i", c: parseInline(src.slice(i + 1, end)) });
        i = end + 1;
        continue;
      }
    }
    text += ch;
    i++;
  }
  pushText();
  return out;
}

/** Dónde se cierra `mark` abierto antes de `from`: contenido no vacío, que no empieza ni acaba
 *  en espacio (así `2 * 3 * 4` no es cursiva), y sin cruzar un salto de párrafo. -1 si no. */
function closing(src: string, mark: string, from: number): number {
  if (from >= src.length || /\s/.test(src[from])) return -1;
  let k = from;
  while (k < src.length) {
    const at = src.indexOf(mark, k);
    if (at === -1) return -1;
    const single = mark.length === 1;
    // Un `*` suelto no cierra en medio de un `**`.
    if (single && (src[at + 1] === mark || src[at - 1] === mark)) {
      k = at + 2;
      continue;
    }
    if (at > from && !/\s/.test(src[at - 1])) return at;
    k = at + 1;
  }
  return -1;
}
