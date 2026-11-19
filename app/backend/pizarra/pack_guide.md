# Cómo se hace un paquete de BoardPrint

Un paquete añade bloques a la pizarra para un dominio nuevo (perfiles alares, tanques,
vigas…), sin tocar la app. Lo haces como **borrador** en tu carpeta de borradores, lo validas
y, cuando está en verde, lo **propones**: el ingeniero ve un resumen y decide si lo instala.
Nunca instalas tú.

## Flujo con tus herramientas

1. `crear_paquete(id, nombre, descripcion)`: crea el borrador desde una plantilla (un bloque
   de ejemplo y su test). `id`: minúsculas, cifras y `_`, empezando por letra.
2. `listar_paquete(id)`, `leer_archivo_paquete(id, ruta)` y
   `escribir_archivo_paquete(id, ruta, contenido)`: el código, siempre dentro del borrador.
3. `validar_paquete(id)`: la validación estática, la carga del paquete y sus tests. Corrige lo
   que diga hasta que salga en verde.
4. `proponer_paquete(id)`: solo con la última validación en verde y sin cambios después.
   Sale en el chat como una tarjeta con *Instalar*.

Para cambiar un paquete instalado: `duplicar_paquete(origen, nuevo)`. Copia el paquete con
otro id y te dice dónde sale escrito el id de antes, que tienes que cambiar por el nuevo.

## Estructura

```
<id>/
  pack.toml        manifiesto
  blocks.py        register(pack): puertos y bloques
  tests/           tests de la regla del cálculo (unittest)
  <módulos>.py     código propio, importado en relativo: from .perfil import naca4
  agent.md         opcional: instrucciones para el agente de diseño (cómo montar y usar
                   tus bloques), en español y breves; entra en su prompt, hasta 4000
                   caracteres
```

`pack.toml`:

```toml
id = "naca"                 # igual que la carpeta
name = "Perfiles NACA"
version = "0.1.0"           # semver
author = "Agente de diseño"
description = "Qué hace, en una frase"
sdk = ">=1.0,<2"
module = "blocks"

[python]
dependencies = ["numpy>=2,<3"]   # librerías de PyPI; [] si solo usa la biblioteca estándar

[requires]                  # otros paquetes, solo si usas su código o sus puertos
# perfiles_base = ">=0.1,<0.2"
```

## El contrato de un bloque

```python
from boardprint_sdk.packs import Param, chart

def calcula(params, inputs, ctx):
    # params: {nombre: valor}; inputs: {puerto: {campo: {"value", "unit", ...}}}
    return {"perfil": {
        "espesor": {"value": 0.12, "unit": "", "label": "Espesor relativo"},
        "polar": chart(("α", "°"), ("Cl", ""), {"Cl": [(0, 0), (5, 0.55)]}, label="Cl(α)"),
    }}

def register(pack):
    pack.port("naca.perfil", "perfil")
    pack.block("naca.perfil4", "Perfil NACA 4", calcula,
               params={"codigo": Param("2412", "", "Código"), "cuerda": Param(1.0, "m", "Cuerda")},
               inputs={}, outputs={"perfil": "naca.perfil"},
               description="Geometría y polar de un perfil NACA de 4 cifras")
    pack.view("naca.perfil4", card=("params", "results", "chart"))
```

- Todo lo que registra un paquete lleva su id delante: `naca.perfil4`, `naca.perfil`.
- `Param(defecto, unidad, etiqueta, choices=(...))`: el tipo del valor por defecto es el que
  admite la tarjeta (número, texto, lista u objeto).
- Una salida es `{puerto: {campo: {"value", "unit", "label"?}}}`. Cada campo con su unidad.
- Si algo no se puede calcular, lanza `ValueError` con el motivo, en español: es lo que verá
  el ingeniero en el bloque.
- Controles genéricos de la tarjeta (`pack.view`): `params`, `results`, `chart` (gráfica x-y
  de un campo hecho con `chart(...)`) y `view2d` (vista 2D a escala con `box`, `line`,
  `point`). No hace falta interfaz propia.
