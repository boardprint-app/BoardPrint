// *Ajustes → Atajos* (plan D97, D185): cada acción de la tabla central (shortcuts.ts) con su
// atajo. *Cambiar* graba la siguiente combinación (una letra o una cifra, con o sin Ctrl, Mayús
// y Alt; Esc cancela); si choca, se dice con qué y hay que confirmarlo: con otra acción de la
// app, esa se queda sin atajo en el mismo cambio; con Excalidraw, la app la atiende antes y la
// fila dice qué pierde Excalidraw. *Quitar* la deja sin atajo; *Restablecer*, las de por defecto.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { AppSettings } from "../appSettings";
import { t } from "../i18n";
import { assignChanges, clash, comboFromEvent, comboLabel, effectiveShortcuts, excalidrawClash, SHORTCUTS,
         type Clash } from "../shortcuts";
import { Row, TabHead, useSaver } from "./common";

type Proposal = { action: string; combo: string; clash: Clash };

export function ShortcutsTab({ app }: { app: AppSettings }) {
  const { save, errors, busy } = useSaver();
  const now = effectiveShortcuts(app.atajos);
  const [capturing, setCapturing] = useState<string | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (capturing) field.current?.focus();
  }, [capturing]);

  const assign = (action: string, combo: string) =>
    save(`atajo.${action}`, { atajos: assignChanges(action, combo, app.atajos) });

  // Se graba en un campo de solo lectura: así ningún atajo de la app salta mientras tanto
  // (`typing`) y Excalidraw no la recibe (la ventana está fuera de su lienzo). El Escape no
  // llega a cerrar la ventana: se queda aquí (`preventDefault`).
  const onKey = (action: string) => (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Tab") return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === "Escape") {
      setCapturing(null);
      return;
    }
    const combo = comboFromEvent(e.nativeEvent);
    if (!combo) return;                          // un modificador solo: falta la letra
    setCapturing(null);
    if (combo === now[action]) return;
    const hit = clash(action, combo, app.atajos);
    if (hit) setProposal({ action, combo, clash: hit });
    else void assign(action, combo);
  };

  return (
    <>
      <TabHead id="st-atajos" title={t("ajustes.pestana.atajos")}>
        <button className="pull-btn" disabled={busy !== null}
                onClick={() => { setProposal(null); void save("atajos", { atajos_por_defecto: true }); }}>
          {t("ajustes.atajos.restablecer")}
        </button>
      </TabHead>
      <p className="st-intro">{t("ajustes.atajos.intro")}</p>
      {errors.atajos && <p className="pull-error" role="alert">{errors.atajos}</p>}
      {SHORTCUTS.map((s) => {
        const id = `atajo.${s.id}`;
        const combo = now[s.id];
        const lost = combo ? excalidrawClash(s.id, combo) : null;
        const p = proposal?.action === s.id ? proposal : null;
        return (
          <div key={s.id} className="st-shortcut">
            <Row id={id} title={t(s.label)} error={errors[id]}
                 hint={lost ? t("ajustes.atajos.pierde", { nombre: lost }) : undefined}>
              {capturing === s.id
                ? <input ref={field} readOnly className="st-capture" value={t("ajustes.atajos.pulsa")}
                         aria-label={t("ajustes.atajos.pulsa_de", { accion: t(s.label) })}
                         onKeyDown={onKey(s.id)} onBlur={() => setCapturing(null)} />
                : <kbd className={combo ? "st-kbd" : "st-kbd st-none"}>{combo ? comboLabel(combo) : t("ajustes.atajos.sin_atajo")}</kbd>}
              <span className="st-row-btns">
                <button className="pull-btn" disabled={busy !== null}
                        onClick={() => { setProposal(null); setCapturing(s.id); }}>
                  {t("ajustes.atajos.cambiar")}
                </button>
                <button className="pull-btn" disabled={busy !== null || !combo}
                        onClick={() => { setProposal(null); void assign(s.id, ""); }}>
                  {t("ajustes.atajos.quitar")}
                </button>
              </span>
            </Row>
            {p && (
              <div className="st-confirm" role="alertdialog" aria-label={t("ajustes.atajos.choque")}>
                <p>{p.clash.con === "app"
                  ? t("ajustes.atajos.choque_app", { combo: comboLabel(p.combo), nombre: p.clash.nombre })
                  : t("ajustes.atajos.choque_excalidraw", { combo: comboLabel(p.combo), nombre: p.clash.nombre })}</p>
                <div className="st-row-btns">
                  <button className="pull-btn" onClick={() => setProposal(null)}>{t("ajustes.cancelar")}</button>
                  <button className="pull-btn pull-apply" disabled={busy !== null}
                          onClick={() => { setProposal(null); void assign(p.action, p.combo); }}>
                    {t("ajustes.atajos.asignar")}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
