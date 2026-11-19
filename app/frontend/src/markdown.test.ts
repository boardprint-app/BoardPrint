// Markdown del chat (plan D173, §10): nunca sale HTML del texto del agente, y lo que el lector
// reconoce sale bien.
import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parseInline, parseMarkdown } from "./markdown";
import { Markdown } from "./ChatMarkdown";

const html = (text: string) => renderToStaticMarkup(createElement(Markdown, { text }));

describe("nunca sale HTML del texto del agente", () => {
  const ATTACKS = [
    "<script>alert(1)</script>",
    '<img src=x onerror="alert(1)">',
    "**<b onmouseover=alert(1)>negrita</b>**",
    "| a | b |\n|---|---|\n| <iframe src=//x> | `<svg onload=alert(1)>` |",
    "- <a href=javascript:alert(1)>enlace</a>",
    "```html\n<script>alert(1)</script>\n```",
    "[pincha](javascript:alert(1))",
  ];
  // Las únicas etiquetas que salen son las del lector, y sin más atributos que los suyos.
  const OURS = new Set(["div", "p", "strong", "em", "code", "br", "pre", "ul", "ol", "li", "hr",
                        "table", "thead", "tbody", "tr", "th", "td"]);
  for (const text of ATTACKS) {
    it(JSON.stringify(text), () => {
      const out = html(text);
      for (const [, name, attrs] of out.matchAll(/<\/?([a-zA-Z0-9]+)([^>]*)>/g)) {
        expect(OURS.has(name.toLowerCase()), `etiqueta <${name}>`).toBe(true);
        expect(attrs.replace(/\s(class|style|start)="[^"]*"/g, "").trim(), `atributos de <${name}>`).toBe("");
      }
      // Lo que parecía HTML se ve como texto.
      if (text.includes("<")) expect(out).toContain("&lt;");
    });
  }

  it("el texto se ve tal cual lo escribió el agente", () => {
    expect(html("<script>alert(1)</script>")).toBe("<div class=\"md\"><p>&lt;script&gt;alert(1)&lt;/script&gt;</p></div>");
  });
});

describe("lo que reconoce", () => {
  it("párrafos separados por una línea en blanco, con saltos dentro", () => {
    expect(parseMarkdown("uno\ndos\n\ntres")).toEqual([
      { t: "p", c: ["uno", { t: "br" }, "dos"] },
      { t: "p", c: ["tres"] },
    ]);
  });

  it("negrita, cursiva y código", () => {
    expect(parseInline("la **flecha** es *pequeña* con `L/500`")).toEqual([
      "la ", { t: "b", c: ["flecha"] }, " es ", { t: "i", c: ["pequeña"] }, " con ",
      { t: "code", text: "L/500" },
    ]);
    expect(parseInline("__ok__ y _bien_")).toEqual([{ t: "b", c: ["ok"] }, " y ", { t: "i", c: ["bien"] }]);
  });

  it("no confunde nombres ni cuentas con cursiva", () => {
    expect(parseInline("leer_pizarra y crear_postit")).toEqual(["leer_pizarra y crear_postit"]);
    expect(parseInline("2 * 3 * 4 = 24")).toEqual(["2 * 3 * 4 = 24"]);
    expect(parseInline("**sin cerrar")).toEqual(["**sin cerrar"]);
  });

  it("dentro del código no hay formato", () => {
    expect(parseInline("`**x**`")).toEqual([{ t: "code", text: "**x**" }]);
    expect(parseMarkdown("```py\nx = 2 * 3\n**y**\n```")).toEqual([
      { t: "code", lang: "py", text: "x = 2 * 3\n**y**" },
    ]);
  });

  it("listas con viñetas y numeradas, con sangría", () => {
    expect(parseMarkdown("- uno\n- **dos**\n  - dentro\n\n3. tres\n4. cuatro")).toEqual([
      { t: "ul", items: [
        { c: ["uno"], depth: 0 }, { c: [{ t: "b", c: ["dos"] }], depth: 0 }, { c: ["dentro"], depth: 1 },
      ] },
      { t: "ol", start: 3, items: [{ c: ["tres"], depth: 0 }, { c: ["cuatro"], depth: 0 }] },
    ]);
  });

  it("tablas con alineación, y cada fila con las columnas de la cabecera", () => {
    const [t] = parseMarkdown("| Campo | Valor |\n|:---|---:|\n| flecha | **0,376** mm |\n| límite |");
    expect(t).toEqual({
      t: "table", align: ["left", "right"],
      head: [["Campo"], ["Valor"]],
      rows: [[["flecha"], [{ t: "b", c: ["0,376"] }, " mm"]], [["límite"], []]],
    });
  });

  it("títulos y separador", () => {
    expect(parseMarkdown("## Resumen\n---\nfin")).toEqual([
      { t: "h", level: 2, c: ["Resumen"] }, { t: "hr" }, { t: "p", c: ["fin"] },
    ]);
  });

  it("la tabla se pinta como tabla", () => {
    expect(html("| a | b |\n|---|---|\n| 1 | 2 |")).toContain("<table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>");
  });
});
