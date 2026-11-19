// Capa de la tinta (plan §3, D188-D195): pinta cada trazo de tinta de la escena (un `freedraw`
// con `opacity 0`, que Excalidraw guarda pero no pinta) encima de las tarjetas, y, con la
// herramienta *Tinta* activa, recibe el ratón en vez de Excalidraw: dibuja con el pincel elegido,
// convierte el trazo en su forma ideal si se mantiene quieto al final, lo ancla a la tarjeta que
// marca y lo mete en la escena en un solo paso del deshacer; con el borrador, borra la tinta que
// toca el recorrido. Hermana de AnchorLayer (mismo z-index), en tres SVG: los del subrayador
// multiplican con lo de debajo, o lo aclaran sobre lo oscuro (un `mix-blend-mode` dentro de un SVG
// solo mezclaría con el SVG).
import { useEffect, useRef, useState } from "react";
import { CaptureUpdateAction, newElementWith, viewportCoordsToSceneCoords } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { useSceneTick } from "./useSceneTick";
import { useStore } from "./store";
import { filteredOut, type PostitData } from "./postit";
import type { Pt } from "./anchors";
import { erased, HOLD_MS, HOLD_PX, inkAnchor, isHeld, isInk, outline, svgPath, type InkPoint,
         type Sample } from "./ink";
import { recognize, type Recognized } from "./shapes";
import { densify, inkElement, inkStroke, surfacePaint, viewTransform, type InkStroke } from "./inkView";
import { getInkTool, releaseInk, setInkTool, toggleInk, toolColor, useInkTool } from "./inkTool";
import { matches, shortcut, typing } from "./shortcuts";

// `filter`, el de la tinta del lienzo; `cardFilter`, el de la anclada a una tarjeta (inkView).
type Props = { api: ExcalidrawImperativeAPI; filter: string; cardFilter: string };

// El trazo en curso: puntos en la escena (con la presión del lápiz), muestras en pantalla para
// «quieto» (HOLD_PX son px de pantalla) y la forma reconocida, si la hay.
type Live = {
  pointer: number;
  pen: boolean;
  points: Pt[];
  pressures: number[];
  screen: Sample[];
  shape: Recognized | null;
  snapAt: Pt | null;
  erasing: Set<string>;
};

const randomInt = () => Math.floor(Math.random() * 2 ** 31);
const newId = () => (crypto.randomUUID?.() ?? `${Date.now()}${Math.random()}`).replace(/[^a-z0-9]/gi, "").slice(0, 21);
const focusBoard = () => (document.querySelector(".app .excalidraw") as HTMLElement | null)?.focus();

