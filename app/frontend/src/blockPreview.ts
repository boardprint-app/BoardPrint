// Vista previa de un bloque (PLAN_TERMINALES T26): lo que enseña su editor con los parámetros
// que se están escribiendo, sin guardar ni ejecutar. La calcula el paquete en el servidor.
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "./auth";
import { getStore } from "./store";

export async function fetchPreview<T>(block: string, params: Record<string, unknown>): Promise<T> {
  const pid = getStore().project?.id ?? "";
  const r = await apiFetch(`/api/projects/${encodeURIComponent(pid)}/blocks/${encodeURIComponent(block)}/preview`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ params }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? `error ${r.status}`);
  return r.json();
}

/** La vista previa de `block` con `params`, pedida otra vez cuando cambian (o cambia `tick`),
 *  con una pausa corta para no pedir una por tecla. Una respuesta vieja nunca pisa a una nueva. */
export function usePreview<T>(block: string | null, params: Record<string, unknown> | null, tick: unknown = null,
                              wait = 150): { data: T | null; error: string | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);
  const key = JSON.stringify(params);
  useEffect(() => {
    if (!block || params === null) return;
    const n = ++seq.current;
    setLoading(true);
    const t = setTimeout(() => {
      fetchPreview<T>(block, params)
        .then((d) => { if (n === seq.current) { setData(d); setError(null); } })
        .catch((e: Error) => { if (n === seq.current) setError(e.message); })
        .finally(() => { if (n === seq.current) setLoading(false); });
    }, wait);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [block, key, tick, wait]);
  return { data, error, loading };
}
