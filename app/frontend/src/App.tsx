// Pizarra de un proyecto: Excalidraw con bloques ejecutables y escena sincronizada con el
// backend (docs/PLAN_PIZARRA.md §3). El backend es la fuente de verdad. Solo viajan los
// elementos que cambian (D69): los de otra ventana del mismo proyecto llegan como `elements`.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  CaptureUpdateAction,
  Excalidraw,
  newElementWith,
  restoreElements,
  viewportCoordsToSceneCoords,
} from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { apiFetch } from "./auth";
import { BlockView } from "./BlockView";
import { connect, disconnect, send } from "./socket";
import { getStore, NO_PACK_ISSUES, pushAgentEvent, resetStore, setStore, useStore } from "./store";
import { cardsClipboard } from "./clipboard";
import { AgentPanel } from "./AgentPanel";
import { mergeElements } from "./merge";
import { saveThumbnail } from "./thumbnail";
import { answerZone } from "./zoneRender";
import { skinOf, type SkinId } from "./skins";
import { SkinMenu } from "./SkinMenu";
import { splitDrop } from "./packs";
import { openInstall, openSettings } from "./settings";
import { PostitCard } from "./PostitCard";
import { filteredOut, KIND_LABEL, POSTIT_KINDS, POSTIT_MIN_WIDTH, userEdit, type PostitData,
         type PostitKind, type PostitPatch } from "./postit";
import { PostitFilterButton } from "./PostitFilterButton";
import { AnchorLayer, type AnchorDrag } from "./AnchorLayer";
import { InkLayer } from "./InkLayer";
import { InkMenu } from "./InkMenu";
import { isInk, normalizeInk } from "./ink";
import { cardInkFilter, skinInkFilter } from "./inkView";
import { ProposalOverlay } from "./ProposalOverlay";
import { ProposalNav } from "./ProposalNav";
import { CompareOverlay } from "./CompareOverlay";
import { PackNotice, PackPanel } from "./PackPanel";
import { FirstAnimationNotice } from "./FirstAnimationNotice";
import { showAnimationNotice } from "./animationNotice";
import { anchorMap, canAnchor, elementAt, followers, movedBetween, type Pt } from "./anchors";
import { BLOCK_MIN_WIDTH } from "./block";
import { ConnectLayer } from "./ConnectLayer";
import { BlockPalette } from "./BlockPalette";
import { isCardEl, isFolderEl, isNodeEl, syncConnections } from "./connections";
import { FileCard } from "./FileCard";
import { AddFileMenu, CardMenu, type MenuTarget } from "./CardMenu";
import { NewFileMenu } from "./OfficeMenu";
import { ThreadLayer } from "./ThreadLayer";
import { ThreadClose } from "./ThreadClose";
import { askAgent, handleThreadMessage, threadError } from "./threadActions";
import { useAskInContextMenu } from "./askMenu";
import { FolderView } from "./FolderView";
import { FolderArrows } from "./FolderArrows";
import { ExcelArrows } from "./ExcelArrows";
import { Preview } from "./Preview";
import { addCards } from "./cardActions";
import { previewKind, type Content } from "./cards";
import { ImageCard } from "./ImageCard";
import { LinkCard } from "./LinkCard";
import { IMAGE_MIN_WIDTH, keepRatio, type Box, type ImageRef } from "./paste";
import { usePaste } from "./usePaste";
import { inView } from "./animation";
import { canvasOffsets, fitShortcut, type Box as UiBox } from "./fit";
import { typing } from "./shortcuts";
import { getAppSettings, loadAppSettings, useAppSettings, type AppSettings } from "./appSettings";
import { boardFontId } from "./fonts";
import { getLanguage, t } from "./i18n";
import { barDensity, type BarDensity } from "./toolbar";
import { localizeCatalog, type CatalogParts } from "./packI18n";
import { designBusy, reviewerBusy } from "./review";

const THUMB_DELAY = 5000; // ms sin cambios antes de rehacer la miniatura

// Bloques, post-its, archivos, fotos y enlaces son tarjetas React dentro de un `embeddable`
// (D14, D71, D131, D137, D140).
const CARD_LINK = /^https:\/\/pizarra\.local\/(block|postit|file|image|link)\//;
const isCard = (e: ExcalidrawElement) => e.type === "embeddable" && CARD_LINK.test(e.link ?? "");
const cardKind = (e: ExcalidrawElement) =>
  e.type === "embeddable" ? (e.customData as { kind?: string } | undefined)?.kind : undefined;
const isPostit = (e: ExcalidrawElement) => cardKind(e) === "postit";
// Ancho mínimo de cada tarjeta (D60): el contenido se adapta al ancho, nunca se corta.
const MIN_WIDTH: Record<string, number> = { postit: POSTIT_MIN_WIDTH, block: BLOCK_MIN_WIDTH, file: 200, folder: 116,
                                            image: IMAGE_MIN_WIDTH, link: 160 };
const isImage = (e: ExcalidrawElement) => cardKind(e) === "image";
const minWidth = (e: ExcalidrawElement) => MIN_WIDTH[cardKind(e) ?? ""] ?? 0;

type Props = {
  projectId: string;
  onHome: (missing?: string) => void; // vuelve a la pantalla de inicio
  skin: SkinId;
  onSkin: (id: SkinId) => void;
};

// El fondo lo pinta el skin detrás del lienzo, que va transparente (src/skins.ts).
const INITIAL = { appState: { viewBackgroundColor: "transparent" } };
const UI_OPTIONS = { canvasActions: { changeViewBackgroundColor: false, toggleTheme: false } };

// Un texto traducido con `{name}` dentro, con ese hueco en negrita (sin partir la frase en trozos).
function withBold(text: string, name: string, value: ReactNode) {
  const [before, ...after] = text.split(`{${name}}`);
  return <>{before}<b>{value}</b>{after.join(`{${name}}`)}</>;
}

/** Selecciona unas tarjetas y las trae a la vista (lo que ya estaba al añadirlo otra vez, O17). */
function revealCards(api: ExcalidrawImperativeAPI, ids: string[]) {
  const els = api.getSceneElements().filter((e) => ids.includes(e.id));
  if (!els.length) return;
  api.updateScene({ appState: { selectedElementIds: Object.fromEntries(els.map((e) => [e.id, true])) },
                    captureUpdate: CaptureUpdateAction.NEVER });
  api.scrollToContent(els, { animate: true, duration: 300 });
}

