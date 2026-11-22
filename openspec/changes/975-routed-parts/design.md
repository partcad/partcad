# Design

## Context

- **Placement today:** `AssemblyFactoryAssy.handle_node_list` places each link once, in
  order. A `connect*` link waits for the links above it, then is placed against one
  of them. `placement_refusals` refuses targets that are listed later.
- **Connections:** `handle_node` resolves a `connect:` or `connectPorts:` section to
  a target location, two ports and two interfaces, then calls `compose_connection`
  (`assembly_factory_assy.py:1717`). That is plain-Python rigid-transform algebra
  (`partcad.joint`, `geom.Location`): the target port, turned to face the source,
  offset by the connection's parameters, and pulled back by the source port. The
  mating between the two interfaces, if any, is found by `_mating_between`.
- **Port direction:** this is a convention, not a rule. `config_interfaces.rst`
  only suggests that male ports point their Z axis out and female ports in, and
  the unit tests declare "+Z into its part". Two ports meet when their Z axes are
  opposed (`resolve_also`). PartCAD has no notion of male or female.
- **Existing precedent:** `resolve_also` runs after the whole list is placed. It
  composes `child.location * port_location(port)` into world poses, and records
  the result for the instruction book.
- **Part identity:** a part is fetched per link through
  `ctx._get_part_async(name, params)` and cached by a hash of its config and
  params.
- **Sweeping:** `PartFactorySweep` / `wrapper_sweep.py` sweep a sketch along a
  Bezier curve in the OCP sandbox. Envelopes cross as BREP.

See proposal.md for the motivation and specs/routed-parts/spec.md for the
behaviour.

### Relation to `sweep`

Both sweep a profile along a path in the OCP sandbox. What `routed` adds is that
the assembly works out the path:

| | `type: sweep` | `type: routed` |
|---|---|---|
| Path | Written in the part (`axis` / `axisCoords`). A Bezier curve uses the points as control points, so it passes through only the first and last one | Worked out from the end frames, `lead` and `via` points. A spline that passes through all of them |
| Frame | The part's own frame. Placed afterwards | The frame of its `links:` list. The geometry *is* the placement |
| Ends move | The axis has to be edited by hand | Rerouted on the next build |
| End directions | Uncontrolled | Whatever the end's connection makes them, exactly as for a part placed there |
| Profile | A sketch, used as drawn at the origin. `MakePipe` per face | A round section or a sketch, placed in the first end's frame and rolled to meet each port's X axis. `MakePipeShell` along the computed frames |
| Built | With the other parts, before placement | In a second pass, after its list is placed |
| One part, many links | Same geometry each time | A different geometry per link, cached per route |
| A path that cannot carry the profile | `MakePipe` raising is a part error. A self-intersecting result goes through, with at most a warning (the `validity` check only reports) | Refused before sweeping, and an invalid result is an error (D9) |
| Checks, scripts, tree reach | — | `length` / `minBendRadius`, the `route` parameter, `reactor/core` paths |

### Nothing builds after placement yet

Three steps run after a list is placed today: `resolve_also` checks
`alsoConnectPorts`, `apply_root_placement` moves the whole assembly, and
`name_joints` makes joint names unique. None of them creates or builds a child.
The route pass is the first to build a part there, so:

- a sub-assembly's routes have to be final when that sub-assembly is (D2);
- the route pass runs before `resolve_also`;
- nothing that reads `assembly.children` during the first loop may expect to see
  routed children. Only connection targets do, and those are refused.

## Goals / Non-Goals

**Goals:**
- Resolve route ends with the very code that places connected parts, so that an
  end and a part plugged into the same port can never disagree.
- Compute the path deterministically, in pure Python, so that the geometry, the
  feasibility checks and the `pc qual test` metrics all come from one curve that
  can be unit-tested without OCP.
- Never add a routed solid that is known to be wrong.
- Give routed links the same caching as any part.

**Non-Goals:**
- Keep-out, collision avoidance with other parts, solving to a given length, and
  automatic rerouting of a path that cannot be built.
- Branching routes (a Y-splitter).
- Links placed against a routed part, and joints at route ends.
- Ends that reach up out of the assembly being built.

