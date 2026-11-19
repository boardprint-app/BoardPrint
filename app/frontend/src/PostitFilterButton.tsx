// Filtro de post-its (plan §3, D80, 4C): un botón de embudo en una esquina con la cuenta de lo
// oculto, que abre los filtros por tipo, estado y autor. Es de la vista: nunca toca la escena.
// Botón y panel van por encima de todo lo de la pizarra.
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";
import { filteredOut, KIND_LABEL, POSTIT_KINDS, type PostitData, type PostitFilter } from "./postit";
import { setStore, useStore } from "./store";

export function PostitFilterButton({ postits }: { postits: PostitData[] }) {
  const { postitFilter: f } = useStore();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const hidden = postits.filter((p) => filteredOut(f, p)).length;
  const set = (patch: Partial<PostitFilter>) => setStore({ postitFilter: { ...f, ...patch } });

  // Se cierra con un clic fuera o con Esc.
  useEffect(() => {
    if (!open) return;
    const down = (ev: PointerEvent) => { if (!box.current?.contains(ev.target as Node)) setOpen(false); };
    const key = (ev: KeyboardEvent) => { if (ev.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("keydown", key, true);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("keydown", key, true);
    };
  }, [open]);

  const chip = (label: string, on: boolean, toggle: () => void, swatch?: string) => (
    <button key={label} className="pf-chip" aria-pressed={on} onClick={toggle}>
      {swatch && <i style={{ background: `var(--pi-${swatch})`, boxShadow: `inset 0 0 0 1.5px var(--pi-${swatch}-b)` }} />}
      {label}
    </button>
  );

  return (
    <div className="pf" ref={box}>
      <button className="pf-btn" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)}
              title={t("lienzo.filtro.titulo")}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinejoin="round" aria-hidden="true"><path d="M3 5h18l-7 8v6l-4 2v-8z" /></svg>
        {t("lienzo.filtro.boton")}
        {hidden > 0 && <span className="pf-count">
          {t(hidden > 1 ? "lienzo.filtro.ocultos_varios" : "lienzo.filtro.ocultos_uno", { n: hidden })}
        </span>}
      </button>
      {open && (
        <div className="pf-pop" role="dialog" aria-label={t("lienzo.filtro.dialogo")}>
          <h4>{t("lienzo.filtro.tipo")}</h4>
          <div className="pf-row">
            {POSTIT_KINDS.map((k) => chip(KIND_LABEL[k], f.kinds[k],
              () => set({ kinds: { ...f.kinds, [k]: !f.kinds[k] } }), k))}
          </div>
          <h4>{t("lienzo.filtro.estado")}</h4>
          <div className="pf-row">{chip(t("lienzo.filtro.descartados"), f.discarded, () => set({ discarded: !f.discarded }))}</div>
          <h4>{t("lienzo.filtro.autor")}</h4>
          <div className="pf-row">{chip(t("lienzo.filtro.agente"), f.agent, () => set({ agent: !f.agent }))}</div>

        </div>
      )}
    </div>
  );
}
