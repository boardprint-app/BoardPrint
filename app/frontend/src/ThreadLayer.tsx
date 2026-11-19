// Capa de hilos (plan D57, D166): encima del lienzo y fuera de la escena de Excalidraw, como
// los hilos de los anclajes (R14). Cada hilo, según su `layout.size`: minimizado, una etiqueta
// junto a su primer elemento (con su estado y, si está decidido, la decisión); en ventana,
// una mini ventana que se arrastra por la cabecera y se redimensiona por la esquina (nunca
// por debajo de 260×170 ni fuera de la vista, `threads.ts`) con su conversación; a pantalla
// completa, tapa la pizarra para escribir con calma. Una línea discontinua va de la etiqueta o
// la ventana a cada ancla. Un hilo sin anclas en la escena no sale: queda en la pestaña
// *Hilos* (D166). El tamaño y la posición se guardan con el hilo (`thread_layout`, con un
// poco de espera al arrastrar) y llegan de las otras ventanas.
import { useEffect, useMemo, useRef, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { useSceneTick } from "./useSceneTick";
import { getStore, setStore, useStore, type AgentEvent, type ThreadInfo } from "./store";
import { ChatLog, DecisionBox, type CardCtx } from "./AgentChat";
import { askInThread, chromeNodes, deleteThread, loadThread, measureChrome, openThread, reopenThread, requestClose,
         setLayout } from "./threadActions";
import { anchored, anchorName, clampWindow, fullThread, labelSpots, LABEL_H, liveAnchors, moveWindow,
         resizeWindow, THREAD_DEFAULT, toScreen, unplaced, wiresInView, type Chrome, type Rect, type View } from "./threads";
import type { Box } from "./anchors";
import { send } from "./socket";
import { t } from "./i18n";

const LAYOUT_DELAY = 300;     // ms entre dos `thread_layout` mientras se arrastra

/** El nombre de cada estado de un hilo (el valor guardado es el id), o el id si no se conoce. */
export const stateLabel = (state: string): string => ({
  abierto: t("agente.hilo.estado.abierto"), decidido: t("agente.hilo.estado.decidido"),
  en_revision: t("agente.hilo.estado.en_revision"),
} as Record<string, string>)[state] ?? state;

const Ico = {
  bubble: <path d="M4 5h16v11H9l-5 4z" />,
  min: <path d="M5 12h14" />,
  full: <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />,
  card: <rect x="4" y="6" width="16" height="12" rx="2" />,
  trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />,
};
export const Icon = ({ d, size = 16 }: { d: keyof typeof Ico; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{Ico[d]}</svg>
);

/** Las tarjetas de privacidad y tope dentro de un hilo: se reenvían al hilo (o a *Cerrar*). */
export const threadCtx = (id: string): CardCtx => ({
  resend: (ev, once) => (ev.close_request ? requestClose(id, once) : askInThread(id, ev.text ?? "", once)),
  drop: (ev) => {
    const logs = getStore().threadLogs;
    setStore({ threadLogs: { ...logs, [id]: (logs[id] ?? []).filter((e) => e !== ev) } });
  },
});

/** Lo que se escribe en un hilo: la caja, *Cerrar con decisión* y Enviar o *Parar*. Un hilo
 *  decidido no admite preguntas (R43): enseña su decisión y *Reabrir*. */
export function ThreadComposer({ th, big = false }: { th: ThreadInfo; big?: boolean }) {
  const { threadBusy, agentBusy, threadFocus } = useStore();
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const here = threadBusy === th.id;
  const elsewhere = !here && (agentBusy || !!threadBusy);

  useEffect(() => {
    if (threadFocus !== th.id) return;
    box.current?.focus();
    setStore({ threadFocus: null });
  }, [threadFocus, th.id]);

  if (th.state === "decidido") {
    return (
      <div className="th-foot th-decided">
        {th.decision && <DecisionBox d={th.decision}>
          <div className="ag-card-btns"><button type="button" className="ag-btn" onClick={() => reopenThread(th.id)}>{t("agente.hilo.reabrir")}</button></div>
        </DecisionBox>}
      </div>
    );
  }
  const submit = () => {
    const v = text.trim();
    if (!v || here || elsewhere) return;
    askInThread(th.id, v);
    setText("");
  };
  return (
    <form className={big ? "th-foot th-input big" : "th-foot th-input"} onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <textarea ref={box} value={text} aria-label={t("agente.hilo.escribir_en", { titulo: th.title })}
                placeholder={big ? t("agente.hilo.placeholder_calma") : t("agente.hilo.placeholder")}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !big) { e.preventDefault(); submit(); }
                  if (e.key === "Enter" && e.ctrlKey && big) { e.preventDefault(); submit(); }
                }} />
      <div className="th-row">
        <span className="ag-note">{elsewhere ? t("agente.hilo.ocupado")
          : big ? t("agente.hilo.ctrl_intro") : t("agente.hilo.intro")}</span>
        <button type="button" className="ag-btn" disabled={here || elsewhere || th.messages === 0}
                title={th.messages === 0 ? t("agente.hilo.nada_que_decidir") : t("agente.hilo.cerrar_nota")}
                onClick={() => requestClose(th.id)}>{t("agente.hilo.cerrar")}</button>
        {here
          ? <button type="button" className="ag-btn" onClick={() => send({ type: "agent_stop" })}>{t("agente.chat.parar")}</button>
          : <button type="submit" className="ag-btn primary" disabled={elsewhere || !text.trim()}>{t("agente.chat.enviar")}</button>}
      </div>
    </form>
  );
}

