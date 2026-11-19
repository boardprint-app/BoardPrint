// Anclajes (plan §3, D74, D140): un post-it o una foto se ancla a otro elemento (`customData.anchor` = su id),
// un hilo los une y, al mover el elemento, el post-it se mueve con él. Reglas puras, sin React
// ni Excalidraw: las usan la capa de hilos (AnchorLayer) y la pizarra (App).

export type Box = { x: number; y: number; width: number; height: number };
export type Pt = { x: number; y: number };
type El = Box & { id: string; isDeleted?: boolean; customData?: Record<string, unknown> };

// Lo que se ancla: post-its y fotos sueltas con su cinta (D140), y la tinta a la tarjeta que
// marca (D192), que la sigue igual pero sin hilo.
export const ANCHORED = new Set(["postit", "image", "ink"]);

export const anchorOf = (e: El): string | null => {
  const a = ANCHORED.has(String(e.customData?.kind)) ? e.customData?.anchor : null;
  return typeof a === "string" && a ? a : null;
};

// post-it → elemento al que va anclado (solo los anclados).
export function anchorMap(elements: readonly El[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const e of elements) {
    const a = !e.isDeleted && anchorOf(e);
    if (a) m.set(e.id, a);
  }
  return m;
}

// Se puede anclar `postit` a `target` si no es él mismo, `target` existe (y no está borrado) y
// seguir los anclajes desde `target` no vuelve a `postit` (un ciclo nunca se mueve bien).
export function canAnchor(postit: string, target: string, elements: readonly El[]): boolean {
  if (postit === target) return false;
  if (!elements.some((e) => e.id === target && !e.isDeleted)) return false;
  const anchors = anchorMap(elements);
  const seen = new Set<string>();
  for (let cur: string | undefined = target; cur && !seen.has(cur); cur = anchors.get(cur)) {
    if (cur === postit) return false;
    seen.add(cur);
  }
  return true;
}

// Al moverse unos elementos (`moved`: id → desplazamiento), sus post-its anclados, y los
// anclados a esos, se mueven lo mismo. Nunca los que se han movido ya por su cuenta (el
// usuario los arrastra a la vez), y un ciclo no entra en bucle.
export function followers(moved: ReadonlyMap<string, Pt>, anchors: ReadonlyMap<string, string>): Map<string, Pt> {
  const children = new Map<string, string[]>();
  for (const [p, t] of anchors) children.set(t, [...(children.get(t) ?? []), p]);
  const out = new Map<string, Pt>();
  const queue = [...moved.keys()];
  const seen = new Set(queue);
  while (queue.length) {
    const id = queue.shift()!;
    const d = moved.get(id) ?? out.get(id)!;
    for (const child of children.get(id) ?? []) {
      if (seen.has(child)) continue;
      seen.add(child);
      out.set(child, d);
      queue.push(child);
    }
  }
  return out;
}

// Desplazamientos entre dos fotos de posiciones (lo que no estaba antes no cuenta).
export function movedBetween(before: ReadonlyMap<string, Pt>, now: readonly El[]): Map<string, Pt> {
  const out = new Map<string, Pt>();
  for (const e of now) {
    const b = before.get(e.id);
    if (!b || e.isDeleted) continue;
    const dx = e.x - b.x, dy = e.y - b.y;
    if (dx || dy) out.set(e.id, { x: dx, y: dy });
  }
  return out;
}

// Punto del borde de `box` más cercano a `p` (o `p` si está dentro).
export function nearestPoint(box: Box, p: Pt): Pt {
  return {
    x: Math.min(Math.max(p.x, box.x), box.x + box.width),
    y: Math.min(Math.max(p.y, box.y), box.y + box.height),
  };
}

// El hilo une los bordes más cercanos del post-it y del elemento: sale del punto del post-it
// más cercano al centro del elemento y llega al punto del elemento más cercano a ese. Si se
// tocan o están uno encima del otro, no hay hilo.
export function thread(postit: Box, target: Box): { from: Pt; to: Pt } | null {
  const c = { x: target.x + target.width / 2, y: target.y + target.height / 2 };
  const from = nearestPoint(postit, c);
  const to = nearestPoint(target, from);
  if (Math.hypot(to.x - from.x, to.y - from.y) < 1) return null;
  return { from, to };
}

// El elemento de más arriba bajo un punto de la escena (para soltar la cinta), sin `skip`.
export function elementAt<T extends El>(elements: readonly T[], p: Pt, skip: (e: T) => boolean): T | null {
  for (let i = elements.length - 1; i >= 0; i--) {
    const e = elements[i];
    if (e.isDeleted || skip(e)) continue;
    const x0 = Math.min(e.x, e.x + e.width), x1 = Math.max(e.x, e.x + e.width);
    const y0 = Math.min(e.y, e.y + e.height), y1 = Math.max(e.y, e.y + e.height);
    if (p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1) return e;
  }
  return null;
}
