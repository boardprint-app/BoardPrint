// *Tomar de Excel* en un parámetro de bloque y el parámetro enlazado (docs/PLAN_EXCEL.md §3.5,
// X2, R1). El menú ofrece solo los nombres de las tarjetas de Excel de la pizarra que casan en
// unidad y tipo (`excel.ts`, las reglas del backend); el enlazado enseña el valor con candado,
// la celda y la tarjeta, y *Quitar enlace*: no se edita a mano.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "./i18n";
import { fmt, LOCK_SHUT } from "./BlockOutputs";
import { linkParam } from "./cardActions";
import { candidates, type ExcelCard, type ParamKind, type ParamLink } from "./excel";

const XL_ICON = (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18M9 4v16" />
  </svg>
);

type MenuProps = {
  block: string; param: string; label: string; kind: ParamKind; unitShown: string;
  sources: Record<string, ExcelCard>;
};

/** El botón de *Tomar de Excel…* y su menú (encima de todo: va al `body`, fuera de la
 *  tarjeta). */
export function ExcelMenuButton({ block, param, label, kind, unitShown, sources }: MenuProps) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const toggle = () => {
    if (at) return setAt(null);
    const r = btn.current!.getBoundingClientRect();
    setAt({ x: r.right, y: r.bottom + 4 });
  };
  return (
    <>
      <button ref={btn} type="button" className="xl-take" onClick={toggle} aria-haspopup="menu" aria-expanded={!!at}
              title={t("bloques.excel.tomar")} aria-label={t("bloques.excel.tomar_de", { name: label })}>
        {XL_ICON}
      </button>
      {at && createPortal(
        <ExcelMenu at={at} anchor={btn.current} onClose={() => setAt(null)}
                   block={block} param={param} kind={kind} unitShown={unitShown} sources={sources} />,
        document.body)}
    </>
  );
}

function ExcelMenu({ at, anchor, onClose, block, param, kind, unitShown, sources }: {
  at: { x: number; y: number }; anchor: HTMLElement | null; onClose: () => void;
  block: string; param: string; kind: ParamKind; unitShown: string; sources: Record<string, ExcelCard>;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState(at);
  const groups = candidates(sources, kind);

  // Dentro de la ventana: alineado a la derecha del botón y, si no cabe debajo, encima.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    const x = Math.max(8, Math.min(at.x - w, window.innerWidth - w - 8));
    const y = at.y + h > window.innerHeight - 8 ? Math.max(8, at.y - h - 30) : at.y;
    setPos({ x, y });
  }, [at]);

  useEffect(() => {
    const down = (e: PointerEvent) => {
      const el = e.target as Node;
      if (!box.current?.contains(el) && !anchor?.contains(el)) onClose();
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("keydown", key, true);
    };
  }, [anchor, onClose]);

  const pick = async (card: string, name: string) => {
    onClose();
    await linkParam(block, param, card, name);
  };

  return (
    <div ref={box} className="xl-menu" role="menu" style={{ left: pos.x, top: pos.y }}
         onWheel={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <div className="q">
        {t("bloques.excel.menu_titulo")} · {kind.unit ? t("bloques.excel.en_unidad", { unit: unitShown }) : t("bloques.excel.sin_unidad")}
      </div>
      {groups.length === 0 && (
        <p className="xl-none">{kind.unit ? t("bloques.excel.ninguno", { unit: unitShown }) : t("bloques.excel.ninguno_sin_unidad")}</p>
      )}
      {groups.map((g) => (
        <div key={g.card} className="xl-grp">
          <div className="xl-card" title={g.cardName}>{g.cardName}</div>
          {g.names.map((n) => (
            <button key={n.nombre} type="button" role="menuitem" onClick={() => void pick(g.card, n.nombre)}
                    title={n.formula ? `${n.where} ${n.formula}` : n.where ?? undefined}>
              <span className="xl-n">{n.nombre}</span>
              <code>{n.where}</code>
              <em>{n.valor === null || n.valor === undefined
                ? (n.problema === "calculando" ? t("bloques.excel.calculando") : t("bloques.excel.sin_valor"))
                : `${fmt(n.valor)}${n.unidad ? ` ${n.unidad}` : ""}`}</em>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Un parámetro enlazado: su valor con candado (no se edita a mano), la celda y la tarjeta de
 *  la que sale, el motivo si no tiene valor y *Quitar enlace*. */
export function LinkedParam({ block, param, label, link, shown, unitShown, card }: {
  block: string; param: string; label: string; link: ParamLink; shown: string; unitShown: string;
  card: ExcelCard | undefined;
}) {
  const cardName = card?.name ?? link.card;
  // Sin valor el backend no da la celda: la de la tarjeta, si el nombre sigue en ella.
  const where = link.where ?? card?.names?.find((n) => n.nombre === link.name)?.where ?? link.name;
  const from = t("bloques.excel.enlazado", { where, file: cardName });
  return (
    <div className={`bp-linked${link.reason ? " bad" : ""}`} data-param={param}>
      <span>{label}</span>
      <b className="bp-lockval" title={from}>
        {LOCK_SHUT}
        {/* Sin valor del Excel, el que quedó en el parámetro no se enseña como suyo (X5). */}
        <span>{link.reason ? t("bloques.excel.sin_valor") : shown}</span>
      </b>
      <em>{unitShown}</em>
      <div className="bp-from">
        <code title={from}>{where}</code>
        <span className="bp-card" title={cardName}>{cardName}</span>
        <button type="button" className="bp-unlink" onClick={() => void linkParam(block, param, null)}
                aria-label={t("bloques.excel.quitar_enlace_de", { name: label })}>
          {t("bloques.excel.quitar_enlace")}
        </button>
      </div>
      {link.reason && <div className="bp-why">{link.reason}</div>}
    </div>
  );
}
