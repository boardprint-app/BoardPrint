// Fusión de elementos que llegan del backend con los de la escena (plan §3, D69): mismo
// criterio que `scene.merge` del backend. Lo que no viene se queda en su sitio, lo nuevo va
// al final, y si todos llevan `index` (índice fraccionario de Excalidraw) se ordena por él,
// que es el orden de dibujo: así traer algo al frente en otra ventana se ve igual aquí.
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";

export function mergeElements(
  local: readonly ExcalidrawElement[],
  incoming: readonly ExcalidrawElement[],
): ExcalidrawElement[] {
  const out = [...local];
  const pos = new Map(out.map((e, i) => [e.id, i]));
  for (const e of incoming) {
    const i = pos.get(e.id);
    if (i === undefined) {
      pos.set(e.id, out.length);
      out.push(e);
    } else {
      out[i] = e; // lo que llegaba más viejo que lo local ya se ha descartado antes
    }
  }
  if (out.every((e) => typeof e.index === "string")) {
    // Estable: a igualdad de índice, el orden de antes. Comparación de texto, como Excalidraw.
    return out
      .map((e, i) => [e, i] as const)
      .sort(([a, i], [b, j]) => (a.index! < b.index! ? -1 : a.index! > b.index! ? 1 : i - j))
      .map(([e]) => e);
  }
  return out;
}
