// Reglas de la pantalla de inicio (plan D63, D65, §10).
import { describe, expect, it } from "vitest";
import { crumbs, findFolder, folderSummary, moveTargets, search, timeAgo, type TreeNode } from "./tree";

const p = (path: string): TreeNode => ({ kind: "project", name: path.split("/").pop()!, path, modified: 0, id: path });
const f = (path: string, children: TreeNode[]): TreeNode => ({
  kind: "folder", name: path ? path.split("/").pop()! : "Personal", path, modified: 0, children,
});

const tree = f("", [
  f("Brazos", [p("Brazos/Brazo pinza"), p("Brazos/Brazo 6 ejes")]),
  f("Terminales", [f("Terminales/Clientes", [p("Terminales/Clientes/Pinza paralela")])]),
  p("Ménsula 40"),
]);

describe("árbol", () => {
  it("encuentra carpetas anidadas por su ruta y nunca un proyecto como carpeta", () => {
    expect(findFolder(tree, "Terminales/Clientes")?.children?.[0].name).toBe("Pinza paralela");
    expect(findFolder(tree, "Ménsula 40")).toBeNull();
    expect(findFolder(tree, "No/Existe")).toBeNull();
  });

  it("las migas empiezan en el workspace", () => {
    expect(crumbs("Personal", "Terminales/Clientes")).toEqual([
      { name: "Personal", path: "" },
      { name: "Terminales", path: "Terminales" },
      { name: "Clientes", path: "Terminales/Clientes" },
    ]);
  });

  it("buscar no distingue mayúsculas ni acentos y mira en todas las carpetas", () => {
    expect(search(tree, "menSula").map((n) => n.path)).toEqual(["Ménsula 40"]);
    expect(search(tree, "pinza").map((n) => n.path)).toEqual(["Brazos/Brazo pinza", "Terminales/Clientes/Pinza paralela"]);
    expect(search(tree, "  ")).toEqual([]);
  });

  it("el resumen de una carpeta cuenta carpetas y proyectos", () => {
    expect(folderSummary(findFolder(tree, "Brazos")!)).toBe("2 proyectos");
    expect(folderSummary(findFolder(tree, "Terminales")!)).toBe("1 carpeta");
    expect(folderSummary(f("Vacía", []))).toBe("vacía");
  });
});

describe("mover", () => {
  it("una carpeta nunca se ofrece como destino de sí misma ni de sus subcarpetas", () => {
    const paths = moveTargets(tree, findFolder(tree, "Terminales")!).map((t) => t.path);
    expect(paths).toEqual(["Brazos"]); // ni Terminales, ni Clientes, ni la raíz (ya está ahí)
  });

  it("un proyecto puede ir a cualquier carpeta menos a la suya", () => {
    const targets = moveTargets(tree, p("Brazos/Brazo pinza"));
    expect(targets.map((t) => t.path)).toEqual(["", "Terminales", "Terminales/Clientes"]);
    expect(targets.map((t) => t.name)).toEqual(["Personal", "Terminales", "Terminales › Clientes"]);
  });
});

describe("fechas relativas", () => {
  const now = new Date(2026, 10, 9, 15, 0).getTime() / 1000; // 9 nov 2026, 15:00
  it("de minutos a fechas", () => {
    expect(timeAgo(now - 20, now)).toBe("hace un momento");
    expect(timeAgo(now - 5 * 60, now)).toBe("hace 5 min");
    expect(timeAgo(now - 2 * 3600, now)).toBe("hace 2 horas");
    expect(timeAgo(new Date(2026, 10, 8, 23, 0).getTime() / 1000, now)).toBe("ayer");
    expect(timeAgo(new Date(2026, 10, 3, 10, 0).getTime() / 1000, now)).toBe("3 nov");
    expect(timeAgo(new Date(2025, 9, 28).getTime() / 1000, now)).toBe("28 oct 2025");
    expect(timeAgo(0, now)).toBe("");
  });
});
