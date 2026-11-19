"""Bloque de prueba del entorno de paquetes: importa numpy al registrarse, como hará un
paquete de verdad (PLAN_PAQUETES P19)."""
import numpy as np

from boardprint_sdk.packs import Param


def _run(p, _inputs, _ctx):
    x = np.linspace(0.0, float(p["L"]), int(p["n"]))
    y = np.sin(x)
    return {"serie": {
        "n": {"value": int(x.size), "unit": ""},
        "media": {"value": round(float(y.mean()), 6), "unit": ""},
        "numpy": {"value": np.__version__, "unit": ""},
    }}


def register(pack):
    pack.port("numpy_demo.serie", "serie")
    pack.block("numpy_demo.seno", "Seno", _run,
               params={"L": Param(10.0, "rad", "Largo"), "n": Param(1000, "", "Puntos")},
               outputs={"serie": "numpy_demo.serie"},
               description="Media de sin(x) con numpy")
