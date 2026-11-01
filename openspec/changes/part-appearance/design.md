## Context

**CMF outside PartCAD.**

- Industrial design specifies an item's colour, material and finish together, as a CMF specification attached
  to the item:
  - colour: by a standard or a vendor's catalogue (RAL 3020; LEGO 21 "Bright Red");
  - material: a grade (ABS, 6061-T6);
  - finish: process and surface (anodise Type II; VDI 3400 Ref 27; SPI A-2), including texture and gloss.
- A different CMF is a different item: a red and a black housing are two part numbers.
- The file an item is defined by carries the CMF the CAD tool knew, scoped to the geometry it applies to.
  Colours sit on faces, solids and products; physical materials sit on solids. How each tool names and exports
  them differs (see "Conventions surveyed").
- LDraw is an instructive case. A colour code there is really a CMF triple: `256` is LEGO's black in rubber,
  and the `CHROME`, `PEARLESCENT` and `METAL` codes are finishes. Of LDraw's 322 colours, 185 carry the LEGO
  colour id and LEGO's own name (`LEGOID 194 - Medium Stone Grey` for LDraw's `Light_Bluish_Grey`, code 71).

**CMF in PartCAD today** (`devel`, 0.8.273):

| Where | What happens |
| --- | --- |
| `materials:` | Objects addressed as `<package>:<name>`: name, density, friction. No display, no `manufacturable`, no aliases, no parameters. |
| `color`, `finish`, `texture` | Reserved object-type parameter names. `color` is "not implemented yet" and accepted only by homogeneous types (`PartFactoryHomogen`). `finish` and `texture` do nothing. |
| `properties.color` | One `#RRGGBB` per node, inherited downward, drawn by the renderers and the IDE. |
| `wrapper_step.py` | `STEPControl_Reader`: every colour, material and name in the file is discarded. |
| `export_step.py` | `STEPControl_Writer` of the flattened compound: no structure, names, colours or materials. |
| `wrapper_build123d.py`, `wrapper_cadquery.py` | Keep `.wrapped` only; build123d's `.color`, `.material` and `.label` (all three exist on a `Shape`) are dropped. |
| `part_factory_scad.py` | `--export-format binstl`: colourless. The bundles carry an OpenSCAD development snapshot; a host may have 2021.01. |
| `wrapper_gltf.py` | Builds an XCAF document for `RWGltf_CafWriter`, with no colours in it. |
| Cart and providers | `get_mcftt` reads `material`, `color`, `finish` as strings; providers match strings against `caps.materials[m].colors/finishes`, with `TODO: resolve … as a color object` (and as a finish object). |
| Names | `^[a-zA-Z0-9_/./-]+$` for declarations; parametric names `<name>;<p>=<v>,…` already tolerate `:` and `/` in values (`medium=//pub/std/materials:water`). |
| IDE | Digital Thread > Design has sub-tabs `3d`, `2d`, `draft`; materials appear in the BOM and Build vs Buy views. |

**Verified here, not assumed:**

- **OCCT ignores bytes after the shape.** Its readers read a binary BREP followed by an arbitrary trailer
  (`ocp_serialize.shape_from_brep`) and an ASCII BREP followed by one (`BRepTools::Read`) as the same geometry.
- **Sub-shape order is stable.** `TopExp::MapShapes` gives the same face order before and after PartCAD's
  codec, for a box, a boolean result and a compound of three solids. `wrapper_common.solidify` reuses the
  shell's faces.
- **XBF works but is a separate format.** An XCAF document saved as XBF (`BinXCAFDrivers`) with a colour on one
  face round-trips, and is byte-identical across two saves in one process (5,628 bytes against 5,899 for the
  BREP alone). It is a separate file format, header `BINFILE`.
- **The pinned OCP has the XCAF tools needed:** `STEPCAFControl_Reader/Writer`, `XCAFDoc_{Color,VisMaterial,
  Material}Tool`, `XCAFPrs::CollectStyleSettings`, `XCAFDoc_MaterialTool::GetDensityForShape`,
  `RWGltf_CafReader/Writer`. It has no `RWObj` or `RWPly`.

