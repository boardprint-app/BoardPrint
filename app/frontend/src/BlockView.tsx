// Contenido de un bloque ejecutable, pintado dentro de un elemento `embeddable` (plan §3, D77).
// Se usa con un clic, como una ventana: la cabecera deja pasar el ratón al lienzo (por ella se
// selecciona y se arrastra) y el cuerpo lo recibe (campos, botones y texto seleccionable, D55).
// El papel y los colores salen del skin (skins.css).
//
// Tarjeta elegida en el artifact «Bloques FF 4.4» (D96): cabecera · franja de enchufes ·
// cuerpo · pie con el sello del estado. Mientras corre, una barra fina en el borde de la
// cabecera y el mensaje con Cancelar en ella: nada se mueve, así los enchufes siguen a la
// misma altura (ports.ts) y las conexiones no se descuelgan.
import { useLayoutEffect, useRef, useState, type CSSProperties, type WheelEvent } from "react";
import { getStore, setStore, useStore } from "./store";
import { send } from "./socket";
import { apiFetch } from "./auth";
import { t } from "./i18n";
import { tp } from "./packI18n";
import { blockHeight, contentHeight, wheelOnCanvas, wheelToCanvas } from "./block";
import { proposalFor } from "./proposal";
import { ProposalTab } from "./ProposalTab";
import { ProposalList } from "./ProposalList";
import { BlockOutputs } from "./BlockOutputs";
import { HEAD_H, portColor, portList, SOCKET_H, socketY } from "./ports";
import { connectorPart, hasPanel, PackFrame } from "./PackFrame";
import { BlockParams, useParamDraft } from "./BlockParams";
import { ControlFields } from "./GenericControls";
import { layout } from "./controls";

// Sello al pie (2A). Ejecutando no lleva sello: lo dice la barra.
const STAMPED = new Set(["nunca", "incompleto", "error", "al_dia", "desactualizado", "no_disponible", "en_cola"]);
const stamp = (status: string) => (STAMPED.has(status) ? t(`bloques.sello.${status}`) : "");

// Último alto que se puso sola cada tarjeta (block.ts `blockHeight`): fuera del componente
// para que sobreviva a que Excalidraw la desmonte al salir de la vista.
const FITTED = new Map<string, number>();
const SHRINK_DELAY = 300;   // ms

// Excalidraw solo desplaza o hace zoom si la rueda llega a su canvas: se la reenvía.
// Dentro de un hueco con scroll (las pestañas de salidas), manda ese hueco mientras pueda moverse.
function forwardWheel(ev: WheelEvent<HTMLDivElement>) {
  const pane = (ev.target as HTMLElement).closest?.(".bo-pane") as HTMLElement | null;
  if (!wheelToCanvas(ev, pane ?? ev.currentTarget)) return;
  wheelOnCanvas(ev.currentTarget, {
    deltaX: ev.deltaX, deltaY: ev.deltaY, deltaMode: ev.deltaMode,
    clientX: ev.clientX, clientY: ev.clientY,
    ctrlKey: ev.ctrlKey, metaKey: ev.metaKey, shiftKey: ev.shiftKey, altKey: ev.altKey,
  });
}

type Props = {
  id: string;
  blockType: string;
  height: number;                             // alto del elemento en la escena
  onHeight: (id: string, height: number) => void;
};

