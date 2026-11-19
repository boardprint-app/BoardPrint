// Traducción de lo que da un paquete (PLAN_PUBLICACION O15). Reglas:
// - en español (el idioma de los paquetes) el texto no cambia nunca;
// - si no, la entrada exacta; si no, un patrón `{nombre}` que case con la frase **entera**
//   (con números y comas decimales); si no, el texto de origen;
// - un paquete sin catálogo, o un texto que no está, da el de origen;
// - el catálogo de bloques traducido cambia lo que se pinta y nunca los ids, las claves, las
//   opciones (valores que se guardan) ni los valores por defecto;
// - la interfaz propia de un paquete recibe su catálogo en el estado del marco (`i18n`).
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { localizeCatalog, mergedCatalog, tp, tpOwn, translate, type CatalogParts } from "./packI18n";
import { columnLabel, groupLabel } from "./outputs";
import { frameState, theme } from "./packui";
import { resetStore, setStore, type BlockType } from "./store";

const EN = {
  "Brazo": "Arm",
  "Masa (kg)": "Mass (kg)",
  "Falla por {x} mm": "Fails by {x} mm",
  "{a} de {b}": "{b}'s {a}",
  "Junta {j} con {j}": "Joint {j} with itself",
  "Material": "Material",
  "acero": "steel",
  "Cumple": "Pass",
  "Carga útil": "Payload",
  "Grupo raro": "Odd group",
};

function packs() {
  return [{ id: "acme", name: "Acme", version: "1.0.0", error: null, i18n: { en: EN } },
          { id: "otro", name: "Otro", version: "1.0.0", error: null }];
}

beforeEach(() => {
  setStore({ packs: packs() });
  setLanguage("en");
});
afterEach(() => {
  resetStore();
  setLanguage("es");
});

describe("tp (O15)", () => {
  it("en español no cambia nada", () => {
    setLanguage("es");
    expect(tp("acme", "Brazo")).toBe("Brazo");
    expect(tp("acme", "Falla por 1,2 mm")).toBe("Falla por 1,2 mm");
  });

  it("la entrada exacta", () => {
    expect(tp("acme", "Brazo")).toBe("Arm");
    expect(tp("acme", "Masa (kg)")).toBe("Mass (kg)");
  });

  it("un patrón casa con números y comas decimales", () => {
    expect(tp("acme", "Falla por 1,2 mm")).toBe("Fails by 1,2 mm");
    expect(tp("acme", "Falla por -0,05 mm")).toBe("Fails by -0,05 mm");
    expect(tp("acme", "Falla por 12 mm")).toBe("Fails by 12 mm");
  });

  it("los marcadores se reordenan, y uno repetido tiene que valer lo mismo", () => {
    expect(tp("acme", "masa de L2")).toBe("L2's masa");
    expect(tp("acme", "Junta J1 con J1")).toBe("Joint J1 with itself");
    expect(tp("acme", "Junta J1 con J2")).toBe("Junta J1 con J2");
  });

  it("nunca casa a medias", () => {
    expect(tp("acme", "El Brazo")).toBe("El Brazo");
    expect(tp("acme", "Brazo 2")).toBe("Brazo 2");
    expect(tp("acme", "Falla por 1,2 mm o más")).toBe("Falla por 1,2 mm o más");
    expect(tp("acme", "Ya: Falla por 1,2 mm")).toBe("Ya: Falla por 1,2 mm");
  });

  it("lo que no está da el texto de origen", () => {
    expect(tp("acme", "Pinza")).toBe("Pinza");
    expect(tp("acme", "")).toBe("");
  });

  it("un paquete sin catálogo, o que no está, da el de origen si ningún paquete cargado lo traduce", () => {
    setStore({ packs: packs().filter((p) => p.id === "otro") });
    expect(tp("otro", "Brazo")).toBe("Brazo");
    expect(tp("no_esta", "Brazo")).toBe("Brazo");
    expect(tp(undefined, "Brazo")).toBe("Brazo");
  });

  it("los caracteres de una expresión regular en la clave son texto", () => {
    expect(translate({ "Total (x{n}) [ok]": "Sum (x{n}) [ok]" }, "Total (x3) [ok]")).toBe("Sum (x3) [ok]");
    expect(translate({ "a.b {n}": "A {n}" }, "axb 3")).toBe("axb 3");
  });
});

describe("Ajustes → Paquetes (tpOwn, e2e de v0.1.0)", () => {
  const installed = { id: "acme", i18n: { en: { "Acme robótica": "Acme robotics" } } };

  it("traduce con el catálogo que trae el paquete aunque no haya ninguno cargado (el inicio)", () => {
    resetStore();
    expect(tpOwn(installed, "Acme robótica")).toBe("Acme robotics");
    expect(tpOwn({ id: "acme" }, "Acme robótica")).toBe("Acme robótica");
  });

  it("en español no cambia nada, y con la pizarra abierta sigue valiendo lo de los demás", () => {
    expect(tpOwn(installed, "Brazo")).toBe("Arm");
    setLanguage("es");
    expect(tpOwn(installed, "Acme robótica")).toBe("Acme robótica");
  });
});

