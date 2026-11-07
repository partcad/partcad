---
name: gen-sketch
description: Generate a PartCAD 2D sketch (build123d / cadquery / basic / dxf / svg) whose dimensions are measured to match the request rather than estimated - normalize the input to 2D (a description, a drawing, a photo, a projection, or a 3D model projected with `pc adhoc render`), measure the target dimensions, author a candidate, render it with both of PartCAD's projections (`--reproducible` and `--no-reproducible`, which draw the same geometry as different shapes), measure the same dimensions on both with the bundled measure.py and reconcile them, and iterate until every error is within tolerance. Use for /pc:gen-sketch, when the user asks to generate, create, draw or trace a 2D sketch, profile, outline, cross-section, footprint or blueprint, and as the dimension study /pc:gen-part and /pc:gen-assembly run before they model.
---

# pc:gen-sketch

Generate one PartCAD **sketch** — a 2D profile — whose dimensions are the ones
that were asked for. *You* author the sketch; there is no built-in `ai-*` sketch
type. Two hard requirements:

- the sketch **renders without errors**, and
- **every target dimension, measured on the rendering, is within its
  tolerance** — or the sketch is reported as not meeting it, with the numbers.

A sketch that looks right is not the goal. A dimension is right only once it has
been measured on the result and compared, as a number, with the number it was
meant to be. So this skill works in a loop that never estimates where it can
measure: write the targets down (§3), get them out of the input by normalizing
it to 2D and measuring it (§4, §5), draw a candidate (§6), render it and measure
the *same* dimensions on the rendering (§7), and compare (§8) — iterating with
the error in hand until there is none worth the name.

The same loop is what `/pc:gen-part` and `/pc:gen-assembly` run first, on
**temporary sketches**, to settle a part's dimensions and an assembly's
placements before modelling anything (§9).

Sketches are not manufacturable, so unlike parts they need no
`manufacturable:` flag and skip the `cam` tests.

## 1. Understand the request, and what the input is

`$ARGUMENTS` is the description. Read it and any `requirements`, and look at
every reference image or file directly. Work in millimetres unless told
otherwise — an inch is 25.4 mm exactly, and a drawing in inches is converted
once, in the table of §3, not in the sketch. Ask the user only about genuinely
load-bearing ambiguities: which view a profile is, whether a dimension is a
radius or a diameter, which edge it is measured from.

Then say which of five kinds of input this is, because each is normalized to 2D
differently (§4):

| Input | Example | Normalized by |
| --- | --- | --- |
| **2D description** | "a 100 × 60 plate, Ø5 holes 8 mm in from each corner" | nothing: the numbers are stated |
| **2D object** | a DXF or SVG file; a scan, screenshot or photo of a flat drawing or a flat part | re-rendering the file with `pc adhoc render sketch`; measuring the picture's pixels |
| **3D description** | "a 40 mm cube with a Ø10 hole through the top, 12 mm from the back" | a temporary part, projected with `pc adhoc render part` |
| **3D projection** | a multi-view drawing, an isometric, a photo or render of an object | measuring it, with its projection method taken into account |
| **3D object** | a STEP / STL / BREP / … file, or a part in a package | projecting it with `pc adhoc render part` (or `pc render`) |

## 2. Make sure PartCAD is available