## Goals / Non-Goals

**Goals:**

- CMF as one concept with three components, implemented once and shown the same way in every view, command,
  export and document.
- CMF stated by the item's definition (its source and its type parameters), carried inside the geometry, and
  canonical in the item's name, so the BOM, procurement, manufacturability and documentation agree.
- A clear line between a CMF claim (can be sourced or made) and a display hint.
- One PartCAD convention, with converters from the conventions other tools use.
- Lossless STEP in and out.
- Scripts and OpenSCAD able to state CMF.
- Optimised for the common case: parts of one geometry share one CMF.

**Non-Goals:**

- Optimising for many CMF variants of one geometry. A variant rebuilds and caches its own payload.
- Image textures and UV mapping. A texture is a finish specification (VDI, Mold-Tech, Ra), not an image.
- Physically based rendering in `pc render`. Drawings get colours, the 3D view gets finish hints.
- CMF on an ASSY link other than through `params:`.
- Publishing colour systems whose licence forbids it (Pantone).

## Decisions

### D1. CMF is one concept with three components; texture belongs to finish

`colors:`, `materials:` and `finishes:` are three kinds of one *CMF declaration*. They share their structure
(D3) and differ only in their own facts:

- a colour: nothing more;
- a material: density, friction, and an optional colour claim for its natural surface;
- a finish: process and surface texture (`texture: {vdi3400: "27"}`, `{moldtech: "MT-11010"}`, `{ra: 0.8}`),
  gloss, and display hints (roughness, metallic).

The reserved `texture` parameter is given no meaning of its own.

*Why:* this is how CMF specifications are written, and it is the grouping PartCAD's providers already use
(`caps.materials[m].colors` and `.finishes`). Texture and gloss are what a finish specification says, so a
separate `texture` component would make a finish that says "VDI 3400 Ref 27" ambiguous about where its texture
lives.

### D2. A CMF declaration is a claim; a display colour is a hint

- A **CMF declaration** with `manufacturable: true` (the default) claims that the colour, material or finish
  can be sourced or manufactured as declared.
- A **display** value is only how to draw it. A colour declaration states its display in any CSS Colour Level 4
  notation, or as a reference to another colour declaration whose display it takes. A vendor colour may be
  displayed "as RAL 3001" without claiming to be RAL 3001.
- `//pub/std/color:rgba;color=<RRGGBBAA>` is the parametric display-only declaration
  (`manufacturable: false`): what anybody uses to colour a picture without claiming anything.
- `//pub/std/color` itself is named after industrial specifications: RAL Classic by designation (`RAL 3020`).
  Vendors declare their own colours as they like.

*Why:* a supplier is asked for RAL 3020, not for `#C1121C`. Several specifications draw alike, and one
specification draws differently on different screens. A string that is both a picture and a specification
turns a picture into a specification by accident. That is today's situation, and it is why providers cannot
match colours.

*Alternatives rejected:*

- **Hex values as the colour**: nothing to source.
- **A boolean "display only" flag on parts**: the claim belongs to the colour, not to each use of it.

### D3. Declarations are parametric, aliasable, and canonical

Every CMF declaration may have:

- `parameters:` (with fields templated on them, as `rgba` is);
- `aliases:` (other names of itself);
- `ids:` (its identifiers in other systems: `ral`, `lego`, `ldraw`, `bricklink`, `solidworks`, …).

It may also be a `type: alias` with a `source:` reference to another declaration, in any package. A reference
is **canonicalised** before it enters an item's name or cache key: aliases followed, relative references made
absolute against the package that wrote them, parameters sorted as `format_parameterized_name` does. Two
consumers that alias one LEGO colour differently therefore name the same item.

*Why:* these are the mechanisms parts already have (`type: alias`, `aliases:`, parameters, `enrich`), so CMF
gets nothing new to learn. Canonicalisation is what makes an alias a convenience rather than a second identity.

### D4. Names as external specifications write them, with escaping

