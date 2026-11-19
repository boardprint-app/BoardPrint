"""Motor del banco de diseño: cálculo de piezas y lo común de Fusion (`core`). Los brazos y los
terminales son de sus paquetes (`packs/robotica/`, `packs/terminales/`, docs/PLAN_PAQUETES.md §9).

Paquete de nombre único (plan D53) porque comparte el Python de Fusion con otros complementos:
se importa como `pizarra_engine.<subpaquete>` con la carpeta `engine/` en `sys.path`.
"""
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent   # engine/: el motor
REPO = ENGINE.parent                              # raíz del repo: arms/, out/, datasheets/
