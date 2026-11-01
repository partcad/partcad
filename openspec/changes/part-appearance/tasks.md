Each numbered section is one pull request against `devel` (or against partcad-index, partcad-ldraw or
partcad-ldraw-examples where it says so). Each is additive, and is released before a later section depends on
it. The order puts what everything else reads first: declarations, then the payload, then the sources.

## 0. Withdraw the link-colour approach

- [x] 0.1 Close partcad/partcad#889, partcad/partcad-ldraw#23 and partcad/partcad-ldraw-examples#5, each with a
      comment pointing at this change
- [ ] 0.2 Make the build report a `color`/`material`/`finish` key on an ASSY link with the instruction to put it
      in `params:` (the schema already refuses unknown keys for `pc lint`)

## 1. CMF declarations

- [ ] 1.1 Schema:
      - `colors:` and `finishes:` sections;
      - `materials:` gains `display`, `ids`, `manufacturable` (default true), `parameters`, `aliases`, a
        `color` claim, and `type: alias` + `source:`;
      - one shared definition for the common fields of the three kinds.
- [ ] 1.2 `material.py` → a CMF declaration module for the three kinds: lookup (`<package>:<name>`, `:name`,
      aliases followed), parametric instances, canonical references
- [ ] 1.3 Display values: a CSS Color Level 4 reader (hex forms, `rgb()`, `hsl()`, `hwb()`, `lab()`/`lch()`,
      `oklab()`/`oklch()`, `color()` with sRGB conversion and clamping, named colours), shared by the core and
      `wrappers/appearance.py`, with a TypeScript twin tested against it; references to other declarations'
      display
- [ ] 1.4 Names: allow the extended character set in CMF declaration names. Add percent-escaping of
      `: ; , = # % * ? [ ]` to `parse_parameterized_name`, `format_parameterized_name` and
      `split_resource_path` (split first, decode after). Round-trip tests, including names with spaces and
      commas.
- [ ] 1.5 CLI: `pc list colors`, `pc list finishes`, with `pc list materials` showing the same columns
- [ ] 1.6 Lint: the new sections, unreadable `display`, unresolvable aliases, names needing escapes
- [ ] 1.7 Docs: `digital_thread/lifecycle/design_cmf.rst` (new, in the Design toctree beside 3D, 2D and
      Drafting); a CMF configuration reference for the three sections; `config_parts.rst` MCFTT section
      rewritten as CMF parameters
- [ ] 1.8 partcad-index: `//pub/std/color`:
      - RAL Classic by designation (`RAL 3020`), with `desc` and `ids.ral`. Its `display` values ship only once
        RAL's terms are confirmed to allow publishing them (see the design's Risks); until then the
        declarations ship without `display`;
      - `rgba` as a parametric, `manufacturable: false` declaration.

      Also `//pub/std/finish` (an initial set: as-produced, SPI mould grades, VDI 3400 references, anodise
      types), and `manufacturable`/`ids` on `//pub/std/manufacturing/material`.

## 2. CMF inside the BREP payload

- [ ] 2.1 `ocp_serialize`: write the CMF section after the BREP: palette of CMF sets (references and display
      values), material per solid, colour and finish per face with a per-solid default, run-length encoded.
      Read it back, and accept a producer's `{sub-shape: CMF}` mapping keyed by identity.
- [ ] 2.2 Tests:
      - `BinTools`/`BRepTools` read a payload with a section as the same geometry;
      - face and solid order are stable through encode/decode, `Moved`, `Located`, the cache, sharing by
        digest, and `wrapper_common.solidify`/`finished`;
      - a payload without a section means no CMF.
- [ ] 2.3 `cache_shape` and the Chili3D end: keep treating such a payload as a BREP; a Chili3D shape gets no CMF
      until its kernel writes one
- [ ] 2.4 A CMF summary in node `metadata` (sets, face and solid counts, unspecified counts), recorded by the
      wrapper and cached with the geometry
- [ ] 2.5 `wrapper_common.finished`: apply the declared CMF parameters (fill, or replace under
      `sourceCmf: drop`) to the producer's CMF before encoding; the request carries the resolved declarations
