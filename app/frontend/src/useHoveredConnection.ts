// Conexión bajo el ratón (R37): el nombre del puerto y la etiqueta de una flecha a una carpeta
// solo salen al pasar el ratón por la línea (o con la flecha seleccionada); el resto del tiempo
// la línea, del color de su tipo, ya dice lo que une.
import { useEffect, useState } from "react";
import { viewportCoordsToSceneCoords } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { isConnection } from "./connections";
import { distToPolyline } from "./ports";

const TOLERANCE = 8;      // px de pantalla alrededor de la línea

type Arrow = { id: string; x: number; y: number; points: readonly (readonly [number, number])[] };

export function useHoveredConnection(api: ExcalidrawImperativeAPI): string | null {
  const [hovered, setHovered] = useState<string | null>(null);
  useEffect(() => {
    let frame = 0;
    const move = (ev: PointerEvent) => {
      const { clientX, clientY } = ev;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const st = api.getAppState();
        const p = viewportCoordsToSceneCoords({ clientX, clientY }, st);
        const tol = TOLERANCE / st.zoom.value;
        let best: string | null = null, bestD = tol;
        for (const a of api.getSceneElements().filter(isConnection) as unknown as Arrow[]) {
          const d = distToPolyline(a.points, a, p);
          if (d <= bestD) { best = a.id; bestD = d; }
        }
        setHovered(best);
      });
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => { cancelAnimationFrame(frame); window.removeEventListener("pointermove", move); };
  }, [api]);
  return hovered;
}
