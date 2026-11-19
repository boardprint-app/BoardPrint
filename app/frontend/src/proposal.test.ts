// Cómo se enseña una propuesta (D75, 2A): el diff por palabras y la vuelta de la píldora.
import { describe, expect, it } from "vitest";
import { brief, cycle, isIdList, listDiff, tabFit, wordDiff } from "./proposal";

const show = (before: string, after: string) =>
  wordDiff(before, after).map((s) => (s.kind === "same" ? s.text : s.kind === "del" ? `[-${s.text}]` : `{+${s.text}}`)).join("");

describe("wordDiff", () => {
  it("marca lo quitado y lo nuevo, y deja lo demás", () => {
    expect(show("El soporte va a la placa del bastidor.", "El soporte va a la placa EN 10025 S275.")).toBe(
      "El soporte va a la placa [-del bastidor.]{+EN 10025 S275.}");
  });
  it("juntar los dos textos da siempre el de antes y el de después", () => {
    const segs = wordDiff("uno dos tres cuatro", "uno tres cinco cuatro seis");
    expect(segs.filter((s) => s.kind !== "ins").map((s) => s.text).join("")).toBe("uno dos tres cuatro");
    expect(segs.filter((s) => s.kind !== "del").map((s) => s.text).join("")).toBe("uno tres cinco cuatro seis");
  });
  it("de vacío a algo es todo nuevo, y al revés todo quitado", () => {
    expect(show("", "hola mundo")).toBe("{+hola mundo}");
    expect(show("hola", "")).toBe("[-hola]");
  });
  it("iguales no marca nada", () => {
    expect(wordDiff("igual que antes", "igual que antes")).toEqual([{ kind: "same", text: "igual que antes" }]);
  });
  it("un texto enorme se da entero como quitado y puesto", () => {
    const big = Array.from({ length: 600 }, (_, i) => `p${i}`).join(" ");
    expect(wordDiff(big, big + " más").map((s) => s.kind)).toEqual(["del", "ins"]);
  });
});

describe("cycle", () => {
  it("da la vuelta en los dos sentidos", () => {
    expect([cycle(3, 2, 1), cycle(3, 0, -1), cycle(3, 1, 1), cycle(0, 0, 1)]).toEqual([0, 2, 2, 0]);
  });
});

// Papeles propuestos (D177; plan §10): el diff de una lista de nodos va por `id`.
describe("listDiff", () => {
  const adaptador = { id: "adaptador", modulo: "adaptador", padre: "raiz", params: { iso: "ISO 50" } };
  const bastidor = { id: "bastidor", modulo: "placa", padre: "adaptador", en: "cara",
                     params: { largo: 260, ancho: 80, espesor: 8, material: "al6061" } };
  const ventosa = { id: "ventosa_b", modulo: "ventosa", padre: "bastidor", en: "cara", params: { d: 30 } };
  const camara = { id: "camara", modulo: "comercial", padre: "bastidor", en: "cara", params: { masa: 0.2 } };
  const now = [adaptador, bastidor, ventosa];

  it("lo añadido, lo quitado y lo cambiado, cada uno por su id", () => {
    const next = [adaptador, { ...bastidor, params: { ...bastidor.params, espesor: 10 },
                               componentes: ["terminal:1/placa:1"] }, camara];
    const d = listDiff(now, next)!;
    expect(d.unchanged).toBe(1);
    expect(d.items.map((i) => [i.kind, i.id])).toEqual([["changed", "bastidor"], ["added", "camara"], ["removed", "ventosa_b"]]);
    const ch = d.items[0];
    if (ch.kind !== "changed") throw new Error("bastidor tenía que cambiar");
    // Dentro de `params`, solo el parámetro que cambia; `componentes`, lo que entra.
    expect(ch.fields).toEqual([
      { field: "params", kind: "keys", keys: [{ key: "espesor", before: 8, after: 10 }] },
      { field: "componentes", kind: "items", added: ["terminal:1/placa:1"], removed: [] },
    ]);
  });
  it("cambiar el orden no es cambiar nada: se casan por id, no por posición", () => {
    expect(listDiff(now, [ventosa, adaptador, bastidor])).toEqual({ items: [], unchanged: 3 });
  });
  it("un id que pasa a otro sitio de la lista con otro contenido sale como cambiado, no como quitado y añadido", () => {
    const d = listDiff(now, [{ ...ventosa, padre: "adaptador" }, adaptador, bastidor])!;
    expect(d.items).toEqual([{ id: "ventosa_b", kind: "changed",
                               fields: [{ field: "padre", kind: "value", before: "bastidor", after: "adaptador" }] }]);
  });
  it("el orden de las claves de un nodo no cuenta", () => {
    const { params, ...rest } = bastidor;
    expect(listDiff(now, [adaptador, { params: { material: "al6061", espesor: 8, ancho: 80, largo: 260 }, ...rest }, ventosa])!
      .items).toEqual([]);
  });
  it("un campo quitado y una clave quitada se ven como quitados", () => {
    const { en: _en, ...sinEn } = bastidor;
    const d = listDiff(now, [adaptador, { ...sinEn, params: { largo: 260, ancho: 80, espesor: 8 } }, ventosa])!;
    const ch = d.items[0];
    if (ch.kind !== "changed") throw new Error("bastidor tenía que cambiar");
    expect(ch.fields).toEqual([
      { field: "en", kind: "value", before: "cara", after: undefined },
      { field: "params", kind: "keys", keys: [{ key: "material", before: "al6061", after: undefined }] },
    ]);
  });
  it("de nada a una lista, todo añadido; a una lista vacía, todo quitado", () => {
    expect(listDiff(undefined, now)!.items.map((i) => i.kind)).toEqual(["added", "added", "added"]);
    expect(listDiff([], now)!.items.length).toBe(3);
    expect(listDiff(now, [])!.items.map((i) => i.kind)).toEqual(["removed", "removed", "removed"]);
  });
  it("lo que no es una lista de objetos con id distinto se enseña como hasta ahora", () => {
    expect(listDiff(8, 10)).toBeNull();
    expect(listDiff(["a"], ["a", "b"])).toBeNull();
    expect(listDiff([{ nombre: "abierto" }], [{ nombre: "cerrado" }])).toBeNull();      // sin id
    expect(listDiff(now, [adaptador, adaptador])).toBeNull();                          // id repetido
    expect(isIdList([{ id: 1 }, { id: 2 }])).toBe(true);
    expect(isIdList([])).toBe(false);
  });
});

