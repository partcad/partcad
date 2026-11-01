## ADDED Requirements

### Requirement: A part to be made has its CMF specified with manufacturable declarations
`pc test` SHALL check every part to be made (manufacturable and not purchased). It SHALL pass only if:
- every solid has a material;
- every face has a colour (a material's colour claim counts);
- a finish, if stated, is set;
- each of these resolves to a declaration with `manufacturable: true`.

The check SHALL name the solids or faces that fail, and the component and reason.

#### Scenario: A display-only colour
- **WHEN** a manufacturable part's faces are coloured `//pub/std/color:rgba;color=C91A09FF`
- **THEN** the CMF check fails, saying the colour is display-only

#### Scenario: Unpainted aluminium
- **WHEN** a manufacturable part's material declares a colour claim for its natural surface, and the part
  declares no colour
- **THEN** the CMF check passes

### Requirement: A STEP part to be made has CMF on every component, from its file or its parameters
For a `step` part to be made, every solid and face SHALL have complete CMF. The file's CMF, completed by the part's
CMF parameters (or replaced by them under `sourceCmf: drop`), SHALL be what is checked.

#### Scenario: A file with colours but no materials
- **WHEN** a manufacturable STEP part's file colours every face and states no materials, and the part declares
  `material`
- **THEN** the CMF check passes

#### Scenario: Neither
- **WHEN** the same part declares no `material`
- **THEN** the CMF check fails, naming the solids with no material

### Requirement: A purchasable assembly is judged by its own CMF declaration
An assembly (or its `enrich`) that declares both `vendor` and `sku` SHALL be checked by its own CMF parameters,
which SHALL be manufacturable declarations. Neither the CMF check nor the connectivity rule against `location:`
SHALL descend into it. Its CMF parameters SHALL decide how it is drawn, by propagation.

#### Scenario: A wheel sold assembled
- **WHEN** an assembly declaring `vendor` and `sku` places its rim by `location:`, and its tyre part declares no
  material, and the assembly declares `color` and `material`
- **THEN** it passes the CMF and connectivity checks, and it is drawn in its declared colour where its parts state
  none

### Requirement: The CMF check is introduced in stages
The CMF check SHALL be a warning when introduced, an error for packages that opt in, and an error by default only
after the public index passes it, following `docs/source/contributing.rst`.

#### Scenario: A package written before the check
- **WHEN** an existing package's parts state no CMF, during the warning stage
- **THEN** `pc test` passes and warns, naming each part and what it lacks
