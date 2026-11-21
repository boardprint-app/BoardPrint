# Perfil de fabricación: robótica (terminales y brazos)

> **Plantilla genérica.** Valores de orden de magnitud para empezar, escritos sin mirar ningún
> taller ni ningún fabricante concreto: no son datos de fabricante ni de proveedor. Cámbialos
> por los de tu taller antes de fiarte de ellos: el agente de diseño y el revisor leen este
> texto tal cual. Borra lo que no aplique.

## Qué se fabrica

- Terminales (pinzas, ventosas, utillajes) y brazos ligeros de 4 a 6 ejes, con unos pocos kg
  de carga en el extremo.
- Prototipos y series cortas (de 1 a unas decenas de unidades).

## Mecanizado de aluminio

- Fresadora CNC de 3 ejes, con un recorrido del orden de 600 × 400 × 300 mm.
- Material: aluminio 6061-T6 o 6082-T6 en placa y barra; 7075-T6 para las piezas más cargadas.
- Tolerancias: ±0,1 mm en general; ±0,02 a ±0,05 mm en alojamientos de rodamiento y agujeros
  de centraje (H7).
- Espesor mínimo de pared: del orden de 1,5 mm; radio interior mínimo, el de la fresa (1 mm o
  más; mejor 3 mm).
- Roscas M3 a M8 con una longitud de rosca de al menos 1,5 veces el diámetro; insertos
  helicoidales donde se monta y desmonta a menudo.
- El anodizado añade del orden de 10 a 25 µm por cara: tenerlo en cuenta en los ajustes.

## Impresión 3D

- FDM, con un volumen del orden de 250 × 250 × 250 mm: PLA para pruebas; PETG o nailon con
  fibra para piezas funcionales.
- Tolerancias: ±0,2 a ±0,3 mm; los agujeros salen unos 0,2 mm por debajo de su medida
  (repasarlos con broca).
- Paredes de 1,2 mm o más (tres perímetros con boquilla de 0,4 mm); voladizos de hasta unos
  45° sin soportes.
- La pieza es más débil entre capas: orientar la carga en el plano de la capa.
- Roscas con insertos térmicos de latón (M3, M4), no roscando el plástico.

## Chapa

- Acero de 0,8 a 3 mm, inoxidable de 0,8 a 2 mm y aluminio de 1 a 3 mm, en corte láser y
  plegado (normalmente externalizados).
- Tolerancias: ±0,1 mm en el corte; ±0,3 a ±0,5 mm y ±1° en el plegado.
- Radio interior de plegado del orden del espesor; agujeros a dos espesores o más del pliegue;
  ala mínima de unos cuatro espesores.

## Perfil ranurado

- Perfil ranurado de aluminio, en series de 20, 30 y 40 mm (ranura de 6 a 10 mm según la
  serie), cortado a medida con ±0,5 mm.
- Uniones con escuadras y tuercas en T; con escuadras por las dos caras si tiene que ser rígido.
- Para bancadas, bastidores y la base del brazo, no para eslabones que giran (pesa y tiene
  holguras).

## Lo que se compra

- Rodamientos, ejes, tornillería ISO, motores y reductoras se compran de catálogo, nunca se
  fabrican. Sus datos, de su ficha en la librería, no de este perfil.

## Qué se externaliza y a quién

- (p. ej. anodizado, corte láser y plegado de chapa, tratamientos térmicos)
