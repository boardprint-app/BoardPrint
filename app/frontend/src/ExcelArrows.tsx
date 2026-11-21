// La flecha de enlace de una tarjeta de Excel a un bloque (docs/PLAN_EXCEL.md §3.6, R5). No es
// un elemento de la escena: se pinta encima del lienzo desde `links` (una discontinua por pareja
// tarjeta-bloque, con «3 enlaces»), así que no se puede desincronizar de los enlaces ni entra en
// el orden de ejecución. Un clic la selecciona y abre lo que tiene (*Editar enlaces…*, *Quitar
// la flecha*); con ella seleccionada, Supr la borra: quita sus enlaces y cada parámetro se queda
// con su último valor. El menú de enlace lo abre también ConnectLayer al soltar la salida de un
// Excel en un bloque sin entrada que la acepte (`openLinkMenu`). Lo puro, en excelPairs.ts.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CaptureUpdateAction } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { useSceneTick } from "./useSceneTick";
import { useStore } from "./store";
import { t } from "./i18n";
import { fmt } from "./BlockOutputs";
import { CARD_SOCKET_Y, isBlockEl, isExcelEl, isNodeEl } from "./connections";
import { elbowRoute, labelSpot, socketPoint, socketY, type Pt, type Rect } from "./ports";
import { linkPairs, linkRows, pairBody, pairLabel, type LinkRow } from "./excelPairs";
import { removePairLinks, setPairLinks } from "./cardActions";

type MenuAt = { card: string; block: string; at: Pt };
let opener: ((m: MenuAt) => void) | null = null;

/** Abre el menú de enlace de la tarjeta `card` al bloque `block` en el punto `at` de la
 *  ventana (lo llama ConnectLayer al soltar la flecha). */
export function openLinkMenu(m: MenuAt) {
  opener?.(m);
}

const keyOf = (card: string, block: string) => `${card}\u0000${block}`;
const cardName = (el: ExcalidrawElement | undefined) =>
  String((el?.customData as { path?: string } | undefined)?.path ?? "").split(/[\\/]/).pop() ?? "";
const typing = (el: EventTarget | null) => !!(el as HTMLElement | null)?.closest?.("input, select, textarea, [contenteditable]");

