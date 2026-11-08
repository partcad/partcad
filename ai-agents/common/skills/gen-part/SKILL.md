---
name: gen-part
description: Generate a PartCAD part from a natural-language description (and optional reference images, drawings, 3D files or requirements) by writing down what it is required to be, settling its dimensions on temporary sketches that /pc:gen-sketch measures and validates, authoring a CAD script (or extruding a validated sketch), and validating it with the PartCAD CLI - including measuring the same dimensions again on the part's own projections. Use for /pc:gen-part or when the user asks to generate, create, or model a single mechanical part.
---

# pc:gen-part

Generate one PartCAD **part**. The text after the command (`$ARGUMENTS`) is the
part description — what to build. *You* author the CAD script yourself and prove
it works with the PartCAD CLI; do not use any built-in `ai-*` part type or
generation pipeline. Hard requirement: the finished part **passes `pc test`** (its
geometry instantiates cleanly).

Steps 4–7 are the reference flow — the shape the legacy `pc add part --ai`
pipeline used (plan geometry → write script → validate → compare → refine), with
the dimensions settled first and measured last: settle the dimensions on
sketches → plan → write the script → validate → measure and compare → refine.
Treat it as a strong default, not a script: skip, reorder, or replace steps as
the part warrants, but always finish by validating, and never let a stated or
shown dimension reach the model without having been measured.

## 1. Understand the request

- `$ARGUMENTS` is the description. Read it and any `requirements`, and view
  reference images directly. Ask the user to clarify only genuinely load-bearing
  ambiguities; otherwise proceed and state your assumptions.
- Work in millimeters and degrees unless told otherwise.
- Put the origin where the part rests: a part that stands on its own has its
  base on z = 0, which is the floor of the scene it is simulated in.
- Separate **what the part is required to be** from how you are going to model
  it. The first is what the user said — "holds a 2 kg shelf", "four M3 holes on
  a 40 mm square", "under 50 g" — and it is written down in §5 as the part's
  `requirements:`, before the design is judged against it. The second is your
  choice, and stays out of them.

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:setup executable` first.

### Is an IDE watching?

Then ask, once, whether there is an IDE to show the work in as it goes:

```sh
pc --no-ansi ide state > /dev/null
```

That asks the PartCAD IDE on this machine (VS Code with the PartCAD extension,
or the PartCAD IDE itself) what it is showing. It needs no package and no
daemon, so it can be asked before anything exists. If it fails saying that no
PartCAD IDE is running, there is none: skip every `pc ide view` below and do not
bring it up. Any other answer, including an IDE too old to report its state,
means one is listening, and the part is shown in its 3D view as it takes shape
(§7).

## 3. Choose a representation

Pick the script kind that best fits the part — you decide:

| Kind | Good for |
| --- | --- |
| `build123d` | general parametric solids (recommended default) |
| `cadquery` | fluent / CSG-style modeling |
| `scad` (OpenSCAD) | simple constructive geometry, no Python |
| `sdf` | organic / implicit shapes |
| `extrude` / `sweep` | a constant profile, straight or along a path: built from the sketch §4 validated, with no script at all |

A part that is nothing but one box or one cylinder needs no script at all:
declare it as `type: basic` with a `cuboid:` (a number for a cube, or
`[x, y, z]` sizes) or a `cylinder:` (`radius`, `height`, standing along Z).
Both are centred on the origin; move them with `offset:`. PartCAD writes the
geometry itself, without a sandbox. There is no file to write
and nothing for `pc add part`; put the declaration in `partcad.yaml` as §5 shows
and go on from there.

## 4. Settle the dimensions on sketches, then plan the geometry

A dimension is decided in 2D before it is spent in 3D. In 2D it is measured
exactly and cheaply, on one projection; in 3D a wrong number hides behind other
faces, and finding it costs a rebuild and a set of renders that still only
*show* it. So before any geometry, run `/pc:gen-sketch` §3–§8 as a **dimension
study** (its §9): whenever the description, a reference image, a drawing or an
object to reproduce gives the part any dimension at all — which is nearly
always — and even when none of the sketches will be used to build it.

1. **Normalize the input to 2D** the way `/pc:gen-sketch` §4 says: a 3D
   description is materialized as a temporary part and projected with
   `pc adhoc render part --input build123d`; a 3D file is projected with
   `pc adhoc render part`; a drawing, a photo or an isometric is measured with
   its projection method taken into account.
2. **Write the dimension table** (`/pc:gen-sketch` §3): every dimension stated,
   derived or measured, with its tolerance, its source and the two features it
   is measured between. It is a design input, not a requirement; the
   requirements of §5 say what the user asked for in their words.
3. **Draw a temporary sketch per view that carries dimensions** —
   `<name>/dims-front`, `<name>/dims-top`, `<name>/dims-right`, each in that
   view's picture coordinates — render each with both projections, reconcile
   them and measure with `measure.py` (`/pc:gen-sketch` §5.2, §7), and iterate
   until every row of the table is within tolerance.

What comes out is the validated table: the source of every number the part is
built from (§5), and what its own projections are measured against (§7).

**Build from the sketch where that is the most efficient way.** A part that is
one constant profile is an extrusion of the validated sketch, and needs no
script:

```yaml
parts:
  <name>:
    type: extrude
    sketch: <name>/dims-top        # the validated profile
    depth: 10
    desc: <the description>
    manufacturable: false
    parameters:
      material:
        type: string
        default: //pub/std/manufacturing/material/plastic:pla
