## ADDED Requirements

### Requirement: Colours, materials and finishes are CMF declarations of one shape
A package SHALL be able to declare colours in `colors:`, materials in `materials:` and finishes in `finishes:`.
Each declaration SHALL be addressed as `<package>:<name>`, with `:<name>` meaning the referring package. The
three kinds SHALL share one set of fields:
- `desc` and `url`;
- `display`: a visualisation hint;
- `ids`: identifiers in other systems and conventions;
- `manufacturable`: true unless stated;
- `parameters`;
- `aliases`.

Each kind SHALL add only its own facts: a colour nothing more; a material its physical facts (density,
friction, …) and an optional colour claim; a finish its process and surface texture specification.

#### Scenario: The three kinds listed alike
- **WHEN** a package declares a colour, a material and a finish
- **THEN** `pc list colors`, `pc list materials` and `pc list finishes` list them with the same columns:
  name, display, manufacturable, ids

#### Scenario: Texture is a finish
- **WHEN** a finish declares `texture: {vdi3400: "27"}`
- **THEN** a part with that finish carries the texture as part of its finish, and nothing else is needed to
  state it

### Requirement: A display colour is a hint, a colour declaration is a claim
A colour declaration SHALL state its display colour in any CSS colour notation, or as a reference to another
colour declaration (for example a RAL Classic one) whose display it takes. A display colour on its own SHALL NOT
make anything manufacturable. A declaration with `manufacturable: true` SHALL be a claim that the colour can be
sourced or manufactured.

#### Scenario: A vendor colour displayed through RAL
- **WHEN** a vendor declares `signal-red: {display: "//pub/std/color:RAL 3001"}`
- **THEN** it is drawn in RAL 3001's display colour, and it is manufacturable as the vendor's own claim

#### Scenario: CSS notations
- **WHEN** declarations state `display` as `#c91a09`, `rgb(201 26 9)`, `hsl(4 91% 41%)` or `firebrick`
- **THEN** each is read as the sRGB colour CSS Color Level 4 defines for it, and an unreadable value is a lint
  error naming the declaration

### Requirement: CMF declarations take parameters
A CMF declaration SHALL be able to declare `parameters:` like any parametric object. It SHALL be instantiated by
a parameterised reference (`<package>:<name>;<param>=<value>`), and its fields MAY be templated on those
parameters.

#### Scenario: A display-only colour on the spot
- **WHEN** a part declares `color: "//pub/std/color:rgba;color=C91A09FF"`
- **THEN** the part is drawn in `#C91A09`, and the colour is not manufacturable, because
  `//pub/std/color:rgba` declares `manufacturable: false`

### Requirement: CMF aliases
A CMF declaration SHALL be able to be an alias, `type: alias` with a `source:` reference (optionally
parameterised) to another declaration, possibly in another package. It SHALL also be able to list alternative
names of itself in `aliases:`. References through an alias SHALL resolve to the alias's target, and the target's
canonical reference SHALL be what enters an item's name and cache key.

#### Scenario: A short local name for a vendor colour
- **WHEN** a package declares `stone: {type: alias, source: "//pub/universe/lego:Medium Stone Grey"}` and links a
  brick with `params: {color: ":stone"}`
- **THEN** the brick's item name carries `color=//pub/universe/lego:Medium Stone Grey` (escaped as names
  require), the same item a package naming the vendor colour directly gets

### Requirement: Names that external specifications use, and escaping
A CMF declaration's name SHALL be able to contain spaces and printable characters other than `: ; , = # %` and
the pattern characters `* ? [ ]`, with no leading or trailing space. Any name or parameter value SHALL be able
to carry those characters percent-encoded (`%3A %3B %2C %3D %23 %25 %2A %3F %5B %5D`). The parser SHALL split on
the separators first and decode each component afterwards, and formatting a name SHALL encode the same set.

#### Scenario: RAL by its designation
- **WHEN** `//pub/std/color` declares `RAL 3020`, and a part declares `color: "//pub/std/color:RAL 3020"`
- **THEN** the reference resolves, and `pc info` shows the name as written

#### Scenario: A vendor name with a reserved character
- **WHEN** a vendor's material is called `PA12, glass filled`
- **THEN** it is declared and referenced as `PA12%2C glass filled`, and is displayed as `PA12, glass filled`

### Requirement: The standard catalogue uses industrial names
`//pub/std/color` SHALL declare colours under the names of industrial CMF specifications, starting with RAL Classic
by its designation (`RAL 3020`), with the specification's own name in `desc` and its id in `ids`. It SHALL ship
their display values only where the specification's terms allow publishing them. It SHALL declare the parametric
display-only `rgba` colour with `manufacturable: false`. It SHALL NOT declare colours whose specification's licence
does not allow publishing them (Pantone). A vendor package SHALL be free to declare its own colours under its own
names.

#### Scenario: Listing the standard colours
- **WHEN** a user runs `pc list colors //pub/std/color`
- **THEN** RAL Classic colours are listed by designation, and `rgba` is listed as parametric and not
  manufacturable
