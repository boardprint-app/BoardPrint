// Los atajos de Excalidraw que puede pisar uno de la app (plan D97, D185): solo los de una
// letra o una cifra, que son los únicos que puede tener un atajo de la app. Excalidraw no los
// exporta: están copiados a mano de su código para la versión instalada
// (node_modules/@excalidraw/excalidraw/dist/dev: las `keyTest` de sus acciones, `SHAPES` con
// las teclas de las herramientas y el `onKeyDown` de su App, que comprueba la paleta de
// comandos, el láser, el bloqueo, los colores y el cuentagotas). Valen para EXCALIDRAW_VERSION:
// `shortcuts.test.ts` falla si package.json pide otra, y entonces se repasan.
//
// Las herramientas solo saltan con la tecla sola (sin Ctrl, Alt ni Mayús: con Mayús la letra
// llega en mayúscula y no casa); Ctrl vale también por Cmd. `app` marca los que ya atiende la
// propia app antes que Excalidraw (encuadrar, fit.ts): no son choque para esa acción.
// Fuera quedan los que no son una letra ni una cifra (Supr, flechas, +, -, [, ], ', /, ?) y
// Alt+Mayús+D (el tema), que la app tiene apagado (`toggleTheme: false` en App.tsx).

export const EXCALIDRAW_VERSION = "0.18.0";

/** `combo` en forma canónica (shortcuts.ts, `normalizeCombo`); `name`, la clave del texto. */
export type ExcalidrawKey = { combo: string; name: string; app?: string };

export const EXCALIDRAW_KEYS: ExcalidrawKey[] = [
  // Herramientas (SHAPES): letra y cifra
  { combo: "V", name: "excalidraw.seleccion" }, { combo: "1", name: "excalidraw.seleccion" },
  { combo: "R", name: "excalidraw.rectangulo" }, { combo: "2", name: "excalidraw.rectangulo" },
  { combo: "D", name: "excalidraw.rombo" }, { combo: "3", name: "excalidraw.rombo" },
  { combo: "O", name: "excalidraw.elipse" }, { combo: "4", name: "excalidraw.elipse" },
  { combo: "A", name: "excalidraw.flecha" }, { combo: "5", name: "excalidraw.flecha" },
  { combo: "L", name: "excalidraw.linea" }, { combo: "6", name: "excalidraw.linea" },
  { combo: "P", name: "excalidraw.lapiz" }, { combo: "X", name: "excalidraw.lapiz" },
  { combo: "7", name: "excalidraw.lapiz" },
  { combo: "T", name: "excalidraw.texto" }, { combo: "8", name: "excalidraw.texto" },
  { combo: "9", name: "excalidraw.imagen" },
  { combo: "E", name: "excalidraw.borrador" }, { combo: "0", name: "excalidraw.borrador" },
  // Otras herramientas y teclas sueltas
  { combo: "H", name: "excalidraw.mano" },
  { combo: "K", name: "excalidraw.laser" },
  { combo: "F", name: "excalidraw.marco" },
  { combo: "Q", name: "excalidraw.bloquear_herramienta" },
  { combo: "I", name: "excalidraw.cuentagotas" },
  { combo: "S", name: "excalidraw.color_trazo" },
  { combo: "G", name: "excalidraw.color_fondo" },
  // Con Mayús
  { combo: "Mayús+1", name: "excalidraw.encuadrar_todo", app: "view.fit_all" },   // i18n-ok: combo canónico
  { combo: "Mayús+2", name: "excalidraw.encuadrar_seleccion", app: "view.fit_selection" },   // i18n-ok: combo canónico
  { combo: "Mayús+3", name: "excalidraw.encuadrar_vista", app: "view.fit_viewport" },   // i18n-ok: combo canónico
  { combo: "Mayús+0", name: "excalidraw.zoom_100" },   // i18n-ok: combo canónico
  { combo: "Mayús+H", name: "excalidraw.voltear_h" },   // i18n-ok: combo canónico
  { combo: "Mayús+V", name: "excalidraw.voltear_v" },   // i18n-ok: combo canónico
  { combo: "Mayús+S", name: "excalidraw.cuentagotas_trazo" },   // i18n-ok: combo canónico
  { combo: "Mayús+G", name: "excalidraw.cuentagotas_fondo" },   // i18n-ok: combo canónico
  { combo: "Mayús+F", name: "excalidraw.fuente" },   // i18n-ok: combo canónico
  // Con Alt
  { combo: "Alt+Z", name: "excalidraw.zen" },
  { combo: "Alt+S", name: "excalidraw.ajuste_objetos" },
  { combo: "Alt+R", name: "excalidraw.modo_vista" },
  { combo: "Alt+H", name: "excalidraw.distribuir_h" },
  { combo: "Alt+V", name: "excalidraw.distribuir_v" },
  { combo: "Mayús+Alt+C", name: "excalidraw.copiar_png" },   // i18n-ok: combo canónico
  // Con Ctrl
  { combo: "Ctrl+Z", name: "excalidraw.deshacer" },
  { combo: "Ctrl+Y", name: "excalidraw.rehacer" },
  { combo: "Ctrl+Mayús+Z", name: "excalidraw.rehacer" },   // i18n-ok: combo canónico
  { combo: "Ctrl+A", name: "excalidraw.seleccionar_todo" },
  { combo: "Ctrl+C", name: "excalidraw.copiar" },
  { combo: "Ctrl+V", name: "excalidraw.pegar" },
  { combo: "Ctrl+Mayús+V", name: "excalidraw.pegar_texto" },   // i18n-ok: combo canónico
  { combo: "Ctrl+X", name: "excalidraw.cortar" },
  { combo: "Ctrl+D", name: "excalidraw.duplicar" },
  { combo: "Ctrl+G", name: "excalidraw.agrupar" },
  { combo: "Ctrl+Mayús+G", name: "excalidraw.desagrupar" },   // i18n-ok: combo canónico
  { combo: "Ctrl+K", name: "excalidraw.enlace" },
  { combo: "Ctrl+Mayús+L", name: "excalidraw.bloquear" },   // i18n-ok: combo canónico
  { combo: "Ctrl+F", name: "excalidraw.buscar" },
  { combo: "Ctrl+S", name: "excalidraw.guardar" },
  { combo: "Ctrl+Mayús+S", name: "excalidraw.guardar_archivo" },   // i18n-ok: combo canónico
  { combo: "Ctrl+O", name: "excalidraw.abrir" },
  { combo: "Ctrl+Mayús+E", name: "excalidraw.exportar_imagen" },   // i18n-ok: combo canónico
  { combo: "Ctrl+P", name: "excalidraw.paleta" },
  { combo: "Ctrl+Mayús+P", name: "excalidraw.paleta" },   // i18n-ok: combo canónico
  { combo: "Ctrl+0", name: "excalidraw.zoom_100" },
  { combo: "Ctrl+Alt+C", name: "excalidraw.copiar_estilos" },
  { combo: "Ctrl+Alt+V", name: "excalidraw.pegar_estilos" },
];
