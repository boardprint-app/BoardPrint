// Pestaña «Versiones» del panel derecho (plan §3, D76, diseño 3B): guardar una versión con
// nombre, la lista con miniatura, nombre y fecha, elegir dos para comparar y, con el clic
// derecho, restaurar (antes se guarda sola la actual), comparar con ahora, renombrar o mandar
// a la papelera. *Comparar* enseña aquí la lista de cambios; las marcas van en la pizarra.
import { useCallback, useEffect, useState, type MouseEvent } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { apiFetch, token } from "./auth";
import { setStore, useStore } from "./store";
import { CHANGE_MARK, changeLabel, shortDate, toggleSelection, type Change, type VersionInfo } from "./versions";
import { t } from "./i18n";

type Props = { projectId: string; api: ExcalidrawImperativeAPI | null; beforeSave: () => Promise<void> };

async function call(path: string, method = "GET", body?: unknown) {
  const r = await apiFetch(path, {
    method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail ?? t("agente.versiones.error", { status: r.status }));
  return data;
}

function thumbUrl(pid: string, v: VersionInfo) {
  const q = new URLSearchParams({ v: v.id });
  if (token) q.set("token", token);
  return `/api/projects/${encodeURIComponent(pid)}/versions/${encodeURIComponent(v.id)}/thumbnail?${q}`;
}

export function VersionsTab({ projectId, api, beforeSave }: Props) {
  const { versionsTick, compare, types } = useStore();
  const base = `/api/projects/${encodeURIComponent(projectId)}`;
  const [list, setList] = useState<VersionInfo[]>([]);
  const [sel, setSel] = useState<string[]>([]);
  const [naming, setNaming] = useState<string | null>(null);        // nombre de la nueva
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [menu, setMenu] = useState<{ v: VersionInfo; x: number; y: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    call(`${base}/versions`).then((d) => setList(d.versions)).catch((e) => setError(e.message));
  }, [base]);
  useEffect(load, [load, versionsTick]);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null); setBusy(true);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const save = () => run(async () => {
    await beforeSave();                         // la miniatura, al día
    await call(`${base}/versions`, "POST", { name: naming ?? "" });
    setNaming(null);
    load();
  });
  const restore = (v: VersionInfo) => run(async () => {
    setMenu(null);
    setStore({ compare: null, compareFocus: null });
    await call(`${base}/versions/${encodeURIComponent(v.id)}/restore`, "POST");
    load();
  });
  const rename = () => run(async () => {
    if (!renaming) return;
    await call(`${base}/versions/${encodeURIComponent(renaming.id)}`, "PATCH", { name: renaming.name });
    setRenaming(null);
    load();
  });
  const trash = (v: VersionInfo) => run(async () => {
    setMenu(null);
    await call(`${base}/versions/${encodeURIComponent(v.id)}`, "DELETE");
    setSel((s) => s.filter((x) => x !== v.id));
    load();
  });
  // a → b: de la más antigua a la más nueva (o a la pizarra de ahora).
  const doCompare = (ids: string[]) => run(async () => {
    setMenu(null);
    const pick = ids.map((id) => list.find((v) => v.id === id)!).filter(Boolean)
      .sort((x, y) => x.created.localeCompare(y.created));
    const [a, b] = pick.length === 2 ? pick : [pick[0], null];
    const q = new URLSearchParams({ a: a.id, b: b ? b.id : "now" });
    const d = await call(`${base}/compare?${q}`);
    setStore({ compare: { a: a.id, b: b ? b.id : "now", aName: a.name, bName: b ? b.name : t("agente.versiones.ahora"), changes: d.changes },
               compareFocus: null });
  });

  // Ir a un cambio: lo que sigue en la pizarra se centra y se selecciona; lo quitado, su fantasma.
  const goTo = (c: Change) => {
    if (!api || compare?.b !== "now") return;
    setStore({ compareFocus: c.id });
    const el = api.getSceneElements().find((e) => e.id === c.id);
    if (el) {
      api.scrollToContent(el, { animate: true, duration: 300 });
      api.updateScene({ appState: { selectedElementIds: { [el.id]: true } } });
    } else {
      const st = api.getAppState();
      const z = st.zoom.value, e = c.element;
      api.updateScene({ appState: { scrollX: st.width / 2 / z - (e.x + e.width / 2),
                                    scrollY: st.height / 2 / z - (e.y + e.height / 2) } });
    }
  };

  const onRow = (ev: MouseEvent, v: VersionInfo) => {
    if (ev.type === "contextmenu") {
      ev.preventDefault();
      const box = (ev.currentTarget.closest(".ag-panel") as HTMLElement).getBoundingClientRect();
      setMenu({ v, x: ev.clientX - box.left, y: ev.clientY - box.top });
      return;
    }
    setSel((s) => toggleSelection(s, v.id));
  };

  if (compare) {
    const aName = compare.aName, bName = compare.bName;
    const quote = (nombre: string) => t("agente.versiones.cita", { nombre });
    return (
      <div className="vt">
        <div className="vt-cmp-head">
          <b>{quote(aName)} → {compare.b === "now" ? t("agente.versiones.ahora") : quote(bName)}</b>
          <span>{t(compare.changes.length === 1 ? "agente.versiones.cambios_uno" : "agente.versiones.cambios_varios",
                   { n: compare.changes.length })}</span>
        </div>
        <div className="vt-chg">
          {compare.changes.length === 0 && <div className="vt-empty">{t("agente.versiones.sin_cambios")}</div>}
          {compare.changes.map((c) => (
            <button key={c.id} className={`vt-c vt-${c.change}`} onClick={() => goTo(c)}
                    disabled={compare.b !== "now"}>
              <span className="vt-mark">{CHANGE_MARK[c.change]}</span>
              <span>{changeLabel(c, types)}</span>
            </button>
          ))}
        </div>
        <div className="vt-foot">
          <button className="vt-ok" disabled={busy}
                  onClick={() => restore(list.find((v) => v.id === compare.a)!)}>{t("agente.versiones.restaurar_nombre", { nombre: aName })}</button>
          <button onClick={() => setStore({ compare: null, compareFocus: null })}>{t("agente.versiones.cerrar")}</button>
        </div>
      </div>
    );
  }

  return (
    <div className="vt" onClick={() => setMenu(null)}>
      <div className="vt-new">
        {naming === null ? (
          <button className="vt-save" onClick={() => setNaming(t("agente.versiones.nombre_nueva", {
            // Sin «/» ni «:», que el nombre no admite (storage/names.py): «17-11 18.40».
            fecha: shortDate(new Date().toISOString()).replace(" · ", " ").replace(/\//g, "-").replace(/:/g, ".") }))}>
            {t("agente.versiones.guardar_version")}
          </button>
        ) : (
          <form className="vt-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
            <input autoFocus value={naming} onChange={(e) => setNaming(e.target.value)} aria-label={t("agente.versiones.nombre_aria")}
                   onKeyDown={(e) => e.key === "Escape" && setNaming(null)} onFocus={(e) => e.currentTarget.select()} />
            <button type="submit" className="vt-ok" disabled={busy}>{t("agente.versiones.guardar")}</button>
          </form>
        )}
      </div>
      {error && <div className="vt-error">{error}</div>}
      <div className="vt-list">
        {list.length === 0 && <div className="vt-empty">{t("agente.versiones.vacio")}</div>}
        {list.map((v) => (
          <div key={v.id} className={`vt-row${sel.includes(v.id) ? " on" : ""}${v.auto ? " auto" : ""}`}
               onClick={(e) => onRow(e, v)} onContextMenu={(e) => onRow(e, v)} role="button" tabIndex={0}
               aria-pressed={sel.includes(v.id)}>
            <img className="vt-thumb" src={thumbUrl(projectId, v)} alt=""
                 onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
            {renaming?.id === v.id ? (
              <form className="vt-form" onSubmit={(e) => { e.preventDefault(); rename(); }} onClick={(e) => e.stopPropagation()}>
                <input autoFocus value={renaming.name} aria-label={t("agente.versiones.nuevo_nombre")}
                       onChange={(e) => setRenaming({ id: v.id, name: e.target.value })}
                       onKeyDown={(e) => e.key === "Escape" && setRenaming(null)} />
              </form>
            ) : (
              <span className="vt-meta">
                {v.auto ? <i>{v.name}</i> : <b>{v.name}</b>}
                <span>{shortDate(v.created)}{v.auto ? ` · ${t("agente.versiones.automatica")}` : ""}</span>
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="vt-foot">
        {sel.length === 1 && <button className="vt-ok" onClick={() => doCompare(sel)}>{t("agente.versiones.comparar_ahora")}</button>}
        {sel.length === 2 && <button className="vt-ok" onClick={() => doCompare(sel)}>{t("agente.versiones.comparar")}</button>}
        {sel.length === 0 && <span className="vt-hint">{t("agente.versiones.pista")}</span>}
      </div>
      {menu && (
        <div className="vt-menu" style={{ left: menu.x, top: menu.y }} onClick={(e) => e.stopPropagation()}>
          <button onClick={() => restore(menu.v)}>{t("agente.versiones.restaurar")}</button>
          <button onClick={() => doCompare([menu.v.id])}>{t("agente.versiones.comparar_ahora")}</button>
          <button onClick={() => { setRenaming({ id: menu.v.id, name: menu.v.name }); setMenu(null); }}>{t("agente.versiones.renombrar")}</button>
          <button onClick={() => trash(menu.v)}>{t("agente.versiones.papelera")}</button>
        </div>
      )}
    </div>
  );
}
