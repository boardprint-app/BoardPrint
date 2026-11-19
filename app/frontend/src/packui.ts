// Protocolo v1 entre la tarjeta (o el panel) y la interfaz propia de un paquete, que corre en
// un `iframe` aislado (docs/PLAN_PAQUETES.md §5, P24). Sin React: lo usa PackFrame.tsx y lo
// prueban los tests.
//
// La interfaz no elige nunca a qué bloque habla: cada marco tiene sus efectos atados a su
// bloque (P6), y un `block` dentro de un mensaje no cuenta. Lo que cambia el bloque va por el
// mismo `set_params` que la tarjeta, con la validación del backend de siempre; una `action`, a
// la ruta del bloque, que solo llega a las acciones de su paquete (P46). Un mensaje que no es
// del protocolo se ignora y se apunta (`ignore`): nunca cambia nada.
//
// Un bloque con conector (P41) lleva además la **parte del conector**: la interfaz propia del
// paquete del conector en otro marco, atado al mismo bloque, que solo puede cambiar los
// parámetros que dibuja ese paquete (los de un control `<conector>.<x>`) y solo llamar a sus
// acciones (`<conector>.<acción>`). Lo ve todo igual que la parte del bloque.
import type { BlockState, BlockType, Value } from "./store";

export const PROTOCOL = 1;

/** Alto de la interfaz en la tarjeta: el mínimo de D60 lo pone la tarjeta (BLOCK_MIN_HEIGHT);
 *  aquí solo que no se quede en nada ni crezca sin fin. */
export const FRAME_MIN_H = 40;
export const FRAME_MAX_H = 2000;
const TOAST_MAX = 300;
const ID_MAX = 64;

export type Surface = "card" | "panel";
/** De quién es el marco: del paquete del bloque o del de su conector (P41). */
export type Part = "block" | "connector";
export type ToastKind = "info" | "error";

/** Lo que la interfaz puede pedir (interfaz → app). */
export type Request =
  | { type: "ready" }
  | { type: "setParams"; params: Record<string, unknown> }
  | { type: "preview"; id: string | number; params: Record<string, unknown> }
  | { type: "action"; id: string | number; name: string; args: Record<string, unknown> }
  | { type: "run" }
  | { type: "openPanel" }
  | { type: "closePanel" }
  | { type: "resize"; height: number }
  | { type: "toast"; text: string; kind: ToastKind }
  | { type: "wheel"; wheel: Wheel };

/** La rueda que la página no usa (P54): la manda el puente que el backend mete en la página
 *  (pack_ui.py). Coordenadas en píxeles de la página; la tarjeta la pasa al lienzo. */
export type Wheel = { dx: number; dy: number; mode: number; x: number; y: number;
                      ctrl: boolean; meta: boolean; shift: boolean; alt: boolean };
export const WHEEL_MAX = 2000;    // un giro de rueda o de trackpad nunca pasa de unos cientos

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isId = (v: unknown): v is string | number =>
  (typeof v === "string" && v.length > 0 && v.length <= ID_MAX) || (typeof v === "number" && Number.isFinite(v));

/** El mensaje como `Request`, o el motivo por el que no lo es. */
export function parse(data: unknown): Request | { ignored: string } {
  if (!isObj(data)) return { ignored: "no es un objeto" };
  if (data.v !== PROTOCOL) return { ignored: `versión ${JSON.stringify(data.v)} (la de la app es ${PROTOCOL})` };  // i18n-ok motivo para el log
  switch (data.type) {
    case "ready": case "run": case "openPanel": case "closePanel":
      return { type: data.type };
    case "setParams":
      return isObj(data.params) ? { type: "setParams", params: data.params } : { ignored: "setParams sin params" };
    case "preview":
      if (!isId(data.id)) return { ignored: "preview sin id" };
      return isObj(data.params ?? {}) ? { type: "preview", id: data.id, params: (data.params ?? {}) as Record<string, unknown> }
        : { ignored: "preview con params que no son un objeto" };
    case "action":
      if (!isId(data.id)) return { ignored: "action sin id" };
      if (typeof data.name !== "string" || !data.name) return { ignored: "action sin name" };
      return isObj(data.args ?? {}) ? { type: "action", id: data.id, name: data.name, args: (data.args ?? {}) as Record<string, unknown> }
        : { ignored: "action con args que no son un objeto" };
    case "resize":
      return typeof data.height === "number" && Number.isFinite(data.height)
        ? { type: "resize", height: clampHeight(data.height) } : { ignored: "resize sin height" };
    case "toast":
      return typeof data.text === "string" && data.text.trim()
        ? { type: "toast", text: data.text.trim().slice(0, TOAST_MAX), kind: data.kind === "error" ? "error" : "info" }
        : { ignored: "toast sin texto" };
    case "wheel": {
      const num = (k: string) => typeof data[k] === "number" && Number.isFinite(data[k]);
      if (!["dx", "dy", "x", "y"].every(num)) return { ignored: "wheel sin dx, dy, x o y numéricos" };  // i18n-ok motivo para el log
      const d = (k: string) => Math.max(-WHEEL_MAX, Math.min(WHEEL_MAX, data[k] as number));
      return { type: "wheel", wheel: {
        dx: d("dx"), dy: d("dy"), mode: [0, 1, 2].includes(data.mode as number) ? data.mode as number : 0,
        x: data.x as number, y: data.y as number,
        ctrl: data.ctrl === true, meta: data.meta === true, shift: data.shift === true, alt: data.alt === true,
      } };
    }
    default:
      return { ignored: `tipo desconocido ${JSON.stringify(data.type)}` };
  }
}

