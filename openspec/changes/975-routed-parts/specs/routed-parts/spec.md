# Spec Delta

## Purpose

Lets a cable, hose or tube be modelled as a part whose shape follows the ports it
connects, so that it reroutes itself whenever the parts at its ends are moved,
instead of being a fixed solid drawn by hand in one assembly's frame.

## ADDED Requirements

### Requirement: Routed part type
A part declared with `type: routed` SHALL be a profile swept along the path of the route that places it. The profile SHALL be either a round section given by `diameter`, with an optional `innerDiameter` that makes it hollow, or a sketch named by `sketch`. Exactly one of the two SHALL be given.

#### Scenario: Round hollow tube
- **WHEN** a part declares `type: routed`, `diameter: 6` and `innerDiameter: 4`, and an assembly places it with `route:`
- **THEN** the part's solid is a 6 mm tube with a 4 mm bore, following the route from its first end to its last

#### Scenario: Sketch profile
- **WHEN** a part declares `type: routed` and `sketch: flat-cable-section`
- **THEN** the sketch is swept along the route, in the plane normal to the path, drawn in the first end's frame, with its X axis along the X axis of each `through` entry and of the second end where the path reaches them, the roll between them spread evenly along the path

#### Scenario: Profile not symmetric about its X axis
- **WHEN** a routed part's sketch is a D shape with its flat on +Y, and its route's ends are listed one way and then the other
- **THEN** the flat lies on +Y of whichever end is listed first, and on −Y of the other end's frame, so the two solids differ; for a sketch symmetric about its X axis they are the same

#### Scenario: Both or neither profile
- **WHEN** a part declares `type: routed` with both `diameter` and `sketch`, or with neither
- **THEN** the package is reported as invalid, and the message names the part and the two fields

### Requirement: The end frame, and the ports declared in it
Every route end SHALL have an end frame: its origin is the centre of the cable's end face, and its +Z axis runs along the cable. A routed part, or a script part that declares the `route` parameter, MAY declare ports and implement interfaces. They are declared in the end frame, and are used for ends that differ: a tube end that itself mates (a push-fit), an offset, or a port turned the other way round. Neither kind of part SHALL be given ports it did not declare.

#### Scenario: Plain tube
- **WHEN** a routed part declares no `ports:` and no `implements:`
- **THEN** it has no ports, and every end of a route that places it is connected by the end frame's origin

#### Scenario: Offset port
- **WHEN** a routed part declares a port `gland` at `[[0, 0, -12], [0, 0, 1], 0]`
- **THEN** a route end connected by `gland` puts the cable's end face 12 mm back from the target port, along the cable, and nothing is drawn in those 12 mm

#### Scenario: Ports that depend on the route
- **WHEN** a routed part's ports or interface parameters refer to the `route` parameter
- **THEN** the package is reported as invalid, because the ends have to be known before the route is

### Requirement: Connectors are parts of their own
A routed part's solid SHALL be the swept profile only: no geometry SHALL be added for its ports, interfaces or offsets. Where a cable has a connector (a plug, a ferrule, a fitting), it SHALL be modelled as a part of its own, placed like any other link, and the route SHALL end at one of its ports. A connector SHALL NOT be required: an end MAY connect straight to any port.

#### Scenario: Cable ending in a plug
- **WHEN** a link `usb-plug` places a plug part by `connectPorts:` into a socket that the sibling link `control` maps, and a route's end is `{connectPorts: {name: usb-plug, to: cable-exit}}`
- **THEN** the route starts at the plug's `cable-exit` port, the plug and the cable are separate items in the assembly, and nothing is left undrawn between the socket and the cable

#### Scenario: No connector
- **WHEN** a tube's route ends directly at a barb port of a pump, with no fitting part
- **THEN** the route is built against the barb port, and nothing reports a missing connector

#### Scenario: Plug listed after the route
- **WHEN** the plug's link comes after the routed link in the same `links:` list
- **THEN** the route still ends at the plug's port, as placed

#### Scenario: Nothing drawn for an offset
- **WHEN** a routed part declares a port offset from its end face and a route uses it
- **THEN** the routed solid ends at the end face, and nothing is drawn between it and the target port