```

`type: extrude` extrudes along the sketch's +Z from z = 0, so the profile is the
part's `top` view and its base is on the floor. A part whose constant profile
belongs to its front or side view comes out lying on that face: take that only
where its orientation does not matter, and otherwise write the script.
`type: sweep` takes a section along a path (`axis:`). Neither has a script for
`pc add part` to register, so write the declaration by hand; the sketch it is
built from stops being temporary.

Then, for anything non-trivial, plan the constructive solid geometry —
coordinate system, primitives with dimensions/positions/orientations, then
unions/differences/intersections and fillets/chamfers — with every dimension
taken from the table. This mirrors the legacy "CSG" step and usually cuts
iterations.

## 5. Author, register, and mark it

Write the script file **first** from `$ARGUMENTS` (plain type — never `ai-*`),
taking every dimension from the table §4 validated — the same constants under
the same names, placed from the same datums — then register it; `pc add part`
requires the file to already exist (an `extrude` or `sweep` part has no file, and
is declared by hand as §4 shows; nor has a `basic` part, which is declared by
hand as shown below and skips the script and `pc add part` altogether):

```sh
pc --no-ansi add part --desc "<the description>" <kind> <name>.<ext>   # e.g. build123d bracket.py
```

Language conventions for the script:

- **build123d / cadquery / sdf (Python):** import everything you use (including
  `math` and the library itself); call `show_object(<result>)` to expose the
  part; do not export anything. For cadquery, avoid `tetrahedron` / `hexahedron`.
- **OpenSCAD:** a complete script defining all functions and constants; no
  external modules; no export.

Then mark the part **not manufacturable** in `partcad.yaml` — a generated part is
not a catalog/supplier item, and this is what lets `pc test` pass:

```yaml
parts:
  <name>:
    type: <kind>
    path: <name>.<ext>
    desc: <the description>
    manufacturable: false
```

A `basic` part has its solid where a script part has its `path:`, and is placed
by its `offset:` (it is built centred on the origin):

```yaml
parts:
  <name>:
    type: basic
    cuboid: [<size x>, <size y>, <size z>]   # or a number for a cube, or
    # cylinder: {radius: <r>, height: <h>}   # standing along Z
    offset: [[<x>, <y>, <z>], [0, 0, 1], 0]  # optional
    desc: <the description>
    manufacturable: false
```

### Write down what it is required to be

Then add `requirements:` to the same declaration — what the description asked
for, in the description's own terms, *not* the design you chose. `pc test`
checks the model against what it can measure — the `ports:`, `interfaces:`,
`physics:` and `match:` — and `/pc:validate` judges the `features:`, which are
prose; the IDE shows both as the part's Requirements tab:

```yaml
    requirements:
      features:                       # everything asked for, a name and a sentence each
        mounting: Four M3 clearance holes on a 40 mm square, reachable from the top
        shelf-load: Holds a 2 kg shelf at its free end without visible bending
      physics:                        # only what the description bounds
        mass: "<0.05"                 # kg
