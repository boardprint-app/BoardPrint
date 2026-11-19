// El actualizador (docs/PLAN_V020.md §4, V9-V13), con `tauri-plugin-updater` contra el
// `latest.json` del último Release de boardprint-app/BoardPrint. Como el modo de ventana, sin IPC:
// el shell y el backend se hablan por ficheros en la carpeta de los ajustes.
//
// - `update.json` lo escribe el shell: `{"estado": "disponible" | "al_dia" | "instalando" |
//   "error", "version", "actual", "notas", "fecha", "motivo"}`. El backend lo da a la interfaz.
// - `update.request` lo escribe el backend cuando el usuario pide algo: `check` o `install`.
//   El shell lo mira cada segundo, lo borra y lo hace.
//
// Al arrancar, una comprobación en segundo plano; si hay versión nueva, además del fichero, el
// evento `pizarra-update` a la interfaz. **Instalar lo decide el usuario** (V9): nunca en
// silencio. Antes de instalar se para el backend (y con él los trabajadores, que se cierran al
// perder su canal), para que el instalador pueda sustituir sus ficheros.
use std::path::{Path, PathBuf};
use std::time::Duration;

use tauri::{AppHandle, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};

pub const STATE: &str = "update.json";
pub const REQUEST: &str = "update.request";

fn write_state(dir: &Path, state: serde_json::Value) {
    let _ = std::fs::write(dir.join(STATE), state.to_string());
}

fn notify(app: &AppHandle, state: &serde_json::Value) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval(&format!(
            "window.dispatchEvent(new CustomEvent('pizarra-update', {{ detail: {state} }}))"
        ));
    }
}

/// Mira si hay versión nueva y lo deja en `update.json`. Sin red o sin Release, `error` con
/// su motivo: la interfaz no avisa de nada (solo lo enseña *Ajustes* si se pide).
async fn check(app: &AppHandle, dir: &Path) -> Option<Update> {
    let current = app.package_info().version.to_string();
    let found = match app.updater() {
        Ok(updater) => updater.check().await.map_err(|e| e.to_string()),
        Err(e) => Err(e.to_string()),
    };
    match found {
        Ok(Some(update)) => {
            let state = serde_json::json!({
                "estado": "disponible",
                "version": update.version,
                "actual": current,
                "notas": update.body,
                "fecha": update.date.map(|d| d.to_string()),
            });
            write_state(dir, state.clone());
            notify(app, &state);
            Some(update)
        }
        Ok(None) => {
            write_state(dir, serde_json::json!({ "estado": "al_dia", "actual": current }));
            None
        }
        Err(motivo) => {
            write_state(dir, serde_json::json!({ "estado": "error", "actual": current, "motivo": motivo }));
            None
        }
    }
}

/// Descarga, comprueba la firma e instala. `stop` para el backend antes. Si falla, se vuelve a
/// abrir la app (el backend ya no está) y `update.json` dice por qué.
async fn install(app: &AppHandle, dir: &Path, stop: fn(&AppHandle)) {
    let Some(update) = check(app, dir).await else { return };
    write_state(dir, serde_json::json!({ "estado": "instalando", "version": update.version }));
    stop(app);
    if let Err(e) = update.download_and_install(|_, _| {}, || {}).await {
        write_state(dir, serde_json::json!({
            "estado": "error", "version": update.version, "motivo": e.to_string()
        }));
    }
    app.restart();
}

/// Una comprobación al arrancar y, cada segundo, lo que pida el backend en `update.request`.
pub fn watch(app: AppHandle, dir: PathBuf, stop: fn(&AppHandle)) {
    std::thread::spawn(move || {
        tauri::async_runtime::block_on(check(&app, &dir));
        let request = dir.join(REQUEST);
        loop {
            std::thread::sleep(Duration::from_secs(1));
            let Ok(what) = std::fs::read_to_string(&request) else { continue };
            let _ = std::fs::remove_file(&request);
            match what.trim() {
                "install" => tauri::async_runtime::block_on(install(&app, &dir, stop)),
                _ => {
                    tauri::async_runtime::block_on(check(&app, &dir));
                }
            }
        }
    });
}
