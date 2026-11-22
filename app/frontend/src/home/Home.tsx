// Pantalla de inicio: una pizarra (plan D63, propuesta A). Sale la primera vez, cuando el
// último proyecto ya no existe y al volver desde la píldora del proyecto. Lo que hay en el
// workspace lo dice el backend (`/api/workspace`); aquí solo se pinta y se piden cambios.
import { useCallback, useEffect, useState, type DragEvent, type MouseEvent } from "react";
import { apiFetch, token } from "../auth";
import { t } from "../i18n";
import { openSettings } from "../settings";
import { ContextMenu, MoveDialog, NameDialog, TrashDialog, type MenuItem } from "./Dialogs";
import { openLibrary } from "../libraryOpen";
import { NewWorkspaceDialog } from "./NewWorkspaceDialog";
import { countProjects, crumbs, findFolder, folderSummary, moveTargets, search, timeAgo, type TreeNode } from "./tree";
import { WorkspaceMenu } from "./WorkspaceMenu";
import "./home.css";

type Recent = { id: string; name: string; exists: boolean; folder?: string; modified?: number; thumbnail?: boolean };
type WorkspaceView = {
  app: string;
  workspace: { id: string; name: string; path: string };
  tree: TreeNode;
  recent: Recent[];
  problem: string | null;
};
type Dialog =
  | { kind: "new-project" | "new-folder"; parent: string }
  | { kind: "rename" | "move" | "trash"; node: TreeNode };

type Props = { missing: string | null; problem?: string; onOpen: (id: string) => void };

const DRAG_TYPE = "application/x-pizarra-node";

async function call(method: string, path: string, body?: unknown) {
  const r = await apiFetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail ?? t("lienzo.inicio.error_http", { status: r.status }));
  return data;
}

function thumbUrl(id: string, version: number) {
  const q = new URLSearchParams({ v: String(Math.round(version)) });
  if (token) q.set("token", token);
  return `/api/projects/${encodeURIComponent(id)}/thumbnail?${q}`;
}

/** Miniatura de la pizarra; si aún no tiene, un dibujo de pizarra con bloques. */
function Thumb({ id, version, label, has }: { id: string; version: number; label: string; has?: boolean }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [id, version]);
  return (
    <div className="thumb" role="img" aria-label={t("lienzo.inicio.miniatura", { nombre: label })}>
      {failed || !has ? (
        <><i className="b1" /><i className="ar" /><i className="b2" /><i className="pi" /></>
      ) : (
        <img src={thumbUrl(id, version)} alt="" onError={() => setFailed(true)} />
      )}
    </div>
  );
}

// Un texto traducido con `{name}` dentro, con ese hueco en negrita (sin partir la frase en trozos).
function withStrong(text: string, name: string, value: string) {
  const [before, ...after] = text.split(`{${name}}`);
  return <>{before}<strong>{value}</strong>{after.join(`{${name}}`)}</>;
}

const MoreIcon = () => (

  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" />
  </svg>
);

