// *Ajustes → Cuentas* (docs/PLAN_M365.md §3, M13): la cuenta de Microsoft 365. Iniciar sesión
// abre el navegador del sistema y el backend espera a que vuelva (M2); SharePoint se pide aparte
// (M4). Se llama *Cuentas* y no *Conectores*: conector ya es Fusion y los demás programas.
import { useCallback, useEffect, useState } from "react";
import { t } from "../i18n";
import { m365SignIn, m365SignOut, m365State, type M365State } from "../m365Api";
import { rich, Row, rowLabel, TabHead } from "./common";

export function AccountsTab() {
  const [state, setState] = useState<M365State | null>(null);
  const [busy, setBusy] = useState<"entrar" | "sharepoint" | "salir" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const got = await m365State();
    if (got.ok) setState(got.value);
    else setError(got.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const run = async (what: "entrar" | "sharepoint" | "salir") => {
    setBusy(what);
    setError(null);
    const got = what === "salir" ? await m365SignOut() : await m365SignIn(what === "sharepoint");
    setBusy(null);
    if (got.ok) setState(got.value);
    else setError(got.error);
  };

  const account = state?.account ?? null;
  return (
    <>
      <TabHead id="st-cuentas" title={t("ajustes.pestana.cuentas")} />
      <h4 className="st-subhead">{t("m365.titulo")}</h4>
      <p className="st-intro">{t("m365.intro")}</p>
      {state === null && !error && <p className="st-busy" role="status">{t("m365.cargando")}</p>}
      {state && !state.configured && <p className="st-intro">{rich(t("m365.sin_configurar"))}</p>}
      {state?.configured && (
        <>
          <Row id="m365.cuenta" title={t("m365.cuenta")}
               hint={account ? t(`m365.tipo.${account.kind}`) : t("m365.sin_cuenta_nota")}
               error={error ?? undefined}>
            {account ? (
              <>
                <span aria-labelledby={rowLabel("m365.cuenta")}>
                  {account.name && account.name !== account.username ? `${account.name} · ` : ""}{account.username}
                </span>
                <button className="pull-btn" disabled={busy !== null} onClick={() => void run("salir")}>
                  {t("m365.cerrar")}
                </button>
              </>
            ) : (
              <>
                <span>{t("m365.sin_cuenta")}</span>
                <button className="pull-btn primary" disabled={busy !== null} onClick={() => void run("entrar")}>
                  {busy === "entrar" ? t("m365.esperando") : t("m365.iniciar")}
                </button>
              </>
            )}
          </Row>
          {account && (
            <Row id="m365.sharepoint" title={t("m365.sharepoint")}
                 hint={state.sharepoint ? undefined : t("m365.sharepoint_no_nota")}>
              {state.sharepoint ? <span>{t("m365.sharepoint_si")}</span>
                // Una cuenta personal no tiene SharePoint: el botón abriría un inicio de sesión
                // que no puede salir bien.
                : account.kind === "personal" ? <span>{t("m365.sharepoint_personal")}</span> : (
                <button className="pull-btn" disabled={busy !== null} onClick={() => void run("sharepoint")}>
                  {busy === "sharepoint" ? t("m365.esperando") : t("m365.sharepoint_dar")}
                </button>
              )}
            </Row>
          )}
          <p className="st-intro st-small">{rich(t("m365.permisos"))}</p>
        </>
      )}
      {!state?.configured && error && <p className="pull-error" role="alert">{error}</p>}
    </>
  );
}
