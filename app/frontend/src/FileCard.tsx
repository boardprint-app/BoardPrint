// Tarjeta de un archivo o de una carpeta (plan §3, D59, D131, D139), pintada dentro de un
// `embeddable` como los bloques. No es un bloque: no se ejecuta ni tiene sello (D131); su
// estado (si se encuentra, su tamaño, lo que entra) lo da el sondeo del backend (`sources`).
//
// Lo elegido en el artifact «Archivos FF 4.8»: el archivo es una etiqueta de una línea con el
// enchufe a la derecha y, seleccionado, una barra encima con *Abrir* partido (D141) y «···»
// (el menú). La carpeta es la de verdad, estrecha, con hasta tres papeles que asoman, el tipo
// escrito arriba de cada uno, y un chip con lo que entra cuando no es todo; enchufe de entrada
// (recibe salidas, D109) y de salida. Lo que no está lleva la banda roja «No encontrado» con
// «Buscar de nuevo». Toda la tarjeta deja pasar el ratón al lienzo (se selecciona y se arrastra
// como cualquier elemento), salvo sus botones y sus enchufes. *Previsualizar* (D135) sale en la
// barra si el tipo se puede ver en la app; el doble clic hace lo mismo (App.tsx). Un Excel lleva
// además un enchufe de entrada: la flecha de escritura de un bloque (PLAN_EXCEL §3.3), con lo
// que va a cada nombre y *Escribir copia* (ExcelWrite.tsx).
import { useLayoutEffect, useRef, type CSSProperties } from "react";
import { setStore, useStore } from "./store";
import { t } from "./i18n";
import { confirmCard, openCard, relocateCard } from "./cardActions";
import { contentOf, fmtSize, folderChip, previewKind, typeFamily, typeLabel } from "./cards";
import { CARD_SOCKET_Y } from "./connections";
import { portColor, SOCKET_H } from "./ports";
import { fmt } from "./BlockOutputs";
import { isExcelPath, nameState, writeTarget, type ExcelName, type ExcelWrite } from "./excel";
import { WriteChooser, WriteFooter } from "./ExcelWrite";

const OPEN_WITH = /Windows/.test(navigator.userAgent);   // «Abrir con» solo en Windows (D141)

export function FileIcon({ type, size = "md" }: { type: string; size?: "sm" | "md" | "big" }) {
  return (
    <span className={`ficon ficon-${size} ff-${typeFamily(type)}`} aria-hidden="true">
      <i /><b>{typeLabel(type) || "·"}</b>
    </span>
  );
}

export function FolderIcon({ small }: { small?: boolean }) {
  return <span className={`ico-folder${small ? " sm" : ""}`} aria-hidden="true" />;
}

const baseName = (p: string) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? p;
const dirName = (p: string) => {
  const parts = p.replace(/[\\/]+$/, "").split(/([\\/])/);
  return parts.slice(0, -1).join("");
};

type Props = {
  id: string;
  kind: "file" | "folder";
  data: { path?: string; content?: unknown };
  selected: boolean;
  height: number;
  onHeight: (id: string, height: number) => void;
  onMenu: (id: string, at: { x: number; y: number }) => void;
  onRemove: (id: string) => void;
};

