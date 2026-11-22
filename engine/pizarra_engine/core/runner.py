"""Orquestador del ciclo: parámetros -> Fusion -> medidas -> cálculo -> informe.

La pieza la pone quien llama (su `params.toml`, su `build` y su `calc`): el motor no conoce
ninguna. La ménsula es del paquete `piezas` (docs/PLAN_PIEZAS.md Z3), y dentro de Fusion se usa
así, con el motor y el paquete registrados (`engine_bootstrap`, como `CAD-LLM_Recalcular`):
    from pizarra_packs.piezas.fusion import api; api.run("mensula")

run(part, reset=False, *, spec_path, build, calc)
    - Abre (o crea) el documento propio de la pieza; nunca toca otros documentos.
    - Crea en Fusion los parámetros que falten. Con reset=True devuelve todos a
      los valores por defecto de params.toml.
    - Construye la geometría si el componente no existe; si existe, Fusion ya la
      ha regenerado con los valores vivos.
    - Lee valores vivos y propiedades físicas, calcula y escribe out/<pieza>/.

evaluate(spec, calc, values, measured, tl_errors)
    - Las cuentas, sin Fusion: el cálculo de la pieza con las dos comprobaciones de siempre
      delante (línea de tiempo y rango). La usan `run` y el bloque que analiza la pieza.
"""
import importlib
import json
from datetime import datetime

from pizarra_engine import REPO as ROOT


def _fresh(name):
    mod = importlib.import_module(name)
    return importlib.reload(mod)


def evaluate(spec, calc, values: dict, measured: dict, tl_errors: list):
    """(results, checks, notes) de la pieza con sus valores vivos y lo medido. Delante del
    cálculo, «Línea de tiempo sin errores» y «Parámetros dentro de rango»: una pieza con un
    error en la línea de tiempo o un parámetro fuera de rango nunca cumple, aunque el cálculo
    sí. Python puro."""
    from . import params

    results, checks, notes = calc.compute(values, measured)
    rng = params.range_issues(spec, values)
    checks[:0] = [
        {"name": "Línea de tiempo sin errores", "value": len(tl_errors), "limit": "0 errores", "ok": not tl_errors},
        {"name": "Parámetros dentro de rango", "value": len(rng), "limit": "0 fuera de rango", "ok": not rng},
    ]
    notes = list(notes) + [f"Error de línea de tiempo: {x}" for x in tl_errors] + [f"Rango: {x}" for x in rng]
    return results, checks, notes


def run(part: str, reset: bool = False, *, spec_path, build, calc) -> dict:
    """`spec_path`: el `params.toml` de la pieza; `build` y `calc`, sus módulos (ya
    recargados por quien llama, si hace falta)."""
    params = _fresh("pizarra_engine.core.params")
    fusion_io = _fresh("pizarra_engine.core.fusion_io")
    report = _fresh("pizarra_engine.core.report")

    spec = params.load(spec_path)
    design, created = fusion_io.open_part_document(spec.document, spec.component)
    changes = fusion_io.sync_params(design, spec, reset)
    comp, built = build.ensure(design, spec)

    values = fusion_io.read_params(design, spec.params)
    measured = fusion_io.physical_properties(comp)
    tl_errors = fusion_io.timeline_errors(design)

    results, checks, notes = evaluate(spec, calc, values, measured, tl_errors)

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
