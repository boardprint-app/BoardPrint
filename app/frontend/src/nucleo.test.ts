// El frontend del núcleo nunca nombra un paquete (docs/PLAN_PAQUETES.md §10 «Núcleo sin
// dominio», P67): la mitad de `app/backend/tests/test_nucleo_sin_dominio.py` que mira
// el TypeScript de `app/frontend/src`, aquí porque el parser de TypeScript entiende el JSX y el
// de Python no. Los `.css` los mira el de Python (vitest los lee vacíos).
//
// Regla: en el código, ningún nombre (`fusionSync`, `TERMINALES_X`, `blockOpenFusion`) lleva
// un paquete como palabra; en un texto (comillas, plantilla, texto de JSX), ninguna palabra en
// minúscula es un paquete (`"fusion.destino"`, `"la brida del robot"`). Lo que hace falta de un
// paquete llega por el catálogo (su `name`, el color de su `[ports]`, P67). Los comentarios sí
// pueden citarlo, y un texto puede hablar del programa con mayúscula («Abrir Fusion»).
import ts from "typescript";
import { describe, expect, it } from "vitest";

// Los mismos que en test_nucleo_sin_dominio.py (NAMES): los paquetes del repo y lo suyo que más
// se nombraba. `robotica_base` cae por `robotica`.
const NAMES = new Set(["fusion", "robotica", "terminales", "brida", "robotarm", "terminals"]);

// {fichero relativo a src: motivo}: el fichero entero. Vacía desde FF 10.9 (el editor de
// terminales, a packs/terminales/ui-src, P68-P71); una nueva necesita su motivo.
const ALLOWED: Record<string, string> = {};

// Sin este fichero: `import.meta.glob` nunca devuelve el que lo llama.
const SOURCES = import.meta.glob(["./**/*.ts", "./**/*.tsx"],
                                 { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** Las palabras de un nombre de código: `blockOpenFusion`, `FUSION_UNITS`. */
function codeWords(name: string): string[] {
  return name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").split(/[^A-Za-z0-9]+/).map((w) => w.toLowerCase());
}

/** Las palabras de un texto, tal cual: «Abrir Fusion» habla del programa, «fusion.pull» no. */
function textWords(text: string): string[] {
  return text.split(/[^\p{L}\p{N}]+/u);
}

type Hit = [line: number, what: string];

function hitsTs(path: string, text: string): Hit[] {
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true,
                                 path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: Hit[] = [];
  const line = (n: ts.Node) => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
  const visit = (n: ts.Node) => {
    if (ts.isIdentifier(n) || ts.isPrivateIdentifier(n)) {
      if (codeWords(n.text).some((w) => NAMES.has(w))) out.push([line(n), n.text]);
    } else if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) || ts.isTemplateHead(n)
               || ts.isTemplateMiddle(n) || ts.isTemplateTail(n) || ts.isJsxText(n)
               || ts.isRegularExpressionLiteral(n)) {
      if (textWords(n.text).some((w) => NAMES.has(w))) out.push([line(n), n.text.trim()]);
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

/** `[(línea, lo que nombra)]` de un fichero `.ts` o `.tsx`. */
const namesOf = hitsTs;

const rel = (p: string) => p.replace(/^\.\//, "");

describe("núcleo sin dominio (P67)", () => {
  it("el frontend del núcleo nunca nombra un paquete", () => {
    const bad = Object.entries(SOURCES).filter(([p]) => !(rel(p) in ALLOWED))
      .flatMap(([p, text]) => namesOf(p, text).map(([l, w]) => `${rel(p)}:${l}: ${JSON.stringify(w)}`));
    expect(bad, "el núcleo nombra un paquete; si es a propósito, va en ALLOWED con su motivo").toEqual([]);
  });

  it("la regla ve lo que tiene que ver", () => {
    const src = [
      "// un comentario cita fusion: vale",
      "/** y un docstring, terminales */",
      "import { fusionSync } from './x';",
      "const a = 'fusion.destino', b = `Abrir Fusion`, c = 'la brida del robot';",
      "const TERMINALES_X = 1; const terminalBlock = 2; const r = /robotarm/;",
      "const el = <button className=\"block-open-robotica\">Abrir Fusion</button>;",
      "const ok = <p>Terminales/Clientes · Brida ñ</p>;",
    ].join("\n");
    expect(namesOf("x.tsx", src).map(([, w]) => w)).toEqual(
      ["fusionSync", "fusion.destino", "la brida del robot", "TERMINALES_X", "/robotarm/",
       "block-open-robotica"]);
  });

  it("cada excepción dice por qué y sigue haciendo falta", () => {
    for (const [p, why] of Object.entries(ALLOWED)) {
      expect(why.trim(), p).not.toBe("");
      const text = SOURCES[`./${p}`];
      expect(text, `${p} ya no existe: quítalo de ALLOWED`).toBeDefined();
      expect(namesOf(p, text).length, `${p} ya no nombra un paquete: quítalo de ALLOWED`).toBeGreaterThan(0);
    }
  });
});
