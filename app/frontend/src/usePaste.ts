// Ctrl+V en la pizarra (D84, D137, D140, D152): una imagen sobre un post-it entra en él; en la
// pizarra, es una foto suelta; una URL sola, un enlace. Lo demás (texto, elementos copiados) lo
// pega Excalidraw. Se escucha antes que él, que pegaría la imagen sin guardarla. La foto y el
// enlace los crea la interfaz, para que entren en deshacer; la imagen la guarda el backend.
// Sacado de App.tsx tal cual.
import { useEffect, useRef } from "react";
import { CaptureUpdateAction, restoreElements, viewportCoordsToSceneCoords } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";
import { getStore } from "./store";
import { uploadImage } from "./cardActions";
import { filteredOut, type PostitData, type PostitPatch } from "./postit";
import { cardSkeleton, imageBox, linkDomain, linkTitle, linkWidth, pasteOnto, pastedUrl,
         type ImageRef } from "./paste";
import type { Pt } from "./anchors";

const newId = () => crypto.randomUUID().replace(/-/g, "").slice(0, 20);
// Tamaño natural de una imagen pegada (para que no se deforme); si el navegador no la lee, 4:3.
async function naturalSize(file: Blob): Promise<{ width: number; height: number }> {
  try {
    const bmp = await createImageBitmap(file);
    const size = { width: bmp.width, height: bmp.height };
    bmp.close();
    return size;
  } catch {
    return { width: 800, height: 600 };
  }
}

export function usePaste(api: ExcalidrawImperativeAPI | null, patchPostit: (id: string, patch: PostitPatch) => void) {
  // Dónde está el ratón (en la ventana): ahí va lo que se pega con Ctrl+V (D140).
  const pointer = useRef<{ clientX: number; clientY: number } | null>(null);
  useEffect(() => {
    if (!api) return;
    const onMove = (ev: PointerEvent) => { pointer.current = { clientX: ev.clientX, clientY: ev.clientY }; };
    const inField = (t: EventTarget | null) =>
      !!(t as HTMLElement | null)?.closest?.("input, textarea, select, [contenteditable]");
    const place = () => {
      const st = api.getAppState();
      if (pointer.current) return viewportCoordsToSceneCoords(pointer.current, st);
      return { x: -st.scrollX + st.width / st.zoom.value / 2, y: -st.scrollY + st.height / st.zoom.value / 2 };
    };
    const create = (skel: ReturnType<typeof cardSkeleton>) => {
      const [el] = restoreElements([skel as never], null);
      api.updateScene({ elements: [...api.getSceneElementsIncludingDeleted(), el],
                        captureUpdate: CaptureUpdateAction.IMMEDIATELY });
      api.updateScene({ appState: { selectedElementIds: { [el.id]: true } }, captureUpdate: CaptureUpdateAction.NEVER });
    };
    const pasteImage = async (file: Blob, at: Pt) => {
      // El post-it de debajo se decide al pegar, no al terminar de subir: el ratón se mueve.
      const f = getStore().postitFilter;
      const onto = pasteOnto(api.getSceneElements(), at,
        (e) => filteredOut(f, e.customData as unknown as PostitData));
      const [name, size] = await Promise.all([uploadImage(file), naturalSize(file)]);
      if (!name) return;
      const image: ImageRef = { file: name, ...size };
      if (onto && api.getSceneElements().some((e) => e.id === onto)) {
        patchPostit(onto, { image });
      } else {
        create(cardSkeleton("image", newId(), at, imageBox(size.width, size.height), { image, anchor: null }));
      }
    };
    const onPaste = (ev: ClipboardEvent) => {
      const dt = ev.clipboardData;
      if (!dt || inField(ev.target)) return;
      const text = dt.getData("text/plain");
      // Excel y Word dan también una imagen de lo copiado: con texto, manda el texto.
      const image = !text.trim()
        ? [...dt.items].find((i) => i.kind === "file" && i.type.startsWith("image/"))?.getAsFile() ?? null
        : null;
      const url = image ? null : pastedUrl(text);
      if (!image && !url) return;
      ev.preventDefault();
      ev.stopImmediatePropagation();
      const at = place();
      if (image) {
        void pasteImage(image, at);
      } else if (url) {
        const title = linkTitle(url);
        create(cardSkeleton("link", newId(), at, { width: linkWidth(title, linkDomain(url)), height: 38 },
                            { url, title }));
      }
    };
    window.addEventListener("pointermove", onMove, true);
    window.addEventListener("paste", onPaste, true);
    return () => {
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("paste", onPaste, true);
    };
  }, [api, patchPostit]);
}
