// Lo que hace la interfaz con los hilos (D165-D167, D176): los mensajes `thread_*` del
// WebSocket (protocolo en `server.py`) y su reflejo en el store. Las reglas de la ventana
// están en `threads.ts`; lo que se pinta, en `ThreadLayer` y `ThreadClose`.
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { send } from "./socket";
import { getStore, setStore, type AgentEvent, type ThreadInfo } from "./store";
import { chromeFrom, clampWindow, defaultWindow, liveAnchors, THREAD_DEFAULT, toScreen, unplaced, type Chrome,
         type Layout, type Rect, type View } from "./threads";

type Api = ExcalidrawImperativeAPI;

/** El tamaño de la pizarra en pantalla (sin el panel derecho): lo que ocupa la capa de hilos. */
export function boardView(): View {
  const r = document.querySelector(".th-layer")?.getBoundingClientRect();
  if (r && r.width > 0) return { width: r.width, height: r.height };
  const rp = parseFloat(getComputedStyle(document.querySelector(".app") ?? document.body).getPropertyValue("--rp-w")) || 0;
  return { width: window.innerWidth - rp, height: window.innerHeight };
}

// La interfaz fija de la pizarra que nada de los hilos tapa (paso 5b, `threads.ts`): la barra
// de arriba entera (con su segunda fila si no cabe en una), el Filtro, y abajo la barra de
// herramientas, el zoom, la ayuda y el botón del panel plegado.
export const CHROME_NODES = {
  top: [".excalidraw .App-menu_top", ".project-pill"],
  bottom: [".excalidraw .App-toolbar-container", ".excalidraw .layer-ui__wrapper__footer-left",
           ".excalidraw .layer-ui__wrapper__footer-right", ".ag-fab"],
  others: [".pf"],
};

/** Esos nodos, por grupo (para observar si cambian de tamaño). */
export const chromeNodes = (group: keyof typeof CHROME_NODES) =>
  CHROME_NODES[group].flatMap((sel) => [...document.querySelectorAll<HTMLElement>(sel)]);

/** La interfaz fija medida ahora, relativa a la pizarra (la capa de hilos). */
export function measureChrome(): Chrome {
  const layer = document.querySelector(".th-layer")?.getBoundingClientRect();
  const ox = layer?.x ?? 0, oy = layer?.y ?? 0;
  const rects = (group: keyof typeof CHROME_NODES) => chromeNodes(group).map((n) => {
    const r = n.getBoundingClientRect();
    return { x: r.x - ox, y: r.y - oy, w: r.width, h: r.height };
  });
  return chromeFrom(boardView(), rects("top"), rects("bottom"), rects("others"));
}

/** La caja en pantalla de cada elemento vivo de `ids`. */
export function screenBoxes(api: Api, ids: readonly string[]) {
  const st = api.getAppState();
  const s = { scrollX: st.scrollX, scrollY: st.scrollY, zoom: st.zoom.value };
  const want = new Set(ids);
  const out = new Map<string, { x: number; y: number; width: number; height: number }>();
  for (const e of api.getSceneElements()) if (want.has(e.id)) out.set(e.id, toScreen(e, s));
  return out;
}

export const liveIdsOf = (api: Api) => new Set(api.getSceneElements().map((e) => e.id));

function placeNear(api: Api, anchors: readonly string[], size = THREAD_DEFAULT): Rect {
  const boxes = screenBoxes(api, anchors);
  const first = anchors.find((a) => boxes.has(a));
  return defaultWindow(first ? boxes.get(first)! : null, boardView(), size, measureChrome());
}

const findThread = (id: string) => getStore().threads.find((t) => t.id === id);

/** Pide sus mensajes si aún no están (al abrirlo en ventana o a pantalla completa). */
export function loadThread(id: string) {
  if (!getStore().threadLogs[id]) send({ type: "thread_history", id });
}

/** Cambia el tamaño o la posición de un hilo: en el store ya, y al backend si `push` (que lo
 *  guarda y lo reenvía a las otras ventanas). */
export function setLayout(id: string, layout: Partial<Layout>, push = true) {
  const { threads } = getStore();
  const t = threads.find((x) => x.id === id);
  if (!t) return;
  const next = { size: "window" as const, ...THREAD_DEFAULT, x: 0, y: 0, ...t.layout, ...layout };
  setStore({ threads: threads.map((x) => (x.id === id ? { ...x, layout: next } : x)) });
  if (push) send({ type: "thread_layout", id, layout: next });
}

/** Abre un hilo en ventana (o a pantalla completa). Una ventana nunca colocada se pone junto
 *  a su primer ancla; con `locate`, antes se lleva la vista a sus anclas. Solo uno a pantalla
 *  completa: el que lo estaba vuelve a ventana. */
