// Cuánto se compacta la barra de arriba (O17): la píldora del proyecto, la barra y el botón de la
// biblioteca de Excalidraw comparten una fila en lo que queda de pizarra con el panel derecho
// abierto (`--rp-w`, D174). A 1440 px con el panel abierto quedan ~1020 px: con las etiquetas
// enteras la barra pasaba a dos filas y la píldora se comía el nombre del proyecto.
//
// 0: todo con su texto. 1: Tinta, Añadir archivo y Nuevo archivo solo con su icono (el texto,
// en el `title`). 2: también Bloque, Ejecutar lo desactualizado y la cuenta de propuestas.
// Los anchos de corte salen de medir la barra en español, la más larga (~860 px enteros, ~610
// en el nivel 1 y ~420 en el 2), más la píldora (~400 con un nombre de 20 letras), la
// biblioteca (~100) y los márgenes.
export type BarDensity = 0 | 1 | 2;
export const FULL_BAR_MIN = 1480;
export const ICON_BAR_MIN = 1200;

export function barDensity(boardWidth: number): BarDensity {
  if (boardWidth >= FULL_BAR_MIN) return 0;
  return boardWidth >= ICON_BAR_MIN ? 1 : 2;
}
