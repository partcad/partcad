## Why

PartCAD is meant to keep the data of real, manufacturable products, and in a real product **CMF - colour,
material and finish - is part of the item**:

- A red housing and a black housing are two part numbers, ordered, stocked and inspected separately. LEGO
  says it outright: an *element* is a design in a colour, and the element is what is sold.
- A CMF specification names each component by a standard or a vendor's catalogue (RAL 3020, LEGO "Bright
  Red", ABS, VDI 3400 Ref 27, anodise Type II), not by an RGB value.
- The CAD file a part is defined by carries CMF per body and per face: STEP AP214/AP242 states colours on
  products, solids and faces, and materials (with density) on solids. 3MF, glTF and OBJ+MTL carry the same
  per triangle or primitive, and LDraw states a colour on every triangle.

PartCAD keeps almost none of it:

- **STEP loses it both ways.** A `step` part is read with `STEPControl_Reader` (`wrappers/wrapper_step.py`),
  which discards every colour, material and name in the file. The `step` exporter writes the flattened
  compound with `STEPControl_Writer` (`builtin/export/export_step.py`), losing the assembly structure too.
- **A shape is at most one colour.** `properties.color` is per node, so a two-colour moulding or a printed
  label cannot be represented.
- **Scripts and OpenSCAD lose what they state.** The build123d and CadQuery wrappers keep only `.wrapped`, so
  a shape's `.color` and `.material` are dropped. OpenSCAD parts are exported as `binstl`, which has no colour.
- **CMF is strings, and incomplete.** `material` is a catalogue object (`materials:`). `color` is a stub
  ("Not implemented yet"). `finish` and `texture` are reserved names. Providers match colour and finish as free
  text, and the code says what is missing: `TODO: resolve cart_item.color as a color object`, and the same for
  `finish` (`plugin_factory_provider_manufacturer.py`).
- **Nothing tells a claim from a picture.** `#FF0000` drawn on screen and "RAL 3020, sourced from this
  supplier" are the same string today.

