// Reglas de las tarjetas de archivo y de carpeta (plan §10, D109, D132, D136, D142): las
// mismas que en Python (test_files.py, test_graph.py), vistas desde la interfaz.
import { describe, expect, it } from "vitest";
import {
  accepts, contentOf, copyLabel, EVERYTHING, fmtSize, folderChip, globMatch, markTree, marks,
  nothing, outOfPattern, outputFiles, previewKind, treeOrder, parsePatterns, setOverwrite, summary, toggle, typeFamily,
  typeLabel, menuPlace, linkedFile, type Content, type Entry,
} from "./cards";

describe("tipos por prefijo (D132)", () => {
  it("archivo acepta cualquier archivo.*", () => {
    expect(accepts("archivo", "archivo.step")).toBe(true);
    expect(accepts("archivo", "archivo.pdf")).toBe(true);
    expect(accepts("archivo", "archivo")).toBe(true);
  });
  it("archivo.step nunca acepta archivo.pdf ni archivo", () => {
    expect(accepts("archivo.step", "archivo.step")).toBe(true);
    expect(accepts("archivo.step", "archivo.pdf")).toBe(false);
    expect(accepts("archivo.step", "archivo")).toBe(false);
  });
  it("carpeta solo carpetas, y el resto, tipos idénticos", () => {
    expect(accepts("carpeta", "carpeta")).toBe(true);
    expect(accepts("carpeta", "archivo.pdf")).toBe(false);
    expect(accepts("archivo", "carpeta")).toBe(false);
    expect(accepts("acme.pieza", "acme.pieza")).toBe(true);
    expect(accepts("archivo", "archivos.pdf")).toBe(false);
  });
  it("el icono dice la extensión y su familia", () => {
    expect(typeLabel("archivo.step")).toBe("STEP");
    expect(typeLabel("archivo")).toBe("");
    expect(typeFamily("archivo.step")).toBe("stp");
    expect(typeFamily("archivo.docx")).toBe("doc");
    expect(typeFamily("archivo.raro")).toBe("gen");
  });
});

describe("tamaño legible", () => {
  it("con coma decimal y sin decimales de más", () => {
    expect(fmtSize(512)).toBe("512 B");
    expect(fmtSize(340 * 1024)).toBe("340 kB");
    expect(fmtSize(2.4 * 1024 ** 2)).toBe("2,4 MB");
    expect(fmtSize(112 * 1024 ** 2)).toBe("112 MB");
    expect(fmtSize(2 * 1024 ** 2)).toBe("2 MB");
  });
});

// Carpeta de ejemplo, en el orden del recorrido del backend (`files.tree`).
const TREE: Entry[] = [
  { path: "Schunk", kind: "dir", size: 0, marked: "all" },
  { path: "Schunk/EGK", kind: "dir", size: 0, marked: "all" },
  { path: "Schunk/EGK/manual.pdf", kind: "file", size: 10, marked: true },
  { path: "Schunk/EGK/pinza.step", kind: "file", size: 20, marked: true },
  { path: "Schunk/precios.xlsx", kind: "file", size: 5, marked: true },
  { path: "lista.pdf", kind: "file", size: 1, marked: true },
];
const state = (c: Content) => Object.fromEntries(markTree(TREE, c).map((e) => [e.path, e.marked]));

