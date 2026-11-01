## ADDED Requirements

### Requirement: CMF is shown the same way everywhere
Every place PartCAD shows an item's CMF SHALL show the same three components, in the order colour, material,
finish. Each SHALL appear as its declaration's name with a swatch of its display value where the medium allows,
and marked when it is not manufacturable or not specified. Those places are:
- the IDE's Design > CMF tab;
- the BOM and Build vs Buy views;
- `pc info`;
- `pc list colors`, `pc list materials`, `pc list finishes`;
- the generated documents.

#### Scenario: The same part in the CLI and the IDE
- **WHEN** a user runs `pc info` on a part and opens the part's Design > CMF tab
- **THEN** both list the same CMF sets, with the same names, the same display colours and the same
  manufacturable marks

### Requirement: Design > CMF in the IDE
The IDE's Digital Thread SHALL have a CMF sub-tab under Design, beside 3D, 2D and Drafting. For a part, it SHALL
list the CMF sets with:
- their faces and solids;
- their origin (source, converted from which convention, declared, propagated, a material's colour claim).

Choosing a set SHALL highlight its faces in the 3D view. For an assembly, it SHALL list the CMF of every item,
grouped by item, with the items whose CMF is incomplete first.

#### Scenario: Finding an unspecified face
- **WHEN** a part to be made has faces without a colour, and the user opens Design > CMF
- **THEN** a row marked unspecified lists those faces, and choosing it highlights them

### Requirement: Drawings and viewers draw display values per face
The SVG, PNG and JPEG renderers and the IDE's 3D view SHALL draw each face in its CMF set's display colour. They
SHALL use the display default for faces with none. The 3D view SHALL use a finish's display hints (roughness,
metallic) where it has them.

#### Scenario: A two-colour part in a drawing
- **WHEN** a part with two CMF sets is rendered to SVG
- **THEN** its faces are drawn in the two display colours, and it is still one hidden-line drawing

### Requirement: Exports carry CMF where the format can
- The STEP export SHALL write, through XCAF: product structure and names; face, solid and product colours; solid
  materials with density; and the PartCAD CMF references as user-defined attributes, following the CAx-IF
  recommended practice.
- glTF SHALL write a material per CMF set.
- 3MF SHALL write base materials with display colours, assigned per triangle.
- URDF and MJCF SHALL write one visual or geom per CMF set.
- STL SHALL warn once that the format cannot carry CMF.

#### Scenario: A STEP round trip
- **WHEN** a part with per-face CMF is exported to STEP by PartCAD and read back as a `step` part with the
  `partcad` convention
- **THEN** every face and solid has the same CMF references as before

### Requirement: CMF is documented in one place
The documentation SHALL have a CMF page under Digital Thread > Design, beside 3D, 2D and Drafting. It SHALL
explain:
- the three components;
- claims versus display;
- sources and precedence;
- variants;
- conventions and converters;
- naming;
- what manufacturability requires.

A configuration reference SHALL document `colors:`, `materials:` and `finishes:` together. The parts and
assemblies references SHALL describe the CMF type parameters once, the same way, and link to it.

#### Scenario: A reader looking for how to colour a part
- **WHEN** a reader opens the parts reference
- **THEN** it lists `color`, `material` and `finish` as CMF parameters accepted by every type, and links to the
  CMF page for what they mean