### Requirement: Route placement
An ASSY part link SHALL accept a `route:` section whose `ends` list exactly two ends, each a connection or a free end (see "Free ends"), and whose optional `through` lists the connections the route passes through between them. A connection is a `connectPorts:` or a `connect:` section with the fields that name the two sides, with their usual meaning, and an optional `lead`. A `route:` SHALL NOT be combined with `location:`, `connect:` or `connectPorts:` on the same link.

#### Scenario: Ends by port
- **WHEN** a routed link has `ends: [{connectPorts: {name: pump, to: outlet}}, {connectPorts: {name: reactor, to: inlet}}]`
- **THEN** the path runs from the `outlet` port of `pump` to the `inlet` port of `reactor`, in that order

#### Scenario: End by interface
- **WHEN** a routed tube implements `push-fit-6mm-tube`, and an end is `{connect: {with: push-fit-6mm-tube, name: manifold, to: push-fit-6mm}}`
- **THEN** that end is resolved by the interfaces and the mating between them, as a `connect:` would resolve it

#### Scenario: Not two ends
- **WHEN** a route's `ends` lists one end, or three
- **THEN** schema validation and `pc lint` report it, saying that ports passed through go in `through`, and the build reports it and leaves the link out

#### Scenario: Fields that make no sense for an end
- **WHEN** an end's or a `through` entry's section gives `motion`, `physics`, `joint`, `exploded` or `interferes`
- **THEN** schema validation and `pc lint` report the field, and the build ignores it

#### Scenario: How an end goes in
- **WHEN** an end or a `through` entry gives `how`, such as `{stage: plumbing, pushForceMax: 20}`
- **THEN** it is valid, and the instruction book's step for the routed link reads it as it reads a connection's `how`

#### Scenario: Placement stated twice
- **WHEN** a link has both `route:` and `connectPorts:`
- **THEN** schema validation and `pc lint` report the conflict, and the build reports it and ignores the `route:`

### Requirement: The routed part's side of a connection
A connection end that omits the routed part's side (`with`) SHALL be connected as if by a port at the end frame's origin, unturned. Only an end MAY give `with`, not a `through` entry, and it SHALL name a port or an interface the part declares.

#### Scenario: Plain tube names no port
- **WHEN** a routed part declares no ports, and neither end of its route gives `with`
- **THEN** both ends are connected by the end frame's origin, and no warning about port detection is logged

#### Scenario: Port the part does not declare
- **WHEN** an end gives `with: start`, and the routed part declares no port `start`
- **THEN** the build reports that the part has no such port and lists the ports it has (or says it has none), and the link is left out

### Requirement: An end sits where a connected part would
Each end's frame SHALL be the placement the routed part would get if that end's connection alone placed it. The cable SHALL leave the first end travelling along +Z of that end's frame, and arrive at the second end travelling along −Z of its frame, whose +Z points back into the cable. A connection that would keep a degree of freedom SHALL be taken at its default position, and a route end SHALL make no joint.

#### Scenario: Same as a part placed there
- **WHEN** a route end is `{connectPorts: {with: tip, name: board, to: socket}}`, and a separate part with the same `tip` port is placed by `connectPorts: {with: tip, name: board, to: socket}`
- **THEN** the route's first end frame is that part's placement, to within 1e-9 mm and 1e-9 rad

#### Scenario: Same as a part placed there, with no port named
- **WHEN** a route end is `{connectPorts: {name: board, to: socket}}`, and a separate part whose only port `p` is at its origin, unturned, is placed by `connectPorts: {with: p, name: board, to: socket}`
- **THEN** the route's first end frame is that part's placement, to within 1e-9 mm and 1e-9 rad

#### Scenario: Port declared the other way round
- **WHEN** a target port's Z axis points out of its part, so that a part connected there would sit inside it
- **THEN** the route also enters the part, exactly as the connected part would, and the fix is the same: declare a port on the routed part that is turned the other way round, and name it in `with`

#### Scenario: Interfaces that do not mate
- **WHEN** an end connects a routed part's interface to a target interface with no mating between them, where a `connect:` would report the pair
- **THEN** the build reports the same problem for that route end

#### Scenario: A free connection
- **WHEN** an end connects by interfaces whose mating keeps a rotation free
- **THEN** the end frame is taken at the rotation's default, and no joint is added to the assembly

