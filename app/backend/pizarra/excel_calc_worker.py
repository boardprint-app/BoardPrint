"""Recalcula celdas de un Excel con xlcalculator (docs/PLAN_EXCEL.md §3.4, X7).

Lo lanza `pizarra.excel_calc` con el Python de su propio entorno (`<caché>/envs-excel/`), en un
proceso aparte y sin ventana. **Solo la stdlib y xlcalculator:** en la app instalada va como
recurso (`worker/pizarra/`, `tauri.conf.json`) y no importa nada de `pizarra`.

    entrada (stdin)   {"path": "libro.xlsx", "cells": ["Datos!B5", "'Mi hoja'!A1"]}
    salida (stdout)   {"values": {celda: valor}, "errors": {celda: motivo}}
                      o {"error": motivo} si el libro no se puede leer

Una celda que xlcalculator no sabe calcular (una función que no tiene, un `VLOOKUP`
aproximado) o que da un error de Excel va a `errors` con su motivo, y las demás siguen. Un
valor es un número, un texto o un sí/no: nunca un error ni una celda vacía.
"""
import contextlib
import json
import math
import sys


def address(where):
    """`'Mi hoja'!$B$3` → `Mi hoja!B3`, como xlcalculator guarda las celdas."""
    sheet, _, cell = where.rpartition("!")
    if len(sheet) >= 2 and sheet[0] == sheet[-1] == "'":
        sheet = sheet[1:-1].replace("''", "'")
    return f"{sheet}!{cell.replace('$', '')}"


def plain(v):
    """El valor de xlcalculator en JSON, o `ValueError` si no es un valor."""
    from xlcalculator.xlfunctions import func_xltypes
    if isinstance(v, BaseException):                    # los errores de Excel vienen como valor
        raise ValueError(f"{type(v).__name__}: {v}")
    if isinstance(v, func_xltypes.Blank):
        raise ValueError("vacía")
    v = getattr(v, "value", v)
    if hasattr(v, "item") and not isinstance(v, (bool, int, float, str)):
        v = v.item()                                    # un número de numpy
    if isinstance(v, bool) or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"no es un número finito: {v}")
        return v
    raise ValueError(f"valor que no se sabe pasar: {type(v).__name__}")


def recalc(path, cells):
    from xlcalculator import Evaluator, ModelCompiler
    try:
        evaluator = Evaluator(ModelCompiler().read_and_parse_archive(path))
    except Exception as exc:                            # noqa: BLE001 el libro entero
        return {"error": f"{type(exc).__name__}: {exc}"[:500]}
    values, errors = {}, {}
    for where in cells:
        try:
            values[where] = plain(evaluator.evaluate(address(where)))
        except Exception as exc:                        # noqa: BLE001 solo esa celda
            errors[where] = f"{type(exc).__name__}: {exc}"[:300]
    return {"values": values, "errors": errors}


def main():
    req = json.loads(sys.stdin.read())
    out = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):        # lo que imprima xlcalculator, aparte
        result = recalc(req["path"], list(req["cells"]))
    out.write(json.dumps(result) + "\n")
    out.flush()


if __name__ == "__main__":
    main()
