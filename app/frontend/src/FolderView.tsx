// Vista de una carpeta dentro de la app (plan §3, D59, D110, D136, D139, D142), encima de la
// pizarra y con el skin. Aquí se marca qué entra en los bloques: casillas (de tres estados en
// las subcarpetas) o un patrón. Se elige entre mosaico (se entra en las subcarpetas) y lista en
// árbol, y se recuerda la última. Mientras se edita, las casillas las calcula cards.ts con las
// mismas reglas que el backend; *Hecho* lo escribe en la tarjeta (`customData.content`) y el
// backend vuelve a sondear (D147).
import { useEffect, useMemo, useState } from "react";
import { folderContent, revealCard, type FolderContent } from "./cardActions";
import {
  contentOf, EVERYTHING, fmtSize, markTree, nothing, outOfPattern, parsePatterns, summary, toggle, treeOrder,
  type Content, type Entry,
} from "./cards";
import { FileIcon, FolderIcon } from "./FileCard";
import { getLanguage, t } from "./i18n";

const MODE_KEY = "pizarra-folder-view";
const BIG = 500 * 1024 ** 2;          // como files.BIG_FOLDER (D136)
type Mode = "tiles" | "list";

function savedMode(): Mode {
  try { return localStorage.getItem(MODE_KEY) === "tiles" ? "tiles" : "list"; } catch { return "list"; }
}

const leaf = (p: string) => p.slice(p.lastIndexOf("/") + 1);
const parentOf = (p: string) => (p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "");
const typeOf = (p: string) => {
  const m = /\.([a-z0-9]+)$/i.exec(p);
  const ext = m ? m[1].toLowerCase() : "";
  return ext ? `archivo.${ext === "stp" ? "step" : ext}` : "archivo";
};
const fmtDate = (s: number) => (s ? new Date(s * 1000).toLocaleDateString(getLanguage() === "en" ? "en-US" : "es-ES", { day: "numeric", month: "short", year: "numeric" }) : "");

function Check({ state, disabled, onClick, label }: { state: Entry["marked"]; disabled?: boolean; onClick: () => void; label: string }) {
  const on = state === true || state === "all";
  const mid = state === "some";
  return (
    <button type="button" role="checkbox" aria-checked={mid ? "mixed" : on} aria-label={label}
            className={`cb${on ? " on" : ""}${mid ? " mid" : ""}`} disabled={disabled}
            title={disabled ? t("bloques.carpeta.fuera_patron") : undefined} onClick={onClick} />
  );
}

type Props = {
  id: string;
  name: string;
  content: unknown;
  onSave: (content: Content) => void;
  onClose: () => void;
};