export function InkLayer({ api, filter, cardFilter }: Props) {
  useSceneTick(api);
  const tool = useInkTool();
  const { postitFilter } = useStore();
  const cache = useRef(new Map<string, { key: string; stroke: InkStroke | null }>());
  const live = useRef<Live | null>(null);
  const [, setFrame] = useState(0);
  const redraw = () => setFrame((f) => f + 1);
  const holdTimer = useRef<number | undefined>(undefined);
  const input = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState<Pt | null>(null);

  // Lo oculto por el filtro de post-its: el post-it y la tinta anclada a él.
  const els = api.getSceneElements();
  const byId = new Map(els.map((e) => [e.id, e]));
  const hiddenCard = (id: string | null | undefined) => {
    const e = id ? byId.get(id) : undefined;
    const cd = e?.customData as PostitData | undefined;
    return cd?.kind === "postit" && filteredOut(postitFilter, cd);
  };
  const visible = (e: ExcalidrawElement) => !(isInk(e) && hiddenCard(e.customData?.anchor as string | undefined))
    && !hiddenCard(e.id);

  // ----------------------------------------------------------- atajo, Esc y herramientas de Excalidraw
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && getInkTool().active) {
        live.current = null;
        setInkTool(releaseInk);
        return;
      }
      if (!matches(ev, shortcut("tinta.activar")) || typing(ev.target)) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      setInkTool(toggleInk);
    };
    // Una herramienta de la barra de Excalidraw suelta la tinta (también la que ya estaba puesta).
    const onToolbar = (ev: PointerEvent) => {
      if ((ev.target as HTMLElement | null)?.closest?.(".App-toolbar")) setInkTool(releaseInk);
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("pointerdown", onToolbar, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("pointerdown", onToolbar, true);
    };
  }, []);

  // Al activarla, Excalidraw pasa a la selección; si cambia de herramienta (con su atajo), suelta.
  useEffect(() => {
    if (!tool.active) {
      live.current = null;
      return;
    }
    if (api.getAppState().activeTool.type !== "selection") api.setActiveTool({ type: "selection" });
    return api.onChange((_e, st) => {
      if (st.activeTool.type !== "selection") setInkTool(releaseInk);
    });
  }, [api, tool.active]);

  // La rueda va al lienzo de Excalidraw (desplazar y zoom), como desde las tarjetas.
  useEffect(() => {
    const el = input.current;
    if (!el) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      document.querySelector(".app .excalidraw canvas.interactive")?.dispatchEvent(new WheelEvent("wheel", {
        deltaX: ev.deltaX, deltaY: ev.deltaY, deltaMode: ev.deltaMode, clientX: ev.clientX, clientY: ev.clientY,
        ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, shiftKey: ev.shiftKey, altKey: ev.altKey,
        bubbles: true, cancelable: true,
      }));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [tool.active]);

  // ----------------------------------------------------------- dibujar y borrar
  const scenePt = (ev: { clientX: number; clientY: number }) =>
    viewportCoordsToSceneCoords({ clientX: ev.clientX, clientY: ev.clientY }, api.getAppState());

  // «Quieto» (D191): tras cada movimiento se vuelve a mirar al cabo de HOLD_MS.
  const armHold = () => {
    window.clearTimeout(holdTimer.current);
    holdTimer.current = window.setTimeout(() => {
      const l = live.current;
      if (!l || l.shape || getInkTool().mode === "borrador") return;
      if (!isHeld(l.screen, performance.now(), true)) return;
      const r = recognize(l.points);
      if (!r) return;
      l.shape = r;
      l.snapAt = l.screen[l.screen.length - 1];
      redraw();
    }, HOLD_MS + 20);
  };

  const onDown = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (ev.button !== 0 || live.current) return;
    ev.preventDefault();
    ev.currentTarget.setPointerCapture(ev.pointerId);
    const p = scenePt(ev);
    const pen = ev.pointerType === "pen";
    live.current = {
      pointer: ev.pointerId, pen, points: [p], pressures: [pen ? ev.pressure : 0.5],
      screen: [{ x: ev.clientX, y: ev.clientY, t: performance.now() }], shape: null, snapAt: null,
      erasing: new Set(),
    };
    if (getInkTool().mode === "borrador") eraseAlong([p]);
    armHold();
    redraw();
  };

  const eraseAlong = (path: Pt[]) => {
    const l = live.current;
    if (!l) return;
    const hit = erased(path, api.getSceneElements().filter(visible) as unknown as Parameters<typeof erased>[1]);
    hit.forEach((id) => l.erasing.add(id));
  };

  const onMove = (ev: React.PointerEvent<HTMLDivElement>) => {
    const sp = { x: ev.clientX, y: ev.clientY };
    if (getInkTool().mode === "borrador") setCursor(sp);
    const l = live.current;
    if (!l || ev.pointerId !== l.pointer) return;
    const evs = (ev.nativeEvent.getCoalescedEvents?.() ?? []).length ? ev.nativeEvent.getCoalescedEvents() : [ev.nativeEvent];
    const now = performance.now();
    for (const e of evs) {
      const prev = l.points[l.points.length - 1];
      const p = scenePt(e);
      if (Math.hypot(p.x - prev.x, p.y - prev.y) < 0.3) continue;
      l.points.push(p);
      l.pressures.push(l.pen ? e.pressure : 0.5);
      l.screen.push({ x: e.clientX, y: e.clientY, t: now });
      if (getInkTool().mode === "borrador") eraseAlong([prev, p]);
    }
    // Moverse después de la forma vuelve al trazo a mano.
    if (l.shape && l.snapAt && Math.hypot(sp.x - l.snapAt.x, sp.y - l.snapAt.y) > 2 * HOLD_PX) {
      l.shape = null;
      l.snapAt = null;
    }
    armHold();
    redraw();
  };

  const finish = (ev: React.PointerEvent<HTMLDivElement>) => {
    const l = live.current;
    if (!l || ev.pointerId !== l.pointer) return;
    live.current = null;
    window.clearTimeout(holdTimer.current);
    const t = getInkTool();
    const all = api.getSceneElementsIncludingDeleted();
    if (t.mode === "borrador") {
      // Todo lo tocado en un solo paso del deshacer (D195).
      if (l.erasing.size) {
        api.updateScene({
          elements: all.map((e) => (l.erasing.has(e.id) ? newElementWith(e, { isDeleted: true }) : e)),
          captureUpdate: CaptureUpdateAction.IMMEDIATELY,
        });
      }
    } else {
      const points = l.shape ? l.shape.points : l.points;
      const anchor = inkAnchor(points, l.shape?.shape, api.getSceneElements().filter(visible));
      const el = inkElement({
        points, pressures: l.pen ? l.pressures : undefined, brush: t.brush, color: toolColor(t), size: t.size,
        shape: l.shape?.shape, anchor, created: new Date().toISOString().replace(/\.\d+Z$/, "+00:00"),
        id: newId(), seed: randomInt(), versionNonce: randomInt(), updated: Date.now(),
      });
      api.updateScene({
        elements: [...all, el as unknown as ExcalidrawElement],
        captureUpdate: CaptureUpdateAction.IMMEDIATELY,
      });
    }
    focusBoard();          // para que Ctrl+Z llegue a Excalidraw
    redraw();
  };

  // ----------------------------------------------------------- pintar
  const st = api.getAppState();
  const view = { scrollX: st.scrollX, scrollY: st.scrollY, zoom: st.zoom.value };
  const strokes: InkStroke[] = [];
  const seen = new Set<string>();
  const erasing = live.current?.erasing;
  for (const e of els) {
    if (!isInk(e) || !visible(e)) continue;
    seen.add(e.id);
    const key = `${e.version}:${filter}:${cardFilter}`;
    let c = cache.current.get(e.id);
    if (!c || c.key !== key) {
      c = { key, stroke: inkStroke(e as unknown as Parameters<typeof inkStroke>[0], filter, cardFilter) };
      cache.current.set(e.id, c);
    }
    if (c.stroke) strokes.push(c.stroke);
  }
  for (const id of cache.current.keys()) if (!seen.has(id)) cache.current.delete(id);

  // La vista previa del trazo en curso, con el pincel, el color y el grosor elegidos.
  let preview: { d: string; color: string; opacity: number; blend: string; grain: boolean } | null = null;
  const l = live.current;
  if (l && tool.mode !== "borrador") {
    const pts: InkPoint[] = l.shape
      ? (densify(l.shape.points.map((p) => [p.x, p.y])) as InkPoint[])
      : l.points.map((p, i) => (l.pen ? [p.x, p.y, l.pressures[i]] : [p.x, p.y]));
    const d = svgPath(outline(pts.length === 1 ? [pts[0], pts[0]] : pts, tool.brush, tool.size, l.pen && !l.shape));
    // Encima de una tarjeta, con el filtro de las tarjetas, como quedará al soltar (R53).
    const over = inkAnchor(l.shape ? l.shape.points : l.points, l.shape?.shape, els as unknown as Parameters<typeof inkAnchor>[2]);
    preview = { d, ...surfacePaint({ brush: tool.brush, size: tool.size, opacity: 1 }, toolColor(tool), over ? cardFilter : filter) };
  }

  const path = (s: { id?: string; d: string; color: string; opacity: number; grain: boolean }, dim = false) => (
    <path key={s.id ?? "live"} d={s.d} fill={s.color} opacity={dim ? s.opacity * 0.25 : s.opacity}
          filter={s.grain ? "url(#ink-grain)" : undefined} />
  );
  const tf = viewTransform(view);
  return (
    <>
      <svg className="ink-layer ink-hl" aria-hidden="true">
        <g transform={tf}>
          {strokes.filter((s) => s.blend === "multiply").map((s) => path(s, !!erasing?.has(s.id)))}
          {preview?.blend === "multiply" && path(preview)}
        </g>
      </svg>
      <svg className="ink-layer ink-sc" aria-hidden="true">
        <g transform={tf}>
          {strokes.filter((s) => s.blend === "screen").map((s) => path(s, !!erasing?.has(s.id)))}
          {preview?.blend === "screen" && path(preview)}
        </g>
      </svg>
      <svg className="ink-layer" aria-hidden="true">
        <defs>
          {/* El grano del rotulador (D190): sutil, en unidades de la escena. */}
          <filter id="ink-grain" x="-5%" y="-5%" width="110%" height="110%">
            <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="3" result="noise" />
            <feDisplacementMap in="SourceGraphic" in2="noise" scale="1.4" xChannelSelector="R" yChannelSelector="G" />
          </filter>
        </defs>
        <g transform={tf}>
          {strokes.filter((s) => s.blend === "normal").map((s) => path(s, !!erasing?.has(s.id)))}
          {preview?.blend === "normal" && path(preview)}
        </g>
      </svg>
      {tool.active && (
        <div ref={input} className={tool.mode === "borrador" ? "ink-input erasing" : "ink-input"}
             onPointerDown={onDown} onPointerMove={onMove} onPointerUp={finish} onPointerCancel={finish}
             onPointerLeave={() => setCursor(null)} onContextMenu={(e) => e.preventDefault()}>
          {tool.mode === "borrador" && cursor && (
            <i className="ink-eraser" style={{ left: cursor.x, top: cursor.y }} />
          )}
        </div>
      )}
    </>
  );
}
