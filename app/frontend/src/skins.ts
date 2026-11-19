// Skins de la pizarra (plan D58, D79). Lo visual sale de las variables de skins.css, con
// `data-skin` en <html>. La misma lista está en el backend (pizarra/settings.py, SKINS).
//
// La tinta del usuario (lo dibujado a mano) la pinta el lienzo de Excalidraw con su color
// guardado. En los skins oscuros se usa el tema oscuro de Excalidraw, que invierte solo el
// lienzo (las tarjetas de bloques y post-its son DOM y no las toca) con el lienzo
// transparente y el fondo del skin detrás: un trazo negro hecho en papel en calma sale claro
// en la pizarra verde y vuelve a negro al cambiar de skin, sin tocar lo guardado. Los skins
// claros con fondo de color (laboratorio, corcho) oscurecen la tinta con un filtro al pintarla:
// los colores claros de la paleta (el naranja, sobre todo) no se leerían. Excalidraw 0.18 no
// deja cambiar la paleta por skin.
import { t } from "./i18n";

export type SkinId = "escuela" | "corcho" | "laboratorio" | "cad" | "calma";

export type Skin = {
  id: SkinId;
  name: string;
  dark: boolean;   // tema oscuro de Excalidraw
  base: string;    // color liso del fondo: miniatura y lo que no admite degradados
  inkFilter?: string; // filtro CSS para la tinta en los skins claros con fondo de color
  darkCards?: boolean; // tarjetas oscuras: la tinta que las marca también se aclara (inkView)
};

// `name` es un getter: se traduce al leerlo, no al cargar el módulo (el idioma llega después).
export const SKINS: Skin[] = [
  { id: "escuela", get name() { return t("skin.escuela"); }, dark: true, base: "#2e4a3b" },
  { id: "corcho", get name() { return t("skin.corcho"); }, dark: false, base: "#b98a5a",
    inkFilter: "brightness(.62) saturate(1.5)" },
  { id: "laboratorio", get name() { return t("skin.laboratorio"); }, dark: false, base: "#f6f0e1",
    inkFilter: "brightness(.8) saturate(1.25)" },
  { id: "cad", get name() { return t("skin.cad"); }, dark: true, base: "#2b2e33", darkCards: true },
  { id: "calma", get name() { return t("skin.calma"); }, dark: false, base: "#f5f4f0" },
];

export const DEFAULT_SKIN: SkinId = "escuela";

export function skinOf(id: string | null | undefined): Skin {
  return SKINS.find((s) => s.id === id) ?? SKINS.find((s) => s.id === DEFAULT_SKIN)!;
}