- CMF declaration names may contain spaces and printable characters other than `: ; , = # %` and `* ? [ ]`,
  with no leading or trailing space. That admits `RAL 3020`, `Medium Stone Grey`, `6061-T6` and `PA12 (GF30)`.
- In any name or parameter value, those reserved characters may be written percent-encoded (`%3A`, `%3B`,
  `%2C`, `%3D`, `%23`, `%25`, `%2A`, `%3F`, `%5B`, `%5D`). `parse_parameterized_name` and
  `split_resource_path` split on the raw separators first and decode each component after.
  `format_parameterized_name` encodes the same set.
- The wider character set applies to CMF declarations only. Parts and other shapes keep theirs, because their
  names become file names and are typed on command lines far more often.

*Alternatives rejected:*

- **Slugs only** (`ral-3020`): the name stops being the specification's, and a slug can be an alias anyway.
- **Backslash escaping, or quoting:** both change how the separators are found, which is exactly the
  complication to avoid.

Percent-encoding is the established convention (RFC 3986) and leaves splitting alone.

### D5. One PartCAD convention

On a shape, CMF is a palette of **CMF sets**. Each set holds:

- a colour reference, a material reference and a finish reference, each canonical and each optional;
- the display values resolved for them (sRGB with alpha; roughness and metallic from the finish);
- their origin: the source and the convention it was converted from, declared, propagated, or a material's
  colour claim.

Each solid has a material. Each face has a colour and a finish, defaulting to its solid's.

*Why this granularity:* it is where every surveyed tool and format puts them (see "Conventions surveyed"):
appearance per face with body and part defaults, physical material per body. It is also STEP's and XCAF's
structure, so reading and writing STEP is a mapping, not a translation.

### D6. CMF is stored inside the BREP payload

A shape's payload is its BREP followed by a **CMF section**:

- a short header and a version;
- the palette;
- materials per solid;
- colours and finishes per face (run-length encoded), with sub-shapes addressed by `TopExp::MapShapes` order;
- an end-anchored length, so the section can be found without parsing the BREP.

The producer hands `ocp_serialize` a mapping keyed by sub-shape identity, and indices are computed at encode
time. The wrapper also records a CMF summary in the node's `metadata` (the sets, their face and solid counts,
what is unspecified), cached with the geometry, for consumers that do not load the CAD kernel: `pc test`, the
BOM views, the IDE's CMF tab.

*Why:*

- **Geometry and CMF are one value**, cached, digested and shared together. Parts of one geometry and one CMF,
  the common case, share one entry; a different CMF is a different entry.
- **The payload stays a BREP.** OCCT's readers, an earlier PartCAD reading a newer cache, and the Chili3D end all
  read the geometry and ignore the section (verified), so nothing has to migrate at once.
- **The core stays free of the kernel.** It still never parses a payload; the summary answers its questions.

*Alternatives rejected:*

- **A separate table on the node** (this proposal's previous version): it pays off only when one geometry
  carries many CMFs, which is the case not optimised for. It splits one fact across two places that every reader
  must join.
- **XBF, XCAF's binary document:** it works and is deterministic. But it is a different format for every reader
  (the cache, Chili3D, earlier releases), bound to OCCT versions. It also stores display attributes in XCAF's
  model, where PartCAD's references would still go into generic attributes. XCAF stays where it pays: building
  documents to read and write STEP and glTF.
- **One solid per CMF:** it changes the item's structure, and a painted face is not a solid.

*Accepted trade-off:* a CMF variant rebuilds its geometry, because its parameters are build inputs like any
other.

### D7. Where CMF comes from, in one order

When a part is built, in its sandbox, each sub-shape's CMF is:

1. what the **source** states (the file, the script, the OpenSCAD model), converted by the type's
   `cmfConvention`;
2. completed by the **CMF type parameters** `color`, `material` and `finish` for the components still unset,
   or, with `sourceCmf: drop`, replaced by them entirely;
3. for colour, completed by the **material's colour claim**;
4. otherwise **unspecified**, drawn in the display default (OCCT goldenrod) and failing the CMF check of a part
   to be made.

The CMF parameters are ordinary build inputs: keyed, and handed to a script that assigns them. The payload
therefore holds the final CMF, and every reader reads it without resolving anything.

*Why:* it is the same rule for every type, STEP included (decision 2 from review). "Fill what the source leaves
out" is XCAF's own inheritance, and `sourceCmf: drop` is the deliberate way to replace a file's CMF wholesale.

### D8. Every part and assembly type takes the CMF parameters; propagation is parametric

- `color`, `material`, `finish`, `sourceCmf` and `cmfConvention` are object-type parameters of every part type
  and every assembly type, through one mixin. `PartFactoryHomogen` keeps `tolerance`, which really is about one
  homogeneous body.
- An assembly's CMF parameters are passed to each of its links as parameter values, for those the link's own
  `params:` do not set, recursively.
- Every item therefore ends up the variant its parameters name, under its canonical name, with its own BOM line
  and supply question.
- An imported STEP assembly writes an instance's overridden CMF as `params:` on that link (decision 1 from
  review): the same mechanism, and no invented `<part>@<style>` names.
