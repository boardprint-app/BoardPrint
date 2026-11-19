// Flechas de un bloque a una carpeta (plan §3, D109, D139, 8A): en cada ejecución que termina
// bien copian las salidas a la carpeta. La elección vive en la flecha: su etiqueta dice cuántos
// archivos y si alguno sobrescribe; un clic abre la lista por archivo, con *Nuevo _n* (por
// defecto) o *Sobrescribir*, que se guarda en `customData.overwrite` de la flecha. La etiqueta
// solo sale con el ratón sobre la línea o sobre ella, con la flecha seleccionada o con su lista
// abierta (R37).
import { useEffect, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { useSceneTick } from "./useSceneTick";
import { useHoveredConnection } from "./useHoveredConnection";
import { useStore } from "./store";
import { isConnection, isFolderEl } from "./connections";
import { copyLabel, outputFiles, setOverwrite } from "./cards";
import { labelSpot } from "./ports";
import { t } from "./i18n";

type Arrow = ExcalidrawElement & {
  points: readonly (readonly [number, number])[];
  startBinding?: { elementId: string } | null; endBinding?: { elementId: string } | null;
};
type Cd = { from?: string | null; overwrite?: string[] };

type Props = { api: ExcalidrawImperativeAPI; onOverwrite: (arrow: string, overwrite: string[]) => void };

export function FolderArrows({ api, onOverwrite }: Props) {
  const { blocks, problems } = useStore();
  const [open, setOpen] = useState<string | null>(null);
  const [overLabel, setOverLabel] = useState<string | null>(null);
  useSceneTick(api);
  const hovered = useHoveredConnection(api);

  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
    const click = (e: PointerEvent) => {
      if (!(e.target as HTMLElement)?.closest?.(".copy-pop, .copy-label")) setOpen(null);
    };
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", click, true);
    return () => { window.removeEventListener("keydown", key, true); window.removeEventListener("pointerdown", click, true); };
  }, [open]);

  const els = api.getSceneElements();
  const byId = new Map(els.map((e) => [e.id, e]));
  const st = api.getAppState();
  const z = st.zoom.value;
  const view = (x: number, y: number) => ({ x: (x + st.scrollX) * z, y: (y + st.scrollY) * z });

  const arrows = (els.filter(isConnection) as Arrow[]).flatMap((a) => {
    const src = a.startBinding && byId.get(a.startBinding.elementId);
    const dst = a.endBinding && byId.get(a.endBinding.elementId);
    if (!src || !dst || !isFolderEl(dst) || problems.some((p) => p.arrow === a.id)) return [];
    if (![hovered, open, overLabel].includes(a.id) && !st.selectedElementIds[a.id]) return [];
    const cd = (a.customData ?? {}) as Cd;
    const names = outputFiles(blocks[src.id]?.outputs as never, cd.from ?? null);
    const spot = labelSpot(a.points);
    const folder = String((dst.customData as { path?: string })?.path ?? "").split(/[\\/]/).pop();
    return [{ id: a.id, names, overwrite: cd.overwrite ?? [], folder, ...view(a.x + spot.x, a.y + spot.y) }];
  });

  return (
    <>
      {arrows.map((w) => (
        <div key={w.id} className="copy-wrap" style={{ left: w.x, top: w.y }}
             onPointerEnter={() => setOverLabel(w.id)} onPointerLeave={() => setOverLabel(null)}>
          <button type="button" className="copy-label" aria-expanded={open === w.id}
                  title={t("bloques.copia.titulo")}
                  onClick={() => setOpen(open === w.id ? null : w.id)}>
            {copyLabel(w.names, w.overwrite)}
          </button>
          {open === w.id && (
            <div className="copy-pop" role="dialog" aria-label={t("bloques.copia.al_copiar_a", { folder: w.folder ?? "" })}>
              <div className="q">{t("bloques.copia.al_copiar_a_q", { folder: w.folder ?? "" })}</div>
              {!w.names.length && (
                <div className="last">{t("bloques.copia.sin_archivos")}</div>
              )}
              {w.names.map((n) => {
                const over = w.overwrite.includes(n);
                return (
                  <div key={n} className="fr">
                    <span title={n}>{n}</span>
                    <span className="seg" role="group" aria-label={n}>
                      <button type="button" aria-pressed={!over} onClick={() => onOverwrite(w.id, setOverwrite(w.overwrite, n, false))}>{t("bloques.copia.nuevo_n")}</button>
                      <button type="button" aria-pressed={over} onClick={() => onOverwrite(w.id, setOverwrite(w.overwrite, n, true))}>{t("bloques.copia.sobrescribir")}</button>
                    </span>
                  </div>
                );
              })}
              <div className="last">{t("bloques.copia.nuevo_nota")} (<code>_1</code>, <code>_2</code>…). {t("bloques.copia.nunca_pisa")}</div>
            </div>
          )}
        </div>
      ))}
    </>
  );
}
