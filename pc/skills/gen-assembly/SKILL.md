---
name: gen-assembly
description: Generate a PartCAD assembly (an ASSY that composes parts with placement and/or mates) from a description, generating or reusing the component parts and validating the result with the PartCAD CLI. Use for /pc:gen-assembly or when the user asks to generate or create an assembly, mechanism, or multi-part product.
---

# pc:gen-assembly

Generate a PartCAD **assembly**: an `.assy` file that composes parts (and
sub-assemblies) into one product. The text after the command (`$ARGUMENTS`) is
the assembly description. *You* author both the ASSY and its component parts and
prove the whole thing **passes `pc test`**. There is no legacy `ai` assembly
pipeline — this capability is new.

## 1. Decompose

`$ARGUMENTS` is the description. Break it into components and the
spatial/mechanical relationships between them: which parts, how many of each, and
how they attach to or move relative to one another. Clarify only load-bearing
ambiguities.

## 2. Inventory or generate the parts

```sh
pc --no-ansi list parts          # what already exists to reuse
```

Reuse existing parts; generate any missing component with the `/pc:gen-part`
flow. Each part must pass `pc test` on its own before you compose it.

## 3. Author the ASSY

Scaffold (this creates the empty file and the `assemblies:` entry), then write
`<name>.assy`:

```sh
pc --no-ansi add assembly assy <name>.assy
```

An ASSY file is a tree of nodes under `links:` (reference: PartCAD "Assembly YAML"
docs, `docs/source/assy.rst`).

**Container — the top level, and any grouping node:**

```yaml
name: <optional>
description: <the description>
location: <optional [[x,y,z], [ax,ay,az], angle_deg]>
links:
  - <node>
  - <node>
```

**Part node** — places a part; use **exactly one** placement method:

```yaml
# explicit placement (translation, then rotation of angle_deg about the axis):
- part: <part-in-this-package  or  //package:part>
  name: <optional instance name>
  location: [[x, y, z], [ax, ay, az], angle_deg]
```

```yaml
# OR connect by ports (no interface mating):
- part: <...>
  connectPorts:
    with: <this part's port, if it has more than one>
    name: <target instance already in the assembly>
    to: <target port, if the target has more than one>
```

```yaml
# OR connect by interfaces (universal mating):
- part: <...>
  connect:
    with: <this part's interface, if more than one>
    name: <target instance already in the assembly>
    to: <target interface, if more than one compatible>
    # optional disambiguation: withInstance / withPort / toInstance / toPort
```

`location`, `connectPorts`, and `connect` are **mutually exclusive** — pick one
per node. `with` names the interface/port on the part being added; `to` names it
on the part already in the assembly.

Both `connectPorts` and `connect` also take two optional sections that describe
the connection rather than place it:

```yaml
- part: <...>
  connect:
    name: <target instance already in the assembly>
    comment: <free form context for a human or an LLM; never parsed>
    how:
      stage: <label; consecutive nodes sharing it are connected at the same time>
      pushForceMax: <force in N, default 5>
      pushDistance: <staging distance in mm; default 1.5x the part's length along the interface Z>
      turnDirection: <cw (default) or ccw>
      turnTorqueMax: <torque in N*m, default 0>
      threadStep: <lead in mm per full turn, default 0.00>
      holdWith: <interface(s) to hold the part being added by>
      holdWithInstance: <instance(s) of holdWith>
      holdWithForceMin/Max: <force in N to hold it with, default 3/7; holdWithForce sets both>
      holdTo: <interface(s) to hold the target by>
      holdToInstance: <instance(s) of holdTo>
      holdToForceMin/Max: <force in N to hold the target with, default 3/7; holdToForce sets both>
```

`pushDirection` is not a field: it is deduced from the interfaces (an
interface's +Z points into the object it belongs to, which is the way an
incoming part travels) and reported with the rest.

Everything that is **required** to perform the assembly must be codified in
`how` and the other fields — never only in `comment`, which no tool reads. The
`hold*` fields default to the `connect:` section of the part or assembly
definition in `partcad.yaml`:

```yaml
parts:
  <name>:
    type: step
    connect: # (optional) what this part contributes to every connection
      hold: <interface(s) to hold it by>
      holdInstance: <instance(s) of hold>
      holdForceMin/Max: <force in N; holdForce sets both>
```

`threadStep` defaults to the thread of the interfaces being connected, declared
once on the interface that introduces it:

```yaml
interfaces:
  m3:
    threadStep: 0.5   # inherited by every interface that inherits m3
    selfScrew: false  # true when it cuts its own thread instead of matching one
```

Two connected interfaces must agree on `threadStep` unless one declares
`selfScrew`. Run `pc test -a <name>` to check that: it fails an assembly whose
instructions contradict themselves — a mismatched thread, or a `*Min` above its
`*Max` — and passes one that takes every default.

**Sub-assembly node** — identical to a part node but with `assembly:` instead of
`part:`, and it may carry its own nested `links:`.

Prefer `connect`/`connectPorts` when the parts define interfaces/ports; otherwise
use explicit `location`. Work in millimeters and degrees.

**Do not guess the names** `with:`, `to:`, `withInstance:`, `toInstance:`,
`withPort:` and `toPort:` take. Ask each part what it has, and read the exact
spelling out of the log:

```sh
mkdir -p /tmp/pc-render                                  # -O needs the directory to exist
pc render -t png -O /tmp/pc-render --with-all <part>
```

That draws every port of the part with its name, and every interface instance
with a line out to the ports that belong to it — and lists all of them in the
log, under the `N port(s) drawn on the projection:` line, which is the list to
copy from. `pc info <part>` reports the same names as text.

