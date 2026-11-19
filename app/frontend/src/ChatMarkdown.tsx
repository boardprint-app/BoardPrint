// Pinta el árbol de `markdown.ts` con elementos de React (plan D173): el texto va siempre
// como hijo de texto, que React escapa; nunca `dangerouslySetInnerHTML`.
import { Fragment, type ReactNode } from "react";
import { parseMarkdown, type Block, type Inline } from "./markdown";

function inline(nodes: Inline[]): ReactNode {
  return nodes.map((n, k) => {
    if (typeof n === "string") return <Fragment key={k}>{n}</Fragment>;
    switch (n.t) {
      case "b": return <strong key={k}>{inline(n.c)}</strong>;
      case "i": return <em key={k}>{inline(n.c)}</em>;
      case "code": return <code key={k}>{n.text}</code>;
      case "br": return <br key={k} />;
    }
  });
}

function block(b: Block, k: number): ReactNode {
  switch (b.t) {
    case "p": return <p key={k}>{inline(b.c)}</p>;
    case "h": return <p key={k} className={`md-h md-h${Math.min(b.level, 3)}`}>{inline(b.c)}</p>;
    case "hr": return <hr key={k} />;
    case "code": return <pre key={k} className="md-pre"><code>{b.text}</code></pre>;
    case "ul":
    case "ol": {
      const items = b.items.map((it, j) => (
        <li key={j} style={it.depth ? { marginLeft: it.depth * 16 } : undefined}>{inline(it.c)}</li>
      ));
      return b.t === "ul" ? <ul key={k}>{items}</ul> : <ol key={k} start={b.start}>{items}</ol>;
    }
    case "table":
      return (
        <div key={k} className="md-table">
          <table>
            <thead><tr>{b.head.map((h, j) => (
              <th key={j} style={b.align[j] ? { textAlign: b.align[j]! } : undefined}>{inline(h)}</th>
            ))}</tr></thead>
            <tbody>{b.rows.map((r, j) => (
              <tr key={j}>{r.map((c, m) => (
                <td key={m} style={b.align[m] ? { textAlign: b.align[m]! } : undefined}>{inline(c)}</td>
              ))}</tr>
            ))}</tbody>
          </table>
        </div>
      );
  }
}

export function Markdown({ text }: { text: string }) {
  return <div className="md">{parseMarkdown(text).map(block)}</div>;
}
