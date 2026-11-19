// Shell de escritorio (plan §1). Solo hace cinco cosas:
// 1. elige un puerto libre en 127.0.0.1 y genera un token;
// 2. arranca el backend empaquetado (sidecar) con ellos, el proyecto y la ruta del motor;
// 3. abre la ventana con la pantalla de arranque y, cuando el backend responde, la lleva a
//    http://127.0.0.1:<puerto>/?token=<token> (el backend sirve la interfaz);
// 4. al salir, para el backend;
// 5. los archivos y carpetas soltados desde el explorador se los pasa a la interfaz con sus
//    rutas (el navegador no las da), en el evento `pizarra-drop` (plan §3, D59);
// 6. un `.bppack` abierto con doble clic (PLAN_PAQUETES P82): al arrancar va en la URL
//    (`open=<ruta>`); con la app ya abierta, la segunda instancia se lo pasa a esta y se
//    cierra (`tauri-plugin-single-instance`), y llega a la interfaz en `pizarra-open`;
// 7. el modo de ventana y la escala de `settings.toml` (plan D183, `window_mode.rs`): al abrir
//    y cada vez que el fichero cambia (lo escribe el backend desde *Ajustes*).
// La interfaz no usa IPC de Tauri: todo pasa por HTTP y WebSocket con el backend.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tauri::{DragDropEvent, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

mod window_mode;

use window_mode::{Mode, WindowSettings};

const APP_NAME: &str = "BoardPrint"; // nombre del producto (plan D49, D158)
const WINDOWED: (f64, f64) = (1400.0, 900.0); // el tamaño del modo «ventana»

struct Backend(Mutex<Option<CommandChild>>);

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .expect("no hay ningún puerto libre en 127.0.0.1")
}

fn random_token() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    (0..4)
        .map(|i| {
            let mut h = RandomState::new().build_hasher();
            h.write_u64(nanos ^ (i as u64) ^ (std::process::id() as u64));
            format!("{:016x}", h.finish())
        })
        .collect()
}

/// Los `.bppack` de una línea de órdenes (doble clic en el explorador), con su ruta entera.
fn pack_args<I: IntoIterator<Item = String>>(args: I, cwd: &Path) -> Vec<String> {
    args.into_iter()
        .filter(|a| a.to_lowercase().ends_with(".bppack"))
        .map(|a| cwd.join(&a).to_string_lossy().into_owned())
        .collect()
}

/// Aplica el modo y la escala (D183). Pasar de uno a otro deshace lo del anterior: sin
/// pantalla completa, con o sin bordes, y maximizada o a su tamaño.
fn apply_window(window: &tauri::WebviewWindow, ws: WindowSettings) {
    let full = ws.mode == Mode::Fullscreen;
    let _ = window.set_fullscreen(full);
    if !full {
        let _ = window.set_decorations(ws.mode != Mode::Borderless);
        if ws.mode == Mode::Windowed {
            let _ = window.unmaximize();
            let _ = window.set_size(tauri::LogicalSize::new(WINDOWED.0, WINDOWED.1));
            let _ = window.center();
        } else {
            let _ = window.maximize();
        }
    }
    let _ = window.set_zoom(ws.scale as f64 / 100.0);
}

/// Mira cada segundo la fecha de modificación de `settings.toml` y, si lo leído cambia, lo
/// aplica. Sin `notify`: un fichero, una vez por segundo, no lo merece.
fn watch_window(window: tauri::WebviewWindow, path: std::path::PathBuf, mut last: WindowSettings) {
    std::thread::spawn(move || {
        let mut stamp = std::fs::metadata(&path).and_then(|m| m.modified()).ok();
        loop {
            std::thread::sleep(Duration::from_secs(1));
            let now = std::fs::metadata(&path).and_then(|m| m.modified()).ok();
            if now == stamp {
                continue;
            }
            stamp = now;
            let ws = window_mode::read(&path);
            if ws != last {
                apply_window(&window, ws);
                last = ws;
            }
        }
    });
}