export function clampHeight(h: number): number {
  return Math.round(Math.min(FRAME_MAX_H, Math.max(FRAME_MIN_H, h)));
}

type Rect = { left: number; top: number; width: number; height: number };

/** La rueda de la página como evento del lienzo: el punto pasa a la pantalla con la escala del
 *  zoom (`rect` es el del marco en pantalla; `innerWidth`, su ancho en píxeles de la página) y
 *  nunca cae fuera del marco, diga lo que diga la página. */
export function wheelInit(w: Wheel, rect: Rect, innerWidth: number) {
  const s = innerWidth > 0 ? rect.width / innerWidth : 1;
  const clamp = (v: number, lo: number, len: number) => Math.min(lo + len, Math.max(lo, v));
  return {
    deltaX: w.dx, deltaY: w.dy, deltaMode: w.mode,
    clientX: clamp(rect.left + w.x * s, rect.left, rect.width),
    clientY: clamp(rect.top + w.y * s, rect.top, rect.height),
    ctrlKey: w.ctrl, metaKey: w.meta, shiftKey: w.shift, altKey: w.alt,
  };
}

/** Lo que hace la app con cada petición, ya atado al bloque del marco. */
export type Effects = {
  ready(): void;                                       // vuelve a mandar `init`
  setParams(params: Record<string, unknown>): void;    // el `set_params` de la tarjeta
  preview(params: Record<string, unknown>): Promise<unknown>;
  action(name: string, args: Record<string, unknown>): Promise<unknown>;
  run(): void;
  openPanel(): boolean;                                // false: el bloque no tiene panel
  closePanel(): void;                                  // solo cierra desde el panel
  resize(height: number): void;
  toast(text: string, kind: ToastKind): void;
  wheel(w: Wheel): void;                               // al lienzo (solo en la tarjeta)
  reply(msg: Reply): void;                            // respuesta a preview y action
  ignore(reason: string, data: unknown): void;         // se apunta; nada más
};

export type Reply = { v: typeof PROTOCOL; type: "reply"; id: string | number } &
  ({ ok: true; result: unknown } | { ok: false; error: string });

/** Atiende un mensaje del marco. `fromFrame`: viene del `contentWindow` de **este** marco
 *  (el origen es opaco, `"null"`, y no sirve para distinguirlo de otro). */
export async function handle(data: unknown, fromFrame: boolean, fx: Effects): Promise<void> {
  if (!fromFrame) return;           // de otra ventana u otro marco: ni se apunta
  const m = parse(data);
  if ("ignored" in m) return fx.ignore(m.ignored, data);
  switch (m.type) {
    case "ready": return fx.ready();
    case "setParams": return fx.setParams(m.params);
    case "run": return fx.run();
    case "openPanel": if (!fx.openPanel()) fx.ignore("openPanel: el bloque no declara panel", data); return;
    case "closePanel": return fx.closePanel();
    case "resize": return fx.resize(m.height);
    case "toast": return fx.toast(m.text, m.kind);
    case "wheel": return fx.wheel(m.wheel);
    case "preview": case "action": {
      const p = m.type === "preview" ? fx.preview(m.params) : fx.action(m.name, m.args);
      try {
        fx.reply({ v: PROTOCOL, type: "reply", id: m.id, ok: true, result: await p });
      } catch (e) {
        fx.reply({ v: PROTOCOL, type: "reply", id: m.id, ok: false, error: e instanceof Error ? e.message : String(e) });
      }
    }
  }
}

