// Piezas de las pestañas de *Ajustes* (plan D179): la fila con su `data-row` (para que
// `openSettings(pestaña, fila)` la marque) y su error al lado, el guardado por fila y el
// Escape que se queda una pestaña (Paquetes mientras trabaja).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { saveAppSettings } from "../appSettings";

/** Las pestañas que no dejan cerrar con Escape (devuelven true) se apuntan aquí. */
export const EscapeGuards = createContext<Set<() => boolean> | null>(null);

export function useEscapeGuard(holds: () => boolean) {
  const guards = useContext(EscapeGuards);
  const ref = useRef(holds);
  ref.current = holds;
  useEffect(() => {
    if (!guards) return;
    const g = () => ref.current();
    guards.add(g);
    return () => { guards.delete(g); };
  }, [guards]);
}

/** Guarda un cambio desde una fila: el motivo del rechazo queda junto a esa fila (todo o nada,
 *  `PUT /api/settings`) hasta que la fila se guarda bien. */
export function useSaver() {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const save = useCallback(async (row: string, changes: Record<string, unknown>) => {
    setBusy(row);
    const why = await saveAppSettings(changes);
    setBusy(null);
    setErrors((e) => {
      const next = { ...e };
      if (why) next[row] = why;
      else delete next[row];
      return next;
    });
    return why === null;
  }, []);
  return { save, errors, busy };
}

export const rowLabel = (id: string) => `st-row-${id}`;

/** Un texto del catálogo con `**negrita**` y `` `código` `` (O11): la frase entera va en una
 *  clave, y lo resaltado se marca dentro, en vez de partirla en trozos. */
export function rich(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <b key={i}>{part.slice(2, -2)}</b>
      : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? <code key={i}>{part.slice(1, -1)}</code>
        : part);
}

/** Una fila: el título (y su nota) a la izquierda, el control a la derecha y el error debajo. */
export function Row({ id, title, hint, error, children }: {
  id: string; title: string; hint?: ReactNode; error?: string; children: ReactNode;
}) {
  return (
    <div className="st-row" data-row={id}>
      <div className="st-row-text">
        <span className="st-row-title" id={rowLabel(id)}>{title}</span>
        {hint && <small className="st-row-hint">{hint}</small>}
      </div>
      <div className="st-row-ctl">{children}</div>
      {error && <p className="pull-error st-row-error" role="alert">{error}</p>}
    </div>
  );
}

/** Cabecera de una pestaña, como la de Paquetes. */
export function TabHead({ id, title, children }: { id: string; title: string; children?: ReactNode }) {
  return (
    <div className="st-bar">
      <h3 id={id}>{title}</h3>
      {children}
    </div>
  );
}
