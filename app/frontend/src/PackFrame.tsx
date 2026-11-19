// La interfaz propia de un paquete en su `iframe` aislado (docs/PLAN_PAQUETES.md §5, P24),
// en la tarjeta del bloque o en su panel. El protocolo está en packui.ts; aquí solo se ata al
// bloque, a la app y al marco.
//
// `sandbox="allow-scripts"` sin `allow-same-origin`: origen opaco, sin acceso a la app, sin
// ventanas nuevas ni navegar la pestaña. La red la corta la CSP de lo servido (P47), y que el
// marco navegue él mismo a otra web la corta `frame-src 'self'` de la app (index.html). Si aun
// así el marco carga otra página (otra vez la suya, la de otro paquete), se descarta: el
// primer `load` es el suyo y cualquier otro es una navegación (riesgo 9).
//
// `part="connector"` (P41): la interfaz del paquete del conector del bloque, en su propio marco
// y atada al mismo bloque; solo cambia los parámetros que dibuja y solo llama a sus acciones.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { apiFetch } from "./auth";
import { getLanguage, t } from "./i18n";
import { mergedCatalog } from "./packI18n";
import { fetchPreview } from "./blockPreview";
import { send } from "./socket";
import { getStore, setStore, useStore, type BlockType, type ConnectorInfo } from "./store";
import { skinOf } from "./skins";
import { connectorActionError, connectorCardWanted, connectorSetParams, frameState, frameUrl, handle, initMsg, theme, THEME_VARS,
         updateMsg, wheelInit, type Effects, type FrameEnv, type Part, type Surface } from "./packui";
import { wheelOnCanvas } from "./block";
import { readSkin, subscribeSkin } from "./skinWatch";

const NO_CATALOG: Record<string, string> = {};   // el mismo objeto siempre: no rehace el estado

// Último alto que pidió cada marco de tarjeta: al volver a montarse (Excalidraw desmonta lo que
// sale de la vista) arranca con él y la tarjeta no encoge y crece mientras la página carga.
const FRAME_H = new Map<string, number>();

function themeVars(): Record<string, string> {
  const cs = getComputedStyle(document.documentElement);
  return Object.fromEntries(THEME_VARS.map((n) => [n, cs.getPropertyValue(n).trim()]));
}

/** El bloque abre panel (§5): la interfaz propia o controles genéricos. Es lo que abre
 *  *Editar*; la parte del conector no cuenta (`connectorPart`). */
export function hasPanel(ty: BlockType | undefined): boolean {
  const p = ty?.view?.panel;
  return p === "ui" || (Array.isArray(p) && p.length > 0);
}

/** El paquete del conector del bloque pone su parte en `surface` (P41); en la tarjeta, solo si
 *  el bloque tiene algo del conector (`connectorCardWanted`). */
export function connectorPart(ty: BlockType | undefined, info: Record<string, ConnectorInfo>,
                              surface: Surface): boolean {
  const c = ty?.connector ? info[ty.connector] : undefined;
  return !!c && !!ty && (surface === "card" ? c.card && connectorCardWanted(ty) : c.panel);
}

/** `POST …/blocks/<b>/action`: una acción del paquete del bloque o de su conector (P40, P41),
 *  con la respuesta tal cual (`{result}` o `{detail}`). */
export function blockAction(block: string, name: string, args: Record<string, unknown> = {}) {
  const pid = getStore().project?.id ?? "";
  return apiFetch(`/api/projects/${encodeURIComponent(pid)}/blocks/${encodeURIComponent(block)}/action`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, args }),
  });
}

async function postAction(block: string, name: string, args: Record<string, unknown>) {
  const r = await blockAction(block, name, args);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(body?.detail ?? `error ${r.status}`);
  return body?.result;
}

type Props = { id: string; blockType: string; surface: Surface; part?: Part };

