"""Los tests del backend cargan los paquetes del repo (`packs/`) cuando no dicen otras carpetas,
como el arranque de desarrollo: la carga ya no los conoce (docs/PLAN_PAQUETES.md P81)."""
import os
from pathlib import Path

if not os.environ.get("BOARDPRINT_DEV_PACKS", "").strip():
    os.environ["BOARDPRINT_DEV_PACKS"] = str(Path(__file__).resolve().parents[3] / "packs")
