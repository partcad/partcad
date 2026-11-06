---
name: gen-scene
description: Generate a PartCAD scene - a placed arrangement of objects such as a room, a building interior, a workcell, a desk laid out, an outdoor or underwater setting, or a world for a simulation - from a description. It gives the scene a bottom surface at or above z = 0 (none, and no gravity, in space), models each object as a `basic` primitive unless more detail is called for, places everything with `location:` and fixes it to the world unless it is mobile, stands a building interior on floor plans (`walls` scenes, nested inside the scene), and validates the result with the PartCAD CLI. Use for /pc:gen-scene or when the user asks to generate, create or lay out a scene, a room, an interior, a floor plan, a workcell, an environment or a simulation world.
---

# pc:gen-scene

Generate a PartCAD **scene**: a placed arrangement of objects, such as a living
room, an office floor, a workcell, a table with things laid out on it, or a world
for a simulation. The text after the command (`$ARGUMENTS`) is the description.
*You* author the scene, and the parts it places, and prove the whole of it
**passes `pc test`**.

A scene uses the same ASSY file format as an assembly, and most of
`/pc:gen-assembly` carries over. What changes is the intent: a scene says
*where things are*, not how anything was put together. The rules below follow
from that.

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
| Manufacturable | when it is to be made | not a product: `manufacturable: false` by default |

So: a product, something that is *made* (a desk, a robot, a shelving unit),
belongs to `/pc:gen-assembly`. Where it stands, in a room or a workcell, belongs
here. A product that appears in a scene is an assembly placed by an `assembly:`
link. Generate it with `/pc:gen-assembly` first, or reuse one that exists.

## 2. Decompose

`$ARGUMENTS` is the description. Break it down into:

- **The setting.** It decides the bottom surface, the gravity, the medium, and
  whether there are floor plans:

  | Setting | Bottom surface (§4) | `gravity:` (m/s²) | `medium:` |
  |---|---|---|---|
  | a building interior: a room, a flat, an office, a shop | the floor, under the floor plans (§4) | `[0, 0, -9.81]` | none |
  | outdoors: a garden, a car park, a site | the ground | `[0, 0, -9.81]` | none, or `fluid:air` where drag matters |
  | a workcell, a lab bench, a table laid out | the floor the bench stands on | `[0, 0, -9.81]` | none |
  | under water: a tank, a sea bed | the bottom of the tank, the sea bed | `[0, 0, -9.81]` | `fluid:water`, `fluid:seawater` |
  | the Moon, Mars | the regolith | `[0, 0, -1.62]`, `[0, 0, -3.72]` | none |
  | space, orbit, a space station's surroundings | **none** | `[0, 0, 0]` | none |

  The `medium:` values are `//pub/std/manufacturing/material/fluid:<name>`.

  "In space" has to be **said**, or be the obvious meaning of the
  description (a satellite, a space station, an asteroid field). Anything else
  stands on something.
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
  door to the window", "the ball rolls off the table". It is written down in §5
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
  meant to be shared by several scenes.
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

More detail is in order where it can reasonably be expected:

- the description asks for it, or names a particular model ("an Eames lounge
  chair", "a UR5 arm");
- the catalog already has the object. Reuse it, because the detail comes free;
- the object is what the scene is *about*: the robot in a workcell, the product
  in a showroom. The furnishing around it stays as boxes;
- what the scene is for depends on the object's shape: it has to roll (a box
  does not, and a cylinder rolls only one way), tip over, nest, or leave room
  under itself (the knee room under a desk that a chair is pushed into).

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
  outdoors. Indoors, it is exactly the floor plan (below).
- It is 20 mm thick unless the description says otherwise. Anything that stands
  on it is then at **z = 20**, and anything that stands on something else is at
  the height of the top of that.
- It is `fixed: true`, like everything else that does not move (§5).
- **In space there is none**, and the scene says `gravity: [0, 0, 0]`. Keep
  everything above z = 0 there too, because the simulators' ground plane is at
  z = 0 whatever the gravity.

### Building interiors: floor plans