export function PackFrame({ id, blockType, surface, part = "block" }: Props) {
  const { blocks, types, packs, connectors, run, project } = useStore();
  const ty = types[blockType];
  const st = blocks[id];
  const packId = part === "connector" ? ty?.connector : ty?.pack;
  const pack = packs.find((p) => p.id === packId && !p.error);
  const con = ty?.connector ? connectors[ty.connector] : undefined;
  const busy = run !== null;
  const env: FrameEnv = useMemo(() => ({
    part,
    connector: ty?.connector
      ? { id: ty.connector, available: !!con?.available, launching: !!con?.launching } : null,
    busy,
    project: project?.name ?? "",
  }), [part, ty?.connector, con?.available, con?.launching, busy, project?.name]);
  const skin = useSyncExternalStore(subscribeSkin, readSkin);
  const frame = useRef<HTMLIFrameElement>(null);
  const loads = useRef(0);
  const sent = useRef<string | null>(null);          // lo último mandado, para no repetir `update`
  const hKey = `${id}:${part}`;
  const [height, setHeight] = useState(() => FRAME_H.get(hKey) ?? 120);
  const [gone, setGone] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const th = useMemo(() => theme(skin, skinOf(skin).dark, themeVars(), surface), [skin, surface]);
  const lang = getLanguage();
  // el catálogo del paquete del marco (el del conector, en su parte): la interfaz traduce lo suyo
  // (el suyo sobre los de los demás paquetes cargados, como `tp`)
  const i18n = packId ? mergedCatalog(packId, lang, packs) : NO_CATALOG;
  const state = useMemo(() => (ty ? frameState(id, blockType, ty, st, surface, th, env, lang, i18n) : null),
                        [id, blockType, ty, st, surface, th, env, lang, i18n]);
  const stateRef = useRef(state);
  stateRef.current = state;

  const post = (msg: unknown) => frame.current?.contentWindow?.postMessage(msg, "*");   // origen opaco
  const sendInit = () => {
    const s = stateRef.current;
    if (!s) return;
    sent.current = JSON.stringify(s);
    post(initMsg(s));
  };

  useEffect(() => {
    if (!state || sent.current === null) return;
    const json = JSON.stringify(state);
    if (json === sent.current) return;
    sent.current = json;
    post(updateMsg(state));
  }, [state]);

  useEffect(() => {
    const who = packId ?? "?";
    const conn = part === "connector";
    const typeNow = () => getStore().types[blockType];
    const fx: Effects = {
      ready: () => { if (loads.current === 1) sendInit(); },
      // El mismo mensaje que la tarjeta (BlockView `commit`): la misma validación del backend.
      // La parte del conector, solo con los parámetros que dibuja (P41).
      setParams: (params) => {
        const now = typeNow();
        if (!conn || !now) return send({ type: "set_params", block: id, params });
        const { keep, dropped } = connectorSetParams(now, params);
        if (dropped.length) fx.ignore(`setParams: ${dropped.join(", ")} no son de la parte del conector`, params);
        if (Object.keys(keep).length) send({ type: "set_params", block: id, params: keep });
      },
      preview: (params) => conn
        ? Promise.reject(new Error("la vista previa es del paquete del bloque, no de su conector"))
        : fetchPreview(id, params),
      action: (name, args) => {
        const now = typeNow();
        const why = conn ? (now ? connectorActionError(now, name) : "el bloque ya no existe") : null;
        return why ? Promise.reject(new Error(why)) : postAction(id, name, args);
      },
      run: () => {
        if (getStore().run === null) send({ type: "run", block: id });
        else console.warn(`[paquete ${who}] run ignorado: ya hay una ejecución en curso`);  // i18n-ok log de consola
      },
      openPanel: () => {
        if (surface === "panel") return true;
        const now = typeNow();
        if (!(conn ? connectorPart(now, getStore().connectorInfo, "panel") : hasPanel(now))) return false;
        setStore({ packPanel: id });
        return true;
      },
      closePanel: () => { if (surface === "panel") setStore({ packPanel: null }); },
      resize: (h) => { if (surface === "card") { FRAME_H.set(`${id}:${part}`, h); setHeight(h); } },
      toast: (text, kind) => setStore({ notice: { text: `${pack?.name ?? who}: ${text}`, kind, at: Date.now() } }),
      // La rueda que la página no usa, al lienzo (P54); en el panel no hay lienzo debajo.
      // Excalidraw hace zoom alrededor del último `pointermove` que vio en `document` (encima
      // del marco no le llega ninguno) y lo apunta en el fotograma siguiente: primero el
      // puntero, y la rueda detrás.
      wheel: (w) => {
        const el = frame.current;
        if (surface !== "card" || !el) return;
        const init = wheelInit(w, el.getBoundingClientRect(), el.offsetWidth);
        document.dispatchEvent(new PointerEvent("pointermove", { clientX: init.clientX, clientY: init.clientY }));
        requestAnimationFrame(() => wheelOnCanvas(el, init));
      },
      reply: (msg) => post(msg),
      // El registro del paquete, de momento la consola de la app (P48).
      ignore: (reason, data) => console.warn(`[paquete ${who}] mensaje ignorado: ${reason}`, data),
    };
    const onMessage = (ev: MessageEvent) => {
      const win = frame.current?.contentWindow;
      void handle(ev.data, !!win && ev.source === win, fx);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, blockType, surface, part, packId, pack?.name]);

  if (!ty || !pack?.ui) {
    return <div className="pf-note">{t("bloques.marco.sin_interfaz", { pack: packId ?? "?" })}</div>;
  }
  if (gone) {
    return (
      <div className="pf-note pf-gone">
        {t("bloques.marco.cerrada_a")} <b>{pack.name}</b> {t("bloques.marco.cerrada_b", { why: gone })}{" "}
        <button type="button" onClick={() => { loads.current = 0; sent.current = null; setGone(null); setAttempt((a) => a + 1); }}>
          {t("bloques.marco.recargar")}
        </button>
      </div>
    );
  }
  const onLoad = () => {
    loads.current += 1;
    if (loads.current === 1) sendInit();
    else {
      console.warn(`[paquete ${pack.id}] la interfaz ha cargado otra página: se descarta (riesgo 9)`);  // i18n-ok log de consola
      setGone(t("bloques.marco.otra_pagina"));
    }
  };
  return (
    <iframe key={attempt} ref={frame} className={`pf-frame pf-${surface}${part === "connector" ? " pf-connector" : ""}`}
            title={`${ty.title} · ${pack.name}`}
            sandbox="allow-scripts" referrerPolicy="no-referrer" src={frameUrl(pack.id, pack.ui)}
            style={surface === "card" ? { height } : undefined} onLoad={onLoad} />
  );
}
