// La bienvenida (plan D186): la abre *Ajustes → General → Volver a ver la bienvenida* (que antes
// guarda `bienvenida_vista: false`) y, al arrancar, la app si aún no se ha visto. Cuatro pasos,
// con *Saltar* en todos: idioma y unidades, la sesión de Claude Code, los programas conectados
// (Fusion: el núcleo no nombra ningún paquete, P67, así que el paso enseña los conectores que
// haya, con el nombre que da su paquete) y dónde se guarda.
// Aquí, el estado (abierta, en qué paso) y la lógica que no pinta; la ventana es
// `WelcomeDialog.tsx`.
import { useSyncExternalStore } from "react";
import type { AppSettings } from "./appSettings";

export const WELCOME_STEPS = ["idioma", "sesion", "programas", "carpeta"] as const;
export type WelcomeStep = (typeof WELCOME_STEPS)[number];
export const LAST_STEP = WELCOME_STEPS.length - 1;

export type WelcomeState = { open: boolean; step: number };

let state: WelcomeState = { open: false, step: 0 };
const listeners = new Set<() => void>();

function set(patch: Partial<WelcomeState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

/** Abre la bienvenida por el primer paso (también si ya estaba abierta). */
export const openWelcome = () => set({ open: true, step: 0 });
export const closeWelcome = () => set({ open: false });
export const goToStep = (step: number) => set({ step: clampStep(step) });
export const getWelcome = () => state;

export function useWelcome(): WelcomeState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
  );
}

const clampStep = (step: number) => Math.max(0, Math.min(LAST_STEP, Math.trunc(step)));
export const nextStep = (step: number) => clampStep(step + 1);
export const prevStep = (step: number) => clampStep(step - 1);

/** ¿Sale sola al cargar los ajustes? Solo si han llegado y dicen que aún no se ha visto: sin
 *  ajustes (el backend no responde) nunca, para no enseñarla a quien ya la vio. */
export const welcomeOnLoad = (app: AppSettings | null): boolean => app !== null && app.bienvenida_vista === false;

/** ¿Se pinta ya el inicio o la pizarra? Solo con la vista elegida y los ajustes pedidos (hayan
 *  llegado o no): el idioma sale de ellos y Excalidraw toma el suyo al montarse. Pintada
 *  antes, la pizarra se quedaba con Excalidraw en español y la app en inglés (e2e de v0.1.0). */
export const readyToShow = (view: unknown, settingsTried: boolean): boolean => view !== null && settingsTried;

/** Lo que guardan *Terminar* y *Saltar* (y *Usar esta carpeta* antes de rearrancar). */
export const WELCOME_SEEN = { bienvenida_vista: true } as const;

/** *Terminar* o *Saltar*: guarda que ya se vio y cierra. Cierra aunque no se guarde (la
 *  bienvenida nunca bloquea): entonces vuelve a salir la próxima vez. Devuelve el motivo. */
export async function finishWelcome(
  save: (changes: Record<string, unknown>) => Promise<string | null>,
): Promise<string | null> {
  const why = await save({ ...WELCOME_SEEN });
  closeWelcome();
  return why;
}

// --- El paso de los programas: el estado de cada conector (`GET /api/connectors`) ----------

export type ConnectorState = "disponible" | "abriendose" | "cerrado";
export type ConnectorInfo = { name?: string; available?: boolean; launching?: boolean };

/** Abierto, abriéndose o sin abrir. Que el programa no está instalado no se sabe hasta pedir
 *  *Abrir* (`launch` da 404 con el motivo). */
export function connectorState(c: ConnectorInfo): ConnectorState {
  if (c.available) return "disponible";
  return c.launching ? "abriendose" : "cerrado";
}

/** Los conectores por su nombre (el de su paquete), con su id. Ninguno: no hay ningún paquete
 *  con un programa instalado. */
export function connectorList(connectors: Record<string, ConnectorInfo> | null | undefined) {
  return Object.entries(connectors ?? {})
    .map(([id, c]) => ({ id, name: c.name || id, state: connectorState(c) }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

// --- El paso de la carpeta: esperar al servidor rearrancado --------------------------------

/** La misma carpeta, aunque cambien las mayúsculas (Windows) o las barras. */
export function sameFolder(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const norm = (p: string) => p.replace(/[\\/]+/g, "/").replace(/\/$/, "").toLowerCase();
  return norm(a) === norm(b);
}

export const RESTART_WAIT_MS = 15000;    // lo más que se espera al servidor rearrancado

/** Health de `/api/health`: `null` si no responde (el servidor de antes ya se fue). */
export type Health = { workspace?: string | null } | null;

/** Espera al servidor rearrancado tras *Usar esta carpeta* (D186: mismo puerto, mismo token).
 *  Vale cuando `/api/health` ya da la carpeta nueva, o cuando vuelve a responder tras haber
 *  dejado de hacerlo (la ruta puede llegar resuelta de otra forma). false si pasan `ms`. */
export async function waitForRestart(
  ruta: string, health: () => Promise<Health>,
  { ms = RESTART_WAIT_MS, every = 300, sleep = (n: number) => new Promise((r) => setTimeout(r, n)),
    now = () => Date.now() } = {},
): Promise<boolean> {
  const end = now() + ms;
  let down = false;
  await sleep(every);                       // el de antes aún contesta unos 0,3 s
  while (now() < end) {
    const h = await health().catch(() => null);
    if (h === null) down = true;
    else if (down || sameFolder(h.workspace, ruta)) return true;
    await sleep(every);
  }
  return false;
}

/** El plan de la cuenta de Claude como se escribe (O17): `claude auth status` lo da en minúscula
 *  («max», «pro», «team») y es un nombre propio, el mismo en los dos idiomas: «Max», «Pro». Uno
 *  desconocido, con cada palabra en mayúscula («claude_max» → «Claude Max»). */
export function planLabel(raw: string): string {
  return raw.trim().split(/[\s_-]+/).filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(" ");
}
