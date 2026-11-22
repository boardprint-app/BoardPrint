// Microsoft 365 en la pizarra (docs/PLAN_M365.md §9): las migas del panel, a dónde sube
// *Guardar en la nube* (M9), qué tarjeta es de la nube (M6, M10) y qué marca enseña (M7, M8).
import { afterEach, describe, expect, it } from "vitest";
import {
  cloudActions, cloudOf, conflictTarget, driveQuery, enter, fmtModified, getM365View, goTo, handleM365Message,
  libraryRoot, oneDriveRoot, parseStates, resetM365View, stateMark, uploadTarget, type M365Item,
} from "./m365";

const folder = (id: string, name: string, drive_id = "D1"): M365Item => ({
  id, drive_id, name, folder: true, child_count: 2, size: 0, modified: "", web_url: "", ctag: null, service: "onedrive",
});

describe("migas del panel", () => {
  it("entrar añade la carpeta al final y volver corta hasta esa miga", () => {
    const a = enter([oneDriveRoot()], folder("A", "Proyectos"));
    const b = enter(a, folder("B", "Brazo"));
    expect(b.map((c) => c.item_id)).toEqual([null, "A", "B"]);
    expect(goTo(b, 0)).toEqual([b[0]]);
    expect(goTo(b, 1).map((c) => c.label)).toEqual([b[0].label, "Proyectos"]);
  });
  it("volver a una miga que no existe no cambia nada", () => {
    const b = enter([oneDriveRoot()], folder("A", "Proyectos"));
    expect(goTo(b, 5)).toBe(b);
    expect(goTo(b, -1)).toBe(b);
  });
  it("la raíz de OneDrive no lleva ids; una biblioteca de SharePoint es su raíz", () => {
    expect(driveQuery(oneDriveRoot(), "onedrive")).toBe("service=onedrive");
    const lib = libraryRoot({ id: "L 1", name: "Documentos", web_url: "" });
    expect(driveQuery(lib, "sharepoint")).toBe("service=sharepoint&drive_id=L+1&item_id=root");
  });
});

describe("Guardar en la nube (M9)", () => {
  it("en la raíz de OneDrive no manda carpeta; en una carpeta, su unidad y su id", () => {
    expect(uploadTarget(oneDriveRoot(), "onedrive")).toEqual({ service: "onedrive" });
    const inside = enter([oneDriveRoot()], folder("F", "Informes", "D9"));
    expect(uploadTarget(inside[1], "onedrive")).toEqual({ service: "onedrive", drive_id: "D9", folder_id: "F" });
  });
  it("en un conflicto, la mía va a la raíz de la misma unidad, nunca encima del original", () => {
    const ref = cloudOf({ m365: { service: "sharepoint", drive_id: "D2", item_id: "I2" } })!;
    expect(conflictTarget(ref)).toEqual({ service: "sharepoint", drive_id: "D2", folder_id: "root" });
    expect(conflictTarget(ref).folder_id).not.toBe(ref.item_id);
  });
});

describe("tarjetas de la nube (M6, M10)", () => {
  it("solo es de la nube con unidad e id; sin ellos, una tarjeta normal", () => {
    expect(cloudOf({ path: "a.xlsx" })).toBeNull();
    expect(cloudOf({ m365: { service: "onedrive", item_id: "X" } })).toBeNull();
    expect(cloudOf({ m365: { service: "onedrive", drive_id: "D", item_id: "X" } })?.service).toBe("onedrive");
  });
  it("un correo no tiene unidad: su id es el del mensaje, se abre en Outlook y no se actualiza", () => {
    const ref = cloudOf({ m365: { service: "correo", message_id: "M1", web_url: "https://outlook" } })!;
    expect(ref.item_id).toBe("M1");
    expect(cloudActions(ref)).toEqual({ outlook: true, refresh: false });
    const file = cloudOf({ m365: { service: "sharepoint", drive_id: "D", item_id: "X" } })!;
    expect(cloudActions(file)).toEqual({ outlook: false, refresh: true });
  });
  it("un servicio desconocido se trata como OneDrive", () => {
    expect(cloudOf({ m365: { service: "dropbox", drive_id: "D", item_id: "X" } })?.service).toBe("onedrive");
  });
});

describe("marcas del sondeo (M7, M8)", () => {
  afterEach(() => resetM365View());
  it("solo el conflicto y sin conexión se ven; al día y descargada, nada", () => {
    expect(stateMark("conflicto")).toBe("conflicto");
    expect(stateMark("sin_conexion")).toBe("sin_conexion");
    expect(stateMark("al_dia")).toBeNull();
    expect(stateMark("descargada")).toBeNull();
    expect(stateMark(undefined)).toBeNull();
  });
  it("del WebSocket solo entran los estados que se conocen, nunca un error", () => {
    expect(parseStates({ a: "conflicto", b: "error", c: "sin_conexion", d: 3 })).toEqual({ a: "conflicto", c: "sin_conexion" });
    expect(parseStates(null)).toEqual({});
  });
  it("con `cards` cambian las marcas; sin ellas, la cuenta (el panel la vuelve a mirar)", () => {
    const tick = getM365View().tick;
    handleM365Message({ cards: { a: "conflicto" } });
    expect(getM365View().states).toEqual({ a: "conflicto" });
    expect(getM365View().tick).toBe(tick);
    handleM365Message({});
    expect(getM365View().tick).toBe(tick + 1);
    resetM365View();
    expect(getM365View().states).toEqual({});
  });
});

describe("fecha de una fila", () => {
  it("en el idioma de la app, y vacía si no se entiende", () => {
    expect(fmtModified("2026-11-21T10:00:00Z", "es")).toMatch(/21.*nov.*2026/);
    expect(fmtModified("2026-11-21T10:00:00Z", "en")).toMatch(/Nov 21, 2026/);
    expect(fmtModified("", "es")).toBe("");
    expect(fmtModified("no es fecha", "es")).toBe("");
  });
});
