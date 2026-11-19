// *Previsualizar* un archivo dentro de la app (plan D135, D139): una ventana encima de la
// pizarra con el skin. El PDF, con el visor que trae el navegador (WebView2 en la app); la
// imagen, tal cual; el texto, hasta 2 MB; un HTML (los informes de los bloques) pintado en un
// iframe aislado, sin scripts; el STEP, en el visor propio (StepViewer, D62). El archivo lo da
// el backend por la tarjeta (`…/cards/<id>/raw`), nunca por una ruta de la interfaz.
import { lazy, Suspense, useEffect, useState } from "react";
import { apiFetch, token } from "./auth";
import { fmtSize, previewKind, TEXT_PREVIEW_MAX } from "./cards";
import { openCard } from "./cardActions";
import { t } from "./i18n";
import { FileIcon } from "./FileCard";
import { getStore, useStore } from "./store";

const StepViewer = lazy(() => import("./StepViewer"));
const OPEN_WITH = /Windows/.test(navigator.userAgent);

/** URL del archivo de una tarjeta. `withToken`: para un <img> o un <iframe>, que no mandan la
 *  cabecera del token; `version` hace que un archivo cambiado no salga de la caché. */
export function rawUrl(cardId: string, withToken: boolean, version?: number) {
  const pid = encodeURIComponent(getStore().project?.id ?? "");
  const q = new URLSearchParams();
  if (withToken && token) q.set("token", token);
  if (version) q.set("v", String(version));
  const qs = q.toString();
  return `/api/projects/${pid}/cards/${encodeURIComponent(cardId)}/raw${qs ? `?${qs}` : ""}`;
}

function TextView({ url }: { url: string }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    apiFetch(url).then(async (r) => {
      if (!live) return;
      if (!r.ok) setError((await r.json().catch(() => null))?.detail ?? `error ${r.status}`);
      else setText(await r.text());
    }).catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [url]);
  if (error) return <div className="pv-wait pv-err">{t("bloques.vista.no_se_puede", { error })}</div>;
  if (text === null) return <div className="pv-wait">{t("bloques.vista.cargando")}</div>;
  return <pre className="pv-text">{text}</pre>;
}

type Props = { id: string; name: string; onClose: () => void };

export function Preview({ id, name, onClose }: Props) {
  const { sources } = useStore();
  const view = sources[id];
  const type = view?.type ?? "archivo";
  const kind = previewKind(type);

  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [onClose]);

  const version = view?.mtime_ns ? Math.round(view.mtime_ns / 1e6) : undefined;
  let body: JSX.Element;
  if (view && !view.ok) {
    body = <div className="pv-wait pv-err">{t("bloques.vista.no_se_puede", { error: view.reason ?? t("bloques.vista.no_esta") })}</div>;
  } else if (kind === "pdf") {
    body = <iframe className="pv-frame" title={name} src={rawUrl(id, true, version)} />;
  } else if (kind === "html") {
    body = <iframe className="pv-frame pv-white" title={name} sandbox="" src={rawUrl(id, true, version)} />;
  } else if (kind === "image") {
    body = <div className="pv-img"><img src={rawUrl(id, true, version)} alt={name} /></div>;
  } else if (kind === "text") {
    body = (view?.size ?? 0) > TEXT_PREVIEW_MAX
      ? <div className="pv-wait">{t("bloques.vista.muy_grande", { size: fmtSize(TEXT_PREVIEW_MAX) })}</div>
      : <TextView url={rawUrl(id, false, version)} />;
  } else if (kind === "step") {
    body = (
      <Suspense fallback={<div className="pv-wait">{t("bloques.vista.cargando_visor")}</div>}>
        <StepViewer rawUrl={rawUrl(id, false)} hash={view?.hash ?? null} />
      </Suspense>
    );
  } else {
    body = <div className="pv-wait">{t("bloques.vista.no_previsualiza")}</div>;
  }

  return (
    <div className="fv-back" role="presentation" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`fv-win pv-win pv-kind-${kind ?? "none"}`} role="dialog" aria-modal="true" aria-label={t("bloques.vista.vista_previa_de", { name })}>
        <div className="fv-head">
          <div className="fv-crumbs">
            <FileIcon type={type} size="sm" />
            <strong title={name}>{name}</strong>
            {view?.ok && <span>{fmtSize(view.size)}</span>}
          </div>
          <span className="fv-sp" />
          <span className="pv-open">
            <button type="button" className="ubtn" onClick={() => void openCard(id)}>{t("bloques.salidas.abrir")}</button>
            {OPEN_WITH && <button type="button" className="ubtn more" title={t("bloques.archivos.abrir_con_titulo")}
                                  aria-label={t("bloques.archivos.abrir_con")} onClick={() => void openCard(id, true)}>▾</button>}
          </span>
          <button type="button" className="ubtn" onClick={onClose} aria-label={t("bloques.vista.cerrar")}>✕</button>
        </div>
        <div className="pv-body">{body}</div>
      </div>
    </div>
  );
}
