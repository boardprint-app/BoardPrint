# Writing a BoardPrint pack

A **pack** adds blocks to the board for a domain (airfoils, tanks, beams…) without touching
the app. It is a folder with a `pack.toml` manifest and Python code written against the
**pack SDK** (`boardprint_sdk`, version 1.4.0 today). The app ships without packs: every pack
is built exactly this way.

**Packs live outside the core.** You do not fork BoardPrint or send a pull request to ship a
pack: you write it in your own folder or repository and install it as a `.bppack` file.

**Licensing.** The core is Apache-2.0, and that license does not require a pack to be open
source. A pack talks to the app only through the SDK and the files described here, so it can
be private or proprietary, or use any open-source license you like. Say which one in
`pack.toml` (`license`, below) and ship your own `LICENSE` file inside the pack folder if you
want one.

This guide is based on the code that loads and validates packs:
[`app/backend/boardprint_sdk/`](../../app/backend/boardprint_sdk/) (the SDK),
[`app/backend/pizarra/packs.py`](../../app/backend/pizarra/packs.py) (manifest and loading),
[`app/backend/pizarra/pack_validate.py`](../../app/backend/pizarra/pack_validate.py) (static
validation) and [`app/backend/pizarra/pack_template/`](../../app/backend/pizarra/pack_template/)
(the starter template). The design agent's own guide, in Spanish, is
[`app/backend/pizarra/pack_guide.md`](../../app/backend/pizarra/pack_guide.md). Internal
names and messages are in Spanish (*pizarra* = board, *paquete* = pack).

## Folder layout

```
<id>/
  pack.toml        manifest
  blocks.py        register(pack): ports and blocks (the module named by `module`)
  tests/           unittest tests of the calculation rules
  <modules>.py     your own code, always imported relatively: from .profile import naca4
  ui/              optional: your own UI (index.html, plus its JS and CSS)
  locales/         optional: translations, one <lang>.toml per language (en.toml)
  agent.md         optional: short instructions for the design agent on how to use your
                   blocks; it goes into the agent's prompt, up to 4000 characters
  fusion/          optional: code that runs inside Autodesk Fusion (the only place `adsk`
                   may be imported)
```

The folder name is the pack id. `__pycache__/`, `ui-src/`, `node_modules/`, `.git/` and
`.pyc` files are never part of the pack: `ui-src/` is the place for UI sources you compile
into `ui/`.

## `pack.toml`

```toml
id = "naca"                 # same as the folder: lowercase letters, digits and _, starting with a letter
name = "NACA airfoils"
version = "0.1.0"           # strict semver MAJOR.MINOR.PATCH, no pre-release
author = "Your name or company"
description = "What it does, in one sentence"
license = "LicenseRef-Proprietary"   # optional, see below
sdk = ">=1.0,<2"            # the SDK range it needs
module = "blocks"           # the module with register(pack); default "blocks"

[python]
dependencies = ["numpy>=2,<3"]   # PyPI requirements; [] if it only uses the standard library
# modules = ["yaml"]             # import names that differ from the distribution name

[requires]                  # other packs, only if you import their code or use their ports
# naca_base = ">=0.1,<0.2"

[ports]                     # optional: a colour for each of your port types
# "naca.profile" = "#3b82f6"

[ui]                        # optional: your own UI
# entry = "ui/index.html"
```

- `name`, `author` and `description` are required. `id`, `version` and `sdk` must be valid.
- `sdk`: a range of comma-separated conditions (`>=`, `<=`, `==`, `!=`, `>`, `<`). The app
  does not load a pack whose range excludes its SDK version. Within 1.x, minor versions only
  add API (see the changelog in
  [`boardprint_sdk/__init__.py`](../../app/backend/boardprint_sdk/__init__.py)); if you use
  something added later, raise the lower bound (for example `Param(choices={...})` needs
  `>=1.4`).
- `[requires]` values use the same range syntax.
- `[ports]` keys must start with `<id>.` and be registered with `pack.port`; colours are
  `#rrggbb`.
- `[ui] entry` must be a path inside `ui/`.
- `license`: not read by the loader today, it is metadata for people. Use an SPDX identifier
  (`Apache-2.0`, `MIT`) or `LicenseRef-…` for a proprietary license.

## The block contract

`register(pack)` receives a `PackBuilder` and declares what the pack adds:

- `pack.port(type, label)`: a port type.
- `pack.block(kind, title, run, inputs=, outputs=, params=, description=, preview=, …)`: a
  block. `inputs` and `outputs` map port names to port types.