export function ProjectBoard({ projectId, onHome, skin, onSkin }: Props) {
  const [api, setApi] = useState<ExcalidrawImperativeAPI | null>(null);
  // Solo en desarrollo: la API de Excalidraw en window, para las pruebas en el navegador.
  useEffect(() => {
    if (import.meta.env.DEV && api) (window as unknown as { __excalidraw?: unknown }).__excalidraw = api;
  }, [api]);
  // Cuánto se compacta la barra de arriba con lo que queda de pizarra junto al panel derecho
  // (toolbar.ts): la clase `bar-1` o `bar-2` en `.app`.
  const appRef = useRef<HTMLDivElement>(null);
  const [density, setDensity] = useState<BarDensity>(0);
  useEffect(() => {
    const board = appRef.current?.querySelector(":scope > .excalidraw");
    if (!board) return;
    const fit = () => setDensity(barDensity(board.getBoundingClientRect().width));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(board);
    return () => ro.disconnect();
  }, [api]);
  // Solo tarjetas seleccionadas: sin barra de enlace ni panel de trazo y relleno (D77).
  const [cardsSelected, setCardsSelected] = useState(false);
  // Con otra herramienta que la de selección (flecha, mano, formas…), el cuerpo de un bloque
  // deja pasar el ratón al lienzo: una flecha empieza encima de un bloque y la mano lo arrastra.
  const [selectTool, setSelectTool] = useState(true);
  // Los post-its de la escena, para la cuenta del filtro (solo cambia si cambia alguno).
  const [postits, setPostits] = useState<PostitData[]>([]);
  const postitsKey = useRef("");
  // Anclajes (D74): posiciones de la última vez, para saber qué se ha movido y mover con ello
  // sus post-its anclados; y el arrastre de la cinta en curso, que pinta la capa de hilos.
  const lastPos = useRef<Map<string, Pt>>(new Map());
  // Caja de cada foto suelta la última vez: dice qué borde se está estirando (keepRatio).
  const lastPhoto = useRef<Map<string, Box>>(new Map());
  const [anchorDrag, setAnchorDrag] = useState<AnchorDrag | null>(null);
  const liveCache = useRef<{ arr: unknown; ids: Set<string> }>({ arr: null, ids: new Set() });
  // Última versión de cada elemento que ya conoce el backend: solo se envía lo que cambia.
  const known = useRef<Map<string, number>>(new Map());
  const timer = useRef<number | undefined>(undefined);
  const thumbTimer = useRef<number | undefined>(undefined);
  const thumbDirty = useRef(false);
  // El catálogo de bloques tal y como llega (O15): si el idioma se conoce después de `init`
  // (los ajustes llegan por su lado), se vuelve a traducir desde él.
  const rawCatalog = useRef<CatalogParts | null>(null);
  const idioma = useAppSettings()?.idioma;
  useEffect(() => {
    if (rawCatalog.current) setStore(localizeCatalog(rawCatalog.current));
  }, [idioma]);
  const skinRef = useRef(skin);
  const { problems, packIssues, lastError, project, savedAt, postitFilter, run } = useStore();
  // Bandeja de bloques (D96 4B): se muestra u oculta con *Bloque* y se queda abierta.
  const [trayOpen, setTrayOpen] = useState(false);
  // Menú contextual de una tarjeta de archivo, de carpeta o de un bloque (D139).
  const [menu, setMenu] = useState<MenuTarget | null>(null);
  const { folderView, preview } = useStore();

  const flushThumbnail = useCallback(async () => {
    window.clearTimeout(thumbTimer.current);
    if (!api || !thumbDirty.current) return;
    thumbDirty.current = false;
    await saveThumbnail(api, projectId, skinOf(skinRef.current));
  }, [api, projectId]);

  // El skin va por ref: si flushThumbnail dependiera de él, cambiarlo reconectaría el WebSocket.
  // Al cambiarlo, la miniatura se rehace con el nuevo al rato.
  useEffect(() => {
    if (skinRef.current === skin) return;
    skinRef.current = skin;
    thumbDirty.current = true;
    window.clearTimeout(thumbTimer.current);
    thumbTimer.current = window.setTimeout(flushThumbnail, THUMB_DELAY);
  }, [skin, flushThumbnail]);

  // Mete en la escena elementos que vienen del backend (mínimos: restoreElements completa
  // valores por defecto, mide el texto y repara los enlaces de texto ligado). El alto de un
  // post-it lo corrige su tarjeta al pintarse (PostitCard).
  const applyFromServer = useCallback(
    (incoming: ExcalidrawElement[], replace: boolean) => {
      if (!api) return;
      const local = api.getSceneElementsIncludingDeleted();
      if (!replace) {
        // restoreElements da siempre la razón a lo que llega (sube su versión por encima de
        // la local): una edición local más nueva, aún sin enviar, se perdería. Se descarta lo
        // que llega más viejo; la edición local saldrá en el próximo envío.
        const localVersion = new Map(local.map((e) => [e.id, e.version]));
        incoming = incoming.filter((e) => (localVersion.get(e.id) ?? -1) <= e.version);
        if (!incoming.length) return;
      }
      // restoreElements también rehace el `index` mirando solo este lote: a lo que llega sin
      // índice (creado por el backend) se le quita el que le ponga, para que vaya al final.
      const hadIndex = new Set(incoming.filter((e) => typeof e.index === "string").map((e) => e.id));
      const restored = restoreElements(incoming, local, {
        refreshDimensions: true,
        repairBindings: true,
      }).map((e) => (replace || hadIndex.has(e.id) ? e : ({ ...e, index: null } as unknown as typeof e)));
      // Lo que no viene se queda en su sitio y en su orden de dibujo (D69).
      const elements = replace ? restored : mergeElements(local, restored);
      api.updateScene({ elements, captureUpdate: CaptureUpdateAction.NEVER });
      // Lo que acaba de llegar ya lo tiene el backend: no se reenvía.
      if (replace) known.current = new Map();
      const arrived = new Set(restored.map((e) => e.id));
      for (const e of api.getSceneElementsIncludingDeleted()) {
        if (replace || arrived.has(e.id)) known.current.set(e.id, e.version);
      }
    },
    [api],
  );

  useEffect(() => {
    if (!api) return;
    resetStore();
    // El texto de los post-its se mide al restaurarlo: si la fuente aún no está cargada se
    // mide con otra y luego se desborda. Se precarga antes de recibir la escena.
    const fontsReady = Promise.race([
      document.fonts.load("16px Excalifont", "AaÁáÉéÍíÓóÚúÑñ¿?Ø×"),   // i18n-ok: glifos a precargar
      new Promise((r) => setTimeout(r, 3000)),
    ]);
    let cancelled = false;
    fontsReady.then(() => !cancelled && connect(projectId, (msg) => {
      if (msg.type === "init") {
        // También llega al restaurar una versión: la escena entera, y la comparación ya no vale.
        // Los textos de los paquetes, ya en el idioma de la app (O15, packI18n.ts).
        rawCatalog.current = { types: msg.types, ports: msg.catalog?.ports ?? {},
                               packs: msg.catalog?.packs ?? [], connectorInfo: msg.catalog?.connectors ?? {},
                               templates: msg.catalog?.templates ?? {} };
        setStore({ project: msg.project, ...localizeCatalog(rawCatalog.current), blocks: msg.blocks,
                   problems: msg.problems, packIssues: msg.packs ?? NO_PACK_ISSUES,
                   run: msg.run ?? null, connectors: msg.connectors ?? {},
                   proposals: msg.proposals ?? [], compare: null,
                   compareFocus: null, sources: msg.sources ?? {}, folderView: null, preview: null,
                   agentState: msg.agent ?? null, threads: msg.threads ?? [],
                   reviewState: msg.review ?? null, reviewBusy: !!msg.review?.running,
                   threadBusy: msg.agent?.busy && msg.agent?.thread ? msg.agent.thread : null });
        applyFromServer(msg.elements, true);
        send({ type: "agent_history" });     // el chat guardado del proyecto (D164)
        send({ type: "review_history" });    // y la conversación del revisor (FF 6.1)
        // Un proyecto sin miniatura (p. ej. el spike importado) la tiene al poco de abrirlo.
        if (!msg.thumbnail && msg.elements.length) {
          thumbDirty.current = true;
          thumbTimer.current = window.setTimeout(flushThumbnail, THUMB_DELAY);
        }
      } else if (msg.type === "elements") {
        applyFromServer(msg.elements, false);
      } else if (msg.type === "blocks") {
        setStore({ blocks: msg.blocks, problems: msg.problems, packIssues: msg.packs ?? NO_PACK_ISSUES,
                   run: msg.run ?? null, lastError: null,
                   sources: msg.sources ?? {} });
      } else if (msg.type === "connectors") {
        // Fusion se ha abierto o cerrado (D106); los estados de los bloques llegan detrás.
        setStore({ connectors: msg.connectors });
      } else if (msg.type === "block_progress") {
        const run = getStore().run;
        if (run) setStore({ run: { ...run, block: msg.block, fraction: msg.fraction, message: msg.message } });
      } else if (msg.type === "run_finished") {
        // Lo que no se ejecutó y por qué (p. ej. un bloque sin su conector), o el fallo.
        const why = [msg.error, ...(msg.skipped ?? []).map((s: { reason: string }) => s.reason)]
          .filter(Boolean);
        if (why.length) setStore({ lastError: [...new Set(why)].join(" · ") });
      } else if (msg.type === "saved") {
        setStore({ savedAt: msg.at });
        // Miniatura para la pantalla de inicio: cuando la pizarra lleva un rato quieta.
        thumbDirty.current = true;
        window.clearTimeout(thumbTimer.current);
        thumbTimer.current = window.setTimeout(flushThumbnail, THUMB_DELAY);
      } else if (msg.type === "versions") {
        setStore({ versionsTick: getStore().versionsTick + 1 });
      } else if (msg.type === "proposals") {
        setStore({ proposals: msg.proposals });
      } else if (msg.type === "project") {
        setStore({ project: msg.project });
      } else if (msg.type === "project_closed") {
        onHome(msg.reason === "missing" ? "" : undefined);
      } else if (msg.type === "error") {
        if (!threadError(msg.message)) setStore({ lastError: msg.message });
      } else if (msg.type === "agent") {
        pushAgentEvent(msg);
      } else if (msg.type === "agent_history") {
        setStore({ agentLog: msg.events ?? [], agentState: msg.state ?? getStore().agentState,
                   agentBusy: designBusy(msg.state) });
      } else if (msg.type === "agent_state") {
        // Consumo y ajustes (D168, D169); al acabar un mensaje también libera el chat.
        const { type: _t, ...state } = msg;
        setStore({ agentState: state, agentBusy: getStore().agentBusy && designBusy(state),
                   reviewBusy: getStore().reviewBusy && reviewerBusy(state),
                   threadBusy: state.busy && state.thread ? state.thread : null });
      } else if (msg.type === "review_history") {
        // La conversación del revisor (FF 6.1), su estado y el del agente del proyecto.
        setStore({ reviewLog: msg.events ?? [], reviewState: msg.state ?? getStore().reviewState,
                   agentState: msg.agent ?? getStore().agentState, reviewBusy: !!msg.state?.running });
      } else if (msg.type === "review_state") {
        // Al acabar cada revisión: sus post-its aceptados, descartados y abiertos (§9).
        const { type: _r, ...review } = msg;
        setStore({ reviewState: review, reviewBusy: getStore().reviewBusy && !!review.running });
      } else if (handleThreadMessage(msg)) {
        // los hilos (`threads`, `thread_*`): threadActions.ts
      } else if (msg.type === "settings") {
        void loadAppSettings();              // otra ventana cambió un ajuste (D179)
      } else if (msg.type === "animation_notice") {
        showAnimationNotice();               // la primera animación del proyecto (D187)
      } else if (msg.type === "zone_request") {
        void answerZone(api, msg, skinOf(skinRef.current));   // `ver_zona` del agente (D171)
      }
    }, () => onHome()));
    return () => {
      cancelled = true;
      window.clearTimeout(timer.current);
      flushThumbnail();
      disconnect();
    };
  }, [api, applyFromServer, projectId, onHome, flushThumbnail]);

  // Volver al inicio con la miniatura ya guardada, para que la tarjeta no salga vieja.
  const goHome = async () => {
    await flushThumbnail();
    onHome();
  };

  // Cambia un elemento de la escena desde una tarjeta. `undoable`: entra en deshacer (lo que
  // escribe el usuario); lo derivado (el alto que pide el texto) no.
  const patchElement = useCallback(
    (id: string, patch: (e: ExcalidrawElement) => Partial<ExcalidrawElement> | null, undoable: boolean) => {
      if (!api) return;
      let hit = false;
      const elements = api.getSceneElementsIncludingDeleted().map((e) => {
        if (e.id !== id) return e;
        const p = patch(e);
        if (!p) return e;
        hit = true;
        return newElementWith(e, p as never);
      });
      if (hit) {
        api.updateScene({
          elements,
          captureUpdate: undoable ? CaptureUpdateAction.IMMEDIATELY : CaptureUpdateAction.NEVER,
        });
      }
    },
    [api],
  );
  // Texto, tipo o estado de un post-it, con la regla de autoría (D72): lo que escribe el
  // usuario entra en deshacer.
  const patchPostit = useCallback((id: string, patch: PostitPatch) => {
    patchElement(id, (e) => ({ customData: userEdit(e.customData as unknown as PostitData, patch) }), true);
  }, [patchElement]);

  // Ids de lo que existe (sin borrar), para el «sin anclaje» de las tarjetas. Se rehace solo
  // cuando cambia la lista de elementos de Excalidraw (misma referencia entre cambios).
  const liveIds = useCallback(() => {
    if (!api) return liveCache.current.ids;
    const arr = api.getSceneElementsIncludingDeleted();
    if (arr !== liveCache.current.arr) {
      liveCache.current = { arr, ids: new Set(arr.filter((e) => !e.isDeleted).map((e) => e.id)) };
    }
    return liveCache.current.ids;
  }, [api]);

  // Arrastrar la cinta de un post-it (D74, D80): soltarla sobre un elemento lo ancla; en vacío,
  // lo desancla. Un anclaje a sí mismo o que cierre un ciclo no se hace (el hilo sale en rojo).
  const startAnchor = useCallback((id: string, ev: PointerEvent) => {
    if (!api) return;
    const start = { x: ev.clientX, y: ev.clientY };
    const probe = (e: PointerEvent): AnchorDrag => {
      const at = viewportCoordsToSceneCoords({ clientX: e.clientX, clientY: e.clientY }, api.getAppState());
      const els = api.getSceneElements();
      const f = getStore().postitFilter;
      let hit = elementAt(els, at, (x) => x.id === id
        || (isPostit(x) && filteredOut(f, x.customData as unknown as PostitData)));
      // Un texto dentro de una forma: se ancla a la forma.
      const container = (hit as { containerId?: string | null } | null)?.containerId;
      if (container) hit = els.find((x) => x.id === container) ?? hit;
      const target = hit?.id ?? null;
      return { postit: id, at, target, bad: !!target && !canAnchor(id, target, els) };
    };
    const move = (e: PointerEvent) => setAnchorDrag(probe(e));
    const up = (e: PointerEvent) => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      setAnchorDrag(null);
      if (Math.hypot(e.clientX - start.x, e.clientY - start.y) < 4) return;   // un clic, no un arrastre
      const d = probe(e);
      if (d.bad) return;
      patchElement(id, (el) => ((el.customData as { anchor?: string | null })?.anchor ?? null) === d.target
        ? null : { customData: { ...el.customData, anchor: d.target } }, true);
      (document.querySelector(".excalidraw") as HTMLElement | null)?.focus();
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
    setAnchorDrag(probe(ev));
  }, [api, patchElement]);

  // Un post-it oculto por el filtro no se queda seleccionado (no se ve, no se mueve sin querer).
  const dropFiltered = useCallback(() => {
    if (!api) return;
    const st = api.getAppState();
    const f = getStore().postitFilter;
    const byId = new Map(api.getSceneElements().map((e) => [e.id, e]));
    const sel = Object.keys(st.selectedElementIds);
    const keep = sel.filter((id) => {
      const e = byId.get(id);
      return !(e && isPostit(e) && filteredOut(f, e.customData as unknown as PostitData));
    });
    if (keep.length !== sel.length) {
      api.updateScene({ appState: { selectedElementIds: Object.fromEntries(keep.map((id) => [id, true])) } });
    }
  }, [api]);
  useEffect(dropFiltered, [postitFilter, dropFiltered]);
  // El alto de una tarjeta lo pide su contenido (post-it y bloque): no entra en deshacer.
  const setCardHeight = useCallback((id: string, height: number) => {
    patchElement(id, (e) => (Math.abs(e.height - height) < 1 ? null : { height }), false);
  }, [patchElement]);

  // Doble clic sobre un post-it: se abre su cuadro de texto (D71); sobre una carpeta, su vista
  // (D59). Se escucha antes que Excalidraw, que con un doble clic crearía un texto nuevo encima.
  useEffect(() => {
    if (!api) return;
    const onDbl = (ev: MouseEvent) => {
      const t = ev.target as HTMLElement | null;
      if (t?.closest?.(".postit-edit, .postit-ctl, .postit-kind, .pf, .project-pill, .toolbar, .ag-panel, .ag-fab, .fc-bar, .fc-lost, .fk-big, .fv-back, .card-menu, .lk-edit, .th-layer > *, .th-close-back")) return;
      const st = api.getAppState();
      const { x, y } = viewportCoordsToSceneCoords({ clientX: ev.clientX, clientY: ev.clientY }, st);
      const top = [...api.getSceneElements()].reverse().find((e) =>
        x >= e.x && x <= e.x + e.width && y >= e.y && y <= e.y + e.height);
      // Enlace: cambiar el título (D137); foto: nada (Excalidraw pondría un texto encima).
      if (top && (cardKind(top) === "link" || isImage(top))) {
        ev.stopPropagation();
        ev.preventDefault();
        if (cardKind(top) === "link") setStore({ editingLink: top.id });
        return;
      }
      if (top && isCardEl(top)) {
        ev.stopPropagation();
        ev.preventDefault();
        const src = getStore().sources[top.id];
        if (isFolderEl(top)) {
          if (src?.ok !== false) setStore({ folderView: top.id });
        } else if (src?.ok && previewKind(src.type)) {
          setStore({ preview: top.id });           // doble clic: *Previsualizar* (D139)
        }
        return;
      }
      const f = getStore().postitFilter;
      const hit = [...api.getSceneElements()].reverse().find((e) =>
        isPostit(e) && !filteredOut(f, e.customData as unknown as PostitData)
        && x >= e.x && x <= e.x + e.width && y >= e.y && y <= e.y + e.height);
      if (!hit) return;
      ev.stopPropagation();
      ev.preventDefault();
      setStore({ editingPostit: hit.id });
    };
    window.addEventListener("dblclick", onDbl, true);
    return () => window.removeEventListener("dblclick", onDbl, true);
  }, [api]);

  // Ctrl+C y Ctrl+X (D85): un texto seleccionado se copia como texto; si no, con un bloque
  // seleccionado se copia el bloque con sus parámetros, para pegarlo aquí o en otro proyecto.
  // Se escucha antes que Excalidraw, que lo copiaría sin ellos (copiar, con el evento `copy`;
  // cortar, con la tecla). Un clic en el lienzo quita la selección de texto, para que Ctrl+C
  // no copie un texto seleccionado de antes.
  useEffect(() => {
    if (!api) return;
    const textSelected = () => {
      const sel = document.getSelection();
      return !!sel && !sel.isCollapsed && !!String(sel).trim();
    };
    const inField = (t: EventTarget | null) =>
      !!(t as HTMLElement | null)?.closest?.("input, textarea, select, [contenteditable]");
    const blocksClipboard = () => cardsClipboard(api.getSceneElements(),
      new Set(Object.keys(api.getAppState().selectedElementIds)),
      (id) => getStore().blocks[id]?.params);
    const onCopy = (ev: ClipboardEvent) => {
      if (inField(ev.target)) return;
      if (textSelected()) {
        ev.stopImmediatePropagation();     // copia el navegador; Excalidraw copiaría elementos
        return;
      }
      const text = blocksClipboard();
      if (!text || !ev.clipboardData) return;
      ev.clipboardData.setData("text/plain", text);
      ev.preventDefault();
      ev.stopImmediatePropagation();
    };
    const onCutKey = (ev: KeyboardEvent) => {
      if (!(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== "x" || ev.altKey || ev.shiftKey) return;
      if (inField(ev.target) || textSelected()) return;
      const text = blocksClipboard();
      if (!text) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      // Primero al portapapeles; después lo borra Excalidraw con su propio Supr (desengancha
      // las flechas y entra en deshacer), como si se hubiera pulsado.
      navigator.clipboard.writeText(text).then(() =>
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Delete", code: "Delete", bubbles: true })),
      ).catch(() => setStore({ lastError: t("lienzo.portapapeles.error") }));
    };
    const onCanvasDown = (ev: PointerEvent) => {
      if ((ev.target as HTMLElement | null)?.tagName === "CANVAS") document.getSelection()?.removeAllRanges();
    };
    window.addEventListener("copy", onCopy, true);
    window.addEventListener("keydown", onCutKey, true);
    window.addEventListener("pointerdown", onCanvasDown, true);
    return () => {
      window.removeEventListener("copy", onCopy, true);
      window.removeEventListener("keydown", onCutKey, true);
      window.removeEventListener("pointerdown", onCanvasDown, true);
    };
  }, [api]);

  // La fuente de la pizarra (D184) en los textos nuevos de Excalidraw; los ya dibujados se
  // quedan con la suya. Los post-its la toman de `--f-board` (Root). Va ya en `initialData`:
  // Excalidraw restaura su appState al arrancar y pisaría la que se pusiera antes; si los
  // ajustes aún no han llegado, los espera. Los cambios de después, con `updateScene`.
  const initialData = useMemo(() => {
    const withFont = (s: AppSettings | null) =>
      ({ appState: { ...INITIAL.appState, currentItemFontFamily: boardFontId(s?.fuentes.pizarra) } });
    const now = getAppSettings();
    return now ? withFont(now) : loadAppSettings().then(withFont);
  }, []);
  const boardFont = useAppSettings()?.fuentes.pizarra;
  useEffect(() => {
    if (!api || !boardFont) return;
    api.updateScene({ appState: { currentItemFontFamily: boardFontId(boardFont) },
                      captureUpdate: CaptureUpdateAction.NEVER });
  }, [api, boardFont]);

  // Encuadrar (por defecto Mayús+1, 2 y 3, configurables: D185) con los márgenes de la interfaz
  // de verdad (fit.ts): el de Excalidraw cree que su barra de herramientas está arriba y deja el
  // zoom al 10 %.
  useEffect(() => {
    if (!api) return;
    const onKey = (ev: KeyboardEvent) => {
      const kind = fitShortcut(ev);
      if (!kind || typing(ev.target)) return;
      const root = document.querySelector<HTMLElement>(".excalidraw");
      const all = api.getSceneElements();
      if (!root || !all.length) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      const at = root.getBoundingClientRect();
      const rel = (el: Element | null): UiBox | null => {
        const r = el?.getBoundingClientRect();
        return r && (r.width || r.height)
          ? { top: r.top - at.top, bottom: r.bottom - at.top, left: r.left - at.left, right: r.right - at.left }
          : null;
      };
      const offsets = canvasOffsets({ width: at.width, height: at.height }, {
        top: [rel(root.querySelector(".App-menu_top")), rel(document.querySelector(".project-pill"))]
          .filter((b): b is UiBox => b !== null),
        toolbar: rel(root.querySelector(".App-toolbar")),
        left: rel(root.querySelector(".App-menu__left")),
        right: rel(root.querySelector(".sidebar")),
      });
      const sel = api.getAppState().selectedElementIds;
      const picked = kind === "all" ? [] : all.filter((e) => sel[e.id]);
      const targets = picked.length ? picked : all;
      api.scrollToContent(targets, kind === "viewport"
        ? { fitToViewport: true, canvasOffsets: offsets }
        : { fitToContent: true, canvasOffsets: offsets });
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [api]);

  // El título de un enlace (D137): lo escribe el usuario, entra en deshacer.
  const setLinkTitle = useCallback((id: string, title: string) => {
    patchElement(id, (e) => ({ customData: { ...e.customData, title } }), true);
  }, [patchElement]);

  // Ctrl+V (D84, D137, D140): imagen en un post-it, foto suelta o enlace (usePaste.ts).
  usePaste(api, patchPostit);

  // Clic derecho sobre una tarjeta de archivo, de carpeta o un bloque: el menú propio (D139),
  // con la tarjeta seleccionada (o, si es parte de una selección de varios, con todos, para
  // *Preguntar al agente* sobre ellos, D176). En lo demás, el de Excalidraw; sobre un post-it
  // o una foto, con *Preguntar al agente* arriba (`askMenu.ts`).
  useEffect(() => {
    if (!api) return;
    const onMenu = (ev: MouseEvent) => {
      const t = ev.target as HTMLElement | null;
      if (t?.closest?.("input, textarea, [contenteditable], .card-menu, .fv-back, .ag-panel, .th-layer > *, .th-close-back")) return;
      const p = viewportCoordsToSceneCoords({ clientX: ev.clientX, clientY: ev.clientY }, api.getAppState());
      const hit = [...api.getSceneElements()].reverse().find((e) =>
        p.x >= e.x && p.x <= e.x + e.width && p.y >= e.y && p.y <= e.y + e.height);
      if (!hit || !isNodeEl(hit)) return;
      ev.preventDefault();
      ev.stopPropagation();
      const sel = Object.keys(api.getAppState().selectedElementIds);
      const group = sel.length > 1 && sel.includes(hit.id) ? sel : undefined;
      if (!group) api.updateScene({ appState: { selectedElementIds: { [hit.id]: true } } });
      setMenu({ id: hit.id, kind: cardKind(hit) as MenuTarget["kind"], at: { x: ev.clientX, y: ev.clientY }, group });
    };
    window.addEventListener("contextmenu", onMenu, true);
    return () => window.removeEventListener("contextmenu", onMenu, true);
  }, [api]);

  useAskInContextMenu(api);

  // Archivos y carpetas arrastrados desde el explorador (D59): el shell de Tauri da sus rutas
  // (src-tauri/src/main.rs) en `pizarra-drop`, con el punto de la ventana donde se soltaron.
  useEffect(() => {
    if (!api) return;
    const onDrop = (ev: Event) => {
      const { paths: all, x, y } = (ev as CustomEvent<{ paths: string[]; x: number; y: number }>).detail ?? {};
      const paths = splitDrop(all ?? []).others;    // los .bppack, a instalar (Root, P82)
      if (!paths.length) return;
      const dpr = window.devicePixelRatio || 1;
      const at = viewportCoordsToSceneCoords({ clientX: x / dpr, clientY: y / dpr }, api.getAppState());
      void addCards(at, "file", paths, (ids) => revealCards(api, ids));
    };
    window.addEventListener("pizarra-drop", onDrop);
    return () => window.removeEventListener("pizarra-drop", onDrop);
  }, [api]);

  // Quitar de la pizarra (nunca borra el archivo): lo borra Excalidraw con su Supr, que
  // desengancha las flechas y entra en deshacer.
  const removeCard = useCallback((id: string) => {
    if (!api) return;
    api.updateScene({ appState: { selectedElementIds: { [id]: true } } });
    (document.querySelector(".excalidraw") as HTMLElement | null)?.focus();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Delete", code: "Delete", bubbles: true }));
  }, [api]);
  const openMenu = useCallback((id: string, at: { x: number; y: number }) => {
    const el = api?.getSceneElements().find((e) => e.id === id);
    if (el) setMenu({ id, kind: cardKind(el) as MenuTarget["kind"], at });
  }, [api]);
  // Lo que entra de una carpeta (D142), al pulsar *Hecho* en su vista: entra en deshacer.
  const saveContent = useCallback((id: string, content: Content) => {
    patchElement(id, (e) => ({ customData: { ...e.customData, content } }), true);
  }, [patchElement]);
  // Sobrescribir o archivo nuevo, por archivo, en la flecha a una carpeta (D109).
  const setOverwrite = useCallback((arrow: string, overwrite: string[]) => {
    patchElement(arrow, (e) => ({ customData: { ...e.customData, overwrite } }), true);
  }, [patchElement]);

  // Centro de la vista, en coordenadas de la escena (donde salen los post-its y los archivos).
  const viewCenter = (dx: number, dy: number) => {
    const s = api!.getAppState();
    return { x: -s.scrollX + s.width / s.zoom.value / 2 - dx, y: -s.scrollY + s.height / s.zoom.value / 2 - dy };
  };

  // Cambios del usuario: con un pequeño retardo, y solo los elementos cuya versión no conoce
  // el backend. Se miran también los borrados (Excalidraw los guarda con isDeleted).
  const onChange = useCallback((_els: readonly ExcalidrawElement[], appState: {
    selectedElementIds: Readonly<Record<string, true>>; activeTool: { type: string };
  }) => {
    setSelectTool(appState.activeTool.type === "selection");
    const sel = Object.keys(appState.selectedElementIds);
    if (api) {
      const byId = new Map(api.getSceneElements().map((e) => [e.id, e]));
      setCardsSelected(sel.length > 0 && sel.every((id) => { const e = byId.get(id); return !!e && isCard(e); }));
      const list = api.getSceneElements().filter(isPostit).map((e) => e.customData as unknown as PostitData);
      const key = list.map((p) => `${p.postitKind}:${p.state}:${p.author}`).join("|");
      if (key !== postitsKey.current) {
        postitsKey.current = key;
        setPostits(list);
      }
      dropFiltered();
    }
    // Un trazo de tinta va siempre con `opacity 0` (D188): si se la sube el panel de Excalidraw,
    // pasa a `customData.ink.opacity`, sin entrar en deshacer.
    if (api) {
      const raised = api.getSceneElements().filter((e) => isInk(e) && e.opacity > 0);
      if (raised.length) {
        const ids = new Set(raised.map((e) => e.id));
        api.updateScene({
          elements: api.getSceneElementsIncludingDeleted().map((e) => {
            if (!ids.has(e.id)) return e;
            const n = normalizeInk(e);
            return newElementWith(e, { opacity: n.opacity, customData: n.customData });
          }),
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      }
    }
    // Lo que se ha movido arrastra a sus post-its anclados, y a los anclados a esos (D74),
    // salvo los que se han movido a la vez. No entra en deshacer: al deshacer el movimiento,
    // vuelven con él.
    if (api) {
      const els = api.getSceneElements();
      const moved = movedBetween(lastPos.current, els);
      const follow = moved.size ? followers(moved, anchorMap(els)) : new Map<string, Pt>();
      if (follow.size) {
        api.updateScene({
          elements: api.getSceneElementsIncludingDeleted().map((e) => {
            const d = follow.get(e.id);
            return d ? newElementWith(e, { x: e.x + d.x, y: e.y + d.y }) : e;
          }),
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      }
      lastPos.current = new Map(api.getSceneElements().map((e) => [e.id, { x: e.x, y: e.y }]));
    }
    // Cada conexión acaba en su enchufe (D88, R18): al crecer un bloque y en las flechas del
    // spike. Mientras se arrastra o se estira algo, lo mantiene Excalidraw; se ajusta al soltar.
    if (api) {
      const st = api.getAppState() as unknown as { selectedElementsAreBeingDragged?: boolean; resizingElement?: unknown };
      if (!st.selectedElementsAreBeingDragged && !st.resizingElement) syncConnections(api, getStore().types);
    }
    // Una tarjeta nunca más estrecha que su mínimo (D60): el contenido se adapta al ancho.
    if (api) {
      const narrow = api.getSceneElements().filter((e) => e.width < minWidth(e));
      if (narrow.length) {
        const ids = new Set(narrow.map((e) => e.id));
        api.updateScene({
          elements: api.getSceneElementsIncludingDeleted().map((e) =>
            ids.has(e.id) ? newElementWith(e, { width: minWidth(e) }) : e),
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      }
    }
    // Una foto suelta nunca se deforma (D84): el alto lo da el ancho, también mientras se estira.
    if (api) {
      const fixes = new Map<string, Box>();
      for (const e of api.getSceneElements()) {
        const img = isImage(e) ? (e.customData as { image?: ImageRef }).image : undefined;
        const box = img ? keepRatio(lastPhoto.current.get(e.id), e, img) : null;
        if (box) fixes.set(e.id, box);
      }
      if (fixes.size) {
        api.updateScene({
          elements: api.getSceneElementsIncludingDeleted().map((e) => {
            const b = fixes.get(e.id);
            return b ? newElementWith(e, { y: b.y, height: b.height }) : e;
          }),
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      }
      lastPhoto.current = new Map(api.getSceneElements().filter(isImage)
        .map((e) => [e.id, { x: e.x, y: e.y, width: e.width, height: e.height }]));
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      if (!api) return;
      // Lo que se está dibujando o escribiendo aún no sale: se manda al acabar.
      const st = api.getAppState() as unknown as Record<string, { id?: string } | null>;
      const busy = new Set([st.newElement?.id, st.editingTextElement?.id, st.multiElement?.id]);
      // Lo nuevo de esta ventana lleva autor y fecha (D72); lo pegado ya trae los suyos y el
      // backend corrige un autor de agente.
      const fresh = api.getSceneElementsIncludingDeleted().filter((e) =>
        !known.current.has(e.id) && !busy.has(e.id) && !e.isDeleted
        && !(e.customData as { author?: string } | undefined)?.author);
      if (fresh.length) {
        const ids = new Set(fresh.map((e) => e.id));
        const created = new Date().toISOString().replace(/\.\d+Z$/, "+00:00");
        api.updateScene({
          elements: api.getSceneElementsIncludingDeleted().map((e) => ids.has(e.id)
            ? newElementWith(e, { customData: { ...e.customData, author: "user", created } }) : e),
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      }
      const changed = api.getSceneElementsIncludingDeleted()
        .filter((e) => known.current.get(e.id) !== e.version && !busy.has(e.id));
      if (!changed.length) return;
      for (const e of changed) known.current.set(e.id, e.version);
      send({ type: "scene", elements: changed });
    }, 250);
  }, [api, dropFiltered]);

  // Post-it nuevo del usuario en el centro de la vista, con su cuadro de texto abierto.
  const addPostit = async (kind: PostitKind) => {
    if (!api) return;
    const s = api.getAppState();
    const x = -s.scrollX + s.width / s.zoom.value / 2 - 130;
    const y = -s.scrollY + s.height / s.zoom.value / 2 - 60;
    const r = await apiFetch(`/api/projects/${encodeURIComponent(projectId)}/postits`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, x, y }),
    });
    if (r.ok) setStore({ editingPostit: (await r.json()).id });
  };

  return (
    <div ref={appRef} className={["app", cardsSelected && "cards-selected", !selectTool && "tool-other",
                                  density > 0 && `bar-${density}`].filter(Boolean).join(" ")}
         style={{ "--ink-filter": skinOf(skin).inkFilter ?? "none" } as CSSProperties}>
      <Excalidraw
        excalidrawAPI={setApi}
        onChange={onChange}
        langCode={getLanguage() === "en" ? "en" : "es-ES"}
        theme={skinOf(skin).dark ? "dark" : "light"}
        initialData={initialData}
        UIOptions={UI_OPTIONS}
        validateEmbeddable={CARD_LINK}
        // El icono de enlace de una tarjeta no se pinta (vite.config.ts), pero su zona de clic
        // sigue ahí: sin esto, pulsar justo encima de la esquina abre el enlace interno.
        onLinkOpen={(el, ev) => { if (CARD_LINK.test(el.link ?? "")) ev.preventDefault(); }}
        renderEmbeddable={(el, appState) => {
          const cd = el.customData as { kind?: string; blockType?: string } | undefined;
          if (cd?.kind === "file" || cd?.kind === "folder") {
            return <FileCard id={el.id} kind={cd.kind} data={cd as { path?: string; content?: unknown }}
                             selected={!!appState.selectedElementIds[el.id]} height={el.height}
                             onHeight={setCardHeight} onMenu={openMenu} onRemove={removeCard} />;
          }
          if (cd?.kind === "image") {
            return <ImageCard id={el.id} data={cd as { image?: ImageRef }}
                              selected={!!appState.selectedElementIds[el.id]}
                              anchorLost={!!(cd as { anchor?: string | null }).anchor
                                          && !liveIds().has((cd as { anchor: string }).anchor)}
                              onAnchorStart={startAnchor} />;
          }
          if (cd?.kind === "link") {
            return <LinkCard id={el.id} data={cd as { url?: string; title?: string }} height={el.height}
                             selected={!!appState.selectedElementIds[el.id]}
                             onHeight={setCardHeight} onTitle={setLinkTitle} />;
          }
          if (cd?.kind === "postit") {
            return <PostitCard id={el.id} data={cd as unknown as PostitData} height={el.height}
                               selected={!!appState.selectedElementIds[el.id]} inView={inView(el, appState)}
                               anchorLost={!!(cd as { anchor?: string | null }).anchor
                                           && !liveIds().has((cd as { anchor: string }).anchor)}
                               onAnchorStart={startAnchor}
                               onPatch={patchPostit} onHeight={setCardHeight} />;
          }
          if (cd?.kind !== "block" || !cd.blockType) return null;
          return <BlockView id={el.id} blockType={cd.blockType} height={el.height}
                            onHeight={setCardHeight} />;
        }}
        renderTopRightUI={() => (
          <div className="toolbar">
            {POSTIT_KINDS.map((k) => (
              <button key={k} className="tb-postit" onClick={() => addPostit(k)}
                      title={t("lienzo.barra.nuevo_postit", { tipo: KIND_LABEL[k].toLowerCase() })}
                      aria-label={t("lienzo.barra.nuevo_postit", { tipo: KIND_LABEL[k].toLowerCase() })}>
                <i style={{ background: `var(--pi-${k})`, boxShadow: `inset 0 0 0 1.5px var(--pi-${k}-b)` }} />
              </button>
            ))}
            <span className="tb-sep" aria-hidden="true" />
            <InkMenu filter={skinInkFilter(skinOf(skin))} />
            <AddFileMenu at={() => viewCenter(120, 20)} onExisting={(ids) => api && revealCards(api, ids)} />
            <NewFileMenu api={api} />
            <button className={trayOpen ? "tb-on" : ""} aria-pressed={trayOpen} onClick={() => setTrayOpen((o) => !o)}
                    title={t("lienzo.barra.bandeja_titulo")} aria-label={t("lienzo.barra.bloque")}>
              <span className="tb-glyph" aria-hidden="true">▦</span><span className="tb-label">{t("lienzo.barra.bloque")}</span>
            </button>
            {/* Ejecutar lo desactualizado (D89): todo lo que no está al día; lo que no se puede
                ejecutar se salta y se dice por qué. Apagado mientras dura una ejecución. */}
            <button disabled={run !== null} onClick={() => send({ type: "run_stale" })}
                    title={t("lienzo.barra.ejecutar_titulo")} aria-label={t("lienzo.barra.ejecutar")}>
              <span className="tb-glyph" aria-hidden="true">▶</span><span className="tb-label">{t("lienzo.barra.ejecutar")}</span>
            </button>
          </div>
        )}
      />
      {/* Píldora del proyecto (plan D63): nombre, carpeta, guardado y vuelta al inicio. */}
      <div className="project-pill">
        <button className="pill-home" onClick={goHome} aria-label={t("lienzo.pildora.inicio")}
                title={t("lienzo.pildora.inicio")}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 11l9-7 9 7" /><path d="M5 10v10h14V10" /><path d="M10 20v-6h4v6" />
          </svg>
        </button>
        <span className="pill-name">{project?.name ?? "…"}</span>
        <span className="pill-meta">
          {[project?.folder, savedAt ? t("lienzo.pildora.guardado") : null].filter(Boolean).join(" · ")}
        </span>
        <ProposalNav api={api} />
        <SkinMenu skin={skin} onSkin={onSkin} />
        <button className="pill-home" onClick={() => openSettings()} aria-label={t("lienzo.pildora.ajustes")} title={t("lienzo.pildora.ajustes")}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
          </svg>
        </button>
      </div>
      {api && <AnchorLayer api={api} drag={anchorDrag} />}
      {api && <InkLayer api={api} filter={skinInkFilter(skinOf(skin))} cardFilter={cardInkFilter(skinOf(skin))} />}
      {api && <ConnectLayer api={api} />}
      {api && <FolderArrows api={api} onOverwrite={setOverwrite} />}
      {api && <ExcelArrows api={api} />}
      {menu && <CardMenu target={menu} onClose={() => setMenu(null)} onRemove={removeCard}
                         onAsk={(ids) => api && askAgent(api, ids)} api={api} />}
      {api && preview && (() => {
        const el = api.getSceneElements().find((e) => e.id === preview);
        if (!el) return null;
        const path = String((el.customData as { path?: string }).path ?? "");
        return <Preview key={preview} id={preview} name={path.split(/[\\/]/).pop() ?? ""}
                        onClose={() => setStore({ preview: null })} />;
      })()}
      {api && folderView && (() => {
        const el = api.getSceneElements().find((e) => e.id === folderView);
        if (!el) return null;
        const cd = el.customData as { path?: string; content?: unknown };
        return <FolderView key={folderView} id={folderView} name={String(cd.path ?? "").split(/[\\/]/).pop() ?? ""}
                           content={cd.content} onSave={(c) => saveContent(folderView, c)}
                           onClose={() => setStore({ folderView: null })} />;
      })()}
      {api && <BlockPalette api={api} projectId={projectId} trayOpen={trayOpen} onCloseTray={() => setTrayOpen(false)} />}
      {api && <ThreadLayer api={api} />}
      <ThreadClose />
      {api && <ProposalOverlay api={api} />}
      {api && <CompareOverlay api={api} />}
      <PackPanel />
      <PackNotice />
      <FirstAnimationNotice />
      <PostitFilterButton postits={postits} />
      <AgentPanel projectId={projectId} api={api} beforeSave={async () => {
        thumbDirty.current = true;          // la versión se lleva la miniatura de ahora
        await flushThumbnail();
      }} />
      {(problems.length > 0 || lastError || packIssues.missing.length > 0 || packIssues.changed.length > 0) && (
        <div className="problems">
          {lastError && <div>⚠ {lastError}</div>}
          {problems.map((p) => (
            <div key={p.arrow}>{t("lienzo.problemas.conexion", { motivo: p.reason })}</div>
          ))}
          {/* P13: nunca se pierde nada; se instala desde aquí (PLAN_PAQUETES P82) */}
          {packIssues.missing.map((p) => (
            <div key={`m-${p.id}`}>
              {withBold(t("lienzo.problemas.falta_paquete",
                          { version: p.version ? ` ${p.version}` : "", n: p.blocks.length }), "id", p.id)}
            </div>
          ))}
          {packIssues.missing.length > 0 && (
            <button className="problems-btn" onClick={() => openInstall({ pick: true })}>
              {t("lienzo.problemas.instalar")}
            </button>
          )}
          {packIssues.changed.map((p) => (
            <div key={`c-${p.id}`}>
              {withBold(t("lienzo.problemas.version_cambiada",
                          { locked: p.locked, installed: p.installed }), "id", p.id)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
