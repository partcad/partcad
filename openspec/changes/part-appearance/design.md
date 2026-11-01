## Context

**What a product's appearance is, outside PartCAD.** In a PDM/PLM system, appearance is specified the way
material is: on the item, as part of what the item *is*.

- Industrial design writes it as a CMF specification:
  - **colour**: a named standard such as RAL 3020, a supplier's colour number, or LEGO's colour 21 "Bright
    Red";
  - **material**: a grade;
  - **finish**: gloss level, anodise type, a mould texture such as VDI 3400 Ref 27.
- A part made in two colours is two items with two numbers. LEGO says it outright: an *element* is a design
  in a colour, and is what is sold.
- The CAD file the part is defined by carries the visual side of that specification, scoped to the geometry
  it applies to:
  - STEP AP214/AP242 attaches `STYLED_ITEM`s to products, solids and faces;
  - a material designation (with density) to solids.

  OCCT reads all of it into an XCAF document: `XCAFDoc_ColorTool` (generic/surface/curve colours on shapes and
  sub-shapes), `XCAFDoc_VisMaterialTool` (PBR visual materials), `XCAFDoc_MaterialTool` (physical materials),
  and `XCAFPrs::CollectStyleSettings` (resolves which style each sub-shape ends up with).
- Mesh formats carry the same per-face facts: 3MF base materials and colour groups per triangle, glTF materials
  per primitive, OBJ `usemtl` per face group.
- LDraw states a colour code on every triangle, and code `16` means "the colour of whatever places me".

**What PartCAD does today** (facts found on `devel`, 0.8.273):

| Where | What happens to appearance |
| --- | --- |
| `wrappers/wrapper_step.py` | `STEPControl_Reader`: every colour, material and name in the file is discarded. |
| `wrappers/step_metadata.py` | Reads layers and user properties as text; notes that XCAF would give colours, and does not ask. |
| `wrappers/wrapper_import_assy.py` | `STEPCAFControl_Reader` for structure and names; colours not read. |
| `wrappers/wrapper_import_gltf.py` | `RWGltf_CafReader` into XCAF, then written to STL: materials discarded. |
| `part_factory_3mf.py`, `wrapper_obj.py` | Geometry only. |
| `builtin/export/export_step.py` | `STEPControl_Writer` of the flattened compound: no names, colours, materials or structure. |
| `builtin/export/export_3mf.py` | `cq.exporters`, no colour. |
| `wrappers/wrapper_gltf.py` | Already builds an XCAF document and writes it with `RWGltf_CafWriter`: the obvious place to put colours, empty today. |
| Shape envelope | `properties.color` per node: one colour per part or assembly, inherited downward (`wrappers/appearance.py`). |
| IDE (`webview/scene.ts`) | Paints each node one appearance, overriding every glTF material. |
| `color` parameter | Accepted only by homogeneous types (`PartFactoryHomogen`, correct), "not implemented yet", not promoted to `properties`, hashed like geometry, handed to scripts. |
| Cart / providers | `get_mcftt("color")` reads the parameter as an item attribute; providers match it as a free string, with `TODO: resolve cart_item.color as a color object`. |
| partcad-ldraw `ldraw.py` | Ignores the colour field of every line. |

Two facts the design rests on were checked here and not assumed:

- **Face order is stable.** `TopExp::MapShapes(shape, TopAbs_FACE)` yields the same order before and after
  `ocp_serialize.compressed_brep` → `shape_from_payload`. This held for a box, a boolean result, and a compound
  of three solids, and the face count is unchanged after `Moved()`.
- **`wrapper_common.solidify` reuses the shell's faces**, so face identity survives the step every wrapper
  output goes through.

The pinned OCP provides `STEPCAFControl_Reader/Writer`, `XCAFDoc_{Color,VisMaterial,Material,Layer}Tool`,
`XCAFPrs::CollectStyleSettings`, `XCAFDoc_MaterialTool::GetDensityForShape`, `RWGltf_CafReader/Writer` and
`BinXCAFDrivers`. It does **not** provide `RWObj` or
`RWPly`.

## Goals / Non-Goals

**Goals:**

