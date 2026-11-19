"""Backend de la pizarra (spike FF 3.1, docs/PLAN_PIZARRA.md).

Python puro salvo `server.py` (FastAPI). La lógica que fija reglas del plan vive en módulos
sin dependencias para poder testearla con unittest, como el motor.
"""
