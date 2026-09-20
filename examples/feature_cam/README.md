# Route files: `pc cam`

`pc cam` writes the program a machine cuts an object with. It takes the object's
own outline, offsets it by the radius of the cutter, and cuts it at a series of
depths — a 2.5D route, which is what a CNC router does to sheet goods and what a
mill does to a plate.

```shell
pc cam
```

```
//pub/examples/partcad/feature_cam:nameplate: .../nameplate.nc
	engrave, 2 pass(es), 0.400 mm deep, 669.6 mm of cutting moves
//pub/examples/partcad/feature_cam:panel: .../panel.nc
	profile, 6 pass(es), 18.000 mm deep, 6434.5 mm of cutting moves
//pub/examples/partcad/feature_cam:tray_recess: .../tray_recess.nc
	pocket, 4 pass(es), 8.000 mm deep, 18428.9 mm of cutting moves
```

Three objects were routed. This package declares five.

## An object opts in by saying how it is made, and that is the whole of the opt-in

`pc cam` with nothing named produces a route for every sketch and part of the
package whose `manufacturing:` section names a machine or a job parameter, and
passes over every object that does not — silently. `spacer` in `partcad.yaml` is
here to be passed over: it is an ordinary part, identical to `panel` but for the
missing section, and a run over this package neither routes it nor complains
about it. `stock` is passed over for the same reason — it is the sheet the other
two are cut *out of*, bought rather than made.

That silence is deliberate. Most objects are never cut, and a package where
three parts of forty are is the ordinary case rather than thirty-seven warnings.
What *is* an error is naming one:

```shell
pc cam :spacer
```

```
ERROR: ...:spacer says nothing about being cut, so there is nothing to route
```

— because naming an object is asking about that object, and coming back with
nothing would look exactly like a route that went somewhere you did not notice.

An assembly and a scene are not routed at all, and cannot be. An assembly is put
together rather than cut, and a scene is an arrangement of things that were each
cut on their own, so neither has an outline a machine could follow.

## The three operations

Each says which side of the outline the tool runs on.

| | object | operation | what it does |
| --- | --- | --- | --- |
| `panel` | a 300 × 200 × 18 mm panel with two cable holes | `profile` | around the outside of the panel and the inside of each hole, so it survives at its nominal size |
| `tray_recess` | the 160 × 100 × 8 mm **void** of a tray | `pocket` | clears what is inside the outline, ring by ring |
| `nameplate` | a flat 120 × 40 mm sketch | `engrave` | follows the outline itself, offset by nothing |

**`profile` cuts the holes first.** A profile cut ends by separating the part
from its stock, and a hole cut after that is cut in something that is no longer
held. `panel.nc` starts at `X-93.000 Y0.000` — the cable hole at x = −100, with
a 6 mm cutter running 3 mm inside its 10 mm radius — and the panel's own outline
is the last thing in the file.

**`pocket` cuts the wall last**, for the opposite reason: the innermost ring
first means the finished wall is cut by a tool engaged on one side rather than
buried in a slot. `tray_recess.nc` starts at `X-31.200 Y1.200`, which is the
last ring that still has anything left of it, and works outward.

**`engrave` ignores the cutter's diameter**, because a V-bit and a drag knife
have no radius to compensate for. It is the one operation whose path is the
object's own geometry.

## What is configured where

The cutter, the depths and the feeds are one namespace with three layers, and
the narrower layer wins:

1. `//builtin/cam`, which PartCAD ships — a slow feed, a shallow pass, a
   generous clearance, and `direction: climb`.
2. this package's own `cam: gcode:` section, at the bottom of `partcad.yaml` —
   what this shop does: `feed: 2400 mm/min`, `safe_z: 8 mm`.

   `safe_z:` is a **clearance above the top of the object**, not an absolute
   height: the panel's top is at Z18, so its rapids are at `Z26.000` while the
   nameplate's — a sketch at Z0 — are at `Z8.000`.
3. the object's own `manufacturing:` section — what is true of that object, and
   nothing else. `panel` names a cutter diameter and a spindle speed;
   `tray_recess` also names a shallower pass and a stepover, because it is
   clearing an area rather than following a line.

So a package cutting twenty parts from one sheet says `diameter: 6 mm` once, and
the one part that needs a smaller cutter says so for itself.