## Decisions

### D1. Ends are connections of the routed part itself (option B)
A route end is a `connectPorts:` or a `connect:` section, unchanged in meaning,
whose `with` side is a port or interface of the routed part:

```yaml
parts:
  silicone-tube-6x4:
    type: routed
    diameter: 6
    innerDiameter: 4
    implements:
      push-fit-6mm-tube: [[0, 0, 0], [0, 0, 1], 0]   # the tube end itself mates

# ASSY
- part: silicone-tube-6x4
  route:
    ends:
      - connect: {with: push-fit-6mm-tube, name: manifold, to: push-fit-6mm}
        lead: 15
      - connectPorts: {name: reactor/core, to: inlet}
    via: [[0, 0, 120]]
```

All ports and interfaces of a routed part are declared in one frame, the end
frame: origin at the cable's end face, +Z along the cable. Each end's frame is
the placement that end's connection alone would give the whole part. An end that
gives no `with` is connected as if by a port at the origin of that frame, so a
plain tube declares no ports and names none:

```yaml
- part: silicone-tube-6x4
  route:
    ends:
      - connectPorts: {name: pump, to: outlet}
      - connectPorts: {name: reservoir, to: inlet}
```

Ports are declared only for ends that differ: a tube end that itself mates (a
push-fit), an offset, or a port turned the other way round. A connector is not
one of them: it is a part of its own (D11).

#### D1a. No default ports; `with` is optional (decided 2026-11-22)

**Decision.** Routed parts, and script parts that declare `route`, get no ports
they did not declare. Every end may omit `with`, and is then connected as if by a
port at the end frame's origin, unturned. `with` names a declared port or
interface. `through` entries never give it.

**Why.** An earlier draft gave every port-less routed part two default ports,
`start` and `end`, both at the end frame's origin:
- for a plain tube they are one port under two names, and say nothing;
- the order of `ends` already says which end is which;
- the cables whose ends really differ (a push-fit end that mates by interface, an
  offset on one side, a port turned the other way round) declare their own ports
  anyway.

So the defaults only made every end say `with: start` or `with: end` for nothing,
and made the ports passed through an exception.

**Consequences.**
- A plain tube's route names no cable ports at all.
- `with: start` on a part that declares no `start` is an error that lists the
  ports the part has, not a silent default.
- The D8 resolver has to accept a missing source port. It substitutes an
  identity port rather than taking the "peer port auto-detection" path that a
  port-less child of an ordinary link takes.
- The equivalence test compares an end without `with` with a plain part whose
  only port is at its origin, unturned.

Alternatives considered for how the direction at an end is decided:

| Option | Direction decided by | Pros | Cons |
|---|---|---|---|
| A. `flip: true` per end | Facing rule; `flip` reverses | Trivial | A patch over the convention: users must know which ports are backwards |
| **B. The cable has end ports (chosen)** | The existing connection rules, on the cable's own ports and interfaces | One rule for every joint. Fixed once, in the cable part. Interface and mating checks for free. Paves the way for connectors on cable ends | Needs the connection code factored out (D8), and that code has to accept a missing source port |
| C. Explicit `direction:` per end | A vector in the target port's frame | Fully explicit. Handles odd port angles | Verbose, and still requires knowing how each port was declared |
| D. Infer from the next knot | The sign of the port's Z that points towards the next knot | No syntax | Silently wrong for a cable that must leave backwards and then turn |
| E. Infer from geometry | Away from the target's solid | Automatic | Heuristic, needs the solid, ambiguous for recessed ports |
| F. Fix the port | `map:` long form (`turnX: 180`) on an enrich | Nothing new | An enrich just to route a cable |

C can be added later as an override if a real case needs it.

### D2. Second pass inside `handle_node_list`
Route links are taken out of the first loop and handled after
`wait_for_tasks()`, before `resolve_also`, in list order. `route` joins
`PLACEMENTS`. `placement_refusals` does not apply the "placed after" rule to
route ends. It adds a refusal for any `connect*`, `alsoConnectPorts` or route end
that names a routed link.

