"""Una sola fuente para la versión de la app (docs/PLAN_V020.md V12).

    python scripts/set_version.py 0.2.0      # la escribe en todos los manifiestos
    python scripts/set_version.py            # dice la de cada uno

Escribe solo la línea de la versión de cada fichero (la de la app, nunca la de una
dependencia que valga lo mismo): `tauri.conf.json`, `Cargo.toml`, `Cargo.lock`, los dos
`package.json` y sus `package-lock.json`. La usa el workflow App con su entrada `version`.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SEMVER = re.compile(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?")

# {fichero: [lo que va delante del valor en la línea de la versión]}; cada una se sustituye una
# sola vez, en su primera aparición (en un package-lock.json, la raíz y su `packages[""]`).
_TOP, _LOCK, _CARGO = r'(?m)^(  "version": ")', r'(?m)^(      "version": ")', r'(?m)^(version = ")'
_RULES = {
    "app/shell/src-tauri/tauri.conf.json": [_TOP],
    "app/shell/src-tauri/Cargo.toml": [_CARGO],
    "app/shell/src-tauri/Cargo.lock": [r'(name = "pizarra-shell"\r?\nversion = ")'],
    "app/shell/package.json": [_TOP],
    "app/shell/package-lock.json": [_TOP, _LOCK],
    "app/frontend/package.json": [_TOP],
    "app/frontend/package-lock.json": [_TOP, _LOCK],
}
_VALUE = r'([^"]*)(")'
FILES = tuple(_RULES)


def current(root=REPO):
    """{fichero: versión}, la de su primera regla."""
    out = {}
    for rel, rules in _RULES.items():
        text = (Path(root) / rel).read_text(encoding="utf-8")
        m = re.search(rules[0] + _VALUE, text)
        out[rel] = m.group(2) if m else None
    return out


def write(root, version):
    if not _SEMVER.fullmatch(version):
        raise ValueError(f"no es una versión X.Y.Z: {version!r}")
    for rel, rules in _RULES.items():
        path = Path(root) / rel
        raw = path.read_bytes().decode("utf-8")
        for rule in rules:
            raw, n = re.subn(rule + _VALUE, lambda m: m.group(1) + version + m.group(3), raw,
                             count=1)
            if n != 1:
                raise ValueError(f"{rel}: no encuentro la línea de la versión ({rule})")
        path.write_bytes(raw.encode("utf-8"))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        write(REPO, sys.argv[1])
    for rel, v in current(REPO).items():
        print(f"{v}\t{rel}")
