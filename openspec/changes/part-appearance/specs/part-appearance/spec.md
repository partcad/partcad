## ADDED Requirements

### Requirement: A part's appearance comes from its definition alone
A part's appearance SHALL come only from:
- the colour-defining file the part is read from; or
- the colour declared for the whole part by its `color` object-type parameter (or, for a part type that
  accepts none, its declared `properties: color:`).

Nothing an assembly says SHALL change a part's appearance as product data.

#### Scenario: An ASSY link names an item and nothing about how it looks
- **WHEN** an ASSY file's link carries a `color` key
- **THEN** `pc lint` reports it as a schema error, and the build ignores it with an error naming the link and
  saying to link a colour variant of the part instead

#### Scenario: The same part placed twice looks the same twice
- **WHEN** an assembly places one part twice
- **THEN** both placements resolve to the same appearance, face for face

### Requirement: Multi-colour parts come only from colour-defining formats
A part SHALL have more than one appearance across its faces only when its part type reads a format that defines
appearance per face or per solid (STEP AP214/AP242 and LDraw first; 3MF, glTF and OBJ+MTL as their readers
land). Any other part type SHALL produce a part of at most one colour.

#### Scenario: A script colours a sub-shape
- **WHEN** a `build123d` script returns a shape whose sub-shapes carry their own `.color`
- **THEN** those colours are not used, a warning says the part is one homogeneous body and takes one colour
  through its `color` parameter, and the part resolves to its declared colour or none

#### Scenario: A STEP file colours its faces
- **WHEN** a `step` part's file states a colour on some faces and another on its solid
- **THEN** each face resolves to its own colour where it has one and to its solid's otherwise

### Requirement: Shapes carry per-face and per-solid appearance beside their geometry
A shape node SHALL be able to carry an `appearance` entry: a palette of styles, a style per face in
`TopExp::MapShapes(TopAbs_FACE)` order, and optionally a style per solid. The producing wrapper SHALL write it,
it SHALL be cached in the same entry as the geometry it describes, and the core SHALL carry it unchanged.

#### Scenario: Appearance survives the cache
- **WHEN** a part with per-face appearance is built, cached, and materialized from the cache in another process
- **THEN** every face resolves to the same style it had when it was built

#### Scenario: Placing a node keeps its appearance
- **WHEN** an assembly places a part with per-face appearance at any location
- **THEN** the placed node's faces resolve to the same styles as the part's own

#### Scenario: Old envelopes mean what they meant
- **WHEN** a node has no `appearance` entry
- **THEN** it resolves exactly as it did before this change

### Requirement: One resolution order, applied by every consumer
A face's appearance SHALL be, in order:
1. its face style;
2. its solid's style;
3. the part's declared colour;
4. its material's natural appearance;
5. the display default `#DAA520`.

Steps 1-4 make a face *specified*; step 5 does not. An assembly's own `properties.color` SHALL apply only as a
display fallback before step 5, and SHALL never make a face specified. The SVG, PNG and JPEG renderers, the
IDE's Digital Thread and every exporter SHALL resolve appearance through this one order.

#### Scenario: A face with no style of its own
- **WHEN** a face has no style, its solid has none, and the part declares `color`
- **THEN** the face is drawn in the declared colour and counts as specified

#### Scenario: The renderer and the IDE agree
- **WHEN** the same part is rendered to SVG and shown in the Digital Thread
- **THEN** each face is the same colour in both

### Requirement: A part to be made has a complete appearance
`pc test` SHALL check that every face of a part to be made (manufacturable and not purchased) resolves through
steps 1-4 of the resolution order. The check SHALL start as a warning and become an error only through the
staged process in `docs/source/contributing.rst`.

#### Scenario: A printed part with no colour
- **WHEN** a manufacturable `build123d` part made of a material with no natural appearance declares no `color`
- **THEN** `pc test` reports that the part's appearance is unspecified

#### Scenario: A machined aluminium part
- **WHEN** a manufacturable part declares no `color` and its material declares a natural appearance
- **THEN** the appearance check passes

### Requirement: Derived views may highlight without changing items
A shape derived for documentation (an instruction book's step, an interference artifact) MAY stamp a display
colour on the nodes it holds. Such a view SHALL NOT be an item, and SHALL NOT be cached as one.

#### Scenario: The instruction book highlights a step
- **WHEN** an instruction book draws the parts added at a step in a highlight colour
- **THEN** the parts' own appearance is unchanged everywhere else, including in the BOM and exports