Then mark the assembly **not manufacturable** in `partcad.yaml` (it is generated,
not a catalog item) so `pc test` passes:

```yaml
assemblies:
  <name>:
    type: assy
    path: <name>.assy
    manufacturable: false
```

Do not add a `manufacturing:` section: `assy` is the only method an assembly has
and it comes with the type. (`additive`/`subtractive`/`forming` are ways of
making a *part* and mean nothing here.) Marking it manufacturable instead makes
`pc test` require that every part in it can be bought or made from a declared
supplier — only do that when that is true.

## 4. Validate, render it from several angles, iterate

```sh
pc --no-ansi test -a <name>          # build gate: geometry instantiates
```

That gate passes for an assembly whose parts are all in the wrong place, so the
design is decided by looking at it — and one picture cannot decide it. An
assembly is judged on *where* its components are, and position along the viewing
direction is precisely what a projection collapses: a part offset into the
screen, mirrored, or turned a quarter turn sits perfectly in the one view that
hides the error. Render **four** — `front`, `top` and `right` to place things in
all three axes, `iso` to see the product whole. A rendered file is named after
the object, so give each view a directory of its own or they overwrite each
other:

```sh
for view in front top right iso; do
  mkdir -p /tmp/pc-render/$view                     # -O expects it to exist
  pc --no-ansi render -a -t png --view $view -O /tmp/pc-render/$view <name>
done
```

Each view directory gets `<name>.png` plus one file per sub-assembly, since a
sub-assembly is an object in its own right. View all four of `<name>.png` — and
the sub-assemblies' own views when a nesting is what went wrong — and check
against the decomposition from §1:

- every component is there, as many times as it should be, and nothing else is;
- each one is where it belongs in all three axes — a placement is only confirmed
  by two views that share no viewing direction;
- each one is oriented as it belongs, including where a symmetric part hides it:
  a flipped bracket reads the same from the front and differs from the top;
- nothing interpenetrates that should not, and nothing floats where it should
  seat — a gap and a contact look alike from the front and separate from the side.

Add `back`, `left` or `bottom` when a component stays hidden behind another in
all four, and `--viewport-origin X,Y,Z` / `--viewport-up X,Y,Z` to look along a
joint no named view shows. `/pc:render` covers these options in full.

Where a component is in the wrong place and the ASSY uses `connect:` rather
than `location:`, the views tell you *that* it is wrong; the next section tells
you *why*.

### When a connection comes out wrong

A part in the wrong place tells you *that* a `connect:` is wrong, not *why* —
ports and interfaces are not geometry, so nothing about them is on the plain
render. Draw them:

```sh
mkdir -p /tmp/pc-render/ports
# Every port of every part. Add --with-interfaces for each interface joined to
# its ports, or --with-all for both.
pc --no-ansi render -a -t png --view iso -O /tmp/pc-render/ports --with-ports <name>
```

These write `<name>.png` like any other render, so an overlay needs a directory
of its own or it lands on top of the plain views from above — and `--no-ansi`
because the port names are reported on stderr, which is half of what makes the
picture readable.

On an assembly these walk everything inside it and place each child's ports
where the assembly put the child, so both ends of a connection are on one
picture. Each port is a coordinate frame whose **long arrow is `+Z`** — the
direction a part travels along when it is connected through that port — and each
is named `<part-instance>:<port>`.

Being a frame rather than geometry does not exempt it from what §4 is about: one
projection still collapses the axis a port is offset along, so two frames a
millimetre apart along the line of sight are drawn one on top of the other. When
the `iso` view leaves that ambiguous, render the overlay from the same four
views the geometry was checked from.

Read the picture:

- **Connected as intended**: the two frames coincide and their `+Z` arrows point
  in **opposite** directions.
- **A fixed gap between the two frames**: the connection resolved, but one of
  the parts places that port wrong. Fix the part's `implements:`, not the ASSY —
  and use `/pc:add-interfaces` for that.
- **Frames coincide but the part is rotated**: the ports met and the roll (their
  `X` axes) is what disagrees, or the wrong instance of a symmetric interface was
  picked. Pin it with `withInstance:`/`toInstance:`.
- **The part did not move at all**: the `connect:` named something that does not
  exist or is ambiguous. The log lists every port drawn, with its exact name —
  compare it against what the ASSY says.
- **Two parts connected through the wrong pair**: `--with-interfaces` shows
  which ports each interface instance owns, which is what a `connect:` selects
  by. If a bolt pattern shows up as four separate instances rather than one with
  four ports, the interface is declared wrong.

Iterate on the `--with-ports` render, not the plain one, for as long as a
connection is the thing being fixed. A part whose own port is in the wrong place
is fixed in the part, not in the ASSY — render that part on its own with
`--with-all` (`/pc:add-interfaces` covers reading it) before touching the
assembly that uses it.

Then adjust the placements or mates, re-test, and re-render. Iterate until every
view matches. `pc inspect -a <name>` gives an interactive view.

## 5. Finalize

Summarize the structure — parts, sub-assemblies, key placements — and how to view
it (`pc inspect -a <name>`, or `pc render -a -t png --with-all <name>` for a
picture with the connection metadata on it).

For an assembly whose connections are worth keeping a picture of, declare the
drawing as a file type so `pc render` keeps it up to date along with everything
else:

```yaml
assemblies:
  <name>:
    render:
      svg-with-ports:
        package: //builtin/render
        path: render_svg.py
        extension: ports.svg
        with_ports: true
```

`examples/feature_interface` does this for a part and for the assembly it
belongs to.
