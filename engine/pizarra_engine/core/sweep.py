"""Barrido de un parámetro en Fusion: para cada valor, Fusion regenera la pieza,
se miden sus propiedades y se ejecutan todas las comprobaciones.

La pieza la pone quien llama, como en `runner.run`. Dentro de Fusion, la ménsula (paquete
`piezas`, docs/PLAN_PIEZAS.md Z3):
    from pizarra_packs.piezas.fusion import api
    api.sweep("mensula", "t", [3, 4, 5, 6, 8, 10, 12, 15])

Al terminar, el parámetro vuelve a su valor original aunque algo falle.
Resultado: out/<pieza>/sweep_<param>.json y sweep_<param>.html, y la opción
más ligera que cumple todas las comprobaciones.
"""
import importlib
import json
from datetime import datetime

from pizarra_engine import REPO as ROOT


def _fresh(name):
    return importlib.reload(importlib.import_module(name))


def run(part: str, param: str, values, apply_best: bool = False, *, spec_path, build, calc) -> dict:
    """`spec_path`: el `params.toml` de la pieza; `build` y `calc`, sus módulos."""
    params = _fresh("pizarra_engine.core.params")
    fusion_io = _fresh("pizarra_engine.core.fusion_io")
    sweep_report = _fresh("pizarra_engine.core.sweep_report")

    spec = params.load(spec_path)
    if param not in spec.params:
        raise KeyError(f"{param} no es un parámetro de {part}")
    p = spec.params[param]
    design, _ = fusion_io.open_part_document(spec.document, spec.component)
    fusion_io.sync_params(design, spec, reset=False)
    comp, _ = build.ensure(design, spec)

    fp = design.userParameters.itemByName(param)
    original = fp.expression
    rows, skipped = [], []
    try:
        for v in values:
            if not (p.min <= v <= p.max):
                skipped.append(v)
                continue
            fp.expression = f"{v:g} {p.unit}".strip()
            vals = fusion_io.read_params(design, spec.params)
            meas = fusion_io.physical_properties(comp)
            tl = fusion_io.timeline_errors(design)
            results, checks, _ = calc.compute(vals, meas)
            checks.insert(0, {"name": "Línea de tiempo sin errores", "value": len(tl), "limit": "0 errores", "ok": not tl})
            rows.append({
                "value": v, "mass_kg": meas["mass_kg"], "ok": all(c["ok"] for c in checks),
                "checks": [{"name": c["name"], "value": c["value"], "limit": c["limit"], "ok": c["ok"]} for c in checks],
                "results": {r["name"]: r["value"] for r in results},
            })
    finally:
        fp.expression = original

    passing = [r for r in rows if r["ok"]]
    best = min(passing, key=lambda r: r["mass_kg"]) if passing else None
    if apply_best and best is not None:
        fp.expression = f"{best['value']:g} {p.unit}".strip()

    out = ROOT / "out" / part
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "part": part, "param": param, "label": p.label, "desc": p.desc,
        "time": datetime.now().isoformat(timespec="seconds"),
        "original": original, "skipped_out_of_range": skipped,
        "best": best["value"] if best else None, "rows": rows,
    }
    (out / f"sweep_{param}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    html_path = out / f"sweep_{param}.html"
    sweep_report.write(html_path, data)
    return {
        "best": data["best"], "best_mass_kg": best["mass_kg"] if best else None,
        "n": len(rows), "passing": [r["value"] for r in passing],
        "skipped": skipped, "applied": bool(apply_best and best), "report": str(html_path),
    }
