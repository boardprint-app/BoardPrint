"""Prueba del entorno de paquetes en la app instalada (docs/PLAN_PAQUETES.md FF 10.1 paso 1).

    python app/shell/smoke_pack_env.py

Solo Windows, en el CI, tras compilar el instalador: lo instala en silencio (como un usuario,
en %LOCALAPPDATA%), y con el sidecar instalado (`--probe-pack-env`) crea un entorno con numpy
en la caché de la app, registra el paquete de prueba de los tests y uno con numpy en el
trabajador y ejecuta un bloque, dos veces: con la caché fría y con la caliente. Comprueba el criterio de fracaso de
§12 y deja las medidas en el resumen del run.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRUEBA = ROOT / "app" / "backend" / "tests" / "packs_prueba" / "prueba"
BUNDLE = ROOT / "app" / "shell" / "src-tauri" / "target" / "release" / "bundle" / "nsis"
PRODUCT, IDENTIFIER = "BoardPrint", "dev.boardprint.desktop"
# El instalador sin el entorno de paquetes (`tauri build` en local el 2026-11-12, sin `pyenv/`
# ni `worker/`: 189,8 MB; con ellos, 209,4). §12: no puede crecer más de 60 MB.
BASELINE_MB, MAX_GROWTH_MB = 189.8, 60
MAX_REGISTER_COLD_S, MAX_RUN_ADDED_S = 2.0, 0.5


def install():
    setups = list(BUNDLE.glob("*-setup.exe"))
    if len(setups) != 1:
        sys.exit(f"se esperaba un setup.exe en {BUNDLE}, hay {setups}")
    setup = setups[0]
    t0 = time.time()
    subprocess.run([str(setup), "/S"], check=True)
    home = Path(os.environ["LOCALAPPDATA"]) / PRODUCT
    exe = home / "pizarra-backend.exe"
    for _ in range(60):                      # el instalador de NSIS puede soltar antes de acabar
        if exe.is_file() and (home / "pyenv" / "python" / "python.exe").is_file():
            break
        time.sleep(1)
    else:
        sys.exit(f"tras instalar no están el sidecar y el Python en {home}: "
                 f"{sorted(p.name for p in home.iterdir()) if home.is_dir() else 'no existe'}")
    print(f"instalado en {home} en {time.time() - t0:.0f} s")
    return setup, home


def probe(home, cache, packs, out):
    cmd = [str(home / "pizarra-backend.exe"), "--probe-pack-env", str(out),
           "--pyenv-dir", str(home / "pyenv"), "--cache-dir", str(cache),
           "--worker-dir", str(home / "worker"), "--engine-dir", str(home / "engine"),
           "--packs", str(packs), "--packs", str(ROOT / "app" / "backend" / "tests" / "packs_numpy"),
           "--run", "numpy_demo.seno", "--baseline", "prueba.tubo"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    total = time.time() - t0
    m = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    if proc.returncode or "error" in m:
        print(proc.stdout, proc.stderr)
        log = Path(cache) / "logs" / "worker.log"
        if log.is_file():
            print(log.read_text(encoding="utf-8", errors="replace")[-4000:])
        sys.exit(f"la prueba del entorno falló: {m.get('error') or proc.returncode}")
    m["probe_total_seconds"] = total
    return m


def main():
    if sys.platform != "win32":
        sys.exit("solo Windows (el instalador de macOS se prueba a mano)")
    setup, home = install()
    setup_mb = setup.stat().st_size / 1e6
    pyenv_mb = sum(f.stat().st_size for f in (home / "pyenv").rglob("*") if f.is_file()) / 1e6
    tmp = Path(tempfile.mkdtemp())
    packs = tmp / "packs"
    # El paquete de prueba de los tests (O20): también está en el repo público, que no lleva
    # paquetes; así la app instalada carga un paquete de verdad en el CI de los dos repos.
    shutil.copytree(PRUEBA, packs / "prueba",
                    ignore=shutil.ignore_patterns("__pycache__"))
    # La caché de la app de verdad (Tauri app_cache_dir: %LOCALAPPDATA%\<identificador>).
    cache = Path(os.environ["LOCALAPPDATA"]) / IDENTIFIER
    shutil.rmtree(cache / "envs", ignore_errors=True)
    shutil.rmtree(cache / "uv", ignore_errors=True)
    shutil.rmtree(cache / "pycache", ignore_errors=True)
    cold = probe(home, cache, packs, tmp / "cold.json")
    warm = probe(home, cache, packs, tmp / "warm.json")

    added = warm["run_worker_baseline_seconds"] - warm["run_today_seconds"]
    rows = [
        ("Instalador", f"{setup_mb:.1f} MB", f"crece {setup_mb - BASELINE_MB:+.1f} MB "
         f"sobre {BASELINE_MB} MB (máx. +{MAX_GROWTH_MB})"),
        ("pyenv instalado (Python + uv)", f"{pyenv_mb:.1f} MB", ""),
        ("Entorno con numpy (caché fría, con descarga)", f"{cold['env_seconds']:.1f} s",
         f"{cold['env_mb']:.0f} MB en disco; al instalar un paquete, no al arrancar"),
        ("Entorno ya hecho", f"{warm['env_seconds'] * 1000:.1f} ms", ""),
        ("Registrar en frío (primer proceso, sin .pyc)", f"{cold['register_cold_seconds']:.2f} s",
         f"máx. {MAX_REGISTER_COLD_S} s"),
        ("Registrar en caliente", f"{warm['register_warm_seconds']:.2f} s", ""),
        ("Ejecutar numpy_demo.seno (proceso + registro + bloque)", f"{warm['run_seconds']:.2f} s",
         f"el bloque solo: {warm['run_only_seconds'] * 1000:.0f} ms"),
        ("prueba.tubo en el trabajador", f"{warm['run_worker_baseline_seconds']:.2f} s", ""),
        ("prueba.tubo como hoy (D92, proceso del sidecar)", f"{warm['run_today_seconds']:.2f} s", ""),
        ("Lo que suma el trabajador a una ejecución", f"{added:+.2f} s",
         f"máx. +{MAX_RUN_ADDED_S} s"),
    ]
    table = "| Medida | Valor | Nota |\n|---|---|---|\n" + "\n".join(
        f"| {a} | {b} | {c} |" for a, b, c in rows)
    summary = (f"### Entorno de paquetes (PLAN_PAQUETES FF 10.1 paso 1)\n\n{table}\n\n"
               f"numpy {warm['run_outputs']['serie']['numpy']['value']}, Python "
               f"{warm['pyenv'].get('python')}, uv {warm['pyenv'].get('uv')}\n")
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(summary)
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "pack_env_probe.json").write_text(
        json.dumps({"cold": cold, "warm": warm, "setup_mb": setup_mb, "pyenv_mb": pyenv_mb},
                   indent=2, ensure_ascii=False), encoding="utf-8")

    fails = []
    if setup_mb - BASELINE_MB > MAX_GROWTH_MB:
        fails.append(f"el instalador crece {setup_mb - BASELINE_MB:.1f} MB")
    if cold["register_cold_seconds"] > MAX_REGISTER_COLD_S:
        fails.append(f"registrar en frío tarda {cold['register_cold_seconds']:.2f} s")
    if added > MAX_RUN_ADDED_S:
        fails.append(f"el trabajador suma {added:.2f} s a una ejecución")
    if fails:
        sys.exit("criterio de fracaso de §12 (se replantea P19-P21): " + "; ".join(fails))
    print("prueba del entorno de paquetes: OK")


if __name__ == "__main__":
    main()