The LEGO examples made this visible: every picture is goldenrod, although every LDraw file states colours. A
first attempt put a `color:` on the ASSY link that places a part (partcad/partcad#889,
partcad/partcad-ldraw#23, partcad/partcad-ldraw-examples#5, all now closed). That is the wrong layer: a link
names an item and cannot change what the item is, and the bill of materials still could not tell a red brick
from a blue one. This change replaces it.

## What Changes

- **CMF as one concept, with three components.**
  - Colour, material and finish are each *CMF declarations*: objects of a package in `colors:`, `materials:`
    and `finishes:`, all built the same way.
  - Surface texture is part of finish, as CMF practice treats it.
  - Every declaration has: a display hint; identifiers in other systems (`ids:`); `manufacturable:` (true by
    default, a claim that it can be sourced or made); optional `parameters:`; per-declaration `aliases:`; and
    `type: alias` declarations that point at another package's.
- **A display colour is not a colour declaration.**
  - A *CMF colour declaration* is a claim that the colour can be sourced or manufactured.
  - A *display colour* is only a visualisation hint. Each declaration states its display however it likes:
    any CSS colour notation, or a reference to a RAL Classic declaration.
  - `//pub/std/color:rgba;color=<RRGGBBAA>` is a parametric declaration for quick display-only use, marked
    `manufacturable: false`.
  - `//pub/std/color` is named after industrial CMF specifications such as RAL Classic. Vendors declare their
    own colours their own way.
- **One PartCAD convention, and converters into it.**
  - Inside PartCAD, a CMF component is always a reference to a declaration, `<package>:<name>[;<parameters>]`,
    canonicalised (aliases followed, relative references made absolute).
  - A new type parameter, `cmfConvention`, chooses a converter that maps another tool's CMF into that
    convention: STEP as the CAx-IF practices write it, SOLIDWORKS, Onshape, Fusion, Creo, NX, CATIA, 3MF,
    glTF, OpenSCAD, build123d, CadQuery, LDraw.
  - Converters are implementations in a `//builtin/cmf` package, so a package can supply its own, as with file
    types.
- **CMF is stored inside the BREP.** A part's payload is its BREP followed by a CMF section:
  - a palette of CMF sets;
  - material per solid;
  - colour and finish per face, with a per-solid default.

  OCCT's readers ignore what follows the shape (verified for binary and ASCII BREP), so the payload stays a BREP
  to every reader. Geometry and CMF are cached and deduplicated together. Parts of one geometry and one CMF
  share one entry; a part in another CMF is another entry, which is accepted rather than optimised for.
- **CMF reaches a part from its source, its type parameters, and nothing else.**
  - Sources: the file, or the script or OpenSCAD model, converted by `cmfConvention`.
  - Every part type and every assembly type accepts the CMF type parameters `color`, `material` and `finish`.
    By default they fill in what the source leaves unset. `sourceCmf: drop` makes them replace everything the
    source states; it is meant for STEP, and honoured by every type whose source states CMF.
  - An assembly's CMF parameters propagate to its links as parameter values, and a link's own `params:` win.
    So a colour variant is an item of its own, with its own name, BOM line and order.
  - Nothing in an ASSY file states CMF other than through `params:`.
- **Scripts and OpenSCAD can state CMF.**
  - The build123d and CadQuery wrappers keep `.color`, `.material` and `.label`, `cq.Assembly` colours, and
    `show_object` colour options.
  - A `set_cmf(shape, color=…, material=…, finish=…)` helper is handed to scripts as `show_object` is.
  - OpenSCAD parts are exported as coloured 3MF where the OpenSCAD in use writes colours.
- **STEP CMF is complete or completed.**
  - STEP files are read through XCAF: face, solid and product colours, solid materials and densities, and the
    CAD tools' user attributes.
  - A STEP part's CMF parameters fill the elements its file leaves out, or replace the file's under
    `sourceCmf: drop`.
  - A STEP part to be made needs CMF on every solid and face, one way or the other.
  - In an imported STEP assembly, a colour overridden on one instance becomes `params:` on that link: the same
    variant mechanism as everywhere else, with no invented names.
- **Manufacturability checks CMF and its claims.**
  - A part to be made needs a material on every solid, and a colour on every face (a material may claim its
    natural colour). Each must resolve to a declaration with `manufacturable: true`.
  - An assembly that declares `vendor` and `sku` is checked by its own CMF declaration, which also decides how
    it is drawn. Its insides are not checked: it may use `location:`, or parts that are not manufacturable.
  - This starts as a warning.
- **Names that external specifications use.**
  - CMF declaration names may contain spaces and the other characters real CMF identifiers use ("RAL 3020",
    "Bright Red", "6061-T6").
  - The characters the parser gives a meaning to (`: ; , = #`, and `%` itself) are written percent-encoded in
    any name or parameter value. The parser splits first and decodes after, so it does not get more complex.
- **One presentation of CMF everywhere.**
  - Docs: a new "CMF" page under Digital Thread > Design, beside 3D, 2D and Drafting, plus a configuration
    reference for the three sections.
  - IDE: a CMF sub-tab under Design, and Color, Material and Finish columns in the BOM and Build vs Buy views.
  - CLI: `pc list colors` and `pc list finishes` beside `pc list materials`, and a CMF section in `pc info`.
  - Exports: STEP via XCAF; glTF, 3MF, URDF and MJCF materials.
  - All of them name and show the three components the same way.
- **LEGO, end to end.**
  - partcad-ldraw declares the colours LEGO actually makes (the `LEGOID` entries of LDraw's `LDConfig.ldr`),
    under LEGO's own names.
  - Its wrapper converts each triangle's LDraw colour, leaving `16` (the main colour) to the part's `color`.
  - A shortcut passes its colour on through parameters.
  - The examples declare short aliases of LEGO's colours and pass them through assembly and part parameters.
    No ASSY link states a colour.

Breaking changes follow "Branches, releases and breaking changes" in `docs/source/contributing.rst`: additive
and released first, then the index migrated, and the old form retired. Affected:

- hand-written `properties: color:` (moves to the `color` parameter);
- free-form colour names (converted to display-only colours, with a warning);
- every part's cache entry (rebuilt once with its CMF section);
- every checked-in render of a part that gains CMF.

## Capabilities

### New Capabilities
- `cmf-declarations`: colours, materials and finishes as declarations with display hints, `ids`,
  `manufacturable`, parameters and aliases; display colour versus CMF claim; `//pub/std/color`; naming and
  escaping.
- `cmf-assignment`: how CMF reaches a part (source, converters, type parameters, `sourceCmf`, assembly
  propagation) and how it is stored inside the BREP; item identity of CMF variants; scripts, OpenSCAD and STEP
  as sources.
- `cmf-conventions`: the single PartCAD convention and the `cmfConvention` converters from other tools.
- `cmf-manufacturability`: what "CMF specified" means for parts, STEP parts and purchasable assemblies, and how
  `manufacturable:` of each component counts.
- `cmf-presentation`: one representation of CMF in the IDE (Design > CMF), the CLI, BOM views, drawings,
  exports and documentation.

### Modified Capabilities
- None. The specs under `openspec/specs/` cover development process and documentation, not product data.

## Impact

- **Configuration and schema** (`src/partcad_utils/schema/partcad.json`):
  - `colors:` and `finishes:` sections, and a `cmfConventions:` section for converters;
  - `materials:` gains `display`, `ids`, `manufacturable`, `parameters`, `aliases`, alias declarations and a
    colour claim;
  - CMF type parameters on every part and assembly type;
  - wider names for CMF declarations;
  - percent-escaping in `partcad_utils/utils.py` (`parse_parameterized_name`, `format_parameterized_name`,
    `split_resource_path`).
- **Core**:
  - `material.py` generalised to the three kinds;
  - `part_factory.py` and `part_factory_homogen.py`: CMF moves to every type, `tolerance` stays homogeneous;
  - assembly factories (propagation);
  - `assembly_factory_imported.py` and `wrappers/wrapper_import_assy.py` (instance overrides as `params:`);
  - `shape.py` (canonical CMF in names and keys);
  - `plugin_provider_data_cart.py` and providers (CMF objects).
- **Payload**:
  - `wrappers/ocp_serialize.py`: write and read the CMF section;
  - a CMF summary in node `metadata` for consumers without the kernel;
  - `cache_shape.py` and the Chili3D end keep reading the payload as a BREP.
- **Sources**: `wrapper_step.py`, `wrapper_build123d.py`, `wrapper_cadquery.py`, `part_factory_scad.py`,
  `wrapper_import_gltf.py`, `part_factory_3mf.py`, and a new `//builtin/cmf` package of converters.
- **Consumers**:
  - `wrappers/appearance.py` becomes the CMF reader, with `ide/vscode/src/webview/appearance.ts` as its twin;
  - `render_svg.py`, `wrapper_gltf.py`;
  - `export_{step,gltf,3mf,urdf,stl}.py`.
- **Tests**: a `cmf` test in `pc test`; the connectivity test exempts purchasable assemblies.
- **UI**:
  - IDE: Design > CMF tab, BOM and BvB columns, explorer entries;
  - CLI: `pc list colors|finishes` and `pc info`.
- **Documentation**:
  - `digital_thread/lifecycle/design_cmf.rst` (new);
  - a CMF configuration reference (new);
  - `config_parts.rst` (MCFTT becomes CMF parameters), `config_assemblies.rst`, `config_output.rst`,
    `assy.rst` (`params:` carries CMF);
  - `cli.rst`.
- **Checked-in renders** under `examples/`, re-rendered by the PR that changes them.
- **Other repositories**:
  - partcad-index: `//pub/std/color` (RAL Classic and `rgba`), `//pub/std/finish`, and `manufacturable`/`ids`
    for `//pub/std/manufacturing/material`;
  - partcad-ldraw;
  - partcad-ldraw-examples.
