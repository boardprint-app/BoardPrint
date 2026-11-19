"""Los tests del backend cargan, cuando no dicen otras carpetas, el paquete de prueba
(`tests/packs_prueba`: los bloques de las reglas del núcleo, también en el repo público) y los
paquetes del repo (`packs/`, si están), como el arranque de desarrollo: la carga ya no los conoce
(docs/PLAN_PAQUETES.md P81)."""
import os
from pathlib import Path

if not os.environ.get("BOARDPRINT_DEV_PACKS", "").strip():
    os.environ["BOARDPRINT_DEV_PACKS"] = os.pathsep.join(
        str(d) for d in (Path(__file__).resolve().parent / "packs_prueba",
                         Path(__file__).resolve().parents[3] / "packs"))
