## Why

PartCAD is meant to keep the data of real, manufacturable products, and in real products appearance is
**part of the item**. A red housing and a black housing are two part numbers: they are ordered, stocked,
inspected and shipped separately. Industrial practice states it as a CMF specification - colour, material,
finish - attached to the part, and the CAD file the part is defined by carries it per body and per face. STEP
AP214/AP242 files state a colour on each solid and each face, a physical material on each solid, and a name on
each product. 3MF, glTF and OBJ+MTL do the same for meshes. LDraw states a colour on every triangle.

PartCAD throws nearly all of that away today:

- **STEP in, STEP out lose it.** A `step` part is read with `STEPControl_Reader`
  (`src/partcad/wrappers/wrapper_step.py`), which discards every colour, material and name in the file. The
  `step` exporter writes the flattened compound with `STEPControl_Writer`
  (`src/partcad/builtin/export/export_step.py`), so a round trip through PartCAD also loses the assembly
  structure. `step_metadata.py` says why it reads the file as text: "XCAF gives names, layers and colours" -
  and nothing reads them.
- **A shape can only be one colour.** The shape tree carries `properties.color` per node. There is nowhere to
  say that one face of a part is a different colour from another, so a two-colour moulding, a printed label or
  a black O-ring groove cannot be represented at all.
- **The colour parameter is a stub.** `color` is an object-type parameter that only homogeneous part types
  accept (`PartFactoryHomogen`), which is the right rule, but it is documented as "Not implemented yet. Use
  color names for now." It is never turned into what the part is drawn in
  (`PartFactory.OBJECT_TYPE_PARAMETER_PROPERTIES` leaves it out on purpose). Because it is an ordinary
  parameter, a colour variant would also be built and cached as different geometry.
- **Colours are strings.** A manufacturing provider matches `cart_item.color` against its own colour names, and
  the code says what is missing: `TODO: resolve cart_item.color as a color object`
  (`plugin_factory_provider_manufacturer.py`). The same TODO stands for `finish`.