export function Home({ missing, problem, onOpen }: Props) {
  const [data, setData] = useState<WorkspaceView | null>(null);
  const [error, setError] = useState<string | null>(problem ?? null);
  const [missingName, setMissingName] = useState(missing);
  const [folder, setFolder] = useState("");
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; node: TreeNode } | null>(null);
  const [dropOn, setDropOn] = useState<string | null>(null);
  // *Nuevo workspace* (PLAN_WORKSPACES W6), con la carpeta base; y la espera al cambiar (W3)
  const [newWs, setNewWs] = useState<{ base: string | null } | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const body: WorkspaceView = await call("GET", "/api/workspace");
      setData(body);
      if (body.problem) setError(body.problem);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Si la carpeta en la que se estaba desaparece (borrada o movida), se vuelve a la raíz.
  useEffect(() => {
    if (data && !findFolder(data.tree, folder)) setFolder("");
  }, [data, folder]);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    await load();
  };

  const forget = (id: string) => act(() => call("DELETE", `/api/recent/${encodeURIComponent(id)}`));

  const moveNode = (node: TreeNode, dest: string) =>
    node.kind === "project"
      ? call("PATCH", `/api/projects/${encodeURIComponent(node.id!)}`, { dest })
      : call("PATCH", "/api/folders", { path: node.path, dest });

  const openNode = (node: TreeNode) => {
    if (node.kind === "folder") {
      setFolder(node.path);
      setQuery("");
    } else if (node.id) {
      onOpen(node.id);
    } else {
      setError(t("lienzo.inicio.no_abre", { nombre: node.name, motivo: node.error ?? "" }));
    }
  };

  const menuFor = (node: TreeNode): MenuItem[] => [
    { label: t("lienzo.inicio.abrir"), onSelect: () => openNode(node) },
    { label: t("lienzo.inicio.renombrar_menu"), onSelect: () => setDialog({ kind: "rename", node }) },
    { label: t("lienzo.inicio.mover_menu"), onSelect: () => setDialog({ kind: "move", node }) },
    {
      label: t("lienzo.inicio.explorador"),
      onSelect: () => act(() => call("POST", "/api/reveal",
        node.kind === "project" ? { project: node.id } : { folder: node.path })),
    },
    { label: t("lienzo.inicio.papelera_menu"), danger: true, onSelect: () => setDialog({ kind: "trash", node }) },
  ];

  const openMenu = (e: MouseEvent, node: TreeNode) => {
    e.preventDefault();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ x: e.clientX || r.right, y: e.clientY || r.bottom, node });
  };

  // Arrastrar un proyecto o una carpeta a otra carpeta (o a una miga) lo mueve.
  const dragStart = (e: DragEvent, node: TreeNode) => {
    e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(node));
    e.dataTransfer.effectAllowed = "move";
  };
  const dropProps = (path: string) => ({
    onDragOver: (e: DragEvent) => {
      if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
      e.preventDefault();
      setDropOn(path);
    },
    onDragLeave: () => setDropOn((d) => (d === path ? null : d)),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      setDropOn(null);
      const node: TreeNode = JSON.parse(e.dataTransfer.getData(DRAG_TYPE));
      if (node.path !== path) act(() => moveNode(node, path));
    },
  });

  if (!data) {
    return (
      <main className="home">
        <h1>{error ? t("lienzo.inicio.no_workspace") : t("lienzo.inicio.abriendo")}</h1>
        {/* sin workspace (su carpeta falta), la lista sirve para abrir o crear otro (W6) */}
        {error && (
          <div className="home-head">
            <WorkspaceMenu label={t("workspaces.elegir")} disabled={switching !== null} onError={setError}
                           onBusy={setSwitching} onNew={(base) => setNewWs({ base })} />
          </div>
        )}
        {switching && <div className="notice" role="status"><p>{switching}</p></div>}
        {error && <div className="notice" role="alert"><p>{error}</p></div>}
        {newWs && <NewWorkspaceDialog base={newWs.base} onClose={() => setNewWs(null)} />}
      </main>
    );
  }

  const current = findFolder(data.tree, folder) ?? data.tree;
  const recent = data.recent;
  const last = recent.find((r) => r.exists);
  const others = recent.filter((r) => r !== last).slice(0, 8);
  const results = query.trim() ? search(data.tree, query) : null;
  const shown = results ?? current.children ?? [];
  const empty = !data.tree.children?.length;

  const tile = (node: TreeNode) => (
    <li key={node.path} className={`tile${dropOn === node.path && node.kind === "folder" ? " drop" : ""}`}
        onContextMenu={(e) => openMenu(e, node)}
        {...(node.kind === "folder" ? dropProps(node.path) : {})}>
      <button className="tile-open" draggable onDragStart={(e) => dragStart(e, node)} onClick={() => openNode(node)}
              aria-label={t(node.kind === "folder" ? "lienzo.inicio.carpeta_aria" : "lienzo.inicio.proyecto_aria", { nombre: node.name })}>
        {node.kind === "folder" ? (
          <span className="tile-art folder-art" aria-hidden="true">
            <i className="tab" /><i className="sheet1" /><i className="sheet2" /><i className="front" />
          </span>
        ) : (
          <span className={`tile-art project-art${node.id ? "" : " broken"}`}>
            {node.id ? <Thumb id={node.id} version={node.modified} label={node.name} has={node.thumbnail} /> : <span className="thumb" />}
          </span>
        )}
        <span className="tile-name">{node.name}</span>
        <span className="tile-meta">
          {node.kind === "folder" ? folderSummary(node)
            : node.id ? timeAgo(node.modified) : t("lienzo.inicio.no_se_puede_abrir")}
          {results && node.path.includes("/") ? ` · ${node.path.slice(0, node.path.lastIndexOf("/"))}` : ""}
        </span>
      </button>
      <button className="icon-btn more" aria-label={t("lienzo.inicio.mas_acciones", { nombre: node.name })} onClick={(e) => openMenu(e, node)}>
        <MoreIcon />
      </button>
    </li>
  );

  const d = dialog;
  return (
    <main className="home">
      <header className="home-head">
        <h1>{data.app}</h1>
        <WorkspaceMenu label={t("lienzo.inicio.workspace", { nombre: data.workspace.name })} disabled={switching !== null} onError={setError}
                       onBusy={setSwitching} onNew={(base) => setNewWs({ base })} />
        <label className="home-search">
          <span className="sr-only">{t("lienzo.inicio.buscar")}</span>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
            <circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" />
          </svg>
          <input type="search" placeholder={t("lienzo.inicio.buscar")} value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <button className="btn-outline home-library" onClick={() => openLibrary()}>{t("libreria.boton")}</button>
        <button className="btn-outline home-settings" onClick={() => openSettings()}>{t("lienzo.inicio.ajustes")}</button>
      </header>

      {switching && <div className="notice" role="status"><p>{switching}</p></div>}
      {missingName !== null && (
        <div className="notice" role="status">
          <p>
            {missingName
              ? withStrong(t("lienzo.inicio.no_encuentra_nombre"), "nombre",
                           t("lienzo.inicio.comillas", { nombre: missingName }))
              : t("lienzo.inicio.no_encuentra")}
          </p>
          <button className="btn-outline" style={{ color: "inherit", borderColor: "currentColor" }}
                  onClick={() => setMissingName(null)}>{t("lienzo.inicio.entendido")}</button>
        </div>
      )}
      {error && (
        <div className="notice" role="alert">
          <p>{error}</p>
          <button className="btn-outline" style={{ color: "inherit", borderColor: "currentColor" }}
                  onClick={() => setError(null)}>{t("lienzo.inicio.cerrar")}</button>
        </div>
      )}

      <div className="home-cols">
        <section className="home-col" aria-labelledby="h-seguir">
          <h2 id="h-seguir">{last ? t("lienzo.inicio.seguir") : t("lienzo.inicio.empezar")}</h2>
          {last ? (
            <article className="big-card">
              <span className="tape" aria-hidden="true" />
              <Thumb id={last.id} version={last.modified ?? 0} label={last.name} has={last.thumbnail} />
              <div className="big-card-foot">
                <div>
                  <h3>{last.name}</h3>
                  <p>{[last.folder || data.workspace.name, last.modified ? t("lienzo.inicio.guardado_hace", { cuando: timeAgo(last.modified) }) : ""].filter(Boolean).join(" · ")}</p>
                </div>
                <button className="btn-paper" onClick={() => onOpen(last.id)}>{t("lienzo.inicio.abrir")}</button>
              </div>
            </article>
          ) : (
            <div className="empty">
              <p className="chalk" style={{ fontSize: 22 }}>
                {empty ? t("lienzo.inicio.vacio_workspace") : t("lienzo.inicio.abre_derecha")}
              </p>
              <button className="btn-chalk" onClick={() => setDialog({ kind: "new-project", parent: "" })}>{t("lienzo.inicio.nuevo_proyecto_btn")}</button>
            </div>
          )}

          {others.length > 0 && (
            <>
              <h2 style={{ fontSize: 23, marginTop: 10 }}>{t("lienzo.inicio.recientes")}</h2>
              <ul className="postits">
                {others.map((r, i) => (
                  <li key={r.id} className={`postit-card${r.exists ? "" : " gone"}`}
                      style={{ transform: `rotate(${[-1.4, 1.1, -0.5, 0.8][i % 4]}deg)` }}>
                    <span className="pin" aria-hidden="true" />
                    {r.exists ? (
                      <button className="title" onClick={() => onOpen(r.id)}>{r.name}</button>
                    ) : (
                      <span className="title" style={{ font: "400 19px var(--f-board)", color: "var(--paper-fg)" }}>{r.name}</span>
                    )}
                    <span>{r.exists ? (r.folder || data.workspace.name) : t("lienzo.inicio.ya_no_esta")}</span>
                    {r.exists ? <span>{timeAgo(r.modified ?? 0)}</span>
                      : <button className="forget" onClick={() => forget(r.id)}>{t("lienzo.inicio.quitar_recientes")}</button>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="home-col" aria-labelledby="h-carpeta">
          <div className="folder-head">
            {results ? (
              <h2 id="h-carpeta">{t("lienzo.inicio.resultados")}</h2>
            ) : (
              <nav className="crumbs" aria-label={t("lienzo.inicio.carpeta_actual")} id="h-carpeta">
                {crumbs(data.workspace.name, current.path).map((c, i, all) => (
                  <span key={c.path} style={{ display: "contents" }}>
                    {i > 0 && <span className="sep" aria-hidden="true">›</span>}
                    <button aria-current={i === all.length - 1 ? "page" : undefined}
                            className={dropOn === c.path ? "drop" : undefined}
                            onClick={() => setFolder(c.path)} {...dropProps(c.path)}>
                      {c.name}
                    </button>
                  </span>
                ))}
              </nav>
            )}
            <span className="soft">
              {results ? t("lienzo.inicio.encontrados", { n: results.length }) : folderSummary(current)}
            </span>
            <div className="btn-row">
              <button className="btn-chalk" onClick={() => setDialog({ kind: "new-project", parent: current.path })}>{t("lienzo.inicio.mas_proyecto")}</button>
              <button className="btn-outline" onClick={() => setDialog({ kind: "new-folder", parent: current.path })}>{t("lienzo.inicio.mas_carpeta")}</button>
            </div>
          </div>

          {shown.length > 0 ? (
            <ul className="tiles">{shown.map(tile)}</ul>
          ) : (
            <p className="hint">{results ? t("lienzo.inicio.nada") : t("lienzo.inicio.carpeta_vacia")}</p>
          )}
          <p className="hint">{t("lienzo.inicio.ayuda")}</p>
        </section>
      </div>

      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuFor(menu.node)} onClose={() => setMenu(null)} />}
      {newWs && <NewWorkspaceDialog base={newWs.base} onClose={() => setNewWs(null)} />}

      {d?.kind === "new-project" && (
        <NameDialog title={t("lienzo.inicio.nuevo_proyecto")} label={t("lienzo.inicio.nombre")}
                    submitLabel={t("lienzo.inicio.crear_abrir")} onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            const p = await call("POST", "/api/projects", { folder: d.parent, name });
            onOpen(p.id);
          }} />
      )}
      {d?.kind === "new-folder" && (
        <NameDialog title={t("lienzo.inicio.nueva_carpeta")} label={t("lienzo.inicio.nombre")}
                    submitLabel={t("lienzo.inicio.crear")} onClose={() => setDialog(null)}
          onSubmit={async (name) => { await call("POST", "/api/folders", { parent: d.parent, name }); await load(); }} />
      )}
      {d?.kind === "rename" && (
        <NameDialog title={t("lienzo.inicio.renombrar_titulo", { nombre: d.node.name })}
                    label={t("lienzo.inicio.nombre_nuevo")} initial={d.node.name}
                    submitLabel={t("lienzo.inicio.renombrar")}
          onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            if (d.node.kind === "project") await call("PATCH", `/api/projects/${encodeURIComponent(d.node.id!)}`, { name });
            else {
              const r = await call("PATCH", "/api/folders", { path: d.node.path, name });
              if (folder === d.node.path || folder.startsWith(d.node.path + "/")) setFolder(r.path + folder.slice(d.node.path.length));
            }
            await load();
          }} />
      )}
      {d?.kind === "move" && (
        <MoveDialog name={d.node.name} targets={moveTargets(data.tree, d.node)} onClose={() => setDialog(null)}
          onSubmit={async (dest) => { await moveNode(d.node, dest); await load(); }} />
      )}
      {d?.kind === "trash" && (
        <TrashDialog name={d.node.name} onClose={() => setDialog(null)}
          detail={d.node.kind === "folder"
            ? t(countProjects(d.node) === 1 ? "lienzo.inicio.papelera_carpeta_uno" : "lienzo.inicio.papelera_carpeta_varios",
                { n: countProjects(d.node) })
            : t("lienzo.inicio.papelera_proyecto")}
          onSubmit={async () => {
            if (d.node.kind === "project") await call("DELETE", `/api/projects/${encodeURIComponent(d.node.id!)}`);
            else await call("DELETE", `/api/folders?path=${encodeURIComponent(d.node.path)}`);
            await load();
          }} />
      )}
    </main>
  );
}