/** Lo hablado en un hilo, con la decisión anterior a la vista si se ha reabierto. */
export function ThreadBody({ th, log, anchorsText }: { th: ThreadInfo; log: AgentEvent[] | undefined; anchorsText: string }) {
  const { threadBusy } = useStore();
  const ctx = useMemo(() => threadCtx(th.id), [th.id]);
  return (
    <>
      {th.state === "en_revision" && th.decision && (
        <div className="th-review"><DecisionBox d={th.decision} label={t("agente.decision.en_revision")} /></div>
      )}
      {log ? <ChatLog className="ag-log th-log" log={log} busy={threadBusy === th.id} ctx={ctx}
                      empty={t("agente.hilo.vacio", { anclas: anchorsText })} />
        : <div className="ag-log th-log"><div className="ag-empty">{t("agente.cargando")}</div></div>}
    </>
  );
}

function DeleteBar({ th, onCancel }: { th: ThreadInfo; onCancel: () => void }) {
  return (
    <div className="th-confirm" role="alertdialog" aria-label={t("agente.hilo.borrar")}>
      <span>{t(th.decision ? "agente.hilo.borrar_pregunta_decision" : "agente.hilo.borrar_pregunta", { titulo: th.title })}</span>
      <button type="button" className="ag-btn" onClick={onCancel}>{t("agente.cancelar")}</button>
      <button type="button" className="ag-btn danger" onClick={() => deleteThread(th.id)}>{t("agente.borrar")}</button>
    </div>
  );
}

type WinProps = {
  th: ThreadInfo; rect: Rect; view: View; chrome: Chrome; anchorsText: string; front: boolean;
  onFront: () => void; onDraft: (r: Rect | null) => void;
};

/** La mini ventana: cabecera para arrastrar, la conversación, la caja y la esquina para
 *  redimensionar. Mientras se arrastra se pinta el borrador y se manda cada `LAYOUT_DELAY`. */
