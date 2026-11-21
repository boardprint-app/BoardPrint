// Diálogos y menú contextual de la pantalla de inicio: papel sobre la pizarra.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { t } from "../i18n";

export function Dialog({ title, children, onClose, className }: {
  title: string; children: ReactNode; onClose: () => void; className?: string;
}) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={className ? `dialog ${className}` : "dialog"} role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <h2 id="dialog-title">{title}</h2>
        {children}
      </div>
    </div>
  );
}

/** Ejecuta la acción; si el backend la rechaza (nombre no válido, ya existe…), enseña por qué
 *  y deja el diálogo abierto para corregir. */
function useSubmit(action: () => Promise<void>, onClose: () => void) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, submit };
}

type NameProps = {
  title: string;
  label: string;
  initial?: string;
  submitLabel: string;
  onSubmit: (name: string) => Promise<void>;
  onClose: () => void;
};

export function NameDialog({ title, label, initial = "", submitLabel, onSubmit, onClose }: NameProps) {
  const [name, setName] = useState(initial);
  const { error, busy, submit } = useSubmit(() => onSubmit(name), onClose);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  return (
    <Dialog title={title} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }} style={{ display: "contents" }}>
        <label>
          {label}
          <input ref={input} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="btn-row">
          <button type="button" className="btn-outline" onClick={onClose}>{t("lienzo.inicio.cancelar")}</button>
          <button type="submit" className="btn-paper" disabled={busy || !name.trim()}>{submitLabel}</button>
        </div>
      </form>
    </Dialog>
  );
}

type MoveProps = {
  name: string;
  targets: { name: string; path: string }[];
  onSubmit: (dest: string) => Promise<void>;
  onClose: () => void;
};

export function MoveDialog({ name, targets, onSubmit, onClose }: MoveProps) {
  const [dest, setDest] = useState(targets[0]?.path ?? "");
  const { error, busy, submit } = useSubmit(() => onSubmit(dest), onClose);
  return (
    <Dialog title={t("lienzo.inicio.mover_titulo", { nombre: name })} onClose={onClose}>
      {targets.length === 0 ? (
        <p>{t("lienzo.inicio.mover_sin_destino")}</p>
      ) : (
        <label>
          {t("lienzo.inicio.mover_a_carpeta")}
          <select value={dest} onChange={(e) => setDest(e.target.value)} autoFocus>
            {targets.map((to) => <option key={to.path} value={to.path}>{to.name}</option>)}
          </select>
        </label>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="btn-row">
        <button type="button" className="btn-outline" onClick={onClose}>{t("lienzo.inicio.cancelar")}</button>
        <button type="button" className="btn-paper" disabled={busy || !targets.length} onClick={submit}>{t("lienzo.inicio.mover")}</button>
      </div>
    </Dialog>
  );
}

type TrashProps = { name: string; detail: string; onSubmit: () => Promise<void>; onClose: () => void };

export function TrashDialog({ name, detail, onSubmit, onClose }: TrashProps) {
  const { error, busy, submit } = useSubmit(onSubmit, onClose);
  return (
    <Dialog title={t("lienzo.inicio.papelera_titulo", { nombre: name })} onClose={onClose}>
      <p>{t("lienzo.inicio.papelera_detalle", { detalle: detail })}</p>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="btn-row">
        <button type="button" className="btn-outline" onClick={onClose} autoFocus>{t("lienzo.inicio.cancelar")}</button>
        <button type="button" className="btn-chalk btn-danger" disabled={busy} onClick={submit}>{t("lienzo.inicio.papelera_enviar")}</button>

      </div>
    </Dialog>
  );
}

export type MenuItem = { label: string; onSelect: () => void; danger?: boolean };

export function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector("button")?.focus();
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) onClose();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", close);
    };
  }, [onClose]);
  // Que no se salga de la ventana.
  const left = Math.min(x, window.innerWidth - 240);
  const top = Math.min(y, window.innerHeight - 52 * items.length - 16);
  return (
    <div ref={ref} className="ctx-menu" role="menu" style={{ left, top }}>
      {items.map((it) => (
        <button key={it.label} role="menuitem" className={it.danger ? "danger" : undefined}
                onClick={() => { onClose(); it.onSelect(); }}>
          {it.label}
        </button>
      ))}
    </div>
  );
}