- `pack.view(kind, card=, panel=)`: what the block's card and side panel show.
- `pack.template(id, title, blocks, links, description=)`: a ready-made chain of blocks.
- `pack.action(name, run, description=)`: something your own UI can call.
- `pack.connector(...)`: an external program the blocks work with, such as a CAD tool.

Everything a pack registers is prefixed with its id (`naca.profile4`, `naca.profile`), so two
packs can never collide.

A block is a function `run(params, inputs, ctx)`:

- `params`: `{name: value}`. Each parameter is declared as
  `Param(default, unit, label, choices=...)`; the type of the default is the type the card
  accepts (number, text, list or object). `choices` can be a tuple of values or
  `{value: label}`.
- `inputs`: `{input_port: {field: {"value", "unit", ...}}}`, the last output of the block
  connected to each input.
- `ctx`: a `RunContext`. Write output files only to `ctx.workdir`; report progress on long
  calculations with `ctx.progress(fraction, message)` and check `ctx.cancelled()`.
- It returns one payload per output port: `{output_port: {field: {"value", "unit",
  "label"?}}}`. Every field carries its unit (`""` if it has none).
- If something cannot be calculated, raise `ValueError` with the reason: that is what the
  engineer sees on the block. `ConfirmRequired(message, action, label)` asks the user to
  confirm before going on.
- `preview(params, inputs)` (optional) returns what the editor shows while parameters are being
  edited. It must be fast and pure: no files, no connectors.

**The rule of numbers.** No number without a source. What a block computes is its own source;
a value from a table or a standard says in the code where it comes from (a comment with the
standard or the book), and an estimate says so in its `label`. Do not invent coefficients.

## Generic controls

You do not need any UI code. `pack.view` takes a list of generic controls for the card and
the panel: `params`, `results`, `chart` and `view2d`. The last two draw output fields built
with the SDK helpers:

- `chart(x, y, curves, label=)`: an x-y chart, for example
  `chart(("Position", "mm"), ("Deflection", "mm"), {"F = 200 N": points})`.
- `view2d(x, y, items, label=, y_down=)`: a 2D view to scale, made of `box`, `line` and
  `point` items.

A tube block, for example, can draw its side view with `view2d`, and a cantilever block can
chart the deflection along the tube with `chart`.

## Minimal example

This is the pack the app's template creates (`app/backend/pizarra/pack_template/`), with the
placeholders filled in for an id `area_demo` and the module docstring left out. Block labels
are in Spanish, as in the template. It passes validation and its test as is.

`area_demo/pack.toml`:

```toml
id = "area_demo"
name = "Area demo"
version = "0.1.0"
author = "Agente de diseño"
description = "Area of a rectangle"
sdk = ">=1.0,<2"
module = "blocks"

[python]
dependencies = []
```

`area_demo/blocks.py`:

```python
from boardprint_sdk.packs import Param


def area(params, inputs, ctx):
    """Ejemplo: el área de un rectángulo. Sustitúyelo por el cálculo del paquete."""
    a = params["ancho"] * params["alto"]
    return {"resultado": {"area": {"value": a, "unit": "mm²", "label": "Área"}}}


def register(pack):
    pack.port("area_demo.resultado", "resultado")
    pack.block("area_demo.ejemplo", "Ejemplo", area,
               params={"ancho": Param(10.0, "mm", "Ancho"), "alto": Param(5.0, "mm", "Alto")},
               outputs={"resultado": "area_demo.resultado"},
               description="El área de un rectángulo (ejemplo de la plantilla)")
```

`area_demo/tests/test_blocks.py` (plus an empty `tests/__init__.py`):

```python
import os
import unittest
from pathlib import Path

from pizarra import packs

ROOT = Path(__file__).resolve().parents[2]
EXTRA = [d for d in os.environ.get("BOARDPRINT_TEST_PACKS", "").split(os.pathsep) if d]
REG = packs.load([str(ROOT), *EXTRA], log=lambda m: None)


def run(kind, **params):
    return REG[kind].run({**REG.default_params(kind), **params}, {}, packs.RunContext(block_id="t"))


class Ejemplo(unittest.TestCase):
    def test_el_area_es_ancho_por_alto(self):
        got = run("area_demo.ejemplo", ancho=4.0, alto=2.5)
        self.assertAlmostEqual(got["resultado"]["area"]["value"], 10.0)


if __name__ == "__main__":
    unittest.main()
```

