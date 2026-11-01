## ADDED Requirements

### Requirement: One PartCAD convention for CMF on a shape
On a shape, CMF SHALL be a palette of CMF sets. Each set SHALL hold:
- an optional canonical reference to a colour declaration, one to a material declaration and one to a finish
  declaration;
- the display values resolved for them;
- their origin.

Each solid SHALL have one material; each face SHALL have one colour and one finish, defaulting to its solid's.
Every reader of CMF in PartCAD SHALL read this convention and no other.

#### Scenario: A material on a face
- **WHEN** a source states a material on a single face
- **THEN** the converter assigns it to the face's solid if the whole solid agrees, and otherwise reports it as a
  finish or coating it cannot represent as a material, without inventing a material per face

### Requirement: Converters are chosen by `cmfConvention`
Every part and assembly type SHALL accept a `cmfConvention` parameter naming the converter that maps its source's
CMF into the PartCAD convention.
- Each type SHALL have a default (`step` for STEP files, `3mf`, `gltf`, `openscad`, `build123d`, `cadquery`,
  `ldraw`).
- Converters SHALL be implementations in a `//builtin/cmf` package, and a package SHALL be able to supply its
  own, the way it supplies a file type.
- `partcad` SHALL be the identity converter, reading CMF that PartCAD itself wrote.

#### Scenario: A STEP file from a known CAD tool
- **WHEN** a STEP part declares `cmfConvention: solidworks`
- **THEN** the material and appearance names and user-defined attributes SOLIDWORKS writes are read as that tool
  means them, and mapped to declarations

#### Scenario: A package's own converter
- **WHEN** a package declares a converter in its own `cmfConventions:` section, and a part names it
- **THEN** the part's source CMF is converted by that implementation

### Requirement: Converters map names through `ids`, and say what they could not map
A converter SHALL map each name or value the source states to a declaration, by that declaration's `ids` for the
convention. It SHALL search the part's own package and the packages its `catalogs` parameter lists. What it
cannot map SHALL become:
- for a colour, the display-only `//pub/std/color:rgba` of the stated value;
- for a material or a finish, unset, for the part's parameters to complete.

Each SHALL be reported once per part, naming the source value.

#### Scenario: An unrecognised STEP colour
- **WHEN** a STEP face is coloured RGB (0.8, 0.1, 0.05) with no name any declaration's `ids` matches
- **THEN** it carries `//pub/std/color:rgba;color=CC1A0DFF`, and a warning says the colour is display-only

#### Scenario: A vendor's material name
- **WHEN** a SOLIDWORKS STEP file names a solid's material `6061-T6 (SS)`, and a declaration in scope lists
  `ids: {solidworks: "6061-T6 (SS)"}`
- **THEN** the solid's material is that declaration

### Requirement: LDraw codes are converted as CMF triples
The `ldraw` converter SHALL map an LDraw colour code to a colour, a material and a finish:
- a rubber code to the LEGO colour in rubber;
- a transparent code to the LEGO colour in its transparent material;
- a chrome, pearlescent or metallic code to its finish.

It SHALL leave code `16` unset, so that the part's `color` completes it.

#### Scenario: A tyre
- **WHEN** a tyre's triangles are drawn in LDraw code 256
- **THEN** their colour is LEGO's black and their material is rubber, as partcad-ldraw declares them
