// El perfil de fabricación (PLAN_V020 V8): lo escrito dice si está guardado, sin guardar o si
// aún es la plantilla (que los agentes no leen), y un rechazo enseña el motivo del backend.
import { describe, expect, it } from "vitest";
import { detail, importRows, profileStatus, type Profile, type ProfileImportPlan } from "./profile";

const tpl = "# Perfil\n## Máquinas\n";
const template: Profile = { texto: tpl, guardado: false, plantilla: tpl };

describe("el perfil dice si lo escrito está guardado", () => {
  it("la plantilla sin tocar y sin guardar es plantilla, no guardado", () => {
    expect(profileStatus(tpl, template)).toBe("template");
  });
  it("lo escrito distinto de lo guardado está sin guardar", () => {
    expect(profileStatus(tpl + "- Torno", template)).toBe("dirty");
    expect(profileStatus("otro", { texto: "uno", guardado: true, plantilla: tpl })).toBe("dirty");
  });
  it("lo guardado, aunque sea igual que la plantilla, está guardado", () => {
    expect(profileStatus(tpl, { ...template, guardado: true })).toBe("saved");
  });
  it("sin respuesta del backend no se da nada por guardado", () => {
    expect(profileStatus("", null)).toBe("dirty");
  });
});

describe("un rechazo enseña el motivo del backend", () => {
  it("el detail del 422 tal cual", () => {
    expect(detail({ detail: "el perfil no puede pasar de 20000 caracteres" }, 422))
      .toBe("el perfil no puede pasar de 20000 caracteres");
  });
  it("sin detail, el estado HTTP", () => {
    expect(detail(null, 503)).toMatch(/503/);
    expect(detail({ detail: [{ msg: "x" }] }, 422)).toMatch(/422/);
  });
});

// El resumen de importar un perfil .zip (PLAN_LIBRERIA L9): dice siempre qué se sustituye, qué
// se queda (lo que el zip no trae) y dónde queda la copia, antes de aceptar.
const plan: ProfileImportPlan = {
  file: "C:/x/Taller-perfil-2026-11-18.zip", token: "t", nombre: "Taller-perfil-2026-11-18.zip",
  manifest: { esquema: 1, app: "0.2.0", fecha: "2026-11-18" },
  fichas: 3, tipos: { reducer: 2, gripper: 1 }, fabricacion: true, stock: null,
  invalid: [], ignored: [],
  sustituye: { fichas: 5, quitadas: ["VIEJA"], fabricacion: true, stock: 0 },
  copia: "C:/ws/profile/.copias",
};
const valueOf = (p: ProfileImportPlan, label: string) =>
  importRows(p).find((r) => r.label === label)?.value ?? "";

describe("el resumen de importar un perfil", () => {
  it("la copia sale siempre, con su carpeta", () => {
    expect(valueOf(plan, "Copia")).toContain("C:/ws/profile/.copias");
  });
  it("sin stock en el zip, dice que se queda el de ahora", () => {
    expect(valueOf(plan, "Stock")).toMatch(/se queda/);
    expect(valueOf({ ...plan, stock: 4, sustituye: { ...plan.sustituye, stock: 9 } }, "Stock"))
      .toMatch(/sustituye.*9/);
  });
  it("las fichas que se van se nombran; si no se va ninguna, no hay fila", () => {
    expect(valueOf(plan, "Se quitan")).toBe("VIEJA");
    expect(importRows({ ...plan, sustituye: { ...plan.sustituye, quitadas: [] } })
      .some((r) => r.label === "Se quitan")).toBe(false);
  });
  it("cuenta las fichas por tipo, y la fabricación dice si sustituye la de ahora", () => {
    expect(valueOf(plan, "Fichas")).toBe("3 (reducer 2, gripper 1)");
    expect(valueOf(plan, "Fabricación")).toMatch(/sustituye/);
    expect(valueOf({ ...plan, fabricacion: false }, "Fabricación")).toMatch(/se queda/);
  });
});

// Hacia un workspace nuevo (PLAN_WORKSPACES W4): no hay nada que sustituir ni copia (`copia`
// null), así que el resumen solo dice lo que trae, y lo que no trae empieza vacío.
describe("el resumen de un perfil para un workspace nuevo", () => {
  const nuevo: ProfileImportPlan = {
    ...plan, destino: "nuevo", copia: null, proveedores: false,
    sustituye: { fichas: 0, quitadas: [], fabricacion: false, stock: 0 },
  };
  const labels = (p: ProfileImportPlan) => importRows(p).map((r) => r.label);

  it("sin copia ni librería que sustituir", () => {
    expect(labels(nuevo)).toEqual(["Fichas", "Fabricación", "Proveedores", "Stock"]);
    expect(importRows(nuevo).some((r) => /sustituye/.test(r.value))).toBe(false);
  });
  it("lo que no trae, empieza vacío", () => {
    expect(valueOf({ ...nuevo, fabricacion: false }, "Fabricación")).toMatch(/empieza sin/);
    expect(valueOf(nuevo, "Stock")).toMatch(/empieza sin stock/);
    expect(valueOf({ ...nuevo, stock: 4 }, "Stock")).toMatch(/4/);
    expect(valueOf(nuevo, "Proveedores")).toMatch(/empieza sin/);
  });
  it("con copia null aunque no diga el destino, tampoco enseña la copia", () => {
    expect(labels({ ...nuevo, destino: undefined })).not.toContain("Copia");
  });
});
