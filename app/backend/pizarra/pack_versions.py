"""Versiones de paquetes y del SDK (docs/PLAN_PAQUETES.md §1, P22).

- La **versión** de un paquete es semver estricta: `MAYOR.MENOR.PARCHE`, sin prerelease (FF 10
  no la necesita; si llega, se amplía aquí).
- Un **rango** es una lista de condiciones separadas por comas, todas a la vez:
  `">=1.0,<2"`, `"==0.2.1"`, `"0.2.1"` (lo mismo que `==`), `"!=1.3.0"`. En un rango, una
  versión puede ir corta (`1`, `1.0`) y se completa con ceros.

Solo stdlib (`packaging` no está en el backend congelado ni hace falta para esto).
"""
import re

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_CLAUSE_RE = re.compile(r"^(>=|<=|==|!=|>|<)?\s*((?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){0,2})$")
_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b, ">": lambda a, b: a > b, "<": lambda a, b: a < b}


def parse_version(text):
    """`"1.2.3"` → `(1, 2, 3)`; `ValueError` si no es semver."""
    m = SEMVER_RE.match(text) if isinstance(text, str) else None
    if not m:
        raise ValueError(f"la versión {text!r} no es semver (MAYOR.MENOR.PARCHE, p. ej. 0.1.0)")
    return tuple(int(g) for g in m.groups())


def parse_spec(text):
    """`">=1.0,<2"` → `[(">=", (1, 0, 0)), ("<", (2, 0, 0))]`; `ValueError` si no se entiende."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"el rango de versiones {text!r} está vacío o no es texto")
    clauses = []
    for part in text.split(","):
        m = _CLAUSE_RE.match(part.strip())
        if not m:
            raise ValueError(f"el rango de versiones {text!r} no se entiende (p. ej. \">=1.0,<2\")")
        nums = [int(n) for n in m.group(2).split(".")]
        clauses.append((m.group(1) or "==", tuple(nums + [0] * (3 - len(nums)))))
    return clauses


def satisfies(version, spec):
    """¿Cumple `version` (texto semver o tupla) el rango `spec` (texto)?"""
    v = parse_version(version) if isinstance(version, str) else tuple(version)
    return all(_OPS[op](v, ref) for op, ref in parse_spec(spec))
