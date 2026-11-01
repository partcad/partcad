## ADDED Requirements

### Requirement: STEP parts are read with their appearance and materials
A `step` part SHALL be read through XCAF, keeping:
- the colour of each face and each solid, as the file resolves them;
- the physical material of each solid (name and density);
- product and shape names.

Layers and user properties SHALL keep being read as they are today.

#### Scenario: A two-colour STEP part
- **WHEN** a STEP file states a red colour on one face of a solid whose own colour is grey
- **THEN** the part's appearance has that face red and every other face grey

#### Scenario: A STEP part with a material per solid
- **WHEN** a STEP file assigns a material with a density to each of two solids
- **THEN** each solid carries its material, and the part's mass is the sum of each solid's volume at its own
  density

### Requirement: STEP instance overrides become variants
When a STEP assembly overrides a component's appearance on one instance, the import SHALL keep that appearance
by making the instance a variant part of its own (`<part>@<style>`) and SHALL say so in a warning. It SHALL NOT
attach the appearance to the link.

#### Scenario: One screw drawn black among silver ones
- **WHEN** a STEP assembly places a screw product eight times and overrides the colour of one instance to black
- **THEN** the imported assembly links seven of the screw and one of a black variant of it, and a warning names
  the variant

### Requirement: STEP export writes structure, names, appearance and materials
The `step` exporter SHALL write an XCAF document built from the shape tree:
- one product per distinct item and one instance per placement;
- names;
- face, solid and part colours;
- physical materials per solid.

Reading the written file back SHALL yield the same appearance per face.

#### Scenario: Round trip
- **WHEN** a coloured STEP part is exported to STEP by PartCAD and the result is read back as a `step` part
- **THEN** every face resolves to the same colour, and the assembly structure and names are unchanged

### Requirement: Mesh and scene exports carry appearance where the format can
- glTF export SHALL write a material per style.
- 3MF export SHALL write a base material per style, assigned per triangle.
- URDF and MJCF exports SHALL write a multi-colour part as one visual or geom per style.
- STL export SHALL warn once that the format cannot carry colour.

#### Scenario: A two-colour part to glTF
- **WHEN** a part with two face styles is exported to glTF
- **THEN** the file has two materials with those colours, and every primitive references the material of its
  faces

### Requirement: LDraw parts are meshed with their colours
The `:ldraw` partType (partcad-ldraw) SHALL:
- carry each triangle's resolved LDraw colour code into the part's appearance;
- leave the faces of top-level code `16` without a style, so that they take the part's `color`;
- merge coplanar faces only within one colour.

#### Scenario: A printed tile
- **WHEN** a printed LDraw tile is built with `color=white`
- **THEN** its print's faces are the print's colours and every other face is white
