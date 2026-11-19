"""Todo lo que habla con Fusion: documento, parámetros de usuario y propiedades físicas.

Unidades: la API de Fusion trabaja internamente en cm, kg y rad. Aquí se
convierte todo a mm, kg y grados antes de devolverlo.
"""
import math

import adsk.core
import adsk.fusion

_TO_DISPLAY = {"mm": lambda v: v * 10.0, "deg": math.degrees, "": lambda v: v}


def app():
    return adsk.core.Application.get()


def _has_component(doc, comp_name: str) -> bool:
    """Un documento aún sin guardar se llama "Untitled": se reconoce por
    contener ya el componente de la pieza."""
    design = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
    if design is None:
        return False
    return any(o.component.name == comp_name for o in design.rootComponent.occurrences)


def open_part_document(doc_name: str, comp_name: str):
    """Devuelve (design, created) del documento de la pieza.

    - Si está abierto, lo activa si hace falta y lo usa.
    - Si no está abierto, crea uno nuevo SIN guardar (lo guarda el usuario con
      Ctrl+S y el nombre de meta.document). No se busca ni se guarda en la
      nube desde el script: hacerlo dentro de un script MCP cerró Fusion.
    Nunca trabaja sobre otro documento."""
    a = app()
    for doc in a.documents:
        if doc.name.split(" v")[0] == doc_name or _has_component(doc, comp_name):
            if a.activeDocument != doc:
                doc.activate()
            return adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType")), False
    doc = a.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(a.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    return design, True


def sync_params(design, spec, reset: bool) -> dict:
    """Crea en Fusion los parámetros que falten con su valor por defecto.
    Con reset=True también devuelve los existentes a su valor por defecto.
    Devuelve {nombre: 'creado' | 'reseteado'} con lo que ha cambiado."""
    up = design.userParameters
    changes = {}
    for name, p in spec.params.items():
        comment = f"{p.desc} [{p.label}]"
        fp = up.itemByName(name)
        if fp is None:
            up.add(name, adsk.core.ValueInput.createByString(p.expression), p.unit, comment)
            changes[name] = "creado"
        elif reset and abs(_display(fp) - p.value) > 1e-9:
            fp.expression = p.expression
            changes[name] = "reseteado"
        if fp is not None and fp.comment != comment:
            fp.comment = comment
    return changes


def _display(fp) -> float:
    return _TO_DISPLAY[fp.unit](fp.value) if fp.unit in _TO_DISPLAY else fp.value


def read_params(design, names) -> dict:
    """Valores vivos de la tabla de parámetros, en unidades de visualización."""
    out = {}
    for n in names:
        fp = design.userParameters.itemByName(n)
        if fp is not None:
            out[n] = _display(fp)
    return out


def physical_properties(component) -> dict:
    """Masa, volumen, CdG y material del componente, en kg, mm3 y mm."""
    pp = component.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
    cg = pp.centerOfMass
    mats = sorted({b.material.name for b in component.bRepBodies if b.material})
    return {
        "mass_kg": pp.mass,
        "volume_mm3": pp.volume * 1000.0,
        "area_mm2": pp.area * 100.0,
        "density_kg_m3": pp.density * 1e6 if pp.density else (pp.mass / (pp.volume * 1e-6) if pp.volume else 0.0),
        "cg_mm": [cg.x * 10.0, cg.y * 10.0, cg.z * 10.0],
        "materials": mats,
        "bodies": component.bRepBodies.count,
    }


def timeline_errors(design) -> list:
    """Operaciones de la línea de tiempo con error o aviso tras regenerar. Una suprimida a
    propósito (p. ej. a mano, traída a la pizarra) no es un error (R28)."""
    errs = []
    tl = design.timeline
    for i in range(tl.count):
        item = tl.item(i)
        try:
            if item.isSuppressed:
                continue
        except Exception:      # algunos elementos de la línea de tiempo no lo dicen
            pass
        hs = item.healthState
        if hs != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
            errs.append(f"{item.name}: {item.errorOrWarningMessage or hs}")
    return errs