**`diameter:` has no default, and must not get one.** Every other parameter has a
defensible default; the diameter of the cutter is the one number that cannot be
guessed from the part, and a route produced against a diameter nobody chose is
wrong by exactly the amount nobody noticed. A request that reaches the
implementation without one is refused and says where to set it.

### Two scopes inside that third layer

The object's section has a scope of its own, and it is the reason the machine is
named rather than assumed. A key written directly under `manufacturing:` is
shared by every machine the object names; a key written inside a machine's own
subsection — `cnc:`, `laser:`, `drill:` — belongs to that machine and outranks
the shared one. `nameplate` below uses both: its `speed:` is shared, everything
about the cut is under `cnc:`.

Naming several machines is naming **alternatives**, not stages: it says the
object could be made either way, `pc test` answers for both claims, and `pc cam`
has to be told which to write for —

```shell
pc cam -m laser :gasket   # writes gasket.laser.nc
pc cam -m cnc   :gasket   # writes gasket.cnc.nc
```

— because a default nobody picked is a program for the wrong machine. The two
files land beside each other rather than one overwriting the other. An object
that really is machined in *stages* is a chain of objects, each naming the
previous one as its `source:`. (No object here names more than one machine;
[`produce_part_subtractive`](../produce_part_subtractive/) has the one that
does.)

**Units are read, not assumed.** A length may be written `6`, `6 mm`, `0.25 in`
or `0.25"`, a feed `2400`, `2400 mm/min`, `40 mm/s` or `60 in/min`, a speed
`18000` or `18000 rpm`. A bare number is millimetres and millimetres per minute.
That conversion happens at every layer, so a `mm/min` written by the package is
understood as surely as one written on the object. What the *file* is written in
is a separate question, and the `units:` parameter of the `gcode` file type: a
part 18 mm thick is cut 18 mm deep whether the program says `G21` or `G20`.

`depth:` is the one key with a conditional default. A part that does not say is
cut **through** — from the top of its bounding box to the bottom, which for
`panel` is 18 mm in six 3 mm passes. A sketch has no thickness to be cut through,
so `nameplate` has to say how deep to score and is refused if it does not.

**A sketch's section has no `method:` and no `source:`.** A drawing is not made
out of anything — it is a path a machine follows — so `nameplate` declares the
machine and the job and nothing else. A *part* that says `method: subtractive`
does have to name the `source:` it is cut from, which is what `stock` is here
for, and what `pc test -f manufacturability` checks the part actually fits
inside.

## What comes out

Plain RS-274, as a `.nc` file beside the package:

```gcode
(PartCAD route)
(object: //pub/examples/partcad/feature_cam:panel)
(operation: profile climb, tool 6.000, depth 18.000 in 6 passes)
(units: millimeters)
G21
G90
G17
G94
M3 S18000
G0 Z26.000
G0 X-93.000 Y0.000
G1 Z15.000 F600
G1 X-93.038 Y0.732 F2400
...
M5
M30
```

**Every curve is G1 moves, not G2/G3 arcs.** An arc word is only an arc while
the plane it was written in survives the post-processor, and the `tolerance:`
parameter (0.01 mm by default) is one number that says exactly what the
approximation costs. Two of them would say less.

**The file is byte-stable.** Nothing in it is a timestamp, a host name or a
version, so the same object and the same parameters produce the same bytes on
any machine — which is what makes a route something a repository can hold and a
reviewer can diff. They are not checked in *here* only because nothing in this
repository regenerates them: the examples job renders, it does not route, so a
committed `.nc` would be a file that silently stops matching the part it came
from. See `.gitignore`.

**A spindle nobody commands is one the operator set.** An object that names no
`speed:` gets no `M3`/`M5`, because a router with a manual dial is still the
common case.

## The limits, which are real

**The outline is a section taken at the bottom of the cut.** For a prismatic
object — a panel, a plate, a gasket, anything cut out of stock of one thickness
— that is the same outline at every depth and there is nothing more to say. For
an object whose cross-section changes over the cut there is no single right
answer: following the widest gouges nothing but leaves material, following the
narrowest cuts into the part. `pc cam` follows the bottom and **says so**:

```
WARNING: ...: the outline changes over the depth of the cut
         (<area> mm2 at the top, <area> mm2 at the bottom);
         this route follows the one at the bottom
```

