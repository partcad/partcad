## ADDED Requirements

### Requirement: CMF reaches a part from its source and its type parameters only
A part's CMF SHALL come from:
- what its source states (a file, a script, an OpenSCAD model), converted into PartCAD's convention by the
  type's `cmfConvention` converter; and
- the CMF type parameters `color`, `material` and `finish`.

By default the parameters SHALL fill only the components the source leaves unset. With `sourceCmf: drop` they
SHALL replace everything the source states. An ASSY link SHALL be able to affect CMF only through its
`params:`.

#### Scenario: A STEP file with one uncoloured solid
- **WHEN** a STEP part's file colours one of its two solids, and the part declares `color`
- **THEN** the coloured solid keeps the file's colour, and the other takes the declared one

#### Scenario: Overriding everything the file says
- **WHEN** the same part declares `sourceCmf: drop` and `color`, `material` and `finish`
- **THEN** every solid and face takes the declared CMF, and nothing the file stated remains

#### Scenario: A link that states a colour outside params
- **WHEN** an ASSY link carries a `color` key
- **THEN** `pc lint` reports it, and the build reports it with the instruction to pass it in `params:`

### Requirement: Every part type and every assembly type accepts the CMF type parameters
`color`, `material`, `finish`, `sourceCmf` and `cmfConvention` SHALL be object-type parameters accepted by every
part type and every assembly type, with the same meaning everywhere. `tolerance` SHALL stay accepted only by the
types that produce one homogeneous body.

#### Scenario: A STEP part with a material parameter
- **WHEN** a `step` part declares `material`
- **THEN** it is accepted, and fills the solids the file states no material for

### Requirement: An assembly's CMF parameters propagate as parameters
An assembly's CMF parameters SHALL be passed to each of its links as parameter values, for each CMF parameter the
link's own `params:` do not set. They SHALL propagate recursively. An item SHALL become the variant those
parameters name, with its own name, BOM line and supply question.

#### Scenario: A wall of grey bricks
- **WHEN** an assembly `wall` has links to `brick` with no params, and is linked as `wall` with
  `params: {color: ":stone"}`
- **THEN** every brick in it is the item `brick;color=<stone's canonical reference>`, and the BOM lists that item

#### Scenario: A link's own colour wins
- **WHEN** one link inside that wall says `params: {color: ":red"}`
- **THEN** that brick is red, and the others are stone

### Requirement: Imported STEP assemblies carry instance overrides as link parameters
When a STEP assembly overrides a component's CMF on one instance, the import SHALL write that CMF as `params:` on
the link to that instance. It SHALL NOT invent a part name for it.

#### Scenario: One black screw among silver ones
- **WHEN** a STEP assembly places a screw eight times and colours one instance black
- **THEN** the imported tree links seven screws with no CMF params and one with the black colour in its params

### Requirement: CMF is stored inside the BREP payload
A shape's payload SHALL be its BREP followed by a CMF section. The section SHALL hold:
- a palette of CMF sets (colour, material and finish references, with their display values);
- a material per solid;
- a colour and a finish per face, with a per-solid default.

Sub-shapes SHALL be addressed by their index in `TopExp::MapShapes` order. A reader that does not know the
section SHALL still read the BREP. The wrapper that builds the shape SHALL also record a summary of its CMF in the
node's `metadata`, for consumers that do not load the CAD kernel.

#### Scenario: An old reader
- **WHEN** a payload with a CMF section is read by OCCT's `BinTools`/`BRepTools`, or by an earlier PartCAD
- **THEN** it reads the same geometry, and ignores the section

#### Scenario: Shared when alike, separate when not
- **WHEN** two parts build the same geometry with the same CMF, and a third builds it with another colour
- **THEN** the first two share one payload, and the third has its own

### Requirement: Scripts and OpenSCAD state CMF
The build123d and CadQuery wrappers SHALL keep, per returned shape and sub-shape:
- `color` (as a display-only colour unless a CMF reference is given);
- `material` (as a material reference);
- `label`;
- `cq.Assembly` colours, and `show_object` colour options.

Scripts SHALL be handed a `set_cmf(shape, color=None, material=None, finish=None)` helper that attaches CMF
references. OpenSCAD parts SHALL be exported as 3MF with colours where the OpenSCAD in use writes them, and the
colours converted by the `openscad` convention.

#### Scenario: A build123d part with a painted face
- **WHEN** a script calls `set_cmf(face, color="//pub/std/color:RAL 9005")` on one face of its solid, and the part
  declares `color: "//pub/std/color:RAL 9010"`
- **THEN** that face is RAL 9005 and every other face RAL 9010

#### Scenario: An OpenSCAD colour
- **WHEN** a `.scad` model uses `color("red")` and the OpenSCAD in use exports coloured 3MF
- **THEN** those faces carry the display-only colour `#FF0000`, or the declaration the convention maps `red` to