- An assembly that declares `vendor` and `sku` (or its `enrich`) is a bought item. Its CMF parameters are its
  CMF claim, checked as such (D11), and they decide how it is drawn through the same propagation (decision 4).

*Why:* one meaning of `color` everywhere is what makes CMF coherent. A link names an item, and its `params:`
choose which variant, which PartCAD already does for every other parameter.

*Alternative rejected:* **implicit display inheritance** (today's `properties.color` flowing down). It colours
a part without changing what the part is, which is the confusion this change removes.

### D9. Scripts and OpenSCAD state CMF

A script or a `.scad` model is as much a definition as a STEP file, so it may state CMF:

- **build123d:** the wrapper keeps `.color` (a display-only colour, unless `set_cmf` names a declaration),
  `.material` (a material reference) and `.label` of every returned shape and sub-shape.
- **CadQuery:** the same, plus `cq.Assembly` child colours and `show_object(…, options={"color": …})`.
- **`set_cmf(shape, color=…, material=…, finish=…)`** is handed to scripts as `show_object` is, and attaches
  canonical references by sub-shape identity.
- **OpenSCAD:** parts are exported as 3MF where the OpenSCAD in use writes colours, with per-triangle colours
  read through lib3mf and converted by `openscad`. An OpenSCAD that writes no colours still exports `binstl`
  and states no CMF.

*Why the earlier restriction is dropped:* it judged CMF by the *format*, when what matters to manufacturing is
whether the CMF is *complete and claimed* (D11). The restriction would push a user to STEP for nothing, and
build123d already has the attributes.

### D10. Converters: `cmfConvention`

A source states CMF in its tool's convention. `cmfConvention` names the converter that maps it into D5's:

- Converters are implementations in a `//builtin/cmf` package, declared in a `cmfConventions:` section the
  way file types are declared under `render:` and `export:`, so a package may supply its own.
- Each type has a default: `step` for STEP, `3mf`, `gltf`, `openscad`, `build123d`, `cadquery`, `ldraw`. A
  part chooses another when its file came from a particular tool (`cmfConvention: solidworks`).
- A converter reads the source's facts (names, RGB values, material designations, user-defined attributes) and
  looks each up by `ids` among the declarations in scope: the part's own package and the converter's `catalogs`
  parameter.
- A fact it cannot match becomes, for a colour, the display-only `rgba` of the stated value. For a material or
  a finish it is left unset, to be completed by the parameters (D7). A warning names it either way.

<!-- SURVEY -->

### D11. Manufacturability counts claims

`pc test` gains a `cmf` check for every part to be made (manufacturable and not purchased). It passes only if:

- every solid has a material;
- every face has a colour (a material's colour claim counts);
- the finish, if stated, is set;
- each resolves to a declaration with `manufacturable: true`.

Consequences:

- A display-only `rgba` colour fails it.
- So does a converter's unmatched colour, so a STEP part whose file colours are not recognised claims must
  complete them through its parameters, or replace them with `sourceCmf: drop`. Either way, every solid and face
  of a STEP part to be made ends up specified, from the file or from the user (decision 2).
- A purchasable assembly is checked by its own CMF parameters. Neither this check nor the connectivity rule
  against `location:` descends into it, so a wheel sold assembled may place its rim by coordinates and contain
  a tyre part with no material (decision 4).

The check is a warning first, an error under a package opt-in next, and an error by default once the index
passes, the path `tolerance` took.

### D12. One presentation, everywhere

CMF is always shown as its three components in the order colour, material, finish: each by declaration name,
with a display swatch, marked when not manufacturable or unspecified, and with its origin where there is room.
The same presentation is used by:

- **IDE:** a new Design > CMF tab (sets, faces and solids, origin, highlight on selection; for an assembly, a
  roll-up by item with incomplete items first); Color, Material and Finish columns in the BOM and Build vs Buy
  views; CMF declarations in the explorer.
- **CLI:** `pc list colors|materials|finishes` with identical columns, and a CMF section in `pc info`.
- **Drawings:** faces in their display colours. **3D view:** finish roughness and metallic.
- **Exports:**
  - STEP through XCAF: structure, names, colours on faces, solids and products, materials with density, and
    PartCAD's references as user-defined attributes so that a PartCAD-to-PartCAD round trip keeps the claims;
  - glTF and 3MF materials;
  - URDF and MJCF visuals per CMF set;
  - STL warns.
- **Docs:** `digital_thread/lifecycle/design_cmf.rst`, beside 3D, 2D and Drafting, explains the model, and
  `design.rst`'s "Properties" points to it. One configuration reference covers the three sections, and the parts
  and assemblies references describe the CMF parameters once and link to it.

### D13. LEGO, on this model

- **partcad-ldraw** declares LEGO's colours: the 185 `LEGOID` entries of `LDConfig.ldr`, named as LEGO names
  them, with `ids` (LEGO, LDraw, BrickLink, Rebrickable) and LDraw's value as `display`. It also declares the
  materials and finishes LDraw's codes imply (ABS, polycarbonate for transparent colours, rubber; chrome,
  pearlescent, metallic). Codes without a LEGO id are not declared as manufacturable colours. These are
  "the colours actually used by the vendor" (decision 3), and every consumer references them.
- **The `ldraw` converter** turns each code into a CMF triple. The wrapper carries codes per triangle (LDraw's
  inheritance of `16`), merges coplanar faces only within a code, and leaves top-level `16` unset for the part's
  `color` parameter to complete.
- **Shortcuts** are assemblies whose `color` propagates to their `16` parts. A part the shortcut's file draws in
  a fixed colour gets its own `params:`. A shortcut LEGO sells whole declares `vendor`/`sku`, and its CMF is its
  claim.
- **The examples** declare aliases (`colors: {stone: {type: alias, source: "//pub/universe/lego:Medium Stone
  Grey"}}`) and pass them through the sub-assemblies' `params:` (`castle/wall` with `color: ":stone"`), so each
  brick becomes `Brick:3004;color=<canonical>`. The BOM lists buildable lines, and the LEGO stores order by
  (design, LEGO colour id). No ASSY link states a colour outside `params:`.

## Decisions taken in review

1. No `<part>@<style>` names. STEP instance overrides become link `params:`, and CMF parameter handling is one
   mechanism for part and assembly types (D8).
2. User parameters complete a STEP file's CMF. Every component of a STEP part to be made must end up specified,
   and `sourceCmf: drop` replaces the file's CMF entirely (D7, D11).
3. Both bare and full references are supported. For LEGO, partcad-ldraw declares the vendor's colours and
   consumers reference them through CMF aliases. External names are kept, with percent-escaping where the
   parser needs it (D3, D4, D13).
4. CMF stays declarable on assemblies with `vendor` and `sku`. It is their claim and their look, and it keeps
   them procurable whatever is inside (D8, D11).
5. `//pub/std/color` uses industrial names. Vendors define their own. A claim differs from a display colour,
   which may be any CSS notation or RAL reference. CMF declarations take parameters, `rgba` is display-only, and
   `manufacturable:` is on every CMF declaration and counted by the checks (D2, D3, D11).

## Why this is the right approach for PartCAD

- **It is CMF as industry writes it.** Three components, specified by catalogue and standard, attached to the
  item, with the picture of each kept apart from the claim.
- **It is the structure the source data already has.** Colour and finish per face with body defaults, material
  per body: what STEP, XCAF and every surveyed tool use. STEP and every other format become mappings, and the
  converters exist because tools *name* things differently, not because they structure them differently.
- **It keeps identity in one place.** CMF enters an item's canonical name through parameters, so the BOM,
  procurement, manufacturability, drawings and exports read one answer. An assembly can only choose variants,
  never repaint an item.
- **It extends PartCAD rather than adding to it.** Declarations generalise `materials:`. Aliases, parameters
  and `enrich` are the existing variant mechanisms, `metadata` already carries what a wrapper learnt from
  geometry, and the payload stays a BREP.
- **It is optimised for the common case and honest about the other.** One geometry with one CMF is one cached
  value. Many CMFs of one geometry cost a build each, and are allowed to.

## Risks / Trade-offs

- **Sub-shape indices are only as stable as the sub-shapes.** Mitigations:
  - indices are computed from identity at encode time;
  - a test pins stability through the codec, placement, the cache and sharing;
  - an operation that rebuilds faces (sewing, unifying, booleans) carries CMF through OCCT history or drops it
    with a warning, never silently.
- **CMF variants cost builds.** LEGO's 1 x 1 brick in 177 colours would be 177 builds. This is accepted. The
  examples use a handful of colours per part.
- **Every cached part is rebuilt once,** as each wrapper's `CACHE_VERSION` moves. `STEPCAFControl_Reader` is
  slower than `STEPControl_Reader`; it is measured on the index's largest files before it lands.
- **An edge between two colours in a line drawing.** Hidden-line removal yields it once per colour group; both
  are drawn, the later on top.
- **Wider names.** Spaces in CMF names need quoting on a command line. Percent-encoded forms always work, and
  shapes' names are unchanged.
- **Checked-in renders change** wherever parts gain CMF. Each PR re-renders what it changes, and the
  `Examples (PartCAD)` job holds it to that.
- **Licensing of colour systems.** Only what may be published is shipped (see "Conventions surveyed").

## Migration Plan

Additive phases, each released before the next depends on it (see `tasks.md` for the pull requests):

1. Declarations, names and escaping, `//pub/std/color` and `//pub/std/finish`, CLI listing, and docs.
2. The CMF section inside the BREP, the summary, the reader, drawings and the glTF form.
3. CMF parameters on every type, propagation and canonical names, and the cart and providers.
4. STEP.
5. Scripts and OpenSCAD.
6. Converters.
7. The `cmf` check, as a warning.
8. The IDE and the CLI presentation.
9. Exports.
10. LEGO.
11. Retirement: the check by default, hand-written `properties: color:` and free-form colours refused, and
    `texture` given no meaning.

Hand-written `properties: color:` and free-form `color` values keep working through the migration. They are
converted to the `color` parameter and to display-only `rgba` respectively, each with a warning naming the
replacement. A payload without a CMF section is always valid. Rolling back a phase is reverting its pull
request.

## Open Questions

1. **The CMF section's encoding**: compact JSON (readable, diffable in a debugger) or a binary encoding? JSON is
   proposed; a palette and run-lengths stay small.
2. **Finish completeness**: is a part to be made with no finish stated "as produced" (proposed), or must it
   state `//pub/std/finish:as-produced` explicitly?
3. **Converter priority**: which CAD tools' conventions to implement first after `step`. The proposal is those
   the index's STEP files come from, found by their `FILE_NAME` originating system.
4. **A propagated CMF parameter a link's item cannot use** (an assembly passing `finish` to a purchased part sold
   in one finish): ignore it with a warning (proposed), or fail the build?