```

- **`features:`** is where most of it goes. One per thing asked for — a
  dimension that matters, a feature that has to be there, something it has to
  survive — named so it can be referred to, and stated the way the user stated
  it.
- **`physics:`** is any field of a `physics:` section, required as a value
  (`0.05`), a comparison (`"<0.05"`, `">0,<=1"`), or alternatives (`"1,2"`).
  Only what the description actually bounds. A mass is worked out from the
  measured volume and the part's material (`properties: material:`), so require
  one only where the part names a material with a density, or states its mass;
  a requirement PartCAD cannot evaluate fails as "not known".
- **`ports:`** and **`interfaces:`** are for a part that connects to something
  (a bolt pattern, a plug, a rail), naming what it has to have and as much of
  where as matters — anything may be `null`, and most of it should be:

  ```yaml
      ports:
        top: [null, [0, 0, 1], null]    # a port called 'top', anywhere, facing up (+Z)
      interfaces:
        m3-thru: null                   # implements it (or something inheriting it), anywhere
  ```

  The middle element is the way the port *faces* (its Z axis), not the axis its
  location is rotated about. Write these only when the description says how the
  part connects; `/pc:add-interfaces` then adds the ports that meet them.
- **`match:`** is for a part asked for *relative to another object* —
  "like the old bracket, but no more than 5% heavier", "a replacement within
  2% of the original's volume". Key it by the other object's name (`:sibling`
  or `//package:name`), with `volume`, `displacement` and `mass` (or `weight`)
  as a percentage of that object's, either way. `displacement` is the volume
  and every void sealed inside it — what the part takes up rather than what it
  is made of — for a part that has to fill the space the other one did:

  ```yaml
      match:
        :bracket-v1:
          mass: 5%                      # within 5% of what bracket-v1 weighs
  ```

  `pc test` reads it by the numbers `pc compare :bracket-v1 <name>` reports
  (§7). A mass needs a material with a density on both objects, as above.
- If the part declares a `simulate:` entry that demonstrates one of the
  features, say which with `feature: <name>` on that entry.

Leave out what the description did not ask for. A requirement you invented is a
design decision written where nobody will question it.

If the part was modelled from reference images — a drawing, a photo, a sketch —
name them under `images:` as well, as paths relative to the package. That is what
puts them beside the part in the README `pc render` writes, so a reader sees what
the model was made to match; nothing else reads them.

```yaml
    images:
      - drawing.png
      - photo.jpg
```

**Say what it is made of.** PartCAD derives the part's mass, centre of mass and
inertia from its solid and its material's density, so a part that names a
material never needs a guessed mass — and one that names none has no mass at
all, which every simulation of it then makes up. The script types (`build123d`,
`cadquery`, `scad`, `sdf`) take a `material` parameter, which the script does
not have to read; a `step` part rejects it and states `properties: material:`
instead.

```yaml
    parameters:
      material:
        type: string
        default: //pub/std/manufacturing/material/plastic:pla
```