### Requirement: Leads and ports passed through
An end or a `through` entry MAY give `lead`, a straight length in millimetres that the path runs along its axis before it bends. The path SHALL pass through each `through` entry in order, from the first end towards the second, along the Z axis of that entry's frame.

#### Scenario: Straight lead
- **WHEN** an end gives `lead: 10`
- **THEN** the first 10 mm of the path from that end lie on the end's axis

#### Scenario: Cable through a grommet
- **WHEN** a route's ends are a connector and a sensor, and its `through` is `[{connectPorts: {name: panel, to: grommet}}]`
- **THEN** the path passes through the grommet's port along its axis, between the two ends

#### Scenario: Two ports passed through
- **WHEN** a route's `through` lists a grommet and then a clip
- **THEN** the path passes through the grommet, then the clip, then reaches the second end

#### Scenario: Side named on a port passed through
- **WHEN** a `through` entry gives `with`
- **THEN** schema validation and `pc lint` report the end, and the build reports it and leaves the link out

### Requirement: Waypoints
Each `through` entry and the second end MAY list `via` points, in the frame of the route's `links:` list: the points the path SHALL pass through, in order, on its way to that entry from the one before it. The first end SHALL NOT give `via`. A route without `through` MAY give `via` on the route instead, meaning the same as `via` on its second end. A route SHALL NOT give both, and a route with `through` SHALL NOT give a route-level `via`.

#### Scenario: Waypoints
- **WHEN** a two-ended route gives `via: [[0, 0, 120], [40, 0, 120]]`
- **THEN** the path passes through both points, in the order listed, exactly as when its second end gives that `via`

#### Scenario: Waypoints on each stretch
- **WHEN** a route's ends are a sensor and a board that gives `via: [B]`, and its `through` is a grommet that gives `via: [A]`
- **THEN** the path passes through A between the sensor and the grommet, and through B between the grommet and the board

#### Scenario: Several waypoints on several stretches
- **WHEN** a route's `through` lists a grommet with `via: [A1, A2]` and a clip with `via: [C]`, and its second end gives `via: [B1, B2]`
- **THEN** the path passes A1, A2, the grommet, C, the clip, B1, B2 and the second end, in that order

#### Scenario: Waypoints in the wrong place
- **WHEN** the first end gives `via`, or a route with `through` gives a route-level `via`, or a route gives `via` both on the route and on its second end
- **THEN** schema validation and `pc lint` report it, and the build reports it and leaves the link out

### Requirement: Free ends
Either end of a route MAY be a free end: `location:`, in the OCCT location syntax of a link, giving the end frame directly in the frame of the route's `links:` list, instead of a connection. A free end MAY give `lead` and SHALL NOT give `with`. At least one end of a route SHALL be a connection, and a `through` entry SHALL NOT be free.

#### Scenario: Hose with a free end
- **WHEN** a route's ends are `{connectPorts: {name: pump, to: drain}}` and `{location: [[300, 0, 40], [0, 0, 1], 0]}`
- **THEN** the path runs from the pump's `drain` port and ends with its end face at (300, 0, 40), the hose above it, arriving downwards, against that frame's +Z, which points into the hose

#### Scenario: Free end with waypoints and a grommet
- **WHEN** a route's ends are a connection and a free end, its `through` is a grommet, and the grommet and the free end give `via` points
- **THEN** the path passes through the grommet and every `via` point, each on its stretch, and ends at the free end

#### Scenario: Free end stays put
- **WHEN** the link at the connected end of a one-ended route is moved and the assembly is rebuilt
- **THEN** the route starts at the moved port, and the free end is where its `location:` says

#### Scenario: No connection at all
- **WHEN** every end of a route is free
- **THEN** schema validation, `pc lint` and the build report that a route needs at least one connected end (a shape with a fixed path is a `sweep`), and the link is left out

#### Scenario: Free port passed through, or a free end that also connects
- **WHEN** a `through` entry gives `location:`, or one end gives both `location:` and `connectPorts:` or `connect:`, or a free end gives `with`
- **THEN** schema validation and `pc lint` report the end, and the build reports it and leaves the link out

### Requirement: Ends reach ports through the assembly tree
The `name` of an end or a `through` entry SHALL be a link of the route's own `links:` list, or a path that starts at such a link and descends through the links of the sub-assemblies it places, separated by `/`. An end SHALL resolve whether its link is listed before or after the route.

