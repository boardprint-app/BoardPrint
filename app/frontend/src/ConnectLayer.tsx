// Crear una conexión desde un enchufe (plan §3, D88): se arrastra desde un punto y se suelta en
// un enchufe del otro lado o en el cuerpo de otro bloque. En el cuerpo, si solo hay una entrada
// libre del mismo tipo se usa esa; si hay varias, sale un menú; si ninguna, se dice por qué.
// También pinta el nombre del puerto sobre una conexión, del color de su tipo, cuando el ratón
// pasa por ella o está seleccionada (R37), y junto a cada flecha no válida, siempre, su motivo
// (los `problems` del backend): es un error, y la línea sola no lo dice.
//
// Las tarjetas de archivo y de carpeta (D131) tienen enchufes como los bloques: su salida va a
// una entrada que la acepte (`archivo` acepta cualquier `archivo.*`, D132), y la entrada de una
// carpeta recibe las salidas de un bloque (D109): desde un enchufe de salida, solo esa salida;
// desde la carpeta soltada en un bloque, todas. Su etiqueta la pinta FolderArrows. La entrada de
// un Excel recibe la flecha de escritura de un bloque (PLAN_EXCEL §3.3): qué campo va a cada
// nombre se elige en la tarjeta.
import { useEffect, useState, type CSSProperties } from "react";
import { viewportCoordsToSceneCoords } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { useSceneTick } from "./useSceneTick";
import { useHoveredConnection } from "./useHoveredConnection";
import { getStore, setStore, useStore } from "./store";
import { addConnection, cardPort, isCardEl, isExcelEl, isFolderEl, isNodeEl, isConnection } from "./connections";
import { accepts } from "./cards";
import { t } from "./i18n";
import { tp } from "./packI18n";
import { compatibleInputs, labelSpot, portColor, type Pt, type Side } from "./ports";

type End = { block: string; port: string; side: Side; type: string; kind: string };
type Drag = { from: End; start: Pt; at: Pt; hover: End | null };
type Menu = { at: Pt; src: ExcalidrawElement; outPort: string; dst: ExcalidrawElement; options: string[]; type: string };

// Enchufe bajo un punto de la pantalla (el DOM de las tarjetas va encima del lienzo).
function socketAt(x: number, y: number): End | null {
  for (const n of document.elementsFromPoint(x, y)) {
    const s = (n as HTMLElement).closest?.(".sock") as HTMLElement | null;
    const b = s?.closest("[data-block]") as HTMLElement | null;
    if (s && b?.dataset.block) {
      return { block: b.dataset.block, port: s.dataset.port ?? "", side: s.classList.contains("sock-out") ? "out" : "in",
               type: s.dataset.type ?? "", kind: b.dataset.kind ?? "block" };
    }
  }
  return null;
}

