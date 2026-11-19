"""SDK de BoardPrint (docs/PLAN_PAQUETES.md §2, P22): la única superficie de la app que un
paquete puede usar.

- `boardprint_sdk.packs`: lo de `register(pack)` y los bloques (`Param`, `Fix`, `Pull`,
  `ConfirmRequired`, `RunContext`, `PackBuilder`…).
- El lado común (`pizarra_engine.core`: parámetros, unidades, informe, `fusion_io`) sigue en el
  motor, que también va a Fusion (§6).

**Versión semántica.** `pack.toml` pide un rango (`sdk = ">=1.0,<2"`) y la app no carga un
paquete cuyo rango no cumple esta versión. `tests/test_sdk.py` fija la superficie pública:
quitar o cambiar un nombre o una firma sube la versión mayor; añadir, la menor. Cada cambio va
al changelog de abajo.

Changelog:
- 1.0.0 (FF 10.1 paso 2): `packs` con el contrato de FF 4.4 a FF 5.1, movido de `pizarra.packs`.
- 1.1.0 (FF 10.5 paso 1): `PackBuilder.view` y `View` (qué pintan la tarjeta y el panel: la
  interfaz propia o controles genéricos, §5), `PackBuilder.action` y `Action` (lo que llama la
  interfaz propia, P40). Con el paso 3, aún sin publicar: los controles `chart` y `view2d` y
  los campos que pintan (`chart`, `view2d`, `box`, `line`, `point`, P52).
- 1.2.0 (FF 10.8 paso 1): `PackBuilder.connector` y `Connector` (el conector de un paquete,
  §6, P38), `connector=` en `PackBuilder.block` y `BlockType.connector` (P41), y en
  `RunContext` lo que un paquete hace en la pizarra desde una acción (P39): `block`,
  `upstream`, `set_params`, `postits`, `add_postit`, `clear_error` y `block_file`.
  Con el paso 2, aún sin publicar: `RunContext.block_type` (el tipo de un bloque de otro
  paquete, para el conector, P57) y `formerly=` en `PackBuilder.block` y `BlockType.formerly`
  (los ids de antes de un bloque, P59).
- 1.3.0 (FF 5.2 paso 2): `Pull.accept` (cómo entra lo aceptado al traer en el bloque de
  delante: el terminal lo escribe en su árbol, docs/PLAN_TERMINALES.md T28).
- 1.4.0 (FF 4.7 paso 4): `Param(choices={valor: etiqueta})` y `Param.choice_labels` (lo que
  enseña la interfaz de cada opción; se guarda el valor, D181).
"""
__version__ = "1.4.0"