export function FileCard({ id, kind, data, selected, height, onHeight, onMenu, onRemove }: Props) {
  const { sources, ports, run } = useStore();
  const view = sources[id];
  const inner = useRef<HTMLDivElement>(null);
  const path = String(data.path ?? "");
  const name = baseName(path);
  const type = view?.type ?? (kind === "folder" ? "carpeta" : "archivo");
  const lost = !!view?.checked && !view.ok && !view.big && /^no encontrad/.test(view.reason ?? "");
  const unreadable = !!view?.checked && !view.ok && !view.big && !lost;

  // La tarjeta mide lo que pide su contenido (la banda y los botones de «No encontrado»).
  useLayoutEffect(() => {
    const box = inner.current;
    if (!box) return;
    const fit = () => {
      const need = Math.ceil(box.offsetHeight);
      if (Math.abs(need - height) >= 1) onHeight(id, need);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(box);
    return () => ro.disconnect();
  }, [id, height, onHeight]);

  const sock = (side: "in" | "out", port: string) => (
    <div className={`sock sock-${side}${side === "in" ? " free" : ""}`} data-port={port} data-type={side === "in" ? "*" : type}
         style={{ top: CARD_SOCKET_Y[kind] - SOCKET_H / 2, height: SOCKET_H, "--c": portColor(type, ports) } as CSSProperties}>
      <b className="dot" />
      <span className="tip" role="tooltip">
        {side === "in"
          ? <><b>{t("bloques.archivos.salidas_de_bloque")}</b> · {t(kind === "file" ? "bloques.archivos.se_escriben" : "bloques.archivos.se_copian")}</>
          : <><b>{port}</b> {t("bloques.tarjeta.salida")} · {ports[type]?.label ?? type}</>}
      </span>
    </div>
  );

  const menuAt = (ev: React.MouseEvent) => {
    const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    onMenu(id, { x: r.left, y: r.bottom + 4 });
  };

  const lostBox = (
    <div className="fc-lost">
      <div className="fc-path" title={path}>{dirName(path) || path}</div>
      <div className="fc-btns">
        <button type="button" className="fbtn main" onClick={() => void relocateCard(id)}>{t("bloques.archivos.buscar_de_nuevo")}</button>
        <button type="button" className="fbtn" onClick={() => onRemove(id)}>{t("bloques.archivos.quitar")}</button>
      </div>
    </div>
  );

  if (kind === "folder") {
    const c = contentOf(data.content);
    const chip = folderChip(c, view);
    const more = Math.max(0, (view?.files ?? 0) - (view?.peek.length ?? 0));
    return (
      <div className={`fcard fcard-folder${lost ? " lost" : ""}${selected ? " sel" : ""}`} data-block={id} data-kind="folder">
        {lost && <div className="fc-band fc-band-top">{t("bloques.archivos.no_encontrada")}</div>}
        <div className="fcard-inner" ref={inner}>
          <div className="fold">
            <div className="fold-back" />
            <div className="fold-files">
              {(view?.peek ?? []).map((t, i) => <FileIcon key={i} type={t} />)}
            </div>
            <div className="fold-front" />
            {more > 0 && <span className="fold-more">+{more}</span>}
          </div>
          <div className="fk-name" title={path}>{name}</div>
          <div className="fk-meta">
            {view?.checked && !lost && <span>{view.files === 1 ? t("bloques.archivos.n_archivos_uno") : t("bloques.archivos.n_archivos_varios", { n: view.files })}</span>}
            {!view?.checked && <span>{t("bloques.archivos.comprobando")}</span>}
            {chip && <span className="chip">{chip}</span>}
          </div>
          {view?.big && (
            <div className="fk-big">
              <span>{t("bloques.archivos.marcados", { size: fmtSize(view.size) })}</span>
              <button type="button" className="fbtn main" disabled={run !== null} onClick={() => void confirmCard(id)}>
                {t("bloques.archivos.calcular_hash")}
              </button>
            </div>
          )}
          {view?.notice && <div className="fk-notice" title={view.notice}>⚠ {t("bloques.archivos.copia_fallo", { notice: view.notice })}</div>}
          {unreadable && <div className="fk-notice">⚠ {view!.reason}</div>}
          {lost && lostBox}
        </div>
        <div className="block-socks">{sock("in", "carpeta")}{sock("out", "carpeta")}</div>
      </div>
    );
  }

  return (
    <div className={`fcard fcard-file${lost ? " lost" : ""}${selected ? " sel" : ""}`} data-block={id} data-kind="file">
      {selected && !lost && (
        <div className="fc-bar">
          {previewKind(type) && view?.ok && (
            <button type="button" onClick={() => setStore({ preview: id })}>{t("bloques.archivos.previsualizar")}</button>
          )}
          <span className="fc-split">
            <button type="button" onClick={() => void openCard(id)}>{t("bloques.salidas.abrir")}</button>
            {OPEN_WITH && <button type="button" className="more" title={t("bloques.archivos.abrir_con_titulo")}
                                  aria-label={t("bloques.archivos.abrir_con")} onClick={() => void openCard(id, true)}>▾</button>}
          </span>
          <button type="button" title={t("bloques.archivos.mas")} aria-label={t("bloques.archivos.mas_acciones")} onClick={menuAt}>···</button>
        </div>
      )}
      {lost && <div className="fc-band fc-band-top">{t("bloques.archivos.no_encontrado")}</div>}
      <div className="fcard-inner" ref={inner}>
        <div className="fc-row">
          <FileIcon type={type} size="sm" />
          <span className="fc-name" title={path}>{name}</span>
          {view?.ok && <span className="fc-ext">{fmtSize(view.size)}</span>}
        </div>
        {view?.ok && view.names && <ExcelNames id={id} names={view.names} write={view.write ?? null} />}
        {view?.ok && view.names && view.write && <WriteFooter cardId={id} write={view.write} />}
        {view?.ok && view.names_error && <div className="fk-notice">⚠ {t("bloques.excel.ilegible", { error: view.names_error })}</div>}
        {unreadable && <div className="fk-notice">⚠ {view!.reason}</div>}
        {lost && lostBox}
      </div>
      <div className="block-socks">{isExcelPath(path) && sock("in", "escribir")}{sock("out", "archivo")}</div>
    </div>
  );
}

/** Los nombres definidos de un Excel (PLAN_EXCEL §3.5): el valor con su unidad y la celda. Lo
 *  no admitido va en gris y, con lo que no tiene valor, dice su motivo al pasar el ratón. Con
 *  flechas de escritura (`write`), cada nombre donde se puede escribir lleva su `← salida`. */
function ExcelNames({ id, names, write }: { id: string; names: ExcelName[]; write: ExcelWrite | null }) {
  if (!names.length) return <div className="fc-names-none">{t("bloques.excel.sin_nombres")}</div>;
  return (
    <ul className="fc-names">
      {names.map((n) => {
        const state = nameState(n);
        const value = state === "ok" ? <>{fmt(n.valor)}{n.unidad && <em> {n.unidad}</em>}</>
          : t(`bloques.excel.${state}`);
        return (
          <li key={n.nombre} className={`fcn fcn-${state}`} title={n.motivo ?? undefined}>
            <span className="fcn-n">{n.nombre}</span>
            <span className="fcn-w">{n.where ?? "—"}</span>
            <span className="fcn-v">{value}</span>
            {write && (writeTarget(n) ? <span className="fcn-x"><WriteChooser cardId={id} n={n} write={write} /></span>
              : n.formula !== null && state !== "no_admitido" && <span className="fcn-x fcn-f">{t("bloques.excel.escribir.formula")}</span>)}
          </li>
        );
      })}
    </ul>
  );
}
