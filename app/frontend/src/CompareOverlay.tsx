// Marcas de *Comparar* en la pizarra (plan §3, D76): al comparar una versión con la pizarra de
// ahora, cada cambio se recuadra (añadido, modificado, menor) y lo quitado sale como fantasma
// en su sitio de entonces. El cambio elegido en la lista se resalta.
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { useStore } from "./store";
import { useSceneTick } from "./useSceneTick";
import { elementName } from "./versions";

export function CompareOverlay({ api }: { api: ExcalidrawImperativeAPI }) {
  useSceneTick(api);
  const { compare, compareFocus, types } = useStore();
  if (!compare || compare.b !== "now") return null;
  const st = api.getAppState();
  const z = st.zoom.value;
  const byId = new Map(api.getSceneElements().map((e) => [e.id, e]));
  return (
    <div className="cmp-layer" aria-hidden="true">
      {compare.changes.map((c) => {
        const now = byId.get(c.id);
        const b = c.change === "removed" || !now ? c.element : now;
        const x = (Math.min(b.x, b.x + b.width) + st.scrollX) * z;
        const y = (Math.min(b.y, b.y + b.height) + st.scrollY) * z;
        const w = Math.abs(b.width) * z, h = Math.abs(b.height) * z;
        return (
          <div key={c.id} className={`cmp-box cmp-${c.change}${compareFocus === c.id ? " focus" : ""}`}
               style={{ left: x - 5, top: y - 5, width: w + 10, height: h + 10 }}>
            {c.change === "removed" && <span className="cmp-ghost">{elementName(c.element, types)}</span>}
          </div>
        );
      })}
    </div>
  );
}