#### Scenario: Port inside a sub-assembly
- **WHEN** the top assembly places `reactor` (an assembly with a link `core`), and an end is `{connectPorts: {name: reactor/core, to: probe}}`
- **THEN** the end is resolved against the `probe` port of `core`, at its position as placed inside `reactor` within the top assembly

#### Scenario: Link listed after the route
- **WHEN** a route names a link that comes later in the same `links:` list
- **THEN** the route resolves against that link's final placement, and no ordering problem is reported

#### Scenario: Unresolvable end
- **WHEN** an end names a link or path segment that does not exist, or a port or interface the item does not have
- **THEN** the build reports which end failed and what is available at that level, the routed part is left out of the assembly, and `pc qual test` reports the problem for that link

### Requirement: Route follows its ends
A routed part SHALL be built after every other link of its `links:` list has been placed. It SHALL be expressed in that list's frame, so that changing where an end is placed changes the route on the next build, with nothing else edited.

#### Scenario: End moved
- **WHEN** the `location:` of the link at one end of a route is changed and the assembly is rebuilt
- **THEN** the routed part starts at the moved port, and the other end is unchanged

#### Scenario: Unchanged route is cached
- **WHEN** an assembly is rebuilt and neither end nor any waypoint has moved
- **THEN** the routed part comes from the cache rather than being rebuilt

### Requirement: Routed parts cannot be connection targets
No other link SHALL be placed against a routed link by `connect:`, `connectPorts:`, `alsoConnectPorts:`, or another route's end or `through` entry.

#### Scenario: Connecting to a routed link
- **WHEN** a link's `connectPorts:` names a link that is placed by `route:`
- **THEN** the build refuses the connection, with a message saying that a routed link cannot be connected to

### Requirement: Script parts can be routed
A part of a script type (`cadquery`, `build123d`) that declares a parameter named `route` of type `string` SHALL be placeable with `route:`. The parameter SHALL then be given the route as JSON, in the frame of the route's `links:` list: the frame, `lead` and `via` points of each end and `through` entry, and the sampled path. Its ends are connected as a routed part's are. Placing a part with `route:` when it is neither `routed` nor declares that parameter SHALL be reported as an error.

#### Scenario: Script receives the ends
- **WHEN** a build123d part declares `parameters: {route: {type: string}}` and is placed with a two-ended `route:`
- **THEN** its script receives `route` as JSON with two ends, each with `origin`, `z` and `x` as three numbers, and `lead`, and the part, which declares no ports, is connected at both ends by the end frame's origin

#### Scenario: Checks on a script part
- **WHEN** a script part that declares `route` is placed with a route whose `via` point coincides with an end or `through` entry anywhere along it, or whose script builds more than one solid
- **THEN** the link is left out with the reason, as for a routed part; the bend and self-crossing checks, which need a profile radius known before the build, are not applied to it

#### Scenario: Part that cannot be routed
- **WHEN** a `step` part is placed with `route:`
- **THEN** the build reports that the part type is not routed and does not declare a `route` parameter, and the link is left out

### Requirement: A route that cannot be built is an error, not a bad solid
A routed part SHALL NOT be added to the assembly when its path cannot carry its profile. That is when any two of its knots coincide, when the path bends tighter than the profile's outer radius, when two non-adjacent stretches of the path come closer than the profile's outer diameter, or when the sweep fails or yields anything but one valid solid. The build SHALL report the reason, where on the path it happens, and the values involved. `pc qual test` SHALL fail the assembly for it.

#### Scenario: Bend tighter than the tube
- **WHEN** a 6 mm tube's route has a `via` point 1 mm from an end, so that the path bends at a radius of 1.8 mm
- **THEN** the routed link is left out, and the build reports a bend radius of 1.8 mm at the given point against the tube's 3 mm radius, suggesting moving the `via` point

#### Scenario: Path crossing itself
- **WHEN** `via` points make the path loop back through itself
- **THEN** the routed link is left out, and the build reports the two path positions that come closer than the profile's diameter

#### Scenario: A port passed through with no way decided
- **WHEN** the knots before and after a `through` entry lie level along its axis, so that nothing decides which way along the axis it passes; for a routed part or a script part alike
- **THEN** the routed link is left out before anything is built, and the build names the entry and suggests moving a `via` point so that the path comes to it along its axis