export function ConnectLayer({ api }: { api: ExcalidrawImperativeAPI }) {
  const { types, problems, ports } = useStore();
  const [drag, setDrag] = useState<Drag | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  useSceneTick(api);
  const hovered = useHoveredConnection(api);

  const elById = (id: string) => api.getSceneElements().find((e) => e.id === id);
  const typeOf = (el: ExcalidrawElement) => types[(el.customData as { blockType?: string })?.blockType ?? ""];

  // Las salidas de un bloque a una carpeta: `port` null, todas.
  const toFolder = (blockId: string, kind: string, port: string | null, folder: ExcalidrawElement | undefined) => {
    if (kind !== "block") return setStore({ lastError: t("bloques.conexion.solo_bloques_a_carpeta") });
    const src = elById(blockId);
    if (src && folder) addConnection(api, types, src, port, folder, null);
  };
  // La flecha de escritura de un bloque a un Excel (una sola por bloque: lo que va a cada
  // nombre se elige en la tarjeta).
  const toExcel = (blockId: string, kind: string, port: string | null, card: ExcalidrawElement | undefined) => {
    if (kind !== "block") return setStore({ lastError: t("bloques.conexion.solo_bloques_a_excel") });
    const src = elById(blockId);
    const dup = api.getSceneElements().some((e) => isConnection(e)
      && (e as { startBinding?: { elementId: string } | null }).startBinding?.elementId === blockId
      && (e as { endBinding?: { elementId: string } | null }).endBinding?.elementId === card?.id);
    if (dup) return setStore({ lastError: t("bloques.conexion.escritura_repetida") });
    if (src && card) addConnection(api, types, src, port, card, null);
  };
  const cardName = (el: ExcalidrawElement) =>
    String((el.customData as { path?: string })?.path ?? "").split(/[\\/]/).pop() ?? "";

  // Une `a` y `b` (uno de cada lado) o explica por qué no.
  const finish = (a: End, b: End | null, at: Pt, overBlock: ExcalidrawElement | null) => {
    const out = a.side === "out" ? a : b, inn = a.side === "in" ? a : b;
    if (b && b.side !== a.side && b.block !== a.block) {
      if (inn!.kind === "folder") return toFolder(out!.block, out!.kind, out!.port, elById(inn!.block));
      if (inn!.kind === "file") return toExcel(out!.block, out!.kind, out!.port, elById(inn!.block));
      if (!accepts(inn!.type, out!.type)) {
        return setStore({ lastError: t("bloques.conexion.tipo_distinto", { a: out!.port, ta: out!.type, b: inn!.port, tb: inn!.type }) });
      }
      if (getStore().blocks[inn!.block]?.inputs?.[inn!.port]) {
        return setStore({ lastError: t("bloques.conexion.ya_conectada", { port: inn!.port }) });
      }
      const src = elById(out!.block), dst = elById(inn!.block);
      if (src && dst) addConnection(api, types, src, out!.port, dst, inn!.port);
      return;
    }
    if (!overBlock || overBlock.id === a.block) return;         // soltada en vacío: nada
    if (a.kind === "folder" && a.side === "in") {               // de la carpeta a un bloque
      return isCardEl(overBlock) ? setStore({ lastError: t("bloques.conexion.solo_bloques_a_carpeta") })
        : toFolder(overBlock.id, "block", null, elById(a.block));
    }
    if (a.kind === "file" && a.side === "in") {                 // del Excel a un bloque
      return toExcel(overBlock.id, isCardEl(overBlock) ? "card" : "block", null, elById(a.block));
    }
    if (isCardEl(overBlock)) {
      if (a.side === "out") {
        return isFolderEl(overBlock) ? toFolder(a.block, a.kind, a.port, overBlock)
          : isExcelEl(overBlock) ? toExcel(a.block, a.kind, a.port, overBlock)
          : setStore({ lastError: t("bloques.conexion.archivo_no_recibe") });
      }
      const ct = getStore().sources[overBlock.id]?.type ?? (isFolderEl(overBlock) ? "carpeta" : "archivo");
      if (!accepts(a.type, ct)) {
        return setStore({ lastError: t("bloques.conexion.tipo_distinto", { a: cardName(overBlock), ta: ct, b: a.port, tb: a.type }) });
      }
      if (getStore().blocks[a.block]?.inputs?.[a.port]) {
        return setStore({ lastError: t("bloques.conexion.ya_conectada", { port: a.port }) });
      }
      return addConnection(api, types, overBlock, cardPort(overBlock), elById(a.block)!, a.port);
    }
    const ty = typeOf(overBlock);
    if (!ty) return;
    if (a.side === "out") {
      const options = compatibleInputs(a.type, ty.inputs, Object.keys(getStore().blocks[overBlock.id]?.inputs ?? {}));
      const src = elById(a.block)!;
      if (options.length === 1) return addConnection(api, types, src, a.port, overBlock, options[0]);
      if (options.length > 1) return setMenu({ at, src, outPort: a.port, dst: overBlock, options, type: a.type });
      return setStore({ lastError: t("bloques.conexion.sin_entrada_libre", { title: ty.title, type: a.type }) });
    }
    // Desde una entrada, soltada en un bloque: su única salida de ese tipo.
    const outs = Object.entries(ty.outputs).filter(([, ot]) => accepts(a.type, ot)).map(([p]) => p);
    if (getStore().blocks[a.block]?.inputs?.[a.port]) {
      return setStore({ lastError: t("bloques.conexion.ya_conectada", { port: a.port }) });
    }
    const dst = elById(a.block)!;
    if (outs.length === 1) return addConnection(api, types, overBlock, outs[0], dst, a.port);
    if (outs.length === 0) return setStore({ lastError: t("bloques.conexion.sin_salida", { title: ty.title, type: a.type }) });
    return setStore({ lastError: t("bloques.conexion.varias_salidas", { title: ty.title, type: a.type }) });
  };

  useEffect(() => {
    const down = (ev: PointerEvent) => {
      if (ev.button !== 0) return;
      const tg = ev.target as HTMLElement | null;
      if (!tg?.closest?.(".sock .dot")) return;
      const from = socketAt(ev.clientX, ev.clientY);
      if (!from) return;
      ev.preventDefault();
      ev.stopPropagation();                    // ni Excalidraw selecciona ni arrastra el bloque
      setMenu(null);
      const start = { x: ev.clientX, y: ev.clientY };
      setDrag({ from, start, at: start, hover: null });
      const move = (e: PointerEvent) => {
        const hover = socketAt(e.clientX, e.clientY);
        setDrag({ from, start, at: { x: e.clientX, y: e.clientY },
                  hover: hover && hover.side !== from.side && hover.block !== from.block ? hover : null });
      };
      const up = (e: PointerEvent) => {
        window.removeEventListener("pointermove", move, true);
        window.removeEventListener("pointerup", up, true);
        setDrag(null);
        if (Math.hypot(e.clientX - start.x, e.clientY - start.y) < 4) return;
        const target = socketAt(e.clientX, e.clientY);
        const p = viewportCoordsToSceneCoords({ clientX: e.clientX, clientY: e.clientY }, api.getAppState());
        const over = [...api.getSceneElements()].reverse().find((el) => isNodeEl(el)
          && p.x >= el.x && p.x <= el.x + el.width && p.y >= el.y && p.y <= el.y + el.height) ?? null;
        finish(from, target, { x: e.clientX, y: e.clientY }, over);
      };
      window.addEventListener("pointermove", move, true);
      window.addEventListener("pointerup", up, true);
    };
    window.addEventListener("pointerdown", down, true);
    return () => window.removeEventListener("pointerdown", down, true);
  });

  // El menú se cierra con Esc o con un clic fuera.
  useEffect(() => {
    if (!menu) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setMenu(null); };
    const click = (e: PointerEvent) => { if (!(e.target as HTMLElement)?.closest?.(".port-menu")) setMenu(null); };
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", click, true);
    return () => { window.removeEventListener("keydown", key, true); window.removeEventListener("pointerdown", click, true); };
  }, [menu]);

  // Motivo de cada flecha no válida, junto a su punto medio.
  const st = api.getAppState();
  const z = st.zoom.value;
  const view = (x: number, y: number) => ({ x: (x + st.scrollX) * z, y: (y + st.scrollY) * z });
  const labels = problems.flatMap((pr) => {
    const a = api.getSceneElements().find((e) => e.id === pr.arrow) as
      (ExcalidrawElement & { points: readonly (readonly [number, number])[] }) | undefined;
    if (!a) return [];
    const mid = a.points[Math.floor(a.points.length / 2)];
    return [{ id: pr.arrow, reason: pr.reason, ...view(a.x + mid[0], a.y + mid[1]) }];
  });

  // Nombre del puerto sobre la conexión del ratón o seleccionada, del color de su tipo.
  type Arrow = ExcalidrawElement & { points: readonly (readonly [number, number])[]; startBinding?: { elementId: string } | null };
  const wires = (api.getSceneElements().filter(isConnection) as Arrow[]).flatMap((a) => {
    const src = a.startBinding && elById(a.startBinding.elementId);
    const dst = (a as { endBinding?: { elementId: string } | null }).endBinding;
    if (dst && isFolderEl(elById(dst.elementId) ?? ({} as ExcalidrawElement))) return [];   // FolderArrows
    const port = (a.customData as { from?: string } | undefined)?.from;
    const type = src && port ? typeOf(src)?.outputs[port] : undefined;
    if (!type || problems.some((pr) => pr.arrow === a.id)) return [];
    if (a.id !== hovered && !st.selectedElementIds[a.id]) return [];
    const spot = labelSpot(a.points);
    // el nombre del puerto es un id: solo se traduce lo que se pinta (O15)
    return [{ id: a.id, name: tp(typeOf(src as ExcalidrawElement)?.pack, port!), color: portColor(type, ports), ...view(a.x + spot.x, a.y + spot.y) }];
  });

  const rect = (document.querySelector(".excalidraw") as HTMLElement | null)?.getBoundingClientRect();
  const local = (p: Pt) => ({ x: p.x - (rect?.left ?? 0), y: p.y - (rect?.top ?? 0) });

  return (
    <>
      <svg className="connect-layer" aria-hidden="true">
        {drag && (() => {
          const a = local(drag.start), b = local(drag.at);
          return <path d={`M${a.x} ${a.y} L${b.x} ${b.y}`} className={`connect-live${drag.hover ? " on" : ""}`}
                       style={{ "--c": portColor(drag.from.type, ports) } as CSSProperties} />;
        })()}
      </svg>
      {wires.map((w) => (
        <div key={w.id} className="wire-label" style={{ left: w.x, top: w.y, "--c": w.color } as CSSProperties}>{w.name}</div>
      ))}
      {labels.map((l) => (
        <div key={l.id} className="connect-problem" style={{ left: l.x, top: l.y }}>{l.reason}</div>
      ))}
      {menu && (() => {
        const p = local(menu.at);
        const dstTitle = typeOf(menu.dst)?.title ?? "";
        return (
          <div className="port-menu" style={{ left: p.x, top: p.y }} role="menu">
            <div className="q">{t("bloques.conexion.a_que_entrada", { title: dstTitle })}</div>
            {menu.options.map((o) => (
              <button key={o} type="button" role="menuitem" style={{ "--c": portColor(menu.type, ports) } as CSSProperties}
                      onClick={() => { addConnection(api, types, menu.src, menu.outPort, menu.dst, o); setMenu(null); }}>
                <i />{tp(typeOf(menu.dst)?.pack, o)}<em>{t("bloques.conexion.libre")}</em>
              </button>
            ))}
          </div>
        );
      })()}
    </>
  );
}