`ROOT` is the folder that *contains* the pack, so keep each pack in a parent folder (for
example `mypacks/area_demo/`). `BOARDPRINT_TEST_PACKS` adds the folders of packs listed in
`[requires]`.

## Tests

Test the **rule**, not the code: "lift grows with the angle of attack until stall", "the
maximum thickness of a 0012 is 12 % of the chord". A test that repeats the formula of the code
proves nothing; use known cases (a textbook result, a limit case, a symmetry).

Tests may import only the standard library, your `[python] dependencies`, `boardprint_sdk`,
`pizarra.packs` and the pack itself. From a source checkout of BoardPrint (see *Build from
source* in the root README), run them from `app/backend` so `pizarra` is importable:

```bash
cd app/backend
../../.venv/Scripts/python -m unittest discover -s /path/to/mypacks/area_demo/tests -t /path/to/mypacks/area_demo/tests -v
```

That Python needs your pack's libraries installed. Inside the app, the design agent's
validation runs the tests in the packs environment, with them.

To try the pack in a development run of the app, set `BOARDPRINT_DEV_PACKS` to the parent
folder (several folders separated by the OS path separator) before starting the backend. It
is ignored by the installed app.

## Your own UI (optional)

If the generic controls are not enough, the pack can bring its own page: plain HTML, JS and
CSS in `ui/` (no build step needed), declared with `[ui] entry = "ui/index.html"`. In
`register`, `pack.view("<id>.<block>", card="ui")` puts it on the card, `panel="ui"` in a side
panel opened with *Edit*, or both.

It runs in an isolated `iframe` (`sandbox="allow-scripts"`, opaque origin) served with a
Content Security Policy without network: scripts, styles, images and fonts only from the
pack's own `ui/`, and `connect-src 'none'` (no `fetch`, WebSocket or CDN). It talks to the app
with `postMessage`, an object with `v: 1` and a `type`:

```js
const send = (m) => parent.postMessage({ v: 1, ...m }, "*");
window.addEventListener("message", (e) => {
  const m = e.data;
  if (m?.v !== 1) return;
  if (m.type === "init" || m.type === "update") draw(m);   // the state of its block
  if (m.type === "reply") resolve(m.id, m);                // {id, ok, result | error}
});
send({ type: "ready" });            // on load: the app answers with "init"
```

