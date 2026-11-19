"""Genera THIRD_PARTY_NOTICES.md: lo de terceros que va dentro del instalador y sus licencias.

    .venv/Scripts/python.exe scripts/third_party_notices.py          # reescribe el fichero
    .venv/Scripts/python.exe scripts/third_party_notices.py --check  # falla si esta desfasado

Todo sale de los manifiestos y de los propios ficheros, nunca escrito a mano
(docs/PLAN_PUBLICACION.md §3):

- **Interfaz**: `app/frontend/package-lock.json` (las entradas que no son `dev`), con el autor y
  el repositorio de cada `node_modules/<pkg>/package.json`. Las fuentes de Excalidraw que copia
  `copy-fonts.mjs`, de la tabla `name` de cada `.woff2` (el Brotli lo descomprime `node`).
- **Shell (Rust)**: `cargo metadata` sobre `Cargo.lock`, para los objetivos del instalador
  (Windows y macOS). Solo las dependencias normales: ni las de compilacion ni las macros
  procedurales llegan al ejecutable. Sin `cargo`, se conserva la seccion que ya habia.
- **Backend (Python)**: el cierre de `app/backend/requirements.txt` con sus extras y marcadores,
  leido con `importlib.metadata` del Python que congela el sidecar. Por eso se ejecuta con el
  de `.venv` (o el del workflow App), no con cualquiera.
- **Ficheros aparte**: occt-import-js, el Python standalone y `uv` de `pyenv/`, el CLI de Claude
  Code, PyInstaller y el instalador NSIS, cada uno con lo que declaran sus ficheros.

Sin red, salvo la que `cargo metadata` necesite para descargar los manifiestos de crates.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from email.header import decode_header, make_header
from importlib import metadata
from pathlib import Path

try:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
except ImportError:  # pip lo trae vendorizado
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "THIRD_PARTY_NOTICES.md"
FRONTEND = ROOT / "app" / "frontend"
TAURI = ROOT / "app" / "shell" / "src-tauri"
REQUIREMENTS = ROOT / "app" / "backend" / "requirements.txt"
FONTS = FRONTEND / "node_modules" / "@excalidraw" / "excalidraw" / "dist" / "prod" / "fonts"
OCCT = FRONTEND / "node_modules" / "occt-import-js"
PYENV = TAURI / "pyenv"
NSIS = Path(os.environ.get("LOCALAPPDATA", "")) / "tauri" / "NSIS"

# Objetivos del instalador (.github/workflows/app.yml: windows-latest y, opcional, macos-latest).
RUST_TARGETS = ["x86_64-pc-windows-msvc", "aarch64-apple-darwin", "x86_64-apple-darwin"]

# uv va como binario suelto, sin metadatos: su licencia es la que declara su paquete en PyPI
# (`license_expression` de https://pypi.org/pypi/uv/<version>/json). Revisar al subir `UV` en
# app/shell/fetch_pyenv.py.
UV_LICENSE = "MIT OR Apache-2.0"
UV_SOURCE = "https://github.com/astral-sh/uv"

COPYLEFT = re.compile(r"\b(A?GPL|LGPL|MPL|EPL|CPL|CDDL|EUPL|OSL)\b|unknown|see ", re.I)

# Como se usa cada licencia a vigilar. Es explicacion, no dato de licencia.
USAGE = {
    "occt-import-js": "Not bundled into the JS: copied as separate, replaceable files "
                      "(`vendor/occt/occt-import-js.js` + `.wasm`) loaded at runtime by the STEP "
                      "viewer worker with `importScripts`, with both LGPL texts beside them "
                      "(`copy-occt.mjs`, plan D62). Unmodified upstream build.",
    "elkjs": "Bundled unmodified in the web UI as a transitive dependency of "
             "`@excalidraw/excalidraw` (via its Mermaid support). EPL-2.0 is weak, file-level "
             "copyleft: its source is the published npm package.",
    "Open CASCADE": "Compiled into `occt-import-js.wasm` and shipped with it as the same "
                    "separate, replaceable file (see occt-import-js).",
    "Native libraries of that CPython": "Shipped unmodified as part of that CPython build, "
                                        "but its LICENSE.txt does not include their license "
                                        "texts: add them here or confirm with upstream.",
    "Other native DLLs": "Picked up by PyInstaller from the build machine's PATH, not from "
                         "the interpreter or site-packages. "
                         "Check whether the CI build includes them and under which "
                         "redistribution terms.",
    "PyInstaller bootloader": "Only the bootloader is embedded in the sidecar executable; the "
                              "Bootloader exception allows distributing it with programs under "
                              "any license.",
    "NSIS": "The Windows installer stub (`setup.exe`). The LZMA module carries a special "
            "exception that allows linking without the CPL applying to the linked code.",
}


# --------------------------------------------------------------------------- utilidades


def md(text) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def spdx_from_text(text: str) -> str | None:
    """La licencia de un texto de licencia o de un campo de fuente: la que se nombra antes.

    Un texto de licencia empieza por la suya y despues cita otras (el LICENSE.txt de CPython
    lleva la PSF y luego la Apache de OpenSSL), asi que manda la posicion, no el orden de la lista.
    """
    t = " ".join(text.split())
    checks = [
        (r"SIL Open Font License,? Version 1\.1|openfontlicense\.org|scripts\.sil\.org/OFL",
         "OFL-1.1"),
        (r"GNU LESSER GENERAL PUBLIC LICENSE Version 2\.1", "LGPL-2.1"),
        (r"GNU LESSER GENERAL PUBLIC LICENSE Version 3", "LGPL-3.0"),
        (r"GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL-3.0"),
        (r"GNU GENERAL PUBLIC LICENSE Version 2", "GPL-2.0"),
        (r"GNU GENERAL PUBLIC LICENSE Version 3", "GPL-3.0"),
        (r"Mozilla Public License,? (Version|v\.?) ?2\.0", "MPL-2.0"),
        (r"Apache License,? Version 2\.0|apache\.org/licenses/LICENSE-2\.0", "Apache-2.0"),
        (r"PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2", "PSF-2.0"),
        (r"\bMIT License\b|Permission is hereby granted, free of charge", "MIT"),
        (r"Redistribution and use in source and binary forms", "BSD-style"),
        (r"Boost Software License", "BSL-1.0"),
        (r"The FreeType Project LICENSE", "FTL"),
        (r"\"Old MIT\" license", "MIT-Modern-Variant"),
        (r"PNG Reference Library License version 2", "libpng-2.0"),
        (r"This software is provided 'as-is', without any express or implied warranty", "Zlib"),
        (r"Permission to use, copy, modify, distribute, and sell this software", "libtiff"),
        (r"Independent JPEG Group", "IJG"),
        (r"SHARED/Apache-2\.0", "Apache-2.0"),  # los #include de pypdfium2
    ]
    found = [(m.start(), spdx) for pattern, spdx in checks
             for m in [re.search(pattern, t, re.I)] if m]
    return min(found)[1] if found else None


def norm_expr(expr: str) -> str:
    """`MIT/Apache-2.0` y `Apache-2.0 OR MIT` son lo mismo: un orden canonico para agrupar."""
    e = re.sub(r"\s*/\s*", " OR ", expr.strip())
    e = re.sub(r"\s+", " ", e)
    if "(" not in e and " AND " not in e and " WITH " not in e:
        e = " OR ".join(sorted(set(e.split(" OR ")), key=str.lower))
    return e


def needs_attention(lic: str) -> bool:
    return bool(COPYLEFT.search(lic or "unknown"))


def permissive_option(lic: str) -> str | None:
    """En una disyuncion sencilla, la alternativa permisiva (p. ej. `MPL-2.0 OR Apache-2.0`)."""
    e = lic.strip("() ")
    if " OR " not in e or " AND " in e or "(" in e:
        return None
    opts = [o for o in e.split(" OR ") if not COPYLEFT.search(o)]
    return " OR ".join(opts) if opts else None


def repo_url(repo) -> str:
    if isinstance(repo, dict):
        repo = repo.get("url", "")
    repo = (repo or "").strip()
    m = re.match(r"^(github|gitlab|bitbucket):(.+)$", repo)
    if m:
        return f"https://{m.group(1)}.{'org' if m.group(1) == 'bitbucket' else 'com'}/{m.group(2)}"
    if re.match(r"^[\w.-]+/[\w.-]+$", repo):
        return f"https://github.com/{repo}"
    repo = re.sub(r"^git\+", "", repo)
    repo = re.sub(r"^(git|ssh)://(git@)?", "https://", repo)
    repo = re.sub(r"^git@([^:]+):", r"https://\1/", repo)
    return re.sub(r"\.git$", "", repo)


def person(p) -> str:
    if isinstance(p, dict):
        return p.get("name", "")
    p = str(make_header(decode_header(p))) if p and "=?" in p else (p or "")
    return re.sub(r"\s*[<(].*$", "", p).strip().strip('"').strip()


# --------------------------------------------------------------------------- interfaz


def frontend():
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    if not (FRONTEND / "node_modules").exists():
        sys.exit("faltan app/frontend/node_modules: cd app/frontend && npm ci")
    rows = []
    for key, entry in lock["packages"].items():
        if not key or entry.get("dev") or entry.get("devOptional") or entry.get("link"):
            continue
        name = key.split("node_modules/")[-1]
        pj_path = FRONTEND / key / "package.json"
        pj = json.loads(pj_path.read_text(encoding="utf-8")) if pj_path.exists() else {}
        lic = entry.get("license") or pj.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type")
        if not lic and pj.get("licenses"):
            lic = " OR ".join(l.get("type", "?") if isinstance(l, dict) else l
                              for l in pj["licenses"])
        if not lic:
            for f in sorted((FRONTEND / key).glob("licen[cs]e*")) if pj_path.exists() else []:
                found = spdx_from_text(f.read_text(encoding="utf-8", errors="replace")[:3000])
                if found:
                    lic = f"{found} (from its {f.name} file)"
                    break
        url = repo_url(pj.get("repository")) or pj.get("homepage") or \
            f"https://www.npmjs.com/package/{name}"
        holder = person(pj.get("author"))
        note = " (optional, platform-specific)" if entry.get("optional") else ""
        rows.append({"name": name, "version": entry.get("version", "") + note,
                     "license": lic or "unknown",
                     "source": f"{holder}, {url}" if holder else url})
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def _base128(b: bytes, i: int):
    val = 0
    for _ in range(5):
        c = b[i]
        i += 1
        val = (val << 7) | (c & 0x7F)
        if not c & 0x80:
            return val, i
    raise ValueError("UIntBase128 demasiado largo")


def woff2_names(path: Path) -> dict[int, str]:
    """Los registros de la tabla `name` de un .woff2 (0 copyright, 1 familia, 13/14 licencia)."""
    b = path.read_bytes()
    if b[:4] != b"wOF2":
        raise ValueError(f"{path.name} no es WOFF2")
    num_tables, = struct.unpack(">H", b[12:14])
    compressed_len, = struct.unpack(">I", b[20:24])
    off, entries = 48, []
    for _ in range(num_tables):
        flags = b[off]
        off += 1
        idx, ver = flags & 0x3F, flags >> 6
        if idx == 63:
            off += 4
        length, off = _base128(b, off)
        if (ver == 0) if idx in (10, 11) else (ver != 0):  # glyf/loca: version 0 = transformada
            length, off = _base128(b, off)
        entries.append((idx, length))
    node = shutil.which("node")
    if not node:
        raise RuntimeError("hace falta node para descomprimir el Brotli de las fuentes")
    data = subprocess.run(
        [node, "-e", "process.stdout.write(require('zlib').brotliDecompressSync("
                     "require('fs').readFileSync(0)))"],
        input=b[off:off + compressed_len], capture_output=True, check=True).stdout
    pos = 0
    for idx, length in entries:
        if idx == 5:
            name = data[pos:pos + length]
            break
        pos += length
    else:
        return {}
    _, count, str_off = struct.unpack(">HHH", name[:6])
    out: dict[int, tuple[int, str]] = {}
    for r in range(count):
        plat, enc, lang, nid, ln, so = struct.unpack(">6H", name[6 + 12 * r:18 + 12 * r])
        raw = name[str_off + so:str_off + so + ln]
        if plat == 3:
            text, rank = raw.decode("utf-16-be", errors="replace"), 0 if lang == 0x409 else 1
        elif plat == 1:
            text, rank = raw.decode("mac_roman"), 2
        else:
            continue
        if nid not in out or rank < out[nid][0]:
            out[nid] = (rank, text.strip())
    return {k: v for k, (_, v) in out.items()}


def fonts():
    rows = []
    if not FONTS.exists():
        return rows
    for family in sorted(p for p in FONTS.iterdir() if p.is_dir()):
        files = sorted(family.glob("*.woff2"))
        if not files:
            continue
        names = woff2_names(files[0])
        notice = names.get(0) or ""
        lic_text = " ".join(filter(None, [names.get(13), names.get(14)]))
        # Hay fuentes que meten el texto de la licencia en el aviso de copyright (ID 0).
        lic = spdx_from_text(lic_text) if lic_text else spdx_from_text(notice)
        if not lic:
            lic = (f"unknown (font says: \"{' '.join(lic_text.split())[:220]}\")" if lic_text
                   else "unknown (the font has no license record)")
        holders = [l.strip() for l in notice.splitlines()
                   if re.match(r"\s*(copyright|\(c\)|©|digitized)", l, re.I)]
        rows.append({"name": family.name,
                     "version": names.get(5, ""), "files": len(files), "license": lic,
                     "source": "; ".join(holders) or " ".join(notice.split())[:200]})
    return rows


# --------------------------------------------------------------------------- shell (Rust)


def rust():
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    cmd = [cargo, "metadata", "--format-version", "1", "--locked"]
    for t in RUST_TARGETS:
        cmd += ["--filter-platform", t]
    try:
        out = subprocess.run(cmd, cwd=TAURI, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"aviso: cargo metadata no ha funcionado ({e}); se conserva la seccion de Rust",
              file=sys.stderr)
        return None
    meta = json.loads(out.decode("utf-8"))
    pkgs = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    root = meta["resolve"]["root"]

    def proc_macro(pid):
        return any("proc-macro" in t["kind"] for t in pkgs[pid]["targets"])

    seen, stack = set(), [root]
    while stack:
        pid = stack.pop()
        for dep in nodes[pid]["deps"]:
            normal = any(k["kind"] is None for k in dep["dep_kinds"])
            if normal and dep["pkg"] not in seen and not proc_macro(dep["pkg"]):
                seen.add(dep["pkg"])
                stack.append(dep["pkg"])
    crates = sorted((pkgs[p] for p in seen), key=lambda p: (p["name"], p["version"]))
    groups: dict[str, list] = {}
    for c in crates:
        lic = norm_expr(c.get("license") or "") if c.get("license") else \
            ("see " + c["license_file"] if c.get("license_file") else "unknown")
        groups.setdefault(lic, []).append(c)
    return crates, groups


# --------------------------------------------------------------------------- backend (Python)


def read_requirements(path: Path) -> list[str]:
    reqs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r"):
            reqs += read_requirements(path.parent / line[2:].strip())
        elif not line.startswith("-"):
            reqs.append(line)
    return reqs


def other_platform_envs():
    win = {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt",
           "platform_machine": "AMD64"}
    mac = {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix",
           "platform_machine": "arm64"}
    return [("macOS", mac)] if sys.platform == "win32" else [("Windows", win)]


def dist_text(f) -> str:
    """El texto de un fichero de una distribucion instalada (PackagePath)."""
    return Path(f.locate()).read_text(encoding="utf-8", errors="replace")


def py_license(dist) -> str:
    m = dist.metadata
    if m.get("License-Expression"):
        return m["License-Expression"].strip()
    lic = (m.get("License") or "").strip()
    if lic and len(lic) <= 60 and "\n" not in lic and lic.upper() != "UNKNOWN":
        return lic
    classifiers = [c.split(" :: ")[-1] for c in m.get_all("Classifier") or []
                   if c.startswith("License ::")]
    if classifiers:
        short = {"MIT License": "MIT", "Apache Software License": "Apache",
                 "BSD License": "BSD", "Python Software Foundation License": "PSF"}
        return " OR ".join(short.get(c, c) for c in classifiers) + " (classifier)"
    for f in dist.files or []:
        if re.search(r"(LICEN[CS]E|COPYING)", f.name, re.I):
            found = spdx_from_text(dist_text(f)[:3000])
            if found:
                return f"{found} (from its {f.name} file)"
    if lic:
        found = spdx_from_text(lic[:3000])
        if found:
            return f"{found} (from its License field)"
    return "unknown"


def py_source(dist) -> str:
    m = dist.metadata
    holder = person(m.get("Author") or "") or person(m.get("Author-email") or "") or \
        person(m.get("Maintainer") or "") or person(m.get("Maintainer-email") or "")
    urls = {}
    for u in m.get_all("Project-URL") or []:
        label, _, url = u.partition(",")
        urls[label.strip().lower()] = url.strip()
    url = next((urls[k] for k in ("source", "source code", "code", "repository", "github",
                                  "homepage", "home")
                if k in urls), None) or m.get("Home-page") or \
        next(iter(urls.values()), None) or f"https://pypi.org/project/{m['Name']}/"
    return f"{holder}, {url}" if holder else url


def python_deps():
    seen: dict[str, dict] = {}
    done: set[tuple[str, str]] = set()
    skipped: list[tuple[str, str, str]] = []
    queue = [(Requirement(r), "requirements.txt") for r in read_requirements(REQUIREMENTS)]
    while queue:
        req, parent = queue.pop(0)
        key = canonicalize_name(req.name)
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            sys.exit(f"{req.name} no esta instalado en {sys.executable}: ejecuta el script con "
                     "el Python que congela el sidecar (.venv con app/backend/requirements.txt)")
        if key not in seen:
            # Una rueda con binarios de terceros dentro (pypdfium2 trae PDFium) deja sus
            # licencias en licenses/BUILD_LICENSES/; las de otras plataformas van en subcarpetas.
            bundled = []
            for f in dist.files or []:
                if len(f.parts) == 4 and f.parts[2] == "BUILD_LICENSES":
                    spdx = spdx_from_text(dist_text(f))
                    bundled.append(f"{f.name} ({spdx})" if spdx else f.name)
            bundled = sorted(set(bundled))
            seen[key] = {"name": dist.metadata["Name"], "version": dist.version,
                         "license": py_license(dist), "source": py_source(dist),
                         "bundled": bundled}
        for extra in sorted(req.extras) + [""]:
            if (key, extra) in done:
                continue
            done.add((key, extra))
            for spec in dist.requires or []:
                child = Requirement(spec)
                env = {"extra": extra}
                if child.marker is None or child.marker.evaluate(env):
                    queue.append((child, dist.metadata["Name"]))
                elif any(child.marker.evaluate({**default_environment(), **e, "extra": extra})
                         for _, e in other_platform_envs()):
                    where = ", ".join(n for n, e in other_platform_envs()
                                      if child.marker.evaluate({**default_environment(), **e,
                                                                "extra": extra}))
                    skipped.append((child.name, where, dist.metadata["Name"]))
    rows = sorted(seen.values(), key=lambda r: r["name"].lower())
    return rows, sorted(set(skipped))


# --------------------------------------------------------------------------- ficheros aparte


def first_match(path: Path, pattern: bytes, chunk=64 << 20) -> str | None:
    """Busca un patron en un binario grande, por trozos."""
    rx = re.compile(pattern)
    with path.open("rb") as f:
        tail = b""
        while True:
            block = f.read(chunk)
            if not block:
                return None
            m = rx.search(tail + block)
            if m:
                return m.group(0).decode("utf-8", errors="replace")
            tail = block[-4096:]


# El componente detras de cada DLL nativa de CPython, para buscarlo en su LICENSE.txt.
DLL_COMPONENT = {"libcrypto": "OpenSSL", "libssl": "OpenSSL", "libffi": "libffi",
                 "sqlite3": "SQLite", "zlib1": "zlib", "tcl86t": "Tcl", "tk86t": "Tk",
                 "liblzma": "xz", "libbz2": "bzip2", "libexpat": "expat", "libmpdec": "mpdecimal"}


def dll_component(path: Path) -> str:
    stem = re.sub(r"(-\d+)?(-x64|-arm64)?$", "", path.stem.lower())
    return DLL_COMPONENT.get(stem, stem)


def sidecar_binaries() -> list[Path] | None:
    """Los binarios nativos que PyInstaller metio en el sidecar, si esta compilado aqui."""
    toc = ROOT / "out" / "build_sidecar" / "work" / "pizarra-backend" / "PKG-00.toc"
    if not toc.exists():
        return None
    entries = ast.literal_eval(toc.read_text(encoding="utf-8"))[2]
    return sorted({Path(src) for _, src, kind in entries if kind == "BINARY"})


def cpython_rows(name, version, lic_txt, dlls, where, source, note, origin=None):
    """Un CPython: su licencia y las DLL suyas que su LICENSE.txt no cubre."""
    text = lic_txt.read_text(encoding="utf-8", errors="replace") if lic_txt.exists() else ""
    names = sorted(set(DLL_COMPONENT.values()))
    covered = [c for c in names if re.search(rf"\b{re.escape(c)}\b", text, re.I)]
    also = covered + (["Microsoft Distributable Code (`vcruntime140*.dll`)"]
                      if "Microsoft Distributable Code" in text else [])
    rows = [{"name": name, "version": version, "license": spdx_from_text(text) or "unknown",
             "source": source, "where": where,
             "note": note + (" and also covers " + ", ".join(also) if also else "") + "."}]
    own = [d for d in dlls if not d.name.lower().startswith(("python", "vcruntime"))]
    missing = [d for d in own if dll_component(d) not in covered]
    if missing:
        rows.append({"name": f"Native libraries of that CPython ({version})",
                     "version": "as built upstream",
                     "license": "unknown (not stated in its LICENSE.txt)", "source": source,
                     "where": where,
                     "note": "Files: " + ", ".join(f"`{d.name}` ({dll_component(d)})"
                                                   for d in missing)
                             + (f"; list taken from {origin}" if origin else "") + "."})
    return rows


def shipped():
    rows = []
    # occt-import-js (y OpenCASCADE dentro de su .wasm)
    pj = json.loads((OCCT / "package.json").read_text(encoding="utf-8"))
    lic_files = {f.name: spdx_from_text(f.read_text(encoding="utf-8")[:3000])
                 for f in sorted((OCCT / "dist").glob("license*.txt"))}
    rows.append({"name": "occt-import-js (`occt-import-js.js`, `occt-import-js.wasm`)",
                 "version": pj["version"], "license": pj.get("license", "unknown"),
                 "source": repo_url(pj.get("repository")),
                 "where": "web UI, `vendor/occt/`",
                 "note": "License texts shipped beside it: " + ", ".join(
                     f"`{k}` ({v})" for k, v in lic_files.items())})
    if "license.occt.txt" in lic_files:
        rows.append({"name": "Open CASCADE Technology (compiled into `occt-import-js.wasm`)",
                     "version": "as built by occt-import-js " + pj["version"],
                     "license": lic_files["license.occt.txt"] or "unknown",
                     "source": "https://dev.opencascade.org", "where": "web UI, `vendor/occt/`",
                     "note": "License text: `license.occt.txt`"})

    # Python standalone de los paquetes
    pyenv = json.loads((PYENV / "pyenv.json").read_text(encoding="utf-8")) \
        if (PYENV / "pyenv.json").exists() else {}
    if (PYENV / "python").exists():
        rows += cpython_rows(
            "CPython, python-build-standalone `install_only_stripped`", pyenv.get("python", "?"),
            PYENV / "python" / "LICENSE.txt", sorted((PYENV / "python" / "DLLs").glob("*.dll")),
            "`pyenv/python/`", "https://github.com/astral-sh/python-build-standalone",
            "Its `LICENSE.txt` ships with it")
    rows.append({"name": "uv", "version": pyenv.get("uv", "?"), "license": UV_LICENSE,
                 "source": UV_SOURCE, "where": "`pyenv/uv[.exe]`",
                 "note": "Standalone binary; license as declared by its PyPI package "
                         "(`license_expression`)."})

    # Claude Code CLI, que trae el Agent SDK
    sdk = metadata.distribution("claude-agent-sdk")
    cli_version = "?"
    vfile = Path(sdk.locate_file("claude_agent_sdk/_cli_version.py"))
    if vfile.exists():
        m = re.search(r"__cli_version__\s*=\s*\"([^\"]+)\"", vfile.read_text(encoding="utf-8"))
        cli_version = m.group(1) if m else "?"
    cli = next((p for p in [TAURI / "claude-cli" / "claude.exe", TAURI / "claude-cli" / "claude",
                            Path(sdk.locate_file("claude_agent_sdk/_bundled/claude.exe")),
                            Path(sdk.locate_file("claude_agent_sdk/_bundled/claude"))]
                if p.exists()), None)
    terms = first_match(cli, rb"\(c\) Anthropic PBC\. All rights reserved\.[^\n\"'`]{0,200}") \
        if cli else None
    rows.append({"name": "Claude Code CLI (bundled by the Claude Agent SDK)",
                 "version": cli_version,
                 "license": "Proprietary: Anthropic's own terms (no SPDX license)",
                 "source": "https://code.claude.com/docs/en/legal-and-compliance",
                 "where": "`claude-cli/claude[.exe]`",
                 "note": f"The binary states: \"{terms.strip()}\"" if terms else
                         "Notice not found in the binary on this machine."})
    readme = sdk.metadata.get_payload() or ""
    m = re.search(r"## License and terms\s+(.+?)(\n#|\Z)", readme, re.S)
    if m:
        rows.append({"name": "Claude Agent SDK terms of use", "version": sdk.version,
                     "license": f"{py_license(sdk)} code; use governed by Anthropic's terms",
                     "source": py_source(sdk), "where": "backend sidecar",
                     "note": "Its README: \"" + " ".join(m.group(1).split()) + "\""})

    # Lo que PyInstaller mete en el sidecar ademas de las librerias: el interprete con el que
    # corre build_sidecar.py y sus DLL. Con el sidecar ya compilado, la lista exacta sale de su
    # tabla de contenidos (PKG-00.toc); si no, de la carpeta DLLs del interprete.
    base = Path(sys.base_prefix)
    binaries = sidecar_binaries()
    from_toc = binaries is not None
    if binaries is None:
        binaries = sorted((base / "DLLs").glob("*.dll"))
    inside = [b for b in binaries if base in b.parents]
    rows += cpython_rows(
        "CPython interpreter frozen into the sidecar",
        ".".join(map(str, sys.version_info[:3])), base / "LICENSE.txt", inside,
        "`pizarra-backend` sidecar", "https://www.python.org",
        "The interpreter that runs `build_sidecar.py`; its `LICENSE.txt` is not copied into "
        "the sidecar", "PyInstaller's build table of contents" if from_toc else
        "the interpreter's `DLLs/` folder (sidecar not built on this machine)")
    venv = Path(sys.prefix)
    others = [b for b in binaries if base not in b.parents and venv not in b.parents]
    if others:
        folders = sorted({str(b.parent.name) for b in others})
        rows.append({"name": "Other native DLLs PyInstaller picked up from the build machine",
                     "version": f"{len(others)} files",
                     "license": "unknown (no license file with them)",
                     "source": "build machine: " + ", ".join(f"`{f}`" for f in folders),
                     "where": "`pizarra-backend` sidecar",
                     "note": "Files: " + ", ".join(f"`{b.name}`" for b in others)})
    try:
        pyi = metadata.distribution("pyinstaller")
        copying = next((f for f in pyi.files or [] if f.name == "COPYING.txt"), None)
        spdx = None
        if copying:
            m = re.search(r"SPDX-License-Identifier:\s*(.+)", copying.read_text(encoding="utf-8"))
            spdx = m.group(1).strip().strip("()") if m else None
        rows.append({"name": "PyInstaller bootloader", "version": pyi.version,
                     "license": spdx or py_license(pyi), "source": py_source(pyi),
                     "where": "`pizarra-backend` sidecar", "note": "Build tool; only its "
                     "bootloader ends up in the executable."})
    except metadata.PackageNotFoundError:
        pass

    # NSIS, el instalador de Windows (Tauri lo descarga en %LOCALAPPDATA%\tauri\NSIS)
    copying = NSIS / "COPYING"
    if copying.exists():
        text = copying.read_text(encoding="utf-8", errors="replace")
        parts = []
        for label, rx in [("Zlib", r"zlib/libpng license"), ("bzip2-1.0.6", r"bzip2 license"),
                          ("CPL-1.0", r"Common Public License version 1\.0")]:
            if re.search(rx, text, re.I):
                parts.append(label)
        version = "?"
        makensis = NSIS / "makensis.exe"
        if makensis.exists():
            try:
                version = subprocess.run([str(makensis), "/VERSION"], capture_output=True,
                                         text=True, timeout=30).stdout.strip() or "?"
            except (OSError, subprocess.SubprocessError):
                pass
        rows.append({"name": "NSIS", "version": version, "license": " AND ".join(parts),
                     "source": "https://nsis.sourceforge.io", "where": "Windows `setup.exe`",
                     "note": "Per its COPYING: zlib/libpng for NSIS itself, bzip2 license for "
                             "the bzip2 module, CPL-1.0 (with a linking exception) for LZMA."})
    return rows


# --------------------------------------------------------------------------- render


def table(rows, cols):
    head = "| " + " | ".join(c for c, _ in cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(md(r[k]) for _, k in cols) + " |\n" for r in rows)


def keep_section(name: str) -> str:
    if OUT.exists():
        m = re.search(rf"<!-- {name}:start -->\n(.*?)<!-- {name}:end -->",
                      OUT.read_text(encoding="utf-8"), re.S)
        if m:
            return m.group(1)
    return "_Not generated: `cargo metadata` was not available._\n\n"


def render() -> str:
    fe, fo, sh = frontend(), fonts(), shipped()
    py, py_skipped = python_deps()
    rs = rust()
    attention = []

    shipped_names = [r["name"] for r in sh]
    for r in fe:  # lo que tambien va como fichero aparte sale en esa seccion, no dos veces
        if needs_attention(r["license"]) and not any(n.startswith(r["name"] + " ")
                                                     for n in shipped_names):
            attention.append(("Web UI (npm)", r["name"], r["version"], r["license"]))
    for r in fo:
        if needs_attention(r["license"]):
            attention.append(("Web UI fonts", r["name"], r["version"], r["license"]))
    for r in py:
        if needs_attention(r["license"]) or r["bundled"]:
            attention.append(("Backend (Python)", r["name"], r["version"], r["license"]))
            if r["bundled"]:
                USAGE[r["name"]] = (
                    "The wheel ships a prebuilt native library frozen into the sidecar. Licenses "
                    "of what that library bundles, from the wheel's `licenses/BUILD_LICENSES/`: "
                    + ", ".join(r["bundled"]) + ".")
    for r in sh:
        if needs_attention(r["license"]):
            attention.append(("Separately shipped", r["name"], r["version"], r["license"]))

    s = [
        "# Third-party notices\n\n",
        "BoardPrint itself is licensed under the Apache License 2.0 (see `LICENSE` and "
        "`NOTICE`). This file lists the third-party components that are **bundled inside the "
        "desktop installer**, with the license each one declares and its copyright holder or "
        "project URL where its manifest gives one. Development-only tools (devDependencies, "
        "Rust build-dependencies and procedural macros, test runners) are not shipped and are "
        "not listed.\n\n",
        "This file is generated by `scripts/third_party_notices.py` from the manifests and "
        "lockfiles (`app/frontend/package-lock.json`, `app/shell/src-tauri/Cargo.lock` via "
        "`cargo metadata`, the installed metadata of `app/backend/requirements.txt`) and from "
        "the shipped files themselves. Do not edit it by hand: run "
        "`.venv/Scripts/python.exe scripts/third_party_notices.py` after changing dependencies "
        "(`--check` fails if it is out of date). Licenses are reported as declared by each "
        "package; the full license texts are in each package's distribution.\n\n",
        "## Contents\n\n",
        f"- Web UI (npm, production dependency closure): {len(fe)} packages\n",
        f"- Web UI fonts (copied from Excalidraw): {len(fo)} families\n",
    ]
    if rs:
        s.append(f"- Desktop shell (Rust crates linked into the executable): {len(rs[0])} crates "
                 f"in {len(rs[1])} license groups\n")
    s += [f"- Backend sidecar (Python packages frozen by PyInstaller): {len(py)} packages\n",
          f"- Separately shipped binaries and assets: {len(sh)} entries\n\n"]

    s += ["## Web UI (npm)\n\n",
          "The React/Vite interface (`app/frontend`), served by the backend sidecar. Listed: "
          "every non-dev package in `package-lock.json`, i.e. the production dependency "
          "closure of `package.json` (a superset of what Vite actually bundles).\n\n",
          table(fe, [("Component", "name"), ("Version", "version"), ("License", "license"),
                     ("Source", "source")]), "\n"]

    s += ["### Fonts\n\n",
          "Copied unmodified from `@excalidraw/excalidraw` to `public/fonts/` by "
          "`scripts/copy-fonts.mjs` so the app works offline. License and copyright are read "
          "from each font's `name` table (IDs 0, 13 and 14).\n\n",
          table(fo, [("Font family", "name"), ("Version", "version"), ("Files", "files"),
                     ("License", "license"), ("Copyright", "source")]), "\n"]

    s.append("## Desktop shell (Rust)\n\n<!-- rust:start -->\n")
    if rs:
        crates, groups = rs
        s.append("Crates statically linked into the Tauri executable (`app/shell/src-tauri`), "
                 "from `cargo metadata` over `Cargo.lock` for the installer targets ("
                 + ", ".join(f"`{t}`" for t in RUST_TARGETS) + "): normal dependencies only. "
                 "Each crate's source and authors are at `https://crates.io/crates/<name>`.\n\n"
                 "| License | Crates | Names |\n|---|---|---|\n")
        for lic in sorted(groups, key=lambda k: (-len(groups[k]), k)):
            names = ", ".join(f"{c['name']} {c['version']}" for c in groups[lic])
            s.append(f"| {md(lic)} | {len(groups[lic])} | {md(names)} |\n")
            if needs_attention(lic):
                for c in groups[lic]:
                    attention.append(("Desktop shell (Rust)", c["name"], c["version"], lic))
        s.append("\n")
    else:
        s.append(keep_section("rust"))
        for m in re.finditer(r"^\| (.+?) \| \d+ \| (.+?) \|$", keep_section("rust"), re.M):
            if needs_attention(m.group(1)):
                for nv in m.group(2).split(", "):
                    n, _, v = nv.partition(" ")
                    attention.append(("Desktop shell (Rust)", n, v, m.group(1)))
    s.append("<!-- rust:end -->\n")

    s += ["## Backend sidecar (Python)\n\n",
          "Packages frozen into the `pizarra-backend` executable by PyInstaller: the closure of "
          "`app/backend/requirements.txt` (with `requirements-base.txt` and extras such as "
          "`uvicorn[standard]`), resolved from the installed metadata of the Python that builds "
          "the sidecar.\n\n",
          table(py, [("Component", "name"), ("Version", "version"), ("License", "license"),
                     ("Source", "source")]), "\n"]
    if py_skipped:
        s.append("Not installed on the platform this file was generated on, but pulled in by "
                 "environment markers on the other installer platform (their licenses are not "
                 "listed above): "
                 + "; ".join(f"`{n}` ({w}, required by {p})" for n, w, p in py_skipped)
                 + ".\n\n")

    s += ["## Separately shipped binaries and assets\n\n",
          "Files copied into the installer as resources next to the executables "
          "(`tauri.conf.json` `bundle.resources` / `externalBin`, `app/shell/build_sidecar.py`, "
          "`app/shell/fetch_pyenv.py`, `app/frontend/scripts/copy-occt.mjs`), plus what the "
          "build tools embed.\n\n",
          table(sh, [("Component", "name"), ("Version", "version"), ("License", "license"),
                     ("Location", "where"), ("Source", "source"), ("Notes", "note")]), "\n"]

    s.append("## Licenses that need attention\n\n"
             "Copyleft (GPL, LGPL, AGPL, MPL, EPL, CPL) or undetermined licenses among the "
             "components above, and how each one is used.\n\n"
             "| Layer | Component | Version | License | How it is used |\n|---|---|---|---|---|\n")
    for layer, name, version, lic in attention:
        usage = USAGE.get(name) or next((v for k, v in USAGE.items() if name.startswith(k)), None)
        alt = permissive_option(lic)
        if not usage:
            if alt:
                usage = f"Dual-licensed: used under the permissive option ({alt})."
            elif layer == "Desktop shell (Rust)":
                usage = ("Statically linked, unmodified, into the shell executable. MPL-2.0 is "
                         "file-level copyleft: its source is the published crate."
                         if "MPL" in lic else "Statically linked, unmodified, into the shell.")
            elif layer == "Web UI fonts":
                usage = ("Font files copied unmodified from the MIT-licensed "
                         "`@excalidraw/excalidraw` package, but the font itself declares no "
                         "license: confirm with upstream.")
            elif "unknown" in lic.lower():
                usage = "License not declared in the shipped metadata: check upstream."
            else:
                usage = "Bundled unmodified."
        elif alt:
            usage = f"Dual-licensed: used under the permissive option ({alt}). " + usage
        s.append(f"| {md(layer)} | {md(name)} | {md(version)} | {md(lic)} | {md(usage)} |\n")
    return "".join(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="falla si el fichero esta desfasado")
    args = ap.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            sys.exit(f"{OUT.name} esta desfasado: python scripts/third_party_notices.py")
        print(f"{OUT.name} al dia")
        return
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"{OUT.relative_to(ROOT)} escrito")


if __name__ == "__main__":
    main()
