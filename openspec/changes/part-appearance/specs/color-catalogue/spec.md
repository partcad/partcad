## ADDED Requirements

### Requirement: Colours are objects of a package
A package SHALL be able to declare colours in a `colors:` section. Each colour SHALL be addressed as
`<package>:<name>` and resolved the way a material is, with `:name` meaning the referring object's own package.

A colour SHALL carry:
- a display `value` (`#RRGGBB` or `#RRGGBBAA`);
- optionally a description;
- optionally `ids`: the colour's identifiers in other systems (for example `ral`, `lego`, `ldraw`, `bricklink`,
  `rebrickable`).

#### Scenario: A part names a catalogued colour
- **WHEN** a part declares `color: //pub/std/color/ral:traffic-red`
- **THEN** the part is drawn in that colour's `value`, and its cart item carries the colour object with its
  `ral` id

#### Scenario: A colour that does not resolve
- **WHEN** a part's `color` names a colour no package declares
- **THEN** the package reports the part as broken with the name it could not resolve, as it does for an
  unresolved material

### Requirement: A literal colour is display-only
A `color` value that is a literal `#RRGGBB` or `#RRGGBBAA` SHALL be accepted and drawn. It SHALL NOT be treated
as a specification a supplier can be asked for.

#### Scenario: A purchased part in a literal colour
- **WHEN** `pc supply quote` asks for a purchased part whose `color` is a literal
- **THEN** the quote proceeds as for an unspecified colour, with a warning that the colour specifies nothing a
  store can match

### Requirement: Suppliers are handed the colour object
A cart item SHALL carry the resolved colour object (name, value and ids), not the string the part declared.
Providers SHALL be able to match it by any id they know.

#### Scenario: A LEGO store orders the right element
- **WHEN** a store is asked for `//pub/universe/lego/ldraw/Brick:3004;color=red`
- **THEN** it receives the colour's `lego` id and can order the element for that design in that colour,
  instead of the cheapest colour

### Requirement: Free-form colour names are migrated, not broken
A `color` value that is neither a reference nor a literal (for example `red`) SHALL keep working through the
migration. It SHALL resolve against the part's own package and then the standard catalogue, with a deprecation
warning. It SHALL be retired only through the staged process in `docs/source/contributing.rst`.

#### Scenario: An existing package says `color: red`
- **WHEN** a package written before this change declares a part with `color: red`
- **THEN** the part resolves to the standard catalogue's `red` and a warning names the reference to use instead