#### Scenario: Coincident knots
- **WHEN** a `via` point coincides with an end's or a `through` entry's origin, two `via` points coincide, or two ends are at the same point, whether or not the two are next to each other along the route
- **THEN** the routed link is left out, and the build names the two knots

#### Scenario: A route left out still fails the assembly
- **WHEN** a route is refused and its link is left out of the assembly
- **THEN** `pc qual test` fails the assembly with the refusal, under the link's name

#### Scenario: Sweep yields an invalid solid
- **WHEN** a sketch profile's sweep along an otherwise acceptable path produces a shape that OCCT rejects as invalid, or that is not one solid
- **THEN** the routed link is left out and the build reports the defect, rather than adding the shape with a warning

### Requirement: Routes are checked for interference
`pc qual test`'s interference check SHALL cover routed parts. Each end and `through` entry SHALL count as a joint between the routed part and the part it connects to, so an overlap there SHALL be expected only where that joint's ports, interfaces or mating declare it, as for a connected part. Anywhere else, a routed part that shares space with another part SHALL fail the check, naming both.

#### Scenario: Waypoint on the wrong stretch
- **WHEN** a cable's `via` point meant for the stretch before a panel's grommet is listed on the second end instead, so that the path goes back through the panel
- **THEN** `pc qual test` fails the assembly with an interference naming the cable and the panel

#### Scenario: Waypoint on the right stretch
- **WHEN** the same `via` point is listed on the grommet
- **THEN** no interference is reported

#### Scenario: Tube pushed over a barb
- **WHEN** a tube's end overlaps the barb it is pushed onto, inside the tube on the cable side of its end face, and the barb port declares `snapIn`
- **THEN** no interference is reported for that end, as far as the joint's depth from the end face

#### Scenario: Cable resting against a part
- **WHEN** a cable's path touches a part's surface without entering it
- **THEN** no interference is reported

#### Scenario: Grommet gripping the cable on both sides
- **WHEN** a `through` entry joins a cable to a grommet in the middle of a panel, the joint declares the overlap, and the grommet grips the cable on both sides of its port
- **THEN** no interference is reported for the grommet on either side, within the joint's depth from the port

#### Scenario: Same cable back past the joint
- **WHEN** a cable pushed onto a manifold's barb loops back and passes through the manifold again within the joint's depth of the barb's axis but far along the path from the joint
- **THEN** `pc qual test` fails the assembly with an interference at that second pass: only the joint's own stretch of cable is excused

#### Scenario: Joined at one place, colliding at another
- **WHEN** a hose is pushed onto a manifold's barb, whose port declares `snapIn`, and its path also runs back through the same manifold elsewhere
- **THEN** `pc qual test` fails the assembly with an interference naming the hose and the manifold at that other place: the allowance covers the joint's region, not every overlap between the two parts

### Requirement: Length and bend radius are checked
When a routed part declares `length`, `pc qual test` SHALL fail the assembly if the route's centreline is longer than that length. The centreline runs from the first end face to the last, so it includes leads but not port offsets. When it declares `minBendRadius`, `pc qual test` SHALL fail the assembly if the tightest bend of the centreline has a smaller radius. Either failure SHALL state the measured and the declared value. The route SHALL NOT be reshaped to meet either limit.

#### Scenario: Cable too short
- **WHEN** a routed part declares `length: 300` and its route's centreline measures 342 mm
- **THEN** `pc qual test` fails the assembly, naming the link, 342 mm and 300 mm

#### Scenario: Bend too tight for the material
- **WHEN** a routed part declares `minBendRadius: 15`, and the route's tightest bend has a radius of 9 mm, larger than the profile's radius
- **THEN** the part is built, and `pc qual test` fails the assembly, naming the link, 9 mm and 15 mm

#### Scenario: Port offsets are not cable
- **WHEN** a routed part declares `length: 1000` and an end port 12 mm beyond its end face, and the centreline measures 995 mm
- **THEN** `pc qual test` reports no length problem

#### Scenario: Within limits
- **WHEN** the route is no longer than `length` and bends no tighter than `minBendRadius`
- **THEN** `pc qual test` reports no route problem