A building's interior stands on **floor plans**. A floor plan is a scene of type
`walls`: the walls of one room, standing on the outline of a sketch of its plan,
each wall seen from inside the room and see-through from outside, so a picture
taken from outside looks into the room (see "Rooms: the walls standing on a
sketch" in `docs/source/config_scenes.rst`). The interior is a scene of its own,
`type: assy`, which places the floor, the floor plans and the furnishing, since
scenes may contain other scenes:

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
  above, on XY, and in the interior's own coordinates. A rectangular room is a
  `basic` `rectangle:`, as above. Anything else (an L, a bay window, a round
  corner) is drawn with `/pc:gen-sketch` from the plan's dimensions. A `walls`
  scene refuses two outlines, a hole, an open outline and a spline, with the
  reason. A column in the room is an object standing in it, not a hole in the
  plan.
- **The floor is the plan made solid.** A rectangle is the `basic` cuboid above,
  at the plan's size and position. Any other outline is the plan extruded, which
  grows up from z = 0: `type: extrude`, `sketch: <scene>/plan`, `depth: 20`.
- **One floor plan per room**, `<scene>/<room>` on `<scene>/<room>-plan`, all
  drawn in the one frame of the whole interior and so all placed at
  `[[0, 0, 20], ...]`. A wall two rooms share is then drawn twice, once facing
  each room. That is right for walls seen from one side: from either room you
  see it, and from outside you see through it.
- **In a corner case, make a single floor plan, where that is possible.** That
  covers a space that is a building interior only at a stretch (a garage, a
  shed, a stage, a trade-show booth), an interior that could be divided into
  rooms several ways (open plan, a studio flat), or a request that is nothing
  but the room itself. Draw the whole enclosure as one outline, in one `walls`
  scene, rather than one floor plan per room, or none at all. It is still placed
  on its floor, and that floor is still the bottom surface. Where one outline
  cannot draw the space, fall back to one floor plan per room.
- **Doors and windows.** A `walls` scene cuts no openings. Where the description
  asks for them, write *that room's* floor plan as an `assy` scene of
  `//builtin/building:wall` links instead, placed by the `walls` scene's own
  rule. Walk the outline **clockwise** as seen from above. The edge from P to Q
  is a wall at P, `length` |PQ| long, turned about Z by the edge's heading,
  `atan2(Qy - Py, Qx - Px)`. The wall's front is on the right of the walk, which
  is the inside of the room. For the 4000 x 5000 room above:

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
  package's path), drawn as if the wall were unrolled in front of you: X along
  it from its start, from 0 to `length`, and Y up from 0 to `height`. One door is
  a `basic` `rectangle:` standing on y = 0. Several openings are a
  `/pc:gen-sketch` sketch. An arc wall is the same, with the arc's `radius`.
  Prove the hand-placed room is the room the `walls` scene would have placed
  with the walk in §6, run over both. Compare where each wall is and how long
  it is: the `walls` scene starts at another corner, and spells its numbers
  differently, so the names will not match.

### Settle the placements on a layout sketch

Where the description gives the distances between things (a clearance, a
gap, how far from a wall, a pitch), or a drawing or photo shows them, run
`/pc:gen-sketch` §3–§8 on a **layout sketch**, `<scene>/layout-top` (its §9),
before writing any placement, exactly as `/pc:gen-assembly` §3 does: each object
drawn as its footprint where its origin is going, turned the way its link will
turn it, and for an interior, the plan's outline drawn around them. Add an
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
- **Rest one thing on another exactly**, at the height of the top of what is
  under it: never into it, and never above it. Something that starts inside
  another is shot out of it as soon as a simulation starts, and something above
  it falls first.
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
  pushed, stacked to topple or left to settle.
- **Fixed** (`fixed: true`): furniture, appliances, machines, shelves, fittings,
  the floor, the floor plans, and whatever stands on a fixed thing and is not
  said to move. A sofa *can* be moved; that does not make it mobile in this
  scene.
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

**Read the output; do not go by the exit code.** A scene is not manufacturable,
so its `interference` check *warns* rather than fails: `pc test` exits 0 over
`interference: 'table' and 'sofa' share 600000000.000 mm^3`. Treat every
`share N mm^3` as a failure, and move one of the two objects. Resting exactly on
something bounds no volume, and is not reported.

Walls are surfaces rather than solids, so the same check passes over them
(`4 part(s) are not valid solids and were not checked: walls/wall-1, ...`),
which is expected. It also means **nothing checks that an object stays inside
its room**. That is the top view's job, and the measurements', below.

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

A wall is drawn from the side it faces and not at all from behind, so from
outside a room the near walls are see-through and the far ones are seen from
inside: in `iso`, expect two walls, not four. From `top`, every wall is edge-on
and the picture is the plan.

Check each view against the decomposition from §2:

- every object is there, as many times as it should be, and nothing else;
- each is where it belongs in all three axes, which only two views that share no
  viewing direction can confirm;
- each faces the way it belongs: the sofa towards the screen, the chairs to the
  table;
- each **stands on** what it belongs on: not sunk into it (interference reports
  that) and not floating above it (nothing reports that; look at `front` and
  `right`);
- everything is inside its room, and clear of the walls, in `top`;
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
error, the way `/pc:gen-sketch` §8 reads it.

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
settles where it is put, the ball rolls off the table, the stack of boxes
topples), declare it as a `simulate:` on the scene and check it with `pc sim`,
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
        validation: |
          all(
              max(abs(a - b) for a, b in zip(after["bodies"][n]["pos"], before["bodies"][n]["pos"])) < 5.0
              for n in before["bodies"]
          )
```

- The scene is simulated as the subject of a world, by default
  `//builtin/scene:subject`, which places it where it stands. Its bottom
  surface is at z = 0 or above, so the entry needs no `offset:`.
- **The gravity and the medium are the world's, not the scene's own.** The
  default world states neither, so a scene with `gravity: [0, 0, 0]` simulated
  in it falls under Earth's gravity. In space, pass the gravity to the run:
  `params: { gravity: [0, 0, 0] }`. A medium needs a world that is filled with
  it: write one, as the `underwater` scene of `/pc:gen-assembly` §7, and name it
  in `scene: :<scene>/world`.
- `pc --no-ansi sim --json -S <scene>` prints every body by name, before and
  after, which is what a claim about one object is written against.

When a claim fails, fix the scene, not the threshold.

## 8. Finalize

Summarize the scene:

- the setting, its bottom surface, its gravity and medium;
- every object, how many of each, which are `basic` stand-ins, and which have more
  detail and why;
- which objects are mobile;
- the floor plans, and the openings they have;
- the layout's table (target, measured, error);
- what `pc test` and `pc sim` found;
- every size and every placement you assumed;
- how to view it: `pc ide view -S <scene>`, which under an IDE is what is already
  on screen.

Offer `/pc:validate <scene>` (a scene) for a verdict on every requirement.

Remove the layout sketches (their declarations and their files, as
`/pc:gen-sketch` §9 says) unless the user wants them kept. Keep the plan
sketches and the openings: the floor plans stand on them, and the floors are
extruded from them.
