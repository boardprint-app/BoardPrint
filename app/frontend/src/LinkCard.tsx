// Enlace pegado (plan §3, D137; artifact «Archivos FF 4.8», 5B): una píldora subrayada con la
// inicial del dominio, el título y el dominio. Seleccionado, saca a su derecha la barra (como
// la etiqueta de un archivo, R39) con *Abrir en el navegador*, cambiar el título y copiar el
// enlace; el doble clic también cambia el título (lo detecta App). No es entrada de bloques, el
// agente no lo lee y la app no descarga nada: abrirlo lo hace el backend con la URL de la escena.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { openLink } from "./cardActions";
import { t } from "./i18n";
import { letterColor, linkDomain, linkInitial } from "./paste";
import { setStore, useStore } from "./store";

type Props = {
  id: string;
  data: { url?: string; title?: string };
  selected: boolean;
  height: number;
  onHeight: (id: string, height: number) => void;
  onTitle: (id: string, title: string) => void;
};

export function LinkCard({ id, data, selected, height, onHeight, onTitle }: Props) {
  const { editingLink } = useStore();
  const editing = editingLink === id;
  const url = String(data.url ?? "");
  const domain = linkDomain(url);
  const title = String(data.title ?? "") || domain;
  const [draft, setDraft] = useState(title);
  const inner = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);

  useLayoutEffect(() => {
    const box = inner.current;
    if (!box) return;
    const need = Math.ceil(box.offsetHeight);
    if (Math.abs(need - height) >= 1) onHeight(id, need);
  }, [id, height, onHeight]);

  useEffect(() => {
    if (!editing) return;
    setDraft(title);
    requestAnimationFrame(() => { field.current?.focus(); field.current?.select(); });
  }, [editing]); // eslint-disable-line react-hooks/exhaustive-deps

  const close = (save: boolean) => {
    const next = draft.trim();
    if (save && next && next !== title) onTitle(id, next);
    setStore({ editingLink: null });
    (document.querySelector(".excalidraw") as HTMLElement | null)?.focus();
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      setStore({ lastError: t("lienzo.portapapeles.error") });
    }
  };

  return (
    <div className={`linkcard${selected ? " sel" : ""}`} data-kind="link">
      {selected && !editing && (
        <div className="fc-bar">
          <button type="button" onClick={() => void openLink(id)}>{t("lienzo.enlace.abrir")}</button>
          <button type="button" onClick={() => setStore({ editingLink: id })}>{t("lienzo.enlace.cambiar_titulo")}</button>
          <button type="button" onClick={() => void copy()}>{t("lienzo.enlace.copiar")}</button>
        </div>
      )}
      <div className="lk-row" ref={inner} title={url}>
        <span className="lk-letter" style={{ background: letterColor(domain) }} aria-hidden="true">{linkInitial(domain)}</span>
        {editing ? (
          <input ref={field} className="lk-edit" value={draft} aria-label={t("lienzo.enlace.titulo_campo")}

                 onChange={(e) => setDraft(e.target.value)}
                 onBlur={() => close(true)}
                 onPointerDown={(e) => e.stopPropagation()}
                 onKeyDown={(e) => {
                   e.stopPropagation();                // que Excalidraw no lo tome como atajo
                   if (e.key === "Enter") close(true);
                   if (e.key === "Escape") close(false);
                 }} />
        ) : (
          <span className="lk-title">{title}</span>
        )}
        <span className="lk-domain">{domain}</span>
      </div>
    </div>
  );
}
