// Varios workspaces (PLAN_WORKSPACES W6, W7, §6 «La interfaz»): la petición de crear lleva el
// «desde» de cada opción, la carpeta por defecto es `<base>/<nombre>`, el abierto no se quita
// y el que no se encuentra no se abre; abrir o crear espera al rearranque (W3).
import { describe, expect, it } from "vitest";
import {
  canOpen, canRemove, defaultFolder, desdeOf, entryState, newWorkspaceRequest, switchOutcome, templateContents,
  type WorkspaceEntry,
} from "./workspaces";

const entry = (patch: Partial<WorkspaceEntry> = {}): WorkspaceEntry =>
  ({ id: "a", nombre: "Personal", ruta: "C:\\Docs\\BoardPrint\\Personal", abierto: false, falta: false, ...patch });

describe("qué workspaces se pueden abrir y quitar (W7)", () => {
  it("el abierto no se abre ni se quita", () => {
    const w = entry({ abierto: true });
    expect([canOpen(w), canRemove(w), entryState(w)]).toEqual([false, false, "abierto"]);
  });
  it("uno cuya carpeta falta no se abre, pero se quita de la lista", () => {
    const w = entry({ falta: true });
    expect([canOpen(w), canRemove(w), entryState(w)]).toEqual([false, true, "falta"]);
  });
  it("otro que está en su carpeta se abre y se quita", () => {
    expect([canOpen(entry()), canRemove(entry()), entryState(entry())]).toEqual([true, true, "cerrado"]);
  });
});

describe("la carpeta por defecto de uno nuevo", () => {
  it("es <carpeta_base>/<nombre>, con la barra de la base", () => {
    expect(defaultFolder("C:\\Users\\Ana\\Documents\\BoardPrint", " Trabajo ")).toBe("C:\\Users\\Ana\\Documents\\BoardPrint\\Trabajo");
    expect(defaultFolder("/home/ana/BoardPrint/", "Trabajo")).toBe("/home/ana/BoardPrint/Trabajo");
  });
  it("sin base o sin nombre, ninguna", () => {
    expect(defaultFolder(null, "Trabajo")).toBe("");
    expect(defaultFolder("C:\\B", "  ")).toBe("");
  });
});

describe("la petición de crear lleva el «desde» de cada opción (W4)", () => {
  const base = "C:\\Docs\\BoardPrint";
  const token = "0123456789abcdef0123456789abcdef";

  it("vacío, una plantilla o el token del perfil inspeccionado", () => {
    expect(desdeOf({ kind: "vacio" })).toBe("vacio");
    expect(desdeOf({ kind: "plantilla", id: "sector" })).toBe("plantilla:sector");
    expect(desdeOf({ kind: "perfil", token })).toBe(token);
  });
  it("un perfil aún sin elegir no deja crear", () => {
    expect(desdeOf({ kind: "perfil", token: null })).toBeNull();
    expect(newWorkspaceRequest("Trabajo", null, base, { kind: "perfil", token: null })).toBeNull();
  });
  it("con la carpeta por defecto no manda ruta: la calcula el backend con el nombre que valida", () => {
    expect(newWorkspaceRequest(" Trabajo ", null, base, { kind: "plantilla", id: "sector" }))
      .toEqual({ nombre: "Trabajo", desde: "plantilla:sector" });
  });
  it("con una carpeta elegida, la manda", () => {
    expect(newWorkspaceRequest("Trabajo", "D:\\Obra", base, { kind: "perfil", token }))
      .toEqual({ nombre: "Trabajo", ruta: "D:\\Obra", desde: token });
  });
  it("sin nombre, o sin carpeta elegida ni base, no hay petición", () => {
    expect(newWorkspaceRequest("  ", null, base, { kind: "vacio" })).toBeNull();
    expect(newWorkspaceRequest("Trabajo", null, null, { kind: "vacio" })).toBeNull();
    expect(newWorkspaceRequest("Trabajo", "D:\\Obra", null, { kind: "vacio" }))
      .toEqual({ nombre: "Trabajo", ruta: "D:\\Obra", desde: "vacio" });
  });
});

describe("lo que trae una plantilla", () => {
  it("lo que dice su manifiesto, o nada", () => {
    expect(templateContents({ fabricacion: true, fichas: 0, proveedores: false })).toBe("perfil de fabricación");
    expect(templateContents({ fabricacion: true, fichas: 3, proveedores: true }))
      .toBe("perfil de fabricación, 3 fichas, proveedores");
    expect(templateContents({ fabricacion: false, fichas: 1, proveedores: false })).toBe("1 ficha");
    expect(templateContents({ fabricacion: false, fichas: 0, proveedores: false })).toBe("nada");
  });
});

describe("abrir o crear espera al rearranque (W3)", () => {
  const got = (patch = {}) => ({ workspace: entry({ ruta: "D:\\Trabajo" }), reinicio: true, ...patch });

  it("con reinicio, espera al servidor en la carpeta del workspace y recarga", async () => {
    const seen: string[] = [];
    const wait = async (ruta: string) => { seen.push(ruta); return true; };
    expect(await switchOutcome(got(), async () => null, wait)).toBe("recargar");
    expect(seen).toEqual(["D:\\Trabajo"]);
  });
  it("si el servidor no vuelve, lo dice", async () => {
    expect(await switchOutcome(got(), async () => null, async () => false)).toBe("no_vuelve");
  });
  it("sin reinicio: ya era el abierto, o se abrirá al volver a abrir la app", async () => {
    const never = async () => { throw new Error("no espera"); };
    expect(await switchOutcome(got({ reinicio: false }), async () => null, never)).toBe("mismo");
    expect(await switchOutcome(got({ reinicio: false, al_abrir: true }), async () => null, never)).toBe("al_abrir");
  });
});