- Appearance is a fact about an item, stated by the item's definition, and every consumer of the item sees the
  same appearance.
- Per-face and per-solid appearance, read losslessly from colour-defining formats, and written back losslessly
  to the ones PartCAD exports.
- A part in a colour is an item of its own in the BOM and in procurement. Its geometry is built and cached
  once for all its colours.
- Colours are specified, not just displayed: a catalogue entry a supplier can be handed, with a display value
  for drawing it.
- A manufacturable part's appearance is complete.
- The core stays free of the CAD kernel. Every step is additive and released before anything is retired.

**Non-Goals:**

- Image textures and UV mapping. Finish and texture keep reserved places in a style (D10) but are not drawn.
- Physically based rendering in `pc render`. Line drawings get colours, not lighting.
- Colour on an assembly link, now or later (D1).
- Making a multi-colour part out of a format that does not define colours (scripts, STL, SCAD). That is what
  rules such a part out of being manufacturable.
- Changing how `material` reaches scripts or the cache key. It stays a geometry input, because a script may
  legitimately make a part thicker in a softer material.

## Decisions

### D1. Appearance is stated by the part, never by a link

A link in an ASSY file names an item. It never changes what that item is. A red brick and a blue brick are
different items, and an assembly that needs both links both.

*Why:* everything downstream of the assembly keys on the item:

- the BOM groups by `<package>:<name>` (`Assembly._get_bom_real`);
- `pc supply` asks a store about that item;
- `get_mcftt` answers for that item;
- a STEP export writes one product per item.

An appearance hung on the link is invisible to all of them. The castle in partcad/partcad#889 rendered red and
grey and still listed "Brick 1 x 2 x 153", which is not a buildable bill of materials.

*Alternatives rejected:*

