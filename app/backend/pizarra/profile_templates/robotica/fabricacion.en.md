# Manufacturing profile: robotics (end effectors and arms)

> **Generic template.** Order-of-magnitude values to get started, written without looking at
> any particular workshop or manufacturer: they are not manufacturer or supplier data. Replace
> them with your workshop's before relying on them: the design agent and the reviewer read
> this text as it is. Delete what does not apply.

## What is made

- End effectors (grippers, suction cups, fixtures) and light arms with 4 to 6 axes, carrying
  a few kg at the tip.
- Prototypes and short runs (from 1 to a few dozen units).

## Aluminium machining

- 3-axis CNC mill, with a travel of the order of 600 × 400 × 300 mm.
- Material: 6061-T6 or 6082-T6 aluminium plate and bar; 7075-T6 for the most loaded parts.
- Tolerances: ±0.1 mm in general; ±0.02 to ±0.05 mm on bearing seats and locating holes (H7).
- Minimum wall thickness: of the order of 1.5 mm; minimum inner radius, the cutter's (1 mm or
  more; 3 mm is better).
- M3 to M8 threads with a thread length of at least 1.5 times the diameter; helical inserts
  where parts are often assembled and taken apart.
- Anodising adds of the order of 10 to 25 µm per face: allow for it in fits.

## 3D printing

- FDM, with a build volume of the order of 250 × 250 × 250 mm: PLA for trials; PETG or
  fibre-filled nylon for functional parts.
- Tolerances: ±0.2 to ±0.3 mm; holes come out about 0.2 mm undersize (ream them with a drill).
- Walls of 1.2 mm or more (three perimeters with a 0.4 mm nozzle); overhangs up to about 45°
  without supports.
- The part is weaker between layers: put the load in the plane of the layer.
- Threads with brass heat-set inserts (M3, M4), not tapped into the plastic.

## Sheet metal

- Steel from 0.8 to 3 mm, stainless from 0.8 to 2 mm and aluminium from 1 to 3 mm, laser cut
  and bent (usually outsourced).
- Tolerances: ±0.1 mm on the cut; ±0.3 to ±0.5 mm and ±1° on bends.
- Inner bend radius of the order of the thickness; holes two thicknesses or more from the bend;
  minimum flange of about four thicknesses.

## Slotted profile

- Slotted aluminium profile, in 20, 30 and 40 mm series (slot from 6 to 10 mm depending on the
  series), cut to length within ±0.5 mm.
- Joints with angle brackets and T-nuts; brackets on both faces when it has to be stiff.
- For benches, frames and the base of the arm, not for links that rotate (it is heavy and has
  play).

## What is bought

- Bearings, shafts, ISO fasteners, motors and gearboxes are bought from a catalogue, never
  made. Their data come from their record in the library, not from this profile.

## What is outsourced and to whom

- (e.g. anodising, sheet laser cutting and bending, heat treatments)
