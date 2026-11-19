// Añadir bloques (plan D91, D96 4B + 4C):
// - La bandeja: un panel a la izquierda que se muestra u oculta con *Bloque* y se queda abierto
//   mientras se monta. Buscador, plantillas y bloques por paquete. Un clic pone el bloque en el
//   centro de la vista; arrastrándolo, donde se suelte.
// - El buscador de Ctrl+B (atajo configurable, D97): sale donde está el ratón y el bloque nace
//   ahí. ↑↓ elige, Intro pone, Esc cierra. Nunca mientras se escribe en un campo o un texto.
// Una plantilla deja la cadena entera ya conectada, en un sitio libre (el backend lo busca).
import { useEffect, useMemo, useRef, useState, type CSSProperties, type HTMLAttributes,
         type PointerEvent as RPointerEvent } from "react";
import { viewportCoordsToSceneCoords } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { apiFetch } from "./auth";
import { t } from "./i18n";
import { setStore, useStore, type Connector, type PackInfo } from "./store";
import { cascade, packsOf, paletteItems, search, type Item } from "./palette";
import { portColor, type Pt } from "./ports";
import { matches, shortcut, typing } from "./shortcuts";

type Props = { api: ExcalidrawImperativeAPI; projectId: string; trayOpen: boolean; onCloseTray: () => void };

/** El nombre de un paquete en la bandeja: el `name` de su `pack.toml`, que llega en el catálogo (P67). */
const packLabel = (id: string, packs: PackInfo[]) => packs.find((p) => p.id === id)?.name || id;

export function BlockPalette({ api, projectId, trayOpen, onCloseTray }: Props) {
  const { types, templates } = useStore();
  const all = useMemo(() => paletteItems(types, templates), [types, templates]);
  const pointer = useRef<Pt>({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
  const [finder, setFinder] = useState<Pt | null>(null);       // dónde salió el buscador
  const [drag, setDrag] = useState<{ item: Item; at: Pt } | null>(null);
  const recent = useRef<{ x: number; y: number; at: number }[]>([]);   // bloques recién pedidos

  const toScene = (p: Pt) => viewportCoordsToSceneCoords({ clientX: p.x, clientY: p.y }, api.getAppState());
  const viewCenter = () => {
    const s = api.getAppState();
    return { x: -s.scrollX + s.width / s.zoom.value / 2, y: -s.scrollY + s.height / s.zoom.value / 2 };
  };

  // Pone el bloque (centrado en el punto, con la cabecera arriba) o la plantilla (desde el punto).
  const place = async (item: Item, at: { x: number; y: number }) => {
    const base = `/api/projects/${encodeURIComponent(projectId)}`;
    // nunca justo encima de otro bloque (Ctrl+B dos veces sin mover el ratón): en cascada. Lo
    // recién pedido cuenta aunque el backend aún no lo haya devuelto a la escena.
    const now = Date.now();
    recent.current = recent.current.filter((p) => now - p.at < 5000);
    const corner = cascade({ x: at.x - 140, y: at.y - 20 }, [
      ...api.getSceneElements().filter((e) => e.type === "embeddable").map((e) => ({ x: e.x, y: e.y })),
      ...recent.current]);
    if (item.kind === "block") recent.current.push({ ...corner, at: now });
    const r = item.kind === "block"
      ? await apiFetch(`${base}/blocks`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type: item.id, x: corner.x, y: corner.y }) })
      : await apiFetch(`${base}/templates`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ template: item.id, x: at.x, y: at.y }) });
    if (!r.ok) setStore({ lastError: t("bloques.paleta.error_poner", { title: item.title, detail: (await r.json().catch(() => ({}))).detail ?? r.status }) });
  };

  // Dónde está el ratón (para el buscador) y Ctrl+B.
  useEffect(() => {
    const move = (e: PointerEvent) => { pointer.current = { x: e.clientX, y: e.clientY }; };
    const key = (e: KeyboardEvent) => {
      if (!matches(e, shortcut("blocks.search")) || typing(e.target)) return;
      e.preventDefault();
      e.stopPropagation();
      setFinder({ ...pointer.current });
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("pointermove", move, true); window.removeEventListener("keydown", key, true); };
  }, []);

  // Arrastrar un elemento de la bandeja a la pizarra.
  const startDrag = (item: Item, e: RPointerEvent) => {
    if (e.button !== 0) return;
    const start = { x: e.clientX, y: e.clientY };
    let moved = false;
    const move = (ev: PointerEvent) => {
      if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 5) return;
      moved = true;
      setDrag({ item, at: { x: ev.clientX, y: ev.clientY } });
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      setDrag(null);
      if (!moved) return place(item, viewCenter());                       // un clic: al centro
      const over = document.elementFromPoint(ev.clientX, ev.clientY) as HTMLElement | null;
      if (over?.closest(".bk-tray")) return;                               // soltado en la bandeja
      place(item, toScene({ x: ev.clientX, y: ev.clientY }));
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  };

  return (
    <>
      {trayOpen && <Tray all={all} onClose={onCloseTray} onPointerDown={startDrag} />}
      {finder && (
        <Finder all={all} at={finder} onClose={() => setFinder(null)}
                onPick={(item) => { setFinder(null); place(item, toScene(finder)); }} />
      )}
      {drag && (
        <div className="bk-ghost" style={{ left: drag.at.x, top: drag.at.y }}>
          <b>{drag.item.title}</b><small>{t("bloques.paleta.suelta")}</small>
        </div>
      )}
    </>
  );
}

