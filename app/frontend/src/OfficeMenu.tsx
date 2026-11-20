// Office con el agente en la interfaz (plan D176, FF 4.6 paso 7). Los textos de los encargos y
// lo puro, en office.ts.
//
// - En el menú de una tarjeta de archivo (`OfficeItems`, dentro de CardMenu): *Leer con el
//   agente* (PDF, Word, Excel, PowerPoint), con dos destinos: a post-its, o a la entrada de un
//   bloque (los conectados a la tarjeta primero, o cualquiera de la pizarra); y *Editar con el
//   agente* (Word, Excel, PowerPoint), con una caja para decir qué cambiar. Cada uno abre un
//   hilo anclado a la tarjeta (y al bloque) con el encargo ya escrito (D165).
// - *Nuevo archivo* en la barra (`NewFileMenu`): Word, Excel o PowerPoint y lo que se pide. Con
//   algo seleccionado, el hilo se ancla a lo seleccionado (el contenido sale de ahí); sin nada,
//   un hilo no tiene a qué anclarse (D57) y el encargo va al chat del agente.
// - La propuesta de archivo (`FileProposal`, en ProposalOverlay): el diff de `editar_archivo`
//   por párrafo, celda o diapositiva, lo de antes tachado y lo nuevo resaltado.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { send } from "./socket";
import { useStore, getStore } from "./store";
import { boardView, measureChrome, screenBoxes } from "./threadActions";
import { defaultWindow } from "./threads";
import { wordDiff, type Proposal } from "./proposal";
import { blockChoices, briefTitle, canEdit, canRead, connectedBlocks, editBrief, EDITABLE, fileName,
         newFileBrief, readToBlock, readToPostits, type OfficeType } from "./office";
import { t } from "./i18n";
import "./office.css";

type Api = ExcalidrawImperativeAPI;

const Ico = ({ d }: { d: ReactNode }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);
const READ = <path d="M3 5h7a3 3 0 013 3v11a2 2 0 00-2-2H3zM21 5h-7a3 3 0 00-3 3v11a2 2 0 012-2h8z" />;
const EDIT = <path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4" />;
const NEW = <><path d="M14 3H6v18h12V7z" /><path d="M14 3v4h4M12 11v6M9 14h6" /></>;

/** Abre un hilo anclado a `anchors` con el encargo `text`, en ventana junto al primero; sin
 *  anclas, el encargo va al chat del agente. */
export function briefAgent(api: Api | null, anchors: string[], title: string, text: string) {
  const ids = [...new Set(anchors)].slice(0, 20);
  if (!ids.length || !api) {
    send({ type: "agent_ask", text });
    return;
  }
  const boxes = screenBoxes(api, ids);
  const first = ids.find((a) => boxes.has(a));
  const rect = defaultWindow(first ? boxes.get(first)! : null, boardView(), undefined, measureChrome());
  send({ type: "thread_create", anchors: ids, title, text, layout: { size: "window", ...rect } });
}

/** ¿Está el agente con otro mensaje? Entonces no se le puede encargar nada todavía. */
const useBusy = () => {
  const { agentBusy, threadBusy } = useStore();
  return agentBusy || threadBusy !== null;
};

type ItemsProps = { id: string; type: string; name: string; exists: boolean; api: Api | null; onClose: () => void };

/** *Leer con el agente* y *Editar con el agente* en el menú de una tarjeta de archivo. */
export function OfficeItems({ id, type, name, exists, api, onClose }: ItemsProps) {
  const { blocks, types } = useStore();
  const busy = useBusy();
  const [mode, setMode] = useState<"read" | "edit" | null>(null);
  const [what, setWhat] = useState("");
  const card = { id, name };
  const choices = useMemo(() => {
    if (mode !== "read") return [];
    const all = Object.entries(blocks).map(([bid, b]) => ({ id: bid, title: types[b.type]?.title ?? b.type }));
    return blockChoices(all, connectedBlocks(api?.getSceneElements() ?? [], id, blocks));
  }, [mode, blocks, types, api, id]);
  if (!canRead(type)) return null;
  const go = (anchors: string[], title: string, text: string) => { onClose(); briefAgent(api, anchors, title, text); };
  const sendEdit = () => { if (what.trim() && !busy) go([id], briefTitle.edit(card), editBrief(card, what)); };
  const off = !exists || busy;
  return (
    <>
      <button type="button" role="menuitem" className={`it${mode === "read" ? " om-open" : ""}`} disabled={off}
              aria-expanded={mode === "read"} onClick={() => setMode(mode === "read" ? null : "read")}>
        <Ico d={READ} />{t("agente.office.leer")}<span className="om-caret" aria-hidden="true">▸</span>
      </button>
      {mode === "read" && (
        <div className="om-sub" role="group" aria-label={t("agente.office.leer")}>
          <button type="button" role="menuitem" className="it two" onClick={() => go([id], briefTitle.read(card), readToPostits(card))}>
            <span><b>{t("agente.office.a_postits")}</b><small>{t("agente.office.a_postits_nota")}</small></span>
          </button>
          <div className="om-h">{t("agente.office.a_bloque")}</div>
          {choices.length ? choices.map((b) => (
            <button key={b.id} type="button" role="menuitem" className="it om-block"
                    onClick={() => go([id, b.id], briefTitle.read(card), readToBlock(card, b))}>
              <span className="om-name">{b.title}</span>{b.connected && <span className="om-tag">{t("agente.office.conectado")}</span>}
            </button>
          )) : <div className="om-none">{t("agente.office.sin_bloques")}</div>}
        </div>
      )}
      {canEdit(type) && (
        <button type="button" role="menuitem" className={`it${mode === "edit" ? " om-open" : ""}`} disabled={off}
                aria-expanded={mode === "edit"} onClick={() => setMode(mode === "edit" ? null : "edit")}>
          <Ico d={EDIT} />{t("agente.office.editar")}
        </button>
      )}
      {mode === "edit" && (
        <div className="om-edit">
          <textarea autoFocus rows={3} value={what} aria-label={t("agente.office.que_cambiar")}
                    placeholder={t("agente.office.que_cambiar_placeholder")}
                    onChange={(e) => setWhat(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendEdit(); }} />
          <div className="om-row">
            <small>{t("agente.office.copia_nota")}</small>
            <button type="button" className="om-go" disabled={!what.trim() || busy} onClick={sendEdit}>{t("agente.office.pedir")}</button>
          </div>
        </div>
      )}
      {busy && <div className="hint">{t("agente.office.ocupado")}</div>}
    </>
  );
}