export function ExcelArrows({ api }: { api: ExcalidrawImperativeAPI }) {
  const { blocks, types } = useStore();
  const [sel, setSel] = useState<string | null>(null);
  const [menu, setMenu] = useState<MenuAt | null>(null);
  useSceneTick(api);

  useEffect(() => {
    opener = (m) => { setSel(null); setMenu(m); };
    return () => { opener = null; };
  }, []);

  const els = api.getSceneElements();
  const byId = new Map(els.map((e) => [e.id, e]));
  const st = api.getAppState();
  const z = st.zoom.value;
  const view = (p: Pt) => ({ x: (p.x + st.scrollX) * z, y: (p.y + st.scrollY) * z });

  const arrows = linkPairs(blocks).flatMap((p) => {
    const card = byId.get(p.card), block = byId.get(p.block);
    if (!card || !block || !isExcelEl(card) || !isBlockEl(block)) return [];
    const ty = types[(block.customData as { blockType?: string })?.blockType ?? ""];
    // Entra por la izquierda del bloque, debajo de sus enchufes de entrada: no es una de ellas.
    const s = socketPoint("out", 0, card as Rect, CARD_SOCKET_Y.file);
    const e = socketPoint("in", 0, block as Rect, socketY(Object.keys(ty?.inputs ?? {}).length));
    const pts = elbowRoute(s, e, card as Rect, block as Rect).map(view);
    const spot = labelSpot(pts.map((q) => [q.x, q.y] as [number, number]));
    return [{ ...p, key: keyOf(p.card, p.block), pts, spot, file: cardName(card), title: ty?.title ?? "" }];
  });
  const selected = arrows.find((a) => a.key === sel) ?? null;

  const remove = (a: { card: string; block: string }) => {
    setSel(null);
    void removePairLinks(a.block, a.card);
  };

  // Supr o Retroceso con la flecha seleccionada la borra; Esc o un clic fuera la deseleccionan.
  useEffect(() => {
    if (!selected) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setSel(null); return; }
      if ((e.key === "Delete" || e.key === "Backspace") && !typing(e.target)) {
        e.preventDefault();
        e.stopPropagation();                 // Excalidraw no borra lo que tuviera seleccionado
        remove(selected);
      }
    };
    const down = (e: PointerEvent) => {
      if (!(e.target as HTMLElement)?.closest?.(".xl-arrow-hit, .xl-arrow-label, .xl-arrow-pop")) setSel(null);
    };
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", down, true);
    return () => { window.removeEventListener("keydown", key, true); window.removeEventListener("pointerdown", down, true); };
  });

  const pick = (key: string) => {
    setSel(key);
    // lo que hubiera seleccionado en el lienzo se suelta: Supr es para la flecha
    api.updateScene({ appState: { selectedElementIds: {} }, captureUpdate: CaptureUpdateAction.NEVER });
  };

  const path = (pts: Pt[]) => pts.map((q, i) => `${i ? "L" : "M"}${q.x} ${q.y}`).join(" ");
  // La capa va encima de las tarjetas: la flecha se recorta donde pasa por un bloque o una
  // tarjeta, como si fuera por debajo (las del lienzo lo hacen), y ahí tampoco recibe el clic.
  const holes = els.filter(isNodeEl).map((n) => {
    const a = view({ x: n.x, y: n.y });
    return `M${a.x} ${a.y}h${n.width * z}v${n.height * z}h${-n.width * z}Z`;
  }).join("");
  // El menú de enlace va en la ventana (`position: fixed`): bajo el botón que lo abre.
  const atButton = (e: React.MouseEvent) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    return { x: r.left, y: r.bottom + 4 };
  };

  return (
    <>
      <svg className="connect-layer xl-arrows" aria-hidden="true">
        <defs>
          <clipPath id="xl-arrows-clip">
            <path d={`M-100000 -100000H100000V100000H-100000Z${holes}`} clipRule="evenodd" />
          </clipPath>
          <marker id="xl-arrow-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" className="xl-arrow-tip" />
          </marker>
        </defs>
        {arrows.map((a) => (
          <g key={a.key} className={a.key === sel ? "on" : undefined} clipPath="url(#xl-arrows-clip)">
            <path d={path(a.pts)} className="xl-arrow" markerEnd="url(#xl-arrow-head)" />
            <path d={path(a.pts)} className="xl-arrow-hit" onPointerDown={(e) => { e.stopPropagation(); pick(a.key); }} />
          </g>
        ))}
      </svg>
      {arrows.map((a) => (
        <div key={a.key} className="copy-wrap" style={{ left: a.spot.x, top: a.spot.y }}>
          <button type="button" className={`xl-arrow-label${a.key === sel ? " on" : ""}`} aria-expanded={a.key === sel}
                  aria-label={t("bloques.excel.flecha.aria", { file: a.file, title: a.title })}
                  onClick={() => (a.key === sel ? setSel(null) : pick(a.key))}>
            {pairLabel(a.params.length)}
          </button>
          {a.key === sel && (
            <div className="copy-pop xl-arrow-pop" role="dialog" aria-label={t("bloques.excel.flecha.aria", { file: a.file, title: a.title })}>
              <div className="q">{t("bloques.excel.flecha.aria", { file: a.file, title: a.title })}</div>
              {a.params.map((p) => {
                const l = blocks[a.block]?.links?.[p];
                const label = types[(byId.get(a.block)?.customData as { blockType?: string })?.blockType ?? ""]?.params[p]?.label || p;
                return (
                  <div key={p} className="fr">
                    <span title={label}>{label}</span>
                    <code className={l?.reason ? "bad" : undefined} title={l?.reason ?? undefined}>← {l?.name}</code>
                  </div>
                );
              })}
              <div className="xl-arrow-btns">
                <button type="button" className="xl-btn" onClick={(e) => { setSel(null); setMenu({ card: a.card, block: a.block, at: atButton(e) }); }}>
                  {t("bloques.excel.flecha.editar")}
                </button>
                <button type="button" className="xl-btn" onClick={() => remove(a)}>{t("bloques.excel.flecha.quitar")}</button>
              </div>
              <div className="last">{t("bloques.excel.flecha.quitar_nota")}</div>
            </div>
          )}
        </div>
      ))}
      {menu && createPortal(<LinkMenu m={menu} onClose={() => setMenu(null)} />, document.body)}
    </>
  );
}