describe("reglas del catálogo de un paquete grande (O15)", () => {
  const BASE = { "Brida ISO {n}": "ISO {n} flange", "Brazo": "Base arm", "domina: {cosa}": "dominates: {cosa}" };
  const OWN = {
    "los fijados tienen que ser {parámetro: valor}": "locks must be {parameter: value}",
    "{x} no cumple los requisitos: {motivos}": "{x} does not meet the requirements: {motivos}",
    "par alto": "high torque", "masa alta": "high mass", "J1 domina": "J1 dominates",
    "Pieza {p}": "Part {p}", "Pieza {p} de {q}": "Part {p} of {q}",
  };
  beforeEach(() => setStore({ packs: [
    { id: "acme", name: "Acme", version: "1.0.0", error: null, i18n: { en: { ...EN, ...OWN } } },
    { id: "base", name: "Base", version: "1.0.0", error: null, i18n: { en: BASE } },
  ] }));

  it("solo {palabra} es un marcador: otras llaves son texto exacto", () => {
    expect(tp("acme", "los fijados tienen que ser {parámetro: valor}")).toBe("locks must be {parameter: value}");
    expect(tp("acme", "los fijados tienen que ser J2: 3")).toBe("los fijados tienen que ser J2: 3");
  });

  it("primero el de más texto fijo delante del primer marcador", () => {
    expect(tp("acme", "Pieza L1 de L2")).toBe("Part L1 of L2");
  });

  it("lo que casa con un marcador también se traduce", () => {
    expect(tp("acme", "Brazo no cumple los requisitos: par alto")).toBe("Arm does not meet the requirements: high torque");
    expect(tp("acme", "domina: J1 domina")).toBe("dominates: J1 dominates");
  });

  it("una lista «a; b» se traduce parte por parte, también dentro de un marcador", () => {
    expect(tp("acme", "par alto; masa alta; otra cosa")).toBe("high torque; high mass; otra cosa");
    expect(tp("acme", "X no cumple los requisitos: par alto; masa alta"))
      .toBe("X does not meet the requirements: high torque; high mass");
  });

  it("un marcador no cruza «; »: la lista se parte y cada línea casa con su patrón", () => {
    const cat = { "{desc} (estado {s})": "{desc} (state {s})", "Tubo corto": "Short tube", "abierto": "open" };
    expect(translate(cat, "Tubo corto (estado abierto); Otro (estado 2)"))
      .toBe("Short tube (state open); Otro (state 2)");
  });

  it("después del suyo, los de los demás paquetes cargados; el suyo manda", () => {
    expect(tp("acme", "Brida ISO 50")).toBe("ISO 50 flange");
    expect(tp("acme", "Brazo")).toBe("Arm");
    expect(tp("base", "Brazo")).toBe("Base arm");
    expect(tp("nadie", "Brida ISO 50")).toBe("ISO 50 flange");
  });
});

describe("el catálogo de bloques traducido (O15)", () => {
  const ty: BlockType = {
    title: "Brazo", pack: "acme", description: "Carga útil", inputs: { carga: "acme.carga" }, outputs: {},
    requires: [], fix: { port: "p", field: "f", label: "Material" },
    params: {
      material: { default: "acero", unit: "", label: "Material", choices: ["acero", "aluminio"] },
      masa: { default: 2, unit: "kg", label: "Masa (kg)", choices: [] },
    },
  };
  const cat = (): CatalogParts => ({
    types: { "acme.brazo": ty }, ports: { "acme.carga": { label: "Carga útil", color: null } },
    templates: { "acme.t": { title: "Brazo", pack: "acme", description: "", blocks: [], links: [] } },
    connectorInfo: {}, packs: packs(),
  });

  it("traduce lo que se pinta y deja los datos", () => {
    const out = localizeCatalog(cat(), "en");
    const b = out.types["acme.brazo"];
    expect(b.title).toBe("Arm");
    expect(b.description).toBe("Payload");
    expect(b.fix?.label).toBe("Material");
    expect(b.params.masa.label).toBe("Mass (kg)");
    expect(b.params.material.choices).toEqual(["acero", "aluminio"]);     // valores: no cambian
    expect(b.params.material.default).toBe("acero");
    expect(b.params.material.choice_labels).toEqual({ acero: "steel" });  // lo que se enseña
    expect(Object.keys(out.types)).toEqual(["acme.brazo"]);
    expect(b.inputs).toEqual({ carga: "acme.carga" });
    expect(out.ports["acme.carga"].label).toBe("Payload");
    expect(out.templates["acme.t"].title).toBe("Arm");
    expect(out.packs[0].i18n).toEqual({ en: EN });                         // tp lo sigue usando
  });

  it("en español es el mismo catálogo", () => {
    const c = cat();
    expect(localizeCatalog(c, "es")).toBe(c);
  });
});

describe("salidas (O15)", () => {
  it("la etiqueta que sale de la clave se traduce con el catálogo del paquete", () => {
    expect(columnLabel("masa_kg", "acme")).toBe("Mass (kg)");
    setStore({ packs: [] });
    expect(columnLabel("masa_kg", "acme")).toBe("Masa (kg)");     // sin catálogo, el de origen
    setStore({ packs: packs() });
    expect(groupLabel("grupo_raro", "acme")).toBe("Odd group");
  });
});

describe("estado del marco (O15)", () => {
  it("lleva el catálogo de su paquete, y vacío por defecto", () => {
    const ty = { title: "B", pack: "acme", description: "", inputs: {}, outputs: {}, requires: [], params: {} };
    const th = theme("escuela", true, {}, "card");
    expect(frameState("b1", "acme.b", ty, undefined, "card", th, undefined, "en", EN).i18n).toBe(EN);
    setStore({ packs: [...packs(), { id: "base", name: "Base", version: "1.0.0", error: null, i18n: { en: { "Brazo": "Base arm", "Brida": "Flange" } } }] });
    const m = mergedCatalog("acme", "en");
    expect(m["Brazo"]).toBe("Arm");                 // el suyo manda
    expect(m["Brida"]).toBe("Flange");
    expect(mergedCatalog("acme", "en")).toBe(m);    // el mismo objeto: el marco no se rehace
    expect(frameState("b1", "acme.b", ty, undefined, "card", th).i18n).toEqual({});
  });
});
