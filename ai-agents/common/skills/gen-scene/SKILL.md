---
name: gen-scene
description: Generate a PartCAD scene - a placed arrangement of objects such as a room, a building inside or out, a workcell, a desk laid out, an outdoor or underwater setting, or a world for a simulation - from a description. It gives the scene a bottom surface at or above z = 0 (none, and no gravity, in space), models each object as a `basic` primitive unless more detail is called for, places everything with `location:` and fixes it to the world unless it is mobile, stands a building's inside on floor plans (`walls` scenes) when only the inside is wanted and builds solid walls with their doors and windows when the outside is modelled too, and validates the result with the PartCAD CLI. Use for /pc:gen-scene or when the user asks to generate, create or lay out a scene, a room, an interior, a floor plan, a building, a workcell, an environment or a simulation world.
---

# pc:gen-scene

Generate a PartCAD **scene**: a placed arrangement of objects, such as a living
room, a house in its garden, a workcell, a table with things laid out on it, or a
world for a simulation. The text after the command (`$ARGUMENTS`) is the
description. *You* author the scene, and the parts it places, and prove the
whole of it **passes `pc test`**.

A scene uses the same ASSY file format as an assembly, and most of
`/pc:gen-assembly` carries over. What changes is the intent: a scene says
*where things are*, not how anything was put together. The rules below follow
from that.

**What a scene has to get right** is its surfaces: those seen from where the
scene is looked at, and those the objects placed in it rest on, stand against or
move through. It also has to get its physical conditions right: what is fixed and
what is free, the gravity, the medium. It does not have to be right *inside*. A
volume nothing sees or touches may be overlapping, rough or not manufacturable,
and the effort goes into the surfaces instead.

## 1. Scene or assembly?