No object in this package triggers it — all three are prismatic over their cut,
which is the case a 2.5D route is exactly right for. Give `panel.py` a draft
angle or a chamfered edge and the warning appears. That warning is the point of
it. A route produced from an outline you did not
expect is the one failure that looks like a success all the way to the machine.

**A pocket may not have an island.** Material in the middle of a pocket is
material the route would have to leave, and leaving it means knowing where the
rings must stop rather than where they run out. An outline with a hole in it is
refused rather than cut through — cut the island as a `profile` of its own.

**A hole smaller than the cutter is refused** too, rather than skipped: there is
no path around the inside of it, and a hole silently missing from a route is
worse than a route that does not exist.

**There is no lead-in, no tab and no ramp.** The tool plunges straight down at
the start of each contour and the part is free at the end of the last pass. For
sheet goods that means fixturing or a sacrificial board, which is what you were
going to do anyway; for a part that must not move, cut it in two runs at
different depths.

**Nothing here knows about your machine.** The route is geometry, feeds and
depths; whether your controller wants this dialect is between you and it. A
controller that wants another is a package declaring a file type in its own
`cam:` section, and `camImplementation` — or `-i` — pointing at it.

## Running it

```shell
# every object of this package that says how it is made
pc cam

# one of them; `-s` when it is a sketch rather than a part
pc cam :panel
pc cam -s :nameplate

# one that names more than one machine, written for the one you pick
pc cam -m laser :gasket

# this package and everything it imports
pc cam -r

# somewhere else, and in somebody else's dialect
pc cam -O /tmp :panel
pc cam -i //some/package:gcode :panel

# as data, for whatever comes next
pc --no-ansi cam --json :panel
```

`--json` prints what was produced — the file, the implementation that wrote it,
and whatever that implementation counted about the route:

```json
[
  {
    "object": "//pub/examples/partcad/feature_cam:panel",
    "implementation": "//builtin/cam:gcode",
    "filepath": ".../panel.nc",
    "extension": "nc",
    "stats": {
      "operation": "profile",
      "paths": 3,
      "passes": 6,
      "depth": 18.0,
      "cut_length": 6434.503735078836
    },
    "warnings": []
  }
]
```

`pc cam` exits non-zero if any object it was asked about produced no route, and
reports every one of them rather than stopping at the first: a route is a file,
and an object whose section is wrong must not cost the other nineteen theirs.

### One thing that will waste your time

**The route is produced in the daemon's environment, not your shell's.** With a
daemon already running, anything you set in the environment to steer a run is
silently ignored. `pc daemon stop` first. The same warning `feature_cae`'s
README gives, for the same reason.

## `pc test -f cam` is the same thing, as a check

```shell
pc test -f cam
```

The check produces the route and passes the object only if one came back. It is
the same code this command runs, so the two cannot disagree about an object, and
it applies to an object that says how it is made and to nothing else — so
`spacer` is not applicable and a package of bolts pays nothing for it. An object
naming several machines is checked once per machine, because each of them is a
separate claim.

There is one way to pass: a route was written. A malformed section fails, an
implementation that cannot be resolved fails, and an implementation that
resolved and produced nothing fails — a cutter bigger than the hole it was asked
to cut, an outline the offset consumed. A machine that cannot provision a
sandbox at all is the one thing it does not hold against the object: nothing was
ever asked there, so it skips, loudly, and does not remember the skip.

**It does not keep what it produced.** An analysis writes its model beside the
package because the model is the answer somebody asked for; a route produced by
a check is a by-product, and one left here would be indistinguishable from the
`.nc` files above — read as current long after the part moved on. So the check
routes into a temporary directory and deletes it.

**The check that used to be called `cam` is `manufacturability` now.** It asks
whether an object *can* be made or bought at all — whether the geometry suits
the method it declares, whether what it is made from is reproducible, whether a
supplier could be found — which is a different question from whether a
post-processor can produce a program for it. Both are computer-aided
manufacturing, which is why one word answered for both until `pc cam` existed.
`-f` filters by name prefix, so `-f manufacturability` selects that check and
its three method-specific siblings, and `-f cam` selects this one alone.

## See also

- `pc render` — what the object *looks* like: [`feature_render`](../feature_render/)
- `pc export` — the object as a file another CAD tool opens: [`feature_export`](../feature_export/)
- `pc cae` — what the object does under load: [`feature_cae`](../feature_cae/)
- `pc supply` — having somebody else make it: [`provider_manufacturer`](../provider_manufacturer/)