// --- app → interfaz ------------------------------------------------------------------------

/** Variables del skin (skins.css) que recibe la interfaz: las del papel de la tarjeta y las de
 *  los controles del panel. `--bp-bg` y `--bp-fg` son las de su sitio. */
export const THEME_VARS = [
  "--paper", "--paper-fg", "--paper-muted", "--ui-bg", "--ui-fg", "--ui-muted", "--ui-line",
  "--ui-hover", "--accent", "--accent-fg", "--focus", "--b-err", "--pc-ok", "--pc-no", "--f-ui",
] as const;

/** Hoja base (P24): lo justo para que una interfaz sin estilos se parezca a la app. */
export const BASE_CSS = `
html, body { margin: 0; background: transparent; color: var(--bp-fg); font: 13px/1.35 var(--f-ui); }
body { padding: 0; overflow-wrap: anywhere; }
a { color: var(--accent); }
button, input, select, textarea { font: inherit; color: inherit; }
button { background: var(--bp-btn-bg); color: var(--bp-btn-fg); border: 1px solid var(--bp-line);
  border-radius: 6px; padding: 3px 10px; cursor: pointer; }
button:hover:not(:disabled) { filter: brightness(1.08); }
button:disabled { opacity: .5; cursor: default; }
input, select, textarea { background: transparent; border: 1px solid var(--bp-line); border-radius: 4px; padding: 2px 4px; }
input:focus, select:focus, textarea:focus, button:focus-visible { outline: 2px solid var(--accent); outline-offset: -1px; }
table { border-collapse: collapse; }
th, td { text-align: left; padding: 2px 6px; border-bottom: 1px solid var(--bp-line); }
.bp-muted { color: var(--bp-muted); }
.bp-error { color: var(--b-err); }
`;

/** El tema de un sitio: variables del skin, ya calculadas por la app, y la hoja base. */
export function theme(skin: string, dark: boolean, vars: Record<string, string>, surface: Surface) {
  const card = surface === "card";
  const site: Record<string, string> = {
    "--bp-bg": card ? vars["--paper"] ?? "" : vars["--ui-bg"] ?? "",
    "--bp-fg": card ? vars["--paper-fg"] ?? "" : vars["--ui-fg"] ?? "",
    "--bp-muted": card ? vars["--paper-muted"] ?? "" : vars["--ui-muted"] ?? "",
    "--bp-line": card ? "rgba(0,0,0,.25)" : vars["--ui-line"] ?? "",
    "--bp-btn-bg": card ? vars["--paper-fg"] ?? "" : vars["--ui-hover"] ?? "",
    "--bp-btn-fg": card ? vars["--paper"] ?? "" : vars["--ui-fg"] ?? "",
  };
  const all = { ...vars, ...site };
  const root = Object.entries(all).filter(([, v]) => v).map(([k, v]) => `${k}: ${v};`).join(" ");
  return { skin, dark, vars: all, css: `:root { ${root} }\n${BASE_CSS}` };
}

/** Lo que no es del bloque y la interfaz necesita para pintarlo (P41): si el programa de su
 *  conector responde, si hay una ejecución en curso en el proyecto (D89: nada se ejecuta ni se
 *  aplica mientras tanto) y el nombre del proyecto (el destino por defecto lleva su nombre). */
export type FrameEnv = {
  part: Part;
  connector: { id: string; available: boolean; launching: boolean } | null;
  busy: boolean;
  project: string;
};
export const BLOCK_ENV: FrameEnv = { part: "block", connector: null, busy: false, project: "" };

export type FrameState = {
  surface: Surface;
  part: Part;
  block: { id: string; type: string; title: string };
  params: Record<string, unknown>;
  specs: BlockType["params"];
  inputs: Record<string, { type: string; connected: boolean; optional: boolean }>;
  outputs: Record<string, Record<string, Value>> | null;
  status: BlockState["status"];
  error: string | null;
  /** Sabe traer de su programa (D116) y ya se le envió algo; qué propone fijar (D121). */
  pull: boolean;
  synced: boolean;
  fix: { port: string; field: string; label: string } | null;
  connector: FrameEnv["connector"];
  busy: boolean;
  project: string;
  theme: ReturnType<typeof theme>;
  lang: string;
  /** El catálogo del paquete del marco en `lang` (`locales/<lang>.toml`, O15): `{texto de
   *  origen: traducción}`, con patrones `{nombre}`. Vacío en el idioma de origen o sin
   *  catálogo. Opcional para el paquete: un campo más del protocolo v1. */
  i18n: Record<string, string>;
};

