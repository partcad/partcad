---
name: add-interfaces
description: Enrich an existing PartCAD part with connection interfaces and ports (mating metadata) so it can be mated to other parts automatically. Use for /pc:add-interfaces or when the user asks to add interfaces, ports, connectors, or mating information to a part, or to make parts snap/connect/assemble together.
---

# pc:add-interfaces

Add **interfaces**, **ports**, and **`implements:`** metadata to an existing
PartCAD part so PartCAD can mate it to other parts by connection rather than by
hand-placed coordinates. The text after the command (`$ARGUMENTS`) names the
target part (and, optionally, how it is meant to connect). *You* decide the
interface types and the exact port coordinates by examining the geometry, and
you prove they are right twice: by drawing them on the part itself
(`pc render --with-all`, step 4) and by mating two instances in a throwaway
assembly and rendering that (step 5). Hard requirement: the enriched part
**passes `pc test`** and the validation assembly renders **correctly
connected**.

Interfaces are the reusable half of this: define the connector once, then every
part that has that feature `implements:` it, and any two compatible parts mate.
Reference: `docs/source/configuration.rst` (the "Interfaces" and "Parts"
sections) and the `feature_interface` example (`connect-interfaces.assy`).

## 1. Resolve the part and how it connects

`$ARGUMENTS` is the object name (a part by default). Read its
`desc:`/`requirements:`/`summary:` from `partcad.yaml`. Make sure PartCAD is
available as `/pc:init` describes (`pc`, then `partcad`, then
`python -m partcad_cli.click.command`).

Decide **what connects to what**: which physical feature on this part joins to a
feature on another part (a bolt hole to a screw, a plug to a socket, a stud to a
receptacle, a rail to a slot). Each such feature becomes a **port**; a named set
of ports is an **interface**. A male feature and the female feature it enters are
two *different, complementary* interfaces that `mates:` each other.

## 2. Understand the geometry (render and/or read the source)

You need each connection feature's **position** and **orientation** in the
part's own coordinate frame, in millimeters. Get them two ways and cross-check:

- **Render it** to see orientation and where the origin sits:
  ```sh
  mkdir -p /tmp/pc-render
  pc render -t png -O /tmp/pc-render <part>        # one isometric PNG
  ```
  To see other angles, place the part at rotated `location`s in a throwaway
  `.assy` and render that. Run `/pc:describe` on the part for a written read of
  the shape.

  Once the part already has some ports, add `--with-ports` to see them drawn on
  that same picture — see "Look at the ports" below. That is also how you check
  a port you have just written before doing anything else with it.
- **Read the exact coordinates** from the source when you can — the CAD script,
  the STEP/BREP, or (for a generated/meshed part) the upstream data file. Exact
  numbers beat measuring off a render.

Confirm the origin and axes by reasoning about the render: where is (0,0,0), and
which way is "up" for *this* part (it is not always +Z — a mesh-imported part
can land with +Y up). Every port coordinate below is in this frame.

## 3. Design the interfaces and port coordinates

A **port** is an OCCT `Location`, `[[x,y,z],[ax,ay,az],angle_deg]`: translate to
`[x,y,z]`, then rotate `angle_deg` about axis `[ax,ay,az]`. Optionally give it a
`sketch:` (a 2D boundary) so it is visible when rendered.

Follow the **port-matching convention** so mates are unambiguous:

- Use the port's **Z axis** as the main direction. A **male** port's Z points
  **outward** (out of the material); the **female** port it enters has Z
  pointing **inward**. When two ports mate, their origins coincide and their Z
  axes are **opposite** — PartCAD flips the incoming part 180 deg about
  `[1,1,0]`, which sends `+Z -> -Z`.
- Orient each port's **X axis** toward the "next" equivalent port (right-hand
  rule). If several ports are interchangeable (e.g. the 4 corners of a bolt
  pattern, or a grid of studs), a consistent circular X orientation makes any
  aligned pair align all of them.

