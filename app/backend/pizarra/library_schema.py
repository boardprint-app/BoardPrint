"""El esquema de las fichas de un paquete (docs/PLAN_LIBRERIA.md L3, L4).

Un paquete declara los campos de `[values]` de cada tipo de ficha que trae como datos, en
`<paquete>/library/schema.toml`: una tabla por tipo y un campo por línea,

    [reducer]
    clases = ["strain_wave", "planetary"]
    ratio = { obligatorio = true, unidad = "-", min = 3, max = 200, descripcion = "Relación de reducción" }

con `unidad` ("-" sin dimensión, "" si es texto), `descripcion` (en el idioma del paquete: la
traducción va en su catálogo, O15), `obligatorio`, y `min` y `max` si es un número. El núcleo
solo enseña esto (`library.WorkspaceLibrary.fields`); lo que valida una ficha con él es del
paquete. Lo demás de un campo (`lista`, `defecto`…) y de un tipo (`clases`) también es suyo.

La carga de los paquetes lo lee (`read`) sin ejecutar su código. Como los catálogos, la lectura
es tolerante: un fichero ilegible o una línea mal hecha se apunta como aviso y el paquete y sus
fichas cargan igual. Solo stdlib: lo usa también la carga del trabajador de paquetes.
"""
import re
import tomllib
from pathlib import Path

PACK_LIBRARY = "library"                  # la carpeta de fichas de un paquete
SCHEMA_FILE = "schema.toml"               # el esquema, en la raíz de esa carpeta
TYPE_KEYS = ("clases",)                   # lo de la tabla de un tipo que no es un campo
# La regla de `storage.names.check_ficha_type`, que aquí no se importa (arrastra `tomli_w`, que
# el trabajador no tiene); `test_libreria` comprueba que es la misma.
TYPE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")


def _field(where, name, spec):
    """`(campo, problema)` de una línea del esquema: `{nombre, unidad, descripcion,
    obligatorio, min, max}`, o `(None, motivo)` si no vale."""
    if not isinstance(spec, dict):
        return None, f"{where}.{name}: tiene que ser una tabla ({{ unidad = …, descripcion = … }})"
    out = {"nombre": name}
    for k, kind, default in (("unidad", str, ""), ("descripcion", str, ""),
                             ("obligatorio", bool, False)):
        v = spec.get(k, default)
        if not isinstance(v, kind):
            return None, f"{where}.{name}.{k}: tiene que ser {'un texto' if kind is str else 'true o false'}"
        out[k] = v
    for k in ("min", "max"):
        v = spec.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            return None, f"{where}.{name}.{k}: tiene que ser un número"
        out[k] = v
    return out, None


def read(folder):
    """`(esquema, problemas)` de `<folder>/library/schema.toml`, los campos de `[values]` que el
    paquete de `folder` declara para cada tipo de ficha (PLAN_LIBRERIA L3): `{tipo: [campo]}`,
    cada campo `{nombre, unidad, descripcion, obligatorio, min, max}`, en el orden del fichero.
    Se lee sin ejecutar nada del paquete. Sin fichero, `({}, [])`. Nunca lanza: un fichero que
    no se lee se queda fuera entero, y un tipo o un campo mal hecho, solo él (los problemas,
    textos para el registro)."""
    path = Path(folder) / PACK_LIBRARY / SCHEMA_FILE
    rel = f"{PACK_LIBRARY}/{SCHEMA_FILE}"
    if not path.is_file():
        return {}, []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return {}, [f"{rel}: no se puede leer: {exc}"]
    schema, problems = {}, []
    for type_, spec in data.items():
        if not TYPE_RE.fullmatch(type_):
            problems.append(f"{rel}: [{type_}]: un tipo va en minúsculas, cifras y _, empezando "
                            "por letra (hasta 40)")
            continue
        if not isinstance(spec, dict):
            problems.append(f"{rel}: {type_}: tiene que ser una tabla por tipo ([{type_}])")
            continue
        fields = []
        for name, f in spec.items():
            if name in TYPE_KEYS:
                continue
            got, why = _field(type_, name, f)
            if why:
                problems.append(f"{rel}: {why}")
            else:
                fields.append(got)
        schema[type_] = fields
    return schema, problems
