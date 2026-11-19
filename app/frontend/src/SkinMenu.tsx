// Selector del skin en la píldora del proyecto (plan D79): también se elige en *Ajustes →
// Apariencia*, pero se queda aquí como acceso rápido, para comparar los cinco (D179).
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";
import { SKINS, type SkinId } from "./skins";

type Props = { skin: SkinId; onSkin: (id: SkinId) => void };

export function SkinMenu({ skin, onSkin }: Props) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="pill-menu" ref={box}>
      <button className="pill-home" aria-label={t("lienzo.skin.menu")} title={t("lienzo.skin.menu")}
              aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-.9-.7-1.4-.7-2.3 0-1 .8-1.6 1.8-1.6H17a4 4 0 0 0 4-4c0-4.7-4-8.5-9-8.5z" />
          <circle cx="7.5" cy="11" r="1" /><circle cx="10.5" cy="7" r="1" /><circle cx="15" cy="7.5" r="1" />
        </svg>
      </button>
      {open && (
        <div className="pill-pop" role="menu" aria-label={t("lienzo.skin.menu")}>
          <div className="pill-pop-title">{t("lienzo.skin.menu")}</div>

          {SKINS.map((s) => (
            <button key={s.id} role="menuitemradio" aria-checked={s.id === skin}
                    onClick={() => { onSkin(s.id); setOpen(false); }}>
              <span className={`skin-swatch swatch-${s.id}`} aria-hidden="true" />
              {s.name}
              {s.id === skin && <span className="pill-check" aria-hidden="true">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
