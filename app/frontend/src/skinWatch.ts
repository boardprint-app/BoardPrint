// El skin está en <html data-skin> (Root.tsx): una sola suscripción para todos los marcos que
// lo necesitan (la interfaz de un paquete, PackFrame; la animación de un post-it,
// PostitAnimation). Para `useSyncExternalStore(subscribeSkin, readSkin)`.
const skinListeners = new Set<() => void>();
let skinObserver: MutationObserver | null = null;

export function subscribeSkin(l: () => void) {
  skinListeners.add(l);
  if (!skinObserver) {
    skinObserver = new MutationObserver(() => skinListeners.forEach((f) => f()));
    skinObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-skin"] });
  }
  return () => {
    skinListeners.delete(l);
    if (!skinListeners.size) { skinObserver?.disconnect(); skinObserver = null; }
  };
}

export const readSkin = () => document.documentElement.dataset.skin ?? "";
