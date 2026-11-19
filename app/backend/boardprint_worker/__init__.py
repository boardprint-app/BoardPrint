"""Trabajador de paquetes (docs/PLAN_PAQUETES.md P19, §4, P89-P91).

Corre en el *entorno de paquetes* (un Python de verdad con las librerías de los paquetes), no
en el backend: `python -m boardprint_worker`. Habla con el backend por stdin/stdout, un
mensaje JSON por línea, con el protocolo v2 que describe `__main__`: registrar los paquetes
(que vuelven como datos, `pizarra.pack_data`), ejecutar un bloque (con progreso y
confirmación), la vista previa, las acciones (que piden a la pizarra lo de la API de P39) y
los conectores. El backend lo maneja con `pizarra.pack_host`.

Lo que un paquete escriba en stdout (un `print`, o una librería de C con `printf`) va a
stderr: el canal es solo del protocolo.

Viaja como recurso de la app (`worker/`) con lo que necesita del backend para cargar: el SDK
(`boardprint_sdk`) y, de `pizarra`, `packs`, `pack_data`, `pack_validate`, `pack_versions` y
`files`, solo biblioteca estándar.
"""
