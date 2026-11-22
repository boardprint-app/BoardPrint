"""Los `.bppack` oficiales (docs/PLAN_PAQUETES.md P11, P77): los paquetes del repo que se
publican junto al instalador, exportados con el mismo código que *Exportar* de la app.

    python app/shell/build_packs.py [--out <carpeta>] [ids...]

Sin ids, los oficiales (`OFFICIAL`) que haya en `packs/`; sin `packs/` (el repo público, que
no lleva paquetes) no hace nada y sale bien. Necesita la interfaz de los paquetes compilada
(`npm run build` o `npm run build:packs` en app/frontend): un paquete con `[ui]` sin su `ui/` no
se exporta. Lo usan el workflow App y la prueba de humo del sidecar (`smoke_sidecar.py`).
"""
import argparse
import sys
from pathlib import Path

SHELL = Path(__file__).resolve().parent
ROOT = SHELL.parents[1]
PACKS = ROOT / "packs"
OUT = SHELL / "dist-packs"
OFFICIAL = ("robotica_base", "robotica", "terminales", "fusion", "piezas")


def build(out=OUT, ids=OFFICIAL):
    """Exporta `ids` de `packs/` a `out` y devuelve las rutas de los `.bppack` ([] si no hay
    `packs/` o ningún id)."""
    if not ids or not PACKS.is_dir():
        return []
    sys.path.insert(0, str(ROOT / "app" / "backend"))
    from pizarra import pack_install
    out = Path(out)
    return [pack_install.export(PACKS / pid, out, find=lambda p: PACKS / p) for pid in ids]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("ids", nargs="*", default=list(OFFICIAL))
    args = ap.parse_args()
    paths = build(args.out, args.ids)
    if not paths:
        print("sin paquetes que exportar")
    for path in paths:
        print(f"{path.name} ({path.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
