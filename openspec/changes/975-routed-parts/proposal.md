# Proposal

Issue: [#975](https://github.com/partcad/partcad/issues/975)

## Why

Cables, hoses and tubes join two parts that are placed independently, but every
PartCAD part is built in its own frame before it is placed. A tube can therefore
only be a fixed solid whose route is written by hand in some assembly's frame, and
it stays right only while neither end moves (issue #975). The MicroLab model has
nine silicone tubes and a thermistor cable routed this way. They are kept in step
with their ports by Jinja variables shared between the route and the ports.

## What Changes

- New built-in part type `type: routed`: a profile (a round section given by
  `diameter` and an optional `innerDiameter`, or a named sketch) swept along a
  path that PartCAD computes from the route's ends. The part type can also declare
  `length` (the real length of the cable) and `minBendRadius`.
- Each end of a routed part is connected exactly the way a part plugged into the
  same port would be, so the existing connection and mating rules decide which
  way the cable leaves. A plain tube declares no ports: its end face is what is
  plugged in. A cable whose ends differ, with an offset or a mating interface,
  declares ports or interfaces for them and names them in `with`.
- A routed part's solid is the swept cable only. A connector, where there is one
  (a plug, a ferrule, a fitting), is a part of its own, and the route ends at its
  cable-exit port. None is required: a route can end straight at any port.
- New ASSY placement section `route:` for a part link, as an alternative to
  `location:`, `connect:` and `connectPorts:`. It lists its two `ends` and,
  optionally, the ports it passes `through` (a grommet, a clip), each an ordinary
  `connectPorts:` or `connect:` section with an optional straight `lead` and
  optional `via` waypoints, in the assembly frame, for the stretch leading to it.
  Either end may instead be free, a `location:` where the cable just ends, for
  hoses and cords connected at one end only.
- A flat or keyed profile meets every port it reaches turned the way that port
  is, the roll spread evenly along the path.
- `pc qual test`'s interference check covers routed parts, with each route end
  and port passed through counted as a joint, so a cable sent through a part by a
  misplaced waypoint fails it.
- A route whose path cannot carry the profile is refused, with the position and
  the reason, instead of yielding a self-intersecting solid. That covers a bend
  tighter than the profile, a path that crosses itself, coincident points, and a
  failed or invalid sweep.
- An end names its link by a path through the assembly tree (`reactor/core`), so a
  route declared in a parent assembly can reach a port inside a sub-assembly.
  `map:` is not needed for this.
- Route links are built in a second pass, after every other link of their
  `links:` list has been placed. The route is built in the frame of that list, so
  moving either end reroutes it on the next build.
- A CadQuery or build123d part can be placed with `route:` too. It opts in by
  declaring a string parameter `route` and receives the end poses and waypoints
  as JSON, so it can build its own geometry along them.
- `pc qual test` reports a route that is longer than the part's `length`, or that
  bends tighter than its `minBendRadius`. These limits are only checked: the
  route is not reshaped to meet them.
- Out of scope: keep-out from other parts, solving the route to a given length
  (slack or sag), and connecting other links to a routed part.

## Capabilities

### New Capabilities
- `routed-parts`: parts whose geometry follows the ports they connect. This covers
  the `routed` part type, the ASSY `route:` placement, how ends reach ports through
  the assembly tree, the script hook, and the `pc qual test` checks for length and
  bend radius.

### Modified Capabilities
<!-- None: no existing spec covers assembly or part behaviour. -->

## Impact

- **Core:** `assembly_factory_assy.py` (the second pass after `handle_node_list`, and
  resolving tree paths); a new `part_factory_routed.py`, a pure-Python route-path
  module, and a sandbox wrapper `wrapper_route.py`; a new `qual/basic` check;
  `AssemblyChild` records the route.
- **Schemas:** `assy.json` (`route` node section, exclusive with the other
  placements), `partcad.json` (the `routed` part type).
- **Tooling:** `pc lint` and schema validation; the part-type lists that are kept
  complete by tests (`partcad_client.object_types`).
- **Docs and examples:** `config_parts.rst`, `assy.rst`, and a new
  `examples/feature_routed_parts` package with a behave feature.
- **No breaking changes:** files that use none of this build exactly as before.
