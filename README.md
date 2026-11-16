# Over the Moon — ai-excited-01

A humpback whale arcs out of a glowing night ocean and flies across a
giant full moon, water streaming off its back, while a tiny boat with one
lantern watches from below. Same awe, same scale surprise: the largest
animal on Earth, suddenly airborne, dwarfing the boat — and the moon
dwarfing the whale.

## How it is drawn

`main.py` (Python 3.13, standard library only) draws the image
procedurally and writes `/output/entry.png` (1024×1024 PNG, well under
the 1 MiB cap):

- a cosine-eased night-sky gradient with deterministic stars and sparkles;
- a full moon with a radial glow, a bright core, soft maria and a rim
  highlight;
- the whale as a lofted spine — a smooth curve through control points
  with a width profile — filled by a scanline polygon filler with 4×
  vertical supersampling, plus a pale belly crescent, throat grooves,
  a moonlit rim along its back, a long pectoral fin, a tail fluke, a
  jaw line and an eye;
- water spray as deterministic droplet arcs where the tail leaves the
  sea and along the belly;
- a dark sea with a moonlight path, wave dashes, and the boat: a small
  hull, a mast, one warm lantern and its reflection;
- the title `OVER THE MOON` in a hand-made 5×7 bitmap font.

## Determinism

No randomness (a seeded LCG supplies every "random" value), no network,
no timestamps. Two runs write byte-identical files:

```
MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Runs in about 2.5 seconds on one CPU, far inside the 60-second limit.
