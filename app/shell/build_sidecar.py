"""Empaqueta el backend con PyInstaller como sidecar de Tauri.

    python app/shell/build_sidecar.py [--triple x86_64-pc-windows-msvc]

Requiere la interfaz ya compilada (app/frontend/dist) y PyInstaller instalado. Deja
`app/shell/src-tauri/binaries/pizarra-backend-<triple>[.exe]`, el nombre que Tauri exige
para `bundle.externalBin`.

El motor va dos veces, a propósito (plan R1): congelado dentro del ejecutable para los
bloques de cálculo, y como ficheros .py en los recursos de la app (tauri.conf.json) para que
lo importe el Python de Fusion.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
DIST_WEB = ROOT / "app" / "frontend" / "dist"
BIN_DIR = ROOT / "app" / "shell" / "src-tauri" / "binaries"
CLI_DIR = ROOT / "app" / "shell" / "src-tauri" / "claude-cli"
WORK = ROOT / "out" / "build_sidecar"


def host_triple():
    try:
        out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
        return next(l.split(": ")[1] for l in out.splitlines() if l.startswith("host: "))
    except (OSError, subprocess.CalledProcessError, StopIteration):
        pass
    machine = platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triple", default=None)
    args = ap.parse_args()
    triple = args.triple or host_triple()
    if not (DIST_WEB / "index.html").exists():
        sys.exit("falta la interfaz compilada: cd app/frontend && npm run build")

    sep = ";" if sys.platform == "win32" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
           "--name", "pizarra-backend",
           "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "work"),
           "--specpath", str(WORK),
           "--paths", str(BACKEND),
           "--collect-submodules", "uvicorn",
           "--collect-submodules", "claude_agent_sdk",
           # Microsoft 365 (PLAN_M365 §2): se importan dentro de funciones, y msal_extensions
           # elige su cifrado por sistema (windows, osx, libsecret).
           "--collect-submodules", "msal",
           "--collect-submodules", "msal_extensions",
           "--hidden-import", "pizarra.agent",
           "--hidden-import", "pizarra.pack_env",     # --probe-pack-env (FF 10.1 paso 1)
           # Sin paquetes ni motor (PLAN_PAQUETES P11, P95): los paquetes corren en el
           # trabajador, en el entorno de paquetes (recursos pyenv/, worker/ y engine/), y el
           # backend no importa ninguno.
           "--add-data", f"{DIST_WEB}{sep}web",
           # Lo que el agente usa para hacer paquetes (PLAN_PAQUETES P99, P100): datos, no código.
           "--add-data", f"{BACKEND / 'pizarra' / 'pack_template'}{sep}pizarra/pack_template",
           "--add-data", f"{BACKEND / 'pizarra' / 'pack_guide.md'}{sep}pizarra",
           # Las plantillas de sector, perfiles que vienen con la app (PLAN_WORKSPACES W4).
           "--add-data", f"{BACKEND / 'pizarra' / 'profile_templates'}{sep}pizarra/profile_templates",
           str(BACKEND / "run_backend.py")]
    # `--collect-submodules` importa el paquete en un subproceso aislado que no ve `--paths`.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(BACKEND)] + [p for p in [os.environ.get("PYTHONPATH")] if p])}
    subprocess.run(cmd, check=True, env=env)

    exe = ".exe" if sys.platform == "win32" else ""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = BIN_DIR / f"pizarra-backend-{triple}{exe}"
    shutil.copy2(WORK / "dist" / f"pizarra-backend{exe}", target)
    print(f"sidecar: {target} ({target.stat().st_size / 1e6:.1f} MB)")
    # El CLI de Claude Code ya no va en el instalador (PLAN_PUBLICACION O13): la app usa el
    # que instala el usuario. Lo que quede de una compilación de antes no se empaqueta.
    shutil.rmtree(CLI_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
