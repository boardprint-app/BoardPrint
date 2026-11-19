# BoardPrint

**A whiteboard for parametric engineering design.** You sketch the problem on an infinite
board, drop in calculation blocks, connect them with arrows, and let an AI agent help you
reason about the design. The numbers always come from deterministic, tested code. With a
pack that connects to your CAD, results go there as parametric models.

*[Español](README.es.md)*

> **Status: early preview (v0.1.0).** It works end to end on Windows. The app ships without
> packs: you write the ones you need with the SDK, or ask the agent to. Expect rough edges and
> breaking changes before 1.0.

## What it does

- **Board.** An [Excalidraw](https://excalidraw.com) canvas where blocks, sticky notes,
  files, images and ink live together. Each sticky note has a type (requirement, decision,
  risk, question…) and a status. Named versions let you go back.
- **Calculation blocks.** A block takes parameters and inputs and produces typed outputs:
  sizing, checks, bills of materials, reports. Arrows carry data between blocks. When an
  input changes, everything downstream is marked as outdated, and blocks run in the
  background, so the board never freezes.
- **Design agent (optional).** Claude works on the same board. It reads it, proposes changes
  you accept or reject, answers in threads anchored to cards, and runs blocks. It never makes
  up a number: every figure on the board comes from a block or from a cited source. Token use
  and a per-project spending cap are shown.
- **CAD connectors.** A pack can declare a connector to an external program, such as a CAD
  tool, that its blocks work with. A built-in STEP viewer previews parts without any CAD.
- **Packs.** Everything domain-specific comes in a *pack*: Python blocks against a versioned
  SDK, their own isolated UI, and the Python libraries they need in a packs environment
  separate from the app. A pack is a folder or a `.bppack` file, installed in
  *Settings → Packs*. The app ships with none: write your own with the
  [SDK](docs/packs/README.md), or ask the agent to write one for you, with tests.

## Install

Download the installer from [Releases](https://github.com/boardprint-app/BoardPrint/releases):

- **Windows 10/11:** `BoardPrint_x.y.z_x64-setup.exe` (per-user, no admin rights needed). The
  installer is not code-signed yet, so SmartScreen will warn you: *More info → Run anyway*.
- **macOS:** `.dmg` (less tested).

The app comes without packs, so the board starts with no blocks: see
[Write your own pack](#write-your-own-pack).

Optional:

- **For the agent:** [Claude Code](https://claude.com/claude-code) installed on the same
  machine (it is not bundled), signed in with your Claude account or used with an Anthropic API
  key (*Settings → Agents*). Without it, everything except the agent works.

## Build from source

You need Python 3.13, Node 24 and, for the desktop shell, Rust (`rustup`).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r app/backend/requirements.txt   # bin/python on macOS/Linux

# Development: backend on 127.0.0.1:8765 and Vite on http://localhost:5173
cd app/backend && ../../.venv/Scripts/python -m pizarra.server
cd app/frontend && npm install && npm run dev
```

The desktop installer is built locally. See [`app/shell/README.md`](app/shell/README.md).

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

## Write your own pack

A pack is a folder with a `pack.toml` and Python blocks that use the `boardprint_sdk`. It does
not touch the core, so it can stay private and use any license you like. Start with
[`docs/packs/README.md`](docs/packs/README.md), or ask the agent to create one.

## Repository layout

| Path | What |
|---|---|
| `app/frontend/` | React + TypeScript + Excalidraw UI |
| `app/backend/` | Python backend (`pizarra`), pack SDK (`boardprint_sdk`) and worker |
| `app/shell/` | Tauri 2 desktop shell and installer |
| `engine/` | Shared engine core that packs may use (`pizarra_engine.core`) |
| `docs/packs/` | How to write a pack |

Internal names (`pizarra`, `pizarra_engine`), code comments and docstrings are in Spanish: the
project started as a personal tool (CAD-LLM). The public interface, this README and the contributor
docs are in English.

## Contributing

Issues and pull requests are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md). Commits must
be signed off ([DCO](https://developercertificate.org)).

## License

[Apache License 2.0](LICENSE). Copyright 2026 Bernat Suarez i Domenech. Bundled third-party
components and their licenses are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

*Claude is a trademark of Anthropic, PBC. BoardPrint is not affiliated with Anthropic.*
