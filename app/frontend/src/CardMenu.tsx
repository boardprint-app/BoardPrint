// Menú contextual de las tarjetas de archivo y de carpeta, y del bloque (plan §3, D59, D139,
// D141). Sustituye al de Excalidraw sobre esas tarjetas: el de Excalidraw habla de capas y
// estilos, que no significan nada en un archivo.
//
// Archivo y carpeta (7B): cabecera con el nombre y la carpeta, *Abrir* partido (la flecha,
// «Abrir con» de Windows), abrir en el explorador, copiar ruta, «Buscar otro archivo…» y quitar
// de la pizarra (nunca borra el archivo). La carpeta abre su vista dentro de la app.
// *Previsualizar* solo en lo que se puede ver en la app (D135). *Preguntar al agente* (D176)
// abre un hilo anclado a la tarjeta, o a todo lo seleccionado si la tarjeta es parte de una
// selección de varios (`group`).
// En un archivo, también *Leer con el agente* y *Editar con el agente* (D176, OfficeMenu.tsx).
// Bloque (9C): Ejecutar, *Guardar también en…* (D109), *Preguntar al agente* y quitar.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { OfficeItems } from "./OfficeMenu";
import { menuPlace, previewKind } from "./cards";
import { addCards, cardInfo, copyPath, openCard, relocateCard, revealCard, saveTo, type CardInfo } from "./cardActions";
import { FileIcon, FolderIcon } from "./FileCard";
import { t } from "./i18n";
import { send } from "./socket";
import { setStore, useStore } from "./store";

export type MenuTarget = { id: string; kind: "file" | "folder" | "block"; at: { x: number; y: number }; group?: string[] };

const I = {
  open: <path d="M14 3h7v7M21 3l-9 9M19 14v6H4V5h6" />,
  folder: <path d="M3 7h6l2 2h10v10H3z" />,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M4 16V4h12" /></>,
  eye: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
  find: <path d="M4 4h16v16H4zM9 4v16" />,
  remove: <path d="M5 12h14" />,
  run: <path d="M7 5l12 7-12 7z" />,
  clip: <path d="M21 11l-8.5 8.5a5 5 0 01-7-7L14 4a3.5 3.5 0 015 5l-8.5 8.5a2 2 0 01-3-3L15 7" />,
  ask: <path d="M4 5h16v11H9l-5 4z" />,
};
const Ico = ({ d }: { d: ReactNode }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
const OPEN_WITH = /Windows/.test(navigator.userAgent);

type Props = { target: MenuTarget; onClose: () => void; onRemove: (id: string) => void; onAsk: (ids: string[]) => void;
                api?: ExcalidrawImperativeAPI | null };

/** *Preguntar al agente* (D176): sobre la tarjeta, o sobre todo lo seleccionado. */
export const askLabel = (n: number) => (n > 1 ? t("lienzo.menu.preguntar_varios", { n }) : t("lienzo.menu.preguntar"));

export function CardMenu({ target, onClose, onRemove, onAsk, api = null }: Props) {
  const { run, sources } = useStore();
  const [info, setInfo] = useState<CardInfo | null>(null);
  const { id, kind } = target;
  // Que no se salga de la ventana: con su tamaño de verdad, también cuando crece (*Editar con
  // el agente* abre un cuadro dentro) o la ventana cambia.
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 268, height: 370 });
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setSize({ width: el.offsetWidth, height: el.offsetHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [kind]);

  useEffect(() => {
    if (kind !== "block") void cardInfo(id).then(setInfo);
  }, [id, kind]);

  // Se cierra con Esc, con un clic fuera o al desplazar el lienzo.
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const click = (e: PointerEvent) => { if (!(e.target as HTMLElement)?.closest?.(".card-menu")) onClose(); };
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", click, true);
    window.addEventListener("wheel", onClose, true);
    return () => {
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("pointerdown", click, true);
      window.removeEventListener("wheel", onClose, true);
    };
  }, [onClose]);

  const act = (fn: () => unknown) => () => { onClose(); void fn(); };
  const ask = target.group && target.group.length > 1 ? target.group : [id];
  const askItem = (
    <button type="button" role="menuitem" className="it" onClick={act(() => onAsk(ask))}>
      <Ico d={I.ask} />{askLabel(ask.length)}
    </button>
  );
  const style = menuPlace(target.at, size, { width: window.innerWidth, height: window.innerHeight });

  if (kind === "block") {
    return (
      <div className="card-menu" role="menu" style={style} ref={box}>
        <button type="button" role="menuitem" className="it" disabled={run !== null}
                onClick={act(() => send({ type: "run", block: id }))}><Ico d={I.run} />{t("lienzo.menu.ejecutar")}</button>
        <button type="button" role="menuitem" className="it" onClick={act(() => saveTo(id))}>
          <FolderIcon small />{t("lienzo.menu.guardar_en")}
        </button>
        {askItem}
        <hr />
        <button type="button" role="menuitem" className="it" onClick={act(() => onRemove(id))}>
          <Ico d={I.remove} />{t("lienzo.menu.quitar")}<kbd>{t("lienzo.menu.supr")}</kbd>
        </button>
      </div>
    );
  }

  const exists = info ? info.exists : sources[id]?.ok !== false;
  return (
    <div className="card-menu" role="menu" style={style} ref={box}>
      <div className="mh">
        {kind === "folder" ? <FolderIcon /> : <FileIcon type={sources[id]?.type ?? "archivo"} size="sm" />}
        <div>
          <div className="mh-name">{info?.name ?? "…"}</div>
          <div className="mh-path" title={info?.path}>{info?.folder ?? ""}</div>
        </div>
      </div>
      {kind === "folder" ? (
        <button type="button" role="menuitem" className="it" disabled={!exists}
                onClick={act(() => setStore({ folderView: id }))}><Ico d={I.open} />{t("lienzo.menu.abrir")}</button>
      ) : (
        <div className="it split">
          <button type="button" role="menuitem" className="main" disabled={!exists} onClick={act(() => openCard(id))}>
            <Ico d={I.open} />{t("lienzo.menu.abrir")}
          </button>
          {OPEN_WITH && (
            <button type="button" role="menuitem" className="more" disabled={!exists} title={t("lienzo.menu.abrir_con_titulo")}
                    aria-label={t("lienzo.menu.abrir_con")} onClick={act(() => openCard(id, true))}>▸</button>
          )}
        </div>
      )}
      {kind === "file" && previewKind(sources[id]?.type ?? "") && (
        <button type="button" role="menuitem" className="it" disabled={!exists}
                onClick={act(() => setStore({ preview: id }))}><Ico d={I.eye} />{t("lienzo.menu.previsualizar")}</button>
      )}
      <button type="button" role="menuitem" className="it" disabled={!exists} onClick={act(() => revealCard(id))}>
        <Ico d={I.folder} />{t("lienzo.menu.explorador")}
      </button>
      <button type="button" role="menuitem" className="it" onClick={act(() => copyPath(id))}>
        <Ico d={I.copy} />{t("lienzo.menu.copiar_ruta")}
      </button>
      <button type="button" role="menuitem" className="it" onClick={act(() => relocateCard(id))}>
        <Ico d={I.find} />{kind === "folder" ? t("lienzo.menu.buscar_carpeta") : t("lienzo.menu.buscar_archivo")}
      </button>
      {askItem}
      {kind === "file" && <OfficeItems id={id} type={sources[id]?.type ?? ""} name={info?.name ?? t("lienzo.menu.el_archivo")}
                                       exists={exists} api={api} onClose={onClose} />}
      <hr />
      <button type="button" role="menuitem" className="it" onClick={act(() => onRemove(id))}>
        <Ico d={I.remove} />{t("lienzo.menu.quitar")}<kbd>{t("lienzo.menu.supr")}</kbd>
      </button>
      <div className="hint">{kind === "folder" ? t("lienzo.menu.aviso_carpeta") : t("lienzo.menu.aviso_archivo")}</div>
    </div>
  );
}

