// Escribir las salidas de los bloques en una copia del Excel, en su tarjeta (docs/PLAN_EXCEL.md
// §3.3, §3.5, X6, R4). Con una flecha de escritura de un bloque a la tarjeta, cada nombre en el
// que se puede escribir (una celda admitida que no es una fórmula) lleva `← bloque · salida ·
// campo`, que se elige en un menú con los campos de los bloques con flecha (los que no casan en
// unidad salen apagados con su motivo; el backend lo vuelve a comprobar). Abajo, *Escribir
// copia*, que no deja sin resultado o con un bloque desactualizado y dice por qué. Lo puro, en
// excel.ts.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { t } from "./i18n";
import { fmt } from "./BlockOutputs";
import { setWrite, writeCopy } from "./cardActions";
import { useStore } from "./store";
import { writeButton, writeChoices, type ExcelName, type ExcelWrite } from "./excel";

/** `← bloque · salida · campo` de un nombre, con su menú. */
export function WriteChooser({ cardId, n, write }: { cardId: string; n: ExcelName; write: ExcelWrite }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const row = write.rows[n.nombre];
  const title = row ? write.writers.find((w) => w.id === row.block)?.title ?? row.block : null;
  const toggle = () => {
    if (at) return setAt(null);
    const r = btn.current!.getBoundingClientRect();
    setAt({ x: r.left, y: r.bottom + 4 });
  };
  return (
    <>
      <button ref={btn} type="button" className={`xw-pick${row ? " on" : ""}${row?.reason ? " bad" : ""}`}
              onClick={toggle} aria-haspopup="menu" aria-expanded={!!at} title={row?.reason ?? undefined}
              aria-label={t("bloques.excel.escribir.elegir_de", { name: n.nombre })}>
        {row ? <>← {title} · {row.port} · {row.field}</> : t("bloques.excel.escribir.elegir")}
      </button>
      {at && createPortal(<WriteMenu at={at} anchor={btn.current} onClose={() => setAt(null)}
                                     cardId={cardId} n={n} write={write} />, document.body)}
    </>
  );
}

function WriteMenu({ at, anchor, onClose, cardId, n, write }: {
  at: { x: number; y: number }; anchor: HTMLElement | null; onClose: () => void;
  cardId: string; n: ExcelName; write: ExcelWrite;
}) {
  const { blocks } = useStore();
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState(at);
  const choices = writeChoices(n, write.writers, blocks);
  const now = write.rows[n.nombre];

  useLayoutEffect(() => {      // dentro de la ventana; si no cabe debajo, encima
    const el = box.current;
    if (!el) return;
    const w = el.offsetWidth, h = el.offsetHeight;
    const x = Math.max(8, Math.min(at.x, window.innerWidth - w - 8));
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

  const pick = async (sel: { block: string; port: string; field: string } | null) => {
    onClose();
    await setWrite(cardId, n.nombre, sel);
  };

  return (
    <div ref={box} className="xl-menu xw-menu" role="menu" style={{ left: pos.x, top: pos.y }}
         onWheel={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <div className="q">
        {t("bloques.excel.escribir.elegir_de", { name: n.nombre })}
        {n.unidad ? ` · ${t("bloques.excel.en_unidad", { unit: n.unidad })}` : ""}
      </div>
      {choices.length === 0 && <p className="xl-none">{t("bloques.excel.escribir.ninguna")}</p>}
      {write.writers.map((w) => {
        const mine = choices.filter((c) => c.block === w.id);
        if (!mine.length) return null;
        return (
          <div key={w.id} className="xl-grp">
            <div className="xl-card" title={w.title}>{w.title}</div>
            {mine.map((c) => {
              const why = c.problem ? t(`bloques.excel.escribir.unidad.${c.problem}`, { unit: c.unit || "—", sfx: n.unidad || "—" }) : null;
              const on = now && now.block === c.block && now.port === c.port && now.field === c.field;
              return (
                <button key={`${c.port}.${c.field}`} type="button" role="menuitemradio" aria-checked={!!on}
                        disabled={!!why} title={why ?? undefined} className={on ? "on" : undefined}
                        onClick={() => void pick({ block: c.block, port: c.port, field: c.field })}>
                  <span className="xl-n">{c.port} · {c.label ?? c.field}</span>
                  <em>{why ?? `${fmt(c.value)}${c.unit ? ` ${c.unit}` : ""}`}</em>
                </button>
              );
            })}
          </div>
        );
      })}
      {now && (
        <button type="button" role="menuitem" className="xw-none" onClick={() => void pick(null)}>
          {t("bloques.excel.escribir.no_escribir")}
        </button>
      )}
    </div>
  );
}

/** *Escribir copia* con el motivo si no deja, y la nota de que el original no se toca. */
export function WriteFooter({ cardId, write }: { cardId: string; write: ExcelWrite }) {
  const { blocks } = useStore();
  const [busy, setBusy] = useState(false);
  const { disabled, reason } = writeButton(write, blocks);
  const go = async () => {
    setBusy(true);
    try {
      await writeCopy(cardId);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="xw-foot">
      <button type="button" className="fbtn main" disabled={disabled || busy} onClick={() => void go()}
              title={reason ?? undefined}>
        {t("bloques.excel.escribir.boton")}
      </button>
      <span className={reason ? "xw-why" : "xw-note"}>{reason ?? t("bloques.excel.escribir.nota")}</span>
    </div>
  );
}