Useful consequence to place features precisely: if you orient the two ports so
the 180 deg flip cancels the rotation, the mated part ends up **translated by
`target_port_position - source_port_position`** with no rotation. So the mating
offset is carried entirely by the two port positions — put the female (receiving)
port on the part's own mating plane and the stacking/insertion depth falls out
automatically, per part. Verify any non-obvious orientation cheaply, without
rendering, using the pure-Python `partcad.geom.Location` (`__mul__`, `.inverse()`,
`.as_packed()`) against the assembly's mate formula
`target_loc * target_port * turn(180@[1,1,0]) * source_port.inverse()`.

Declare it in `partcad.yaml`:

```yaml
sketches:
  <port-boundary>:            # optional, for visualization
    type: basic
    circle: <radius>
interfaces:
  <male-iface>:
    desc: <what it is; note Z points outward>
    ports:
      <port>:
        sketch: <port-boundary>
    mates:
      <female-iface>:
        # freedom of movement, if any; omit or use 0 for a rigid seat
        moveZ: { min: 0, max: 0, default: 0 }
  <female-iface>:
    desc: <the complementary receptacle; Z points inward>
    ports:
      <port>:
        sketch: <port-boundary>
```

Interfaces can `inherits:` others (share ports/parameters) and declare
`parameters:` (`moveX/Y/Z`, `turnX/Y/Z`, or a custom `dir:`) for parametrized
mating such as a slotted hole. Reuse an existing interface if one already fits
rather than inventing a new one.

## 4. Attach the interfaces to the part with `implements:`

A part **implements** an interface, placing that interface's ports onto the
part. Place each occurrence with its own `Location`; use several named instances
to place the same interface at several spots:

```yaml
parts:
  <part>:
    # ...existing config...
    implements:
      <male-iface>:
        <instanceA>: [[x, y, z], [ax, ay, az], angle]
        <instanceB>: [[x, y, z], [ax, ay, az], angle]
      <female-iface>:
        <instanceA>: [[x, y, z], [ax, ay, az], angle]
```

**If the part is served by an external / plugin-backed package** (a dynamic
catalog with no static `partcad.yaml` entry to edit), do **not** try to edit the
source. Enrich it in a **consuming package** instead: add a `type: enrich` part
there that points at the upstream part with `source:` and carries the added
`implements:`. Enrich copies your `implements:` onto the resolved part:

```yaml
parts:
  <local-name>:
    type: enrich
    source: //path/to/upstream/pkg:<upstream-part>
    implements:
      <fully-qualified-iface-name>:      # e.g. //my/consuming/pkg:<male-iface>
        <instance>: [[x, y, z], [ax, ay, az], angle]
```

Use **fully-qualified** interface names in an enriched part's `implements:` (the
enriched part is instantiated in the upstream package's namespace, so a bare name
would resolve there, not in your package). For the consuming package to resolve
`//path/to/upstream/pkg:<part>`, that upstream package must be reachable from the
invocation root — the simplest arrangement is to make the consuming package a
sub-package of the upstream one and run `pc` from the upstream root. If `enrich`
cannot carry the metadata for a given part, fall back to a local wrapper
(`type: alias`, or a thin re-declared part) that adds the `implements:`.

### Look at the ports

`implements:` is what actually puts the ports on the part, so this is the first
moment there is anything to look at — and the cheapest check there is, before
any assembly exists. A port is a coordinate frame and an interface is a named
set of them, so neither shows up in an ordinary render; `pc render` draws them
when asked:

```sh
pc render -t png -O /tmp/pc-render --with-ports <part>        # every port marked and named
pc render -t png -O /tmp/pc-render --with-interfaces <part>   # every interface, joined to its ports
pc render -t png -O /tmp/pc-render --with-all <part>          # both
```

View the PNG and read it against what you wrote:

- Each port is a coordinate frame. The **long arrow is `+Z`** — the direction a
  part travels along when it is connected through that port. A male port's `+Z`
  points out of the material, a female port's points into it. An arrow pointing
  the wrong way is the single most common mistake, and it is obvious here.