function ThreadWindow({ th, rect, view, chrome, anchorsText, front, onFront, onDraft }: WinProps) {
  const { threadLogs } = useStore();
  const [confirm, setConfirm] = useState(false);
  const drag = useRef<{ kind: "move" | "size"; start: Rect; x: number; y: number; last: Rect } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const begin = (kind: "move" | "size") => (e: React.PointerEvent) => {
    if (e.button !== 0 || (kind === "move" && (e.target as HTMLElement).closest("button"))) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { kind, start: rect, x: e.clientX, y: e.clientY, last: rect };
    onFront();
  };
  const move = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const delta = { x: e.clientX - d.x, y: e.clientY - d.y };
    d.last = d.kind === "move" ? moveWindow(d.start, delta, view, chrome) : resizeWindow(d.start, delta, view, chrome);
    onDraft(d.last);
    if (timer.current === undefined) {
      timer.current = window.setTimeout(() => {
        timer.current = undefined;
        if (drag.current) send({ type: "thread_layout", id: th.id, layout: { ...drag.current.last, size: "window" } });
      }, LAYOUT_DELAY);
    }
  };
  const end = () => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    window.clearTimeout(timer.current);
    timer.current = undefined;
    setLayout(th.id, { ...d.last, size: "window" });
    onDraft(null);
  };

  return (
    <section className={front ? "th-win front" : "th-win"} aria-label={t("agente.hilo.aria", { titulo: th.title })}
             style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}
             onPointerDown={onFront} onKeyDown={(e) => e.stopPropagation()}>
      <div className="th-head" onPointerDown={begin("move")} onPointerMove={move} onPointerUp={end}
           onPointerCancel={end} title={t("agente.hilo.arrastra_mover")}>
        <span className={`th-dot st-${th.state}`} title={stateLabel(th.state)} />
        <span className="th-title">{th.title}</span>
        <span className="th-anchors" title={t("agente.hilo.anclado", { anclas: anchorsText })}>{anchorsText}</span>
        <span className="th-btns">
          <button type="button" className="th-ib" aria-label={t("agente.hilo.minimizar")} title={t("agente.hilo.minimizar")}
                  onClick={() => setLayout(th.id, { size: "min" })}><Icon d="min" /></button>
          <button type="button" className="th-ib" aria-label={t("agente.hilo.pantalla_completa")} title={t("agente.hilo.pantalla_completa")}
                  onClick={() => openThread(null, th.id, "full")}><Icon d="full" /></button>
          <button type="button" className="th-ib" aria-label={t("agente.hilo.borrar")} title={t("agente.hilo.borrar")}
                  onClick={() => setConfirm(true)}><Icon d="trash" /></button>
        </span>
      </div>
      {confirm && <DeleteBar th={th} onCancel={() => setConfirm(false)} />}
      <ThreadBody th={th} log={threadLogs[th.id]} anchorsText={anchorsText} />
      <ThreadComposer th={th} />
      <div className="th-grip" aria-hidden="true" title={t("agente.hilo.arrastra_tamano")}
           onPointerDown={begin("size")} onPointerMove={move} onPointerUp={end} onPointerCancel={end} />
    </section>
  );
}

/** A pantalla completa (D57): tapa la pizarra, con la caja grande para escribir con calma. */
function ThreadFull({ th, anchorsText }: { th: ThreadInfo; anchorsText: string }) {
  const { threadLogs } = useStore();
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !getStore().threadClosing) setLayout(th.id, { size: "window" });
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [th.id]);
  return (
    <div className="th-full-back" onKeyDown={(e) => {
      e.stopPropagation();
      if (e.key === "Escape" && !getStore().threadClosing) setLayout(th.id, { size: "window" });
    }}>
      <section className="th-full" aria-label={t("agente.hilo.aria", { titulo: th.title })} role="dialog">
        <div className="th-head">
          <span className={`th-dot st-${th.state}`} title={stateLabel(th.state)} />
          <span className="th-title">{th.title}</span>
          <span className="th-anchors">{t("agente.hilo.anclado", { anclas: anchorsText })}</span>
          <span className="th-btns">
            <button type="button" className="ag-btn" onClick={() => setLayout(th.id, { size: "window" })}>
              <Icon d="card" /> {t("agente.hilo.dejar")}
            </button>
            <button type="button" className="th-ib" aria-label={t("agente.hilo.minimizar")} title={t("agente.hilo.minimizar")}
                    onClick={() => setLayout(th.id, { size: "min" })}><Icon d="min" /></button>
            <button type="button" className="th-ib" aria-label={t("agente.hilo.borrar")} title={t("agente.hilo.borrar")}
                    onClick={() => setConfirm(true)}><Icon d="trash" /></button>
          </span>
        </div>
        {confirm && <DeleteBar th={th} onCancel={() => setConfirm(false)} />}
        <ThreadBody th={th} log={threadLogs[th.id]} anchorsText={anchorsText} />
        <ThreadComposer th={th} big />
      </section>
    </div>
  );
}

