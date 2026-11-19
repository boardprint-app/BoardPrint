"""Descarga el Python y el `uv` que la app lleva como recursos (docs/PLAN_PAQUETES.md P21).

    python app/shell/fetch_pyenv.py [--triple x86_64-pc-windows-msvc]

Deja `app/shell/src-tauri/pyenv/` con:

- `python/`: CPython standalone (python-build-standalone, `install_only_stripped`), sin
  librerías. Es el Python del *entorno de paquetes* (P19): los bloques corren en él, nunca en
  el del ejecutable de PyInstaller.
- `uv[.exe]`: crea los entornos de paquetes y les instala sus librerías (P20).
- `pyenv.json`: qué versiones son. Entra en la huella de cada entorno: si la app trae otro
  Python, los entornos se rehacen.

Versiones fijadas con su sha256 (de la API de GitHub de cada release). Se eligen releases con
unas semanas, no la de la semana. Para subir de versión: cambiar `PYTHON`/`UV` y las sumas.

Se quita lo que un paquete no usa y pesa (tkinter, Tcl/Tk, IDLE, los tests): la interfaz de
un paquete es una página web (P24), no una ventana.
"""
import argparse
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sidecar import host_triple  # noqa: E402

OUT = Path(__file__).resolve().parent / "src-tauri" / "pyenv"

PYTHON = "3.13.18+20261026"
PYTHON_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
              "{tag}/cpython-{ver}-{triple}-install_only_stripped.tar.gz")
PYTHON_SHA256 = {
    "x86_64-pc-windows-msvc": "7369f7a35f261222a6ac8b3a87c1c88eeebee8af945d85346202591a64038dd3",
    "aarch64-apple-darwin": "8392b6ea51d94391befb2c31ebe75463f045d0b69dfcf5e1bb3234e1f5fa3405",
    "x86_64-apple-darwin": "7412c19d896c99431b74a18a5643e110449a7f9590fbab179c3e5ab27b9aa9e3",
}

UV = "0.13.6"
UV_URL = "https://github.com/astral-sh/uv/releases/download/{ver}/uv-{triple}.{ext}"
UV_SHA256 = {
    "x86_64-pc-windows-msvc": "a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f",
    "aarch64-apple-darwin": "60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472",
    "x86_64-apple-darwin": "63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02",
}

# Patrones (glob, relativos a python/) que no se llevan. pip tampoco: lo hace `uv`, y así el
# Python va sin librerías (P21). Una lista por sistema: en Windows el glob no distingue
# mayúsculas y `lib/thread*` de macOS se llevaría `Lib/threading.py`.
PRUNE = {
    "windows": ["tcl", "Lib/tkinter", "Lib/idlelib", "Lib/turtledemo", "Lib/test",
                "Lib/ensurepip", "Lib/site-packages/pip", "Lib/site-packages/pip-*",
                "DLLs/_tkinter.pyd", "DLLs/tcl*.dll", "DLLs/tk*.dll", "DLLs/_test*.pyd",
                "DLLs/_ctypes_test.pyd", "Scripts/pip*"],
    "darwin": ["lib/python3.13/tkinter", "lib/python3.13/idlelib", "lib/python3.13/turtledemo",
               "lib/python3.13/test", "lib/python3.13/ensurepip",
               "lib/python3.13/site-packages/pip", "lib/python3.13/site-packages/pip-*",
               "lib/python3.13/lib-dynload/_tkinter*", "lib/python3.13/lib-dynload/_test*",
               "lib/tcl[0-9]*", "lib/tk[0-9]*", "lib/itcl*", "lib/thread[0-9]*",
               "lib/libtcl*", "lib/libtk*", "bin/pip*", "bin/idle*"],
}


def download(url, sha256):
    print(f"descargando {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        sys.exit(f"sha256 no coincide en {url}: {got} != {sha256}")
    return data


def tree_size(path):
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triple", default=None)
    args = ap.parse_args()
    triple = args.triple or host_triple()
    if triple not in PYTHON_SHA256:
        sys.exit(f"sin Python standalone fijado para {triple}")
    windows = "windows" in triple

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    tag = PYTHON.split("+")[1]
    data = download(PYTHON_URL.format(tag=tag, ver=PYTHON, triple=triple), PYTHON_SHA256[triple])
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(OUT, filter="data")          # deja OUT/python/
    for pattern in PRUNE["windows" if windows else "darwin"]:
        for p in (OUT / "python").glob(pattern):
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()

    exe = ".exe" if windows else ""
    data = download(UV_URL.format(ver=UV, triple=triple, ext="zip" if windows else "tar.gz"),
                    UV_SHA256[triple])
    if windows:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            (OUT / "uv.exe").write_bytes(z.read("uv.exe"))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            member = tar.getmember(f"uv-{triple}/uv")
            (OUT / "uv").write_bytes(tar.extractfile(member).read())
        (OUT / "uv").chmod(0o755)

    (OUT / "pyenv.json").write_text(json.dumps({"python": PYTHON, "uv": UV, "triple": triple},
                                               indent=2) + "\n", encoding="utf-8")
    print(f"pyenv: {OUT} (python {tree_size(OUT / 'python') / 1e6:.1f} MB, "
          f"uv {(OUT / f'uv{exe}').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