/** El menú de enlace: una fila por parámetro que se puede tomar de este Excel, con los nombres
 *  que casan; *Enlazar* deja los enlaces de la pareja en lo elegido (todos o ninguno). */
function LinkMenu({ m, onClose }: { m: MenuAt; onClose: () => void }) {
  const { blocks, sources, types } = useStore();
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState(m.at);
  const bt = blocks[m.block]?.type ?? "";
  const ty = types[bt];
  const card = sources[m.card];
  const rows: LinkRow[] = ty ? linkRows(ty.params, blocks[m.block]?.links, m.card, card?.names ?? []) : [];
  const [chosen, setChosen] = useState<Record<string, string>>(
    () => Object.fromEntries(rows.filter((r) => r.current).map((r) => [r.param, r.current!])));
  const [busy, setBusy] = useState(false);
  const file = card?.name ?? m.card;

  // Dentro de la ventana: desde el punto donde se soltó y, si no cabe, hacia dentro.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    setPos({ x: Math.max(8, Math.min(m.at.x, window.innerWidth - w - 8)),
             y: Math.max(8, Math.min(m.at.y, window.innerHeight - h - 8)) });
  }, [m.at]);

  useEffect(() => {
    const down = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("pointerdown", down, true); document.removeEventListener("keydown", key, true); };
  }, [onClose]);

  const submit = async () => {
    setBusy(true);
    const body = pairBody(rows, chosen);
    const had = rows.some((r) => r.current);
    // Sin nada elegido ni nada de antes, no queda flecha: no hay nada que mandar.
    const ok = Object.keys(body).length || had ? await setPairLinks(m.block, m.card, body) : true;
    setBusy(false);
    if (ok) onClose();
  };

  const optionText = (n: LinkRow["options"][number]) => {
    const v = n.valor === null || n.valor === undefined
      ? (n.problema === "calculando" ? t("bloques.excel.calculando") : t("bloques.excel.sin_valor"))
      : `${fmt(n.valor)}${n.unidad ? ` ${n.unidad}` : ""}`;
    return `${n.nombre} · ${v}`;
  };

  return (
    <div ref={box} className="xl-menu xl-link-menu" role="dialog" style={{ left: pos.x, top: pos.y }}
         aria-label={t("bloques.excel.flecha.titulo", { file, title: ty?.title ?? "" })}
         onWheel={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <div className="xl-link-title">{t("bloques.excel.flecha.titulo", { file, title: ty?.title ?? "" })}</div>
      {rows.length === 0
        ? <p className="xl-none">{t("bloques.excel.flecha.ninguna_fila", { file, title: ty?.title ?? "" })}</p>
        : <div className="q">{t("bloques.excel.flecha.nota")}</div>}
      {rows.map((r) => (
        <label key={r.param} className="xl-link-row" data-param={r.param}>
          <span title={r.label}>{r.label}</span>
          <select value={chosen[r.param] ?? ""} onChange={(e) => setChosen({ ...chosen, [r.param]: e.target.value })}>
            <option value="">{t("bloques.excel.flecha.sin_enlace")}</option>
            {r.options.map((n) => <option key={n.nombre} value={n.nombre}>{optionText(n)}</option>)}
          </select>
          {r.other && !chosen[r.param] && (
            <em>{t("bloques.excel.flecha.de_otro", { file: sources[r.other]?.name ?? r.other })}</em>
          )}
        </label>
      ))}
      <div className="xl-link-btns">
        <button type="button" className="xl-btn" onClick={onClose}>{t("bloques.excel.flecha.cancelar")}</button>
        {rows.length > 0 && (
          <button type="button" className="xl-btn main" disabled={busy} onClick={() => void submit()}>
            {t("bloques.excel.flecha.enlazar")}
          </button>
        )}
      </div>
    </div>
  );
}
