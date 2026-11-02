# CMF - colour, material and finish: design

This is the design record for CMF in PartCAD: what colour, material and finish an item is, where that comes from,
how it is stored, checked and shown, and why. How to *use* it is the user documentation's job
(`docs/source/digital_thread/lifecycle/design_cmf.rst` and `docs/source/config_cmf.rst`); this file is for whoever
changes it. It carries the design and the requirements together: each section states what is decided, and the
requirements (with the scenarios that pin them) follow in [Specifications](#11-specifications).

Status words used below: **built** is on `devel` (with the pull request it came in, where that helps); **decided** is
agreed and not built yet; **open** is not agreed.

## Contents

1. [Goal](#1-goal)
2. [What PartCAD did before](#2-what-partcad-did-before)
3. [Declarations](#3-declarations)
4. [Names and references](#4-names-and-references)
5. [Where an item's CMF comes from](#5-where-an-items-cmf-comes-from)
6. [Storage: inside the BREP](#6-storage-inside-the-brep)
7. [Conventions and converters](#7-conventions-and-converters)
8. [Manufacturability](#8-manufacturability)
9. [Presentation](#9-presentation)
10. [LEGO, end to end](#10-lego-end-to-end)
11. [Specifications](#11-specifications)
12. [Decisions taken in review](#12-decisions-taken-in-review)
13. [Roadmap](#13-roadmap)

## 1. Goal

A product's colour, material and finish are part of what each of its items *is*. A red housing and a black housing
are two part numbers, ordered, stocked and inspected apart; LEGO sells an *element*, a design in a colour. A CMF
specification names each component by a vendor's catalogue or a standard - a colour by its catalogue name, a material
by its grade (`ABS`, `6061-T6`), a finish by its process and surface (`MIL-A-8625 Type II`, `VDI 3400 Ref 27`) - not
by an RGB value.

So in PartCAD:

- CMF is stated by an item's **definition** - the file or script it is built from, and its type parameters - and an
  assembly can only choose which items it places. CMF an assembly states itself is a picture of what it would look
  like, not a specification ([section 8](#8-manufacturability)).
- What a colour **looks like** (a display value, a hint) is kept apart from the **claim** that it can be sourced or
  made (a declaration).
- CMF is carried **with the geometry**, per face and per solid, so that a two-colour moulding is one item in two
  colours.
- Every view, command, export and document shows CMF the **same way**.

## 2. What PartCAD did before

| Where | What happened to CMF |
| --- | --- |
| `materials:` | Objects addressed as `<package>:<name>`: a name, a density, friction. No display, no claim, no aliases, no parameters. |
| `color`, `finish`, `texture` parameters | Reserved names. `color` was "not implemented yet" and accepted only by homogeneous part types; `finish` and `texture` did nothing. |
| `properties.color` | One `#RRGGBB` per node, inherited downward, drawn by the renderers and the IDE. |
| `wrapper_step.py` | `STEPControl_Reader`: every colour, material and name in the file discarded. |
| `export_step.py` | `STEPControl_Writer` of the flattened compound: no structure, names, colours or materials. |
| Script wrappers | `.wrapped` only; build123d's `.color`, `.material` and `.label` dropped. |
| OpenSCAD | Exported as `binstl`: colourless. |
| Cart and providers | Colour and finish matched as free strings, with `TODO: resolve … as a color object` (and as a finish object). |

## 3. Declarations

**Built** (this change's first pull request).

`colors:`, `materials:` and `finishes:` are three kinds of one **CMF declaration** (`partcad.cmf`). They share their
structure and differ only in their own facts:

| Field | Meaning |
| --- | --- |
| `desc`, `url` | What it is. |
| `display` | How to draw it. A **hint**, never a claim. A colour: any CSS colour notation (`#c91a09`, `rgb(201 26 9)`, `hsl(…)`, `oklch(…)`, `color(display-p3 …)`, `firebrick`), or the reference of another colour whose display it takes. A material: the substance's look as it comes. A finish: `{roughness, metallic}`, from 0 to 1, for a 3D view. |
| `manufacturable` | Whether the declaration is a **claim** that this can be sourced or made as declared. True unless stated. |
| `ids` | What other systems call it: a vendor's number, a standard's code, another CAD tool's library name (`{ldraw: 71, bricklink: 86}`). What converters match against ([section 7](#7-conventions-and-converters)). |
| `parameters` | A declaration may be parametric. Its string fields name parameters in PartCAD's own expression syntax (`%color%`, see `partcad.expr`), not Jinja2's, because `partcad.yaml` is rendered as a template before any reference gives a value. |
| `aliases` | Other names of itself in this package. |
| `type: alias`, `source` | This declaration is another name for the one `source` names, in any package. |

A **material** also states its physical facts (density, friction, viscosity) and may claim a colour for its natural
surface (`color:`): an unpainted aluminium part that states no colour is that colour, and counts as specified. A
**finish** names its process and surface specification through `ids` (`{vdi3400: "27"}`, `{spi: "B-2"}`,
`{moldtech: "MT-11010"}`). A part that states no finish is **as produced**, implied: nothing has to be declared for it.

**`texture` is reserved** for a visual texture - an image on a surface - in a later, visualization-only change. It is
no CMF component, no finish states one, and the schema refuses it on a declaration.

**Display colours are sRGB.** CSS, STEP (as OCCT writes `COLOUR_RGB`) and 3MF write sRGB; glTF's factors and OCCT's
`Quantity_Color` are linear and are converted at the edge. A colour outside sRGB is clipped channel by channel rather
than gamut-mapped: a display value is a hint.

**The standard catalogue holds no colour standard.** `//pub/std/color` declares one thing, the parametric display-only
`rgba` (`//pub/std/color:rgba;color=<RRGGBBAA>`, `manufacturable: false`): what anybody uses to colour a picture
without claiming anything. Colour standards are licensed or trademarked, and a package that uses one declares it
itself, as each vendor declares its own colours.

## 4. Names and references

**Built.**

A CMF declaration is named as the specification it comes from names it - `Medium Stone Grey`, `PA12, glass filled`,
`6061-T6 (SS)` - with no leading or trailing space. A YAML key is never read as a reference, so a declaration's name
may hold any text.

A **reference** is parsed, and the characters the parser gives a meaning to - `: ; , = # % * ? [ ]` - are written
percent-encoded inside one (`:PA12%2C glass filled`). The parser splits on the raw separators first and decodes each
name and value afterwards (`partcad_utils.utils.parse_parameterized_name`), so finding the separators is what it
always was. When PartCAD writes a name back out it escapes only what would otherwise be misread - a `,` in a value
that also holds an `=`, and a `%` that would read as an escape - so every name that could be written before is spelled
as it was, and a parametric reference can be a value of its own
(`Brick:3004;color=//pub/std/color:rgba;color=C91A09FF`).

A reference is **canonicalised** before it becomes part of an item's name (`partcad.cmf.canonical`): aliases followed,
a relative reference (`:stone`, `stone`) made absolute against the package that wrote it, its name escaped. That
happens where a reference is written - an ASSY link's `params:`, an `enrich`'s or an alias's `with:` - so two packages
that alias one vendor colour differently name the same item. A colour value that is no declaration but a colour
(`#C91A09`, `red`) - what a `color` parameter could hold before - becomes the display-only `rgba` of it, with a
warning.

## 5. Where an item's CMF comes from

**Built:** the parameters on every type, a part's declared colour drawn, canonical references, the parameters written
into the payload, propagation through ASSY links, sources and converters ([section 7](#7-conventions-and-converters)),
STEP instance overrides on `pc import`.

Every part type and every assembly type accepts five object-type parameters: `color`, `material` and `finish` (each a
reference to a declaration of its kind), `sourceCmf` and `cmfConvention`. `tolerance` stays with the types that build
one homogeneous body.

When a part is built, each sub-shape's CMF is, component by component:

1. what the **source** states - the file, the script, the OpenSCAD model - converted by the type's `cmfConvention`
   ([section 7](#7-conventions-and-converters));
2. completed by the part's **CMF parameters** for the components still unset. `sourceCmf` decides what the source
   keeps: `keep` (the default) all of it, `drop` none of it, or a list (`[color]`) all but the components it names;
3. for colour, completed by the **material's colour claim**;
4. otherwise **unspecified**: drawn in the display default (OCCT goldenrod, `#DAA520`), and not manufacturable.

Inside a part the more specific sub-shape wins: a face's own over its solid's, a solid's over the part's. The
parameters are ordinary build inputs - keyed, and handed to a script that assigns them - so a variant in another CMF is
built and cached as an item of its own. That is accepted rather than optimised for: parts of one geometry share one
CMF far more often than not.

An **assembly's CMF parameters propagate** to its links as parameter values - colour, material and finish, each for a
link whose own `params:` do not set it and whose item does not state it already - recursively; an imported STEP
assembly writes an instance's overridden CMF as `params:` on that link. An item's own CMF is its own: a variant an
`enrich` fixes stays that variant wherever it is linked, and an assembly only fills in what is left, as a part's
parameters fill in what its source leaves. Either way a
link names the variant its parameters name. But CMF set by an assembly - its own parameters, a link's `params:`, or a
legacy `properties: color:` on it - is a finer-grained way of *drawing* the assembly, not a specification of the items
in it, and it costs the assembly its manufacturability ([section 8](#8-manufacturability)). A colour variant that is
to be made or bought as such is declared as a part - an `enrich` that fixes `color` - and linked by name.

## 6. Storage: inside the BREP

**Built.**

A shape's payload is its BREP followed by a binary **CMF section** and a footer. OCCT's readers read a BREP followed by
anything as the same geometry (verified for `BinTools` and `BRepTools`), so the payload stays a BREP to every reader:
an earlier PartCAD reading a newer cache, the Chili3D end, OCCT's own tools. Geometry and CMF are cached, digested and
shared together; parts of one geometry and one CMF share one entry.

```
payload := brep section footer
footer  := u32 len(section), b"PARTCMF1"                     (little-endian)
section := u16 n, n × (u16 len, utf-8)                       strings: references and origins
           u16 m, m × set                                    the palette
           i32 default                                       the part's own set, -1 for none
           runs(solids), runs(faces)
set     := i32 color, i32 material, i32 finish, i32 origin   string indices, -1 for none
           u8 r, u8 g, u8 b, u8 a                            display colour (sRGB)
           u8 roughness, u8 metallic                         finish display, 0..255 for 0..1
           u8 flags                                          1 colour, 2 roughness, 4 metallic present
runs(x) := u32 count of x, u32 k, k × (u32 length, i32 set)  in TopExp::MapShapes order; -1 for none
```

Sub-shapes are addressed by their index in `TopExp::MapShapes` order, which is stable through PartCAD's codec
(verified for a box, a boolean result and a compound of three solids) and through `wrapper_common.solidify`, which
reuses a shell's faces. A producer hands `ocp_serialize` a mapping keyed by sub-shape identity, and indices are
computed at encode time. An operation that rebuilds faces (sewing, unifying, a boolean) carries CMF through OCCT's
history, or drops it with a warning - never silently.

A part's own CMF - its parameters - is written into the section by the **core**, not by each wrapper: after the part is
built and after any `offset`/`scale` (which rebuilds the payload), the core opens the payload with its bounded reader,
completes or replaces the section as `sourceCmf` says, and compresses it again (`partcad.cmf.apply_declared`). It needs
no kernel - the section is bytes after the BREP - so every part type gets it the same way, whatever built it. It is
applied each time the part is read, from a build or from the cache, and is **not** cached: what it comes to turns on
declarations the shape's cache key does not cover (what a colour's declaration says to draw it in, and later which
declaration claims a name a source uses), and an entry written with one package's answer would be served to another
package sharing the geometry. A part that states no CMF pays one dictionary lookup for it. A payload several nodes carry - the compound a script's components are pieces of - is given one
section, and those components are drawn in the part's own set: their faces are the compound's to address.

Whoever writes a section also records a **summary** in the node's `metadata` - the sets with their face and solid counts, and what
is unspecified - cached with the geometry, for consumers that do not load the CAD kernel: `pc test`, the BOM views, the
IDE's CMF tab. A drawing reads it too, to open a payload's section only where it addresses faces one by one: nearly
nothing does, and a drawing costs what it cost before.

*Rejected:* a separate table on the node (it pays off only when one geometry carries many CMFs, the case not optimised
for, and splits one fact across two places every reader joins); OCCT's XBF document (deterministic, but a different
format to every reader and bound to OCCT versions); one solid per CMF (a painted face is not a solid).

## 7. Conventions and converters

**Built:** the convention, the readers of STEP (through XCAF), build123d, CadQuery, OpenSCAD and 3MF, `set_cmf`, the
lookup by `ids`, `cmfConventions:`, and STEP instance overrides on `pc import`. **Decided:** the `ldraw` reader
([section 10](#10-lego-end-to-end)). **Open:** a converter that has to run code of its own.

**One PartCAD convention.** On a shape, CMF is a palette of sets; each holds a canonical colour, material and finish
reference (each optional), the display values resolved for them, and their origin. Each solid has a material; each
face a colour and a finish, defaulting to its solid's.

**Converters** map another tool's convention into it. `cmfConvention` names one; each type has a default (`step`,
`3mf`, `gltf`, `openscad`, `build123d`, `cadquery`, `ldraw`; `partcad` takes references, as `set_cmf` writes them).
A source's reader - the wrapper that reads its file or runs its script - writes the source's facts into the CMF
section as they were stated, in sets of origin `raw:<convention>`: a colour's RGB and its name where it has one, a
material's designation. The core converts every such set as the part is read, before the part's own parameters
complete it, so nothing outside the core ever sees one. Converting is a lookup by `ids` among the declarations in
scope (the part's own package first, then the convention's `catalogs`), with the case folding the tool uses. A colour
it cannot match becomes the display-only `rgba` of the stated value; a material or finish stays unset, for the
parameters to complete; each is reported once per part. A package declares conventions of its own in
`cmfConventions:` - a variation on a builtin one, with its own `ids` key, `catalogs` and case folding - and a part
names one in `cmfConvention`, which never applies to what `set_cmf` said in PartCAD's own terms. A converter that has to
run code of its own (a tool whose names cannot be matched by a table) would be an implementation a package supplies,
the way file types are under `render:`; none needs one yet.

Built: `partcad` (identity), `step`, `build123d`, `cadquery`, `openscad` and `3mf`; a CSS colour written where a
reference belongs is read as its `rgba` ([section 4](#4-names-and-references)). `gltf` is a convention with no reader
yet, and `ldraw` is partcad-ldraw's to read. Open: telling the CAD tool that wrote a STEP file from its `FILE_NAME`
originating system, and conventions of its own for each of the tools the public index holds STEP files from
(`solidworks`, `onshape`, `fusion`, `inventor`, `creo`, `nx`, `catia`); a package declares such a convention in
`cmfConventions:` meanwhile.

### 7.1 Conventions surveyed

From vendor and standards documentation; *unverified* marks what could not be confirmed from a primary source.

| Source | Colour / appearance | Material | Finish | Occurrence overrides | Variants |
| --- | --- | --- | --- | --- | --- |
| STEP AP214/AP242 (CAx-IF *Model Styling and Organization* v1.10) | `STYLED_ITEM` chains ending in `COLOUR_RGB` or one of 8 pre-defined colours; a face is an `OVER_RIDING_STYLED_ITEM` over its solid; an assembly node's style overrides its parts' | material and density as `PROPERTY_DEFINITION`s; OCCT writes them on the product only | a user-defined attribute (the CAx-IF UDA practice's own example is "surface finish"); AP242 `surface_texture_representation` under `surface_condition` | `CONTEXT_DEPENDENT_OVER_RIDING_STYLED_ITEM`, display data | none |
| OCCT XCAF | `ColorGen`/`ColorSurf`/`ColorCurv` down to faces; `VisMaterial` (PBR) for visualisation | `XCAFDoc_Material`: name, density | none | SHUO instance colours | none |
| SOLIDWORKS | face > feature > body > part, a component's above all | per part or body, from `.sldmat` | custom properties | display states | configurations |
| Onshape | part, face, feature | per part, from CSV libraries | none | none | configurations |
| Fusion / Inventor | appearance over the material's look, face > body | per body; iProperty `Material` | Inventor's Finish feature, per face | design views, display data | iPart members with part numbers |
| Creo / Windchill | `.dmt` appearances | `PTC_MASTER_MATERIAL` (part), `PTC_ASSIGNED_MATERIAL` (body) | none | appearance states | family tables; Options & Variants ("Color") |
| NX / Teamcenter | studio materials apart from physical (*unverified*) | per body | colour, texture and gloss rules | none | an uncoloured part exploded into colour-variant items |
| CATIA / 3DEXPERIENCE | covering material | core material | covering material | none | none |
| Fashion / consumer PLM | colour library records | material-colour palettes | none | none | a colourway is a SKU |
| 3MF | `basematerials`: a name "to convey design intent" and an sRGB `displaycolor` "for rendering purposes only" | the base material | display properties apart from the material | forbidden on components | none |
| glTF 2.0 | material per primitive; linear PBR factors | none | `KHR_materials_*` | needs another mesh | `KHR_materials_variants`, one per SKU |
| OpenSCAD | `color()`, the outer call wins; snapshots with Manifold write it to 3MF, 2021.01 only previews it | none | none | none | none |
| build123d | `.color`, `.label`, `.material` (0.13: a `FinishedMaterial`); innermost wins | as left | as left | none | none |
| CadQuery 2.7 | `Assembly.add(color=…)` | `Material` (wraps `XCAFDoc_Material`) | none | none | a product per (colour, shape) |
| LDraw | a code per triangle; `16` is "the colour that places me" | implied by the code (`RUBBER`) | implied by the code (`CHROME`, `PEARLESCENT`, `METAL`) | none | none |

What this decided: colour and physical material are separate everywhere, and a material may lend a default look;
material sits at part or body level and appearance goes down to faces; occurrence overrides are display data in every
CAD tool, while PLM turns released colour variants into items; precedence differs between tools (outer wins in STEP
assembly styles, OpenSCAD and SOLIDWORKS components; inner wins in build123d, CadQuery and face-over-body everywhere),
so PartCAD keeps one rule and a converter states its source's in it (the `step` converter turns an assembly node's
overriding style into `params:` with `sourceCmf: [color]`); and real identifiers contain spaces, `( )`, `+`, `<` `>`,
`@`, `°`, `µ` and now and then `,` `:` `#` `[ ]`, which is what [section 4](#4-names-and-references) admits and escapes.

## 8. Manufacturability

**Built:** the `cmf` check, as a warning, and `cmf: {require: true}` on an object or a package to make it fail; the
connectivity exemption. **Decided:** making it an error by default.

`pc test` gains a `cmf` check. It is a warning first, an error for packages that opt in next, and an error by default
once the public index passes it - the path `tolerance` took.

- **A part to be made** (manufacturable and not purchased) passes only if every solid has a material and every face a
  colour (a material's colour claim counts), each resolving to a declaration with `manufacturable: true`. A finish
  that is stated must be one too; none stated is as produced. A display-only colour fails it, and so does a
  converter's unmatched colour - a STEP part completes it through its parameters, or replaces it with
  `sourceCmf: drop`, so that every solid and face of a STEP part to be made is specified, by the file or by the user.
- **An assembly that sets CMF** - its own CMF parameters, a link's CMF `params:`, or a `properties: color:` - is
  manufacturable if and only if it declares its own `vendor` and `sku`. A link's CMF-parameterised item counts as a
  non-manufacturable part of it: the CMF is there to draw the assembly, and a specification would have been a part.
- **A purchasable assembly** (one declaring `vendor` and `sku`, or its `enrich`) is judged by its own CMF: its CMF
  parameters are its claim and decide how it is drawn. Neither this check nor the connectivity rule against
  `location:` descends into it, so a wheel sold assembled may place its rim by coordinates and hold a tyre part with no
  material.

## 9. Presentation

**Built:** `pc list colors|materials|finishes`, `pc info`'s CMF section, drawings per face, a glTF material per colour,
and in the IDE the explorer's declarations, the CMF tab, the BOM and Build vs Buy columns and per-primitive colours.
**Decided:** the exports below. **Open:** highlighting a set's faces in the 3D view, drawing a finish's roughness and
metallic, and `pc ide view` of a declaration.

CMF is always shown as its three components in the order colour, material, finish: each by its declaration's name, with
a swatch of its display where the medium allows, marked when it is display-only or unspecified, and with its origin
where there is room.

- **CLI:** `pc list colors`, `pc list materials`, `pc list finishes` list name, display, display-only mark and
  description alike; `pc info` of a part gains a CMF section.
- **IDE explorer:** colours, materials and finishes appear beside the other objects, after them, in that order - the
  daemon's package contents carry `colors`, `materials` and `finishes`, read off the declarations as `pc list` reads
  them, with nothing of another package loaded to list them. A row says the display as written and marks one that is
  display-only. Opening one shows a simplified Digital Thread, as an interface does: the Design tab only, selected and
  not shown, and in it the CMF tab only - one tab is no choice, so neither strip is drawn and the CMF pane is the
  panel. There is nothing for PartCAD to draw, so the extension makes that show itself, with no object in it, and the
  tab asks the daemon by the declaration's kind (`cmf.info`), which is the one thing that finds a declaration: its name
  is no object's. It says the name, a swatch of the display (a material's colour claim; a finish's roughness and
  metallic instead), the description, whether it is a claim or display-only, the canonical reference (an alias
  resolved), the `ids`, the aliases, a parametric declaration's parameters, and the rest of what `pc info` says of it.
  The next object shown goes back to the Design tab that was open before the declaration.
- **IDE Digital Thread:** a CMF sub-tab under Design, beside 3D, 2D and Draft (`pc ide view --design-cmf`), drawn from
  `cmf.info`: for a part its one item, for an assembly or a scene every part it holds and every sub-assembly in it
  bought whole - the items the `cmf` check judges, once each with their count - each with its sets (colour, material,
  finish, each by name with a swatch and a display-only mark, then faces, solids and origin), what is unspecified, and
  what keeps it from being specified in the check's own words; the incomplete ones first, and above them what an
  assembly sets itself. The daemon orders and judges them, by `partcad.test.cmf`; the tab draws. It builds what it
  reports on, as `pc test` does, which the 3D view beside it has done already. The BOM and Build vs Buy views get Color,
  Material and Finish columns (the Material column Build vs Buy had becomes the three), from a `cmf` on each line item
  and tree node: the summary recorded with the item's geometry where it has been built, and what it declares otherwise
  (`partcad.cmf.own_info`, marked `declared`) - nothing is built to fill a column. The 3D view keeps each primitive's
  own colour: a primitive whose glb gives it a material is drawn in that colour, with the viewer's own material and so
  its shading, the Opacity slider and the flicker, and one with none keeps its node's colour as before. *Open:*
  highlighting a set's faces in the 3D view when it is chosen (the glb has a mesh per colour, not per set, so sets of
  one colour cannot be told apart); a finish's roughness and metallic in the 3D view (neither the glb nor the
  viewer's Phong material carries them); and `pc ide view` of a declaration, which `inspect.object` does not know as an
  object, as the explorer's show is made by the extension rather than sent by PartCAD.
- **Drawings:** SVG, PNG and JPEG draw each face in its display colour, still as one hidden-line drawing; an edge
  between two colours is drawn once per colour, the later on top. A drawing is on white, so a colour too light to see
  there (relative luminance above 0.5; goldenrod is 0.42) is drawn darker, hue kept: a white face is drawn in grey
  lines rather than invisible ones.
- **glTF:** the faces of one colour are one mesh with that colour's material, so a part of one colour is still one
  primitive; the IDE draws each such primitive in its own colour (above).
- **Exports:** STEP through XCAF - product structure and names, sRGB colours on faces, solids and products, materials
  with density on products and, where a part has several, per solid as user-defined attributes on shape aspects
  (the CAx-IF practice), finishes and PartCAD's references as user-defined attributes. glTF: a material per set. 3MF:
  base materials with display colours, per triangle. URDF and MJCF: one visual or geom per set. STL warns.
- **Documentation:** `docs/source/digital_thread/lifecycle/design_cmf.rst` explains the model;
  `docs/source/config_cmf.rst` is the configuration reference for the three sections; the parts and assemblies
  references describe the CMF parameters once, and link to them.

## 10. LEGO, end to end

**Decided.**

- **partcad-ldraw declares LEGO's colours**: the `LEGOID` entries of LDraw's `LDConfig.ldr` (185 of 322), named as LEGO
  names them (`LEGOID 194 - Medium Stone Grey` for LDraw's code 71), with `ids` for LEGO, LDraw, BrickLink and
  Rebrickable and LDraw's value as `display`; and the materials and finishes its codes imply (ABS, polycarbonate for
  transparent colours, rubber; chrome, pearlescent, metallic). An LDraw code is a CMF triple: `256` is LEGO's black in
  rubber. Codes with no LEGO id are not declared as manufacturable colours.
- **The `ldraw` converter** turns each triangle's code into a triple. The wrapper carries codes per triangle (LDraw's
  inheritance of `16`), merges coplanar faces only within a code, and leaves top-level `16` unset for the part's `color`
  to complete. The XL motor, the IR receiver and the IR remote, which stayed one colour before, come out in theirs.
- **Shortcuts** are assemblies whose `color` propagates to their `16` parts; a part the shortcut's file draws in a
  fixed colour gets its own `params:`. A shortcut LEGO sells whole declares `vendor`/`sku`, and its CMF is its claim.
- **The examples** declare aliases of LEGO's colours and the variants they use as parts (`enrich` fixing `color`), and
  link those; the LEGO stores order by (design, LEGO colour id).

## 11. Specifications

Requirements use SHALL; each is pinned by the scenarios under it.

### 11.1 Declarations

**Requirement: three kinds of one declaration.** `colors:`, `materials:` and `finishes:` SHALL declare CMF
declarations addressed as `<package>:<name>`, sharing `desc`, `url`, `display`, `ids`, `manufacturable` (true unless
stated), `parameters`, `aliases`, and `type: alias` with `source`.
- *Scenario:* a package declares a colour, a material and a finish → `pc list colors|materials|finishes` list them with
  the same columns.

**Requirement: a display is a hint, a declaration is a claim.** A colour's display SHALL be any CSS colour or a
reference to another colour declaration; a display SHALL NOT make anything manufacturable.
- *Scenario:* a vendor colour declares `display: ":other"` → it is drawn in the other's display and is manufacturable
  as the vendor's own claim.
- *Scenario:* `display` written as `#c91a09`, `rgb(201 26 9)`, `hsl(4 91% 41%)` or `firebrick` → each reads as the sRGB
  CSS Color Level 4 defines for it.

**Requirement: parametric declarations.** A declaration SHALL take `parameters:`, and its string fields SHALL name them
as `%name%`.
- *Scenario:* `//pub/std/color:rgba;color=C91A09FF` → drawn in `#C91A09`, not manufacturable.

**Requirement: aliases.** A reference through `type: alias`, or through a name in `aliases:`, SHALL resolve to the
target, and the target's canonical reference SHALL be what enters an item's name.
- *Scenario:* `stone: {type: alias, source: "//vendor:Medium Stone Grey"}`, and a link with `params: {color: ":stone"}`
  → the item is named with `color=//vendor:Medium Stone Grey`, the same item another alias of it names.

**Requirement: texture is reserved.** No declaration SHALL state `texture`.

**Requirement: the standard catalogue.** `//pub/std/color` SHALL declare the parametric display-only `rgba`, and SHALL
NOT declare any colour standard.

### 11.2 Names

**Requirement: names as specifications write them.** A CMF declaration's name SHALL be any text without leading or
trailing whitespace. A reference SHALL carry `: ; , = # % * ? [ ]` percent-encoded; the parser SHALL split first and
decode after; a name PartCAD writes SHALL be spelled as it was wherever it could be written before.
- *Scenario:* a colour named `PA12, glass filled` → referenced as `:PA12%2C glass filled`, shown as written.
- *Scenario:* `bends;include=BEND_UP,BEND_DOWN` and `obj;m=//pub/std:air` → spelled exactly as before.

### 11.3 Assignment

**Requirement: sources and parameters only.** A part's CMF SHALL come from its source, converted by `cmfConvention`,
and from its CMF parameters, which fill what the source leaves unset (`sourceCmf: keep`), replace it (`drop`), or
replace the components listed. An ASSY link SHALL affect CMF only through its `params:`.
- *Scenario:* a STEP file colours one of two solids and the part declares `color` → the other solid takes it.
- *Scenario:* `sourceCmf: [color]` and `color` → every face takes the declared colour, every solid keeps the file's
  material.

**Requirement: every type.** `color`, `material`, `finish`, `sourceCmf` and `cmfConvention` SHALL be accepted by every
part and assembly type; `tolerance` only by the homogeneous ones.
- *Scenario:* a `step` part declares `material` → accepted.

**Requirement: propagation.** An assembly's CMF parameters SHALL be passed to its links for those the link's `params:`
do not set, recursively.
- *Scenario:* a wall linked with `params: {color: ":stone"}` holds bricks linked with none → every brick is
  `brick;color=<stone, canonical>`; one link inside saying `color: ":red"` is red.
- *Scenario:* the same wall holds `red-brick`, an `enrich` of `brick` fixing `color: ":red"` → it stays `red-brick`.

**Requirement: STEP instance overrides.** An imported STEP assembly SHALL write an instance's overridden CMF as that
link's `params:`, inventing no part name, and SHALL write each part's file with the colours and material its definition
states.
- *Scenario:* a red brick placed twice, one instance overriding its colour to blue → one part file, red; the second
  link `params: {color: <blue, converted>, sourceCmf: color}`.

**Requirement: inside the BREP.** A payload SHALL be its BREP followed by the CMF section of [section 6](#6-storage-inside-the-brep);
a reader that does not know the section SHALL read the same geometry.
- *Scenario:* two parts of one geometry and one CMF → one payload; a third in another colour → its own.

**Requirement: scripts and OpenSCAD.** The build123d and CadQuery wrappers SHALL keep `.color` (display-only unless
`set_cmf` names a declaration), `.material` and `.label` per shape and sub-shape, `cq.Assembly` colours and
`show_object` colour options; scripts SHALL be handed `set_cmf(shape, color=…, material=…, finish=…)`. OpenSCAD parts
SHALL be exported as coloured 3MF where the OpenSCAD in use writes colours (told by its version: the snapshots since
2024), and as before everywhere else. A STEP part SHALL be read through XCAF into the geometry the plain reader read.
- *Scenario:* a script sets one face's colour and the part declares another → that face keeps its own, the rest take
  the part's.

### 11.4 Conventions

**Requirement: one convention.** A shape's CMF SHALL be a palette of sets (colour, material, finish references with
display values and origin); material per solid, colour and finish per face with the solid's as default; display
colours sRGB.
- *Scenario:* a source states a material on a single face → it is assigned to the solid where the whole solid agrees,
  and reported otherwise; no material per face is invented.

**Requirement: converters by `cmfConvention`.** Converters SHALL be the builtin conventions or a package's
`cmfConventions:`, mapping names through `ids` within scope, turning an unmatched colour into display-only `rgba`, and
leaving an unmatched material or finish unset, each reported once per part. `cmfConvention` SHALL NOT apply to what
`set_cmf` states.
- *Scenario:* a STEP face coloured RGB (0.8, 0.1, 0.05) with no matching name → `//pub/std/color:rgba;color=CC1A0DFF`
  and a warning.

**Requirement: a source's precedence is stated, not inherited.** A converter whose source uses another precedence
SHALL state the source's intent in PartCAD's.
- *Scenario:* a STEP assembly node's overriding style → `params: {color: …, sourceCmf: [color]}` on the link.

**Requirement: LDraw codes are triples.** The `ldraw` converter SHALL map a code to a colour, a material and a finish,
and leave `16` unset.

### 11.5 Manufacturability

**Requirement: a part to be made.** Every solid SHALL have a material and every face a colour (a material's claim
counts), each a declaration with `manufacturable: true`; a stated finish SHALL be one too; no finish is as produced.
- *Scenario:* faces coloured `//pub/std/color:rgba;…` → the `cmf` check fails, saying the colour is display-only.

**Requirement: a STEP part to be made.** Its file's CMF, completed or replaced by its parameters, SHALL be complete.

**Requirement: CMF an assembly sets.** An assembly that sets CMF (its own CMF parameters, a link's CMF `params:`, a
`properties: color:`) SHALL be manufacturable if and only if it declares its own `vendor` and `sku`.
- *Scenario:* a manufacturable assembly links a part with `params: {color: ":red"}` and has no `vendor`/`sku` → it is
  reported not manufacturable, naming the link.

**Requirement: a purchasable assembly.** An assembly declaring `vendor` and `sku` SHALL be judged by its own CMF, and
neither the CMF check nor the connectivity rule against `location:` SHALL descend into it.

**Requirement: in stages.** The check SHALL be a warning first, and an error for an object or a package declaring
`cmf: {require: true}`.

### 11.6 Presentation

**Requirement: one presentation.** CMF SHALL be shown as colour, material, finish - name, swatch, display-only and
unspecified marks - in the IDE's CMF tab, the BOM and Build vs Buy views, `pc info`, `pc list`, and the generated
documents.
- *Scenario:* an assembly holding a part that states nothing and a part that is specified → its CMF tab lists the
  first before the second, saying "no colour on any face" of it.
- *Scenario:* a part that is not built yet → its BOM line shows the colour, material and finish it declares, marked as
  declared, and nothing is built to show them.

**Requirement: the explorer.** A colour, material or finish opened from the IDE's explorer SHALL show the Digital
Thread with the Design tab only, selected and not shown, and only its sub-tabs.
- *Scenario:* a package declares `colors:` → the explorer lists them after its objects; opening one shows its CMF tab
  alone: its swatch, whether it is a claim, its canonical reference and its `ids`.

**Requirement: a primitive's own colour.** The IDE's 3D view SHALL draw a primitive in the colour its glTF material
gives it, with the viewer's own material, and a primitive with no material in its node's colour.
- *Scenario:* a part with one face coloured `#C91A09` → that face's mesh is drawn `#C91A09`, the rest in the part's
  colour, and the Opacity slider fades both.

**Requirement: drawings and exports** as [section 9](#9-presentation) lists.
- *Scenario:* a part with per-face CMF exported to STEP and read back with the `partcad` convention → the same
  references on every face and solid.

## 12. Decisions taken in review

1. No `<part>@<style>` names: STEP instance overrides are link `params:`, and CMF parameters are one mechanism for part
   and assembly types.
2. User parameters complete a STEP file's CMF; every component of a STEP part to be made ends up specified;
   `sourceCmf: drop` replaces the file's.
3. Both bare and full references; for LEGO, partcad-ldraw declares the vendor's colours and consumers reference them
   through aliases; external names are kept, escaped where the parser needs it.
4. CMF stays declarable on assemblies with `vendor` and `sku`, as their claim and their look.
5. A claim differs from a display colour; CMF declarations take parameters and `manufacturable:`, counted by the checks.
6. CMF set in assembly nodes costs the assembly its manufacturability unless it declares `vendor` and `sku`: it is a
   finer-grained way of drawing, not of specifying. A link's CMF-parameterised item counts as a non-manufacturable part.
7. `texture` stays reserved for a later, visualization-only change.
8. The CMF section is binary. No finish stated is as produced, implied. Converters come in the order of
   [section 7](#7-conventions-and-converters).
9. No colour standard ships in any PartCAD repository, for licensing reasons; packages declare the ones they use.
10. CMF declarations open in the IDE's explorer with a Design-only Digital Thread, as interfaces do.

## 13. Roadmap

| Step | Status |
| --- | --- |
| Declarations, CSS display, names and escaping, canonical references, CMF parameters on every type, a part's declared colour drawn, `pc list colors\|finishes` | built |
| The CMF section inside the BREP, its summary, the parameters written into it by the core, drawings and glTF per face, `pc info` | built |
| Assembly propagation, the visualization-only rule, the `cmf` check (as a warning) | built |
| STEP via XCAF; scripts and OpenSCAD as sources; converters; `pc import` keeping CMF | built |
| IDE: explorer, CMF tab, BOM columns, per-primitive materials | built (highlighting a set's faces, and a finish's look in 3D, open) |
| Exports: STEP via XCAF, glTF, 3MF, URDF/MJCF | decided |
| `//pub/std/color:rgba` in the index; LEGO in partcad-ldraw and its examples | decided |
| A visual `texture` | open |