Pick from the standard catalogues — `pc list materials
//pub/std/manufacturing/material/plastic` (`pla`, `petg`, `abs`, `nylon`, …) or
`.../metal` (`al-6061-t6`, `steel-1018`, `ss-304`, …). When none fits, declare
one under `materials:` and name it as `:<material>`: `density` in kg/m³ (a
datasheet's 1.32 g/cm³ is `1320`), and `mu`, the sliding friction, if the part
will rest on or slide against something. Where grip matters and the material
states no `Mu` (`pc info` shows it under `Material`), give the part a `friction`
under `properties: physics:` from a datasheet — otherwise the engine uses a
default nobody chose.

If you started the project with `pc init`, also delete the empty `sketches:` and
`assemblies:` sections it leaves — a null section crashes `pc render` on older
PartCAD (fixed in partcad/partcad#470).

## 6. Validate

`pc test` is the build gate: with `manufacturable: false`, its CAD check passes
only if the geometry instantiates cleanly, and the manufacturability checks are
skipped. Its `requirements` check holds the model to the `ports:`, `interfaces:`
and `physics:` you wrote down in §5, and says which one is not met and what it
found instead; `pc --no-ansi -v test -f requirements <name>` lists every one.

```sh
pc --no-ansi test <name>
```

Three of its checks fail geometry that instantiates perfectly, and all three are
about a part that would look right in the pictures rendered below: `shell` (the
part is a surface rather than a body — the faces do not close, so it has no
inside and every boolean against it is meaningless), `degenerate` (it has no size
left in some direction) and `solidity` (its faces are oriented inward, so its
volume is negative). **None of them can be turned off on the part** — there is
no such setting, and inventing one is rejected by `pc lint`. Fix the geometry:
close the shape, keep the feature that collapsed, orient the faces outward. A
part that fails one of these is a part nothing downstream can compute with,
however good the picture of it looks.

Then weigh it. `pc --no-ansi info <name>` reports `MassProperties` — `mass` in
kg, `centerOfMass` in mm, `inertia` in kg·m² — each with the `source` it came
from. Check the mass against what the real object would weigh (a 20 mm aluminium
cube is 21.6 g). A mass reported as not known is a part with no material; one a
thousand or a million times off is a density in the wrong unit, here or in the
catalogue. State `properties: physics:` only for what is *known* and the solid
cannot say — a hollow body, a print's infill, a weighed part — because a stated
value overrides the derived one. `mass` alone keeps the solid's inertia, scaled
to it:

```yaml
    properties:
      physics:
        mass: 0.045 # kg, weighed
```

## 7. Render it from several angles, compare, and iterate

`pc test` proves the geometry instantiates. It says nothing about whether the
geometry is the part that was asked for — that is decided by looking at it.

One picture is not enough to decide it. A projection hides everything behind it,
so a hole in the wrong face, a feature on the wrong side, a chamfer that never
got cut, or a shape that is right in outline and wrong in depth all survive the
one view that happens to conceal them. Render **four**: `front`, `top` and
`right` to read proportions and dimensions off, and `iso` to see how the features
go together. A rendered file is named after the object, so give each view a
directory of its own or they overwrite each other:

```sh
for view in front top right iso; do
  mkdir -p /tmp/pc-render/$view                  # -O expects it to exist
  pc --no-ansi render -t png --view $view -O /tmp/pc-render/$view <name>
done
```

Then view all four — `/tmp/pc-render/<view>/<name>.png` — and compare them
against the description and any reference images:

- the overall form and the bounding size, in all three axes;
- every dimension in the table — measured, below, not judged from the picture;
  a dimension no view confirms is one still assumed;
- every feature that was asked for, on the face it was asked for, and nothing
  present that was not — the `features:` you wrote down in §5 are the list to
  go through.

Add `back`, `left` or `bottom` whenever the part is not symmetric about the axis
in question: an asymmetric part has a face you have not seen, and a face you have
not seen is a face you are guessing about. When no named view shows the feature
you need to check, `--viewport-origin X,Y,Z` and `--viewport-up X,Y,Z` look from
an arbitrary direction. `/pc:render` covers these options in full.

### Measure the dimensions on the part

The PNGs show the shape. The numbers are measured the way the sketches' were:
render the views the study covered as SVG with **both** of PartCAD's
projections, and measure them with `measure.py`, which is in the
`/pc:gen-sketch` skill's directory. The two draw one part as different shapes
and different numbers of them — an arc as one curve or as a run of short lines,
an edge whole or broken — so a reading only one supports is not a reading of
the part (`/pc:gen-sketch` §5.2 says how to read `compare`). Say which on
every render — `--reproducible` and `--no-reproducible` — since left unsaid, the
package's file type decides:

```sh
for view in front top right; do
  D=/tmp/pc-render/svg/$view
  mkdir -p $D/polygonal $D/exact
  pc --no-ansi render -t svg --view $view --no-reproducible -O $D/polygonal <name>
  pc --no-ansi render -t svg --view $view --reproducible -O $D/exact <name>
  python3 <the /pc:gen-sketch skill's directory>/measure.py compare $D/exact/<name>.svg $D/polygonal/<name>.svg
  python3 <the /pc:gen-sketch skill's directory>/measure.py svg $D/exact/<name>.svg
done
pc --no-ansi info <name> 2>&1      # BoundingBox: the overall size, from the kernel
```

Each view of the part must measure what that view's sketch did: put both in the
table — target, measured on the part, error, tolerance — and every row has to be
within its tolerance. A projection draws only what can be seen, so measure a
feature in the view that sees it (a hole's diameter along its axis, a step's
height from the side); an extent is checked against `pc info` too.

A row out of tolerance is a defect of the script, and the error says what to
change, the way `/pc:gen-sketch` §8 reads it: in proportion is a scale, a
common offset is a datum, one dimension is its constant. Correct it from the
error rather than by eye.

Fix any error or mismatch, then re-test, re-render and measure again. Iterate
until every view matches and every dimension is in tolerance — no fixed retry
count. `/pc:describe` renders a dimensioned drawing of the finished part, for a
person to read.

### Compare it with the 3D reference, when there is one

A part made to reproduce a 3D file — a STEP model, a scan as STL, a part from
another package — has a better check than any projection: read the candidate
against the reference itself. `pc compare` is the 3D counterpart of
`measure.py compare`: the first object is the reference, the second the
candidate, and every difference is the candidate's less the reference's.
Declare the reference as a part of its own first (`pc add part step <file>`,
or name the other package's part), then:

```sh
pc --no-ansi compare --json --surface-distance 1 <reference> <name> 2>/dev/null
```

`--surface-distance 1` measures at points 1 mm apart over the whole reference
— every vertex, then along every edge, then over every face — how far the
candidate's surface is along the reference's normal there: positive where the
candidate stands outside the reference, negative inside. Pick the spacing from
the size of the smallest feature that has to be right (half of it is a good
start); it is refused, saying which spacing would do, when it would take too
many points. Read, in the JSON:

- `volume` and `mass`: `percent` is how far off the candidate is as a whole. A
  large difference with a small surface distance is a missing or extra
  feature the points fell beside; look at `surface.worst`. A volume that is off
  while the surface is not can be a void sealed inside one of the two, which
  the surface points never reach: add `--displacement`, and compare
  `displacement` and each side's `cavities`.
- `surface.distance`: `min` and `max` (signed), `rms`, and the `p95` of the
  distance's size. A consistent sign is a scale or an offset — a `mean` close to
  `max` on every face says a dimension is too large by that much; a distance
  that is large only at `surface.worst` points says where a feature is
  wrong.
- `surface.beyond`: how many points are further apart than the two
  tolerances added up (`tolerance.allowance`). Give the candidate the
  `tolerance:` it is to be made to, where its type takes one, so that this is a
  verdict rather than a count of every non-zero distance.

Correct the script from the numbers, the way §7 corrects a dimension from its
error, and compare again until the surface is within the allowance. The two
are compared where they are, so a candidate whose origin is not the
reference's measures as far off as its origin is: put the origin where the
reference has it.

### Show each version that renders

Under an IDE (§2), show each version of the part in its 3D view as soon as it
passes the basic checks: the geometry builds (`pc test` finds nothing wrong with
the shape itself; a requirement not met yet does not count against it) and all
four views above rendered without an error. Do it on every pass through this
section, right after the renders and before you compare them:

```sh
pc --no-ansi ide view --design-3d <name>    # the first time: brings the 3D tab forward
pc --no-ansi ide view <name>                # every time after: stays on whatever tab the person chose
```

The 3D view turns the model on its own (its Animate box is on by default
wherever there is a graphics card). A show after the first keeps the angle the
turn had reached, whatever the name, and then brings the camera in or out over
a second until the new version fits however it turns. So each version replaces
the previous one while the turn carries on, and the person watching sees the
part take shape, never cut off by the frame or lost in the middle of it.

The same name shown again is fitted only while the view's **Auto-fit** box is
ticked, which it is by default. Someone zoomed in on one feature unticks it, and
then each new version appears in exactly the view they chose. That is their
setting: leave it alone, and do not work around it by showing the part under
another name.

Show only what passed. A version that does not build or render stays off the
screen, so the view always holds the last version that worked. The show is for
the person, not a check: the four PNGs are still what you compare. If a show
warns that no IDE was detected, the window has been closed, so stop showing.

## 8. Finalize

Summarize what you built — the dimension table (target, measured on the part,
error), material and mass, how far it is from its 3D reference if it had one
(`pc compare`'s volume, mass and surface distance), and assumptions — and how to view it: `pc ide view <name>`, which under an IDE is what is already
on screen (§7). Offer `/pc:validate <name>` for a verdict on every requirement,
the features included.

Remove the temporary sketches the part is not built from — their declarations
and their files (`/pc:gen-sketch` §9) — unless the user wants them kept; keep,
and describe, the sketch an `extrude` or `sweep` part is built from.

If the description claims something physical of the part on its own — it rests
without rolling, it floats — declare that claim as a `simulate:` and check it
with `pc sim`. A part takes the same section an assembly does; `/pc:gen-assembly`
§7 shows how. Name the feature it demonstrates with `feature: <name>`.

If the part is meant to connect to something — a bolt pattern, a plug, a rail —
say so and offer `/pc:add-interfaces`, which adds the ports and interfaces that
let PartCAD mate it automatically. Once it has them, `--with-all` draws them on
the very views you have been comparing against, so a port that is in the wrong
place or facing the wrong way is visible rather than inferred:

```sh
for view in front top right iso; do
  mkdir -p /tmp/pc-render/ports/$view
  pc --no-ansi render -t png --view $view -O /tmp/pc-render/ports/$view --with-all <name>
done
```

Four views again, and for the same reason: a port is a coordinate frame, and one
projection collapses the axis it is offset along just as it does for geometry.
`--no-ansi` because every port drawn is also named on stderr, which is where the
exact string to write in an ASSY file comes from. `/pc:add-interfaces` covers
reading these drawings in full.