/** La etiqueta de un hilo minimizado: su estado, su título y, decidido, la decisión. */
function ThreadLabel({ th, at, onOpen }: { th: ThreadInfo; at: { x: number; y: number }; onOpen: () => void }) {
  const decided = th.state === "decidido" && th.decision;
  return (
    <button type="button" className={decided ? "th-label decided" : "th-label"} style={{ left: at.x, top: at.y }}
            aria-label={t("agente.hilo.abrir_aria", { titulo: th.title })}
            title={decided ? t("agente.hilo.decision_titulo", { texto: th.decision!.text }) : t("agente.hilo.abrir")}
            onClick={onOpen} onKeyDown={(e) => e.stopPropagation()}>
      <Icon d="bubble" />
      <span className={`th-dot st-${th.state}`} />
      <span className="th-label-text">
        <span className="th-label-title">{th.title}</span>
        {decided ? <small className="th-label-dec">{th.decision!.text}</small>
          : <small>{th.state === "en_revision" ? t("agente.hilo.en_revision_mensajes", { mensajes: messages(th.messages) })
                                               : messages(th.messages)}</small>}
      </span>
    </button>
  );
}

/** «3 mensajes», «1 mensaje». */
export const messages = (n: number) => t(n === 1 ? "agente.mensajes_uno" : "agente.mensajes_varios", { n });

const labelWidth = (th: ThreadInfo) =>
  Math.min(320, 70 + Math.max(th.title.length, th.state === "decidido" ? th.decision?.text.length ?? 0 : 12) * 7);

