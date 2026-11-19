// Miniatura de una imagen de salida (D114: la captura de Construir en Fusion). Se pide con el
// token (apiFetch), se recorta a lo que no es transparente (Fusion la da con mucho margen) y un
// clic la amplía encima de todo. El recorte se hace aquí: desde un script, Fusion no aplica
// de forma fiable el encuadre de la cámara a la captura.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch } from "./auth";
import { t } from "./i18n";
import { alphaBox } from "./outputs";

async function cropped(blob: Blob): Promise<string> {
  const bmp = await createImageBitmap(blob);
  const c = document.createElement("canvas");
  c.width = bmp.width;
  c.height = bmp.height;
  const g = c.getContext("2d", { willReadFrequently: true })!;
  g.drawImage(bmp, 0, 0);
  const box = alphaBox(g.getImageData(0, 0, c.width, c.height).data, c.width, c.height);
  if (!box) return URL.createObjectURL(blob);
  const out = document.createElement("canvas");
  out.width = box.w;
  out.height = box.h;
  out.getContext("2d")!.drawImage(c, box.x, box.y, box.w, box.h, 0, 0, box.w, box.h);
  return out.toDataURL("image/png");
}

type Props = { project: string; block: string; file: string; label: string; stamp: unknown };

export function Thumb({ project, block, file, label, stamp }: Props) {
  const [src, setSrc] = useState<string | null>(null);
  const [big, setBig] = useState(false);

  // `stamp` cambia con cada ejecución: el archivo se llama igual pero es otro.
  useEffect(() => {
    let alive = true;
    (async () => {
      const r = await apiFetch(`/api/projects/${encodeURIComponent(project)}/blocks/${encodeURIComponent(block)}/files/${encodeURIComponent(file)}`);
      if (!r.ok || !alive) return;
      const url = await cropped(await r.blob());
      if (alive) setSrc(url);
    })().catch(() => undefined);
    return () => { alive = false; };
  }, [project, block, file, stamp]);

  if (!src) return null;
  return (
    <>
      <button type="button" className="bo-thumb" onClick={() => setBig(true)} title={t("lienzo.miniatura.ampliar", { label })}
>
        <img src={src} alt={label} draggable={false} />
      </button>
      {big && createPortal(
        <div className="thumb-big" role="dialog" aria-label={label} onClick={() => setBig(false)}>
          <img src={src} alt={label} />
        </div>, document.body)}
    </>
  );
}
