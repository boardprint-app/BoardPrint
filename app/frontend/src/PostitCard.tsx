// Tarjeta de un post-it (plan §3, D71), pintada dentro de su elemento `embeddable`. El papel,
// la cinta y los colores salen del skin (skins.css). La tarjeta deja pasar el ratón al lienzo
// (se selecciona y se arrastra como cualquier elemento); solo el cuadro de texto en edición y,
// con el post-it seleccionado, sus controles en el papel (D80, 1B) lo reciben: la etiqueta del
// tipo (pasa al siguiente), Aceptar, Descartar y Reabrir. Se edita con doble clic (lo detecta
// App, que sabe qué post-it hay debajo). El filtro (4C) la oculta sin tocar la escena. Una
// imagen pegada encima del post-it (D140) va encima del texto, con su proporción; la animación
// del agente (D143, D175), también, y solo montada mientras el post-it está a la vista.
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { filteredOut, KIND_LABEL, nextKind, postitView, type PostitData, type PostitKind, type PostitPatch,
         type PostitState } from "./postit";
import { imageUrl } from "./cardActions";
import { t } from "./i18n";
import { proposalFor, wordDiff } from "./proposal";
import { ProposalTab } from "./ProposalTab";
import { PostitAnimation } from "./PostitAnimation";
import { setStore, useStore } from "./store";

type Props = {
  id: string;
  data: PostitData;
  height: number;                          // alto del elemento en la escena
  selected: boolean;
  inView: boolean;                         // a la vista en el lienzo (la animación, D175)
  anchorLost: boolean;                     // anclado a algo que se ha borrado (D74)
  onAnchorStart: (id: string, ev: PointerEvent) => void;   // arrastrar la cinta para anclar
  onPatch: (id: string, patch: PostitPatch) => void;
  onHeight: (id: string, height: number) => void;
};

export const POSTIT_MIN_HEIGHT = 120;

