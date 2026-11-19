// Archivo de un *STEP de referencia* (D129): «Elegir archivo» abre el diálogo del sistema
// desde el backend (la interfaz no ve rutas) y el parámetro guarda la ruta. Con una tarjeta de
// archivo conectada a su entrada manda la tarjeta (D133): se enseña su archivo, no el parámetro.
import { useEffect, useState } from "react";
import { apiFetch } from "./auth";
import { cardInfo } from "./cardActions";
import { t } from "./i18n";

type Props = { value: string; onChange: (path: string) => void; linked?: string | null };

export function ArchivoStep({ value, onChange, linked }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [card, setCard] = useState<{ name: string; path: string } | null>(null);
  useEffect(() => {
    let live = true;
    setCard(null);
    if (linked) void cardInfo(linked).then((c) => { if (live && c) setCard({ name: c.name, path: c.path }); });
    return () => { live = false; };
  }, [linked]);
  if (linked) {
    return (
      <span className="cad-file" title={t("bloques.archivo.manda_tarjeta")}>
        <span className="cad-file-name">{card?.name ?? "…"}</span>
        <span className="cad-file-from">{t("bloques.archivo.de_tarjeta")}</span>
      </span>
    );
  }
  const name = value ? value.split(/[\\/]/).pop() : "";
  const choose = async () => {
    setError(null);
    setBusy(true);
    const r = await apiFetch("/api/dialog/step", { method: "POST" });
    setBusy(false);
    if (!r.ok) {
      setError((await r.json().catch(() => null))?.detail ?? t("bloques.archivo.error_dialogo"));
      return;
    }
    const path = (await r.json()).path as string | null;
    if (path) onChange(path);
  };
  return (
    <span className="cad-file">
      <span className="cad-file-name" title={value || undefined}>{name || t("bloques.archivo.ninguno")}</span>
      <button type="button" className="cad-dest-refresh" disabled={busy} onClick={() => void choose()}>
        {busy ? t("bloques.archivo.eligiendo") : t("bloques.archivo.elegir")}
      </button>
      {error && <span className="cad-doc-error">{error}</span>}
    </span>
  );
}
