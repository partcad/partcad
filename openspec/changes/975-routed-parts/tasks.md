# Tasks

Test rules for every group: tests build their own temporary packages (STL cubes with ports, as in
`tests/partcad/unit/test_assembly_also.py`), share no state, and pass under `-n logical --dist worksteal`.
Tests marked *(sandbox)* run OCP in the Python sandbox and are kept few. Everything else runs without one.

## 1. Extract the connection resolver (refactor, no behaviour change)

- [ ] 1.1 Extract from `handle_node` the step that turns a `connect*` section, a child item and a target child with its location into the ports, interfaces and params passed to `compose_connection`. The target location becomes an explicit argument (D8). Verify that `test_assembly_also.py`, `test_assembly_connect_how.py`, `test_connect_motion_declared.py`, `test_connect_self_screw.py`, `test_assembly_guide.py`, `test_import_assy.py` and `tests/partcad_utils/test_assy_lint.py` all pass with no test edited.
- [ ] 1.2 Add `tests/partcad/unit/test_connection_resolver.py`: for a `connectPorts` link, a `connect` link by interface, one with `toParams`, and a port-less child (which keeps today's "auto-detection" warning), the extracted method called directly returns the placement `handle_node` gives the same link (exact equality of the composed `Location`). Verify that it passes.

## 2. Route path math and feasibility (pure Python)

- [ ] 2.1 Add `src/partcad/route_path.py` (D4). Verify with `tests/partcad/unit/test_route_path.py`:
  - a straight two-end route has length equal to the distance (to 1e-9) and an infinite minimum radius;
  - a lead's samples lie on the end axis, within 1e-9 mm of the axis;
  - every `via` point and `through` entry is a sample point;
  - a route shaped like a quarter circle is within 2 % of the analytic length and radius;
  - transported frames stay orthonormal (to 1e-9), and the first frame's X equals the first end's X;
  - the closest approach of a straight route is infinite, and that of a hairpin is the hairpin's gap.
- [ ] 2.2 Add canonical route JSON (rounded to 1e-6 mm, sorted keys). Verify in the same file that equal routes are byte-identical, that a 1 µm move of an end changes the JSON, and that a sub-1e-7 mm jitter does not (the path is built from the rounded stops).
- [ ] 2.3 Add the D9 pre-sweep checks, returning structured refusals (reason, point, values, remedy). Verify with `tests/partcad/unit/test_route_feasibility.py`, one test per case, each asserting the reason and point:
  - a `via` point coinciding with an end;
  - two ends at the same point;
  - a `via` point 1 mm from an end of a 6 mm tube (bend radius below 3 mm);
  - the same `via` point moved 20 mm from the end, which passes (a `lead` does not fix it: the path doubles back to the point);
  - a figure-eight of `via` points that crosses itself;
  - a hairpin whose gap is below the diameter, refused, and the same hairpin with the gap above it, which passes;
  - a 2 m route with 5 000 samples, checked in under 1 s on a CI runner.
- [ ] 2.4 Roll the carried frames to meet the X axis of each `through` entry and of the second end, spread evenly by arc length, the short way round (D4); name knots as the YAML does (`end 2`, `through 1`, `via point 1 of end 2`); give the JSON `ends`, `through` and per-entry `via` (D14). Verify in `test_route_path.py` that a straight route to a second end turned 90° rolls linearly to it, that one turned 270° rolls 90° the other way, that on a curved route through two entries the frame's X equals each entry's X (to 1e-9) with the frames still orthonormal, and that knot names match the YAML.

## 3. Routed part type and its ends

- [ ] 3.1 Add `routed` to `partcad.json` (`diameter`, `innerDiameter`, `sketch`, `length`, `minBendRadius`; exactly one of `diameter` or `sketch`). Verify that schema tests accept valid declarations, and reject both-or-neither and `innerDiameter >= diameter`.
- [ ] 3.2 Make routed parts expose exactly the ports and interfaces they declare (none by default), and reject ports or interface parameters that refer to `route`. Verify with unit tests: a plain routed part has empty `with_ports.get_ports()`; declared ports appear as declared; the `route` reference is reported as invalid.
- [ ] 3.3 Extract the sketch resolution and sketch cache-key folding from `PartFactorySweep` into a shared helper (D6), with `sweep` and its `CACHE_VERSION` unchanged. Verify that the sweep cache keys in `test_cache_key_collisions.py` are identical before and after, and that `examples/produce_part_sweep` still passes `pc test`.
- [ ] 3.4 Add `src/partcad/wrappers/wrapper_route.py` (D6, plus the D9 post-sweep checks) and `src/partcad/part_factory_routed.py`. Register the type in the part-type registry, `partcad_client.object_types` and `ide/vscode/src/partTypes.ts`. Verify that the completeness tests pass, plus these *(sandbox)* tests in `tests/partcad/unit/test_part_routed.py`:
  - a 6/4 mm tube on a sampled arc is one valid solid, with volume within 1 % of π(3²−2²)·L;
  - both end faces are centred on the end origins (to 1e-6 mm) and normal to their Z axes (to 1e-6 rad);
  - a flat rectangular sketch has its long side along each end's X at both end faces (to 1e-6 rad), i.e. the solid follows the rolled frames (D4);
  - a sketch whose sweep self-intersects is refused with the defect named, and no shape is returned;
  - a missing `route` param is a clear error.
- [x] 3.5 Document the `routed` type in `docs/source/config_parts.rst`: its fields, the profile rule, the end frame and when to declare ports, a pointer to `route:`, and a short "routed or sweep?" note. Use `sweep` for a fixed shape drawn in the part's own frame, and `routed` for anything that joins two placed parts and has to follow them. Cross-link the two sections. Verify that the docs build has no warnings.

## 4. ASSY `route:` placement

- [ ] 4.1 Add the `route` node section to `assy.json`: `ends` with exactly two entries, an optional `through` list, `via` and `comment` (D14). Each end and `through` entry is `connectPorts` or `connect` (only the fields naming the two sides, plus `comment`) with `lead` and `via` (D12); only ends take `with` or `location`. Add `not required` pairs against `location`, `connect` and `connectPorts`. Verify with schema tests, and with `pc lint` cases in `test_assy_lint.py`, for: a valid route; route plus `connectPorts`; one end only; three ends, with a message pointing at `through`; `how` or `joint` inside an end or a `through` entry; an end with both `connect` and `connectPorts`; `with` on a `through` entry; a route with no `with` anywhere, which is valid. Waypoints (D12): `via` on the first end; a route-level `via` together with `through`; `via` both on the route and on the second end. Free ends (D10): a free first or second end is valid; a free `through` entry; every end free; `location` together with `connectPorts` or `connect` in one end; `with` on a free end.
- [ ] 4.2 Add tree-path target resolution (D3). Verify with `tests/partcad/unit/test_route_targets.py` on a two-level assembly:
  - a sibling end;
  - a nested end, whose world pose equals the pose `alsoConnectPorts` computes for the same port;
  - a `map:` port by its single-segment name;
  - a wrong segment and a wrong port, each with the list of available names;
  - a path through an alias, with the "places no links" message.
- [ ] 4.3 Add the second pass in `handle_node_list` (D2), using the D8 resolver for each end, with the routed part fetched without `route`. Verify with `tests/partcad/unit/test_assembly_route.py`:
  - **equivalence:** each end frame equals the placement of a plain part with the same port placed by the same `connectPorts` or `connect`, to 1e-9;
  - **equivalence without `with`:** an end without `with` equals the placement of a plain part whose only port is at its origin, unturned, placed by `connectPorts` naming that port, and no "auto-detection" warning is logged;
  - `with` naming a port the routed part does not declare is reported with the list of its ports, or "none", and the link is left out;
  - a target port declared the other way round sends the end into the part, as it does the plain part;
  - interfaces with no mating report the same problem a `connect` does;
  - a free mating takes its default, and no joint appears in `assembly.joints()`;
  - an end listed after the route resolves;
  - moving an end's `location:` changes only that end's frame and the route JSON;
  - an unchanged rebuild is a cache hit;
  - connecting to a routed link, by any of the four ways, is refused;
  - a `through` entry is passed along its axis between the two ends; two `through` entries are passed in order; a `through` entry giving `with` is refused;
  - **free end:** its end frame equals the parsed `location:` exactly; moving the connected end's link changes only the connected end; a free end with `lead`, `via` points and a `through` grommet passes through all of them in order;
  - **waypoints (D12):** each entry's `via` points become stops just before it, in order, across two `through` entries with several points each; a route-level `via` builds the same stops as `via` on the second end; the three misplaced-`via` cases are refused at build time; a route whose ends are all free is refused at build time with the "at least one connected end" message;
  - a script part that declares `route` and no ports is connected at both ends by the end frame's origin;
  - **connectors (D11):** a route ending at the `cable-exit` port of a separately placed plug part starts exactly there, with the plug listed before and after the route; the routed solid adds no geometry for an offset port (its end face lies at the end origin); a route straight to a barb port with no fitting part builds with no warning;
  - `AssemblyChild.route` holds the ends, length, minimum radius and closest approach.
- [ ] 4.4 Wire the D9 refusals into the build. Verify with the same test file that each pre-sweep refusal case from 2.3 leaves the link out of `assembly.children`, logs the reason, and appears in `get_connect_problems()`.
- [ ] 4.5 Add the script hook (a part that declares `route: {type: string}`). Verify with a *(sandbox)* test whose build123d script sweeps a circle along the received frames, and asserts that the JSON has `origin`, `z`, `x` and `lead` per end, and that the solid's endpoints are on the end origins. A `step` part placed with `route:` is reported and left out.
- [x] 4.6 Document `route:` in `docs/source/assy.rst`: ends as connections, the end frame, tree paths, `lead`, `via`, the script hook, the second pass, refusals and their remedies, and the restrictions. Verify that the docs build has no warnings.

## 5. Checks and instructions

- [ ] 5.1 Add `qual/basic/route.py` (D7). Verify with `tests/partcad/unit/test_qual_route.py`:
  - too short fails, naming the link and both values;
  - port offsets are not counted in the length;
  - bending tighter than `minBendRadius` (but wider than the profile) builds the part and fails, naming both values;
  - within limits passes;
  - no limits declared passes;
  - a D9 refusal fails with its own text.
- [ ] 5.3 Make the interference check treat each route end and `through` entry as a joint (D13). Verify with cases in `tests/partcad/unit/test_qual_route.py` *(sandbox)*:
  - a `via` point listed on the second end instead of the grommet sends the cable back through the panel, and the check fails naming the cable and the panel;
  - the same point listed on the grommet passes;
  - a tube end overlapping a barb whose port declares `snapIn` passes, and fails without it;
  - a cable resting against a surface without entering it passes.
- [ ] 5.2 Make the instruction book (`assembly_guide.py`) state each route step, from end to end with tree paths, and "leave the other end at (x, y, z)" for a free end. Verify with cases in `test_assembly_guide.py` for a two-ended route and a one-ended one.

## 6. Example and integration

- [ ] 6.1 Add `examples/feature_routed_parts`:
  - two blocks with ports, one of them inside a sub-assembly;
  - a tube routed between them with `lead` and `via`;
  - a cable through a panel grommet and a clip (`through`), with `via` points on each stretch;
  - a cable with a USB-style plug as a part of its own, connected into a socket by interface, the route starting at the plug's `cable-exit` port;
  - a push-fit tube whose end implements an interface that mates with a fitting;
  - a build123d cable that uses the script hook;
  - a drain hose with one free end;
  - an SVG render in its README.
  Register it in `examples/partcad.yaml`. Verify that `pc test` and `pc render` succeed in it.
- [ ] 6.2 Add `features/routed_parts.feature` with these scenarios: build and inspect; move an end by editing `location:` and rebuild, with the route changed; `pc qual test` reports a cable that is too short; a `via` point too close gives the refusal message; a `via` point on the wrong stretch fails `pc qual test` with an interference naming the cable and the panel. Verify with `poetry run behave features/routed_parts.feature`.
- [ ] 6.3 Run the unit suite (`poetry run pytest tests -x -n logical --dist worksteal`), `features/routed_parts.feature` and the lint hooks, and verify that all pass.

## Workflow follow-up

- Open a PR against `devel` from branch `975-routed-parts` pushed to origin, with "Closes #975" in its description, listing the behave features that were run.
- Archive the change once the PR is merged.
- Adopt `route:` for the MicroLab tubes and thermistor cable in the 4tv project, as a separate change.