export function FolderView({ id, name, content, onSave, onClose }: Props) {
  const [data, setData] = useState<FolderContent | null>(null);
  const [draft, setDraft] = useState<Content>(() => contentOf(content));
  const [patternText, setPatternText] = useState(() => contentOf(content).patterns.join(" "));
  const [mode, setMode] = useState<Mode>(savedMode);
  const [here, setHere] = useState("");                         // subcarpeta abierta en mosaico
  const [closed, setClosed] = useState<Set<string>>(new Set());  // subcarpetas plegadas en la lista

  useEffect(() => { void folderContent(id).then(setData); }, [id]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, [onClose]);

  const pickMode = (m: Mode) => {
    setMode(m);
    try { localStorage.setItem(MODE_KEY, m); } catch { /* sin almacenamiento: no se recuerda */ }
  };

  const entries = useMemo(() => (data ? markTree(treeOrder(data.entries), draft) : []), [data, draft]);
  const sum = useMemo(() => summary(entries, draft), [entries, draft]);
  const flip = (path: string) => setDraft((c) => toggle(entries, c, path));
  const setPatterns = (text: string) => {
    setPatternText(text);
    setDraft((c) => ({ ...c, patterns: parsePatterns(text) }));
  };

  // Lista en árbol: lo de dentro de una subcarpeta plegada no se enseña.
  const visible = entries.filter((e) => {
    for (let p = parentOf(e.path); p; p = parentOf(p)) if (closed.has(p)) return false;
    return true;
  });
  const crumbs = here ? here.split("/") : [];

  const row = (e: Entry) => {
    const depth = e.path.split("/").length - 1;
    const dis = e.kind === "file" && outOfPattern(e.path, draft);
    const off = e.marked === false || e.marked === "none";
    return (
      <div key={e.path} className={`fv-row${off ? " off" : ""}`} role="row">
        <Check state={e.marked} disabled={dis} onClick={() => flip(e.path)} label={t("bloques.carpeta.entra", { name: leaf(e.path) })} />
        <span className="fv-nm" style={{ paddingLeft: depth * 22 }}>
          {e.kind === "dir" ? (
            <button type="button" className="fv-tw" aria-expanded={!closed.has(e.path)}
                    aria-label={closed.has(e.path) ? t("bloques.carpeta.desplegar") : t("bloques.carpeta.plegar")}
                    onClick={() => setClosed((s) => { const n = new Set(s); if (n.has(e.path)) n.delete(e.path); else n.add(e.path); return n; })}>
              {closed.has(e.path) ? "▸" : "▾"}
            </button>
          ) : <span className="fv-tw" />}
          {e.kind === "dir" ? <FolderIcon small /> : <FileIcon type={typeOf(e.path)} size="sm" />}
          <span title={e.path}>{leaf(e.path)}</span>
        </span>
        <span className="fv-num">{fmtSize(e.size)}</span>
        <span className="fv-num">{fmtDate(e.mtime ?? 0)}</span>
      </div>
    );
  };

  const tile = (e: Entry) => {
    const dis = e.kind === "file" && outOfPattern(e.path, draft);
    const off = e.marked === false || e.marked === "none";
    return (
      <div key={e.path} className={`fv-tile${off ? " off" : ""}`}>
        <Check state={e.marked} disabled={dis} onClick={() => flip(e.path)} label={t("bloques.carpeta.entra", { name: leaf(e.path) })} />
        {e.kind === "dir" ? (
          <button type="button" className="fv-enter" onClick={() => setHere(e.path)} title={t("bloques.carpeta.abrir", { name: leaf(e.path) })}>
            <span className="fv-bigfolder" aria-hidden="true" />
            <span className="fv-tname">{leaf(e.path)}</span>
          </button>
        ) : (
          <>
            <FileIcon type={typeOf(e.path)} size="big" />
            <span className="fv-tname" title={e.path}>{leaf(e.path)}</span>
          </>
        )}
      </div>
    );
  };

  return (
    <div className="fv-back" role="presentation" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="fv-win" role="dialog" aria-modal="true" aria-label={t("bloques.carpeta.carpeta", { name })}>
        <div className="fv-head">
          <div className="fv-crumbs">
            <FolderIcon />
            {mode === "tiles" && here
              ? <button type="button" className="fv-crumb" onClick={() => setHere("")}>{name}</button>
              : <strong>{name}</strong>}
            {mode === "tiles" && crumbs.map((c, i) => (
              <span key={i} className="fv-crumbpart">
                <span aria-hidden="true">›</span>
                {i === crumbs.length - 1
                  ? <strong>{c}</strong>
                  : <button type="button" className="fv-crumb" onClick={() => setHere(crumbs.slice(0, i + 1).join("/"))}>{c}</button>}
              </span>
            ))}
          </div>
          <span className="fv-seg" role="group" aria-label={t("bloques.carpeta.vista")}>
            <button type="button" aria-pressed={mode === "tiles"} onClick={() => pickMode("tiles")}>{t("bloques.carpeta.mosaico")}</button>
            <button type="button" aria-pressed={mode === "list"} onClick={() => pickMode("list")}>{t("bloques.carpeta.lista")}</button>
          </span>
          <span className="fv-sp" />
          <label className="fv-pat">{t("bloques.carpeta.patron")}
            <input value={patternText} placeholder="*.pdf" spellCheck={false} onChange={(e) => setPatterns(e.target.value)} />
          </label>
          <button type="button" className="ubtn" onClick={() => { setDraft(EVERYTHING); setPatternText(""); }}>{t("bloques.carpeta.todo")}</button>
          <button type="button" className="ubtn" onClick={() => setDraft((c) => nothing(entries, c))}>{t("bloques.carpeta.nada")}</button>
        </div>
        <div className={`fv-body fv-mode-${mode}`}>
          {!data && <div className="fv-empty">{t("bloques.carpeta.leyendo")}</div>}
          {data && !entries.length && <div className="fv-empty">{t("bloques.carpeta.vacia")}</div>}
          {data && entries.length > 0 && mode === "list" && (
            <div className="fv-list" role="table">
              <div className="fv-row hd" role="row"><span /><span>{t("bloques.carpeta.nombre")}</span><span className="fv-num">{t("bloques.carpeta.tamano")}</span><span className="fv-num">{t("bloques.carpeta.modificado")}</span></div>
              {visible.map(row)}
            </div>
          )}
          {data && entries.length > 0 && mode === "tiles" && (
            <div className="fv-tiles">{entries.filter((e) => parentOf(e.path) === here).map(tile)}</div>
          )}
          {data?.cut && <div className="fv-empty">{t("bloques.carpeta.cortada", { n: 5000 })}</div>}
        </div>
        <div className="fv-foot">
          <span className="fv-sum">
            {t("bloques.carpeta.entran", { marked: sum.marked, total: sum.total })} · <b>{fmtSize(sum.size)}</b>
            {draft.patterns.length > 0 && <> · {t("bloques.carpeta.patron_min")} <code>{draft.patterns.join(" ")}</code></>}
            {sum.size > BIG && <span className="fv-big"> · {t("bloques.carpeta.grande")}</span>}
          </span>
          <span className="fv-sp" />
          <button type="button" className="ubtn" onClick={() => void revealCard(id)}>{t("bloques.carpeta.explorador")}</button>
          <button type="button" className="ubtn" onClick={onClose}>{t("bloques.tarjeta.cancelar")}</button>
          <button type="button" className="ubtn main" onClick={() => { onSave(draft); onClose(); }}>{t("bloques.carpeta.hecho")}</button>
        </div>
      </div>
    </div>
  );
}