export function BlockView({ id, blockType, height, onHeight }: Props) {
  const { blocks, types, proposals, run, ports, packIssues, connectorInfo } = useStore();
  const prop = proposalFor(proposals, id);
  const st = blocks[id];
  const ty = types[blockType];
  const { params, setDraft, commit } = useParamDraft(id, st);
  const inner = useRef<HTMLDivElement>(null);

  // El bloque sigue a su contenido (sin barra de scroll dentro): crece al aparecer las salidas
  // o un error y vuelve a encoger al irse. Más alto, si el usuario lo estira, sí (block.ts).
  // Encoger espera un momento: al volver a montarse (Excalidraw desmonta lo que sale de la
  // vista) la interfaz del paquete y las miniaturas tardan en medir, y la tarjeta no debe
  // encoger y volver a crecer cada vez.
  useLayoutEffect(() => {
    const box = inner.current;
    if (!box) return;
    let timer = 0;
    const fit = (now: boolean) => {
      const need = blockHeight(height, box.offsetHeight, FITTED.get(id) ?? null);
      if (need === contentHeight(box.offsetHeight)) {
        if (need < height && !now) {
          window.clearTimeout(timer);
          timer = window.setTimeout(() => fit(true), SHRINK_DELAY);
          return;
        }
        FITTED.set(id, need);
      }
      if (need !== height) onHeight(id, need);
    };
    fit(false);
    const ro = new ResizeObserver(() => fit(false));
    ro.observe(box);
    return () => { ro.disconnect(); window.clearTimeout(timer); };
  }, [id, height, onHeight]);

  if (!ty) {
    // Un bloque de un paquete que no está (P13): se queda con todo, sin ejecutar ni editar.
    const missing = packIssues.missing.find((p) => p.blocks.includes(id));
    return (
      <div className={`block${missing ? " bs-no_instalado" : ""}`}>
        <div className="block-inner" ref={inner}>
          <div className="block-head" style={{ height: HEAD_H }}>
            <span className="block-title">{missing ? t("bloques.tarjeta.paquete_no_instalado") : t("bloques.tarjeta.tipo_desconocido")}</span>
          </div>
          <div className="block-body">
            <code>{blockType}</code>
            {missing && (
              <p className="block-missing">
                {t("bloques.tarjeta.falta")} <b>{missing.id}</b>{missing.version && ` ${missing.version}`}. {t("bloques.tarjeta.se_conservan")}
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }
  const status = st?.status ?? "nunca";
  // La interfaz propia del paquete (PLAN_PAQUETES §5, P24) sustituye a los controles
  // genéricos; cabecera, enchufes, Ejecutar, el error y el sello siguen siendo de la app (D77).
  // Los genéricos, los que declara `pack.view` (P52): Parámetros encima de Ejecutar, los demás
  // debajo y en su orden.
  const ownUi = ty.view?.card === "ui";
  const { above, below } = layout(ty.view?.card);
  const stale = status === "desactualizado";
  // La parte del conector (P41): su interfaz, debajo de la del bloque (destino, documento,
  // *Traer*, *Fijar*); y su panel, el de *Traer*.
  const conCard = connectorPart(ty, connectorInfo, "card");
  const conPanel = connectorPart(ty, connectorInfo, "panel");

  const running = run?.block === id ? run : null;
  const ins = portList(ty.inputs);
  const outs = portList(ty.outputs);
  const sock = (side: "in" | "out", p: { name: string; type: string }, i: number, free: boolean) => {
    const opt = side === "in" && !!ty.optional?.includes(p.name);
    return (
      <div key={`${side}:${p.name}`} className={`sock sock-${side}${free ? " free" : ""}${opt ? " opt" : ""}`}
           data-port={p.name} data-type={p.type}
           style={{ top: socketY(i) - SOCKET_H / 2, height: SOCKET_H, "--c": portColor(p.type, ports) } as CSSProperties}>
        <b className="dot" />
        <span className="tip" role="tooltip">
          <b>{tp(ty.pack, p.name)}</b> {side === "in" ? (opt ? t("bloques.tarjeta.entrada_opcional") : t("bloques.tarjeta.entrada")) : t("bloques.tarjeta.salida")} · {ports[p.type]?.label ?? p.type}
        </span>
      </div>
    );
  };

  return (
    <div className={`block bs-${status}${prop ? " prop" : ""}${prop?.change.delete ? " prop-delete" : ""}`} data-block={id}>
      <div className="block-inner" ref={inner}>
        <div className="block-head" style={{ height: HEAD_H }}>
          <span className="block-title">{ty.title}</span>
          {prop && <span className="badge badge-prop">{t("bloques.tarjeta.propuesta")}</span>}
          {running && (
            <span className="block-running">
              {running.message ? tp(ty.pack, running.message) : t("bloques.tarjeta.calculando")}
              {running.fraction !== null && ` · ${Math.round(running.fraction * 100)} %`}
              <button className="block-cancel" type="button" onClick={() => send({ type: "cancel" })}>{t("bloques.tarjeta.cancelar")}</button>
            </span>
          )}
          {running && (
            <span className={`block-bar${running.fraction === null ? " indet" : ""}`} aria-hidden="true">
              <i style={running.fraction === null ? undefined : { width: `${running.fraction * 100}%` }} />
            </span>
          )}
        </div>
        {/* Las teclas no llegan a los atajos de Excalidraw, y cortar o pegar en un campo no
            toca la pizarra (Excalidraw escucha en document). Copiar lo decide App (D85). */}
        <div className="block-body"
             onKeyDown={(e) => e.stopPropagation()}
             onCut={(e) => e.stopPropagation()}
             onPaste={(e) => e.stopPropagation()}
             onWheel={forwardWheel}>
          {ownUi && <PackFrame id={id} blockType={blockType} surface="card" />}
          {above.includes("params") && (
            <BlockParams ty={ty} st={st} params={params} setDraft={setDraft} commit={commit} prop={prop} />
          )}
          {conCard && <PackFrame id={id} blockType={blockType} surface="card" part="connector" />}
          {/* Una ejecución por proyecto (D89): mientras dura, Ejecutar no se puede en ningún
              bloque; el que corre enseña su progreso y Cancelar (mata su proceso, D92). */}
          <div className="block-actions">
            <button className="block-run"
                    disabled={run !== null || status === "incompleto" || status === "no_disponible"}
                    onClick={() => send({ type: "run", block: id })}>
              {t("bloques.tarjeta.ejecutar")}
            </button>
            {hasPanel(ty) && (
              <button className="block-panel" type="button" onClick={() => setStore({ packPanel: id })}>
                {t("bloques.tarjeta.editar")}
              </button>
            )}
          </div>
          {status === "no_disponible" && ty.requires.length > 0 && (
            ty.connector && ty.requires.includes(ty.connector) ? <OpenConnector id={ty.connector} /> : (
              <div className="block-note">{t("bloques.tarjeta.necesita", { names: ty.requires.join(", ") })}</div>
            )
          )}
          {st?.error && (
            <div className="block-error">
              {tp(ty.pack, st.error)}
              {/* Confirmación (D112): relanza el bloque una vez con esa acción. «Ver cambios»
                  (D116, acción `pull`) no relanza: abre el panel, donde está la parte de Traer
                  de su conector (P41). */}
              {st.error_action && (st.error_action.action !== "pull" || conPanel) && (
                <button type="button" className="block-confirm" disabled={run !== null}
                        onClick={() => st.error_action!.action === "pull"
                          ? setStore({ packPanel: id })
                          : send({ type: "run", block: id, options: { [st.error_action!.action]: true } })}>
                  {tp(ty.pack, st.error_action.label)}
                </button>
              )}
            </div>
          )}
          {below.map((c) => c === "results" ? (st?.outputs && (
            <BlockOutputs key={c} id={id} outputs={st.outputs} stale={stale}
                          locks={(params.locks as Record<string, number> | undefined) ?? {}} />
          )) : <ControlFields key={c} control={c} outputs={st?.outputs ?? null} stale={stale} size="card" pack={ty.pack} />)}
        </div>
        {stamp(status) && <div className="block-foot"><span className="stamp">{stamp(status)}</span></div>}
      </div>
      {/* Enchufes sobre el borde, encima de todo (no ocupan sitio dentro de la tarjeta). */}
      <div className="block-socks">
        {ins.map((p, i) => sock("in", p, i, !st?.inputs?.[p.name]))}
        {outs.map((p, i) => sock("out", p, i, false))}
      </div>
      {/* Un parámetro lista de nodos (el `arbol`, D177) va por nodo dentro de la pestaña. */}
      {prop && <ProposalTab p={prop}><ProposalList p={prop} label={(n) => ty?.params[n]?.label || n} /></ProposalTab>}
    </div>
  );
}

/** «Abrir Fusion» (D106) en un bloque que necesita su conector: lo lanza como un doble clic y
 *  el bloque pasa solo a ejecutable cuando el programa responde (aviso `connectors` del
 *  backend). Vale para cualquier conector: el nombre es el que da el backend. */
function OpenConnector({ id }: { id: string }) {
  const con = useStore().connectors[id];
  const name = con?.name ?? id;
  const [error, setError] = useState<string | null>(null);
  const launching = !!con?.launching;
  // Arrancando en todos los bloques de la ventana a la vez; el vigilante del backend lo
  // confirma (y avisa a las otras ventanas) en unos segundos.
  const mark = (on: boolean) => {
    const c = getStore().connectors;
    setStore({ connectors: { ...c, [id]: { ...(c[id] ?? { name, available: false }), launching: on } } });
  };
  const open = async () => {
    setError(null);
    mark(true);
    const r = await apiFetch(`/api/connectors/${encodeURIComponent(id)}/launch`, { method: "POST" });
    if (!r.ok) {
      mark(false);
      setError((await r.json().catch(() => null))?.detail ?? t("bloques.conector.error_abrir", { name }));
    }
  };
  return (
    <div className="block-note block-connector">
      {launching ? (
        <span>{t("bloques.conector.abriendo", { name })}</span>
      ) : (
        <>
          <span>{t("bloques.conector.necesita_abierto", { name })}</span>
          <button className="block-open-connector" onClick={open}>{t("bloques.conector.abrir", { name })}</button>
        </>
      )}
      {error && <div className="block-error">{error}</div>}
    </div>
  );
}
