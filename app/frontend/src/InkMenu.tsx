// Botón *Tinta* de la barra de la app (plan D189): el botón activa o suelta la herramienta (y se
// ve activo mientras lo está) y su flecha abre el menú con los pinceles, el borrador, los cinco
// colores y los tres grosores. Elegir algo en el menú también la activa; elegir un pincel o el
// borrador lo cierra (los colores y grosores, no: se eligen seguidos). El atajo, Esc y soltarla
// al elegir una herramienta de Excalidraw los lleva la capa (InkLayer).
import { useEffect, useState } from "react";
import { t } from "./i18n";
import { INK_COLORS, INK_MODES, INK_SIZES, pickColor, pickMode, pickSize, setInkTool, toggleInk,
         toolColor, useInkTool, type InkMode } from "./inkTool";
import { comboLabel, shortcut } from "./shortcuts";
import { filterColor } from "./inkView";

// Iconos de 24 px, trazo de 2 (como los del resto de la barra).
const MODE_ICON: Record<InkMode, string> = {
  rotulador: "M15 5l4 4 M4 20l1-5L15 5l4 4L9 19l-5 1z",
  pluma: "M12 19l7-7 3 3-7 7-3-3z M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z M2 2l7.6 7.6 M13 11a2 2 0 1 1-4 0 2 2 0 0 1 4 0z",
  subrayador: "M9 11l-6 6v3h9l3-3 M22 12l-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4",
  borrador: "M7 21l-4.3-4.3c-1-1-1-2.5 0-3.4l9.6-9.6c1-1 2.5-1 3.4 0l5.6 5.6c1 1 1 2.5 0 3.4L13 21 M22 21H7 M5 11l9 9",
};
const COLOR_KEY: Record<string, string> = {
  "#1e1e1e": "tinta.color.tinta", "#e03131": "tinta.color.rojo", "#1971c2": "tinta.color.azul",
  "#2f9e44": "tinta.color.verde", "#fab005": "tinta.color.amarillo",
};
const SIZE_KEY: Record<number, string> = { 2: "tinta.grosor.fino", 4: "tinta.grosor.medio", 8: "tinta.grosor.grueso" };

const Ico = ({ d }: { d: string }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);

/** `filter`: el de la tinta del skin, para que los colores se vean como saldrán en la pizarra. */
export function InkMenu({ filter }: { filter: string }) {
  const tool = useInkTool();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const click = (e: PointerEvent) => {
      const el = e.target as HTMLElement | null;
      if (el?.closest?.(".tb-ink")) return;
      setOpen(false);
      // El clic en la pizarra que cierra el menú, con la tinta activa, no pinta un punto.
      if (el?.closest?.(".ink-input")) {
        e.stopPropagation();
        e.preventDefault();
      }
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", click, true);
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("pointerdown", click, true); window.removeEventListener("keydown", key, true); };
  }, [open]);
  const combo = shortcut("tinta.activar");
  const title = combo ? t("tinta.boton.titulo_atajo", { atajo: comboLabel(combo) }) : t("tinta.boton.titulo");
  const color = toolColor(tool);
  const seen = (c: string) => filterColor(c, filter);
  return (
    <span className="tb-ink">
      <button type="button" className={tool.active ? "tb-on tb-ink-main" : "tb-ink-main"} aria-pressed={tool.active}
              onClick={() => setInkTool(toggleInk)} title={title} aria-label={t("tinta.boton")}>
        <Ico d={MODE_ICON[tool.mode]} /><span className="tb-label">{t("tinta.boton")}</span>
        <i className="tb-ink-dot" style={{ background: seen(color) }} aria-hidden="true" />
      </button>
      <button type="button" className={tool.active ? "tb-on tb-ink-more" : "tb-ink-more"} aria-expanded={open}
              aria-haspopup="menu" aria-label={t("tinta.menu")} title={t("tinta.menu")}
              onClick={() => setOpen((o) => !o)}>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
      </button>
      {open && (
        <div className="card-menu tb-ink-menu" role="menu" aria-label={t("tinta.menu")}>
          {INK_MODES.map((m) => (
            <button key={m} type="button" role="menuitemradio" aria-checked={tool.active && tool.mode === m}
                    className={tool.mode === m ? "it on" : "it"}
                    onClick={() => { setInkTool((s) => pickMode(s, m)); setOpen(false); }}>
              <Ico d={MODE_ICON[m]} />
              <span>{t(`tinta.modo.${m}`)}</span>
            </button>
          ))}
          <hr />
          <div className="ink-row" role="group" aria-label={t("tinta.colores")}>
            {INK_COLORS.map((c) => (
              <button key={c} type="button" className="ink-swatch" aria-pressed={color === c}
                      aria-label={t(COLOR_KEY[c])} title={t(COLOR_KEY[c])}
                      onClick={() => setInkTool((s) => pickColor(s, c))}>
                <i style={{ background: seen(c) }} />
              </button>
            ))}
          </div>
          <div className="ink-row" role="group" aria-label={t("tinta.grosor")}>
            {INK_SIZES.map((sz) => (
              <button key={sz} type="button" className="ink-size" aria-pressed={tool.size === sz}
                      aria-label={t(SIZE_KEY[sz])} title={t(SIZE_KEY[sz])}
                      onClick={() => setInkTool((s) => pickSize(s, sz))}>
                <i style={{ height: Math.max(2, sz), background: seen(color) }} />
              </button>
            ))}
          </div>
          <div className="hint ink-hint">{t("tinta.ayuda")}</div>
        </div>
      )}
    </span>
  );
}
