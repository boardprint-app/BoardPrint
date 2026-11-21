"""El `latest.json` del actualizador (docs/PLAN_V020.md §4, V9-V12).

    python scripts/latest_json.py <carpeta con los instaladores> 0.2.0 [--notas notas.md]
    python scripts/latest_json.py --poner-notas latest.json --notas notas.md

Mira en la carpeta los instaladores que tienen su firma al lado (`<nombre>.sig`, la que deja
`tauri build` con `createUpdaterArtifacts` y la clave en `TAURI_SIGNING_PRIVATE_KEY`) y escribe
`latest.json` con la URL de cada uno en el Release `v<versión>` de boardprint-app/BoardPrint. Uno sin
firma no entra: el actualizador lo rechazaría.

Antes saca a la raíz de la carpeta lo que venga en subcarpetas (`aplanar`): el job *publicar*
de App sube `release/*` tal cual, y desde el 20/11 `upload-artifact` guarda cada instalador
bajo su carpeta de `bundle/` (`nsis/`, `dmg/`, `macos/`): sin aplanar, v0.2.2 no encontraba
ninguna firma (PLAN_PUBLICACION §4.5).

Las notas son las del Release, y el aviso de actualización las enseña (PLAN_EXCEL §3.6). El job
*publicar* las pasa con `--notas` al crearlo, y el workflow `notas` las vuelve a poner con
`--poner-notas` cada vez que se edita el Release (`gh release edit --notes-file`): solo cambia
`notes` del `latest.json` ya publicado, con las firmas y las URL tal cual.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

RELEASES = "https://github.com/boardprint-app/BoardPrint/releases/download"
# {plataforma de Tauri: cómo acaba el nombre del instalador que usa el actualizador}
PLATFORMS = {"windows-x86_64": "-setup.exe", "darwin-aarch64": ".app.tar.gz"}


def aplanar(folder):
    """Mueve a la raíz de `folder` los ficheros de sus subcarpetas y quita las que quedan
    vacías. Dos ficheros con el mismo nombre en carpetas distintas es un error: uno pisaría al
    otro en el Release."""
    folder = Path(folder)
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and p.parent != folder):
        dst = folder / f.name
        if dst.exists():
            raise SystemExit(f"{f.name} está dos veces en {folder}")
        f.replace(dst)
    for d in sorted((p for p in folder.rglob("*") if p.is_dir()), reverse=True):
        d.rmdir()


def build(folder, version, notes="", pub_date=None):
    folder = Path(folder)
    platforms = {}
    for platform, suffix in PLATFORMS.items():
        for f in sorted(folder.iterdir()):
            sig = f.with_name(f.name + ".sig")
            if f.name.endswith(suffix) and sig.is_file():
                platforms[platform] = {"signature": sig.read_text(encoding="utf-8").strip(),
                                       "url": f"{RELEASES}/v{version}/{f.name}"}
                break
    return {"version": version, "notes": notes,
            "pub_date": pub_date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "platforms": platforms}


def set_notes(latest, notes):
    """Cambia solo las notas del `latest.json` de `latest`."""
    latest = Path(latest)
    data = json.loads(latest.read_text(encoding="utf-8"))
    data["notes"] = notes
    latest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("carpeta", nargs="?")
    ap.add_argument("version", nargs="?")
    ap.add_argument("--notas", help="fichero con las notas del Release")
    ap.add_argument("--poner-notas", metavar="LATEST_JSON",
                    help="solo cambia las notas de un latest.json ya escrito (con --notas)")
    a = ap.parse_args()
    notes = Path(a.notas).read_text(encoding="utf-8") if a.notas else ""
    if a.poner_notas:
        if not a.notas:
            ap.error("--poner-notas necesita --notas")
        set_notes(a.poner_notas, notes)
        print(f"{a.poner_notas}: notas puestas ({len(notes)} caracteres)")
        raise SystemExit(0)
    if not a.carpeta or not a.version:
        ap.error("faltan la carpeta y la versión")
    aplanar(a.carpeta)
    data = build(a.carpeta, a.version, notes)
    if not data["platforms"]:
        raise SystemExit("ningún instalador con su .sig en " + a.carpeta)
    out = Path(a.carpeta) / "latest.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{out}: {', '.join(data['platforms'])}")
