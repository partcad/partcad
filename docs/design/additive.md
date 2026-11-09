# Additive manufacturing - the design, the print, and what the print weighs: design

This is the design record for how PartCAD describes a printed part: the design it is a print of, what it is drawn as,
the process that prints it, and - proposed, not built - how the printed part itself is worked out: its real weight, and
its geometry as a model of its own. How to *use* what is built is the user documentation's job
(`docs/source/config_making.rst`, "Additive"); this file is for whoever changes it.

Status words, as in [`cmf.md`](cmf.md): **built** is on this branch; **decided** is agreed and not built yet;
**proposed** is not agreed; **open** is not decided at all. *Unverified* marks a claim the survey could not confirm
from a primary source.

## Contents

1. [Goal](#1-goal)
2. [What PartCAD did before](#2-what-partcad-did-before)
3. [The declaration](#3-the-declaration)
4. [Three geometries: the design, the visual, the print](#4-three-geometries-the-design-the-visual-the-print)
5. [CMF and the manufacturing section](#5-cmf-and-the-manufacturing-section)
6. [Survey: predicting the printed part](#6-survey-predicting-the-printed-part)
7. [Proposal: the printed part, its weight, and its route](#7-proposal-the-printed-part-its-weight-and-its-route)
8. [Specifications](#8-specifications)
9. [Roadmap](#9-roadmap)

## 1. Goal

A 3D-printed part is not the solid its designer drew. A slicer turns that solid into a skin a few lines thick, a top
and a bottom a few layers deep, and an inside filled at a density - 15%, 20%, 40% - in a pattern. What is drawn, what is
placed in an assembly and what a supplier is sent is the design; what the part *weighs*, where its centre of mass is,
how stiff it is and what a section through it shows are properties of the print.

So in PartCAD:

- A printed part names its **design** (`manufacturing: source:`) apart from itself, and the design is what is printed,
  what the tolerance is measured against and what a print service is sent.
- The design is also what the part is **drawn** as, unless it names a **visual** (`manufacturing: visual:`).
- The **process** settings that decide the print's geometry (walls, top and bottom layers, infill) are declared under
  the process' own subsection (`fff:`), as a subtractive machine's are under `cnc:` or `laser:`.
- The **print** - the design as the process makes it - is derived from the two, never modelled by hand: first its
  weight, then its geometry, then from the route that prints it.
- What it is **made of** stays the part's CMF. The manufacturing section says how, never of what.

## 2. What PartCAD did before

| Where | What happened |
| --- | --- |
| `manufacturing: method: additive` | A label. The part was its own design; nothing else could be said. |
| `_read_machines` | Refused a cut's keys on a printed part ("describes no cut"), and anticipated "a printer's keys under a printer's subsection". Everything else was ignored. |
| `manufacturability-additive` | The part is a closed solid. `# TODO(clairbee): Utilize the data provided in the config`. |
| `procurement` | A printed part is made "from nothing it names": nothing procured. |
| `manufacturing_instructions` | "Made additively (3D printed)." |
| Weight (`physics`) | The solid's volume at the material's density: a 20%-infill PLA bracket weighed as solid PLA, two to four times its real weight. |
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
    manufacturing:
      method: additive
      source: bracket         # the design
      visual: bracket-render  # optional: drawn as this instead
      fff:                    # the process
        layerHeight: 0.2 mm
        walls: 3
        topLayers: 5
        bottomLayers: 4
        infill: 20%
        infillPattern: gyroid
```

| Key | Meaning |
| --- | --- |
| `source` | Optional. The design. A part naming none is its own design - what every `additive` part written before this meant. Never stock: `procurement.stock_name` is None for a printed part whatever it names. |
| `visual` | Optional, and only beside a `source` and only on a part with no `type:`. What the part is drawn, placed and exported as. Never what is printed. |
| `fff` | Optional. Fused filament fabrication (ISO/ASTM 52900 material extrusion; "FDM" is a trademark). Its keys: `nozzle`, `layerHeight`, `lineWidth` (lengths, any unit `pc cam` reads), `walls`, `topLayers`, `bottomLayers` (whole numbers), `infill` (`20%` or `0.2`; a bare number above 1 is refused), `infillPattern` (a name, lower-cased), `desc`. |

**No `type:`.** A part that names a design needs no geometry of its own. `PartConfiguration.normalize` gives it
`type: alias`, `source: <visual, else design>` and a marker (`implied_type: additive`,
`part_config_manufacturing.implied_type`), so it *is* a reference: it takes its source's cache key, ports, CMF and
tolerance, restates its own `manufacturing:` section (`PartFactoryAlias.RESTATED`), and takes `with:` to parameterise
the design (`with: {color: ":orange"}`). A part that does write a `type:` is drawn as what it is and still names its
design in `source`; it may not say `visual:` as well (the schema and the check refuse it). A design that cannot be
found makes a type-less printed part a reference to nothing, which fails as every such reference does.

**Errors are recorded, not raised.** A process subsection that cannot be read sets `process_error`, kept apart from
`machine_error` on purpose: `pc cam` visits every part whose `machine_error` is set, and a typo in an infill is nothing a
router program has to say about. A print setting written directly under `manufacturing:` is reported as "a setting of
the process it is printed by; write it under 'fff:'" rather than as an unknown key. The cut's keys on a printed part
are still refused as before, in the words every other method hears.

**Names.** PartCAD's camelCase, not one slicer's spelling, so that the declaration is not tied to the slicer that reads
it; the user documentation has the table to PrusaSlicer and Cura keys ([section 6.5](#65-vocabulary)). Only the settings
that decide the printed *shape*: speeds, temperatures and cooling decide whether a print succeeds, and are the
printer's. `PROCESS_DEFAULTS` (0.4 mm nozzle, 0.2 mm layers, 0.45 mm lines, 2 walls, 4 + 4 layers, 15% grid) is what
PartCAD assumes where it has to work something out; it is never written into instructions or sent to a supplier, whose
defaults are better than PartCAD's guess.

**Where it is read.**

| Reader | What it does with it |
| --- | --- |
| `manufacturability-additive` | The declaration can be read; the visual is not doubled by a type; the **design** (or the part itself) exists and is a closed solid. Keys on the design's key and the process settings. |
| `procurement` | A design is not stock: nothing is procured for it. |
| `manufacturing_instructions` | "Printed from the design `bracket`." and "Print it on a filament printer (FFF); layer height 0.2 mm, 3 walls, ..., infill 20% gyroid." - only what was stated. |
| `build_plan` | A `process_error` is a problem of the part, as a `machine_error` is. |
| Cart | `manufacturing: {method, design, processes}` beside `material`/`color`/`finish` (`PartConfigManufacturing.print_data`), settings as stated. |
| Manufacturer provider `load()` | Sends the **design's** STEP, not the visual's. |

## 4. Three geometries: the design, the visual, the print

| | What it is | Where it comes from | Who reads it |
| --- | --- | --- | --- |
| **design** | The solid the designer had in mind | `source:`, else the part | the additive check, the tolerance, a print service, the slicer |
| **visual** | What the part looks like in a view | `visual:`, else the design | every view and drawing, an assembly's placement, `pc export` by default |
| **print** | The design as the process makes it | derived: design + process (+ route) | weight, centre of mass, inertia; a section view; `pc export` of the print ([section 7](#7-proposal-the-printed-part-its-weight-and-its-route)) |

The visual is the part's geometry - `get_wrapped` - because it is what nearly every reader wants and the cheapest to
have. The print is a *derived* object, as a route from `pc cam` is: worked out on demand, cached under a key of its own,
never what an assembly places. That is what keeps a printed part costing what it cost before for everything that does
not ask about the print.

*Rejected:* making the print the part's geometry (every render and every assembly would tessellate an infill
lattice to draw a surface that looks like the design); a `print:` part type the user declares by hand for every printed
part (one more declaration per part for what is always the same derivation - kept instead as an opt-in for exporting
one, [section 7.4](#74-pc-export-and-pc-import)); the visual as a top-level key on every part (only a print has a design
it differs from; a part that is drawn as something else is a reference).

## 5. CMF and the manufacturing section

**Decided:** material is not a manufacturing property. **Built:** the two fixes below. **Proposed:** the rest.

What CMF settled (see [`cmf.md`](cmf.md)) is that an item's material, colour and finish are stated by its definition and
carried with its geometry. The question was whether the manufacturing section should carry a material too - a filament
for a print, a sheet for a laser. It should not:

- **One place.** The filament *is* the part's `material`: its density is what the part is weighed at, its colour claim
  what it is drawn in, its `manufacturable:` what the `cmf` check counts, its `ids` what a supplier matches. A
  `manufacturing: material:` would be a second answer to the same question, and the two can disagree.
- **Slicers draw the same line.** PrusaSlicer's Print / Filament / Printer, Orca's process / filament / machine, Cura's
  quality profile / material XML / machine definition: density, diameter, colour, flow and shrinkage are the material's;
  layers, walls and infill are the process' ([section 6.6](#66-material-and-process-in-slicers-and-services)).
- **What a process constrains is a capability.** That FFF prints thermoplastics and not aluminium is what a provider's
  `caps` say, not what a part declares.
- **An effective density is not a material.** "PLA at 20%" declared as a material of 0.4 g/cm3 would weigh the part
  right and be wrong everywhere else - the CMF check, the exports, the cart, the colour. The print's weight is derived
  from the material and the process ([section 7.1](#71-weight)), never declared.

Where material still lives outside CMF, and what is done about each:

| Where | Problem | Done |
| --- | --- | --- |
| `ShapeConfiguration.get_mcft` (the cart) | Read only the part's own `parameters:`; a reference - and so every type-less printed part - was ordered as made of nothing. | **Built:** falls back to what the reference resolves to. |
| Manufacturer `load()` | Would have sent the visual. | **Built:** sends the design. |
| Cart `material`/`color`/`finish` | Raw strings from `parameters:` defaults (`"red"`, a synthesised `"none"` finish), matched by providers as names (`TODO: resolve ... as a color object`). | **Proposed**, staged as `contributing.rst` requires: add the canonical CMF references and their `ids` beside them (`cmf.own_info`), migrate providers to match by `ids`, then retire the strings. Changing them in place breaks every provider's `caps` matching at once. |
| `properties: material:` (physics, the BOM's `material` column, URDF) | One material per part, promoted from the parameter; the CMF section's material per *solid* - what a STEP file states - is not what the part is weighed at, and a two-material part is weighed at one density. | **Proposed:** physics weighs each solid by the material its CMF set claims (the summary already counts solids per set); `properties: material:` becomes derived from CMF and is no longer read where the section is at hand. |
| Hand-written `properties: material:`/`color:` (`examples/produce_part_cadquery_logo`) | `properties:` is "never written by hand in a package" (`PartFactory.record_object_type_properties`). | **Proposed:** move to the CMF parameters with the next re-render of that example; its images are checked in. |
| `object_type_parameter` | Still reads only the reference's own declaration (said in its docstring). | **Open:** whether every object-type parameter should resolve through a reference, as `get_mcft` now does. |

## 6. Survey: predicting the printed part

From slicer sources (PrusaSlicer `version_2.9.2`, OrcaSlicer and Cura/CuraEngine `main`), vendor documentation and the
literature, November 2026.

### 6.1 From the process settings, without a route

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

### 6.2 From a route (G-code)

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

### 6.3 Shrinkage, warpage, deviation

FFF slicers compensate by scaling per material - Cura `material_shrinkage_percentage_xy/_z`, PrusaSlicer
`filament_shrinkage_compensation_xy/_z`, Orca `filament_shrink` - and offset holes and contours (`xy_size_compensation`,
`xy_contour_compensation`). None simulates. Simulation is commercial - [Digimat-AM](https://hexagon.com/products/digimat/polymer-additive-manufacturing)
(FFF, SLS warpage), [Ansys Additive](https://ansyshelp.ansys.com/public/Views/Secured/corp/v242/en/add_print/add_print_why_use_aa.html),
Simufact (iterated compensation) - or open and metal-only: [AdditiveFOAM](https://github.com/ORNL/AdditiveFOAM)
(GPL, thermal), Adamantine (ORNL, deal.II; [OSTI](https://www.osti.gov/pages/biblio/2472702)), the inherent-strain
method for laser powder bed fusion ([review](https://doi.org/10.1007/s00170-022-10052-2)). Nothing open predicts FFF
warpage well enough to build on: deviation is for a CAE plugin, not for PartCAD's core.

### 6.4 Slicers and their licences

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

### 6.5 Vocabulary

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

### 6.6 Material and process in slicers and services

Slicers keep three profiles - print, filament, printer - and a filament is a brand, a material and a colour with a
density and a diameter ([Cura `fdm_materials`](https://github.com/Ultimaker/fdm_materials)). Print services quote on a
material and finish (Craftcloud's published structure: material group, material, finish group, config with the colour;
[`@all3dp/material-structure`](https://www.npmjs.com/package/@all3dp/material-structure)), Shapeways on a material id
([API](https://developers.shapeways.com/docs)); Xometry offers infill as three grades on its web quote
([Xometry](https://www.xometry.com/resources/3d-printing/comparing-infill-options-for-fdm-1/)); JLC3DP's API is gated.
None takes a filament as a process setting - which is the line [section 5](#5-cmf-and-the-manufacturing-section) draws.

## 7. Proposal: the printed part, its weight, and its route

**Proposed.** In the order it would be built: each step is useful on its own, and each is the next one's test.

### 7.1 Weight

A printed part's mass, centre of mass and inertia are worked out from the design, the material's density and the
process, and `pc info`, the exports and Build vs Buy report them in place of the solid's. The design's **volume** stays
what it was - a closed print displaces its envelope, which is what a scene buoys it by - so only the mass properties
change.

**The model is the slicers' own, done per layer** ([section 6.1](#61-from-the-process-settings-without-a-route)):

```
for each layer i, at z_i = z_min + (i + 1/2) h:
  S_i     = the design's section at z_i                       (2D faces)
  C_i     = S_i offset inward by t_w = lineWidth * walls      (BRepOffsetAPI_MakeOffset, joined)
  T_i     = C_i - (S_i+1 ∩ ... ∩ S_i+topLayers)               solid top skin
  B_i     = C_i - (S_i-1 ∩ ... ∩ S_i-bottomLayers)            solid bottom skin
  P_i     = C_i - T_i - B_i                                   sparse
  dense_i = S_i - P_i,  sparse_i = P_i
mass   = rho h sum_i [ A(dense_i) + phi A(sparse_i) ]
moment = the same sum over each region's area moments (BRepGProp::SurfaceProperties), as slabs of thickness h
```

`phi` is `infill`, `rho` the material's density. Solid regions count at full density, which is how Slic3r spaces solid
lines. A core that comes out empty is solid, as a slicer fills it. 2D offsets and booleans of planar faces are what OCCT
does most reliably, the number of sections is the part's height over the layer height (500 for 100 mm at 0.2 mm), and
nothing is ever a 3D lattice.

On a 20 mm cube at 0.2 mm layers, 0.45 mm lines, 2 walls, 5 + 5 layers and 15% infill in PLA (1.24 g/cm3) the core is
18.2 x 18.2 x 18 mm (5962 mm3) and the part `1.24 x (8000 - 0.85 x 5962) / 1000` = about **3.6 g**, against **9.9 g** as solid - which is the error this fixes.
Expected accuracy is a slicer's: within 5-10% of a scale, dominated by the filament's real density and flow.

- **Where:** a wrapper in the sandbox (`wrapper_print.py`, the measurement beside `shape_measure`), asked by `physics`
  for a part whose manufacturing data names a process; `_derive` takes its mass properties instead of the solid's.
  Sources say how: `derived: printed - 3 walls, 5/4 layers, 20% infill, at 1240 kg/m^3`.
- **Cached** under the design's key, the process' `settings()` (`PrintProcess.key()`) and the density, as the solid's
  derivation is (`physics._derived_hash`), so editing the infill re-weighs without rebuilding anything.
- **Defaults:** `PROCESS_DEFAULTS` where a setting is not stated, said in the source. A printed part naming no process
  is weighed as solid, as now, and `pc info` says that is an upper bound.
- **Cheap fallback**, for a design the sections fail on: `V_core ~ vol(offset3D(S, -t_w) ∩ S shifted down t_t ∩ S
  shifted up t_b)` and `m = rho [V_S - (1 - phi) V_core]`, said as the less exact of the two.

### 7.2 The printed geometry

The same per-layer regions are the printed part's geometry, at three levels of detail:

| Level | What it is | Made by | Good for |
| --- | --- | --- | --- |
| `shell` | Two solids: the skin (dense) and the core (at `phi`) | the regions above, extruded by `h` and fused per kind | a section view of the walls; FEA with an effective core modulus; a STEP of the print |
| `layers` | Every layer's dense regions plus its infill lines, clipped to `P_i`, each extruded by `h` | the pattern's 2D curves per layer: straight lines for `lines`/`grid`/`triangles`, the gyroid's level set `sin x cos y + sin y cos z + sin z cos x = 0` at `z_i` | seeing the infill; exact mass of the model; a mesh for a viewer |
| `route` | Every extrusion move swept by its bead | a G-code ([section 7.3](#73-routes)), stadium cross-sections of width `A / h + h (1 - pi / 4)` | the part as *that* print will be |

`shell` is a B-rep and stays one. `layers` and `route` are meshes, not B-reps: a gyroid core is millions of faces, and
OCCT's booleans are the wrong tool for it. They are written as STL or 3MF in the sandbox, and a layer stack is exactly
what the 3MF **Slice** extension stores, which is the compact form of `layers` - 2D polygons and a height, no
tessellation at all.

### 7.3 Routes

`pc cam` writes a router's program today; a printer's is the same idea - the route a machine follows - and the slot is
there: `cam:` file types are implementations a package supplies, and `implementation:` names one.

- **A slicer implementation**, in a package of its own (`partcad/partcad-slicer`), runs an unmodified PrusaSlicer or
  CuraEngine **in a container** through `partcad_utils.containers` ([section 6.4](#64-slicers-and-their-licences)),
  translating `fff:` to that slicer's keys by the table in [section 6.5](#65-vocabulary) and handing it the design's
  STL or 3MF. It returns the G-code and what the slicer says of it (grams, time). `pc cam bracket-printed` then writes
  `bracket-printed.fff.gcode`, the alternatives landing beside each other as `-m laser` and `-m cnc` do.
- **A route a part is printed with.** A printed part may name it - a G-code file it ships, or the route `pc cam`
  writes - under `instructions:`, the key `sheet_metal` uses for the sketch that says how it is bent. With one, the
  weight and the `route` geometry are the route's, not the model's, and `manufacturability-additive` checks that the
  route agrees with the declaration it claims to be (its layer height from its Z steps, its extent within the design's
  bounding box and tolerance).
- **The weight from a route** is the sum of `E` at the filament's cross-section and density: no geometry, no
  booleans, exact for that route.
- `//builtin/cam` does not slice, and will not: a slicer is somebody else's program with a release cycle of its own,
  which is the test `cam.py` gives for what ships in `builtin`.

### 7.4 pc export and pc import

- **`pc export --print [shell|layers|route]`** writes the printed geometry instead of the part's visual, in any format
  the level allows (`shell` to STEP, `layers`/`route` to STL and 3MF, `layers` to 3MF Slice). Nothing is declared
  for it.
- **A print as a part of its own**, for whoever wants to place it, draw it, section it or compare it: a part type
  `print` whose `source:` is the printed part and whose `detail:` is the level. It is an ordinary part from then on -
  cached, rendered, exported, weighed by its own geometry - and costs nothing until it is asked for.
- **`pc import` of an as-printed model** - a slicer's mesh, a scan, a G-code (as a `gcode` part type that sweeps it) -
  gives a part with its own `type:` and `manufacturing: {method: additive, source: <design>}`: exactly the "a part with
  a geometry of its own that names its design" case built here. A check `manufacturability-print-deviation` compares
  it with its design inside the design's tolerance (`wrapper_compare` measures the difference already), which is how
  a print that came out wrong is told from one that did not.

### 7.5 Other processes

Resin (`sla:`) and powder (`sls:`, `mjf:`) take settings of their own - hollowing and wall thickness, drain holes,
packing - and get subsections of their own when something reads them, as the machines did. The weight model of a
hollowed resin part is [section 7.1](#71-weight)'s with `infill: 0` and a 3D wall; a powder part is solid.

## 8. Specifications

Requirements use SHALL; each is pinned by the tests in `tests/partcad/unit/test_additive.py`.

**Requirement: a design.** An `additive` part MAY name a design in `source:`, and SHALL be its own design where it names
none. A design SHALL NOT be procured.
- *Scenario:* `printed` names `design` → `procured_as(printed) == []`, while a `subtractive` part naming the same
  object is procured as it.

**Requirement: no geometry of its own.** An `additive` part that names a design and no `type:` SHALL be a reference to
its visual - `visual:`, else the design - with its own `manufacturing:` section.
- *Scenario:* `printed: {manufacturing: {method: additive, source: design}}` → `type: alias`, `source: design`, and its
  manufacturing data names `design`.
- *Scenario:* a part with a `type:`, or with a top-level `source:`, is given none.

**Requirement: one visual.** `visual:` SHALL be said only beside a `source:` and only by a part with no `type:`.
- *Scenario:* `type: stl` and `visual: render` → `manufacturability-additive` fails naming both; `pc lint` refuses it.

**Requirement: the process' own subsection.** Print settings SHALL be read under `fff:` only, each as its kind, and an
unreadable one SHALL be recorded, reported by `manufacturability-additive` and the build plan, and not visited by `pc
cam`.
- *Scenario:* `infill: 20%` directly under `manufacturing:` → "write it under 'fff:'".
- *Scenario:* `fff: {infill: 20}` → "more than all of it"; `fff: {speed: 60}` → "does not take 'speed:'".

**Requirement: what is printed is checked.** `manufacturability-additive` SHALL ask the design, not the visual, whether
it is a closed solid, and SHALL key its verdict on the design and the process.
- *Scenario:* a design with open edges → "The design 'design' is not solid"; a visual with open edges → passes.

**Requirement: instructions and suppliers.** The instructions SHALL say the design and the stated settings only; a
cart item SHALL carry them as `manufacturing`; a manufacturer SHALL be sent the design's geometry.

**Requirement: material is CMF.** A `manufacturing:` section SHALL NOT take a material; a reference SHALL report its
source's material to a cart where it states none.
- *Scenario:* `printed` of a design with `material: //pub:pla` → the cart says `//pub:pla`.

## 9. Roadmap

| Step | Status |
| --- | --- |
| `source:` as the design, `visual:`, `fff:`, a type-less printed part, the check, instructions, cart, schema | built |
| `get_mcft` through references; a manufacturer sent the design | built |
| Weight per layer ([7.1](#71-weight)), in `pc info`, the exports and Build vs Buy | proposed |
| Cart CMF references and `ids` beside the strings; providers matching by `ids`; the strings retired | proposed |
| Physics weighing each solid by its CMF material | proposed |
| The printed geometry: `shell`, then `layers` ([7.2](#72-the-printed-geometry)); `pc export --print` | proposed |
| A slicer implementation of `pc cam` in a container; `instructions:` as the route; weight from a route ([7.3](#73-routes)) | proposed |
| `print` part type; `pc import` of an as-printed model and the deviation check ([7.4](#74-pc-export-and-pc-import)) | proposed |
| Resin and powder processes | open |