describe("lo que entra de una carpeta (D136, D142)", () => {
  it("sin marcar nada entra todo, subcarpetas incluidas", () => {
    expect(Object.values(state(EVERYTHING)).every((m) => m === true || m === "all")).toBe(true);
    expect(summary(TREE, EVERYTHING)).toEqual({ marked: 4, total: 4, size: 36 });
  });
  it("desmarcar una subcarpeta quita todo lo suyo", () => {
    const c = toggle(TREE, EVERYTHING, "Schunk");
    expect(c.exclude).toEqual(["Schunk"]);
    const s = state(c);
    expect([s["Schunk"], s["Schunk/EGK"], s["Schunk/EGK/manual.pdf"], s["lista.pdf"]])
      .toEqual(["none", "none", false, true]);
  });
  it("marcar un archivo dentro de una subcarpeta quitada deja lo demás fuera", () => {
    const c = toggle(TREE, toggle(TREE, EVERYTHING, "Schunk"), "Schunk/EGK/manual.pdf");
    expect(c.exclude).toEqual(["Schunk/EGK/pinza.step", "Schunk/precios.xlsx"]);
    const s = state(c);
    expect([s["Schunk"], s["Schunk/EGK"], s["Schunk/EGK/manual.pdf"], s["Schunk/EGK/pinza.step"]])
      .toEqual(["some", "some", true, false]);
  });
  it("una subcarpeta a medias se marca entera al pulsarla", () => {
    const half = toggle(TREE, EVERYTHING, "Schunk/precios.xlsx");
    expect(state(half)["Schunk"]).toBe("some");
    expect(toggle(TREE, half, "Schunk").exclude).toEqual([]);
  });
  it("desmarcar algo ya cubierto por su carpeta no deja rutas de más", () => {
    const half = toggle(TREE, EVERYTHING, "Schunk/EGK/manual.pdf");
    const c = toggle(TREE, toggle(TREE, half, "Schunk"), "Schunk");   // a medias → entera → fuera
    expect(c.exclude).toEqual(["Schunk"]);
  });
  it("el patrón va por el nombre y sin distinguir mayúsculas", () => {
    const c: Content = { exclude: [], patterns: ["*.PDF"] };
    expect(marks("Schunk/EGK/manual.pdf", c)).toBe(true);
    expect(marks("Schunk/EGK/pinza.step", c)).toBe(false);
    expect(outOfPattern("Schunk/EGK/pinza.step", c)).toBe(true);
    expect(globMatch("EGK-40.pdf", "egk-[0-9]?.pdf")).toBe(true);
    expect(globMatch("EGK-40.pdf", "egk-[!0-9]*.pdf")).toBe(false);
    expect(summary(TREE, c)).toEqual({ marked: 2, total: 4, size: 11 });
  });
  it("pulsar una casilla nunca toca los patrones", () => {
    const c = toggle(TREE, { exclude: [], patterns: ["*.pdf"] }, "lista.pdf");
    expect(c).toEqual({ exclude: ["lista.pdf"], patterns: ["*.pdf"] });
  });
  it("la lista en árbol pone cada subcarpeta encima de lo suyo", () => {
    const walk: Entry[] = [   // como lo da os.walk: las subcarpetas de un nivel, juntas
      { path: "Schunk", kind: "dir", size: 0, marked: "all" },
      { path: "lista.pdf", kind: "file", size: 1, marked: true },
      { path: "Schunk/EGK", kind: "dir", size: 0, marked: "all" },
      { path: "Schunk/precios.xlsx", kind: "file", size: 5, marked: true },
      { path: "Schunk/EGK/manual.pdf", kind: "file", size: 10, marked: true },
    ];
    expect(treeOrder(walk).map((e) => e.path)).toEqual(
      ["Schunk", "Schunk/EGK", "Schunk/EGK/manual.pdf", "Schunk/precios.xlsx", "lista.pdf"]);
  });
  it("Nada deja fuera lo de primer nivel", () => {
    const c = nothing(TREE, EVERYTHING);
    expect(c.exclude).toEqual(["Schunk", "lista.pdf"]);
    expect(summary(TREE, c).marked).toBe(0);
  });
  it("los patrones se escriben separados y se leen de la tarjeta", () => {
    expect(parsePatterns(" *.pdf, *.step;*.xlsx ")).toEqual(["*.pdf", "*.step", "*.xlsx"]);
    expect(contentOf({ exclude: ["/Schunk/"], patterns: ["", "*.pdf"] }))
      .toEqual({ exclude: ["Schunk"], patterns: ["*.pdf"] });
    expect(contentOf(undefined)).toEqual(EVERYTHING);
  });
  it("el chip solo sale cuando no entra todo", () => {
    expect(folderChip(EVERYTHING, { files: 4, total: 4, checked: true })).toBeNull();
    expect(folderChip({ exclude: [], patterns: ["*.pdf"] }, { files: 9, total: 14, checked: true }))
      .toBe("*.pdf · 9 de 14");
    expect(folderChip({ exclude: ["a"], patterns: [] }, undefined)).toBe("selección");
  });
});

