// Repinta un componente con cada cambio de la escena, del desplazamiento o del zoom de
// Excalidraw, como mucho una vez por fotograma. Lo usan las capas que van encima del lienzo
// (hilos de los anclajes, propuestas sobre textos y formas).
import { useEffect, useState } from "react";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";

export function useSceneTick(api: ExcalidrawImperativeAPI) {
  const [, setTick] = useState(0);
  useEffect(() => {
    let raf = 0;
    const kick = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; setTick((t) => t + 1); });
    };
    const offChange = api.onChange(kick);
    const offScroll = api.onScrollChange(kick);
    return () => { offChange(); offScroll(); cancelAnimationFrame(raf); };
  }, [api]);
}