- The frame sits at the port's origin. If it is off the feature it is supposed
  to name — beside the hole rather than in it, on the wrong face, at the part
  origin because the `location:` was omitted — the coordinates are wrong.
- The short arrows are `X` and `Y`: use them to check the roll convention (X
  toward the "next" equivalent port).
- `--with-interfaces` names each *instance* once and draws a line out to every
  port in it, so a bolt pattern that should be one interface with four ports
  reads as exactly that. Four separate names means four instances — usually not
  what was intended. The small outlines are the port boundary sketches.

Every port drawn is also listed in the log with the exact name to write in an
ASSY file — look for the `N port(s) drawn on the projection:` line and the
indented list under it. That is where the `with:`/`to:`/`withInstance:`/
`toInstance:` values below come from; do not guess them.

## 5. Validate by mating two instances and rendering

This is the real proof the coordinates are right. Scaffold a throwaway assembly
that connects two parts **purely through the interfaces**:

```sh
pc add assembly assy check.assy
```

```yaml
# check.assy
links:
  - part: <part-or //pkg:part>
    name: a
  - part: <the mating part>
    name: b
    connect:
      with: <b's interface>          # omit if unambiguous
      withInstance: <b's instance>   # if the interface has several
      name: a
      to: <a's interface>
      toInstance: <a's instance>
```

`connect:` mates by interface; `location`/`connectPorts`/`connect` are mutually
exclusive per node. Mark the assembly `manufacturable: false` so `pc test`
passes, then:

```sh
pc test -a <name>                                     # geometry instantiates + mates resolve
pc render -a -t png -O /tmp/pc-render <name>          # writes /tmp/pc-render/<name>.png
pc render -a -t png -O /tmp/pc-render --with-ports <name>   # the same, with every port drawn
```

**View the PNG** and check the two parts are actually connected the way the real
feature connects: mating faces touching, correct offset/grid, no unintended
interpenetration and no gap. A wrong port position shows up as a gap or overlap;
a wrong orientation shows up as the incoming part rotated or facing the wrong
way.

**Then view the `--with-ports` PNG**, which is what says *why*. On an assembly
the option walks every part and draws each one's ports where the assembly put
them, so the two ports that were supposed to mate are two frames on the same
picture:

- Connected correctly: the two frames sit on top of each other with their `+Z`
  arrows pointing in **opposite** directions.
- Two frames a fixed distance apart: the port position is off by exactly that
  much, on the part whose frame is not where the feature is.
- Two frames at the same place but with `+Z` arrows agreeing rather than
  opposing, or rolled against each other: the orientation is wrong, not the
  position.
- A frame nowhere near the feature it names: the `implements:` location is
  wrong, not the interface.

Names on the picture are the instance path (`<part-instance>:<port>`), and the
same list is written to the log, so you can tell which of two identical-looking
frames belongs to which part.

## 6. Iterate

Adjust the port coordinates/orientations and repeat step 5 until the render is
correct — no fixed retry count. Read the `--with-ports` render each time rather
than guessing from the plain one: it distinguishes a wrong position from a wrong
orientation, which the plain render does not. Re-check with a second instance
placed at a *different* port (an offset, not just the aligned case) to confirm
the whole interface is consistent, not just one lucky pair.

## 7. Finalize

Summarize the interfaces you defined (with the male/female Z convention), which
ports/instances you placed and where, where you stored them (the part's package,
or the consuming package for a plugin-backed part), and how to view a connected
example (`pc inspect -a <name>`, or
`pc render -a -t png --with-all <name>` for a picture with the connection
metadata on it).

If the part's ports are worth keeping a picture of — a catalog part other
packages will mate against — declare the drawing as a file type so `pc render`
keeps it up to date instead of leaving it to be redrawn by hand:

```yaml
parts:
  <part>:
    render:
      svg-with-ports:
        package: //builtin/render
        path: render_svg.py
        extension: ports.svg
        with_ports: true
```

See `examples/feature_interface`, which does exactly this for a part and for the
assembly it belongs to.
