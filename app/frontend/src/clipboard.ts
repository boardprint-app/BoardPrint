// Copiar tarjetas (plan §3, D85): Ctrl+C con un bloque seleccionado copia el bloque con sus
// parámetros, que no viven en el elemento sino en el estado de los bloques. Se escribe el mismo
// formato que Excalidraw (`excalidraw/clipboard`), así que su pegar lo entiende, en esta pizarra
// o en la de otro proyecto; el backend pasa `customData.params` al bloque nuevo y lo quita.

type El = {
  id: string;
  type: string;
  isDeleted?: boolean;
  containerId?: string | null;
  frameId?: string | null;
  customData?: Record<string, unknown>;
};

const isBlock = (e: El) => e.type === "embeddable" && e.customData?.kind === "block";

// Lo seleccionado (con el texto ligado de sus contenedores y lo que haya dentro de un marco
// seleccionado, como Excalidraw), o `null` si no hay ningún bloque: entonces copia Excalidraw.
export function cardsClipboard(
  elements: readonly El[],
  selected: ReadonlySet<string>,
  paramsOf: (id: string) => Record<string, unknown> | null | undefined,
): string | null {
  const picked = elements.filter((e) => !e.isDeleted && (selected.has(e.id)
    || (!!e.containerId && selected.has(e.containerId))
    || (!!e.frameId && selected.has(e.frameId))));
  if (!picked.some(isBlock)) return null;
  const ids = new Set(picked.map((e) => e.id));
  const out = picked.map((e) => {
    let c: El = e.frameId && !ids.has(e.frameId) ? { ...e, frameId: null } : e;
    const params = isBlock(e) ? paramsOf(e.id) : null;
    if (params) c = { ...c, customData: { ...c.customData, params } };
    return c;
  });
  return JSON.stringify({ type: "excalidraw/clipboard", elements: out, files: {} });
}
