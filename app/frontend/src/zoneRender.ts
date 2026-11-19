// La imagen de `ver_zona` (plan §4, D171): esta ventana pinta lo pedido con Excalidraw a un PNG
// de hasta 1568 px de lado y lo devuelve por el WebSocket (`zone_image`), o el motivo si no
// puede. Sale como la ve el usuario, con el skin. Los bloques, post-its y tarjetas de archivo son
// DOM (`embeddable` pintados por React) y Excalidraw no los exporta: se dibuja encima su recuadro
// con su título o su texto (`drawCards`, el de la miniatura) y, en las fotos pegadas, la foto.
// Con *Excluir adjuntos* las fotos pegadas ni se pintan (`zoneSelection`). La foto de un post-it
// no sale nunca: solo su texto.
import { exportToCanvas, getCommonBounds } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import type { ExcalidrawElement } from "@excalidraw/excalidraw/element/types";
import { imageUrl } from "./cardActions";
import type { Skin } from "./skins";
import { send } from "./socket";
import { drawCards } from "./thumbnail";
import { drawInk } from "./inkCanvas";
import { cardInkFilter, skinInkFilter } from "./inkView";
import { isPastedImage, MAX_SIDE, PADDING, zoneCrop, zoneScale, zoneSelection, type Rect,
         type ZoneRequest } from "./zone";

async function drawPhotos(ctx: CanvasRenderingContext2D, photos: ExcalidrawElement[], crop: Rect, scale: number) {
  for (const e of photos) {
    const file = (e.customData?.image as { file?: string } | undefined)?.file;
    if (!file) continue;
    const img = new Image();
    img.src = imageUrl(file);
    try {
      await img.decode();
    } catch {
      continue;                    // sin la foto queda su recuadro: no tumba la zona entera
    }
    ctx.drawImage(img, (e.x - crop.x) * scale, (e.y - crop.y) * scale, e.width * scale, e.height * scale);
  }
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).replace(/^data:[^,]*,/, ""));
    r.onerror = () => fail(r.error);
    r.readAsDataURL(blob);
  });
}

export async function renderZone(api: ExcalidrawImperativeAPI, req: ZoneRequest, skin: Skin): Promise<string> {
  const picked = zoneSelection(api.getSceneElements(), req);
  if (!picked.length) {
    throw new Error(req.rect ? "no hay nada en ese recuadro de la pizarra"
                             : "ninguno de esos elementos se puede pintar");
  }
  const cards = picked.filter((e) => e.type === "embeddable");
  // Las tarjetas cuentan para el encuadre, pero las pinta drawCards: en el lienzo, invisibles.
  const elements = picked.map((e) => (e.type === "embeddable" ? { ...e, opacity: 0 } : e));
  const bounds = getCommonBounds(elements);
  const crop = zoneCrop(req, bounds);
  const maxSide = req.maxSide ?? MAX_SIDE;
  const scale = zoneScale(crop, bounds, maxSide);
  const drawing = await exportToCanvas({
    elements, files: api.getFiles(), exportPadding: PADDING,
    appState: { ...api.getAppState(), exportBackground: false, exportWithDarkMode: skin.dark },
    getDimensions: (w: number, h: number) => ({ width: w * scale, height: h * scale, scale }),
  });
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.min(maxSide, Math.round(crop.width * scale)));
  out.height = Math.max(1, Math.min(maxSide, Math.round(crop.height * scale)));
  const ctx = out.getContext("2d")!;
  ctx.fillStyle = skin.base;
  ctx.fillRect(0, 0, out.width, out.height);
  if (skin.inkFilter) ctx.filter = skin.inkFilter;
  ctx.drawImage(drawing, (bounds[0] - PADDING - crop.x) * scale, (bounds[1] - PADDING - crop.y) * scale);
  ctx.filter = "none";
  drawCards(ctx, cards, crop.x, crop.y, scale);
  await drawPhotos(ctx, cards.filter(isPastedImage), crop, scale);
  // La tinta encima de las tarjetas (D193): toda la del recuadro, también la que no se pidió por
  // id (la marca de un bloque pedido va anclada a él, pero es otro elemento).
  drawInk(ctx, api.getSceneElements(), crop.x, crop.y, scale, skinInkFilter(skin), cardInkFilter(skin));
  const blob = await new Promise<Blob | null>((ok) => out.toBlob(ok, "image/png"));
  if (!blob) throw new Error("el navegador no ha podido hacer el PNG");
  return toBase64(blob);
}

/** Contesta a un `zone_request`: la imagen o el motivo, nunca nada (el backend espera 15 s). */
export async function answerZone(api: ExcalidrawImperativeAPI, req: ZoneRequest, skin: Skin) {
  try {
    send({ type: "zone_image", id: req.id, png: await renderZone(api, req, skin) });
  } catch (exc) {
    send({ type: "zone_image", id: req.id, error: exc instanceof Error ? exc.message : String(exc) });
  }
}
