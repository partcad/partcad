# Additive manufacturing - the design, the printer, its route and the print: design

This is the design record for how PartCAD describes a printed part: the design it is a print of, the printer that
prints it, the route the printer follows and the print itself: the part as it comes off the bed, with the emptiness
inside it, which is what it weighs and what a section through it shows - and, by the same means, the part a router
leaves of its stock and a mold gives back of its cavity. How to *use* what is
built is the user documentation's job (`docs/source/config_making.rst`, "Additive"); this file is for whoever changes
it.

Status words, as in [`cmf.md`](cmf.md): **built** is on this branch; **decided** is agreed and not built yet;
**proposed** is not agreed; **open** is not decided at all. *Unverified* marks a claim the surveys could not confirm
from a primary source.

## Contents

1. [Goal](#1-goal)
2. [What PartCAD did before](#2-what-partcad-did-before)
3. [The declaration](#3-the-declaration)
4. [The design, the picture and the print](#4-the-design-the-picture-and-the-print)
5. [A printer is a `pc cam` machine](#5-a-printer-is-a-pc-cam-machine)
6. [CMF and the manufacturing section](#6-cmf-and-the-manufacturing-section)
7. [Survey: the print from its route](#7-survey-the-print-from-its-route)
8. [Prototype: a route from `pc cam`'s parts, and what it deposits](#8-prototype-a-route-from-pc-cams-parts-and-what-it-deposits)
9. [Proposal](#9-proposal)
10. [Specifications](#10-specifications)
11. [Roadmap](#11-roadmap)
12. [Appendix: the first survey - the print from its settings alone](#12-appendix-the-first-survey---the-print-from-its-settings-alone)

## 1. Goal

A 3D-printed part is not the solid its designer drew. A slicer - a router program writer for a machine that adds
material - turns that solid into a route: a few rings around every outline, a few solid layers under every top and over
every bottom, and the inside crossed by lines at a density, 15%, 20%, 40%. What comes off the bed is the material that
route deposits, and it is mostly empty inside.

So in PartCAD:

- A printed part names its **design** (`manufacturing: source:`). The design is what is printed, what the tolerance is
  measured against and what a print service is sent - and what a **picture** of the part draws, unless the part names a
  `visual:` of its own (the part-level key every part has).
- The **printer** is a machine (`fff:`), declared and read exactly as `cnc:`, `laser:`, `drill:` and `cut:` are, with the
  router's keys where they mean the same thing.
- The **route** a printer follows is written by `pc cam`, out of the pieces `//builtin/cam` already has.
- The **print** - the part itself, `get_wrapped`, what is weighed and sectioned and exported as what it is - is what that
  route deposits. It is derived, never modelled by hand.
- What it is **made of** stays the part's CMF. The manufacturing section says how, never of what.

## 2. What PartCAD did before

| Where | What happened |
| --- | --- |
| `manufacturing: method: additive` | A label. The part was its own design; nothing else could be said. |
| `_read_machines` | Refused a cut's keys on a printed part ("describes no cut"), and anticipated "a printer's keys under a printer's subsection". Everything else was ignored. |
| `manufacturability-additive` | The part is a closed solid. `# TODO(clairbee): Utilize the data provided in the config`. |
| `procurement` | A printed part is made "from nothing it names": nothing procured. |
| `manufacturing_instructions` | "Made additively (3D printed)." |
| Weight (`physics`) | The solid's volume at the material's density: a 20%-infill PLA part weighed as solid PLA, two to three times its real weight ([section 8](#8-prototype-a-route-from-pc-cams-parts-and-what-it-deposits)). |
| `pc cam` | Routes for a router, a laser and a drill. Nothing for a printer. |
| Cart (`get_mcft`) | The part's own `parameters:` defaults as raw strings: a reference (an alias, an enrich) reported no material at all. |

## 3. The declaration

**Built.**

```yaml
parts:
  bracket:                    # the design
    type: build123d
    path: bracket.py
    manufacturable: false     # a design is not made on its own: its prints are
    parameters:
      material: {type: string, default: //pub/std/manufacturing/material/plastic:petg}
      tolerance: {type: float, default: 0.2}

  bracket-printed:            # no type: it is the design, printed
    visual: bracket-render    # optional: the part-level key; the design is drawn otherwise
    manufacturing:
      method: additive
      source: bracket         # the design
      fff:                    # the printer: a machine
        toolAxis: -Z          # the nozzle comes down along -Z: printed as modelled
        layerHeight: 0.2 mm
        walls: 3
        topLayers: 5
        bottomLayers: 4
        infill: 20%
        infillPattern: grid
        feed: 3000
```

| Key | Meaning |
| --- | --- |
| `source` | Optional. The design. A part naming none is its own design - what every `additive` part written before this meant. Never stock: `procurement.stock_name` is None for a printed part whatever it names. |
| `visual` (the part's own, not the manufacturing section's) | What a picture draws. For a printed part that names a design and no `visual:`, the design (`visual.design`). |
| `fff` | Optional. A filament printer (fused filament fabrication; ISO/ASTM 52900 material extrusion; "FDM" is a trademark), a machine read by `MachineConfig` ([section 5](#5-a-printer-is-a-pc-cam-machine)). A part naming none is printed on an undeclared one with the usual settings, as a cut part naming no machine is cut on CNC: `pc cam` over a package passes it over, and `-m fff` or making the part routes it. |

**No `type:`.** A part that names a design needs no geometry of its own: it is what the printer makes of it
([section 9.3](#93-the-print-is-the-part), **built**). `part_config_manufacturing.implied_type` gives it `type:
manufactured`, with `implied_type` holding the format its file is kept in - `brep` where it says nothing, `step`, `brep`
or `sdf` where `type:` says one of those. Its factory reads that file where `pc cam --materialize` has written it, and
makes the print on demand where it has not. It is lent the design's material, colour, finish and tolerance where it
states none (`part_factory_manufactured._lend_cmf`). A part that writes any other `type:` - an as-printed model imported
from a slicer or a scan - is that geometry, names its design in `source`, and is compared with the print by the
`materialize` check. The same holds for a molding naming its cavity and a cut part naming its stock and its
`instructions:`.

**Errors are recorded, not raised**, as for every machine: an `fff:` that cannot be read is `machine_error`, which
`manufacturability-additive` and the build plan report and `pc cam` visits ("broken, and therefore visited"). A printer's
setting written directly under `manufacturing:` is reported as "a setting of the printer; write it under 'fff:'"; a
cut's key on a printed part is refused as it always was; `manufacturing: visual:` is refused with a sentence pointing at
the part-level key.

**Where it is read.**

| Reader | What it does with it |
| --- | --- |
| `visual.visual_of_async` | Draws a printed part as its design where it names no `visual:`. A reference inherits, so a type-less printed part (which is the design already) substitutes nothing. |
| `manufacturability-additive` | The declaration can be read; the **design** (or the part itself) exists and is a closed solid. Keys on the design's key and each printer's `MachineConfig.key()`. |
| `procurement` | A design is not stock: nothing is procured for it. |
| `manufacturing_instructions` | "Printed from the design `bracket`." and "Print it on a filament printer (FFF); layer height 0.2 mm, 3 walls, ..., infill 20% gyroid, feed 3000 mm/min." - only what was stated, and the axis where it is not `-Z`. |
| `cam` | `pc cam` passes a printed part over and `pc cam -m fff` refuses with `unrouted_reason` until a printer's route is written ([section 9.1](#91-pc-cam-writes-a-printers-route)). |
| Cart | `manufacturing: {method, design, machines}` beside `material`/`color`/`finish` (`PartConfigManufacturing.print_data`), settings as stated. |
| Manufacturer provider `load()` | Sends the **design's** STEP, not the part's own geometry. |

## 4. The design, the picture and the print

| | What it is | Where it comes from | Who reads it |
| --- | --- | --- | --- |
| **design** | The solid the designer had in mind | `source:`, else the part | the additive check, the tolerance, a print service, the route |
| **picture** | What the part looks like | the part's `visual:`, else the design (`partcad.visual`) | the 3D view, `render:` file types with `visuals: true` |
| **print** | The design as the printer deposits it, empty inside | derived: design + printer, through the route | `get_wrapped`: weight, centre of mass, inertia, sections, exports, simulation, every check |

The part-level `visual:` (#939) settles the first question this record used to answer for itself: a part *is* one
thing - the tree every test, analysis, route, export and simulation reads - and a picture may draw another. For a print
that is exactly the split wanted: the part is the print, with its voids, and a picture draws the design, which is what
it looks like from outside. Nothing is substituted anywhere but in a picture, and a picture is keyed on the visual it
drew, so neither costs the other a rebuild.

## 5. A printer is a `pc cam` machine

**Built:** the declaration. **Proposed:** the route ([section 9.1](#91-pc-cam-writes-a-printers-route)).

A printer follows a route, layer by layer, exactly as a router does; along it, it lays a bead down where a router cuts
one away. So `fff:` is a fifth machine - `MACHINE_FFF`, the additive method's (`PRINTERS`) - read by `MachineConfig`
and `_read_machine` like the four subtractive ones, and every key it takes is either a router's key that means the same
thing or one with no counterpart in a cut:

| `fff:` key | `pc cam` counterpart | Kind |
| --- | --- | --- |
| `toolAxis` / `along` | the same key: the axis the tool comes down along. For a printer that is the **build orientation**, which decides where the layer lines run and what overhangs, and `pc cam` orients a print by it the way it orients a cut (`cam_gcode._orient`) | own |
| `nozzle`, `filament` | a laser's `kerf`: what the machine *is*, not what it is told | own |
| `feed` | `feed`, the same key and the same parser | job |
| `layerHeight` | `depth_per_pass`, built up rather than cut down | job |
| `lineWidth` | the width the path leaves behind: a router's `diameter`, a laser's `kerf` | job |
| `walls` | a `profile`, repeated inward around every outline and every hole, a line apart | job |
| `infill` | a `pocket` whose `stepover` is one line over the infill: 20% is a line every five | job |
| `infillPattern` | `operation`: `concentric` *is* a pocket's rings; `rectilinear`, `grid`, `gyroid`... are lines | job |
| `topLayers`, `bottomLayers` | nothing: a cut never asks what is above it | job |

Speeds other than the feed, temperatures and cooling decide whether a print succeeds rather than what shape it is, and
are the printer's. `implementation:` - who writes the route - is taken on `fff:` as on a router: `//builtin/cam:gcode`
unless said, and the key a slicer package is named by.

**What `//builtin/cam` already has, and what a printer's route still needs.** `cam_gcode.py` is a 2.5D router program
writer, and a slicer is a 2.5D program writer run once per layer. Of what a route is made of:

| Piece | In `//builtin/cam` | For a printer |
| --- | --- | --- |
| The section at a height | `_faces_at(obj, z)` (`b3d.section`) | the same, once per layer |
| The outline as a polyline within a tolerance | `_wire_points` (`GCPnts_QuasiUniformDeflection`) | the same |
| Concentric offsets until nothing is left | `_pocket_paths` (`Wire.offset_2d`, `Kind.ARC`) | perimeters, and concentric infill - **but** a pocket refuses an island, and a printer's every hole is one |
| The program, byte-stable, units and precision | `Program` | the same, plus the `E` word |
| Orientation by the tool axis | `_orient` | the build orientation |
| A drawing of the route from above | `cam_preview.svg` | the same, per layer |
| Lines clipped to a region | - | rectilinear and grid infill, solid skins |
| What is above and below a region | - | top and bottom skins: a layer's region less the intersection of the `n` layers above (below) |
| Extrusion per move | - | `E = L * A / (pi (d_f / 2)^2)`, the stadium area `A = h (w - h (1 - pi / 4))` |

The missing pieces are 2D polygon offsets and booleans that survive islands. OCCT's own fail exactly where a printer
lives: `BRepOffsetAPI_MakeOffset` on a 20 x 20 mm section with a 4 mm hole returns the right regions at 1, 4 and 5 mm
and **drops the hole at 3 mm**, where the hole's offset touches the outline's - and a slicer reaches that tangency on
every part with a hole near a wall; build123d's `offset` of a face raises there (`'Face' object has no attribute
'unwrap'`). That is why `_pocket_paths` refuses islands. Slicers use Clipper for this
([Slic3r](https://github.com/slic3r/Slic3r), PrusaSlicer, Cura); its Python binding `pyclipper` is MIT, wheels on every
platform, and is what the prototype below does it with ([section 8](#8-prototype-a-route-from-pc-cams-parts-and-what-it-deposits)).

## 6. CMF and the manufacturing section

**Decided:** material is not a manufacturing property. **Built:** the two fixes below. **Proposed:** the rest.

What CMF settled (see [`cmf.md`](cmf.md)) is that an item's material, colour and finish are stated by its definition and
carried with its geometry. The question was whether the manufacturing section should carry a material too - a filament
for a print, a sheet for a laser. It should not:

- **One place.** The filament *is* the part's `material`: its density is what the print is weighed at, its colour claim
  what it is drawn in, its `manufacturable:` what the `cmf` check counts, its `ids` what a supplier matches. A
  `manufacturing: material:` would be a second answer to the same question, and the two can disagree.
- **Slicers draw the same line.** PrusaSlicer's Print / Filament / Printer, Orca's process / filament / machine, Cura's
  quality profile / material XML / machine definition: density, diameter, colour, flow and shrinkage are the material's;
  layers, walls and infill are the process' ([section 12.6](#126-material-and-process-in-slicers-and-services)). The one
  filament property a printer needs to write its route - the filament's *diameter*, which turns length of route into
  length of filament - is the machine's (`filament:`), because it is what the printer is fed, as a laser's kerf is what
  it burns.
- **What a process constrains is a capability.** That FFF prints thermoplastics and not aluminium is what a provider's
  `caps` say, not what a part declares.
- **An effective density is not a material.** "PLA at 20%" declared as a material of 0.4 g/cm3 would weigh the part
  right and be wrong everywhere else - the CMF check, the exports, the cart, the colour. The print's weight comes from its
  geometry at the material's density ([section 9.2](#92-what-the-print-weighs)), never from a declared density.

Where material still lives outside CMF, and what is done about each:

| Where | Problem | Done |
| --- | --- | --- |
| `ShapeConfiguration.get_mcft` (the cart) | Read only the part's own `parameters:`; a reference - and so every type-less printed part - was ordered as made of nothing. | **Built:** falls back to what the reference resolves to (not where a store's SKU is bought through an alias, which reads only what the alias declares). |
| Manufacturer `load()` | Would have sent the part's own geometry - the print, or an as-printed mesh. | **Built:** sends the design. |
| Cart `material`/`color`/`finish` | Raw strings from `parameters:` defaults (`"red"`, a synthesised `"none"` finish), matched by providers as names (`TODO: resolve ... as a color object`). | **Proposed**, staged as `contributing.rst` requires: add the canonical CMF references and their `ids` beside them (`cmf.own_info`), migrate providers to match by `ids`, then retire the strings. Changing them in place breaks every provider's `caps` matching at once. |
| `properties: material:` (physics, the BOM's `material` column, URDF) | One material per part, promoted from the parameter; the CMF section's material per *solid* - what a STEP file states - is not what the part is weighed at, and a two-material part is weighed at one density. | **Proposed:** physics weighs each solid by the material its CMF set claims (the summary already counts solids per set); `properties: material:` becomes derived from CMF and is no longer read where the section is at hand. |
| Hand-written `properties: material:`/`color:` (`examples/produce_part_cadquery_logo`) | `properties:` is "never written by hand in a package" (`PartFactory.record_object_type_properties`). | **Proposed:** move to the CMF parameters with the next re-render of that example; its images are checked in. |
| `object_type_parameter` | Still reads only the reference's own declaration (said in its docstring). | **Open:** whether every object-type parameter should resolve through a reference, as `get_mcft` now does. |

## 7. Survey: the print from its route

A second survey, November 2026, of how the deposited volume is worked out from a route - a list of moves, each with a
width `w`, a height `h` and a feed of filament - and which of those ways fits PartCAD. Measurements quoted here as
*measured* were made for this record in a scratch environment beside the prototype of
[section 8](#8-prototype-a-route-from-pc-cams-parts-and-what-it-deposits).

### 7.1 The bead

A bead's cross-section follows from the filament fed by volume conservation: `A = k E pi d_f^2 / (4 L)` for a move of
length `L` that feeds `E` of filament of diameter `d_f`, `k` the extrusion multiplier. Its shape is the slicer's model of
it, and the right model is the one of the slicer whose `E` is being read:

| Model | Area | Used by |
| --- | --- | --- |
| Stadium: a rectangle with semicircular sides of radius `h/2` | `h (w - h (1 - pi/4))`; adjacent lines `s = w - h (1 - pi/4)` apart | Slic3r, PrusaSlicer, Orca ([`Flow.cpp`](https://github.com/prusa3d/PrusaSlicer/blob/master/src/libslic3r/Flow.cpp), [flow math](https://manual.slic3r.org/advanced/flow-math)) |
| Rectangle | `w h` | CuraEngine ([`GCodePathConfig.cpp`](https://github.com/Ultimaker/CuraEngine/blob/main/src/GCodePathConfig.cpp)) |
| Circle | `pi d^2 / 4` | bridges, everywhere |
| Ellipse | `pi w h / 4` | the literature; to conserve the stadium's area it is `4 A / (pi h)` wide |

Its signed distance, at `p = (x, y, z)`, from a move `a -> b` in the layer centred at `z_c` - exact outside, a bound
inside - is the stadium's, `f = sqrt(max(d2 - (w - h)/2, 0)^2 + (z - z_c)^2) - h/2`, `d2` the plane distance from `(x,
y)` to the segment; a rounded rectangle of corner radius `r` (0 for Cura, `h/2` for the stadium) is `|max(u, 0)| +
min(max(u_x, u_z), 0) - r` with `u = (d2 - (w/2 - r), |z - z_c| - (h/2 - r))` ([Quilez's
primitives](https://iquilezles.org/articles/distfunctions/), via [a port](https://mysterypancake.github.io/Houdini-Fun/Houdini_SDFs.html)).
Because every bead of a layer shares `z_c`, **a layer's union is decided by one 2D field**, `D(x, y)`, the distance to
the nearest move: the deposit stands `t(D)` tall over each point (`h` up to `(w - h)/2`, the stadium's chord to `w/2`,
nothing beyond), and the layer's 3D SDF is `f(D, z)`. That is the observation every practical method below rests on.

**The voids are real.** Adjacent stadium beads `s` apart overlap by a lens of about `0.09 h^2` - 4.45% of `A` - and
leave a cusp-shaped void above and below the lens. Micro-CT of PLA at 100% infill, 0.2 mm layers, 0.48 mm lines,
measures 4.05-5.84% porosity, most pores under 0.2 mm, the larger ones between crossing layers and where infill meets
the perimeters ([Wang et al. 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6680582/)); industrial ABS has 0.6-0.7% of
elongated voids ([Hernandez-Contreras 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7504175/)). The geometric union of
nominal stadium beads comes out 2.0% (20% infill) to 3.7% (100%) below `sum A L` (*measured*): the order of the cusp
porosity. **The part still weighs `rho sum A L`** - what the extruder fed, squeezed into the cusps - which is why the
route, not the union, is what a weight is taken from ([section 9.2](#92-what-the-print-weighs)). PrusaSlicer also
overlaps infill with the perimeters by 25% of a line by default (`infill_overlap`,
[`ConfigDefsFDM.cpp`](https://github.com/prusa3d/PrusaSlicer/blob/master/src/slic3r-domain/src/Slic3r/Domain/ConfigDefsFDM.cpp)),
which the prototype does not, and which closes the gap visible in its layer below.

### 7.2 Four ways to the deposited volume

**(a) An analytic SDF union** of every move. fogleman/sdf - the `sdf` part type's library - evaluates every operand of a
`union` at every point, with no culling ([`dn.py`](https://github.com/fogleman/sdf/blob/main/sdf/dn.py)); its `sparse`
mode skips a batch only after an O(N) distance test ([`core.py`](https://github.com/fogleman/sdf/blob/main/sdf/core.py)).
*Measured* with `sdf-fork`: about 55 ns per point per primitive, linear from 10 to 1000 capsules - about ten hours for a
20 mm cube at 0.05 mm. With a spatial index (layer buckets, a 2D cell grid) it becomes (b).

**(b) A sampled distance field**: each move's exact distance splatted into the grid cells of its bounding box, then
meshed. The voxel deposition models are of this family: VOLCO moves material into the nearest free voxels (0.1 mm by
default, GPL-3.0; [repository](https://github.com/FullControlXYZ/volco), [paper](https://eprints.nottingham.ac.uk/51116/));
its predecessor of GPAMS assigns each voxel a volume fraction from a rectangular bead and reports the over-filled voxels
where beads overlap ([Acta Polytechnica 2020](https://ojs.cvut.cz/ojs/index.php/APP/article/view/6407)); Rivet et al. build
a voxel mesh from G-code by a 2.5D shortest-path method
([UPCommons](https://upcommons.upc.edu/entities/publication/7e5210b4-8dd7-4e1a-aec0-7ebf9f5bb869)); an adaptive octree
from G-code ([arXiv 2305.07120](https://arxiv.org/abs/2305.07120)); Sandia's Sculpt overlay grid, a Benchy at 0.25 and 0.1
mm being 1.9 M and 18 M elements ([arXiv 2509.12436](https://arxiv.org/abs/2509.12436)). Sparse grids: OpenVDB is
Apache-2.0 since 12.0 ([Phoronix](https://phoronix.com/news/ASF-OpenVDB-12.0)) but not on PyPI - the `pyopenvdb` there is
an unofficial wrapper - only on conda-forge ([recipe](https://github.com/conda-forge/openvdb-feedstock/blob/main/recipe/recipe.yaml)).

**(c) A 2.5D footprint stack**: per layer, every move stroked by half a width with round ends, unioned, extruded by `h`.
build123d 0.11's `offset_2d(..., side=Side.BOTH, closed=True)` strokes an open wire through `BRepOffsetAPI_MakeOffset`
([`one_d.py`](https://github.com/gumyr/build123d/blob/v0.11.0/src/build123d/topology/one_d.py)); Clipper strokes and
unions a whole layer in one call. DECODE, a sweep-based model, gave better volumes than VOLCO and handled larger parts,
while VOLCO predicted mechanics better ([abstract](https://accedacris.ulpgc.es/jspui/handle/10553/121987)).

**(d) A solid per move, fused**: FreeCAD sweeps from G-code took 69-88 s for a 10 mm cube's 443 sweeps and about 1550 s
for a gyroid-filled dog-bone, growing as a power of the count ([Bacciaglia et
al.](https://cris.unibo.it/bitstream/11585/896484/8/Manuscript_for_IRIS.pdf)); G-Code2STEP (2026) is the same idea
([record](https://pure.unileoben.ac.at/en/publications/g-code2step-converter-for-accurate-representation-of-geometries-c/)).
Not viable at 10^4-10^6 moves. *Measured*: fusing ten layers of the footprint stack in OCCT took 7.8 s, so the stack is
kept as a compound and never fused.

### 7.3 Resolution

*Measured* on one 20 x 20 mm layer against a 3 micrometre reference:

| | 0.1 mm | 0.05 mm | 0.025 mm | 0.0125 mm |
| --- | --- | --- | --- | --- |
| SDF + marching cubes, 20% infill: volume error | -5.7% | -1.5% | -0.33% | -0.09% |
| SDF + marching cubes, 100% infill | -1.18% | -0.19% | -0.04% | -0.01% |
| Triangles per sparse layer | 70 k | 0.3 M | 1.2 M | 4.8 M |
| 2D exact distance and chord integral | - | 0.04%, 3 ms | - | - |

Marching cubes errs low, and manifold3d's marching tetrahedra the same way (-1.2% at 0.05 mm); counting occupied voxels
errs either way by up to 4.7%. About 1% needs a cell of `h/5` to `h/4`, `h/8` to be safe. A rasterised centre line put
through `scipy.ndimage.distance_transform_edt` is 0.1-1.2% off; splatting the exact segment distance is as cheap.

### 7.4 Interchange

[3MF's extensions](https://3mf.io/spec/):

- **Slice** (1.0.2, published): a stack of 2D polygons per layer, with a low-resolution mesh beside it
  ([spec](https://github.com/3MFConsortium/spec_slice)) - exactly approach (c), and the compact way to write a print.
- **Toolpath** (1.0.0, listed as published September 2026 though its own header still says release candidate): profiles
  with `beadwidth` and `beadheight` ([spec](https://github.com/3MFConsortium/spec_toolpath)) - the route itself, in a
  container other tools read. Reader support is *unverified*; lib3mf 2.5.0's notes do not mention it.
- **Beam Lattice** (1.2.0, published): frustums with round sections and sphere or flat caps
  ([spec](https://github.com/3MFConsortium/spec_beamlattice)). Capsules only, so a bead wider than it is tall is not one.
- **Volumetric and Implicit** (1.0, published November 2025): a level set driven by a sampled SDF or an implicit node
  graph, with a beam lattice distance node ([spec](https://github.com/3MFConsortium/spec_volumetric)). No consumer of a
  print written this way was found.

### 7.5 Tooling and licences

| Tool | Licence | Wheels | For |
| --- | --- | --- | --- |
| [pyclipper](https://pypi.org/project/pyclipper/) 1.4 (Clipper 6.4.2) | MIT (Boost) | all three platforms | offsets and booleans of polygons, open paths clipped (`OpenPathsFromPolyTree`), strokes (`ET_OPENROUND`) |
| [manifold3d](https://pypi.org/project/manifold3d/) 3.5 | Apache-2.0 | all three, aarch64 too | `CrossSection.extrude`, `batch_boolean`; its `CrossSection.offset` takes closed polygons only; `level_set` calls Python once per grid point (~0.8 us before the function runs) ([bindings](https://github.com/elalish/manifold/blob/master/bindings/python/manifold3d.cpp)) |
| [scikit-image](https://pypi.org/project/scikit-image/) 0.26 | BSD | all three | marching cubes |
| [sdf-fork](https://pypi.org/project/sdf-fork/) 0.1.1 | MIT | sdist only (2021) | the `sdf` part type |
| [libfive](https://github.com/libfive/libfive) | MPL-2.0 (Studio GPL) | third-party, x86_64 only | - |
| OpenVDB | Apache-2.0 | conda-forge only | sparse grids |
| [trimesh](https://pypi.org/project/trimesh/), [pyvista](https://pypi.org/project/pyvista/) | MIT | pure Python | meshes |
| [lib3mf](https://pypi.org/project/lib3mf/) 2.5 | BSD | x86_64, Windows, macOS | 3MF Slice |

Two notes on PartCAD's own code. `wrapper_sdf.sdf_triangles_to_topods` builds unwelded triangles in a Python loop per
vertex, which is impractical past about a million triangles - one more reason a whole print does not go through the
`sdf` part type. And what a route needs beyond `pc cam`'s pieces - hatch clipping, skins (a layer's region less the
intersection of the outlines `n` layers above or below, as CuraEngine's
[`skin.cpp`](https://github.com/Ultimaker/CuraEngine/blob/main/src/skin.cpp) does) - is polygon algebra Clipper does
robustly and fast; variable-width walls (Arachne, [Kuipers et al. 2020](https://arxiv.org/abs/2004.13497), the default
in PrusaSlicer since 2.5) need a medial axis neither OCCT nor Clipper has, and would also break the one-field-per-layer
shortcut of 7.1.

## 8. Prototype: a route from `pc cam`'s parts, and what it deposits

To find out what is practical rather than what is published, a route writer and three deposit models were built over
`//builtin/cam`'s own code, run in PartCAD's sandbox environment (build123d 0.11.1, OCP 7.9) with `pyclipper`,
`sdf-fork` (the library the `sdf` part type meshes with) and its scikit-image. Not part of this branch: the code is a
scratch prototype, and the numbers are what the proposal rests on.

**The route.** Per layer at `z_i = z_min + (i + 1/2) h`: the section by `cam_gcode._faces_at`, its wires as polylines by
`cam_gcode._wire_points`; perimeters as Clipper offsets of the whole section (islands and all) at `w/2 + k s`, `s = w -
h (1 - pi/4)` being Slic3r's line spacing for a stadium bead; the region left, less the intersection of the 4 sections
above (below), is solid skin, filled with lines `s` apart; the rest is sparse, filled with lines `s / infill` apart,
alternating +-45 degrees; and the program through `cam_gcode.Program` with a relative `E` per move. 0.2 mm layers, 0.45
mm lines, 2 walls, 4 + 4 skins, 20% rectilinear infill, 1.75 mm filament.

**The deposit**, three ways:

- **(A) footprint stack** - per layer, the union of every path stroked to its width (Clipper `ET_CLOSEDLINE`/
  `ET_OPENROUND`), as OCCT faces extruded by `h`: a B-rep, rectangular beads. Stroked at the line *spacing* instead of the
  width, each bead has the stadium's area.
- **(B) layered distance field** - per layer, the XY distance `D` from every point to the nearest path, and the stadium
  bead's profile over it: the deposit stands `t(D) = 2 sqrt((h/2)^2 - max(D - (w - h)/2, 0)^2)` tall, centred on `z_i`.
  Volume and centroid are sums over the grid. The same volume needs no grid at all: `V = h A(r0) + sum t(r) dA(r)` over
  `r` from `r0 = (w - h)/2` to `w/2`, `A(r)` being the area of the route stroked to half-width `r` - a dozen Clipper
  offsets per layer.
- **(C) SDF** - (B) lifted to an SDF3, `f(p) = min over the layers near z of sqrt(max(D_i(x, y) - (w - h)/2, 0)^2 + (z -
  z_i)^2) - h/2` with `D_i` bilinear on the grid, and marched by `sdf`'s own `generate` - what the `sdf` part type does
  with a script's SDF.

**Results** (PLA, 1.24 g/cm3):

| Design | Solid | From the route's own `E` | (B) field, stadium beads | (A) stack, stroke `w` | (A) stack, stroke `s` |
| --- | --- | --- | --- | --- | --- |
| 20 mm cube | 8000 mm3, 9.92 g | 2941 mm3 | **2931 mm3, 3.63 g** | 3175 (+8.3%) | 2978 (+1.8%) |
| 40 x 30 x 6 plate, two 8 mm holes | 6597 mm3, 8.18 g | 3164 | **3131, 3.88 g** | 3355 (+7.1%) | 3212 (+2.7%) |
| cone, 24 to 8 mm, 16 mm tall | 3485 mm3, 4.32 g | 1413 | **1404, 1.74 g** | 1518 (+8.1%) | 1432 (+1.9%) |
| 80 x 60 x 30 block, 4 holes, pocket | 119968 mm3, 148.8 g | 37560 | **37397, 46.4 g** | - | - |

- The field is converged at a 0.05 mm grid (0.16% from 0.025 mm), and the offset integral agrees with it to 0.01%.
- The route's `E` - what a slicer weighs a print by - is within 0.3-1.1% of the field: it counts the overlap of adjacent
  beads twice, which a printer squeezes sideways rather than stacks. Summed per segment, `(L A, L A midpoint)` gives the
  volume and the centroid with no geometry at all, in 15 ms for the cube.
- The first survey's analytic shell-and-core formula ([section 12.1](#121-from-the-settings-without-a-route)) puts the cube
  at 3124 mm3, 6.6% high: the route has a gap between the walls and the infill, bead overlaps, line ends - the details a
  formula over the settings cannot see, and the reason the route is the thing to derive the print from.
- The centre of mass moves where it should: the cube's stays at 10.000 mm; the cone's drops from 5.54 to 5.21 mm, its
  skin being heavier low down.

**Cost** (one core):

| | Route | (B) field, Python | (B) offsets | (A) B-rep stack | (C) SDF mesh |
| --- | --- | --- | --- | --- | --- |
| 10 mm cube (6.2 m of route) | - | - | - | 0.2 s; 7188 faces, 4.1 MB BREP, 32k triangles | 0.1 mm: 3.2 s, 0.58 M triangles, +2.3%; 0.05 mm: 14.8 s, 3.9 M triangles, 2.9 GB, exact |
| 20 mm cube (36 m) | 0.75 s | 2.7 s | 0.3 s | 0.4 s build; 22k faces, 12.9 MB, 98k triangles | 0.05 mm: killed at 15 GB |
| 80 x 60 x 30 block (461 m) | 2.9 s | 77 s | 15 s | - | - |

An SDF mesh of a print is accurate - at 0.05 mm it encloses exactly the field's volume - and hopeless as a part's
geometry: every bead has a surface of its own, and that is about 0.6 million triangles and 0.45 GB per metre of route at
0.05 mm. A 20 mm cube has 36 m of route. The footprint stack is two orders of magnitude lighter, a real B-rep, and within
2-3% of the bead model when stroked at the line spacing.

What the field shows, a layer of the plate and a vertical section through the cube:

![A layer of the plate: its route, and how high the deposit stands over each point](images/additive-layer.png)

![A vertical section through the 20 mm cube: two walls, 4 + 4 skins, 20% infill, and the voids between beads](images/additive-section.png)

The layer shows one simplification of the prototype's route: its infill stops at the centre line of the next ring, so
there is an empty band between the walls and the infill that a slicer closes by overlapping the two (PrusaSlicer's
`infill_overlap`, 25% of a line, [section 7.1](#71-the-bead)). The section shows what no formula over the settings
shows: the cusp voids between beads, in the walls and the skins, of the size micro-CT finds.

## 9. Proposal

In the order it is built; each step is useful on its own and is the next one's test. Each says how far it got.

### 9.1 `pc cam` writes a printer's route

**Built.** `//builtin/cam`'s `gcode` file type has a printer: `MACHINES["fff"]` in `cam_gcode.py`, the route of
[section 8](#8-prototype-a-route-from-pc-cams-parts-and-what-it-deposits) in `cam_fff.py`, with `E` in relative
extrusion, and `MACHINE_FFF` in `ROUTED_MACHINES`. `pc cam :bracket-printed` writes `bracket-printed.nc` (with the
machine in the name only where the part names several); the `cam` check asks that the route can be written, as it asks
of a laser. The instruction book's layer drawings (`cam_preview`) are not built.

- **Clipper** is added to `//builtin/cam`'s `pythonRequirements` (`pyclipper`, MIT): it runs in the sandbox, so nothing
  is added to the wheel or the bundles. The section and the polylines stay `pc cam`'s own.
- **What it is not.** It is a route PartCAD can reason about - every move known, nothing hidden - not a production
  slicer: no supports, no bridges, no seams, no variable-width (Arachne) walls, no travel optimisation. A shop that needs
  those names a slicer as the route's `implementation:` - a package of its own running an unmodified PrusaSlicer or
  CuraEngine in a container through `partcad_utils.containers` (AGPL, so never imported), translating `fff:` by the table
  in [section 12.5](#125-vocabulary), and handing back its G-code. Either way the print is derived from the route, so a
  slicer's route is weighed and drawn by the same code as PartCAD's own.
- **Infill patterns**: `concentric` (rings), `rectilinear`, `lines` and `grid` are built; `gyroid` as the level set of
  `sin x cos y + sin y cos z + sin z cos x` at each layer's `z`, traced as polylines, is not; anything else is refused by
  name.

### 9.2 What the print weighs

**Partly built.** The route's stats carry `volume` (the sum below), `solid_volume` (the sections stacked up) and
`filament_length`; the part's mass is still derived from the deposit geometry's volume, which is 1-4% under the route's.

**The route is the print's weight.** What a printer deposits is what its extruder feeds, `rho k sum A L` - the overlap
of adjacent beads is squeezed into the cusps beside them, not lost ([section 7.1](#71-the-bead)). Summed per move, the
same sum gives the centre of mass (`A L` at each move's midpoint and layer height) and the inertia (each move a slender
box), in milliseconds and with no geometry; it is also what every slicer reports as a print's weight.

The geometry's own volume is the deposit's - the union of the beads - and is 1-4% less, which is the print's cusp
porosity. That is the volume the print *displaces*, which a scene buoys it by, and is the one `physics` already keeps
apart from the mass (`volume`, `centerOfVolume`): a print reports both, from different sources, and each says which.

It reaches the reader that already exists: a part's mass, centre of mass and inertia are derived from its measurements
(`physics._derive`), and the print's measurements are the route's ([section 9.3](#93-the-print-is-the-part)). Cached, as
every derivation is, under the part's key - which for a print covers the design, the printer's settings and the route's
implementation.

### 9.3 The print is the part

**Built**, as the `manufactured` part type rather than a `print` one, because it covers every process whose product
follows from its instructions: a print's deposit (`cam_fff.deposit`), what a router, a laser or a drill leaves of its
stock (`cam_product.removal`, `drilled`), what a saw leaves (`sawn`), a mold's cavity shrunk (`molded`). The product is
asked of the same implementation as the route, with `materialize: true`, so the two cannot disagree; `pc cam
--materialize` writes it into the part's file, and the `materialize` check compares a part that has a file of its own
with it by recorded volume and bounding box, and a cut part or a molding (one solid each) by shape as well: what either
has that the other has not may be no deeper than the part's tolerance. The measurements below are the geometry's own,
not yet the route's.

The type-less printed part stopped being a reference to its design. `implied_type` gives it a part type of its own
whose geometry is its route's deposit:

- **Geometry** (`get_wrapped`): the footprint stack, stroked at the line spacing - a B-rep of planar prisms, one per
  region per layer, so every export, section, drawing and check takes it as it takes any solid. 13 MB of BREP for a 20 mm
  cube is heavy for a part nobody looks inside; the payload is a compound of prisms that is never fused, so the cost is
  linear in route length, and a part whose print is never asked for never builds one. A part too big for that (the
  survey extrapolates 10^6 faces for a 100 mm block) keeps the layer stack as polygons - the 3MF Slice form - and builds
  prisms only for the layers a section or a drawing asks for; manifold3d's `CrossSection.extrude` and `batch_boolean`
  are the mesh alternative where one closed body is wanted.
- **Measurements**: written into the payload's metadata by the wrapper (`shape_envelope.METADATA_*`): the mass
  properties from the route ([9.2](#92-what-the-print-weighs)), and the volume the print displaces from the field's
  offset integral, so that neither is the stack's 1-3% approximation of the bead.
- **Picture**: the design, by the part-level visual rule already built - a print is drawn as what it looks like from
  outside, and a section of it as what it is.
- **Keyed** on the design's key, `MachineConfig.key()` and the route implementation's code version, as a route is.
- **Printability** for free: a feature thinner than a line deposits nothing, so comparing the print with the design
  inside the design's tolerance (`wrapper_compare` measures the difference already) reports a wall too thin to print, a
  hole too small for the nozzle, a pin that vanishes - `manufacturability-additive`'s next question, asked of what the
  printer will actually do.

### 9.4 Where SDF parts fit

**Built as an option**: a printed part that says `type: sdf` is kept as a script whose field is its route's beads
(`cam_fff.sdf_script`: each layer's paths splatted into a 2D distance field, the stadium bead profile, bounded by the
design's box), meshed by the `sdf` part type at half a layer. It is there because it is the bead-exact surface, and it
is not the default for the reason below.

The `sdf` part type is the natural home for the bead-exact surface - (C) above is literally its pipeline - but not as
the part's geometry by default: a bead-resolved surface is ~0.6 M triangles per metre of route at 0.05 mm, and a print of anything
but a coin has hundreds of metres. It is right for three things:

- **A section or a detail**: the field's SDF restricted to a box (a corner, a boss, a 2 mm slab) meshes in seconds, and
  is what a reader of a section drawing or the 3D view zoomed into a wall wants to see - the scallops and the voids.
- **Infill patterns that are fields already** - a gyroid core is an SDF, `|sin x cos y + ...| - t`, and a TPMS-filled
  design for resin or powder is one by construction.
- **Export to a format that carries a field** rather than a surface, where a reader exists
  ([section 7.4](#74-interchange)).

### 9.5 `pc export` and `pc import`

- **`pc export`** of a printed part writes the print, because the print is the part; `--visuals`/a picture writes the
  design. The route itself is `pc cam`'s file. A 3MF of the print may carry the layer stack as the 3MF **Slice**
  extension - the footprint polygons and a height per layer - which is the stack with no tessellation at all.
- **`pc import` of a route** (`.gcode`, `.nc`): a part type `gcode` whose geometry is the deposit of the file's moves
  (the same footprint stack and field, widths from `E`, `L`, `h` and the filament diameter by volume conservation), with
  `manufacturing: {method: additive, source: <design>}` when the user names the design. A slicer's own output becomes a
  print PartCAD can weigh, section and compare with its design.
- **`pc import` of an as-printed model** (a scan): a part with its own `type:` naming its design, compared with it inside
  the tolerance, as in 9.3.

### 9.6 Other processes

Resin (`sla:`) and powder (`sls:`, `mjf:`) are machines of their own when something reads them. Their print is a
hollowed design rather than a route's deposit - a wall thickness, drain holes, an optional lattice - which is an SDF
(shell and gyroid) far more naturally than a B-rep.

## 10. Specifications

Requirements use SHALL; each is pinned by `tests/partcad/unit/test_additive.py`.

**Requirement: a design.** An `additive` part MAY name a design in `source:`, and SHALL be its own design where it names
none. A design SHALL NOT be procured.
- *Scenario:* `printed` names `design` → `procured_as(printed) == []`, while a `subtractive` part naming the same object
  is procured as it.

**Requirement: drawn as its design.** A printed part that names a design and no `visual:` SHALL be drawn as the design
wherever a picture is drawn; a `visual:` of its own SHALL win; `manufacturing: visual:` SHALL be refused.
- *Scenario:* `as-printed: {type: basic, manufacturing: {method: additive, source: design}}` → its picture is
  `//:design`; with `visual: look` → `//:look`.

**Requirement: no geometry of its own.** An `additive` or `forming` part that names a design, or a `subtractive` part
that names its stock and its instructions, and that states no `type:` or `type: brep|step|sdf`, SHALL be what its machine
makes: read from its file where one is written, made on demand where none is. A part fetched from a `fileUrl:` SHALL keep
its file. (`tests/partcad/unit/test_materialize.py`.)
- *Scenario:* no `type:` → `type: manufactured`, `implied_type: brep`; `printed.brep` written → read as `brep`.
- *Scenario:* `pc cam --materialize :printed` → `printed.brep`; with `type: step` → `printed.step`; with `type: sdf` →
  `printed.py`.
- *Scenario:* a part with a file of its own the wrong size → `materialize` fails, naming the difference.

**Requirement: a printer is a machine.** `fff:` SHALL be read as a `MachineConfig`: `toolAxis`/`along`, `nozzle` and
`filament` its own; `layerHeight`, `lineWidth`, `walls`, `topLayers`, `bottomLayers`, `infill`, `infillPattern` and
`feed` its job; an unreadable one SHALL be `machine_error`. It SHALL be routed by `pc cam`.
- *Scenario:* `fff: {along: -Y, feed: 50 mm/s}` → axis `-Y`, feed 3000 mm/min.
- *Scenario:* `infill: 20%` or `feed: 1200` directly under `manufacturing:` → "write it under 'fff:'".
- *Scenario:* a printed part that names no printer is passed over by `pc cam` over the package and routed by
  `pc cam -m fff`.

**Requirement: what is printed is checked.** `manufacturability-additive` SHALL ask the design, not the part's own
geometry, whether it is a closed solid, and SHALL key its verdict on the design and the printer.

**Requirement: instructions and suppliers.** The instructions SHALL say the design and the stated settings only; a cart
item SHALL carry them as `manufacturing`; a manufacturer SHALL be sent the design's geometry.

**Requirement: material is CMF.** A `manufacturing:` section SHALL NOT take a material; a reference SHALL report its
source's material to a cart where it states none; a part that is what its machine makes SHALL be lent its design's (or
its stock's) material and tolerance where it states none.

## 11. Roadmap

| Step | Status |
| --- | --- |
| `source:` as the design; the design as the default picture through the part-level `visual:`; a type-less printed part | built |
| `fff:` as a machine with `pc cam`'s vocabulary | built |
| Check, instructions, cart, schema; `get_mcft` through references; a manufacturer sent the design | built |
| `pc cam -m fff`: the route from `_faces_at`, `_wire_points`, Clipper rings and lines, `Program` with `E` ([9.1](#91-pc-cam-writes-a-printers-route)) | built |
| The route's volume and filament in its stats ([9.2](#92-what-the-print-weighs)) | built |
| The part's mass from the route rather than from the deposit's geometry | proposed |
| `manufactured` part type: the print, the cut, the molding as the part; `pc cam --materialize`; the `materialize` check ([9.3](#93-the-print-is-the-part)) | built |
| A print kept as an SDF (`type: sdf`) ([9.4](#94-where-sdf-parts-fit)) | built |
| SDF sections and details of a print; gyroid infill as a field | proposed |
| `pc import` of G-code as a print; 3MF Slice export ([9.5](#95-pc-export-and-pc-import)) | proposed |
| A slicer package as a route `implementation:` (PrusaSlicer/CuraEngine in a container) | proposed |
| Cart CMF references and `ids`; physics per solid material | proposed |
| Resin and powder printers | open |

## 12. Appendix: the first survey - the print from its settings alone

The first survey, of November 2026, asked how the print is predicted from the settings alone, without a route. It is kept because its sources stand - slicer weights, bead models, licences, vocabulary - and because [section 8](#8-prototype-a-route-from-pc-cams-parts-and-what-it-deposits) measured where its shell-and-core formula falls short of a route (6.6% on a cube).

From slicer sources (PrusaSlicer `version_2.9.2`, OrcaSlicer and Cura/CuraEngine `main`), vendor documentation and the
literature, November 2026.

### 12.1 From the settings, without a route

**Infill density is an area fraction by construction.** Cura sets the line spacing from it:
`infill_line_distance = infill_line_width * 100 / infill_sparse_density * k`, `k` 1 for lines, 2 for grid, 3 for
triangles and cubic ([`fdmprinter.def.json`](https://github.com/Ultimaker/Cura/blob/main/resources/definitions/fdmprinter.def.json));
OrcaSlicer's gyroid period is proportional to `spacing / (density * 2.44)`
([`FillGyroid.hpp`](https://github.com/SoftFever/OrcaSlicer/blob/main/src/libslic3r/Fill/FillGyroid.hpp)). So on every
layer the sparse region is covered to about the declared fraction, and **"a solid skin, plus the declared fraction of
the core"** is the right first-order model - not a heuristic like "0.2 + 0.8 x infill".

**Slicers do not estimate weight; they add up what they extrude.** PrusaSlicer: `weight = extruded_volume x
filament_density x 0.001` ([`GCode.cpp`](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/libslic3r/GCode.cpp));
OrcaSlicer the same; CuraEngine reports `material_amount` per extruder. Their error is the filament density and flow
users enter: a few percent, and biased per material
([Prusa forum](https://forum.prusa3d.com/forum/prusaslicer/filament-mass-estimate/);
[a 2025/26 study of slicer mass prediction bias](https://www.researchgate.net/publication/403668811_Dimensional_Fidelity_and_Slicer_Mass_Prediction_Bias_in_FFF-Printed_UAV_Micro-Frames_A_Material-Dependent_Comparative_Study);
[TU Wien, real against nominal infill](https://repositum.tuwien.at/bitstream/20.500.12708/190929/1/Bodur%20Osman%20-%202023%20-%20Porosity%20Examination%20of%20Additive%20Manufactured%20Parts%20and..pdf)).
Published predictive models are mostly regressions and networks, not formulas
([doi:10.3390/coatings15101117](https://doi.org/10.3390/coatings15101117)).

**Implicit (SDF) tools** shell the body and fill the core with a lattice field, and define infill as
`(V_infilled - V_shell) / (V_orig - V_shell)`
([nTop](https://docs.ntop.com/help-articles/knowledge-base/lattices/how-to-calculate-the-infilled-percentage-of-a-shelled-and-filled-body)).
A sheet gyroid's relative density is about proportional to wall thickness over cell size, which is why a slicer, whose
wall thickness is the nozzle's, reaches a density by changing the period (*unverified*: from a search summary of
[Springer s40964-025-01200-7](https://link.springer.com/article/10.1007/s40964-025-01200-7); the constant, about
`3.09 t / a`, is the survey's own calculation). Python meshing of SDFs:
[fogleman/sdf](https://github.com/fogleman/sdf) (MIT).

**Walls are horizontal offsets of each layer**, not normal offsets of the solid: a 3D offset
(`BRepOffsetAPI_MakeOffsetShape`, `MakeThickSolid`) thickens a sloped face along its normal, which is not what a
slicer does, and fails on thin features ([OCCT modelling algorithms](https://occt3d.com/dev/doc/overview/html/occt_user_guides__modeling_algos.html)).

### 12.2 From a route (G-code)

**A bead's cross-section follows from the extrusion by volume conservation**: `A = E * pi (d_f / 2)^2 / L`, `E` the
filament fed over a move of length `L`. Its width from its area and the layer height `h`
([`GCodeProcessor.cpp` L2631-2668](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/libslic3r/GCode/GCodeProcessor.cpp);
[Slic3r flow math](https://manual.slic3r.org/advanced/flow-math)):

| Model | Width | Used by PrusaSlicer for |
| --- | --- | --- |
| Stadium (a rectangle with round ends) | `A / h + h (1 - pi / 4)` | everything by default |
| Rectangle | `A / h` | external perimeters (x 1.05) |
| Circle | `d_f sqrt(E / L)` | bridges |
| Ellipse | `4 A / (pi h)` | (literature) |

Real beads range from round (fast, high) to flat rounded boxes (slow, squashed)
([Comminal et al. 2018, CFD](https://orbit.dtu.dk/en/publications/numerical-modeling-of-the-strand-deposition-flow-in-extrusion-bas/));
the stadium agrees with experiment well enough to be the default
([PMC7183729](https://pmc.ncbi.nlm.nih.gov/articles/PMC7183729); ellipse fitted to micrographs and voxelised:
[arXiv 2209.02642](https://arxiv.org/abs/2209.02642)). Tools: [GCode2STL](https://github.com/Matter-and-Form/GCode2STL)
(MIT, a square tube per move, for looking at); GPAMS, a voxel deposition model reported within 3.3% of the measured mass
([Additive Manufacturing, 2022](https://www.sciencedirect.com/science/article/abs/pii/S2214860422006686)); Sandia's hex
meshes of the as-printed part ([arXiv 2509.12436](https://arxiv.org/abs/2509.12436)); PrusaSlicer's G-code viewer and
Cura's layer view, which draw widths from `E` as above.

**Weight from a route** needs no geometry at all: `m = rho_f pi (d_f / 2)^2 sum(E_net)`, minding absolute and relative
`E` (M82/M83), `G92` resets and volumetric mode (M200).

**Surface error.** The staircase's cusp height is about `h |n . z|` for a face of normal `n`
([Dolenc & Makela 1994, via Hamburg](https://tams-www.informatik.uni-hamburg.de/publications/2017/Adaptive%20Slicing%20for%20the%20FDM%20Process%20Revisited.pdf);
the closed form is *unverified*); a stadium bead's rounded edge takes about `0.107 h` off every vertical wall.

### 12.3 Shrinkage, warpage, deviation

FFF slicers compensate by scaling per material - Cura `material_shrinkage_percentage_xy/_z`, PrusaSlicer
`filament_shrinkage_compensation_xy/_z`, Orca `filament_shrink` - and offset holes and contours (`xy_size_compensation`,
`xy_contour_compensation`). None simulates. Simulation is commercial - [Digimat-AM](https://hexagon.com/products/digimat/polymer-additive-manufacturing)
(FFF, SLS warpage), [Ansys Additive](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/add_print/add_print_why_use_aa.html),
Simufact (iterated compensation) - or open and metal-only: [AdditiveFOAM](https://github.com/ORNL/AdditiveFOAM)
(GPL, thermal), Adamantine (ORNL, deal.II; [OSTI](https://www.osti.gov/pages/biblio/2472702)), the inherent-strain
method for laser powder bed fusion ([review](https://doi.org/10.1007/s00170-022-10052-2)). Nothing open predicts FFF
warpage well enough to build on: deviation is for a CAE plugin, not for PartCAD's core.

### 12.4 Slicers and their licences

| Tool | Licence | Headless |
| --- | --- | --- |
| PrusaSlicer, OrcaSlicer, Bambu Studio, SuperSlicer | AGPL-3.0 | `prusa-slicer --export-gcode --load print.ini`; `orca-slicer --load-settings ... --slice 0 --export-3mf`. The G-code says `; total filament used [g]`; Orca's 3MF `slice_info.config` the plate's weight. |
| CuraEngine | AGPL-3.0 | `CuraEngine slice -j fdmprinter.def.json -s infill_sparse_density=20 -l part.stl -o part.gcode`. |
| Kiri:Moto | MIT | A browser worker; no documented command line. |
| pyslm (laser powder bed) | LGPL-2.1 | A Python library. |
| FullControl | GPL-3.0 | A Python library that writes G-code paths. |
| lib3mf | BSD | - |

PartCAD is Apache-2.0. Running an **unmodified** slicer as a separate program - a subprocess or a container - is
communication between programs, not a combined work
([GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html#MereAggregation)), and AGPL's section 13 binds only a modified
program ([AGPL](https://www.gnu.org/licenses/agpl-3.0.html)). So a slicer is run in a container, through
`partcad_utils.containers` like KiCad, and libslic3r, CuraEngine and FullControl are never imported; pyslm would carry
relinking obligations into the bundles.

**Formats** ([3MF specifications](https://3mf.io/spec/); core is ISO/IEC 25422:2025): PrusaSlicer's project 3MF keeps
its settings in `Metadata/Slic3r_PE.config` and per-object overrides in `Slic3r_PE_model.config`
([`3mf.cpp`](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/libslic3r/Format/3mf.cpp)); Bambu/Orca in
undocumented JSON and XML ([OpenVCAD writes both](https://matterassembly.org/OpenVCAD-Docs/v3/guides/compilers/slicer-project.html)).
The 3MF **Slice** extension stores stacks of 2D polygons, **Beam Lattice** nodes and beams, **Volumetric** voxel and
implicit fields, and **Toolpath** deposition with `beadwidth` and `beadheight`
([spec_toolpath](https://github.com/3MFConsortium/spec_toolpath); its status, published or release candidate, is
*unverified*).

### 12.5 Vocabulary

ISO/ASTM 52900 names the seven process categories - material extrusion (MEX), powder bed fusion, vat
photopolymerization, binder and material jetting, sheet lamination, directed energy deposition
([ISO](https://www.iso.org/standard/74514.html)) - and no standard names infill or walls. The vocabulary in use is the
slicers':

| PartCAD `fff:` | PrusaSlicer | Orca / Bambu | Cura |
| --- | --- | --- | --- |
| `layerHeight` | `layer_height` | `layer_height` | `layer_height` |
| `walls` | `perimeters` | `wall_loops` | `wall_line_count` |
| `topLayers`, `bottomLayers` | `top_solid_layers`, `bottom_solid_layers` | `top_shell_layers`, `bottom_shell_layers` | `top_layers`, `bottom_layers` |
| `infill` | `fill_density` | `sparse_infill_density` | `infill_sparse_density` |
| `infillPattern` | `fill_pattern` | `sparse_infill_pattern` | `infill_pattern` |
| `lineWidth` | `extrusion_width` | `line_width` | `line_width` |
| `nozzle` | `nozzle_diameter` | `nozzle_diameter` | `machine_nozzle_size` |

PrusaSlicer's patterns: `rectilinear`, `grid`, `triangles`, `stars`, `cubic`, `honeycomb`, `3dhoneycomb`, `gyroid`,
`lightning`, `adaptivecubic`. `infillPattern` is free text for that reason: the slicer that reads it decides, and an
implementation that cannot draw one says so.

### 12.6 Material and process in slicers and services

Slicers keep three profiles - print, filament, printer - and a filament is a brand, a material and a colour with a
density and a diameter ([Cura `fdm_materials`](https://github.com/Ultimaker/fdm_materials)). Print services quote on a
material and finish (Craftcloud's published structure: material group, material, finish group, config with the colour;
[`@all3dp/material-structure`](https://www.npmjs.com/package/@all3dp/material-structure)), Shapeways on a material id
([API](https://developers.shapeways.com/docs)); Xometry offers infill as three grades on its web quote
([Xometry](https://www.xometry.com/resources/3d-printing/comparing-infill-options-for-fdm-1/)); JLC3DP's API is gated.
None takes a filament as a process setting - which is the line [section 6](#6-cmf-and-the-manufacturing-section) draws.
