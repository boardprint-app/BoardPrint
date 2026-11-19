"""Orquestador del ciclo: parámetros -> Fusion -> medidas -> cálculo -> informe.

Uso dentro de Fusion (script o MCP):
    import sys; sys.path.insert(0, r"E:\\TRABAJO\\PROJECTS\\CAD-LLM\\engine")
    from pizarra_engine.core import runner; runner.run("mensula")

run(part, reset=False)
    - Abre (o crea) el documento propio de la pieza; nunca toca otros documentos.
    - Crea en Fusion los parámetros que falten. Con reset=True devuelve todos a
      los valores por defecto de params.toml.
    - Construye la geometría si el componente no existe; si existe, Fusion ya la
      ha regenerado con los valores vivos.
    - Lee valores vivos y propiedades físicas, calcula y escribe out/<pieza>/.
"""
import importlib
import json
from datetime import datetime
from pathlib import Path

from pizarra_engine import REPO as ROOT

PARTS = Path(__file__).resolve().parent.parent / "parts"


def _fresh(name):
    mod = importlib.import_module(name)
    return importlib.reload(mod)


def run(part: str, reset: bool = False) -> dict:
    params = _fresh("pizarra_engine.core.params")
    fusion_io = _fresh("pizarra_engine.core.fusion_io")
    report = _fresh("pizarra_engine.core.report")
    build = _fresh(f"pizarra_engine.parts.{part}.build")
    calc = _fresh(f"pizarra_engine.parts.{part}.calc")

    spec = params.load(PARTS / part / "params.toml")
    design, created = fusion_io.open_part_document(spec.document, spec.component)
    changes = fusion_io.sync_params(design, spec, reset)
    comp, built = build.ensure(design, spec)

    values = fusion_io.read_params(design, spec.params)
    measured = fusion_io.physical_properties(comp)
    tl_errors = fusion_io.timeline_errors(design)

    results, checks, notes = calc.compute(values, measured)
    rng = params.range_issues(spec, values)
    checks[:0] = [
        {"name": "Línea de tiempo sin errores", "value": len(tl_errors), "limit": "0 errores", "ok": not tl_errors},
        {"name": "Parámetros dentro de rango", "value": len(rng), "limit": "0 fuera de rango", "ok": not rng},
    ]
    notes = list(notes) + [f"Error de línea de tiempo: {x}" for x in tl_errors] + [f"Rango: {x}" for x in rng]

    out = ROOT / "out" / part
    out.mkdir(parents=True, exist_ok=True)
    state = {
        "part": part, "time": datetime.now().isoformat(timespec="seconds"),
        "document": spec.document, "created_document": created, "built_geometry": built,
        "param_changes": changes, "values": values, "measured": measured,
        "results": results, "checks": checks,
    }
    (out / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    all_ok, n_bad = report.write(out / "report.html", spec, values, measured, results, checks, notes)
    return {
        "ok": all_ok, "failing": [c["name"] for c in checks if not c["ok"]],
        "report": str(out / "report.html"), "created_document": created,
        "built_geometry": built, "param_changes": changes,
    }