- [ ] 2.6 `wrappers/appearance.py` becomes the CMF reader for every consumer: per-face display, inheritance
      for nodes without a section. `render_svg.py` draws face groups per display colour; `wrapper_gltf.py`
      writes sub-shape colours and finish-derived PBR into its XCAF document (and verifies how
      `SetMergeFaces` groups styled faces).
- [ ] 2.7 Bump `CACHE_VERSION` of every wrapper whose output gains a section, and re-render `examples/` where a
      picture changes

## 3. CMF type parameters on every part and assembly type

- [ ] 3.1 `color`, `material`, `finish`, `sourceCmf` (`keep`, `drop`, or a list of components), `cmfConvention`
      accepted by every part type and every assembly type (a mixin replacing CMF's place in `PartFactoryHomogen`, which keeps `tolerance`). The
      parameters are ordinary inputs: keyed, and handed to scripts that assign them.
- [ ] 3.2 Canonicalisation: CMF parameter values are resolved (aliases followed, relative references made
      absolute against the package that wrote them) before they enter an item's name or key
- [ ] 3.3 Assembly propagation: an assembly's CMF parameters are passed as parameters to each link that does not
      set them, recursively
- [ ] 3.4 Migrate `properties: color:` written by hand to the `color` parameter (a converting warning), and
      free-form colour values to display-only colours (`css` convention, a warning)
- [ ] 3.5 Cart and providers: `ProviderCartItem.color`/`material`/`finish` are resolved declarations; close the
      two TODOs in `plugin_factory_provider_manufacturer.py`; providers match by `ids`
- [ ] 3.6 Tests: fill vs drop; propagation and a link's own params winning; two aliases of one colour naming one
      item; a variant's BOM line

## 4. STEP

- [ ] 4.1 `wrapper_step.py`:
      - read with `STEPCAFControl_Reader` (colour, name, material, layer modes);
      - styles per sub-shape from `XCAFPrs::CollectStyleSettings` and `XCAFDoc_VisMaterialTool`, materials and
        densities from `XCAFDoc_MaterialTool`, user attributes from `step_metadata`;
      - convert with the part's `cmfConvention` (default `step`);
      - record the read time against `STEPControl_Reader` on the index's largest STEP files.
- [ ] 4.2 `wrapper_import_assy.py` and `assembly_factory_imported.py`: component CMF onto the parts; an
      instance override becomes `params:` on its link
- [ ] 4.3 Physical material per solid feeds mass properties per solid
- [ ] 4.4 Tests with small STEP fixtures: face, solid and product colours; two materials; an instance override;
      fill and drop

## 5. Scripts and OpenSCAD

- [ ] 5.1 `wrapper_build123d.py`: keep `.color`, `.material` and `.label` of each returned shape and sub-shape;
      inject `set_cmf`
- [ ] 5.2 `wrapper_cadquery.py`: the same, plus `cq.Assembly` child colours and `show_object` colour options
- [ ] 5.3 `part_factory_scad.py`: export 3MF where the OpenSCAD in use writes colours (version-gated, binstl
      otherwise), read per-triangle colours with lib3mf, convert with `openscad`
- [ ] 5.4 Docs: how a script or a `.scad` model states CMF, and what the part's CMF parameters do to it

## 6. Converters

- [ ] 6.1 `//builtin/cmf` and the `cmfConventions:` section (declared as `render:`/`export:` file types are):
      the converter interface (source facts in, CMF references and display values out), and `partcad`
      (identity)
- [ ] 6.2 Built-in converters:
      - `step`: the CAx-IF styling and UDA practices; an assembly node's overriding style becomes link
        `params:` with `sourceCmf: [color]`;
      - `3mf`: base material name as the claim, `displaycolor` as display;
      - `gltf`: linear factors to sRGB;
      - `css`, `openscad`, `cadquery`;
      - `build123d`: the 0.11 string and the 0.13 `FinishedMaterial`.
- [ ] 6.3 CAD tools: `solidworks`, `onshape`, `fusion`, `inventor`, `creo`, `nx`, `catia`. Map their material and
      appearance names (`.sldmat`, Onshape CSV libraries, `PTC_MASTER_MATERIAL`/`PTC_ASSIGNED_MATERIAL`, …) and
      the attributes they write into STEP, each with the case folding its tool uses. Build them against fixture
      files each tool wrote.
- [ ] 6.4 Lookup scope: declarations' `ids` in the part's own package and the catalogues listed by the
      converter's `catalogs` parameter
- [ ] 6.5 Tests per converter with fixtures each tool wrote

## 7. Manufacturability

- [ ] 7.1 The `cmf` test: material per solid, colour per face (a material's colour claim counts), finish if
      stated, all `manufacturable: true`; names what fails
- [ ] 7.2 Purchasable assemblies (and their `enrich`): checked by their own CMF parameters; the CMF test and the
      connectivity rule against `location:` do not descend into them
- [ ] 7.3 Stages: a warning, an error under a package opt-in, an error by default once the index passes

## 8. Presentation

- [ ] 8.1 IDE: a `cmf` tab in `DESIGN_TABS`; CMF sets with origin and faces/solids; highlight on selection;
      assembly roll-up with incomplete items first
- [ ] 8.2 IDE: per-primitive materials in the 3D view (`scene.ts` keeps a primitive's own material); finish
      roughness/metallic; `appearance.ts` as the tested twin of the reader
- [ ] 8.3 IDE: Color, Material and Finish columns in the BOM and Build vs Buy views; CMF declarations in the
      explorer
- [ ] 8.4 `pc info` CMF section; generated documents (PDF/HTML instruction books) list CMF per item
- [ ] 8.5 Retake the screenshots the IDE changes make wrong (`dev-tools/screenshots/shoot.mjs`)

## 9. Exports

- [ ] 9.1 `export_step.py`:
      - build an XCAF document from the tree: products, instances, names, sRGB colours per face/solid/product;
      - materials with density on products, and per solid as UDAs on shape aspects where a part has several;
      - finishes as UDAs (`surface_condition` where a texture states Ra);
      - CMF references as UDAs;
      - write it with `STEPCAFControl_Writer`;
      - round-trip test with section 4.
- [ ] 9.2 `export_gltf.py` (shared with 2.6), `export_3mf.py` (base materials and display properties per
      triangle), `export_urdf.py` and MJCF (one visual or geom per CMF set), `export_stl.py` (warn once)

## 10. LEGO (partcad-ldraw `main`, then partcad-ldraw-examples `main`)

- [ ] 10.1 partcad-ldraw declares LEGO's colours: the `LEGOID` entries of `LDConfig.ldr` (185 of 322 today), named
      as LEGO names them, with `ids` for LEGO, LDraw, BrickLink and Rebrickable and LDraw's value as `display`.
      It also declares the materials and finishes LDraw's codes imply (rubber, transparent, chrome, pearlescent,
      metallic). Codes with no LEGO id are left undeclared, or declared `manufacturable: false`.
- [ ] 10.2 `ldraw.py`:
      - carry each triangle's resolved code (LDraw's inheritance of `16`; `24` ignored);
      - merge coplanar faces only within one code, and give authored faces their neighbours' code;
      - convert with the `ldraw` convention into colour, material and finish, leaving top-level `16` unset;
      - bump the wrapper's cache version.
- [ ] 10.3 Shortcuts: assemblies whose `color` propagates to their `16` parts, with fixed-colour parts linked
      with their own `params:`. A shortcut sold whole declares its CMF as a purchasable assembly.
- [ ] 10.4 The LEGO stores order by (design, LEGO colour id)
- [ ] 10.5 partcad-ldraw-examples: aliases of the LEGO colours in `colors:`, passed through assembly and part
      `params:` by the generators; re-render; the README's BOM and buying sections in the right colours; raise
      the `partcad:` floor once the index pins section 10.1-10.4

## 11. Retire

- [ ] 11.1 The CMF check an error by default, after the index passes it
- [ ] 11.2 Stop accepting hand-written `properties: color:` and free-form colour values
- [ ] 11.3 The `texture` parameter name: give it no meaning of its own (texture is a finish), and say so where it
      is policed