*Alternative:* one whole-tree pass after the root is built. Rejected, because a
sub-assembly is built and cached independently of its parent, so its routes have
to be final when it is.

### D3. Tree paths resolve through `AssemblyChild` items
The first segment of `reactor/core` is matched against the current list's
children (same first-match rule as `link_names`). Each further segment is matched
against `item.children` of the assembly placed there. Locations are multiplied
down the path, so the leaf child gives the target item and the target location
in the list's frame. A single-segment name also finds an assembly's `map:` ports.
Errors list the names available at the level that failed.

*Alternative:* require `map:` on every intermediate assembly. Rejected: that is
the hand-written plumbing the issue wants removed.

### D4. Path = cubic Hermite spline in a new `route_path.py`
The knots, in order, are: each end's and `through` entry's origin, its lead
point (origin + lead·Z), and the `via` points. The tangent at an end is its Z
axis (reversed at the second end, so the path arrives along it). At a `via` point
it is the Catmull-Rom tangent. At a `through` entry it is whichever sign of Z
points on along the route. Both tangents of a segment get the chord length times 1/cos²(a/2), where
a is the mean angle between the tangents and the chord, capped at 2×. That is the
length a cubic needs to follow a circular arc, so points on a circle give that
circle's radius (to under 1 %). A segment whose tangents lie along its chord, a
lead, stays straight. With plain chord-length magnitudes a quarter circle measured
37 % tighter than it is, which would refuse routes that are fine. The module
returns a dense sample (points, tangents and frames: see "Roll" below), the arc length (Simpson over the sample
intervals), the minimum radius of curvature and where it occurs, and the closest
approach between stretches. A pair of samples counts towards the closest approach
when the second is the nearest of its neighbours to the first, and they are
further apart along the path than the threshold. A straight route never
approaches itself; a hairpin approaches itself by its gap.

`route_path` takes the stops (frames and `via` points) as one ordered list,
which the placement code builds from `ends`, `through` and their `via` lists
(D12, D14).

**Roll.** The frames are carried from the first end's X axis by double reflection
(rotation-minimizing), then rolled about the path so that the profile's X meets
the X axis of every `through` entry and of the second end. The roll each entry
asks for is spread evenly by arc length over the stretch before it, the short way
round (within half a turn). Rolling the starting frame about the tangent rolls
every carried frame by the same angle, so this is exact rather than iterative. A
round tube shows none of it. A flat or keyed profile arrives at each port turned
the way the port is, rather than the way the path happened to carry it, and a
route reads the same whichever end is listed first. A first version carried the
roll from the first end only, which left the second end's turn to chance.

*Alternative:* let OCCT interpolate and measure in the sandbox. Rejected, because
the metrics would be lost on a cache hit and could not be tested in the core.

### D5. The route reaches the part as a reserved parameter `route`
The canonical JSON holds the end frames, leads, `via` points and the sampled
path, with coordinates rounded to 1e-6 mm and keys sorted. The path is built
from the rounded stops, not rounded after: rounding thousands of samples would
let a sub-micrometre jitter of an end flip some of them and change the cache key.
It is passed as
`{"route": json}` to `_get_part_async`. This gives a per-link instance and a
cache key that is unchanged when the route is. `routed` declares the parameter
implicitly, and a script part declares it explicitly. The ends are resolved
against the part fetched *without* `route`, which is why the spec forbids ports
that depend on it.