/** *Añadir archivo* en la barra de la pizarra (D59, R37): archivos (varios a la vez) o una
 *  carpeta, con el diálogo del sistema, en el centro de la vista. El desplegable dice para qué
 *  sirve: «Archivo» a secas se leía como el menú Archivo de cualquier programa. Arrastrarlos
 *  desde el explorador también vale. */
export function AddFileMenu({ at, onExisting }: { at: () => { x: number; y: number }; onExisting?: (ids: string[]) => void }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const click = (e: PointerEvent) => { if (!(e.target as HTMLElement)?.closest?.(".tb-file")) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", click, true);
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("pointerdown", click, true); window.removeEventListener("keydown", key, true); };
  }, [open]);
  const add = (kind: "file" | "folder") => { setOpen(false); void addCards(at(), kind, undefined, onExisting); };
  return (
    <span className="tb-file">
      <button type="button" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((o) => !o)}
              title={t("lienzo.anadir.titulo")} aria-label={t("lienzo.anadir.boton")}>
        <Ico d={I.clip} /><span className="tb-label">{t("lienzo.anadir.boton")}</span>
      </button>
      {open && (
        <div className="card-menu tb-file-menu" role="menu">
          <div className="tb-file-why">{t("lienzo.anadir.explicacion")}</div>
          <button type="button" role="menuitem" className="it two" onClick={() => add("file")}>
            <Ico d={I.find} />
            <span><b>{t("lienzo.anadir.archivos")}</b><small>{t("lienzo.anadir.archivos_tipos")}</small></span>
          </button>
          <button type="button" role="menuitem" className="it two" onClick={() => add("folder")}>
            <FolderIcon small />
            <span><b>{t("lienzo.anadir.carpeta")}</b><small>{t("lienzo.anadir.carpeta_detalle")}</small></span>

          </button>
        </div>
      )}
    </span>
  );
}