describe("salidas a una carpeta (D109)", () => {
  const outputs = {
    tabla: { lista: { file: "lista_materiales.xlsx" }, piezas: {} },
    informe: { html: { file: "informe.html" }, captura: { file: "lista_materiales.xlsx" } },
  };
  it("los archivos de una salida, o de todas", () => {
    expect(outputFiles(outputs, "tabla")).toEqual(["lista_materiales.xlsx"]);
    expect(outputFiles(outputs, null)).toEqual(["informe.html", "lista_materiales.xlsx"]);
    expect(outputFiles(null, null)).toEqual([]);
  });
  it("por defecto nunca sobrescribe", () => {
    expect(copyLabel(["a.xlsx", "b.html"], undefined)).toBe("2 archivos · nuevo _n");
    expect(copyLabel(["a.xlsx", "b.html"], ["b.html"])).toBe("2 archivos · 1 sobrescribe");
    expect(copyLabel([], [])).toBe("copia sus archivos");
  });
  it("sobrescribir solo cambia ese archivo", () => {
    expect(setOverwrite(["a"], "b", true)).toEqual(["a", "b"]);
    expect(setOverwrite(["a", "b"], "a", false)).toEqual(["b"]);
    expect(setOverwrite(undefined, "a", false)).toEqual([]);
  });
});

describe("previsualizar (D135)", () => {
  it("STEP, PDF, imágenes, texto y HTML sí", () => {
    expect(previewKind("archivo.step")).toBe("step");
    expect(previewKind("archivo.pdf")).toBe("pdf");
    expect(previewKind("archivo.png")).toBe("image");
    expect(previewKind("archivo.jpg")).toBe("image");
    expect(previewKind("archivo.csv")).toBe("text");
    expect(previewKind("archivo.html")).toBe("html");
  });
  it("Word, Excel y PowerPoint nunca, ni lo que no se conoce", () => {
    for (const t of ["archivo.docx", "archivo.doc", "archivo.xlsx", "archivo.xls", "archivo.pptx",
                     "archivo.ppt", "archivo.f3d", "archivo.tiff", "archivo", "carpeta"]) {
      expect(previewKind(t)).toBeNull();
    }
  });
});

describe("el menú de una tarjeta cabe en la ventana (prueba de punta a punta de FF 4.6)", () => {
  // El menú de un archivo, con *Leer* y *Editar con el agente*, mide ~430 px y crece al abrir
  // *Editar*: con la altura supuesta de antes (370) el botón quedaba fuera por abajo.
  const view = { width: 1440, height: 900 };
  it("abre donde se pulsa si cabe", () => {
    expect(menuPlace({ x: 300, y: 200 }, { width: 268, height: 430 }, view)).toEqual({ left: 300, top: 200 });
  });
  it("sube lo justo para que quepa su altura real, con margen", () => {
    expect(menuPlace({ x: 500, y: 480 }, { width: 268, height: 540 }, view)).toEqual({ left: 500, top: 900 - 540 - 8 });
  });
  it("y se pega a la izquierda si no cabe a la derecha", () => {
    expect(menuPlace({ x: 1400, y: 10 }, { width: 268, height: 100 }, view).left).toBe(1440 - 268 - 8);
  });
  it("más alto que la ventana: arriba del todo (el menú se desplaza dentro)", () => {
    expect(menuPlace({ x: 10, y: 500 }, { width: 268, height: 1200 }, view).top).toBe(8);
  });
});

describe("STEP de referencia con su tarjeta (D133)", () => {
  it("con una tarjeta conectada a su entrada de archivo, el bloque enseña esa tarjeta, no «Ningún archivo»", () => {
    const inputs = { step: "archivo.step", carga: "kg" };
    expect(linkedFile(inputs, { step: { block: "card1" } })).toBe("card1");
    expect(linkedFile(inputs, {})).toBeNull();
    expect(linkedFile(inputs, { carga: { block: "b2" } })).toBeNull();
  });
});
