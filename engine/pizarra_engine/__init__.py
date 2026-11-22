"""Motor del banco de diseño: lo común de los paquetes y de Fusion (`core`). Las piezas, los brazos
y los terminales son de sus paquetes (`packs/piezas/`, `packs/robotica/`, `packs/terminales/`,
docs/PLAN_PAQUETES.md §9, docs/PLAN_PIEZAS.md Z1).

Paquete de nombre único (plan D53) porque comparte el Python de Fusion con otros complementos:
se importa como `pizarra_engine.<subpaquete>` con la carpeta `engine/` en `sys.path`.
"""
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent   # engine/: el motor
REPO = ENGINE.parent                              # raíz del repo: arms/, out/, datasheets/
