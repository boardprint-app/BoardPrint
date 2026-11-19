// Lógica pura de la pantalla de inicio (plan D63, D65): árbol del workspace, búsqueda,
// migas, fechas relativas y destinos válidos al mover. Sin React: se prueba con vitest.
import { t } from "../i18n";

export type TreeNode = {
  kind: "folder" | "project";
  name: string;
  path: string;
  modified: number; // segundos epoch
  id?: string | null;
  error?: string | null;
  thumbnail?: boolean;
  children?: TreeNode[];
};

export function findFolder(root: TreeNode, path: string): TreeNode | null {
  if (path === "") return root;
  let node: TreeNode | undefined = root;
  for (const part of path.split("/")) {
    node = node?.children?.find((c) => c.kind === "folder" && c.name === part);
    if (!node) return null;
  }
  return node;
}

/** Migas desde la raíz: [{name: "Personal", path: ""}, {name: "Brazos", path: "Brazos"}]. */
export function crumbs(rootName: string, path: string) {
  const out = [{ name: rootName, path: "" }];
  if (path === "") return out;
  const parts = path.split("/");
  parts.forEach((name, i) => out.push({ name, path: parts.slice(0, i + 1).join("/") }));
  return out;
}

const fold = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

/** Carpetas y proyectos de todo el workspace cuyo nombre contiene el texto (sin distinguir
 *  mayúsculas ni acentos: «menSula» encuentra «Ménsula 40»). */
export function search(root: TreeNode, query: string): TreeNode[] {
  const q = fold(query.trim());
  if (!q) return [];
  const out: TreeNode[] = [];
  const walk = (n: TreeNode) => {
    for (const c of n.children ?? []) {
      if (fold(c.name).includes(q)) out.push(c);
      if (c.kind === "folder") walk(c);
    }
  };
  walk(root);
  return out;
}

export function countProjects(node: TreeNode): number {
  if (node.kind === "project") return 1;
  return (node.children ?? []).reduce((s, c) => s + countProjects(c), 0);
}

/** Resumen de una carpeta para su tarjeta: «2 proyectos», «1 carpeta · 1 proyecto», «vacía». */
export function folderSummary(node: TreeNode): string {
  const kids = node.children ?? [];
  const f = kids.filter((c) => c.kind === "folder").length;
  const p = kids.length - f;
  const parts = [];
  if (f) parts.push(t(f === 1 ? "lienzo.inicio.carpetas_uno" : "lienzo.inicio.carpetas_varios", { n: f }));
  if (p) parts.push(t(p === 1 ? "lienzo.inicio.proyectos_uno" : "lienzo.inicio.proyectos_varios", { n: p }));
  return parts.join(" · ") || t("lienzo.inicio.vacia");
}

/** Carpetas a las que se puede mover algo. Una carpeta nunca puede ir dentro de sí misma ni
 *  de una de sus subcarpetas (la misma regla que el backend, que es quien manda). */
export function moveTargets(root: TreeNode, moving: TreeNode): { name: string; path: string }[] {
  const out: { name: string; path: string }[] = [];
  const parent = moving.path.includes("/") ? moving.path.slice(0, moving.path.lastIndexOf("/")) : "";
  const walk = (n: TreeNode, label: string) => {
    if (moving.kind === "folder" && (n.path === moving.path || n.path.startsWith(moving.path + "/"))) return;
    if (n.path !== parent) out.push({ name: label, path: n.path });
    for (const c of n.children ?? []) if (c.kind === "folder") walk(c, label ? `${label} › ${c.name}` : c.name);
  };
  walk(root, root.name);
  // La raíz se llama como el workspace; el resto, con su ruta legible.
  return out.map((t) => (t.path === "" ? t : { ...t, name: t.name.slice(root.name.length + 3) }));
}

/** «hace un momento», «hace 5 min», «hace 2 horas», «ayer», «3 nov» (o «3 nov 2025»). */
export function timeAgo(epochSec: number, now = Date.now() / 1000): string {
  if (!epochSec) return "";
  const s = Math.max(0, now - epochSec);
  if (s < 60) return t("lienzo.inicio.hace_momento");
  if (s < 3600) return t("lienzo.inicio.hace_min", { n: Math.floor(s / 60) });
  const d = new Date(epochSec * 1000);
  const today = new Date(now * 1000);
  const days = Math.floor(
    (Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) -
      Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000,
  );
  if (days === 0) {
    const h = Math.floor(s / 3600);
    return t(h === 1 ? "lienzo.inicio.hace_hora_uno" : "lienzo.inicio.hace_hora_varios", { n: h });
  }
  if (days === 1) return t("lienzo.inicio.ayer");
  const label = `${d.getDate()} ${t("lienzo.inicio.meses").split(",")[d.getMonth()]}`;

  return d.getFullYear() === today.getFullYear() ? label : `${label} ${d.getFullYear()}`;
}
