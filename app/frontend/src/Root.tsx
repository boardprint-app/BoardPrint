// Qué se enseña: la pizarra del último proyecto o la pantalla de inicio (plan D63), con el skin
// de settings.toml (D79) puesto en <html> para que lo usen las dos, y las fuentes (D184) como
// variables CSS en <html>.
import { useCallback, useEffect, useState } from "react";
import { loadAppSettings, saveAppSettings, useAppSettings } from "./appSettings";
import { apiFetch, launchFiles } from "./auth";
import { ProjectBoard } from "./App";
import { fontVars } from "./fonts";
import { Home } from "./home/Home";
import { t } from "./i18n";
import { splitDrop } from "./packs";
import { openInstall } from "./settings";
import { SettingsDialog } from "./SettingsDialog";
import { skinOf, type SkinId } from "./skins";
import { UpdateBanner } from "./UpdateBanner";
import { WelcomeDialog } from "./WelcomeDialog";
import { openWelcome, readyToShow, welcomeOnLoad } from "./welcome";

type View = { view: "home"; missing: string | null; problem?: string } | { view: "project"; project: string };

export default function Root() {
  const [view, setView] = useState<View | null>(null);
  const [skin, setSkinState] = useState<SkinId>(skinOf(null).id);

  useEffect(() => {
    apiFetch("/api/start")
      .then((r) => r.json())
      .then((start) => {
        setSkinState(skinOf(start.skin).id);
        setView(start);
      })
      .catch(() => setView({ view: "home", missing: null, problem: t("lienzo.inicio.sin_backend") }
));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.skin = skin;
  }, [skin]);

  // Los ajustes de la app (D179), una vez al arrancar; después los recarga quien sepa que han
  // cambiado (la ventana de Ajustes al abrirse, la pizarra con `{type: "settings"}`).
  // La bienvenida (D186) sale sola si los ajustes dicen que aún no se ha visto.
  // Hasta haberlos pedido no se pinta nada (`readyToShow`): Excalidraw toma el idioma al montarse.
  const [settingsTried, setSettingsTried] = useState(false);
  useEffect(() => {
    void loadAppSettings().then((got) => {
      setSettingsTried(true);
      if (welcomeOnLoad(got)) openWelcome();
    });
  }, []);
  const app = useAppSettings();

  // El skin sigue al de los ajustes cuando cambia allí (otra ventana, *Ajustes → Apariencia*).
  const savedSkin = app?.skin;
  useEffect(() => {
    if (savedSkin) setSkinState(skinOf(savedSkin).id);
  }, [savedSkin]);

  // Las fuentes (D184): cada una en su variable, con su respaldo; «sistema», la de skins.css.
  const fonts = app?.fuentes;
  useEffect(() => {
    const style = document.documentElement.style;
    for (const [name, value] of Object.entries(fontVars(fonts))) {
      if (value) style.setProperty(name, value);
      else style.removeProperty(name);
    }
  }, [fonts]);

  // Un `.bppack` soltado sobre la ventana abre el resumen de instalar (PLAN_PAQUETES P82), en
  // la pizarra y en el inicio; nunca se convierte en tarjeta. En la app de escritorio llegan
  // las rutas (`pizarra-drop`, src-tauri/src/main.rs); en el navegador, los archivos.
  useEffect(() => {
    const fromShell = (ev: Event) => {
      const { packs } = splitDrop((ev as CustomEvent<{ paths?: string[] }>).detail?.paths ?? []);
      if (packs.length) openInstall({ paths: packs });
    };
    // Doble clic en un `.bppack` (P82): al abrir la app, en la URL; con la app ya abierta, la
    // segunda instancia se los pasa a esta (`pizarra-open`, src-tauri/src/main.rs).
    const launch = splitDrop(launchFiles).packs;
    if (launch.length) openInstall({ paths: launch });
    const over = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
    };
    const drop = (e: DragEvent) => {
      const { packs } = splitDrop(Array.from(e.dataTransfer?.files ?? []));
      if (packs.length) {
        e.preventDefault();
        e.stopPropagation();
        openInstall({ files: packs });
      } else if (!(e.target as Element | null)?.closest?.(".excalidraw")) {
        e.preventDefault();               // fuera de la pizarra, el navegador abriría el archivo
      }
    };
    window.addEventListener("pizarra-drop", fromShell);
    window.addEventListener("pizarra-open", fromShell);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop, true);
    return () => {
      window.removeEventListener("pizarra-drop", fromShell);
      window.removeEventListener("pizarra-open", fromShell);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop, true);
    };
  }, []);

  // Se cambia al momento; si el backend no lo guarda, la próxima vez se abre con el de antes.
  // Por `PUT /api/settings` (D179), que avisa a las demás ventanas; `/api/settings/skin` sigue.
  const setSkin = useCallback((id: SkinId) => {
    setSkinState(id);
    void saveAppSettings({ skin: id });
  }, []);

  const goHome = useCallback((missing?: string) => {
    setView({ view: "home", missing: missing ?? null });
  }, []);
  const open = useCallback((project: string) => setView({ view: "project", project }), []);

  if (view === null || !readyToShow(view, settingsTried)) return null;
  return (
    <>
      {view.view === "project"
        // key: cambiar de proyecto monta una pizarra nueva, sin nada del anterior.
        ? <ProjectBoard key={view.project} projectId={view.project} onHome={goHome}
                        skin={skin} onSkin={setSkin} />
        : <Home missing={view.missing} problem={view.problem} onOpen={open} />}
      <SettingsDialog skin={skin} onSkin={setSkin} />
      <WelcomeDialog />
      <UpdateBanner />
    </>
  );
}
