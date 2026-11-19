// La tinta en un PNG (plan D193): `ver_zona` y la miniatura la pintan **después** de las
// tarjetas, como se ve en la pizarra. Misma transformación que la exportación (`(x0, y0)` de la
// escena en la esquina, `scale`), el color con el filtro del skin, su opacidad y el subrayador
// multiplicando (o aclarando sobre lo oscuro, `surfacePaint`). Sin el grano del rotulador: a ese tamaño no se ve.
import { inkStroke } from "./inkView";

type El = Parameters<typeof inkStroke>[0];

export function drawInk(ctx: CanvasRenderingContext2D, elements: readonly El[], x0: number, y0: number,
                        scale: number, filter: string | null | undefined, cardFilter: string | null | undefined) {
  ctx.save();
  ctx.filter = "none";
  ctx.setTransform(scale, 0, 0, scale, -x0 * scale, -y0 * scale);
  for (const e of elements) {
    const s = inkStroke(e, filter, cardFilter);
    if (!s || !s.d) continue;
    ctx.globalAlpha = s.opacity;
    ctx.globalCompositeOperation = s.blend === "normal" ? "source-over" : s.blend;
    ctx.fillStyle = s.color;
    ctx.fill(new Path2D(s.d));
  }
  ctx.restore();
}