/** *Nuevo archivo* en la barra de la pizarra (D176): Word, Excel o PowerPoint y lo que se pide. */
export function NewFileMenu({ api }: { api: Api | null }) {
  const busy = useBusy();
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<OfficeType>("docx");
  const [what, setWhat] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => {
    if (!open) return;
    // Lo seleccionado al abrirlo: al escribir en la caja, la selección de Excalidraw no cambia.
    setSelected(api ? Object.keys(api.getAppState().selectedElementIds).filter((k) => api.getAppState().selectedElementIds[k]) : []);
    const click = (e: PointerEvent) => { if (!(e.target as HTMLElement)?.closest?.(".tb-new")) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", click, true);
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("pointerdown", click, true); window.removeEventListener("keydown", key, true); };
  }, [open, api]);
  const submit = () => {
    if (!what.trim() || getStore().agentBusy || getStore().threadBusy !== null) return;
    setOpen(false);
    briefAgent(api, selected, briefTitle.create(type), newFileBrief(type, what, selected.length > 0));
    setWhat("");
  };
  return (
    <span className="tb-new">
      <button type="button" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)}
              title={t("agente.office.nuevo_titulo")} aria-label={t("agente.office.nuevo")}>
        <Ico d={NEW} /><span className="tb-label">{t("agente.office.nuevo")}</span>
      </button>
      {open && (
        <div className="card-menu tb-new-menu" role="dialog" aria-label={t("agente.office.nuevo")}>
          <div className="tb-file-why">
            {t("agente.office.nuevo_por_que")}{" "}
            {selected.length > 0 ? t("agente.office.parte_seleccion", { n: selected.length }) : t("agente.office.selecciona_antes")}
          </div>
          <div className="om-types" role="radiogroup" aria-label={t("agente.office.tipo")}>
            {(Object.keys(EDITABLE) as OfficeType[]).map((ty) => (
              <button key={ty} type="button" role="radio" aria-checked={type === ty}
                      className={type === ty ? "on" : ""} onClick={() => setType(ty)}>{EDITABLE[ty]}</button>
            ))}
          </div>
          <div className="om-edit">
            <textarea autoFocus rows={4} value={what} aria-label={t("agente.office.que_escribir")}
                      placeholder={type === "xlsx" ? t("agente.office.placeholder_xlsx")
                        : type === "pptx" ? t("agente.office.placeholder_pptx")
                        : t("agente.office.placeholder_docx")}
                      onChange={(e) => setWhat(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(); }} />
            <div className="om-row">
              <small>{busy ? t("agente.office.ocupado") : selected.length ? t("agente.office.va_hilo") : t("agente.office.va_chat")}</small>
              <button type="button" className="om-go" disabled={!what.trim() || busy} onClick={submit}>{t("agente.office.pedir")}</button>
            </div>
          </div>
        </div>
      )}
    </span>
  );
}

/** El diff de una propuesta de archivo, dentro de su pestaña: el archivo nuevo y, por cada
 *  párrafo, celda o diapositiva, lo de antes y lo de después. */
export function FileProposal({ p }: { p: Proposal }) {
  const f = p.change.file;
  if (!f) return null;
  const shown = f.diff.slice(0, 30);
  return (
    <div className="ask-list om-diff" aria-label={t("agente.office.diff_aria")}>
      <div className="al-head">
        {t("agente.office.copia_nueva")} <b>{fileName(f.nuevo)}</b> · {t(f.diff.length === 1 ? "agente.versiones.cambios_uno" : "agente.versiones.cambios_varios", { n: f.diff.length })}
      </div>
      <ul>
        {shown.map((d) => (
          <li key={d.where} className="al-changed">
            <span className="al-id">{d.name ? <><b>{d.name}</b> {d.where}</> : d.where}</span>
            <div className="om-text">
              {wordDiff(d.before, d.after).map((s, i) => (
                <span key={i} className={s.kind === "same" ? undefined : s.kind === "del" ? "old" : "new"}>{s.text}</span>
              ))}
              {(d.source || d.formula) && <small className="om-src">{d.formula ? t("agente.office.formula") : `← ${d.source}`}</small>}
            </div>
          </li>
        ))}
      </ul>
      {f.diff.length > shown.length && <div className="al-head">{t("agente.office.mas", { n: f.diff.length - shown.length })}</div>}
      {f.calc?.state === "calculando" && <div className="om-calc">{t("agente.office.calculando")}</div>}
      {f.calc?.state === "sin_valor" && (
        <div className="om-calc bad">{t("agente.office.sin_valor", { names: (f.calc.names ?? []).join(", "), motivo: f.calc.motivo ?? "" })}</div>
      )}
      {f.aviso && <div className="om-note">⚠ {f.aviso}</div>}
      <div className="om-note">{t("agente.office.diff_nota")}</div>
    </div>
  );
}
