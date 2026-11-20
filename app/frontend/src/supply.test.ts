// *Dónde comprar* y los proveedores en la interfaz (docs/PLAN_APROVISIONAMIENTO.md §6): un precio
// o un plazo desconocido se enseña como desconocido, nunca como 0, y un campo numérico vacío de
// *Añadir oferta* se manda como null; el orden de los proveedores es el que deja el usuario.
import { describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import {
  emptyOfferDraft, eventText, leadText, moveItem, offerPayload, priceText, providersChanged, resultText,
  toggleType, usdText, type OfferDraft, type SearchJob,
} from "./supply";

const draft = (patch: Partial<OfferDraft>): OfferDraft => ({ ...emptyOfferDraft(), proveedor: "RS", ...patch });

describe("leer una oferta", () => {
  it("el precio con su cantidad, y sin precio nunca es 0", () => {
    setLanguage("es");
    expect(priceText({ precio: 2.95, moneda: "EUR", por_cantidad: 1 })).toBe("2,95 EUR / 1 ud.");
    expect(priceText({ precio: 412.5, moneda: "EUR", por_cantidad: 10 })).toBe("412,50 EUR / 10 uds.");
    expect(priceText({ precio: null, moneda: null, por_cantidad: 1 })).toBe("sin precio");
    setLanguage("en");
    expect(priceText({ precio: 2.95, moneda: "USD", por_cantidad: 1 })).toBe("2.95 USD / 1 pc");
    setLanguage("es");
  });

  it("un plazo desconocido no es 0 días", () => {
    expect(leadText(null)).toBe("plazo desconocido");
    expect(leadText(1)).toBe("plazo 1 día");
    expect(leadText(15)).toBe("plazo 15 días");
  });

  it("lo gastado, en USD con dos decimales", () => {
    expect(usdText(0.05)).toBe("0,05 USD");
    expect(usdText(null)).toBe("0,00 USD");
    expect(usdText(0.004)).toBe("0,004 USD");
  });
});

describe("Añadir oferta (A7)", () => {
  it("un número vacío va como null, nunca 0, y sin precio no se manda moneda", () => {
    const got = offerPayload(draft({ precio: "", plazo_dias: "", por_cantidad: "" }));
    expect(got.ok).toBe(true);
    if (!got.ok) return;
    expect(got.oferta).toMatchObject({ precio: null, plazo_dias: null, por_cantidad: null, moneda: null, url: null });
  });

  it("los números se leen con coma, y la moneda en mayúsculas", () => {
    const got = offerPayload(draft({ precio: "2,95", moneda: "eur", por_cantidad: "10", plazo_dias: "3" }));
    expect(got.ok && got.oferta).toMatchObject({ precio: 2.95, moneda: "EUR", por_cantidad: 10, plazo_dias: 3 });
  });

  it("sin proveedor, un 0, un negativo, días con decimales o un precio sin moneda no se mandan", () => {
    const got = offerPayload(draft({ proveedor: " ", precio: "0", plazo_dias: "2,5", por_cantidad: "-1" }));
    expect(got.ok).toBe(false);
    if (got.ok) return;
    expect(Object.keys(got.errors).sort()).toEqual(["plazo_dias", "por_cantidad", "precio", "proveedor"]);
    const sinMoneda = offerPayload(draft({ precio: "3", moneda: "" }));
    expect(!sinMoneda.ok && Object.keys(sinMoneda.errors)).toEqual(["moneda"]);
  });
});

describe("la búsqueda", () => {
  it("cada paso dice lo que hace, y uno desconocido no dice nada", () => {
    expect(eventText({ kind: "search", query: "IRF540N" })).toBe("Buscando en el buscador: «IRF540N»");
    expect(eventText({ kind: "fetch", url: "https://es.rs-online.com/p/1", ok: false })).toBe("es.rs-online.com no se deja leer");
    expect(eventText({ kind: "rejected", reason: "sin cita" })).toBe("Descartada: sin cita");
    expect(eventText({ kind: "nuevo" } as never)).toBe("");
  });

  it("al acabar, cuántas apuntó y lo gastado", () => {
    const job = (estado: SearchJob["estado"], n: number): SearchJob => ({
      id: "j", clave: "K", estado, eventos: [],
      resultado: { ofertas: Array(n).fill({}), consultas: [], abiertas: [], fallidas: [], rechazadas: [], cost_usd: 0.05 },
    });
    expect(resultText(job("hecha", 1))).toBe("Búsqueda acabada: 1 oferta apuntada · 0,05 USD");
    expect(resultText(job("hecha", 0))).toContain("ninguna oferta");
    expect(resultText(job("tope", 1))).toContain("tope por búsqueda");
    expect(resultText(job("cancelada", 2))).toBe("Búsqueda cancelada: lo apuntado (2) se queda · 0,05 USD");
  });
});

describe("proveedores (A2)", () => {
  const rs = { nombre: "RS", dominio: "es.rs-online.com", tipos: [] };
  const fa = { nombre: "Farnell", dominio: "es.farnell.com", tipos: ["element"] };

  it("subir y bajar cambian el orden, y nunca se salen de la lista", () => {
    expect(moveItem([rs, fa], 1, -1)).toEqual([fa, rs]);
    expect(moveItem([rs, fa], 0, -1)).toEqual([rs, fa]);
    expect(moveItem([rs, fa], 1, 1)).toEqual([rs, fa]);
  });

  it("los tipos marcados siguen el orden de la librería", () => {
    expect(toggleType(["reducer"], "element", ["element", "reducer"])).toEqual(["element", "reducer"]);
    expect(toggleType(["element", "reducer"], "element", ["element", "reducer"])).toEqual(["reducer"]);
  });

  it("el orden cuenta como cambio, y los espacios alrededor no", () => {
    expect(providersChanged([fa, rs], [rs, fa])).toBe(true);
    expect(providersChanged([{ ...rs, nombre: " RS " }, fa], [rs, fa])).toBe(false);
  });
});