export function PostitCard({ id, data, height, selected, inView, anchorLost, onAnchorStart, onPatch, onHeight }: Props) {
  const { blocks, types, editingPostit, postitFilter, proposals } = useStore();
  const prop = proposalFor(proposals, id);
  const v = postitView(data, blocks, types);
  const editing = editingPostit === id;
  const [draft, setDraft] = useState(v.text);
  const inner = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (editing) setDraft(v.text); }, [editing]); // eslint-disable-line react-hooks/exhaustive-deps

  // El alto sigue al texto (nunca por debajo del mínimo): se mide el contenido sin escalar.
  useLayoutEffect(() => {
    const box = inner.current;
    if (!box) return;
    const fit = () => {
      const need = Math.max(POSTIT_MIN_HEIGHT, Math.ceil(box.offsetHeight));
      if (Math.abs(need - height) >= 1) onHeight(id, need);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(box);
    return () => ro.disconnect();
  }, [id, height, onHeight]);

  useEffect(() => {
    if (!editing || !area.current) return;
    area.current.focus();
    area.current.setSelectionRange(area.current.value.length, area.current.value.length);
  }, [editing]);

  const close = (save: boolean) => {
    if (save && draft !== v.text) onPatch(id, { text: draft });
    setStore({ editingPostit: null });
  };

  // Un control que desaparece al pulsarlo (Aceptar en un aceptado…) dejaría el foco en <body>,
  // y los atajos de Excalidraw (Ctrl+Z, Supr) solo funcionan con el foco dentro de la pizarra.
  const act = (ev: MouseEvent<HTMLButtonElement>, patch: Parameters<Props["onPatch"]>[1]) => {
    const board = ev.currentTarget.closest<HTMLElement>(".excalidraw");
    onPatch(id, patch);
    board?.focus();
  };
  const setState = (ev: MouseEvent<HTMLButtonElement>, state: PostitState) => act(ev, { state });
  const cls = ["postit", `pk-${v.kind}`, `ps-${v.state}`, v.unverified ? "unverified" : "",
               selected ? "selected" : "", filteredOut(postitFilter, data) ? "filtered" : "",
               prop ? "prop" : "", prop?.change.delete ? "prop-delete" : ""].join(" ");
  const newKind = prop?.change.postitKind as PostitKind | undefined;
  return (
    <div className={cls}>
      <div className="postit-inner" ref={inner}>
        {/* La cinta se arrastra hasta otro elemento para anclar el post-it, o al vacío para
            desanclarlo (D74, D80). Solo con el post-it seleccionado. */}
        <i className="postit-tape" aria-hidden="true"
           title={selected ? t("lienzo.postit.cinta") : undefined}
           onPointerDown={selected ? (ev) => { ev.preventDefault(); ev.stopPropagation(); onAnchorStart(id, ev.nativeEvent); } : undefined} />
        <div className="postit-tag">
          {selected ? (
            <button className="postit-kind" onClick={(ev) => act(ev, { postitKind: nextKind(v.kind) })}
                    title={t("lienzo.postit.cambiar_tipo")} aria-label={t("lienzo.postit.tipo_aria", { tipo: KIND_LABEL[v.kind] })}>
              {KIND_LABEL[v.kind]} ▾
            </button>
          ) : KIND_LABEL[v.kind]}
          {newKind && newKind !== v.kind && <> <span className="new">{KIND_LABEL[newKind]}</span></>}
          {v.unverified && ` · ${t("lienzo.postit.sin_verificar")}`}
          {v.author && <span className="postit-who"> · {v.author}</span>}
          {anchorLost && <span className="postit-who"> · {t("lienzo.anclaje.perdido")}</span>}
        </div>
        {data.image?.file && (
          // El alto lo reserva la proporción antes de cargar: el post-it no salta al llegar.
          <div className="postit-pic">
            <img src={imageUrl(data.image.file)} alt="" draggable={false}
                 style={{ aspectRatio: `${data.image.width || 4} / ${data.image.height || 3}` }} />
          </div>
        )}
        {data.animation?.file && <PostitAnimation anim={data.animation} kind={v.kind} visible={inView} />}
        {editing ? (
          <textarea
            ref={area}
            className="postit-edit"
            value={draft}
            rows={Math.max(2, draft.split("\n").length)}
            aria-label={t("lienzo.postit.texto_aria", { tipo: KIND_LABEL[v.kind] })}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => close(true)}
            onKeyDown={(e) => {
              e.stopPropagation();                  // que Excalidraw no lo tome como atajo
              if (e.key === "Escape") close(false);
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) close(true);
            }}
            onPointerDown={(e) => e.stopPropagation()}
          />
        ) : prop?.change.text !== undefined ? (
          // Propuesta (2A): lo quitado tachado y lo nuevo resaltado, dentro del papel.
          <p className="postit-text">
            {wordDiff(prop.current.text ?? "", prop.change.text).map((s, i) => (
              <span key={i} className={s.kind === "same" ? undefined : s.kind === "del" ? "old" : "new"}>{s.text}</span>
            ))}
          </p>
        ) : (
          <p className={v.text ? "postit-text" : "postit-text empty"}>
            {v.text || t("lienzo.postit.vacio")}
          </p>
        )}
        {v.sources.length > 0 && <p className="postit-src">{t("lienzo.postit.fuente", { fuentes: v.sources.join("; ") })}</p>}
        {/* Siempre ocupa su sitio (oculta sin seleccionar): el alto no cambia al seleccionar. */}
        <div className="postit-ctl" aria-hidden={!selected}>
          {v.state !== "aceptado" && (
            <button className="pc-ok" tabIndex={selected ? 0 : -1} onClick={(ev) => setState(ev, "aceptado")}>{t("lienzo.postit.aceptar")}</button>
          )}
          {v.state !== "descartado" && (
            <button className="pc-no" tabIndex={selected ? 0 : -1} onClick={(ev) => setState(ev, "descartado")}>{t("lienzo.postit.descartar")}</button>
          )}
          {v.state !== "abierto" && (
            <button className="pc-re" tabIndex={selected ? 0 : -1} onClick={(ev) => setState(ev, "abierto")}>{t("lienzo.postit.reabrir")}</button>
          )}
          {data.image?.file && (
            <button className="pc-re" tabIndex={selected ? 0 : -1} onClick={(ev) => act(ev, { image: null })}>{t("lienzo.postit.quitar_imagen")}</button>
          )}
        </div>
      </div>
      {prop && <ProposalTab p={prop} />}
      {v.state !== "abierto" && (
        <span className="postit-stamp">
          {v.state === "aceptado" ? t("lienzo.postit.sello_aceptado") : t("lienzo.postit.sello_descartado")}
        </span>

      )}
    </div>
  );
}
