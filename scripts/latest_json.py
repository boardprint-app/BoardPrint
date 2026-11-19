"""El `latest.json` del actualizador (docs/PLAN_V020.md §4, V9-V12).

    python scripts/latest_json.py <carpeta con los instaladores> 0.2.0 [--notas notas.md]

Mira en la carpeta los instaladores que tienen su firma al lado (`<nombre>.sig`, la que deja
`tauri build` con `createUpdaterArtifacts` y la clave en `TAURI_SIGNING_PRIVATE_KEY`) y escribe
`latest.json` con la URL de cada uno en el Release `v<versión>` de boardprint-app/BoardPrint. Uno sin
firma no entra: el actualizador lo rechazaría.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

RELEASES = "https://github.com/boardprint-app/BoardPrint/releases/download"
# {plataforma de Tauri: cómo acaba el nombre del instalador que usa el actualizador}
PLATFORMS = {"windows-x86_64": "-setup.exe", "darwin-aarch64": ".app.tar.gz"}


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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("carpeta")
    ap.add_argument("version")
    ap.add_argument("--notas", help="fichero con las notas del Release")
    a = ap.parse_args()
    notes = Path(a.notas).read_text(encoding="utf-8") if a.notas else ""
    data = build(a.carpeta, a.version, notes)
    if not data["platforms"]:
        raise SystemExit("ningún instalador con su .sig en " + a.carpeta)
    out = Path(a.carpeta) / "latest.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{out}: {', '.join(data['platforms'])}")