/** Lo que ve la interfaz de su bloque (P6): nada de otros bloques ni de la escena. De las
 *  entradas, solo el tipo y si están conectadas; los valores que le lleguen los pide con
 *  `action` o `preview`, que el paquete calcula con ellos en el backend. */
export function frameState(id: string, blockType: string, ty: BlockType, st: BlockState | undefined, surface: Surface,
                           th: ReturnType<typeof theme>, env: FrameEnv = BLOCK_ENV, lang = "es",
                           i18n: Record<string, string> = {}): FrameState {
  const params: Record<string, unknown> = {};
  for (const [k, spec] of Object.entries(ty.params)) params[k] = st?.params?.[k] ?? spec.default;
  return {
    surface,
    part: env.part,
    block: { id, type: blockType, title: ty.title },
    params,
    specs: ty.params,
    inputs: Object.fromEntries(Object.entries(ty.inputs).map(([port, type]) =>
      [port, { type, connected: !!st?.inputs?.[port], optional: !!ty.optional?.includes(port) }])),
    outputs: st?.outputs ?? null,
    status: st?.status ?? "nunca",
    error: st?.error ?? null,
    pull: !!ty.pull,
    synced: !!st?.synced,
    fix: ty.fix ?? null,
    connector: env.connector,
    busy: env.busy,
    project: env.project,
    theme: th,
    lang,
    i18n,
  };
}

export const initMsg = (s: FrameState) => ({ v: PROTOCOL, type: "init" as const, ...s });
export const updateMsg = (s: FrameState) => ({ v: PROTOCOL, type: "update" as const, ...s });

/** Cómo se cierra el panel de un bloque (P71). Con una interfaz de paquete dentro (la del bloque
 *  o la parte de su conector), **nunca con un clic fuera**: la app no sabe si dentro hay un
 *  borrador (el árbol de un terminal a medio editar). Con la del bloque (`panel = "ui"`),
 *  tampoco con el *Cerrar* y el Escape de la app: los pone la interfaz, que cierra con
 *  `closePanel` cuando toca. Solo con controles genéricos, con todo. `connector`: el panel
 *  lleva la parte del conector (`connectorPart`). */
export function panelClosing(ty: BlockType | undefined, connector: boolean) {
  const own = ty?.view?.panel === "ui";
  return { outside: !own && !connector, chrome: !own };
}

/** URL de la interfaz de un paquete (P47): `entry` es la de `[ui] entry`, dentro de `ui/`. */
export function frameUrl(pack: string, entry: string): string {
  return `/packs/${encodeURIComponent(pack)}/${entry.split("/").map(encodeURIComponent).join("/")}`;
}

// --- la parte del conector (P41) --------------------------------------------------------------

/** El paquete que dibuja un control (`widget = "<paquete>.<x>"`), o null si es de la app. */
export function widgetPack(widget: string | undefined): string | null {
  const i = (widget ?? "").indexOf(".");
  return i > 0 ? widget!.slice(0, i) : null;
}

/** Los parámetros del bloque que dibuja la parte de su conector: los de un control del paquete
 *  del conector. La tarjeta de la app no los pinta. */
export function connectorParams(ty: BlockType): string[] {
  return ty.connector
    ? Object.entries(ty.params).filter(([, p]) => widgetPack(p.widget) === ty.connector).map(([n]) => n)
    : [];
}

/** Si la tarjeta del bloque lleva la parte de su conector: solo si tiene algo de él (P41: un
 *  control suyo, *Traer* o *Fijar*). Sin eso el marco no pintaría nada y dejaría un hueco. */
export function connectorCardWanted(ty: BlockType): boolean {
  return connectorParams(ty).length > 0 || !!ty.pull || !!ty.fix;
}

/** Lo que la parte del conector puede cambiar de `params`: solo los suyos. El resto se descarta
 *  (y se apunta): nunca llega al backend. */
export function connectorSetParams(ty: BlockType, params: Record<string, unknown>) {
  const own = new Set(connectorParams(ty));
  const keep = Object.fromEntries(Object.entries(params).filter(([k]) => own.has(k)));
  return { keep, dropped: Object.keys(params).filter((k) => !own.has(k)) };
}

/** Si la parte del conector puede llamar a la acción `name`: solo a las de su paquete. El
 *  motivo si no. */
export function connectorActionError(ty: BlockType, name: string): string | null {
  return ty.connector && name.startsWith(`${ty.connector}.`) ? null
    : `la parte del conector ${ty.connector ?? "?"} solo llama a sus acciones (${name})`;
}