describe("brief", () => {
  it("se lee en una línea, nunca como JSON", () => {
    expect(brief({ x: 0, y: 12.5, giro: 90 })).toBe("x: 0, y: 12,5, giro: 90");
    expect(brief(["terminal:1/placa:1", "terminal:1/tapa:1"])).toBe("terminal:1/placa:1, terminal:1/tapa:1");
    expect(brief(undefined)).toBe("—");
    expect(brief(true)).toBe("sí");
    expect(brief({ params: { d: 30 }, efector: true })).toBe("params: (d: 30), efector: sí");
  });
});

describe("tabFit: el recuadro de una propuesta cabe en la ventana (prueba de punta a punta de FF 4.6)", () => {
  // La propuesta de un árbol de 4 nodos medía ~600 px debajo de un bloque a media pantalla:
  // *Aceptar* quedaba fuera por abajo. El sitio es el de la pizarra entre la barra de arriba y
  // la de abajo (`measureChrome`); aquí, la ventana de 900 px con 8 de margen.
  const A = { top: 8, bottom: 892 };
  it("debajo, tal cual, si cabe", () => {
    expect(tabFit(100, 300, 400, A)).toEqual({ above: false, maxHeight: null });
  });
  it("encima si debajo no cabe y encima sí", () => {
    expect(tabFit(700, 800, 400, A)).toEqual({ above: true, maxHeight: null });
  });
  it("si no cabe en ningún lado, en el lado con más sitio y con tope (en px de la tarjeta)", () => {
    const f = tabFit(350, 580, 600, A);
    expect(f.above).toBe(true);                         // 350 − 12 − 8 = 330 > 900 − 8 − 592 = 300
    expect(f.maxHeight).toBe(330);
    expect(tabFit(350, 580, 600, A, 0.5).maxHeight).toBe(660);   // a escala 0,5
  });
  it("nunca debajo de la barra de arriba ni encima de la de abajo", () => {
    expect(tabFit(300, 500, 250, { top: 62, bottom: 780 })).toEqual({ above: false, maxHeight: null });
    expect(tabFit(300, 600, 250, { top: 62, bottom: 780 })).toEqual({ above: true, maxHeight: 226 });
  });
  it("sin sitio ni encima ni debajo (un bloque que llena la vista), encima de la parte de abajo del elemento, dentro de la pizarra", () => {
    // Visto en el navegador: con el mínimo debajo del bloque, *Aceptar* volvía a caer fuera.
    expect(tabFit(20, 880, 600, A)).toEqual({ above: false, maxHeight: 160, top: 892 - 160 });
    expect(tabFit(178, 746, 600, { top: 94, bottom: 832 }, 0.5)).toEqual({ above: false, maxHeight: 320, top: 672 });
  });
});