- `ctx.progress(fracción, mensaje)` en un cálculo largo.
- Vista previa (`preview=`, opcional): `preview(params, inputs)` da lo que enseña el editor
  con los parámetros que se están editando, rápida y sin archivos. Sus fallos van en
  `error` (un texto) o en `errores…` (`{clave: motivo}`), a cualquier profundidad: una
  propuesta del agente sobre ese bloque que los da no se guarda.

## La regla de los números

Ningún número sin fuente. Lo que calcula un bloque es su fuente: la tarjeta cita el bloque. Un
dato de tabla o de norma lleva en el código de dónde sale (un comentario con la norma o el
libro), y uno que sea una estimación se dice en su `label` («estimado»). Nada de inventar
coeficientes.

## Tests

Prueban la **regla**, no el código: «la sustentación crece con el ángulo hasta la entrada en
pérdida», «el espesor máximo de un 0012 es el 12 % de la cuerda». Un test que solo repite la
fórmula del código no prueba nada. Usa casos conocidos (un resultado de libro, un caso
límite, una simetría).

La plantilla trae la forma: cargan el paquete con `pizarra.packs.load` y llaman a los bloques.
Corren en el entorno de paquetes, con las librerías de `[python] dependencies`. Solo pueden
usar la biblioteca estándar, esas librerías, `boardprint_sdk`, `pizarra.packs` y el propio
paquete.

## Lo que la validación no deja

- Un import de una librería que no está en `[python] dependencies`, o de otro paquete que no
  está en `[requires]` (siempre como `pizarra_packs.<id>`).
- Importar el propio paquete en absoluto. Lo propio va en relativo: `from .modulo import x`.
- Ficheros fuera de la carpeta, enlaces, o un paquete de más de 50 MB.
- Usar la red, o escribir fuera de `ctx.workdir`: la app no lo impide, pero un paquete así
  no se propone.

## Interfaz propia (opcional)

Si los controles genéricos no bastan, el paquete puede traer su propia página: un HTML con su
JavaScript y su CSS en `ui/` (sin compilar nada: escribe `ui/index.html` y, si quieres,
`ui/app.js` y `ui/style.css`), y en `pack.toml`:

```toml
[ui]
entry = "ui/index.html"
```

En `register`: `pack.view("<id>.<bloque>", card="ui")` (la tarjeta), `panel="ui"` (un panel
lateral que se abre con *Editar*), o los dos. Corre en un `iframe` aislado y **sin red**: nada
de CDN ni `fetch`; todo lo suyo va en `ui/`.

Habla con la app con `postMessage`, un objeto con `v: 1` y un `type`:

```js
const send = (m) => parent.postMessage({ v: 1, ...m }, "*");
window.addEventListener("message", (e) => {
  const m = e.data;
  if (m?.v !== 1) return;
  if (m.type === "init" || m.type === "update") pinta(m);   // el estado de su bloque
  if (m.type === "reply") resuelve(m.id, m);                // {id, ok, result | error}
});
send({ type: "ready" });            // al cargar: la app contesta con "init"
```

- `init` y `update` traen `params`, `specs` (cada parámetro con `default`, `unit`, `label`),
  `outputs` (lo último que dio el bloque: `{puerto: {campo: {value, unit, label}}}`),
  `status`, `error`, `block` (`id`, `type`, `title`), `surface` (`card` o `panel`) y `theme`.
- Lo que puede pedir: `setParams` `{params}` (pasa por la misma validación que la tarjeta),
  `run` (ejecutar el bloque), `preview` `{id, params}` (la vista previa del bloque con esos
  parámetros; contesta un `reply`), `action` `{id, name, args}` (una acción de su paquete,
  `pack.action`; contesta un `reply`), `resize` `{height}` (el alto que necesita),
  `openPanel`, `closePanel` y `toast` `{text, kind: "info" | "error"}`.
- Las cifras que pinte la interfaz salen de `outputs` o de un `preview` o `action`: nunca las
  calcula ella por su cuenta (la regla de los números).