| | Assembly | Scene |
|---|---|---|
| What it is | a product somebody put together | an arrangement: where things are |
| Declared under | `assemblies:` | `scenes:`, as `type: assy`, or `type: walls` for a floor plan |
| Placed by | connections, with `location:` as the fallback (`/pc:gen-assembly` §5) | `location:`, which is the whole statement |
| `connect:` / `connectPorts:` | attaches | places against the ports and attaches nothing |
| `how:` (assembly instructions) | yes | refused |
| `scene:` links (a scene inside it) | refused | yes |
| `fixed:` | ignored, with an error | welds what the link places to the world |
| In a simulation | attached: one rigid body, plus its joints | every element is a body of its own, and falls unless it is `fixed` |
| `gravity:`, `medium:` | no | yes |
| Overlaps (`pc test`'s `interference`) | a defect in the product | judged by what they touch (§6) |
| Manufacturable | when it is to be made | not a product: `manufacturable: false` by default |

So: a product, something that is *made* (a desk, a robot, a shelving unit),
belongs to `/pc:gen-assembly`. Where it stands, in a room or a workcell, belongs
here. A product that appears in a scene is an assembly placed by an `assembly:`
link. Generate it with `/pc:gen-assembly` first, or reuse one that exists.

## 2. Decompose

`$ARGUMENTS` is the description. Break it down into:

- **The setting.** It decides the bottom surface, the gravity, the medium, and
  how a building is built (§4):

  | Setting | Bottom surface (§4) | `gravity:` (m/s²) | `medium:` |
  |---|---|---|---|
  | a building: a room, a flat, an office, a shop, a house | the floor, or the ground it stands on | `[0, 0, -9.81]` | none |
  | outdoors: a garden, a car park, a site | the ground | `[0, 0, -9.81]` | none, or `fluid:air` where drag matters |
  | a workcell, a lab bench, a table laid out | the floor the bench stands on | `[0, 0, -9.81]` | none |
  | under water: a tank, a sea bed | the bottom of the tank, the sea bed | `[0, 0, -9.81]` | `fluid:water`, `fluid:seawater` |
  | the Moon, Mars | the regolith | `[0, 0, -1.62]`, `[0, 0, -3.72]` | none |
  | space, orbit, a space station's surroundings | **none** | `[0, 0, 0]` | none |

  The `medium:` values are `//pub/std/manufacturing/material/fluid:<name>`.

  "In space" has to be **said**, or be the obvious meaning of the
  description (a satellite, a space station, an asteroid field). Anything else
  stands on something.
- **For a building, whether its outside is part of the scene.** It is when the
  description has the building seen from outside, standing in something modelled
  around it (a garden, a street), or names its facade, its outside walls or
  its roof. It is not when what is wanted is the space inside: a room, a flat, an
  office floor, its furnishing. This decides between floor plans and walls of
  their own (§4).
- **The objects**: what each one is, how many of each, and its real size. Take
  the sizes from the description. Where it gives none, use the ordinary size of
  that kind of thing (a dining table is 750 mm high, a door is 2100 by 900 mm)
  and list every size you assumed.
- **Where each one goes**: against which wall, how far from what, facing which
  way, on top of what. Note every distance the description or a reference
  gives; §4 settles them on a layout sketch before any of them becomes a
  `location:`.
- **Which objects are mobile** (§5). Everything else is fixed.
- **What the scene is required to be**: "seats six", "a 1 m clear path from the
  door to the window", "the ball rolls down the ramp". It is written down in §5
  as the scene's `requirements:`, and a physical claim also becomes a
  `simulate:` (§7).

Clarify only the ambiguities that matter. Otherwise proceed, and state your
assumptions.

## 3. Inventory: reuse, or model as `basic`

First ask, once, whether an IDE is watching, as `/pc:gen-part` §2 does, and see
what already exists:

```sh
pc --no-ansi ide state > /dev/null   # fails, saying no PartCAD IDE is running, when there is none
pc --no-ansi list parts
pc --no-ansi list assemblies
pc --no-ansi list scenes
```

If an IDE is watching, the scene is shown in its 3D view as it takes shape (§6).
For an object somebody may already have modelled, use `/pc:search` on the
catalog as well: something reused is something nobody has to validate.

### Each object is a `basic` part, unless more detail is expected

By default, an object is **one `basic` part**: its bounding box (`cuboid:`), or
its bounding cylinder (`cylinder:`) for something round, at its real overall
size. There is no script and no sandbox, it takes the time it takes to type,
and it says exactly what a scene says: how much room the object takes, and
where.

```yaml
parts:
  <scene>/sofa:
    type: basic
    desc: A three-seat sofa, 2100 x 900 and 850 high, as its bounding box
    cuboid: [2100, 900, 850]                # along X, along Y, height
    offset: [[0, 0, 425], [0, 0, 1], 0]     # half its height: its base on z = 0
    manufacturable: false
    parameters:
      color: { type: string, default: ":fabric" }
```

- **Put the origin at the centre of the object's footprint, on its base.** A
  `basic` solid is built centred on the origin, so its `offset:` lifts it by half
  its height. A link's `location:` z is then the height of the surface the
  object stands on, and the turn about Z is the way it faces. Give the long
  side of a thing that faces somewhere (a sofa, a desk, a bed) along X, with
  its front towards -Y, so that every such object is turned the same way.
- **Declare one part per kind of object**, and link it as many times as there
  are of it: six chairs are one `<scene>/chair` and six links. Name parts
  `<scene>/<object>` so they sit together beside the scene, unless they are
  meant to be shared by several scenes. A name is one object of the package
  whatever its kind, so a part and the sketch it is made from cannot share one:
  `<scene>/south` and `<scene>/south-elevation`.
- **Give each kind of object a colour**, so a scene of boxes can be read, and so
  every kind is a layer of its own in an SVG render (§6). A colour that is only a
  picture says so:

  ```yaml
  colors:
    fabric:
      display: "#5A6E8C"
      manufacturable: false
  ```

- **Name the material of every mobile object**, with the `material` parameter
  as `/pc:gen-part` §5 does: its mass is what a simulation moves. A fixed object
  needs no mass, so naming its material is optional.
- `manufacturable: false` on each part, as `/pc:gen-part` §5 says.

More detail is in order where a surface the box does not have will be seen or
touched, and can reasonably be expected:

- the description asks for it, or names a particular model ("an Eames lounge
  chair", "a UR5 arm");
- the catalog already has the object. Reuse it, because the detail comes free;
- the object is what the scene is *about*: the robot in a workcell, the product
  in a showroom. The furnishing around it stays as boxes;
- something placed in the scene interacts with the shape: it rolls (a box does
  not, and a cylinder rolls only one way), tips over, nests, or uses the room
  under the object (the knee room under a desk that a chair is pushed into).

Then, in increasing order of effort: a few `basic` parts in a small assembly
(`/pc:gen-assembly`; a table is a top on four legs), or a part of its own
(`/pc:gen-part`). Say, for each object, which it is and why.

## 4. Lay it out

### The bottom surface

Unless the scene is in space, give it **a bottom surface** that everything rests
on, whose **underside is at z = 0 or above**. Every simulator writes its own
ground plane at z = 0, whatever the scene, so a floor that reaches below z = 0
starts inside that plane.

```yaml
parts:
  <scene>/floor:
    type: basic
    desc: The floor slab, 20 mm thick, its underside on z = 0
    cuboid: [6000, 4000, 20]
    offset: [[3000, 2000, 10], [0, 0, 1], 0]   # the slab spans z = 0 .. 20
    manufacturable: false
```

- It is the floor of a room, the ground outdoors, the sea bed, the deck of a
  ship. Make it as large as the footprint of what stands on it, plus a margin
  outdoors. Under a floor plan, it is exactly the plan (below).
- It is 20 mm thick unless the description says otherwise. Anything that stands
  on it is then at **z = 20**, and anything that stands on something else is at
  the height of the top of that.
- It is `fixed: true`, like everything else that does not move (§5).
- **In space there is none**, and the scene says `gravity: [0, 0, 0]`. Keep
  everything above z = 0 there too, because the simulators' ground plane is at
  z = 0 whatever the gravity.

### Buildings: the inside only, or the outside too

Which of the two §2 found decides how a building's walls are made.

**The inside only: floor plans.** A floor plan is a scene of type `walls`: the
walls of one room, standing on the outline of a sketch of its plan (see "Rooms:
the walls standing on a sketch" in `docs/source/config_scenes.rst`). Each wall
is drawn from inside the room and is see-through from outside, so the room can
be looked into from any side without taking anything away. That is exactly what
is wanted when nothing outside is modelled, and exactly what is not wanted when
something is, so a floor plan is only for this case. Where it is possible, make
**a single floor plan**, one outline around the whole of the space, and place it
in an `assy` scene with the floor and the furnishing (scenes may contain other
scenes):

```yaml
sketches:
  <scene>/plan:
    type: basic
    desc: The room from above, 4000 x 5000, its corner at the origin
    rectangle: { side-x: 4000, side-y: 5000, x: 2000, y: 2500 }

scenes:
  <scene>/walls:
    type: walls
    desc: The walls of the room, standing on its plan
    sketch: <scene>/plan
    height: 2700                               # from the floor to the ceiling

  <scene>:
    type: assy
    path: <scene>.assy
    desc: <the description>
    gravity: [0, 0, -9.81]
```

```yaml
# <scene>.assy
links:
  - part: <scene>/floor
    name: floor
    fixed: true
  - scene: <scene>/walls
    name: walls
    location: [[0, 0, 20], [0, 0, 1], 0]       # standing on the floor
    fixed: true                                # fixes every wall in it
  - part: <scene>/sofa
    name: sofa
    location: [[2000, 900, 20], [0, 0, 1], 0]
    fixed: true
```

- **The plan is a sketch of one closed outline** of lines and arcs, drawn from
  above, on XY. A rectangular room is a `basic` `rectangle:`, as above. Anything
  else (an L, a bay window, a round corner) is drawn with `/pc:gen-sketch` from
  the plan's dimensions. A `walls` scene refuses two outlines, a hole, an open
  outline and a spline, with the reason. A column in the room is an object
  standing in it, not a hole in the plan.
- **The floor is the plan made solid.** A rectangle is a `basic` cuboid at the
  plan's size and position. Any other outline is the plan extruded, which grows
  up from z = 0: `type: extrude`, `sketch: <scene>/plan`, `depth: 20`.
- **One outline cannot draw a wall inside it.** Where the space is several rooms
  and the walls between them matter, make one floor plan per room,
  `<scene>/<room>` on `<scene>/<room>-plan`, all drawn in the one frame of the
  whole space and so all placed at `[[0, 0, 20], ...]`. A wall two rooms share is
  then drawn twice, once facing each room, which is right for walls seen from
  one side.
- **Doors and windows.** A `walls` scene cannot cut them: it asks each wall for
  its `length`, `height` and `radius` and nothing else. Where they are asked
  for, write *that room's* floor plan as an `assy` scene of
  `//builtin/building:wall` links instead. They are the same one-sided walls,
  placed by the `walls` scene's own rule. Walk the outline **clockwise** as seen
  from above. The edge from P to Q is a wall at P, `length` |PQ| long, turned
  about Z by the edge's heading, `atan2(Qy - Py, Qx - Px)`. The wall's front is
  on the right of the walk, which is the inside of the room. For the 4000 x 5000
  room above:

  ```yaml
  # <scene>/walls.assy, declared as `<scene>/walls: {type: assy, path: <scene>/walls.assy}`
  links:
    - part: //builtin/building:wall
      name: wall-1
      params: { length: 5000, height: 2700, openings: "//<package>:<scene>/door" }
      location: [[0, 0, 0], [0, 0, 1], 90]
    - part: //builtin/building:wall
      name: wall-2
      params: { length: 4000, height: 2700 }
      location: [[0, 5000, 0], [0, 0, 1], 0]
    - part: //builtin/building:wall
      name: wall-3
      params: { length: 5000, height: 2700 }
      location: [[4000, 5000, 0], [0, 0, 1], -90]
    - part: //builtin/building:wall
      name: wall-4
      params: { length: 4000, height: 2700 }
      location: [[4000, 0, 0], [0, 0, 1], 180]
  ```

  `openings:` is a sketch, named in full (`pc list sketches` gives the
  package's path), drawn as if the wall were unrolled in front of you, seen from
  inside the room: X along it from its start, from 0 to `length`, and Y up from 0
  to `height`. One door is a `basic` `rectangle:` standing on y = 0. Several
  openings are a `/pc:gen-sketch` sketch. An arc wall is the same, with the arc's
  `radius`. Prove the hand-placed room is the room the `walls` scene would have
  placed with the walk in §6, run over both. Compare where each wall is and how
  long it is: the `walls` scene starts at another corner, and spells its numbers
  differently, so the names will not match.

**The outside too: walls of their own.** When the building is seen from
outside, its walls are what is seen, so they have to be solid and opaque from
both sides, and floor plans are no help. Model the outside **first**, the doors
and windows cut through it included, and check it from outside (§6) before
anything goes in. Each wall is a part of its own, an extrusion of the sketch of
its elevation with the openings as holes in it, and the walls are placed next to
each other along the building's outline:

```yaml
sketches:
  <scene>/south-elevation:
    type: basic
    desc: The south wall seen from inside, 6000 long and 2720 high from z = 0, with the door and a window
    rectangle: { side-x: 6000, side-y: 2720, x: 3000, y: 1360 }
    inner:
      rectangles:
        - { side-x: 1000, side-y: 2100, x: 1500, y: 1070 }   # the door: from the floor's top, at 20
        - { side-x: 1500, side-y: 1200, x: 4200, y: 1520 }   # a window, its sill 900 above the floor

parts:
  <scene>/south:
    type: extrude
    sketch: <scene>/south-elevation
    depth: 200                                  # the wall's thickness
    offset: [[0, 0, 0], [1, 0, 0], 90]          # stood up: along X, rising along Z, 200 thick towards -Y
    manufacturable: false
  <scene>/end-wall:                             # a wall with no openings needs no sketch
    type: basic
    cuboid: [4000, 200, 2720]
    offset: [[2000, -100, 1360], [0, 0, 1], 0]  # the same frame as the extrusion
    manufacturable: false
```

- **The outline is the outside face.** Walk it clockwise from above, as for a
  floor plan, and place the wall for the edge from P to Q at P, turned by the
  edge's heading. Each wall's thickness then lies to the right of the walk,
  inside the building. Its elevation is drawn as seen from inside: X from the
  wall's start, and a facade drawn from outside is mirrored,
  `x = length - x_outside`.
- **Stand every wall on z = 0, through the floor**, and draw its openings from
  the floor's top (its thickness, 20 above). A door that reached the bottom edge of
  the sketch would make a solid OCCT does not certify (`pc test` says so under
  `validity`). Drawn this way the door is a hole, and the strip under it is inside
  the floor slab, where nothing sees it.
- **Let the walls overlap at the corners.** Placed end to end on the outline,
  two walls share a thickness by thickness column at every outside corner. That
  is inside them, and harmless. At an inside corner (the inner corner of an L) the two
  leave a recess of that size inside the room instead. Lengthen the wall
  arriving there by its thickness where the recess can be seen.
- **A simulation does not see the openings.** MuJoCo collides with a part's
  convex hull, so a door is solid to it. Where something has to pass through
  one in a simulation, build that wall of convex pieces instead (§7).
- **Then the inside**, in the same frame: the walls between rooms are made the
  same way, 100 thick, with their doors as holes; then the furnishing. A roof or
  a ceiling, where the description has one, is a slab on top of the walls. Leave
  it out where the inside is meant to be seen from above.

### Settle the placements on a layout sketch

Where the description gives the distances between things (a clearance, a
gap, how far from a wall, a pitch), or a drawing or photo shows them, run
`/pc:gen-sketch` §3–§8 on a **layout sketch**, `<scene>/layout-top` (its §9),
before writing any placement, exactly as `/pc:gen-assembly` §3 does: each object
drawn as its footprint where its origin is going, turned the way its link will
turn it, and for a building, its outline drawn around them. Add an
elevation, `<scene>/layout-front`, only for what is stacked or hung: shelves,
a lamp over a table, a monitor on a desk.

Where the description gives no distances ("a cosy living room"), choose them:
the usual clearances (900 mm to walk past something, 600 mm in front of a
cupboard to open it), and the usual relationships (a sofa facing the screen,
chairs at the table). Write the table of them down all the same, so that §6
measures the result against something.

The positions the layout validates are the `location:` values.

## 5. Author the scene

### Place everything with `location:`

```yaml
- part: <scene>/table
  name: table
  location: [[2000, 3000, 20], [0, 0, 1], 0]   # on the floor: its top is at 20 + 750
- part: <scene>/vase
  name: vase
  location: [[2000, 3000, 770], [0, 0, 1], 0]  # on the table
```

- `location:` is the statement a scene makes, so it is not a fallback here, and
  `/pc:gen-assembly` §5 (replacing coordinates by connections) does not apply.
- Turn things about Z only, unless something really lies on its side.
- **Rest a thing on what carries it**, at the height of the top of what is
  under it. For a mobile object that is exact: never into what carries it,
  which a simulation shoots it out of, and never above it, which it falls from
  first. For a fixed one it matters only where it shows, and a box sunk a
  little into the floor is not worth a correction.
- `connect:` and `connectPorts:` are allowed, to place an object against
  another through ports both of them declare (a gripper on a robot's flange).
  They place and attach nothing, and `how:` is an error in a scene.
- Give every link a `name:`. It is what a filter, a render's `--filter`, the
  walk in §6 and the IDE call it.

### Fix everything that is not mobile

**Every link says `fixed: true`**, unless the description says that what it
places moves, or that obviously moves:

- **Mobile** (`fixed: false`): a ball, a vehicle, a cart, a drone, a robot
  vacuum, a person, an animal, and anything that is dropped, thrown, poured,
  pushed, stacked to topple or left to settle. So is anything whose staying put
  is what a claim says (§7), such as a stack that stands or a vase that does not
  tip: fixed, it could not fail, and the simulation would prove nothing.
- **Fixed** (`fixed: true`): furniture, appliances, machines, shelves, fittings,
  the floor, the walls, and whatever stands on a fixed thing and is not said to
  move. A sofa *can* be moved; that does not make it mobile in this scene.
- **An assembly with joints** (a robot arm, a cupboard with a hinged door) is
  fixed by its link, which welds its root to the world. Its joints still move.

Write `fixed: false` on a mobile link rather than leaving it out (free is the
default), so that every link shows that the decision was taken. Three rules
about where `fixed:` goes:

- `fixed: true` on a `scene:` link fixes **every** element inside that scene,
  mobile or not. A sub-scene that holds something mobile is not fixed as a
  whole: its own links say which of its elements are fixed.
- It is not read from the file's top-level node. Whether a scene is fixed is
  for whatever places it to say.
- Only `true` or `false`. A quoted `"yes"` is reported and taken as not fixed.

### The world: gravity and medium

State the world on the outermost scene: `gravity:` from the table in §2, written
out even for Earth's, and `medium:` where the scene is filled with something.
Sub-scenes need neither.

```yaml
scenes:
  <scene>:
    type: assy
    path: <scene>.assy
    gravity: [0, 0, 0]                      # in space: and no bottom surface
    # medium: //pub/std/manufacturing/material/fluid:seawater   # under water
```

### Scenes inside scenes

Beyond floor plans, group what **repeats** into a sub-scene of its own, as
`/pc:gen-assembly` §4 groups a product: a desk with its chair and its monitor,
eight times across an office, is `<scene>/desk-set` (`type: assy`) and eight
`scene:` links. A single object that repeats needs no sub-scene, only a part
linked several times. Keep the hierarchy flat otherwise. A sub-scene that
occurs once is not a piece.

### Declare it

Write `<scene>.assy` first, then declare it. `pc add scene` refuses a file that
does not exist yet:

```sh
pc --no-ansi add scene assy <scene>.assy
```

Then complete the declaration in `partcad.yaml`: the `desc`, the world, and what
the scene is required to be. A `walls` floor plan has no file, and is declared
by hand, as in §4.

```yaml
scenes:
  <scene>:
    type: assy
    path: <scene>.assy
    desc: <the description>
    gravity: [0, 0, -9.81]
    requirements:
      features:                     # what the description asked of the arrangement, a name and a sentence each
        seats-six: Six people can sit at the dining table at once
        clear-path: A clear path at least 900 mm wide from the door to the balcony
```

Leave out what nobody asked for, for the reason `/pc:gen-assembly` §3 gives. A
scene is not manufacturable and needs no `manufacturing:`.

## 6. Validate, render it from several angles, iterate

```sh
pc --no-ansi test -S <scene>
```

### Read the overlap warnings, and judge each one

A scene is not manufacturable, so its `interference` check **warns** rather than
fails, and `pc test` exits 0 over
`interference: 'table' and 'sofa' share 600000000.000 mm^3`. A warning is
information, not a verdict. Judge each one by the principle at the top: does the
overlap change a surface that is seen, or one that something placed in the scene
rests on, stands against or moves through?

- **Leave it** where it is inside volumes nothing interacts with: walls sharing
  a column at a corner, walls standing through the floor slab, a cupboard's back
  inside a wall, the box standing for a chair overlapping the box for the table
  it is pushed under. Bounding boxes overlap where the real things would not,
  and that is what a box is for.
- **Fix it** where it shows from where the scene is looked at (a vase sunk into
  a table, a sofa through a wall), where it changes a surface something rests
  on or moves along, and **always where a mobile object is in it**: a
  simulation starts with two bodies inside each other and pushes them apart
  violently.

Resting exactly on something bounds no volume, and is not reported. Report in
§8 which warnings were left and why.

Floor-plan walls are surfaces rather than solids, so the check passes over
them (`4 part(s) are not valid solids and were not checked: walls/wall-1, ...`),
which is expected. It also means nothing checks that an object stays inside a
room that is a floor plan. That is the top view's job, and the measurements',
below. Solid walls (§4) are checked like anything else.

### Prove each regrouping changed nothing

Moving objects into a sub-scene (§5), or replacing a `walls` floor plan by its
walls placed by hand (§4), must leave every object where it was. Walk the scene
down to its parts before and after, and compare the two lists as multisets. The
walk is `/pc:gen-assembly` §6's, with `ctx.get_scene("//<package>:<scene>")` in
place of `ctx.get_assembly(...)`, and it walks through `scene:` links the same
way.

### Look at it

Render **four** views, for the reason `/pc:gen-assembly` §6 gives: an object
offset along the line of sight sits perfectly in the one view that hides it.

```sh
for view in front top right iso; do
  mkdir -p /tmp/pc-render/$view                      # -O expects it to exist
  pc --no-ansi render -t png -S --view $view -O /tmp/pc-render/$view <scene>
done
```

A scene renders as one file, `<scene>.png`, with nothing written for its
sub-scenes. A name with a `/` in it is written into that subdirectory. Render a
sub-scene by its own name when it is what went wrong.

What a building looks like from outside depends on how it was built (§4).
A floor plan's walls are drawn from the side they face and not at all from
behind, so from outside the near walls are see-through and the far ones are seen
from inside: in `iso`, expect two walls, not four. From `top`, every wall is
edge-on and the picture is the plan. Solid walls are opaque: from outside you see
the facades with their doors and windows, the elevations mirrored, and the
inside only through the openings. Check the outside alone before anything goes
in, from each side a facade faces.

Check each view against the decomposition from §2:

- every object is there, as many times as it should be, and nothing else;
- each is where it belongs in all three axes, which only two views that share no
  viewing direction can confirm;
- each faces the way it belongs: the sofa towards the screen, the chairs to the
  table;
- each **stands on** what it belongs on: not sunk into it where that shows, and
  not floating above it (nothing reports that; look at `front` and `right`);
- everything is inside its room, and clear of the walls, in `top`;
- every door and window is where the description puts it;
- the bottom surface is under everything, and there is none in space.

### Measure the placements

Measure the rows of the layout's table on SVG renders with `measure.py`, in the
`/pc:gen-sketch` skill's directory, two objects at a time, exactly as
`/pc:gen-assembly` §6 does:

```sh
D=/tmp/pc-render/svg/top-<a>-<b>
mkdir -p $D
pc --no-ansi render -t svg -S --view top --no-reproducible -O $D --filter '[<a>, <b>]' <scene>
python3 <the /pc:gen-sketch skill's directory>/measure.py svg $D/<scene>.svg
```

Each colour is a layer of its own in the SVG (`Visible-5A6E8C`), which is one more
reason to give each kind of object a colour. Every row of the table has to be
within its tolerance. One that is not is a `location:` to correct from the
error, the way `/pc:gen-sketch` §8 reads it. Measure the openings on the
elevation sketches the same way, `/pc:gen-sketch` §7.

### Show each version that renders

Under an IDE (§3), show the scene in its 3D view each time it passes `pc test`
and its four views rendered, as `/pc:gen-assembly` §6 says, adding `--design-3d`
to the first show of the run:

```sh
pc --no-ansi ide view -S <scene>
```

Then correct, re-test, and re-render until every view matches the description.

## 7. Make the claim the description makes

Where the description says something physical about the scene (everything
settles where it is put, the stack of boxes topples, the ball rolls down the
ramp), declare it as a `simulate:` on the scene and check it with `pc sim`,
the way `/pc:gen-assembly` §7 does for an assembly, with the same `sim-mujoco`
dependency (`pc add dep sim-mujoco https://github.com/partcad/partcad-sim-mujoco.git`):

```yaml
scenes:
  <scene>:
    simulate:
      settles:
        desc: Switched on, nothing fixed moves and every loose object comes to rest where it was put
        feature: <the feature of its requirements this demonstrates>
        simulation: sim-mujoco:mujoco
        params: { samples: 20 }
        validation: |
          all(
              max(abs(a - b) for a, b in zip(after["bodies"][n]["pos"], before["bodies"][n]["pos"])) < 5.0
              and abs(sum(a * b for a, b in zip(after["bodies"][n]["quat"], before["bodies"][n]["quat"]))) > 0.996
              and max(abs(a - b) for a, b in zip(result["samples"][-1]["bodies"][n]["pos"],
                                                  result["samples"][-2]["bodies"][n]["pos"])) < 1.0
              and max(abs(w) for w in after["bodies"][n]["angvel"]) < 1.0
              for n in before["bodies"]
          )
```

No body moved more than 5 mm or turned more than 10° (`|q₀·q₁| > cos 5°`, as in
`/pc:gen-assembly` §7), none was still moving between the last two samples,
and none is still turning at the end (`angvel`, in deg/s). A position alone
would pass a body that tipped over about its own origin, and an orientation
alone one that is still rocking.

- **A run starts at rest**, where the scene places everything, and nothing
  moves anything but gravity, contact and the medium: there is no initial
  velocity, no motor and no controller. A claim driven by those can be shown:
  settling, toppling, sliding or rolling down a slope, sinking, rising. A claim
  that needs a push (a cart pushed, a ball thrown, a robot that moves) cannot.
  Tell the user so, rather than changing the scene until something passes.
- The scene is simulated as the subject of a world, by default
  `//builtin/scene:subject`, which places it where it stands. Its bottom
  surface is at z = 0 or above, so the entry needs no `offset:`.
- **The gravity and the medium are the world's, not the scene's own.** The
  default world states neither, so a scene simulated in it runs under Earth's
  gravity, whatever its own `gravity:` says. Whenever the scene's gravity is not
  Earth's, pass it to the run as well: `params: { gravity: [0, 0, 0] }` in
  space, `[0, 0, -1.62]` on the Moon, `[0, 0, -3.72]` on Mars. A medium needs a
  world that is filled with it: write one, as the `underwater` scene of
  `/pc:gen-assembly` §7, and name it in `scene: :<scene>/world`.
- **MuJoCo collides with convex hulls.** A part that is not convex is solid
  across its hull, so a wall's door and windows are filled in, and so is the
  notch of an L-shaped floor extruded from its plan. That only matters where
  something placed in the scene has to pass through or rest there. In that
  case, build that wall or floor of convex pieces: `basic` cuboids either side
  of an opening and above it, and a floor as rectangles.
- `pc --no-ansi sim --json -S <scene>` prints every body by name, before and
  after, which is what a claim about one object is written against.

When a claim fails, fix the scene, not the threshold.

## 8. Finalize

Summarize the scene:

- the setting, its bottom surface, its gravity and medium;
- for a building, whether its outside is modelled, and so whether it stands on
  floor plans or on walls of its own, with the doors and windows each has;
- every object, how many of each, which are `basic` stand-ins, and which have more
  detail and why;
- which objects are mobile;
- the layout's table (target, measured, error);
- what `pc test` and `pc sim` found, and each overlap warning left as it is, with
  the reason;
- every size and every placement you assumed;
- how to view it: `pc ide view -S <scene>`, which under an IDE is what is already
  on screen.

Offer `/pc:validate <scene>` (a scene) for a verdict on every requirement.

Remove the layout sketches (their declarations and their files, as
`/pc:gen-sketch` §9 says) unless the user wants them kept. Keep the plan, the
elevation and the openings sketches: the floor plans stand on them, and the
floors and walls are extruded from them.
