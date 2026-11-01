## ADDED Requirements

### Requirement: A part in a colour is an item of its own
A part with a `color` value SHALL be a distinct item from the same part in another colour. It SHALL have its own
name (the parametric name `<part>;color=<value>`, or the name of an `enrich` that fixes `color`), its own BOM
line, and its own question to a supplier.

#### Scenario: A wall of two colours
- **WHEN** an assembly links `brick;color=red` 10 times and `brick;color=blue` 5 times
- **THEN** its BOM lists two lines, 10 and 5, and `pc supply quote` asks for each separately

#### Scenario: A named variant
- **WHEN** a package declares `brick-red` as an `enrich` of `brick` fixing `color: red`, and an assembly links
  `:brick-red`
- **THEN** the BOM lists `brick-red`, which resolves to the same appearance and geometry as `brick;color=red`

### Requirement: Colour variants share one geometry
The `color` object-type parameter SHALL NOT be handed to whatever builds a part's geometry (a script, a wrapper,
a partType), and SHALL NOT be part of the geometry cache key. It SHALL be applied to the part's declared colour
when the shape is stamped, on a fresh build and on a cache hit alike.

#### Scenario: The same brick in two colours
- **WHEN** `brick;color=red` and `brick;color=blue` are both built
- **THEN** the geometry is built once, both share one geometry cache entry, and each resolves to its own colour

#### Scenario: A script that reads `color`
- **WHEN** a script assigns `color` at its top level, during the deprecation period
- **THEN** it still receives the value, the part keeps `color` in its key, and a warning says the parameter will
  stop reaching scripts

### Requirement: A shortcut passes its colour to the parts it draws in its own
A shortcut assembly (an assembly a parts library serves for what it draws as one part) SHALL declare a `color`
parameter. It SHALL pass that parameter as a parameter value to the links of the parts its source draws in the
shortcut's own colour, and SHALL link the parts its source draws in fixed colours as those colour variants.

#### Scenario: A wheel with its tyre
- **WHEN** a model links the wheel shortcut `41896c01` with `color=light-bluish-grey`
- **THEN** the rim is `41896;color=light-bluish-grey`, the tyre is `41897;color=black`, and the BOM lists both
