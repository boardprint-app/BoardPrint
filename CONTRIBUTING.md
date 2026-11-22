# Contributing to BoardPrint

> **BoardPrint is no longer maintained** and the repository is archived: issues and pull
> requests are not accepted. These notes stay for anyone who forks it.

## Sign your commits (DCO)

BoardPrint uses the [Developer Certificate of Origin](https://developercertificate.org)
instead of a CLA. Every commit must carry a `Signed-off-by` line, which certifies that you
wrote the change or have the right to submit it under the project's license (Apache-2.0):

```bash
git commit -s -m "Short description of the change"
```

This adds `Signed-off-by: Your Name <you@example.com>` with the name and email from your git
configuration. To sign off commits you already made: `git rebase --signoff main`.

## Set up and run the tests

You need Python 3.13 and Node 24 (and Rust only to build the desktop shell). See
*Build from source* in the [README](README.md).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r app/backend/requirements.txt   # bin/python on macOS/Linux
```

The tests, as the CI runs them ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), each
line from the repository root:

```bash
# Backend
cd app/backend && ../../.venv/Scripts/python -m unittest discover -s tests -t .

# Frontend: type checks and tests
cd app/frontend && npm ci && npx tsc -p . && npm test
```

The repository has no packs, so the backend tests that need one are skipped. A pack's own
tests live in the pack (see [`docs/packs/README.md`](docs/packs/README.md)).

A pull request with failing tests is not merged. Code that imports `adsk` only runs inside
Autodesk Fusion and is not tested in CI: say in the pull request how you checked it in Fusion.

## Project rules

These rules are not negotiable; they are what makes the numbers trustworthy.

- **No hand-entered dimensions.** Every dimension of a CAD model is an expression of a named
  parameter, never a typed number.
- **Calculation code never imports Fusion and has tests.** Calculations are pure Python,
  testable without Fusion. If a test fails, the change is not valid. Tests check the rule
  ("deflection grows with the cube of the length"), not a copy of the formula.
- **No number without a source.** Every figure comes from a block's calculation or from a
  cited source (a standard or a book, in a code comment). Estimates are labelled as such.
- **Units.** The Fusion API works in cm, kg and rad; only `fusion_io` converts. Every output
  field carries its unit.
- **The generic catalog is not manufacturer data.** Its values are orders of magnitude and
  must never be presented as a manufacturer's figures.
- **Each part lives in its own Fusion document.** The runner never writes to another document.
- **Small, focused changes.** Edit only the lines that need to change, one topic per pull
  request, and do not rewrite or delete whole functions or modules unless that is the point of
  the change (say so in the description). If a file grows past about 1000 lines, propose a
  split.
- **Tests first for complex logic.** Write tests that pin down the atomic rules before the
  logic that depends on them.

## Core or pack?

Domain features (a new kind of calculation, a component family, another CAD tool) belong in a
**pack**, not in the core, whenever possible. Packs are developed outside this repository;
see [`docs/packs/README.md`](docs/packs/README.md). Changes to the core are for things every
pack needs: the board, the SDK, execution, the agent, installation.

A change to the SDK's public surface (`app/backend/boardprint_sdk/`) follows semantic
versioning: adding raises the minor version, removing or changing a name or signature raises
the major one, and each change goes to the changelog in `boardprint_sdk/__init__.py`.

## Language

The project started as a personal tool in Spanish: internal names (`pizarra`, `paquete`), code
comments and docstrings are in Spanish. Follow the language of the file you edit. Issues, pull requests and review comments can be in English.

## Code of conduct and security

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Report security
problems privately, as explained in [SECURITY.md](SECURITY.md), not in a public issue.
