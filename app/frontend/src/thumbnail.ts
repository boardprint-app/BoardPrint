// Miniatura de la pizarra para la pantalla de inicio (plan §2, D63): un PNG pequeño que la
// interfaz genera con Excalidraw y guarda el backend en board/thumbnail.png. Sale con el skin
// (D79): el dibujo sin fondo, con la tinta del tema oscuro si el skin lo es, sobre su color liso.
// Las tarjetas (post-its y bloques) son DOM y Excalidraw no las exporta: se dibujan aquí encima,
// con los colores del skin, después del filtro de la tinta (que las invertiría).
import { exportToCanvas, getCommonBounds } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { apiFetch } from "./auth";
import type { Skin } from "./skins";
import { getStore } from "./store";
import { drawInk } from "./inkCanvas";
import { cardInkFilter, skinInkFilter } from "./inkView";

const MAX_SIDE = 480;
const PADDING = 10;

type Card = { kind?: string; postitKind?: string; text?: string; blockType?: string; path?: string };

function cssVar(name: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Pinta las tarjetas (DOM, que Excalidraw no exporta) con `(x0, y0)` de la escena en la esquina
 * del lienzo: el recuadro con su título, su texto o el nombre del archivo. También para `ver_zona`. */
export function drawCards(ctx: CanvasRenderingContext2D, cards: ExcalidrawElement[], x0: number, y0: number, scale: number) {
  const { types } = getStore();
  ctx.save();
  ctx.filter = "none";
  for (const e of cards) {
    const cd = (e.customData ?? {}) as Card;
    const x = (e.x - x0) * scale, y = (e.y - y0) * scale, w = e.width * scale, h = e.height * scale;
    const isPostit = cd.kind === "postit";
    const kind = cd.postitKind ?? "nota";
    ctx.fillStyle = isPostit ? cssVar(`--pi-${kind}`, "#fff1a8") : cssVar("--paper", "#ffffff");
    ctx.shadowColor = "rgba(0,0,0,.35)";
    ctx.shadowBlur = 3 * scale;
    ctx.shadowOffsetY = 1.5 * scale;
    ctx.fillRect(x, y, w, h);
    ctx.shadowColor = "transparent";
    if (isPostit) {
      ctx.strokeStyle = cssVar(`--pi-${kind}-b`, "#c9a900");
      ctx.lineWidth = Math.max(1, scale);
      ctx.strokeRect(x, y, w, h);
    }
    // Texto: lo que quepa, en la fuente de la pizarra.
    const size = Math.max(5, 15 * scale);
    ctx.fillStyle = isPostit ? cssVar("--pi-fg", "#1e1e1e") : cssVar("--paper-fg", "#1e1e1e");
    ctx.font = `${size}px Excalifont, "Segoe Print", cursive`;
    const text = isPostit ? cd.text ?? "" : types[cd.blockType ?? ""]?.title ?? cd.blockType
      ?? (cd.path ?? "").split(/[\\/]/).pop() ?? "";
    const pad = 10 * scale;
    let ty = y + pad + size;
    for (const line of wrap(ctx, text, w - 2 * pad)) {
      if (ty > y + h - pad / 2) break;
      ctx.fillText(line, x + pad, ty);
      ty += size * 1.3;
    }
  }
  ctx.restore();
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number) {
  const out: string[] = [];
  for (const para of text.split("\n")) {
    let line = "";
    for (const word of para.split(" ")) {
      const next = line ? `${line} ${word}` : word;
      if (ctx.measureText(next).width > width && line) { out.push(line); line = word; } else line = next;
    }
    out.push(line);
  }
  return out;
}

export async function saveThumbnail(api: ExcalidrawImperativeAPI, projectId: string, skin: Skin) {
  // Se copia la escena en el momento: la exportación es asíncrona y la pizarra puede cerrarse.
  const all = api.getSceneElements();
  if (!all.length) return;
  const cards = all.filter((e) => e.type === "embeddable");
  // Las tarjetas cuentan para el encuadre, pero las pinta drawCards: en el lienzo, invisibles.
  const elements = all.map((e) => (e.type === "embeddable" ? { ...e, opacity: 0 } : e));
  const appState = { ...api.getAppState(), exportBackground: false, exportWithDarkMode: skin.dark };
  const files = api.getFiles();
  try {
    const drawing = await exportToCanvas({
      elements, appState, files, maxWidthOrHeight: MAX_SIDE, exportPadding: PADDING,
    });
    const out = document.createElement("canvas");
    out.width = drawing.width;
    out.height = drawing.height;
    const ctx = out.getContext("2d")!;
    ctx.fillStyle = skin.base;
    ctx.fillRect(0, 0, out.width, out.height);
    if (skin.inkFilter) ctx.filter = skin.inkFilter;
    ctx.drawImage(drawing, 0, 0);
    const [minX, minY, maxX] = getCommonBounds(elements);
    const scale = drawing.width / (maxX - minX + 2 * PADDING);
    drawCards(ctx, cards, minX - PADDING, minY - PADDING, scale);
    drawInk(ctx, all, minX - PADDING, minY - PADDING, scale, skinInkFilter(skin), cardInkFilter(skin));   // encima (D193)
    const blob = await new Promise<Blob | null>((ok) => out.toBlob(ok, "image/png"));
    if (!blob) return;
    await apiFetch(`/api/projects/${encodeURIComponent(projectId)}/thumbnail`, {
      method: "PUT",
      headers: { "Content-Type": "image/png" },
      body: blob,
    });
  } catch {
    // Sin miniatura la pantalla de inicio pinta su dibujo por defecto: no merece un aviso.
  }
}
