# Shell de escritorio (Tauri 2)

Ventana nativa que arranca el backend empaquetado y carga la interfaz que este sirve
(`docs/PLAN_PIZARRA.md` §1 y §8). Sin IPC de Tauri: todo va por HTTP y WebSocket a
`127.0.0.1:<puerto aleatorio>` con un token por sesión.

| Fichero | Qué es |
|---|---|
| `src-tauri/src/main.rs` | Puerto + token, arranca el sidecar, navega cuando responde, lo para al salir; un `.bppack` abierto con doble clic va a la interfaz (en la URL al arrancar; con la app abierta, por `tauri-plugin-single-instance`) |
| `src-tauri/tauri.conf.json` | Instalador NSIS (por usuario, sin admin) y `.dmg`; motor `.py` como recurso (`engine/`); asocia `.bppack` con la app |
| `loading/` | Pantalla de "arrancando" mientras el backend levanta |
| `build_sidecar.py` | Backend + interfaz compilada → `src-tauri/binaries/pizarra-backend-<triple>` (PyInstaller). Sin paquetes: la app no los trae (`PLAN_PAQUETES` P11) |
| `build_packs.py` | Los `.bppack` oficiales (`robotica_base`, `robotica`, `terminales`, `fusion`) → `dist-packs/`, con el código de *Exportar* (`PLAN_PAQUETES` P77). Sin `packs/` (el repo público) no hace nada |
| `smoke_sidecar.py` | Prueba de humo del sidecar: arranque < 10 s, token obligatorio, interfaz servida, sin paquetes al arrancar e instalados desde su `.bppack` (esto último, solo si hay `packs/`) |
| `fetch_pyenv.py` | Python standalone y `uv` fijados con su sha256 → `src-tauri/pyenv/` (recurso `pyenv/`, `PLAN_PAQUETES` P21) |
| `smoke_pack_env.py` | Instala el `setup.exe` y prueba el entorno de paquetes en la app instalada (criterio de §12 de `PLAN_PAQUETES`) |

## Generar el instalador

Se compila y se prueba **en local**. El CI (`.github/workflows/app.yml`) solo lo hace cuando el
usuario lo pide (*Actions → App → Run workflow* o `gh workflow run App --ref <rama>`): cada
instalador ocupa ~200 MB del almacenamiento de Actions (se guarda 3 días) y gasta minutos de
Windows. El `.dmg`, con la opción macOS, firmado *ad hoc* (`bundle.macOS.signingIdentity:
"-"`): sin firma, un Mac con Apple Silicon dice que la app descargada «está dañada» y no deja
abrirla; con la ad hoc avisa de que no la puede verificar y deja abrirla desde *Ajustes →
Privacidad y seguridad*. Se descarga desde la pestaña Actions,
artefacto `instalador-<sistema>`, y los `.bppack` oficiales, si el repo trae `packs/`, en el
artefacto `paquetes`. Con la opción *publicar* y una versión `X.Y.Z`, además crea el Release de
GitHub `vX.Y.Z` solo con el instalador: la app llega sin paquetes (`PLAN_PAQUETES` P77).

En local hace falta Rust (`rustup`) además de Node y Python:

```bash
cd app/frontend && npm ci && npm run build
cd ../.. && .venv/Scripts/python.exe app/shell/build_sidecar.py
.venv/Scripts/python.exe app/shell/smoke_sidecar.py
.venv/Scripts/python.exe app/shell/fetch_pyenv.py     # sin él, tauri build no encuentra pyenv/
cd app/shell && npm ci && npx tauri build
```

## Entorno de paquetes (`PLAN_PAQUETES` P19-P21)

Los bloques de los paquetes acabarán corriendo en un **Python de verdad** (`pyenv/python`), no
en el del ejecutable de PyInstaller, en un venv por conjunto de paquetes que crea `uv` en
`<caché>/envs/<huella>/` (`app/backend/pizarra/pack_env.py`), con el trabajador
`boardprint_worker` (recurso `worker/`, con el SDK `boardprint_sdk` y, para cargar, `pizarra/packs.py`,
`pack_versions.py`, `pack_validate.py` (la carga valida, FF 10.2) y `files.py`). Lo aprendido en
la prueba de FF 10.1 paso 1:

- **Recursos de un árbol:** en el mapa de `bundle.resources`, la clave `"pyenv/"` copia la
  carpeta con su estructura; un glob (`"pyenv/**/*"`) la **aplana**.
- **Podar el Python** (tkinter, Tcl/Tk, IDLE, tests, pip: 49 → 37 MB): con una lista por
  sistema. En Windows el glob no distingue mayúsculas y `lib/thread*` de macOS se lleva
  `Lib/threading.py`.
- **Entorno limpio** (`pack_env.clean_env`): el hijo no hereda `PYTHONPATH`, `PYTHONHOME`,
  `_PYI_*` ni `_MEIPASS2` del ejecutable congelado; `uv` va con `UV_PYTHON_DOWNLOADS=never`
  (nunca baja otro Python) y `UV_NO_CONFIG`.
- **Sin ventana:** el backend corre sin consola y cada `python.exe` o `uv.exe` que lance abriría
  una; van con `CREATE_NO_WINDOW`.
- **Los `.pyc`, a la caché** (`PYTHONPYCACHEPREFIX=<caché>/pycache`): los recursos y las
  carpetas de paquetes no traen `__pycache__` y, con un proceso por ejecución, todo se
  recompilaría cada vez. Las librerías se compilan al crear el entorno (`compileall`, con el
  mismo prefijo): sin eso, el primer registro con numpy pasaba de 0,6 s a 2 s.
  `uv pip install --compile-bytecode` no sirve: deja los `.pyc` junto a los fuentes y Python,
  con el prefijo, no los mira.
- **El canal del trabajador:** se duplica el stdout para el protocolo y el descriptor 1 pasa a
  stderr, así ni un `print` ni un `printf` de una librería de C lo rompen.

El icono es provisional (generado); se cambia junto con el nombre (plan D49).
