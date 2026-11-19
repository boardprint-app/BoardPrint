// Capa de hilos (plan §3, D74): un SVG encima del lienzo que pinta el hilo discontinuo de cada
// post-it anclado a su elemento, y el hilo provisional mientras se arrastra la cinta. No es
// parte de la escena: sigue el desplazamiento y el zoom de Excalidraw y deja pasar el ratón.
// La misma capa pintará los fantasmas y las marcas de diff (pasos 6 y 7); la tinta la pinta su
// hermana InkLayer (FF 4.9).
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { useSceneTick } from "./useSceneTick";
import { anchorOf, thread, type Box, type Pt } from "./anchors";
import { filteredOut, type PostitData } from "./postit";
import { useStore } from "./store";
import { isInk } from "./ink";

// Arrastre de la cinta en curso: de qué post-it, dónde está el ratón (en la escena) y sobre
// qué elemento se soltaría (null: en vacío, desancla; `bad`: no se puede anclar ahí).
export type AnchorDrag = { postit: string; at: Pt; target: string | null; bad: boolean };

export function AnchorLayer({ api, drag }: { api: ExcalidrawImperativeAPI; drag: AnchorDrag | null }) {
  const { postitFilter } = useStore();
  useSceneTick(api);

  const st = api.getAppState();
  const z = st.zoom.value;
  const v = (p: Pt) => ({ x: (p.x + st.scrollX) * z, y: (p.y + st.scrollY) * z });
  const els = api.getSceneElements();
  const byId = new Map(els.map((e) => [e.id, e]));
  const isHidden = (e: { customData?: unknown }) => {
    const cd = e.customData as PostitData | undefined;
    return cd?.kind === "postit" && filteredOut(postitFilter, cd);
  };

  const lines: { id: string; from: Pt; to: Pt }[] = [];
  for (const e of els) {
    const anchor = anchorOf(e as Box & { id: string; customData?: Record<string, unknown> });
    if (!anchor || isHidden(e) || drag?.postit === e.id || isInk(e)) continue; // la tinta, sin hilo (D192)
    const t = byId.get(anchor);
    if (!t || isHidden(t)) continue;
    const seg = thread(e as Box, t as Box);
    if (seg) lines.push({ id: e.id, from: v(seg.from), to: v(seg.to) });
  }

  let live: { from: Pt; to: Pt; box: Box | null; bad: boolean } | null = null;
  if (drag) {
    const p = byId.get(drag.postit);
    const t = drag.target ? byId.get(drag.target) : undefined;
    if (p) {
      const from = v({ x: p.x + p.width / 2, y: p.y });
      const box = t ? { ...v(t), width: t.width * z, height: t.height * z } : null;
      live = { from, to: v(drag.at), box, bad: drag.bad };
    }
  }

  return (
    <svg className="anchor-layer" aria-hidden="true">
      {lines.map((l) => (
        <g key={l.id}>
          <line x1={l.from.x} y1={l.from.y} x2={l.to.x} y2={l.to.y} className="anchor-thread" />
          <circle cx={l.to.x} cy={l.to.y} r={3.5} className="anchor-dot" />
        </g>
      ))}
      {live && (
        <g className={live.bad ? "anchor-live bad" : "anchor-live"}>
          {live.box && <rect x={live.box.x - 4} y={live.box.y - 4} width={live.box.width + 8}
                             height={live.box.height + 8} rx={6} className="anchor-target" />}
          <line x1={live.from.x} y1={live.from.y} x2={live.to.x} y2={live.to.y} className="anchor-thread" />
          <circle cx={live.to.x} cy={live.to.y} r={4.5} className="anchor-dot" />
        </g>
      )}
    </svg>
  );
}