/** «necesita Fusion»: el nombre de cada conector que pide (D35), o su id si no se conoce. */
function needs(requires: string[], connectors: Record<string, Connector>) {
  return t("bloques.paleta.necesita", { names: requires.map((c) => connectors[c]?.name ?? c).join(", ") });
}

function Row({ item, on, ...rest }: { item: Item; on?: boolean } & HTMLAttributes<HTMLDivElement>) {
  const { connectors, ports } = useStore();
  const off = item.kind === "block" && item.requires.length > 0;
  const style = item.kind === "block"
    ? { "--c": item.input ? portColor(item.input, ports) : "transparent", "--c2": item.output ? portColor(item.output, ports) : "transparent" }
    : {};
  return (
    <div className={`bk-item${on ? " on" : ""}${off ? " off" : ""}`} role="option" aria-selected={!!on} {...rest}>
      <span className={item.kind === "template" ? "bk-ico tpl" : "bk-ico"} style={style as CSSProperties} aria-hidden="true" />
      <span className="bk-txt">
        {item.title}
        <small>{item.kind === "template" ? t("bloques.paleta.plantilla_n", { n: item.count }) : item.description}</small>
      </span>
      {off && <em>{needs(item.requires, connectors)}</em>}
    </div>
  );
}

function Tray({ all, onClose, onPointerDown }: { all: Item[]; onClose: () => void;
                                                onPointerDown: (item: Item, e: RPointerEvent) => void }) {
  const { packs } = useStore();
  const [q, setQ] = useState("");
  const found = search(all, q);
  const tpls = found.filter((i) => i.kind === "template");
  const blocks = found.filter((i) => i.kind === "block");
  return (
    <aside className="bk-tray" aria-label={t("bloques.paleta.bloques")}>
      <div className="bk-head"><b>{t("bloques.paleta.bloques")}</b>
        <button type="button" onClick={onClose} aria-label={t("bloques.paleta.cerrar_bandeja")} title={t("bloques.paleta.cerrar")}>×</button></div>
      <input className="bk-search" placeholder={t("bloques.paleta.buscar")} value={q}
             onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.stopPropagation()} />
      <div className="bk-list" role="listbox">
        {tpls.length > 0 && <div className="bk-group">{t("bloques.paleta.plantillas")}</div>}
        {tpls.map((i) => <Row key={i.id} item={i} onPointerDown={(e) => onPointerDown(i, e)} />)}
        {packsOf(blocks).map((p) => (
          <div key={p}>
            <div className="bk-group">{packLabel(p, packs)}</div>
            {blocks.filter((i) => i.pack === p).map((i) => <Row key={i.id} item={i} onPointerDown={(e) => onPointerDown(i, e)} />)}
          </div>
        ))}
        {!found.length && <p className="bk-none">{t("bloques.paleta.nada", { q })}</p>}
      </div>
      <p className="bk-hint">{t("bloques.paleta.ayuda_clic")} <kbd>{shortcut("blocks.search")}</kbd> {t("bloques.paleta.ayuda_buscar")}</p>
    </aside>
  );
}

function Finder({ all, at, onClose, onPick }: { all: Item[]; at: Pt; onClose: () => void; onPick: (i: Item) => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const found = search(all, q).slice(0, 8);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { setSel(0); }, [q]);
  useEffect(() => {
    const out = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) onClose(); };
    window.addEventListener("pointerdown", out, true);
    return () => window.removeEventListener("pointerdown", out, true);
  }, [onClose]);
  const left = Math.min(at.x, window.innerWidth - 320), top = Math.min(at.y, window.innerHeight - 340);
  return (
    <div className="bk-finder" ref={box} style={{ left, top }} role="dialog" aria-label={t("bloques.paleta.buscar_bloque")}>
      <input autoFocus className="bk-search" placeholder={t("bloques.paleta.bloque_o_plantilla")} value={q}
             onChange={(e) => setQ(e.target.value)}
             onKeyDown={(e) => {
               e.stopPropagation();
               if (e.key === "Escape") onClose();
               else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, found.length - 1)); }
               else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
               else if (e.key === "Enter" && found[sel]) onPick(found[sel]);
             }} />
      <div role="listbox">
        {found.map((i, k) => (
          <Row key={i.id} item={i} on={k === sel} onMouseEnter={() => setSel(k)} onClick={() => onPick(i)} />
        ))}
        {!found.length && <p className="bk-none">{t("bloques.paleta.nada", { q })}</p>}
      </div>
      <p className="bk-hint"><kbd>↑</kbd><kbd>↓</kbd> {t("bloques.paleta.elige")} · <kbd>{t("bloques.paleta.intro")}</kbd> {t("bloques.paleta.pone")} · <kbd>Esc</kbd> {t("bloques.paleta.cierra")}</p>
    </div>
  );
}