export function ThreadLayer({ api }: { api: ExcalidrawImperativeAPI }) {
  const { threads, types } = useStore();
  useSceneTick(api);
  const ref = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ width: window.innerWidth, height: window.innerHeight });
  const [chrome, setChrome] = useState<Chrome>(() => measureChrome());
  const [drafts, setDrafts] = useState<Record<string, Rect>>({});
  const [front, setFront] = useState<string | null>(null);

  // El tamaño de la pizarra y su interfaz fija (paso 5b): se miden de nuevo cuando cambia el
  // tamaño de la ventana o del panel derecho (la capa) o el de la barra de arriba, la de abajo
  // o el Filtro (p. ej. la barra se parte en dos filas). Los nodos de Excalidraw pueden no
  // estar aún al montar: cada medida vuelve a buscarlos y los observa.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const seen = new Set<Element>();
    const measure = () => {
      raf = 0;
      setView((v) => (v.width === el.clientWidth && v.height === el.clientHeight ? v
        : { width: el.clientWidth, height: el.clientHeight }));
      const c = measureChrome();
      setChrome((old) => (JSON.stringify(old) === JSON.stringify(c) ? old : c));
      for (const n of [...chromeNodes("top"), ...chromeNodes("bottom"), ...chromeNodes("others")]) {
        if (!seen.has(n)) { seen.add(n); ro.observe(n); }
      }
    };
    const ro = new ResizeObserver(() => { if (!raf) raf = requestAnimationFrame(measure); });
    ro.observe(el);
    const late = [300, 1500].map((ms) => window.setTimeout(measure, ms));
    return () => { ro.disconnect(); cancelAnimationFrame(raf); late.forEach(window.clearTimeout); };
  }, []);

  // Lo que está en ventana o a pantalla completa trae sus mensajes (al abrir el proyecto, o
  // cuando otra ventana lo abre).
  useEffect(() => {
    for (const th of threads) if (th.layout && th.layout.size !== "min") loadThread(th.id);
  }, [threads]);

  const st = api.getAppState();
  const s = { scrollX: st.scrollX, scrollY: st.scrollY, zoom: st.zoom.value };
  const els = api.getSceneElements();
  const byId = new Map(els.map((e) => [e.id, e]));
  const live = new Set(byId.keys());
  const shown = threads.filter((th) => anchored(th.anchors, live));
  const boxes = new Map<string, Box>();
  for (const th of shown) for (const a of liveAnchors(th.anchors, live)) boxes.set(a, toScreen(byId.get(a)!, s));
  const title = (type: string) => types[type]?.title;
  const anchorsText = (th: ThreadInfo) =>
    liveAnchors(th.anchors, live).map((a) => anchorName(byId.get(a) as never, title)).join(" ↔ ");

  const full = fullThread(shown, live, (th) => th.anchors);
  const sizeOf = (th: ThreadInfo) => (th === full ? "full" : th.layout?.size === "min" || !th.layout ? "min" : "window");
  const minimized = shown.filter((th) => sizeOf(th) === "min");
  const spots = labelSpots(minimized, boxes, view, labelWidth, chrome);
  const windows = shown.filter((th) => sizeOf(th) === "window");
  const rectOf = (th: ThreadInfo): Rect => {
    if (drafts[th.id]) return drafts[th.id];
    const l = th.layout ?? { x: 0, y: 0, ...THREAD_DEFAULT };
    if (unplaced(l)) {
      const first = liveAnchors(th.anchors, live)[0];
      const b = boxes.get(first)!;
      return clampWindow({ x: b.x + b.width + 24, y: b.y, w: l.w, h: l.h }, view, chrome);
    }
    return clampWindow(l, view, chrome);
  };

  const lines: { key: string; from: { x: number; y: number }; to: { x: number; y: number } }[] = [];
  for (const th of minimized) {
    const p = spots.get(th.id);
    if (!p) continue;
    const box = { x: p.x, y: p.y, width: labelWidth(th), height: LABEL_H };
    wiresInView(box, liveAnchors(th.anchors, live).map((a) => boxes.get(a)!), view, chrome)
      .forEach((w, i) => lines.push({ key: `${th.id}-${i}`, ...w }));
  }
  for (const th of windows) {
    const r = rectOf(th);
    const to = liveAnchors(th.anchors, live).map((a) => boxes.get(a)!);
    wiresInView({ x: r.x, y: r.y, width: r.w, height: r.h }, to, view, chrome)
      .forEach((w, i) => lines.push({ key: `${th.id}-${i}`, ...w }));
  }

  return (
    <div ref={ref} className="th-layer">
      <svg className="th-wires" aria-hidden="true">
        {lines.map((l) => (
          <g key={l.key}>
            <line x1={l.from.x} y1={l.from.y} x2={l.to.x} y2={l.to.y} className="th-wire" />
            <circle cx={l.to.x} cy={l.to.y} r={4} className="th-wire-dot" />
          </g>
        ))}
      </svg>
      {minimized.map((th) => spots.get(th.id) && (
        <ThreadLabel key={th.id} th={th} at={spots.get(th.id)!} onOpen={() => { setFront(th.id); openThread(api, th.id); }} />
      ))}
      {windows.map((th) => (
        <ThreadWindow key={th.id} th={th} rect={rectOf(th)} view={view} chrome={chrome} anchorsText={anchorsText(th)}
                      front={front === th.id} onFront={() => setFront(th.id)}
                      onDraft={(r) => setDrafts((d) => {
                        const { [th.id]: _old, ...rest } = d;
                        return r ? { ...rest, [th.id]: r } : rest;
                      })} />
      ))}
      {full && <ThreadFull key={full.id} th={full} anchorsText={anchorsText(full)} />}
    </div>
  );
}