Resolve a command as `/pc:init` does (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`). If none is found, stop and run
`/pc:setup executable` first. Pass `--no-ansi` on every run — it is a global
flag, goes before the subcommand, and sends the log to stderr. The first
command that renders anything builds PartCAD's CAD sandbox and can take
minutes; every one after it is quick.

The measuring helper is `measure.py`, beside this file: `svg` measures a
drawing, `compare` reads two renders of one object against each other (§5.2),
and `image` measures a raster picture (§5.3). It needs any Python 3, and Pillow
only for `image`:

```sh
python3 <this skill's directory>/measure.py --help
```

If an IDE is running (`pc --no-ansi ide state` answers, as in `/pc:gen-part`
§2), show each candidate that renders with `pc --no-ansi ide view -s <name>`.

## 3. Write the targets down first: the dimension table

Before drawing anything, list every dimension the sketch has to have:

| Dimension | Target (mm) | Tolerance | From | Measured between |
| --- | --- | --- | --- | --- |
| width | 100 | ±0.01 | stated | left edge – right edge |
| hole Ø | 5 | ±0.01 | stated | the circle |
| hole inset x | 8 | ±0.01 | stated | left edge – hole centre |
| hole pitch x | 84 | ±0.01 | derived: 100 − 2 × 8 | hole centre – hole centre |
| slot length | 30.2 | ±0.4 | measured: photo.jpg, row 412 | slot end – slot end |

- **From** is where the number came from: *stated* (word for word from the
  request or a dimension written on a drawing), *derived* (with the
  arithmetic), or *measured* (with the file, and the row, column or feature it
  was measured along, so it can be measured again).
- **Measured between** names the two features, which is the same as naming the
  **datum**. "8 from the edge" and "8 from the centre line" are different
  sketches, and a dimension taken from a different datum than the one it was
  drawn from is the commonest way to be exactly wrong.
- **Tolerance.** A stated dimension is drawn from the very number it is
  checked against, so any error is a modelling mistake: ±0.01 mm unless the
  request gives one. A measured dimension cannot be held tighter than it was
  measured (§5), and no dimension may be looser than what it is for — a bolt
  pattern, a fit or a mating outline asks for the tight end.
- **Check the table adds up** before drawing. Chains must close (the parts of a
  dimension add to the whole), stated and measured values of the same thing
  must agree within their tolerances, and a count must match the pattern it
  is a count of. A conflict goes to the user with the numbers; it is not split
  silently in the sketch.

For a sketch that will be kept, the same table goes into the declaration as its
`requirements:` (§6), the way `/pc:gen-part` writes a part's.

## 4. Normalize the input to 2D and measure the targets

Every input ends up as a 2D drawing whose dimensions can be measured as
distances. Prefer an **SVG** at every step: PartCAD's SVG renders carry the
geometry as numbers, in millimetres, and `measure.py` reads them exactly. A
picture is measured only when a picture is all there is.

### 4.1 2D description

Nothing to normalize: the targets are the stated numbers, and the derived ones
worked out from them. Go to §6.

### 4.2 2D object

**A DXF or SVG file.** Let PartCAD read it the way a sketch of that type will
be read, and measure what it read:

```sh
mkdir -p /tmp/pc-sketch/ref
pc --no-ansi adhoc render sketch --no-reproducible outline.dxf /tmp/pc-sketch/ref/outline.svg
pc --no-ansi adhoc render sketch --reproducible outline.dxf /tmp/pc-sketch/ref/outline.exact.svg
python3 <this skill's directory>/measure.py compare /tmp/pc-sketch/ref/outline.exact.svg /tmp/pc-sketch/ref/outline.svg
python3 <this skill's directory>/measure.py svg /tmp/pc-sketch/ref/outline.exact.svg
```

A DXF is scaled to millimetres by its own `$INSUNITS` (`pc info` on a `dxf`
sketch says what it said and how much it was scaled by). An **SVG is read at the
size it says it is printed at** — `width="101mm"` over a `viewBox` 20.2 wide is
5 mm per unit — so run `measure.py svg` on the original as well: its `page:`
line gives that scale, and its numbers times that scale must be what the
re-rendered file measures. When the drawing states any dimension, check the
scale against it before trusting the rest.

**Never turn a PartCAD render back into an `svg` sketch.** A render's numbers are
model millimetres, but its page is sized to fit 512 units, so reading it as a
sketch scales it by whatever that came to.

**A raster picture** — a scan, a screenshot, a photo of a drawing or of a flat
part lying flat — is measured in pixels and calibrated (§5.3). Read every
dimension *written* on a drawing as a stated target, and measure only what is
not written, scaled from what is.

### 4.3 3D description

Materialize it as a **temporary part** and project it, so that which dimensions
appear in the view, how long they look there and what hides what are measured
rather than imagined. A build123d script is enough, outside the package — `pc
adhoc render` projects a file that is in none:

```python
# /tmp/pc-sketch/study.py -- only what decides the dimensions of the view
from build123d import Align, Box, BuildPart, Hole, Location, Locations

with BuildPart() as study:
    Box(40, 40, 40, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(Location((0, 20 - 12, 40))):   # 12 mm from the back face (+Y), on the top
        Hole(radius=5)
show_object(study.part)
```

```sh
cd /tmp/pc-sketch
for view in front top right; do
  pc --no-ansi adhoc render part --input build123d --view $view --no-reproducible study.py $view.svg
  pc --no-ansi adhoc render part --input build123d --view $view --reproducible study.py $view.exact.svg
done
python3 <this skill's directory>/measure.py compare top.exact.svg top.svg
python3 <this skill's directory>/measure.py svg top.exact.svg
```

Each view is rendered both ways, as §5.2 asks. **`--input build123d` is not
optional** for a `.py`: it is guessed to be `sdf`, which fails on a build123d
script (`--input cadquery` for a CadQuery one).

A dimension the description leaves open is a parameter of the study: assign it
at the top of the script (`depth = 10` — a build123d or CadQuery script's
parameters are its top-level assignments), and `-p depth=12` renders another
value without editing anything. With no output file named, `-t svg -O <dir>`
writes `study_depth_12.svg` there, so renders of several values sit side by
side.

The temporary part is an instrument, not the deliverable: keep it to the
features the description dimensions. Its value is that a description in 3D
terms ("on the top, 12 from the back") becomes a 2D distance in a named view,
and that a description which does not determine a dimension shows it here — the
view comes out with a feature somewhere you had to choose. Ask about that
choice, or state it as an assumption in the table.

### 4.4 3D projection

Work out the projection method first (§5.4) — which view each part of a drawing
is, and how lengths in it relate to lengths in the object — then measure it as
an SVG (§5.1) or as a picture (§5.3), and correct for the projection.

### 4.5 3D object

Project it into the views the sketch is of — both ways, as §5.2 asks:

```sh
for view in front top right; do
  pc --no-ansi adhoc render part --view $view --no-reproducible bracket.step /tmp/pc-sketch/$view.svg
  pc --no-ansi adhoc render part --view $view --reproducible bracket.step /tmp/pc-sketch/$view.exact.svg
done
```

An object a package already declares is rendered with `pc render` instead —
`pc --no-ansi render -t svg --view <view> --reproducible -O <dir> <name>` and
the same with `--no-reproducible` — so that its package's own render options
apply.
`pc --no-ansi info <name>` adds the kernel's `BoundingBox` — exact, and the
first thing to check every measured extent against.

### The views

A projection is orthographic, and in each named view the picture's axes are
these model axes — which is what makes a number measured in a view a number in
the model:

| `--view` | picture right | picture up | looking along |
| --- | --- | --- | --- |
| `front` | +X | +Z | +Y |
| `back` | −X | +Z | −Y |
| `right` | +Y | +Z | −X |
| `left` | −Y | +Z | +X |
| `top` | +X | +Y | −Z |
| `bottom` | +X | −Y | +Z |
| `iso` | (true isometric from +X −Y +Z) | | |

A sketch is drawn in its own XY plane and rendered as `top` sees it, which is
also how `type: extrude` uses it (along +Z). So a sketch meant to match a part's
`front` view takes the part's X as its X and the part's Z as its Y.

## 5. Measuring

### 5.1 An SVG: measured exactly

```sh
python3 <this skill's directory>/measure.py svg <drawing.svg>
```

It prints, in the drawing's units with Y up (millimetres, for a PartCAD render):

- `extent` — the overall width and height;
- `circles` — every diameter and centre;
- `arcs` — grouped by the circle they are of: radius, centre, sweep;
- `ellipses` — both diameters and the angle: a circle seen at a slant;
- `vertical edges, by x` / `horizontal edges, by y` — each X (Y) at which an
  edge stands, with what it spans. A width or an inset is the difference of two
  of these;
- `other straight edges`, and closed outlines nothing else explains (a hexagon
  is reported across its corners *and* across its flats).

Every position is given from the left and from the bottom of the extent as
well. Use those, or differences between features, rather than absolute
coordinates: where a projection puts the model origin depends on the
hidden-line algorithm that drew it. `--json` gives everything without
truncation.

A curve drawn as a polygon is fitted, and marked `[fitted to N segments,
residual …]`; a residual near zero is a circle or an ellipse its vertices are
on. `[…; N more only near it: a silhouette]` and `[approximate: …]` are curves
the polygon is only near — good to the residual stated, and to 0.05 % of the
object's size at worst. `splines` are curves the file drew as Bézier curves,
and nothing is fitted to them.

### 5.2 Two projections, read against each other

PartCAD draws a projection with one of two hidden-line algorithms, and
`reproducible:` on the `render: svg:` it is drawn with chooses which: `false`,
the default, projects a triangulation; `true` projects the exact surfaces. They
draw the same geometry **as different shapes, and different numbers of them**:
one long arc where the other has several short ones, an arc where the other has
a run of short straight lines, an edge drawn twice, a straight edge in one piece
where the other breaks it wherever another edge touches it, a silhouette that is
exact in one and only near the curve in the other. A reading only one of them
supports is a reading of an algorithm, not of the object.

So every size is read off **both**, and the two are read against each other:

```sh
python3 <this skill's directory>/measure.py compare <exact.svg> <polygonal.svg>
```

It pairs every feature of one with the nearest of its kind in the other — lining
the two up first, since the algorithms need not put the model's origin in one
place — and reports each pair that differs by more than 0.05 % of the size (the
polygonal projection's own error; `--agreement` to change it), each feature
only one of them has, and the short steps of any curve one of them drew as a
polygon it could not fit. It exits 1 when they disagree. Read what it reports:

- **They agree**: measure on either; the exact one prints rounder numbers.
- **A size agrees and a sweep does not**, by a few degrees: the two decide
  differently where a curve goes out of sight. That is not a dimension.
- **A size differs**: the exact projection has the curve itself, the polygonal
  one a polygon near it. Take the exact reading.
- **A feature only one has**: an artefact of the other — an edge the exact
  algorithm dropped, a polygon too short to fit. Measure that feature where both
  have it: in the view that looks along its axis, which is where a hole's
  diameter is measured anyway.

`measure.py compare` reads two *drawings* of one object. Two *solids* — a
part and the 3D file it reproduces, a redesign and the part it replaces — are
read against each other by `pc compare <reference> <current>`: their volumes,
masses and tolerances, and with `--surface-distance <mm>` how far the current
one's surface is from the reference's, point by point along the reference's
normals (`/pc:gen-part` §7 says how to read it). It exits 1 when they disagree
too: past the two tolerances added up, or past a `--max-volume-difference`,
`--max-displacement-difference` or `--max-mass-difference` given in percent.

The exact projection costs more and can fail on a large model (that is why it
is not the default). What makes a model large is how many edges it has, not
what kind of object it is: a sketch or a simple part is quick, but a detailed
part — an imported STEP with hundreds of faces, a mesh — can take minutes and
gigabytes as surely as an assembly can. Measure a large part a view at a time,
and an assembly a pair of components at a time (`/pc:gen-assembly` §6). Where
the exact projection is not to be had, measure on the polygonal one alone and
widen every tolerance by its error.

Both are had **without changing anything's declaration**: `--reproducible` and
`--no-reproducible` choose the algorithm for one run of `pc render` or `pc adhoc
render`, over whatever the file type says. Pass one of them on **every** render
you measure. Left off, the file type decides, and a package can make either one
its default — every example in PartCAD's own repository says `reproducible:
true` — so a "plain" render is not reliably the polygonal one.

### 5.3 A raster picture: measured in pixels, then calibrated

```sh
python3 <this skill's directory>/measure.py image photo.jpg --row 412 --column 230 --calibrate 1043=100
```

It finds the background (the commonest colour; `--background R,G,B` to say
it), and reports the box around everything else and, along each `--row` and
`--column`, every run of ink it crosses with its start, end and centre — the
centre weighted by intensity, so a line's position is known to a fraction of a
pixel. `--crop X0,Y0,X1,Y1` keeps it to one view of a sheet.

- **Find the row by eye, measure it by script.** Look at the picture to choose
  a row or column through the feature, then let the script say where the edges
  are. Scan two or three neighbouring rows: they agree if the line is clean.
- **Calibrate on a known length,** between two line *centres* (not the box,
  which includes the stroke width), as long as the picture allows and along the
  direction you are going to measure. `--calibrate <px>=<mm>` then reports
  millimetres.
- **State the uncertainty.** A clean drawing measures to about half a pixel at
  each end, so ±1 px over the length, divided by the scale; a photo of a part
  is worse at its edges. That uncertainty is the measured target's tolerance
  in §3.

### 5.4 The projection method

A distance measured in a picture is a length in the object only once the
projection is accounted for:

| Projection | What measures true | Correction |
| --- | --- | --- |
| **Orthographic** (one view, or a multi-view drawing) | lengths parallel to the plane of the view, at the drawing's scale | none; a length along the line of sight is not in this view — take it from another one |
| **Isometric** | lengths along the three isometric axes, all at one scale | calibrate on a known axis-parallel length. A *projection* (PartCAD's `iso`) shows them at ×0.8165 (√⅔), an isometric *drawing* at ×1; calibrating on the picture makes the two the same. A circle on a face is an ellipse: true diameter = major axis ÷ (1.2247 × the axis scale) — in PartCAD's `iso`, the major axis *is* the diameter — and the minor axis is 0.577 of the major. A line not along an axis is not true length: measure its axis components |
| **Dimetric / trimetric** | lengths along each axis, each at its own scale | calibrate each axis on a known length along it |
| **Oblique** (cavalier / cabinet) | the front face, true | the receding axis is ×1 (cavalier) or ×0.5 (cabinet) |
| **Perspective** (a photo, a perspective render) | only lengths in one plane facing the camera, near the known length used to calibrate them | everything else is an estimate: widen its tolerance, and ask for a drawing or a square-on photo if the dimension matters |

A **multi-view drawing** says where each view is by its projection symbol, and
the two conventions put the same views in opposite places:

- **third-angle** (ANSI, North America): the top view *above* the front, the
  right-side view to its *right*;
- **first-angle** (ISO, most of Europe and Asia): the top view *below* the
  front, the right-side view to its *left*.

Identify it from the symbol in the title block, or from the geometry — a
feature visible in one view must line up with it in the next — before mapping
any view to a `--view` name. A drawing read in the wrong convention is mirrored,
not obviously wrong.

## 6. Author the candidate

Choose a representation:

| Kind | Good for |
| --- | --- |
| `build123d` | parametric 2D sketches (recommended default) |
| `cadquery` | fluent 2D sketching |
| `basic` | one circle, square, rectangle or slot, with holes of the same |
| `dxf` | an outline that already is a DXF |
| `svg` | an outline that already is an SVG (see §4.2 for its scale) |

Write it so that iterating is changing one number:

- **One named constant per row of the table**, called what the table calls it,
  and every coordinate computed from them from the datum the table names:
  a hole "8 from the left edge" is at `-WIDTH / 2 + HOLE_INSET_X`, not at a
  number worked out by hand.
- **Radius or diameter, every time.** build123d's `Circle` and `Hole` and a
  `basic` sketch's `circle:` take a *radius*; a drawing's Ø is a diameter.
- **Centred or cornered.** build123d centres `Rectangle` and its siblings unless
  told otherwise (`align=`); a `basic` slot is placed by the centre of its first
  rounded end, and its `length` is over the ends.
- Python scripts import everything they use (including `math` and the library
  itself), expose the result with `show_object(<sketch>)`, and export nothing.

Register it — the script first, then:

```sh
pc --no-ansi add sketch --desc "<the description>" build123d <name>.py
```

(`basic` has no file: write its declaration into `partcad.yaml` by hand.) Then
write the table down:

```yaml
sketches:
  <name>:
    type: build123d
    path: <name>.py
    desc: <the description>
    requirements:
      features:                # the dimension table, one feature per dimension
        width: 100 mm overall, left edge to right edge
        hole-pattern: Four Ø5 holes, centres 8 mm in from each edge (pitch 84 × 44)
```

If you started the project with `pc init`, delete the empty null sections it
leaves.

## 7. Test render, and measure the candidate

```sh
D=/tmp/pc-sketch/<name>/1                                  # one directory per iteration
mkdir -p $D/polygonal $D/exact
pc --no-ansi render -t svg --no-reproducible -O $D/polygonal <name>
pc --no-ansi render -t svg --reproducible -O $D/exact <name>
python3 <this skill's directory>/measure.py compare $D/exact/<name>.svg $D/polygonal/<name>.svg
python3 <this skill's directory>/measure.py svg $D/exact/<name>.svg
pc --no-ansi info <name> 2>&1                              # BoundingBox: the kernel's extent
```

A name with a `/` in it is written into that subdirectory of `-O`
(`bracket/dims-front` → `$D/exact/bracket/dims-front.svg`). Resolve whatever
`compare` reports (§5.2) before taking any number from either.

Measure **the same dimensions, between the same features**, as the table says
the targets were measured — and the extent against `pc info` too. Then look at
the SVG as well: the numbers say whether each dimension is right, and only
looking says that every feature is there and nothing else is. When the targets
came from a picture, render a PNG of the candidate beside it and compare the
two by eye; measure the candidate in its SVG all the same — it is exact, and
the picture was the uncertain one.

## 8. Compare, and iterate with the error

Extend the table with what was measured:

| Dimension | Target | Measured | Error | Tolerance | |
| --- | --- | --- | --- | --- | --- |
| width | 100 | 100.000 | 0.000 | ±0.01 | ok |
| hole Ø | 5 | 10.000 | +5.000 | ±0.01 | **out** |
| hole inset x | 8 | 5.500 | −2.500 | ±0.01 | **out** |

Every error within its tolerance: done. Otherwise the error says what to change,
and its pattern says where to look:

- **Every error in proportion** (each one the same ratio of its target): a
  scale — inches, a radius taken for a diameter (×2), an isometric factor
  (0.8165, 1.2247), an SVG's page scale, a wrong calibration.
- **The same offset on every position along one axis:** a datum — centred
  instead of cornered, measured from the other edge, a slot placed by its
  middle instead of its first end.
- **One dimension out:** its constant. A dimension that moves one-for-one with
  its constant is corrected by the error itself (new = old − error); one that
  does not (a diameter set by a radius moves 2:1, a pitch set by an inset moves
  −2:1) is corrected by the error divided by that ratio.

Correct, re-render into the next iteration's directory, and measure again —
keeping each iteration's table, so the history says what each change did. No
fixed number of rounds; but **if one dimension is still out after two
corrections, stop nudging it**: the model of how it depends on the constants is
wrong. Work it out again, or measure it some other way.

If the targets cannot all be met — they disagree with each other, or one of them
was measured wrong — say so with the numbers rather than splitting the
difference. Measure the reference again before blaming it, and when it was the
reference, correct the table and say that you did.

## 9. Temporary sketches: the dimension study

`/pc:gen-part` and `/pc:gen-assembly` run §3–§8 before they model, on sketches
that exist to settle numbers:

- **One per view that carries dimensions** — usually `front`, `top` and
  `right` for a part; the footprint (`top`) and an elevation (`front`) for an
  assembly's placements. Each is drawn in that view's picture coordinates
  (§4, *The views*), so its numbers are the ones the part's or assembly's own
  projection in that view must measure.
- **Named after what they are for:** `<object>/dims-<view>` (`bracket/dims-front`,
  `gearbox/layout-top`). A file at that path declares the sketch under that
  name — `pc add sketch build123d bracket/dims-front.py`, run in the package's
  directory, adds `bracket/dims-front`.
- **What a study produces is the validated table**, which the part script or
  the ASSY is written from, and against which the result is measured again.

When the work is finished, a temporary sketch that nothing is built from is
removed — its declaration and its file — unless the user wants it kept. One
that a part *is* built from (`type: extrude`, `type: sweep`) is no longer
temporary: keep it, and give it a `desc:` that says what it is. The study
script of §4.3 goes with `/tmp/pc-sketch`.

## 10. Finalize

Report the sketch and the final dimension table — target, measured, error and tolerance for
every dimension, and the uncertainty of every measured target — what the two
projections disagreed on and how it was resolved, how many iterations it took
and what each correction was, every assumption, and how to view it:
`pc ide view -s <name>`.
