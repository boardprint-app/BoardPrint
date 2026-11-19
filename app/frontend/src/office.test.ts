// Office con el agente (D176): qué tarjetas tienen cada acción y qué lleva cada encargo.
import { describe, expect, it } from "vitest";
import { blockChoices, canEdit, canRead, connectedBlocks, editBrief, fileName, newFileBrief, readToBlock,
         readToPostits } from "./office";

const card = { id: "c1", name: "oferta.docx" };

describe("qué se puede leer y editar con el agente", () => {
  it("lee PDF, Word, Excel y PowerPoint; edita solo Word, Excel y PowerPoint de ahora", () => {
    for (const t of ["archivo.pdf", "archivo.docx", "archivo.xlsx", "archivo.pptx"]) expect(canRead(t)).toBe(true);
    for (const t of ["archivo.docx", "archivo.xlsx", "archivo.pptx"]) expect(canEdit(t)).toBe(true);
    expect(canEdit("archivo.pdf")).toBe(false);
    for (const t of ["archivo.doc", "archivo.step", "archivo", "carpeta"]) {
      expect(canRead(t)).toBe(false);
      expect(canEdit(t)).toBe(false);
    }
  });
});

describe("los encargos", () => {
  it("a post-its y a un bloque piden la fuente archivo de la tarjeta con su where (D19)", () => {
    for (const text of [readToPostits(card), readToBlock(card, { id: "b9", title: "Ménsula" })]) {
      expect(text).toContain('ref "archivo:c1"');
      expect(text).toContain("where");
      expect(text).toContain("leer_archivo");
    }
    expect(readToPostits(card)).toContain("crear_postit");
    const block = readToBlock(card, { id: "b9", title: "Ménsula" });
    expect(block).toContain("proponer_cambio");
    expect(block).toContain("bloque:b9");
  });

  it("editar lleva lo que pide el ingeniero y dice que el original no se toca", () => {
    const text = editBrief(card, "  el plazo pasa a dos semanas ");
    expect(text).toContain("editar_archivo");
    expect(text).toContain("el plazo pasa a dos semanas");
    expect(text).toMatch(/original no se toca/);
  });

  it("nuevo archivo dice el tipo, y solo con anclas que parta de ellas", () => {
    expect(newFileBrief("xlsx", "la lista", false)).toContain("tipo xlsx");
    expect(newFileBrief("xlsx", "la lista", false)).not.toContain("anclados");
    expect(newFileBrief("pptx", "la revisión", true)).toContain("anclados");
  });
});

describe("a la entrada de un bloque", () => {
  const blocks = { b1: {}, b2: {}, b3: {} };
  const els = [
    { id: "a1", customData: { kind: "connection" }, startBinding: { elementId: "c1" }, endBinding: { elementId: "b2" } },
    { id: "a2", customData: { kind: "connection" }, startBinding: { elementId: "c1" }, endBinding: { elementId: "b2" } },
    { id: "a3", customData: { kind: "connection" }, startBinding: { elementId: "c1" }, endBinding: { elementId: "b3" }, isDeleted: true },
    { id: "a4", customData: { kind: "connection" }, startBinding: { elementId: "otra" }, endBinding: { elementId: "b1" } },
    { id: "a5", customData: { kind: "arrow" }, startBinding: { elementId: "c1" }, endBinding: { elementId: "b1" } },
  ];

  it("solo cuenta las conexiones vivas que salen de la tarjeta hacia un bloque", () => {
    expect(connectedBlocks(els, "c1", blocks)).toEqual(["b2"]);
  });

  it("los conectados van primero y marcados; el resto, por título", () => {
    const all = [{ id: "b1", title: "Viga" }, { id: "b2", title: "Tornillos" }, { id: "b3", title: "Ménsula" }];
    expect(blockChoices(all, ["b2"]).map((b) => [b.id, b.connected])).toEqual([["b2", true], ["b3", false], ["b1", false]]);
    expect(blockChoices(all, [], 2)).toHaveLength(2);
  });
});

it("el nombre de la copia sale de su ruta guardada, relativa o absoluta", () => {
  expect(fileName("Proyecto/archivos/oferta_1.docx")).toBe("oferta_1.docx");
  expect(fileName("C:\\ofertas\\oferta_1.docx")).toBe("oferta_1.docx");
});
