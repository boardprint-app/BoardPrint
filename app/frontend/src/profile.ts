// El perfil de fabricación del workspace (PLAN_PIZARRA D31, PLAN_V020 V8): un Markdown con
// una plantilla que leen los dos agentes. `GET /api/workspace/fabricacion` da `{texto, guardado,
// plantilla}` (sin guardar, `texto` es la plantilla, que los agentes aún no leen) y `PUT` lo
// guarda (422 si no es texto o pasa de 20000 caracteres). Aquí, lo que no es React ni red (las
// llamadas, en `settings/ProfileRow.tsx`).
import { t } from "./i18n";

export type Profile = { texto: string; guardado: boolean; plantilla: string };

/** Cómo está lo escrito: con cambios sin guardar, guardado, o la plantilla sin guardar aún
 *  (los agentes no la leen hasta que se guarda). */
export type ProfileStatus = "dirty" | "saved" | "template";

export function profileStatus(text: string, saved: Profile | null): ProfileStatus {
  if (!saved || text !== saved.texto) return "dirty";
  return saved.guardado ? "saved" : "template";
}

export function statusText(s: ProfileStatus): string {
  return s === "dirty" ? t("ajustes.perfil.sin_guardar")
    : s === "saved" ? t("ajustes.perfil.guardado") : t("ajustes.perfil.plantilla");
}

/** El motivo de un rechazo del backend: su `detail` si es un texto, o el estado HTTP. */
export function detail(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  return typeof d === "string" && d ? d : t("ajustes.error_http", { estado: status });
}

// ----------------------------------------------------- el perfil .zip (PLAN_LIBRERIA §5, L8-L10)
// `POST /api/profile/export` lo escribe en una carpeta (el stock solo con la casilla) y
// `POST /api/profile/import/inspect` da el resumen de importarlo, que `.../apply` escribe tras
// guardar una copia del perfil de ahora. Cancelar el diálogo da `{file: null}`.

export type ProfileExport = {
  file: string | null; nombre?: string; fichas?: number; stock?: number | null;
  fabricacion?: boolean; omitidas?: string[];
};

// Con `destino: "nuevo"` (PLAN_WORKSPACES W4: crear un workspace con él) no hay nada que
// sustituir ni copia: `copia` es null y `sustituye` va a cero.
export type ProfileImportPlan = {
  file: string | null; token: string; nombre: string;
  manifest: { esquema: number; app: string; fecha: string; generica?: boolean };
  fichas: number; tipos: Record<string, number>; fabricacion: boolean; proveedores?: boolean;
  stock: number | null;
  invalid: { ruta: string; clave: string | null; motivo: string }[]; ignored: string[];
  sustituye: { fichas: number; quitadas: string[]; fabricacion: boolean; stock: number };
  copia: string | null; destino?: "actual" | "nuevo";
};

export type ProfileImportDone = {
  copia: string | null; fichas: number; quitadas: number; fabricacion: boolean; stock: number | null;
};

/** El resumen de importar en filas (título, lo que pasa): qué trae, qué sustituye de lo de
 *  ahora y qué se queda, y dónde queda la copia. Las fichas que no valen van aparte. Hacia un
 *  workspace nuevo, solo lo que trae (`newRows`). */
export function importRows(p: ProfileImportPlan): { label: string; value: string }[] {
  if (p.destino === "nuevo" || p.copia === null) return newRows(p);
  const tipos = Object.entries(p.tipos).map(([tipo, n]) => `${tipo} ${n}`).join(", ");
  const rows = [
    { label: t("ajustes.perfil_zip.r.fichas"),
      value: tipos ? t("ajustes.perfil_zip.fichas_tipos", { n: p.fichas, tipos }) : String(p.fichas) },
    { label: t("ajustes.perfil_zip.r.libreria"),
      value: t("ajustes.perfil_zip.libreria", { n: p.sustituye.fichas }) },
  ];
  if (p.sustituye.quitadas.length) {
    rows.push({ label: t("ajustes.perfil_zip.r.quitadas"), value: p.sustituye.quitadas.join(", ") });
  }
  rows.push({
    label: t("ajustes.perfil_zip.r.fabricacion"),
    value: !p.fabricacion ? t("ajustes.perfil_zip.fab_no")
      : p.sustituye.fabricacion ? t("ajustes.perfil_zip.fab_sustituye") : t("ajustes.perfil_zip.fab_si"),
  });
  rows.push({
    label: t("ajustes.perfil_zip.r.stock"),
    value: p.stock === null ? t("ajustes.perfil_zip.stock_no")
      : p.sustituye.stock ? t("ajustes.perfil_zip.stock_sustituye", { n: p.stock, ahora: p.sustituye.stock })
        : t("ajustes.perfil_zip.stock_si", { n: p.stock }),
  });
  rows.push({ label: t("ajustes.perfil_zip.r.copia"), value: t("ajustes.perfil_zip.copia", { ruta: p.copia }) });
  return rows;
}

/** Lo que trae el zip a un workspace nuevo: no sustituye nada, y lo que no trae empieza vacío. */
function newRows(p: ProfileImportPlan): { label: string; value: string }[] {
  const tipos = Object.entries(p.tipos).map(([tipo, n]) => `${tipo} ${n}`).join(", ");
  const rows = [
    { label: t("ajustes.perfil_zip.r.fichas"),
      value: tipos ? t("ajustes.perfil_zip.fichas_tipos", { n: p.fichas, tipos }) : String(p.fichas) },
    { label: t("ajustes.perfil_zip.r.fabricacion"),
      value: p.fabricacion ? t("ajustes.perfil_zip.fab_si") : t("ajustes.perfil_zip.nuevo_fab_no") },
  ];
  if (p.proveedores !== undefined) {
    rows.push({ label: t("ajustes.perfil_zip.r.proveedores"),
                value: p.proveedores ? t("ajustes.perfil_zip.prov_si") : t("ajustes.perfil_zip.nuevo_prov_no") });
  }
  rows.push({
    label: t("ajustes.perfil_zip.r.stock"),
    value: p.stock === null ? t("ajustes.perfil_zip.nuevo_stock_no") : t("ajustes.perfil_zip.stock_si", { n: p.stock }),
  });
  return rows;
}

/** De dónde viene el zip: la fecha y la versión de la app que lo escribió, si las dice. */
export function importOrigin(p: ProfileImportPlan): string {
  const { fecha, app } = p.manifest;
  if (fecha && app) return t("ajustes.perfil_zip.origen", { fecha, app });
  return fecha ? t("ajustes.perfil_zip.origen_fecha", { fecha }) : "";
}