fn main() {
    tauri::Builder::default()
        // La primera: con la app abierta, otra instancia no arranca otro backend.
        .plugin(tauri_plugin_single_instance::init(|app, argv, cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
                let packs = pack_args(argv.into_iter().skip(1), Path::new(&cwd));
                if !packs.is_empty() {
                    let detail = serde_json::json!({ "paths": packs });
                    let _ = window.eval(&format!(
                        "window.dispatchEvent(new CustomEvent('pizarra-open', {{ detail: {detail} }}))"
                    ));
                }
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let port = free_port();
            let token = random_token();
            let resources = app.path().resource_dir()?;
            let engine = resources.join("engine");
            // Ajustes en la carpeta de configuración de la app (%APPDATA%\<identificador>) y
            // Documentos tal como la resuelve el sistema (puede estar en OneDrive): el
            // workspace por defecto va en <Documentos>/<App>/ (plan §2, D70).
            let settings = app.path().app_config_dir()?.join("settings.toml");
            // El entorno de paquetes (PLAN_PAQUETES P93): el Python y uv de la app, el
            // trabajador y la caché (entornos, .pyc).
            let pyenv = resources.join("pyenv");
            let worker = resources.join("worker");
            let cache = app.path().app_cache_dir()?;
            let documents = app.path().document_dir()?;

            let (mut rx, child) = app
                .shell()
                .sidecar("pizarra-backend")?
                .args([
                    "--port",
                    &port.to_string(),
                    "--token",
                    &token,
                    "--settings",
                    &settings.to_string_lossy(),
                    "--documents",
                    &documents.to_string_lossy(),
                    "--engine-dir",
                    &engine.to_string_lossy(),
                    "--pyenv-dir",
                    &pyenv.to_string_lossy(),
                    "--worker-dir",
                    &worker.to_string_lossy(),
                    "--cache-dir",
                    &cache.to_string_lossy(),
                    "--parent-pid",
                    &std::process::id().to_string(),
                ])
                .spawn()?;
            app.manage(Backend(Mutex::new(Some(child))));
            // Se vacía la salida del backend: si nadie la lee, el proceso se bloquea al escribir.
            tauri::async_runtime::spawn(async move { while rx.recv().await.is_some() {} });

            // El modo de ventana y la escala (D50, D183); por defecto, maximizada: ocupa toda
            // la pantalla sin ser pantalla completa.
            let initial = window_mode::read(&settings);
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title(APP_NAME)
                .inner_size(WINDOWED.0, WINDOWED.1)
                .maximized(matches!(initial.mode, Mode::Maximized | Mode::Borderless))
                .fullscreen(initial.mode == Mode::Fullscreen)
                .decorations(initial.mode != Mode::Borderless)
                .build()?;
            let _ = window.set_zoom(initial.scale as f64 / 100.0);
            watch_window(window.clone(), settings.clone(), initial);

            // Rutas soltadas, con el punto (en píxeles físicos de la ventana) donde se soltaron:
            // la interfaz crea ahí sus tarjetas (frontend/src/App.tsx, `pizarra-drop`).
            let drop_target = window.clone();
            window.on_window_event(move |event| {
                if let WindowEvent::DragDrop(DragDropEvent::Drop { paths, position }) = event {
                    let detail = serde_json::json!({
                        "paths": paths.iter().map(|p| p.to_string_lossy().into_owned()).collect::<Vec<_>>(),
                        "x": position.x,
                        "y": position.y,
                    });
                    let _ = drop_target.eval(&format!(
                        "window.dispatchEvent(new CustomEvent('pizarra-drop', {{ detail: {detail} }}))"
                    ));
                }
            });

            let settings_path = settings.clone();
            let cwd = std::env::current_dir().unwrap_or_default();
            let opened = pack_args(std::env::args().skip(1), &cwd);
            std::thread::spawn(move || {
                let start = Instant::now();
                while start.elapsed() < Duration::from_secs(30) {
                    if TcpStream::connect(("127.0.0.1", port)).is_ok() {
                        let url = format!("http://127.0.0.1:{port}/?token={token}");
                        if let Ok(mut url) = Url::parse(&url) {
                            for p in &opened {
                                url.query_pairs_mut().append_pair("open", p);
                            }
                            let _ = window.navigate(url);
                            // la escala de nuevo: una navegación puede volver al 100 %
                            let _ = window.set_zoom(window_mode::read(&settings_path).scale as f64 / 100.0);
                        }
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }
                let _ = window.eval(
                    "document.getElementById('msg').textContent = \
                     'El backend no ha arrancado en 30 s. Cierra la app y vuelve a abrirla.'",
                );
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir la app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}
