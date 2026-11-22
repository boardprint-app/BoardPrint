// Token del backend local. El shell abre la ventana con ?token=...; se guarda para la sesión
// (sobrevive a recargar) y se quita de la barra de direcciones. En desarrollo no hay token.
const KEY = "pizarra-token";

// Los `.bppack` con los que se abrió la app (doble clic en el explorador, PLAN_PAQUETES P82):
// el shell los pone en la URL como `open=`. Se leen aquí, antes de que `readToken` limpie la
// barra de direcciones.
export const launchFiles: string[] = new URLSearchParams(location.search).getAll("open");

function readToken(): string | null {
  const fromUrl = new URLSearchParams(location.search).get("token");
  try {
    if (fromUrl) {
      sessionStorage.setItem(KEY, fromUrl);
      history.replaceState(null, "", location.pathname);
      return fromUrl;
    }
    return sessionStorage.getItem(KEY);
  } catch {
    return fromUrl;
  }
}

export const token = readToken();

export function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (token) headers.set("X-Token", token);
  return fetch(path, { ...init, headers });
}

// Un WebSocket por proyecto abierto (plan D69).
export function wsUrl(project: string) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const q = new URLSearchParams({ project });
  if (token) q.set("token", token);
  return `${proto}://${location.host}/ws?${q}`;
}

// El del agente de onboarding (PLAN_ONBOARDING N10): del workspace, sin proyecto.
export function wsOnboardingUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const q = new URLSearchParams();
  if (token) q.set("token", token);
  return `${proto}://${location.host}/ws/onboarding${token ? `?${q}` : ""}`;
}