- `init` and `update` carry `params`, `specs` (each parameter's `default`, `unit`, `label`),
  `outputs`, `status`, `error`, `block` (`id`, `type`, `title`), `surface` (`card` or `panel`)
  and `theme`, plus `lang` (the app language, `es` or `en`) and `i18n` (your catalog for
  that language, see [Translating a pack](#translating-a-pack)).
- The page can send `setParams` `{params}` (same validation as the card), `run`, `preview`
  `{id, params}`, `action` `{id, name, args}` (one of its pack's `pack.action`s), `resize`
  `{height}`, `openPanel`, `closePanel` and `toast` `{text, kind: "info" | "error"}`.
- Figures shown by the page come from `outputs`, a `preview` or an `action`; the page never
  computes them itself.

## Translating a pack

Write the pack in one language and add a catalog per
extra language in `locales/<lang>.toml`: a flat table whose keys are the exact source texts
and whose values are their translations.

```toml
"Masa (kg)" = "Mass (kg)"
"Falla por {x} mm" = "Fails by {x} mm"
"{pieza} no cumple: {motivos}" = "{pieza} fails: {motivos}"
```

- A key with `{name}` placeholders (ASCII letters, digits and `_`) is a **pattern**: it
  matches the whole text, with any value in each placeholder (a value never spans `"; "`). The translation must use the
  same set of placeholders (in any order, repeated if needed). Other braces are plain text.
- The app translates **only what it shows**: block titles and descriptions, parameter labels
  and choice labels, port type labels, template and connector titles, port names, progress and
  error messages, and in the outputs the labels, group and column names (including those it
  derives from a key: `masa_kg` is shown as `Masa (kg)`, so translate `"Masa (kg)"`) and text
  cell values. Ids, keys, choice values and everything that travels along the arrows or back to
  your code are never translated: your code does not change.
- Lookup: an exact entry; else the first pattern that matches (most fixed text before the first
  placeholder first), with the captured values translated in turn (up to 3 levels); else, for a
  text like `a; b; c`, each part on its own; else the source text. Your catalog comes first,
  then those of the other loaded packs (a card can show texts produced by a pack it requires).
- In the source language (`es`) nothing is translated.
- Validation (export, install, proposal) rejects a catalog that is not a flat string table, an
  entry whose placeholders differ between key and value, a key made only of placeholders, and a
  file not named after a language. When a pack is loaded, a broken catalog is only a warning
  in the log: the bad entries are left out and the pack loads.

**Your own UI** gets the catalog in its state: `i18n`, a `{source: translation}` object (yours
merged over those of the other loaded packs; empty in the source language). Translate your
own texts with the same rules; a minimal version:

```js
const PH = /\{(\w+)\}/g;
function tr(i18n, text) {
  if (text in i18n) return i18n[text];
  for (const [key, value] of Object.entries(i18n)) {
    const names = [...key.matchAll(PH)].map((m) => m[1]);
    if (!names.length) continue;
    const re = new RegExp("^" + key.split(/\{\w+\}/).map((part) =>
      part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("((?:(?!; ).)+?)") + "$", "s");
    const m = re.exec(text);
    if (m) return value.replace(PH, (all, n) => m[names.indexOf(n) + 1] ?? all);
  }
  return text;
}
```

## Python libraries

Declare PyPI libraries in `[python] dependencies`. The app does not run pack code in its own
Python: it builds a separate *packs environment* with the bundled `uv` and the libraries
requested by the installed packs, and runs blocks in a worker process inside it. A pack whose
libraries cannot be downloaded, or conflict with those of the packs already installed, is not
installed, and the install summary says why.

## Exporting and installing a `.bppack`

A `.bppack` is a zip with a single folder `<id>/` holding the pack files, named
`<id>-<version>.bppack`. Exporting the same files twice gives the same bytes. Only a pack
that passes validation, with its `ui/` built, can be exported.

- **From the app:** *Settings → Packs*: *Export…* saves an installed pack as a `.bppack`, and
  installing from a file (or double-clicking a `.bppack`) shows a summary (blocks, libraries,
  author, the warning that it brings code) before anything is installed. A pack is installed
  for the user (the `packs` folder next to the settings file) or for the workspace
  (`<workspace>/.boardprint/packs`).
- **From a source checkout:** `pizarra.pack_install.export(folder, dest_dir)` writes the
  archive, the same code the app uses:

  ```bash
  cd app/backend
  ../../.venv/Scripts/python -c "import sys; from pizarra import pack_install; print(pack_install.export(sys.argv[1], sys.argv[2]))" /path/to/mypacks/area_demo /path/to/dist
  ```

You can also ask the design agent to write a pack: it works on a draft, validates it, runs its
tests and proposes it, and you decide whether to install it.

## What validation rejects

Validation runs when a pack is loaded, exported, installed or proposed. A pack that does not
pass is not loaded (the others still are). It rejects:

- An incomplete or inconsistent manifest: missing `name`, `author` or `description`; an id
  that is not the folder name; a version that is not semver; a missing `sdk` or one the app's
  SDK does not satisfy; a malformed `[requires]`, `[python]`, `[ports]` or `[ui]`; a missing
  `module` file or `[ui] entry`.
- Links (symbolic or junctions), files outside the pack folder, or more than 50 MB (without
  `ui-src/`).
- Imports, checked statically in every `.py`:
  - a library not listed in `[python] dependencies` (or `[python] modules`);
  - another pack not listed in `[requires]`, or imported other than as `pizarra_packs.<id>`;
  - the pack's own code imported absolutely: use relative imports (`from .module import x`);
    `tests/` is the exception;
  - the app backend (`pizarra`) outside `tests/`; from the app, only `boardprint_sdk` and
    `pizarra_engine.core` are allowed;
  - `adsk` outside `fusion/`; and code under `fusion/`, or anything it reaches, importing
    something other than the standard library, `adsk`, `pizarra_engine.core` and code that
    follows the same rule.

Loading then runs `register(pack)`, and a registration error also stops the pack: a name
without the `<id>.` prefix, a repeated block or port, a parameter that is not a `Param`, an
unknown control in `pack.view`, `"ui"` without `[ui] entry`, a `[ports]` type the pack does not
register, or a `[requires]` pack that does not load.

Dynamic imports (`importlib.import_module`) are not seen statically; registration and the
tests cover them. Network access and writing outside `ctx.workdir` are not blocked by the app
(the design agent's guide tells it not to do either). Pack code runs with your user's
permissions: install packs only from sources you trust.