- **Link `color:`** (#889): the reasons above. It also cannot colour one face.
- **STEP-style instance overrides as a first-class concept.** XCAF can set a colour on an assembly instance.
  But PDM treats such overrides as display state, not as item data, and they do not survive the systems that
  exchange STEP. Importing them is still needed: see D9 for what becomes of one.

*What remains legitimately "per placement":*

- *views* derived for documentation, such as the instruction book's highlight of the current step
  (`assembly_guide.py` stamps `properties.color` on a derived, uncached node) and interference artifacts;
- *display fallbacks* inherited from an assembly's own `properties.color`.

Neither is product data. A view is not an item, and an inherited display colour never counts as a part's
appearance for manufacturability (D7).

### D2. Two sources of a part's appearance, and no third

1. **File-defined**: from a colour-defining format the part is read from. Per face and per solid, with the
   format's own inheritance (a face without a style takes its solid's, then its product's).
2. **Declared**: one colour for the whole part, through the `color` object-type parameter. Two kinds of type
   accept it:
   - the built-in types that produce one homogeneous body (`stl`, `cadquery`, `build123d`, `sdf`, `scad`,
     `extrude`);
   - a package-supplied partType that declares it does (a new `accepts: [color]` in its `partTypes:` entry).
     The colour is then the format's own "main colour": `:ldraw` declares it for LDraw's code `16` (D11).

   `step` keeps rejecting it: the file is authoritative, and a STEP file with no colours at all is still given
   its single colour as `properties: color:`, as today.

A face the file leaves uncoloured falls through to the declared colour. That is XCAF's own rule (a sub-shape
without a colour shows its parent's), so the result is what any STEP viewer shows.

*Why only two:* this is your rule made mechanical. Multi-colour exists only where a file defines it, so a part
defined any other way has at most one colour. It also fits the factory rule PartCAD already has
(`PartFactoryHomogen`: "one material, one colour, one manufacturing tolerance" for one homogeneous body) rather
than adding a new one. Scripts do not get a way to colour faces: a build123d `.color` on a sub-shape is ignored
and warned about, because a scripted part is one homogeneous body by definition.

### D3. Per-face appearance travels beside the BREP as an index table

A shape node gains an optional `appearance` entry:

```yaml
appearance:
  styles:                       # the palette, each style once
    - {color: "#C91A09", ref: "//pub/universe/lego/color:red"}
    - {color: "#1B2A34", ref: "//pub/universe/lego/color:black", finish: matte}
  faces: [[0, 12], [-1, 3], [1, 40]]   # run-length (style, count) in TopExp face-map order; -1 = none
  solids: [-1]                  # optional: style per solid, TopExp solid-map order
```

- It is produced by the wrapper that reads the file, in the process that has the shape live.
- It is encoded by `ocp_serialize.encode_shape` from a face→style mapping keyed by face identity: indices are
  computed at encode time, so a producer never handles indices.
- It is stored in the same cache entry as the geometry, as `metadata.sections` already is. The file defines
  both, and the same hash covers both.
- The core carries it opaquely. Placing a node (`shape_envelope.placed`) composes locations and never touches
  it, because a location moves faces without reordering them.

*Why indices beside the BREP:*

- it keeps the BREP the payload everything already exchanges, caches, deduplicates and shares by digest;
- it keeps the core kernel-free;
- an envelope without the key means exactly what it means today;
- face order through PartCAD's own codec was verified stable.

*Alternatives rejected:*

- **XCAF documents (XBF) as the payload.** This would be lossless and is OCCT's native model. But every
  consumer changes at once (cache, sharing, digests, glTF form, the IDE, the daemon protocol). XBF is a binary,
  OCCT-version-bound format, and the core would need the kernel to look inside a node. XCAF is the right model
  at the *edges*, for reading and writing files (D9), not as PartCAD's storage.
- **One solid per colour** (split a two-colour part into two shapes). This changes the item's structure: a
  two-shot moulding is one manufactured part, not two. It breaks mass per item and manufacturability. And a
  label or a groove is a face, not a solid.
- **Colours in `properties`.** Properties are per node and declared, so they cannot address a face, and
  putting file-derived facts there would mean writing the file's content into the declaration.
- **Per-triangle colours on a tessellation.** This loses the exact faces, does not survive re-meshing at
  another tolerance, and cannot be written back to STEP.

### D4. One resolution order, in one place

The appearance of a face is the first of:

1. its face style;
2. its solid's style;
3. the part's declared colour (D2/D5);
4. its material's natural appearance (D7);
5. the display default, OCCT goldenrod (`#DAA520`).

Steps 1-4 make a face *specified*. Step 5 is a picture of "nobody said".

An assembly's own `properties.color` sits between 4 and 5 as a display fallback only (D1). This keeps
uncoloured parts of imported URDF/MJCF trees looking as their source drew them, without ever making those
parts specified.

`wrappers/appearance.py` is the single implementation, and `ide/vscode/src/webview/appearance.ts` its tested
twin, as `DEFAULT_COLOR` already is. Every renderer, viewer and exporter calls it. None decides on its own.

### D5. A colour variant is a distinct item that shares one geometry

`//pub/universe/lego/ldraw/Brick:3004;color=red` is an item: its own name, its own BOM line, its own `pc supply`
question. An `enrich` that fixes `color` is the same item under a name of the package's choosing
(`config_bom.rst`: an enrich "makes an opinionated version of an existing part by fixing some of its
parameters"). ASSY files link either one. That is already how PartCAD names a parametric variant
(`holes=30,40`), so nothing new is needed for identity.

Geometry is shared across colours by three changes to the `color` object-type parameter:

- **It is consumed by PartCAD, not handed to the geometry producer.** `custom_cqgi` stops passing it; wrappers
  never see it.
- **It is excluded from the geometry cache key.** This is safe *only because* of the point above: nothing that
  builds geometry can read it. That is the condition the deny-list in `shape.py` (`_NON_GEOMETRIC_CONFIG_KEYS`)
  states for leaving a key out ("missing one that does matter serves the wrong shape").
- **It is promoted** into the part's declared colour (`OBJECT_TYPE_PARAMETER_PROPERTIES` gains `color`, with
  the conversion D6 provides). It is applied when the node is stamped (`get_cache_metadata`), as `properties`
  are today, so a cache hit and a fresh build agree.

LEGO's 1 x 1 brick has been made in 177 colours. Under this rule that is one mesh and 177 items, and that is
the point.

*Alternatives rejected:*

- **Keep hashing it.** 177 builds of one shape, and "properties are outputs" is violated in reverse.
- **Keep handing it to scripts and exclude it from the key.** A script that branches on colour would be served
  another colour's geometry, silently: the exact failure the deny-list exists to prevent.

### D6. Colours are catalogue objects; a literal is display-only

A `colors:` section, addressed as `<package>:<name>` like `materials:`, resolved by the same lookup
(`material.py`'s `:name` → own package):

```yaml
colors:
  red:
    value: "#B40000"          # display sRGB, optional alpha; what is drawn
    desc: LEGO Bright Red
    ids: {lego: 21, ldraw: 4, bricklink: 5, rebrickable: 4}
  traffic-red:
    value: "#C1121C"
    ids: {ral: "3020"}
```

- A `color` parameter value is a reference (`//pub/std/color/ral:traffic-red`, `:red`).
- A bare name is looked up in the part's own package. This is how a plugin-served package such as
  `//pub/universe/lego/ldraw/Brick` offers `color=red` (open question 3).
- A literal `#RRGGBB[AA]` is accepted and drawn. It names no colour a supplier can be asked for, so a
  purchased item with one is quoted as today ("cheapest colour") with a warning.
- The cart hands providers the resolved object (name, value, ids), which closes the `TODO` in
  `plugin_factory_provider_manufacturer.py`. The LEGO stores then order the element for (design, colour)
  instead of quoting the cheapest colour.

*Why objects:* a manufacturer is asked for RAL 3020, not for `#C1121C`. sRGB is how a colour is *drawn*, and
several specifications draw alike. Materials made this move already, for the same reason: a string nobody
resolves cannot be matched, priced or checked.

*Alternatives rejected:*

- **Free-form strings** (status quo): unmatchable.
- **Colour folded into material objects** ("ABS Bright Red"): it multiplies the material catalogue by the
  colour catalogue, and providers already model colours *per material* (`caps.materials[m].colors`).

### D7. Appearance is part of manufacturability; materials have a natural appearance

- Material objects gain an optional `appearance` (a colour reference or literal, and a finish): aluminium is
  aluminium-coloured, PLA has none.
- A part that is to be made (manufacturable and not purchased) passes the new `appearance` check of `pc test`
  only if every face resolves through steps 1-4 of D4.
- A purchased part is not checked here. Its colour is part of what is ordered (D6), and `pc supply` says so.

It is introduced as a warning, made an error for packages that opt in, and made the default after the index
is migrated. This is the same path `tolerance` took (`pc test` fails a part to be made that states none).

*Why material appearance counts:* an unpainted machined part is specified by its material and finish, and
demanding a colour for it would be a rule people satisfy with a meaningless value.

### D8. Producers assign by face identity, and carry it through what they do

A producer builds a `{TopoDS_Face: style}` mapping on the final shape. Any operation that replaces faces must
carry the mapping through OCCT history (`BRepBuilderAPI_Sewing`, `ShapeUpgrade_UnifySameDomain`, booleans:
`Modified()`/`Generated()`), or drop the affected faces' styles *with a warning*. Silently losing them is not
allowed.

Merging coplanar faces must only merge faces of one style. That matters for partcad-ldraw's
`_merge_coplanar`, and for any post-processing `wrapper_common.finished` grows later. `solidify` already keeps
faces.

### D9. XCAF at the edges: STEP (and glTF) in and out

**In (STEP part).** `STEPCAFControl_Reader` with colour, name, material and layer modes.
`XCAFPrs::CollectStyleSettings` gives each sub-shape its resolved style (with `XCAFDoc_VisMaterialTool` for PBR
materials), and each style becomes a palette entry. A STEP colour is a literal
(`#RRGGBB`), since STEP carries no colour specification. A colour name the file states (AP242
`colour_specification` names) is kept as the style's `name` for display. XCAFDoc materials (name, density)
become per-solid physical materials. Layers and properties keep coming from `step_metadata`.

**In (STEP assembly).** Each product's own styles become its part's appearance. An instance-level override
(XCAF instance colour, or a context-dependent over-riding styled item) becomes a *variant* part, named
`<part>@<style>`, with a warning. The data is kept, and the invariant of D1 is kept: the override names a
different item (open question 1).

**Out (STEP).** The exporter builds an XCAF document from the shape tree:

- one product per distinct item, one instance per placement (the tree's own dedup);
- names from `name`/`label`;
- face and solid styles from the appearance table;
- the part colour on the product;
- physical materials on solids.

It writes with `STEPCAFControl_Writer`. This also fixes the flattening the exporter does today.

**Out (glTF, IDE).** `wrapper_gltf.py` already builds an XCAF document. It gains sub-shape colours, so
`RWGltf_CafWriter` emits a material per style. Whether `SetMergeFaces(True)` merges only faces of one style
must be verified; if not, merging is done per style. The IDE paints a primitive with its own material when it
has one, and the node's appearance otherwise.

**Others.**

- **3MF out:** lib3mf base materials per triangle from face styles.
- **3MF, glTF, OBJ+MTL in:** follow, mapping per-triangle materials to the faces the mesh→solid conversion
  makes. This build of OCP has no `RWObj`, so OBJ is read with a small MTL reader of PartCAD's own.
- **URDF/MJCF out:** one visual or geom per style of a multi-colour part, since those formats colour per
  visual.
- **STL:** colourless by format; a coloured part exported to STL warns once.

### D10. The style has room for finish and texture, which are specifications

In manufacturing, *finish* and *texture* are specifications (an anodise type, a VDI 3400 or Mold-Tech texture),
not images. A style may name a finish object (`finishes:`, mirroring `colors:` and closing the provider's
second TODO) and a texture designation. Rendering uses only the colour now. A finish may later contribute
PBR roughness and metallic values to the glTF material. Image textures are a non-goal.

### D11. The LEGO examples on this model

**partcad-ldraw, wrapper `ldraw.py`:**

- carries each triangle's resolved LDraw colour code through the meshing pipeline, with inheritance per the
  LDraw spec: `16` takes the placing line's code, and `24` is edges only;
- merges coplanar faces only within one code, and gives a face it authors (a capped hole) its neighbours'
  code;
- emits faces of the top-level `16` with no style, so they inherit the part's `color`. Every other code
  becomes a style referencing `//pub/universe/lego/color:<name>`.

A plain brick is one style-less mesh. A printed tile or an XL motor has fixed-colour faces beside its
main-colour ones. That answers the motor, receiver and remote that stayed one colour in the first attempt.

**partcad-ldraw, repository plugin:**

- `//pub/universe/lego/color` is a colour catalogue generated from `LDConfig.ldr`: value, alpha, and LDraw and
  LEGO ids (the extraction from partcad-ldraw#23 is reused);
- the `:ldraw` partType declares `accepts: [color]` (D2), so every part takes a `color` that is a reference
  into that catalogue and fills in for `16`;
- a shortcut is an assembly with a `color` parameter, passed down as `params: {color: "{{ color }}"}` to the
  parts its file draws in `16`. The parts it draws in fixed colours are linked as those variants
  (`Tyre:41897;color=black`).

This is variant selection, not a link colour: each link names an item.

**partcad-ldraw-examples:** the castle and the car declare their variants as `enrich` parts
(`brick-1x2-light-bluish-grey`, …) and link those, so the BOM reads as a buildable list. `pc supply` asks for
LEGO elements in the right colour. Generators emit the `parts:` block and the links; no ASSY file states a
colour.

## Why this is the right approach for PartCAD

- **It matches the source of truth.** Real parts arrive as STEP files with appearance per face and per body.
  The model here is XCAF's own (face → solid → product, with inheritance), so reading a STEP file and writing
  it back loses nothing, and every other format is a subset of it.
- **It matches item identity.** Colour is part of what an item is, so it lives where identity lives: in the
  part's definition and its name. The BOM, procurement, manufacturability and documentation read the item
  and get the same answer. An assembly cannot give a part an appearance its definition does not have.
- **It matches PartCAD's own architecture** rather than adding a parallel one:
  - the homogeneity rule (`PartFactoryHomogen`) and the MCFTT object-type parameters already decide who may
    declare one colour;
  - materials-as-objects is the model for colours, and the provider TODOs already ask for it;
  - `enrich` and parametric names already express variants;
  - `metadata.sections` already carries file-derived data beside the BREP;
  - the cache deny-list states the exact condition (D5) under which colour may leave the key.
- **It costs what it should.** One mesh per shape regardless of colour count. A kernel-free core. An optional
  envelope key that older code ignores. A phased rollout in which each PR is additive and useful on its own.

## Risks / Trade-offs

- **Face indices are only as stable as the faces.** Mitigation:
  - indices are computed at encode time from identity (D8);
  - a test pins face-order stability through the codec, `Moved`, `Located` and the cache;
  - an operation that reorders faces without history fails that test rather than recolouring silently.
- **An edge between two colours in a line drawing.** HLR yields the edge once per colour group that contains
  one of its faces. Both are drawn, the later group on top. Acceptable for a line drawing; documented.
- **Table size.** LDraw parts have thousands of faces. The run-length encoding keeps a one-colour part at one
  run, and the table rides in an entry that already holds the BREP.
- **Every STEP part is re-read once.** `wrapper_step.py`'s `CACHE_VERSION` moves. `STEPCAFControl_Reader` is
  slower than `STEPControl_Reader` (it also transfers styles); the first PR measures it on the index's largest
  STEP files.
- **Checked-in renders change.** Every image of a part whose STEP file has colours, or whose material gains an
  appearance, changes. Each such PR re-renders and commits them, and the `Examples (PartCAD)` job holds it to
  that.
- **Scripts that read `color` stop receiving it.** A deprecation warning ships first; the index is audited
  for such scripts before the retirement release.
- **Colour standards' licensing.** RAL Classic numbers and published sRGB approximations can ship in
  `//pub/std/color`. Pantone values cannot, and are left to users' own catalogues.

## Migration Plan

Each phase is a pull request (or a few), additive, released before the next depends on it:

1. **Envelope and resolver.** `appearance` key, `wrappers/appearance.py` resolution order, SVG per-face groups,
   glTF sub-shape colours, IDE per-primitive materials. No producer yet, so nothing visible changes. Withdraw
   #889.
2. **STEP in.** XCAF reader for parts; component styles and instance-override variants for STEP assemblies.
   Re-render `examples/` where STEP colours appear.
3. **Colour catalogue and the `color` parameter.** `colors:` section and lookup; promote the parameter; keep it
   out of the key and away from scripts (with a deprecation warning for scripts that assign it); cart and
   providers resolve objects. Index: `//pub/std/color` (RAL Classic, basic web colours for migrating
   free-form names).
4. **Exports.** STEP via XCAF (structure, names, colours, materials), glTF materials, 3MF materials,
   URDF/MJCF per-style visuals.
5. **Manufacturability.** Material `appearance`; the `appearance` check as a warning, then opt-in error.
6. **LDraw.** partcad-ldraw wrapper and plugin (D11), then partcad-ldraw-examples. CI there goes green only
   after phases 1, 3 and 6 are released and the index pins the new partcad-ldraw.
7. **More readers.** glTF, 3MF and OBJ+MTL appearance in.
8. **Retire.** Enforce the appearance check by default; stop accepting free-form colour names; remove the
   script deprecation path.

Rollback at any phase is reverting that phase's PR. An envelope without `appearance` is always valid.

## Open Questions

1. **STEP instance overrides**: materialise as a `<part>@<style>` variant (recommended, lossless, keeps D1), or
   report and drop?
2. **Partially coloured STEP files**: may a declared `properties: color:` fill the faces the file leaves
   uncoloured for a part to be made (recommended, since it is XCAF's own inheritance), or must a manufacturable
   STEP part be fully coloured by its file?
3. **Colour values in names.** Bare catalogue names (`Brick:3004;color=red`, resolved in the part's own
   package), or full references (`;color=//pub/universe/lego/color:red`)? Bare names read better and keep `:`
   out of parametric names; they require the part's package to expose its catalogue. Recommended: bare names,
   with full references accepted where the name parser allows.
4. **Hand-declared `properties: color:` on an assembly**: keep it as a display fallback (recommended), or
   deprecate it?
5. **What `//pub/std/color` ships first**: RAL Classic and the CSS named colours (to give today's free-form
   names a migration target) are proposed. Anything else?