export function openThread(api: Api | null, id: string, size: "window" | "full" = "window", locate = false,
                           fromList = locate) {
  const t = findThread(id);
  if (!t) return;
  loadThread(id);
  if (api && locate) {
    const live = liveIdsOf(api);
    const els = api.getSceneElements().filter((e) => liveAnchors(t.anchors, live).includes(e.id));
    if (els.length) {
      api.scrollToContent(els, { fitToViewport: false, animate: false });
      // El desplazamiento nuevo está en el estado de Excalidraw al siguiente fotograma.
      requestAnimationFrame(() => openThread(api, id, size, false, true));
      return;
    }
  }
  if (size === "full") {
    for (const o of getStore().threads) if (o.id !== id && o.layout?.size === "full") setLayout(o.id, { size: "window" });
  }
  const l = t.layout;
  // Desde la lista (`api` y la vista ya en sus anclas), la ventana se pone junto a ellas.
  const rect = api && (fromList || unplaced(l)) ? placeNear(api, t.anchors, { w: l?.w ?? THREAD_DEFAULT.w, h: l?.h ?? THREAD_DEFAULT.h })
    : clampWindow({ x: l?.x ?? 0, y: l?.y ?? 0, w: l?.w ?? THREAD_DEFAULT.w, h: l?.h ?? THREAD_DEFAULT.h },
                  boardView(), measureChrome());
  setLayout(id, { ...rect, size });
}

/** *Preguntar al agente* (D176): un hilo nuevo anclado a `anchors`, en ventana junto al
 *  primero, sin pregunta todavía; al llegar `thread_created` su caja de texto se lleva el foco. */
export function askAgent(api: Api, anchors: string[]) {
  const ids = [...new Set(anchors)].slice(0, 20);
  if (!ids.length) return;
  pendingFocus = true;
  send({ type: "thread_create", anchors: ids, layout: { size: "window", ...placeNear(api, ids) } });
}
let pendingFocus = false;

export function askInThread(id: string, text: string, once = false) {
  send({ type: "thread_ask", id, text, ...(once ? { once } : {}) });
}

/** *Cerrar con decisión* (D167): el agente propone la frase y el cuadro espera a que llegue. */
export function requestClose(id: string, once = false) {
  setStore({ threadClosing: { id, phase: "waiting", text: "", sources: [], estimate: false, error: null, note: null } });
  send({ type: "thread_close_request", id, ...(once ? { once } : {}) });
}

/** Escribirla uno mismo, sin esperar al agente (si estaba con ella, se le para). */
export function writeDecisionMyself() {
  const { threadClosing: c, threadBusy } = getStore();
  if (!c) return;
  if (threadBusy === c.id) send({ type: "agent_stop" });
  const t = findThread(c.id);
  setStore({ threadClosing: { ...c, phase: "edit", text: c.text || t?.proposed?.text || "", note: null } });
}

export function cancelClose() {
  const { threadClosing: c, threadBusy } = getStore();
  if (c && c.phase === "waiting" && threadBusy === c.id) send({ type: "agent_stop" });
  setStore({ threadClosing: null });
}

export function saveDecision() {
  const c = getStore().threadClosing;
  if (!c || !c.text.trim()) return;
  setStore({ threadClosing: { ...c, phase: "saving", error: null } });
  send({ type: "thread_close", id: c.id,
         decision: { text: c.text.trim(), sources: c.sources, estimate: c.estimate } });
}

export const reopenThread = (id: string) => send({ type: "thread_reopen", id });
export const deleteThread = (id: string) => send({ type: "thread_delete", id });

/** Un `error` del backend mientras se cierra un hilo es del cuadro (p. ej. cifras sin fuente,
 *  D19): se enseña allí y no en la lista de avisos. Devuelve si lo ha recogido. */
export function threadError(message: string): boolean {
  const c = getStore().threadClosing;
  if (!c || c.phase === "edit") return false;
  // Sin el nombre de la excepción de Python con que llega («ValidationError: …»).
  setStore({ threadClosing: { ...c, phase: "edit", error: message.replace(/^\w+Error: /, "") } });
  return true;
}

/** Los mensajes `thread_*` y `threads` del servidor. Devuelve si era uno de ellos. */
export function handleThreadMessage(msg: any): boolean {
  const st = getStore();
  switch (msg.type) {
    case "threads": {
      const threads: ThreadInfo[] = msg.threads ?? [];
      const ids = new Set(threads.map((t) => t.id));
      const logs = Object.fromEntries(Object.entries(st.threadLogs).filter(([id]) => ids.has(id)));
      const c = st.threadClosing;
      const closed = c && (!ids.has(c.id) || threads.find((t) => t.id === c.id)?.state === "decidido");
      setStore({ threads, threadLogs: logs, ...(closed ? { threadClosing: null } : {}) });
      return true;
    }
    case "thread_created": {
      const t: ThreadInfo = msg.thread;
      const known = st.threads.some((x) => x.id === t.id);
      setStore({ threads: known ? st.threads : [...st.threads, t], threadLogs: { ...st.threadLogs, [t.id]: [] },
                 ...(pendingFocus ? { threadFocus: t.id } : {}) });
      pendingFocus = false;
      return true;
    }
    case "thread_history": {
      const events: AgentEvent[] = (msg.events ?? []).map((e: AgentEvent) => ({ ...e, thread: msg.id }));
      setStore({ threadLogs: { ...st.threadLogs, [msg.id]: events },
                 threads: msg.thread ? st.threads.map((x) => (x.id === msg.id ? { ...x, ...msg.thread } : x)) : st.threads });
      return true;
    }
    case "thread_layout":
      setLayout(msg.id, msg.layout, false);
      if (msg.layout?.size && msg.layout.size !== "min") loadThread(msg.id);
      return true;
    default:
      return false;
  }
}