### D6. A wrapper of its own; the factory-side sketch handling is shared with `sweep`
`PartFactoryRouted` runs a new `wrapper_route.py` (`GeomAPI_PointsToBSpline`
through the samples, the profile placed in the first end frame,
`BRepOffsetAPI_MakePipeShell` with an auxiliary spine through each sample offset
along its frame's X, so that the profile follows the D4 frames and their roll
rather than OCCT's own, then `finish_request`).
The sketch resolution and sketch cache-key folding of `PartFactorySweep` move into
a helper that both factories use.

*Alternative:* add a sampled-path mode to `wrapper_sweep.py`. Rejected for now:
- the two share little more than the final pipe call;
- any edit to that file raises its `CACHE_VERSION` and rebuilds every sweep part;
- it puts the `produce_part_sweep` renders at risk.

Revisit if `sweep` wants paths that pass through their points.

### D7. Checks read the route record, not the shape
`AssemblyChild.route` keeps the resolved ends, the length, the minimum radius and
the closest approach from D4. It survives a cache hit, and the instruction book
can say "route <link> from usb-plug:cable-exit to
reactor/core:thermistor-well". `qual/basic/route.py` compares the record with the
part's `length` and `minBendRadius`. Unresolved ends and D9 refusals reach it
through `report_joint_problem`.

### D8. One connection resolver, used by links and by route ends
The part of `handle_node` that turns a `connect*` section, a child item and a
target into `(target location, ports, interfaces, params)` and calls
`compose_connection` is extracted into a method. The method takes the target
child and its location explicitly, so that D3 can hand it a nested one. A link
calls it as today. A route end calls it with the routed part as the child,
discards the joint, and takes the composition at its defaults. A route end
without `with` passes an identity source port (a port at the origin, unturned)
instead of looking one up. That skips the "peer port auto-detection" path, which
an ordinary link with a port-less child still takes.

The extraction lands first, on its own, with no change in behaviour, and the
existing connection tests prove it.

### D9. A route that cannot be built is refused, in two stages
Before any sweep, the core checks the D4 metrics. The build is refused when:

1. **Degenerate knots:** two consecutive knots are within 1e-3 mm, or two ends
   coincide.
2. **Bend tighter than the profile:** the minimum radius of curvature is below the
   profile's outer radius: `diameter`/2, or for a sketch the largest distance of
   its outline from its origin, measured from the sketch's bounding box.
3. **Path crossing itself:** two samples further apart along the path than the
   profile's diameter (plus a margin) come closer than that diameter in space.

After the sweep, `wrapper_route.py` refuses anything that is not exactly one
solid, has non-positive volume, or fails `BRepCheck_Analyzer`. For a generic
part the `validity` check only reports these. For a route, though, an invalid
solid always means the path could not carry the profile.

Any refusal leaves the link out of the assembly. The log message names the link,
the reason, the path position (as a point in the list frame) and the values. The
same text goes into `joint_problems`, so `pc qual test` fails the assembly with
it. Stage 1 and the bend check also suggest the remedy: moving the `via` point
named, or giving the path room near the end named. A `lead` is not suggested,
because it moves where the bend starts and not how tight it is: with a `via`
point 1 mm from an end, a lead makes the path double back to it.

Two limits look alike and are kept apart. The profile radius (2) is geometry: the
solid cannot exist, so the route is refused. `minBendRadius` is the material's
rating: the solid exists but would kink the real tube, so the part is built and
`pc qual test` fails it (D7).

*Alternatives:*
- Add the solid with a warning, as `sweep` effectively does today. Rejected,
  because a self-intersecting solid poisons every later boolean, the mass
  properties, and printing.
- Substitute a centreline wire so that the viewer shows something. Deferred, as
  it would be a new kind of child.

### D10. One-ended routes: a free end at a location (decided 2026-11-22: option a)
Some cables and hoses are connected at one end only:
- a drain hose that ends over a bucket;
- a sensor pigtail, or a power cord that leaves the model;
- a cable left loose to be cut to length on site.

With every end required to be a connection, none of these could be stated other
than by placing a dummy part with a port at the free end.

| Option | The free end is | Pros | Cons |
|---|---|---|---|
| **a. A free end at a location (chosen)** | An end written `location: <OCCT location>` (link syntax), its end frame given directly in the list's frame | Simple. Uses the path, checks and refusals unchanged. The instruction book can say "leave the other end at …" | The free end does not follow anything: it is drawn by hand, like `via` |
| b. Ended by length | Wherever `length` runs out, along the last `via` points | The cable's real length places the end | Makes `length` shape the geometry, against the check-only decision, and the end direction is still unspecified |
| c. Hanging under gravity | Solved, given length and stiffness | Realistic | Out of scope with keep-out and solving (Non-Goals) |
| d. Not supported | A dummy part with a port, placed by hand | Nothing new | A fake part in the BOM and the instruction book |

Rules (spec: "Free ends"):
- either end may be free, a `through` entry may not;
- at least one end must be a connection, since a route with none is a `sweep`;
- a free end gives no `with` and may give `lead`;
- `length` and `minBendRadius` are checked as for any route;
- the schema makes `location` exclusive with `connectPorts`/`connect` within one end.

Moving the connected end changes the route, and the free end stays where it was
written. A free end is one more knot with a frame, so `via` points, `through`
entries and `lead` work with it unchanged, and D4 and D9 need nothing new.

In the implementation, a free end skips the D3 and D8 resolution: its frame is
the parsed location. The instruction book says "leave the other end at (x, y, z)".
(b) can be added later as a second way to end a route.

### D11. Connectors are parts of their own (decided 2026-11-22: option 1)
**Decision.** A routed solid is the swept profile and nothing else. A plug, a
ferrule or a fitting at a cable's end is a part of its own. It is placed like any
link (usually by `connect:` into its socket), and the route ends at its
cable-exit port:

```yaml
- assembly: control-unit           # maps its board's USB socket as `usb-a`
  name: control
- part: usb-a-plug
  name: usb-plug
  connectPorts: {with: mating-face, name: control, to: usb-a}
- part: thermistor-cable           # type: routed, declares no ports
  route:
    ends:
      - connectPorts: {name: usb-plug, to: cable-exit}
        lead: 15
      - connectPorts: {name: reactor/core, to: thermistor-well}
```

**Why.** An earlier draft modelled the thermistor's plug as an interface
implemented by the cable, offset 12 mm beyond the cable's end face. That placed
the cable correctly, but nothing drew the plug: the render showed a 12 mm gap
between the socket and the cable, and the end-frame diagram drew a plug box that
would never be rendered.

| Option | How the plug exists | Pros | Cons |
|---|---|---|---|
| **1. A separate part (chosen)** | Placed by `connect:`. The route ends at its cable-exit port | Nothing new to build. The plug is real: BOM, instruction book, mating checks, render. Fits "nothing connects to a route", since the cable connects to the plug | Two items for a moulded cable bought as one. One more link |
| 2. Fittings carried by the routed part | `fittings: {<port>: <part>}`, with that geometry added to the routed solid at the end frame | One item. No gap | New spec surface: fitting geometry in the sweep, the cache key and the length rules |
| 3. Offsets only | As in the earlier draft | Nothing to do | A visible gap. Honest only when something else draws the connector |

Tree paths (D3) are for route ends only. The plug's own `connect*` names a
sibling as always, and reaches into the control unit through its `map:`. Giving
ordinary connections tree paths would be a separate change.

**Consequences.**
- A connector is never required. An end connects straight to any port: a tube
  pushed onto a barb, a wire into a terminal block, a bare thermistor bead into
  its well. A connector part is only for when there is connector geometry to
  show.
- Port offsets on routed parts remain, for connectors drawn elsewhere (a gland
  built into an enclosure). Nothing is drawn in the offset, and it does not count
  towards `length`.
- An interface on a routed part means the tube end itself mates, as with a
  push-fit tube.
- A moulded cable assembly appears in the BOM as two items, plug and cable.
  Option 2 is the follow-up if that matters.

### D12. `via` points are listed on the entry they lead to (decided 2026-11-22: option a)
A `via` point is a waypoint: a point in the list's frame that the path passes
through. It places nothing, follows nothing, and has no direction of its own. Any
entry may list several, passed in the order listed. The first spelling, one
`via:` list on the route, says nothing about which stretch a point is on once the
route passes through another port. With a sensor, a
grommet and a board, `via: [A, B]` could mean A before the grommet and B after,
or both before; the path might cross the panel twice to reach them.

| Option | Spelling | Pros | Cons |
|---|---|---|---|
| **a. `via` on each entry (chosen)** | Every entry but the first end lists the points passed on the way to it | Unambiguous for any number of ports passed through. Moving a `through` entry in the list moves its waypoints with it. Mirrors the script JSON (each end carries its `via`) | Waypoints of one route are spread over its ends |
| b. Route-level `via` only, two ends only | One list, refused once a port is passed through | Simplest | A route through a grommet cannot be steered at all |
| c. Waypoints as stops in `ends` | `ends: [sensor, {via: A}, grommet, {via: B}, board]` | One flat ordered list | `ends` then holds things that are not ends; every end rule needs "except via entries" |

After D14 the entries are `through[0]`, `through[1]`, … and the second end, in the
order the cable reaches them, and each lists the `via` points of the stretch that
leads to it. A route with no `through` keeps the route-level `via:` as a shorthand
for `via` on its second end: it is what most routes need, and it reads as the
path's shape. Giving both, or a route-level `via` together with `through`, is an
error rather than a merge rule. The first end never gives `via`, since nothing
comes before it.

### D13. Routes are checked for interference; their ends are joints
A `via` point on the wrong stretch, or written in the wrong frame, gives a path
that can be built: D9 cannot tell it from a deliberate detour. What gives it away
is that the cable then runs through a part. `pc qual test` already fails an
assembly whose parts share space (`qual/topology/interference.py`), and it
covers routed parts like any other.

The interference check reads each overlap against the joint between the two
parts, and accepts it only where that joint's ports, interfaces or mating declare
it (`snapIn`, `selfScrew`). Each end and `through` entry of a route is such a joint
between the routed part and the part it connects to: a tube stretched over a barb
is accepted where the barb port declares `snapIn`, the same as for any part pushed
onto it. Everywhere else, a cable that shares space with a part fails, naming
both. A cable that merely rests against a surface bounds no volume, and passes.

A detour through free air that touches nothing is still not caught. It shows in
the render, and as a `length` failure where the cable declares one.

*Alternative:* a check of its own for routes, such as path samples inside a solid.
Rejected, because it would duplicate the interference test with a second notion of
"expected overlap".

### D14. Two `ends` and a `through` list (decided 2026-11-23)
The first spelling put every port the route met in `ends`, so a grommet in the
middle was an "end" where the cable has none, and every end rule had an
exception for the middle ones.

| Option | Spelling | Pros | Cons |
|---|---|---|---|
| **a. `ends` (two) and `through` (chosen)** | `ends: [a, b]`, `through: [g1, g2]` | The words say what each entry is. The rules come from the structure: only `ends` give `with` or are free, `through` never does. No direction implied | The order of travel is `ends[0]`, `through`…, `ends[1]`: the second end is listed before the ports that precede it |
| b. `start` / `through` / `end` | Three keys | Reads in travel order | Implies a direction a route does not have: the path is the same either way round, and the roll is matched at both ends |
| c. One list under another name | `attach:` or `anchors:` | One ordered list | First and last are still special by position, so every rule keeps its exception |
| d. Keep `ends`, fix the prose | Middle "ends" called pass-through ports | No change | The key still says "end" for things that are not |

A route has no direction: the path through the same knots is the same curve
either way round, the checks are symmetric, and with the roll matched at every
port (D4) the solid is too. Flow direction (a pump's outlet to a reservoir) is not
modelled; if it is ever needed, it is a field of its own rather than something
read from which end is listed first.

## Risks / Trade-offs

## Risks / Trade-offs

- **[Extracting the connection resolver regresses ordinary connections]** → It
  lands as a refactor on its own, gated by the existing connection, joint,
  `alsoConnectPorts` and guide tests, unchanged.
- **[A Hermite path can still kink with badly placed waypoints]** → D9 refuses it
  with the position and a remedy. The docs show `lead` and `via` patterns.
- **[The self-crossing check costs time on long routes]** → It runs on a
  down-sampled path through a uniform grid, which is linear in the sample count.
  Tests use a 2 m route with 5 000 samples.
- **[The sketch outer radius from a bounding box is conservative]** → It can only
  refuse a route that might have been buildable, never accept one that is not.
  The message says so.
- **[Many routes mean many cache entries]** → The same is true of any per-link
  param. Rounding keeps equal routes equal.
- **[A sub-assembly reached through a path is an alias or enrich, with no
  children]** → Error: "'X' places no links; name one of its ports instead".

## Migration Plan

Additive. No existing file changes meaning. The MicroLab model moves its tubes to
`route:` in a follow-up in the 4tv repository.
