Each numbered section is one pull request against `devel` (or against partcad-ldraw / partcad-ldraw-examples
`main` where it says so). It is additive, and it is released before a later section depends on it.

## 0. Withdraw the link-colour approach

- [ ] 0.1 Close partcad/partcad#889 (`color:` on an ASSY link), with a comment pointing at this change
- [ ] 0.2 Close partcad/partcad-ldraw#23 and partcad/partcad-ldraw-examples#5. Keep their `LDConfig.ldr` extraction
      and the colour code per shortcut member for section 6.
- [ ] 0.3 Make the build report a `color` key on an ASSY link as an error that names the link and says to link a
      colour variant instead (the schema already refuses unknown keys for `pc lint`)

## 1. Envelope, resolver and drawing

- [ ] 1.1 `shape_envelope`: define the optional `appearance` key (styles, run-length faces, optional solids) and
      carry it through `placed`, `apply_metadata`, `strip_metadata`, `description` and the glTF form
- [ ] 1.2 `ocp_serialize.encode_shape`: accept `{face: style}` / `{solid: style}` keyed by shape identity and
      write indices in `TopExp::MapShapes` order. Decoding hands back the same mapping.
- [ ] 1.3 Test: face order is stable through encode/decode, `Moved`, `Located`, the shape cache, sharing by
      digest, and `wrapper_common.solidify` / `finished`
- [ ] 1.4 `wrappers/appearance.py`: the D4 resolution order (face → solid → declared → material → display
      fallback → default) and "specified" vs not. `split_by_color` splits leaves by face groups.
- [ ] 1.5 `render_svg.py`: project face groups together and draw each in its colour; document the shared-edge
      rule
- [ ] 1.6 `wrapper_gltf.py`: put sub-shape colours into the XCAF document. Verify how `SetMergeFaces` groups
      styled faces; merge per style if it does not.
- [ ] 1.7 IDE (`webview/appearance.ts`, `scene.ts`): keep a primitive's own glTF material; paint the node's
      appearance only on primitives without one. Mirror the resolver and test the twin as `DEFAULT_COLOR` is.
- [ ] 1.8 Docs: `config_parts.rst` Properties/MCFTT (appearance sources and order), `config_output.rst`
      (per-face colours in drawings)

## 2. STEP in

- [ ] 2.1 `wrapper_step.py`: read with `STEPCAFControl_Reader` (colour, name, material, layer modes). Build the
      face/solid style mapping with `XCAFPrs::CollectStyleSettings` and per-solid materials from
      `XCAFDoc_MaterialTool`. Bump `CACHE_VERSION`.
- [ ] 2.2 Measure the read time against `STEPControl_Reader` on the index's largest STEP files; record the
      numbers in the PR
- [ ] 2.3 Per-solid physical material: carry it in the solids table, and compute mass per solid at its own
      density
- [ ] 2.4 `wrapper_import_assy.py`: component appearance onto parts; an instance override becomes a
      `<part>@<style>` variant with a warning
- [ ] 2.5 Tests with small STEP fixtures: face colour, solid colour, inheritance, two materials, an instance
      override
- [ ] 2.6 Re-render `examples/` wherever a STEP part's colours now appear, and commit the images

## 3. Colour catalogue and the `color` parameter

- [ ] 3.1 Schema: `colors:` section (value, desc, ids); `color` parameter values are references, literals, or
      (deprecated) bare names
- [ ] 3.2 Lookup shared with materials (`<package>:<name>`, `:name`, bare name in the own package)
- [ ] 3.3 `PartFactory.OBJECT_TYPE_PARAMETER_PROPERTIES` gains `color`, resolved to the declared colour;
      `color` is left out of the geometry key and not handed to scripts or wrappers. A script that assigns it
      keeps receiving it, keeps it in its key, and is warned.
- [ ] 3.4 `partTypes:` entries may declare `accepts: [color]`
- [ ] 3.5 Cart and providers: `ProviderCartItem.color` is the resolved object; close the colour TODO in
      `plugin_factory_provider_manufacturer.py`; providers match by `ids`
- [ ] 3.6 Tests: two colours of one part share one geometry entry and are two BOM lines; an `enrich` variant
      equals the parametric one; an unresolvable colour breaks only its part
- [ ] 3.7 partcad-index: `//pub/std/color` (RAL Classic, CSS named colours); audit the index for scripts that
      read `color` and for free-form colour names
- [ ] 3.8 Docs: the MCFTT `color` entry (replacing "Not implemented yet"), a colour catalogue page, variants
      in `config_bom.rst`

## 4. Exports

- [ ] 4.1 `export_step.py`: build an XCAF document from the tree (products, instances, names, colours,
      materials) and write it with `STEPCAFControl_Writer`. Round-trip test against section 2.
- [ ] 4.2 `export_gltf.py`: materials per style (shared with 1.6)
- [ ] 4.3 `export_3mf.py`: base materials per triangle from face styles
- [ ] 4.4 `export_urdf.py` and MJCF: one visual or geom per style of a multi-colour part
- [ ] 4.5 `export_stl.py`: warn once when a coloured shape is written

## 5. Manufacturability

- [ ] 5.1 Material objects: optional `appearance` (colour reference or literal, and a finish)
- [ ] 5.2 `pc test` appearance check for parts to be made: a warning, an error under a package opt-in, and a
      message naming the faces or solids that are unspecified
- [ ] 5.3 `//pub/std/manufacturing/material`: natural appearance for the metals
- [ ] 5.4 Docs: what "specified" means, and why a multi-colour part needs a colour-defining file

## 6. LDraw (partcad-ldraw `main`)

- [ ] 6.1 `ldraw.py`: carry the resolved colour code per triangle (LDraw inheritance of `16`, ignore `24`);
      merge coplanar faces within one code; give an authored face its neighbours' code; emit the appearance
      with top-level `16` unstyled. Bump the wrapper's cache version.
- [ ] 6.2 The plugin serves `//pub/universe/lego/color` from `LDConfig.ldr` (values, alpha, LDraw/LEGO/BrickLink
      ids), and `:ldraw` declares `accepts: [color]`
- [ ] 6.3 Shortcuts: a `color` parameter passed to `16` members, with fixed-colour members linked as their
      variants (index: the colour code per member)
- [ ] 6.4 The LEGO stores order by (design, colour id)
- [ ] 6.5 Tests: a plain brick has no styles; 58121 has fixed-colour faces; a printed tile; a shortcut's BOM

## 7. LEGO examples (partcad-ldraw-examples `main`)

- [ ] 7.1 Generators declare the variants as `enrich` parts and link them; no ASSY file states a colour
- [ ] 7.2 Re-render, and update the README's BOM and buying sections (quotes now in the right colours)
- [ ] 7.3 Raise the `partcad:` floor to the release with sections 1 and 3, once the index pins section 6

## 8. More readers

- [ ] 8.1 glTF in: keep materials through the mesh-to-solid conversion
- [ ] 8.2 3MF in: base materials and colour groups per triangle
- [ ] 8.3 OBJ+MTL in (with a reader of PartCAD's own, since this OCP build has no `RWObj`)

## 9. Retire

- [ ] 9.1 Make the appearance check an error by default, after the index passes it
- [ ] 9.2 Stop accepting free-form colour names
- [ ] 9.3 Stop handing `color` to scripts
