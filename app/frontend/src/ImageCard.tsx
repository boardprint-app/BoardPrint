// Foto suelta pegada en la pizarra (plan §3, D84, D140; artifact «Archivos FF 4.8», 4C): la
// imagen sin marco, con dos tiras de cinta en las esquinas y el autor en tiza debajo. Se coge
// y se estira como cualquier elemento (el alto lo fija App con `keepRatio`: nunca se deforma);
// seleccionada, la cinta de arriba se arrastra para anclarla, como la de un post-it (D74).
import type { CSSProperties } from "react";
import { t } from "./i18n";
import { AUTHOR_LABEL } from "./postit";
import { imageUrl } from "./cardActions";
import { IMAGE_CAPTION, type ImageRef } from "./paste";

type Props = {
  id: string;
  data: { image?: ImageRef; author?: string; created?: string };
  selected: boolean;
  anchorLost: boolean;
  onAnchorStart: (id: string, ev: PointerEvent) => void;
};

const shortDate = (iso?: string) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? `${d.getDate()} ${t("lienzo.fecha.meses").split(",")[d.getMonth()]}` : "";
};

export function ImageCard({ id, data, selected, anchorLost, onAnchorStart }: Props) {
  const who = !data.author || data.author === "user" ? t("lienzo.autor.tu") : AUTHOR_LABEL[data.author] ?? data.author;
  const meta = [who, shortDate(data.created), anchorLost ? t("lienzo.anclaje.perdido") : ""].filter(Boolean).join(" · ");
  return (
    <div className={`photo${selected ? " sel" : ""}`} data-kind="image"
         style={{ "--photo-cap": `${IMAGE_CAPTION}px` } as CSSProperties}>
      <div className="photo-pic">
        {data.image?.file
          ? <img src={imageUrl(data.image.file)} alt="" draggable={false} />
          : <span className="photo-none">{t("lienzo.foto.sin_imagen")}</span>}
      </div>
      <i className="photo-tape l" aria-hidden="true"
         title={selected ? t("lienzo.foto.cinta") : undefined}

         onPointerDown={selected ? (ev) => { ev.preventDefault(); ev.stopPropagation(); onAnchorStart(id, ev.nativeEvent); } : undefined} />
      <i className="photo-tape r" aria-hidden="true" />
      <div className="photo-who">{meta}</div>
    </div>
  );
}