The LEGO examples (`partcad/partcad-ldraw-examples`) made the gap visible. Every picture is goldenrod, even
though every LDraw file states a colour per triangle. The first attempt to fix that (partcad/partcad#889,
partcad/partcad-ldraw#23, partcad/partcad-ldraw-examples#5) put a `color:` on the ASSY link that places a
part. That is the wrong layer:

- a link names an item; it does not get to change what the item is;
- the bill of materials still listed "Brick 1 x 2 x 153", with no way to buy the right ones;
- a link colour has no counterpart in a STEP product structure that PDM systems agree on;
- it still could not colour one face of a part.

Those three changes are superseded by this one.

## What Changes

- **Appearance belongs to the part definition, never to an assembly link.** A part's appearance comes from
  exactly two sources:
  - **file-defined**, from a colour-defining format (STEP AP214/AP242, LDraw, and later 3MF, glTF and
    OBJ+MTL), per face and per solid;
  - **declared**, as one colour for the whole body. This is only possible for part types that produce one
    homogeneous body, as the `color` object-type parameter already is.

  A face the file leaves uncoloured takes the part's declared colour, which is XCAF's own inheritance rule.
  Nothing an assembly says changes what a part is. ASSY files get no `color:` key (#889 is withdrawn).
- **Shapes carry per-face appearance.** The shape envelope gets an `appearance` table beside the BREP:
  - a palette of styles;
  - a style index per face, in the order `TopExp::MapShapes` gives (verified stable through PartCAD's BREP
    codec);
  - optionally, one style per solid.

  It is written by the wrapper that reads the file, cached in the same entry as the geometry (as
  `metadata.sections` already is), and read by every consumer through one resolver in
  `wrappers/appearance.py`. The core keeps carrying it as opaque data, so it stays free of the CAD kernel.
- **A colour variant is a distinct item that shares its geometry.** `Brick:3004;color=…`, or an `enrich` that
  fixes `color`, is its own item: its own name, BOM line and order. Geometry stays shared:
  - the `color` parameter is consumed by PartCAD and not handed to the geometry producer;
  - it is left out of the geometry cache key;
  - it is applied as the part's base style when the shape is stamped.

  One mesh serves every colour a part comes in.
- **Colours become catalogue objects.** A `colors:` section, addressed as `<package>:<name>` exactly like
  `materials:`. Each colour has a display value (`#RRGGBB[AA]`) and the identifiers other systems use for it
  (RAL, LEGO, BrickLink, Rebrickable, …). `color` parameters name one, which closes the provider TODO. A
  literal `#RRGGBB` stays allowed as a display-only colour that specifies nothing to a supplier.
- **Appearance is part of manufacturability.** A part that is to be made must have every face resolve to an
  appearance: from its file, from its declared colour, or from its material's natural appearance (an unpainted
  aluminium part is aluminium-coloured). This is introduced as a warning, enforced later. Multi-colour is only
  possible for file-defined parts, so a part defined any other way cannot be both multi-colour and
  manufacturable.
- **Every reader and writer of shapes honours it.** The SVG/PNG/JPEG renderers colour per face. The IDE's
  Digital Thread keeps per-primitive materials. glTF, STEP (now with XCAF: names, colours, materials and
  assembly structure) and 3MF write it. STEP and LDraw are the first readers, with glTF, 3MF and OBJ+MTL after
  them. URDF and MJCF export a multi-colour part as one visual or geom per style.
- **The LEGO examples are redone on this model.** partcad-ldraw:
  - meshes each triangle's LDraw colour into the appearance table, with code `16` (main colour) left uncoloured
    so that it inherits;
  - serves a `color` parameter on every part, whose values are a LEGO colour catalogue generated from LDraw's
    `LDConfig.ldr`;
  - has a shortcut pass its own colour down to its `16` parts.

  The castle and the car declare named variants (`enrich`) and link those. Nothing in an ASSY file states a
  colour.

Breaking changes follow `docs/source/contributing.rst` ("Branches, releases and breaking changes"): additive
first and released, then the index migrated, and the old form retired last. Two items are affected:

- A script that reads `color` stops receiving it. It is warned first, then retired.
- A free-form colour name such as `"red"` must resolve to a catalogue entry. It is warned first.

## Capabilities

### New Capabilities
- `part-appearance`: where a part's appearance comes from (file-defined or declared, never an assembly link),
  the per-face/per-solid appearance table and its inheritance order, and that every renderer, viewer and
  exporter resolves it the same way.
- `color-catalogue`: colours as objects (`colors:`), how a `color` value names one, what a colour carries
  (display value, identifiers in other systems), and how a supplier is handed one.
- `appearance-variants`: a part in a colour is a distinct item (name, BOM line, supply), and its geometry is
  shared with every other colour of the same part.
- `appearance-interchange`: which formats are read and written with their appearance (STEP via XCAF first,
  then glTF, 3MF and OBJ+MTL; LDraw in its own package), what is lossless and what is reported.

### Modified Capabilities
- None. The specs under `openspec/specs/` cover development process and documentation, not shape data.

## Impact

- **Shape envelope** (`shape_envelope.py`, `wrappers/ocp_serialize.py`): a new optional `appearance` key on
  shape nodes. It is additive: an envelope without it means what it means today.
- **Readers/producers**: `wrappers/wrapper_step.py` (XCAF), `wrappers/wrapper_import_assy.py` (component
  appearance, and instance overrides), then `wrapper_import_gltf.py`, `part_factory_3mf.py` and OBJ.
  partcad-ldraw's `ldraw.py`.
- **Consumers**: `wrappers/appearance.py` (the resolver), `builtin/render/render_svg.py` (per-face colour
  groups), `wrappers/wrapper_gltf.py` (XCAF sub-shape colours), `ide/vscode/src/webview/{appearance,scene}.ts`
  (per-primitive materials), `builtin/export/export_{step,gltf,3mf,urdf}.py`.
- **Configuration**: `colors:` section and `color` parameter semantics in `src/partcad_utils/schema/partcad.json`;
  `part_factory.py` (promote `color`, keep it out of the key and away from scripts); `shape.py` key handling;
  `material.py` (natural appearance of a material).
- **Supply**: `plugin_provider_data_cart.py` and `plugin_factory_provider_manufacturer.py` resolve colour
  objects.
- **Tests**: `pc test` gains an appearance check for parts to be made.
- **Documentation**: `config_parts.rst` (MCFTT section, Properties), `config_output.rst`, new colour catalogue
  docs, `assy.rst` unchanged (no link colour).
- **Checked-in renders**: every image under `examples/` whose parts gain a colour (from a STEP file or a
  material) changes, and is re-rendered in the PR that causes it.
- **Other repositories**: partcad-index (`//pub/std/color` catalogue, the parameter migration),
  partcad-ldraw, partcad-ldraw-examples.
- **Withdrawn**: partcad/partcad#889 (link `color:`). partcad/partcad-ldraw#23 and
  partcad/partcad-ldraw-examples#5 are replaced by the LDraw phase; #23's colour table extraction is reused
  there.
