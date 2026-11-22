# BoardPrint

**Una pizarra para el diseño paramétrico en ingeniería.** Dibujas el problema en una pizarra
infinita, pones bloques de cálculo, los conectas con flechas y dejas que un agente de IA te
ayude a razonar el diseño. Los números salen siempre de código determinista y con tests. Con
un paquete que conecte con tu CAD, los resultados van allí como modelos paramétricos.

*[English](README.md)*

> **Estado: versión final (v0.8.0), sin mantenimiento.** BoardPrint se desarrolló hasta el 22
> de noviembre de 2026 y el repositorio está archivado: no se contestan issues ni pull requests.
> Funciona de punta a punta en Windows. La app llega sin paquetes: los que necesites los haces
> con el SDK, o se los pides al agente. El código es Apache-2.0: haz un fork y continúalo
> ([más abajo](#seguir-con-el-proyecto)).

## Qué hace

- **Pizarra.** Un lienzo de [Excalidraw](https://excalidraw.com) donde conviven bloques,
  post-its, archivos, imágenes y tinta. Cada post-it tiene un tipo (requisito, decisión,
  riesgo, pregunta…) y un estado. Las versiones con nombre te dejan volver atrás.
- **Bloques de cálculo.** Un bloque recibe parámetros y entradas y da salidas con tipo:
  dimensionado, comprobaciones, listas de materiales, informes. Las flechas llevan los datos
  de un bloque a otro. Cuando cambia una entrada, todo lo que va detrás queda marcado como
  desactualizado, y los bloques se ejecutan en segundo plano: la pizarra nunca se queda
  congelada.
- **Agente de diseño (opcional).** Claude trabaja en la misma pizarra. La lee, propone
  cambios que tú aceptas o rechazas, contesta en hilos anclados a las tarjetas y ejecuta
  bloques. Nunca se inventa un número: cada cifra de la pizarra sale de un bloque o de una
  fuente citada. Se enseñan los tokens gastados y un límite de gasto por proyecto.
- **Conectores de CAD.** Un paquete puede declarar un conector con un programa externo, como
  un CAD, con el que trabajan sus bloques. Un visor STEP integrado enseña las piezas sin
  ningún CAD.
- **Paquetes.** Todo lo de un dominio concreto va en un *paquete*: bloques en Python contra un
  SDK con versión, su propia interfaz aislada y sus propias librerías de Python en un entorno
  aparte. Un paquete es una carpeta o un archivo `.bppack`, y se instala en *Ajustes →
  Paquetes*. La app no trae ninguno: hazte los tuyos con el [SDK](docs/packs/README.md), o
  pide al agente que te escriba uno, con sus tests.

## Instalación

Descarga el instalador desde [Releases](https://github.com/boardprint-app/BoardPrint/releases):

- **Windows 10/11:** `BoardPrint_x.y.z_x64-setup.exe` (por usuario, sin permisos de
  administrador). El instalador aún no está firmado, así que SmartScreen te avisará: *Más
  información → Ejecutar de todas formas*.
- **macOS (Apple Silicon):** `.dmg` (menos probado). No está notarizado, así que macOS lo
  bloquea la primera vez: permítelo en *Ajustes del Sistema → Privacidad y seguridad → Abrir
  igualmente*.

La app llega sin paquetes, así que la pizarra empieza sin bloques: mira
[Haz tu propio paquete](#haz-tu-propio-paquete).

Opcional:

- **Para el agente:** [Claude Code](https://claude.com/claude-code) instalado en el mismo
  equipo (la app no lo trae), con la sesión de tu cuenta de Claude iniciada o con una clave de
  la API de Anthropic (*Ajustes → Agentes*). Sin él funciona todo menos el agente.

## Compilar desde el código

Necesitas Python 3.13, Node 24 y, para la aplicación de escritorio, Rust (`rustup`).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r app/backend/requirements.txt   # bin/python en macOS/Linux

# Desarrollo: backend en 127.0.0.1:8765 y Vite en http://localhost:5173
cd app/backend && ../../.venv/Scripts/python -m pizarra.server
cd app/frontend && npm install && npm run dev
```

El instalador de escritorio se compila en local. Mira [`app/shell/README.md`](app/shell/README.md).

```bash
cd app/frontend && npm ci && npm run build
cd ../.. && .venv/Scripts/python app/shell/build_sidecar.py
.venv/Scripts/python app/shell/fetch_pyenv.py
cd app/shell && npm ci && npx tauri build
```

Tests:

```bash
cd app/backend && ../../.venv/Scripts/python -m unittest discover -s tests -t .
cd app/frontend && npm test
```

## Haz tu propio paquete

Un paquete es una carpeta con un `pack.toml` y bloques en Python que usan el
`boardprint_sdk`. No toca el núcleo, así que puede ser privado y llevar la licencia que
quieras. Empieza por [`docs/packs/README.md`](docs/packs/README.md) (en inglés), o pide al
agente que te haga uno.

## Estructura del repositorio

| Ruta | Qué hay |
|---|---|
| `app/frontend/` | Interfaz en React + TypeScript + Excalidraw |
| `app/backend/` | Backend en Python (`pizarra`), SDK de paquetes (`boardprint_sdk`) y trabajador |
| `app/shell/` | Aplicación de escritorio con Tauri 2 e instalador |
| `engine/` | Núcleo común del motor que pueden usar los paquetes (`pizarra_engine.core`) |
| `docs/packs/` | Cómo hacer un paquete (en inglés) |

Los nombres internos (`pizarra`, `pizarra_engine`), los comentarios y los docstrings están en
español: el proyecto empezó como herramienta personal (CAD-LLM). La interfaz pública, el
README en inglés y la documentación para colaboradores están en inglés. Los comentarios citan
además documentos de diseño internos (`PLAN_*.md`, números de decisión como D61 o P30) que no
están en este repositorio.

## Seguir con el proyecto

BoardPrint ya no se mantiene, así que el repositorio está archivado (solo lectura). Para
seguir desarrollándolo, haz un fork: la licencia Apache-2.0 te deja usarlo, modificarlo y
redistribuirlo, también con fines comerciales, conservando sus avisos. Un paquete no necesita
ningún fork. Ideas que quedaron abiertas:

- **SharePoint: guardar y búsqueda del agente.** Traer archivos de SharePoint ya está, pero
  nunca se probó con una cuenta de empresa real. Faltan guardar en SharePoint y buscar en él
  desde el agente.
- **Un paquete para CATIA.** Un paquete puede declarar un conector (`pack.connector`) y
  manejar CATIA por su API COM con `pywin32` (solo Windows).
- **Firma de código** del instalador de Windows, y notarización en macOS.

[`CONTRIBUTING.md`](CONTRIBUTING.md) (en inglés) tiene las reglas del proyecto y cómo ejecutar
los tests.

## Licencia

[Apache License 2.0](LICENSE). Copyright 2026 Bernat Suarez i Domenech. Los componentes de
terceros incluidos y sus licencias están en [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

*Claude es una marca de Anthropic, PBC. BoardPrint no tiene relación con Anthropic.*
