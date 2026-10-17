# //pub/examples/partcad/feature_simulate_joints

PartCAD example project which demonstrates simulating a mechanism - one of every kind of joint - checked against its closed form.

A **mechanism** is an assembly whose parts move against each other on
their joints, and what it does can be worked out on paper. This package
states one of every kind of joint PartCAD has, beginning with a pendulum,
and holds each simulation to the answer: in MuJoCo, and in Gazebo too for
every kind Gazebo builds.

`pendulum` is a 300 x 20 x 10 mm bar hung by one end from a frame. The
frame implements `axle`, whose `motion: revolute` says that a bar joined
to it keeps its turn about the axle; so the connection in `pendulum.assy`
is a **joint**, named `swing`, and the bar is a rigid body of its own.
`pc info -a pendulum` lists it under `Joints`. `toParams: {turnZ: ...}` is
where the joint **starts**, and its zero is the parameter at zero -- here,
hanging straight down. `pendulum` starts at 90 degrees and `nudged`, the
same file, at 5: `pc render` draws each where it starts, and the
simulation starts it there too.

`bolted` is the scene they run in. It places its subject `fixed: true`, so
the root body -- the frame -- is welded to the world and the joints inside
it still move; and it states its gravity, 9.81 m/s^2, which every formula
here is written with (MuJoCo's own is 9.81, SDFormat's 9.8).

| Assembly | Type | Starts at | Held to | Gazebo |
| --- | --- | --- | --- | --- |
| `pendulum`, `nudged` | `revolute`, bounded both sides | 90 deg; 5 deg | its speed through the bottom and when it gets there; its period | yes |
| `wound` | `revolute`, unbounded | 270 deg | reads 270, then 360 at the bottom at the pendulum's speed and time (wrapped into +-180 it would read -90, a lost start 0) | yes |
| `door` | `revolute`, `upper: 30` only | -90 deg | the pendulum's speed at the bottom, so the open side stopped nothing; turned back before 45, where it would reach 90 | yes |
| `incline` | `prismatic`, `lower: 0` only | 200 mm up a rail at 30 deg | slides as g sin 30 deg pulls it, and stops at the stop | yes |
| `collar` | `cylindrical` | 5 deg, 260 mm up a shaft at 30 deg | in one run slides as g sin 30 deg pulls it and swings at the period g cos 30 deg gives it: exactly uncoupled | refused |
| `nut` | `screw`, 10 mm lead | 45 deg, 100 mm up | runs down as slowly as the turn it is given says, 36 degrees a millimetre | yes |
| `hooke`, `hooke_across` | `universal` | 5 deg about one turn or the other | that turn's period; the other stays at nought | yes |
| `spherical` | `ball` | twisted 90, tilted 5 | swings in its own plane, at `hooke_across`'s period, so both turns of the start were kept; the twist stays at 90 | yes |
| `cone` | `ball`, bounded at 20 deg | 5 deg from upright | falls against its bound and stays inside 30, where it would fall to 180 | not declared |
| `wall` | `planar` | 50 mm up, 100 along, 30 deg | falls freely; its other two readings do not move | refused |
| `stage` | `composite`, `dof: [moveX, moveY]` | 50 mm up, 100 along | falls freely and does not move sideways | refused |
| `loose` | `floating` | 100 mm above its base | falls freely and comes to rest *on* the base | yes |
| `locked` | none, `motion: fixed` | level, the frame turned | one body, no joint, and it stays put | yes |

Each one with a joint starts away from its zero, so every run checks the
start and its reading back. Each new one states its joint on its own
connection: a `motion:` in the ASSY file outranks the interfaces', and is
in the contact frame, where `toParams` and the readings are too.

Gazebo refuses three types rather than invent a link of a mass nobody
measured -- SDFormat has no joint for a cylindrical or a planar pair, and
a composite is a chain of bodies the declaration leaves out -- and cannot
bound a ball (it would bound each of its three coordinates, a box rather
than a cone). So `collar`, `wall`, `stage` and `cone` have no Gazebo run.


## Usage
```shell
pc sim -a pendulum       # released horizontal, it passes the bottom at the speed its fall gives it
pc sim -a nut            # a nut runs down its screw as slowly as the turn it is given says
pc test -f sim           # every one, as the check pc test runs
pc sim --json -a nudged  # what each engine reports: joints.swing, in degrees and deg/s
```

### The closed forms

Everything follows from the dimensions and g -- the mass cancels, so the
material does not matter. Each validation writes its formula out.

| | Formula | Here |
| --- | --- | --- |
| a 300 x 10 mm bar about its end: I/m, and d below the axle | L^2/3 + h^2/12, L/2 | 0.0300083 m^2, 0.15 m |
| its speed through the bottom, released level (`pendulum`, `wound`, `door`) | sqrt(2 g d / (I/m)) | 567.41 deg/s |
| the time it takes to get there (`pendulum`; `wound` to 360) | K(sin 45 deg) sqrt((I/m) / (g d)) | 0.26477 s |
| its small-angle period (`nudged`) | 2 pi sqrt((I/m) / (g d)) | 0.89726 s |
| slid down a frictionless line at 30 deg (`incline`, `collar`) | (g sin 30 deg) t^2 / 2 | 98.1 mm at 0.2 s |
| the collar's arm about its shaft: L = 50, t = 20 mm, centre c = 15 mm off it, less a bore r = 5 mm | 2 pi sqrt(I / (m g cos 30 deg d)), I = L t ((L^2 + t^2)/12 + c^2) - pi r^4/2, m d = L t c | 0.3798 s |
| a ring, r1 = 5 and r2 = 15 mm, down a screw of lead p = 10 mm (`nut`) | g / (1 + (I/m) (2 pi / p)^2), I/m = (r1^2 + r2^2)/2; 360 / p | 0.1948 m/s^2; 36 deg/mm |
| a 200 x 200 x 10 mm plate hung by an edge, about it (`hooke`) | 2 pi sqrt((L^2/3 + t^2/12) / (g L/2)) | 0.7327 s |
| the same, in its own plane (`hooke_across`, `spherical`) | 2 pi sqrt((L^2/3 + w^2/12) / (g L/2)) | 0.8190 s |
| a free fall (`wall`, `stage`, `loose`) | g t^2 / 2 | 49.05 mm at 0.1 s |
| how far `door` swings against its stop at 30 deg | a bound, not a closed form | under 45 deg, where it would reach 90 |
| how far `cone` turns against its bound at 20 deg | 2 acos(w), w its rotation's first element | 15 to 30 deg, where it would reach 180 |
| how far `locked`, bolted down, moves | -- | 0 |

K is the complete elliptic integral of the first kind; K(sin 45 deg) is
1.854075, which is why a pendulum released level takes 18 % longer to the
bottom than the small-angle formula says.

A stop's own give is not what these check, so a bound is held to where
the body would be without it. MuJoCo softens a stop a few degrees at speed
(`door` gets to 34), and softens a ball's bound by the average of its
three freedoms' inverse inertia, so a slender bar, which barely resists
turning about its own length, is barely held: a 300 mm bar on a 20 degree
cone swings to 45. `cone` stands the plate on its bound, and it stops at 21.

### Two engines, one validation

Both plugins report a joint under its PartCAD name, in degrees and
millimetres: `pos` and `vel` are a number for one freedom and an object
keyed by parameter for several (`{"turnZ": 5.0, "moveZ": 260.0}`), and a
ball and a free body have `quat` too. So a Gazebo run states its MuJoCo
run's validation -- the same YAML anchor -- and it is written to hold in
both:

- Gazebo's first reading, `before`, is 19 ms in: the first instant every
  joint stream has reached. A start is checked against the closed form at
  `before["time"]`, which in MuJoCo is nought.
- Gazebo reports a reading per pose it publishes, every 17 ms or so at
  real time, however many `samples` are asked for. So an instant -- the
  bottom, a crossing of nought -- is read between the readings either side
  of it, and a distance at the reading nearest a time, at its own time.
- A Gazebo run states no `timestep`: the plugin hands it to `gz sim -z`,
  an update rate rather than a step, so the step stays SDFormat's 1 ms.
  That puts a free fall g t dt / 2 ahead, 1 % at 0.1 s: `loose` allows 2 %.


## Assemblies

### collar
<table><tr>
<td valign=top><a href="collar.assy"><img src="././collar.svg" alt="collar" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A collar with an arm on a shaft at 30 degrees, started 260 mm up and turned 5 degrees</td>
</tr></table>

### cone
<table><tr>
<td valign=top><a href="cone.assy"><img src="././cone.svg" alt="cone" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The plate stood on a ball bounded at 20 degrees, started 5 degrees from upright</td>
</tr></table>

### door
<table><tr>
<td valign=top><a href="door.assy"><img src="././door.svg" alt="door" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The pendulum bounded at 30 degrees on one side only, released at -90</td>
</tr></table>

### hooke
<table><tr>
<td valign=top><a href="hooke.assy"><img src="././hooke.svg" alt="hooke" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The plate on a universal joint, started 5 degrees about the edge it hangs by</td>
<td valign=top>Parameters:<br/><ul>
<li>edge: 5</li>
<li>across: 0</li>
</ul>
</td>
</tr></table>

### hooke_across
<table><tr>
<td valign=top><a href="hooke.assy"><img src="././hooke_across.svg" alt="hooke_across" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The plate on a universal joint, started 5 degrees about the line square to it</td>
<td valign=top>Parameters:<br/><ul>
<li>edge: 0</li>
<li>across: 5</li>
</ul>
</td>
</tr></table>

### incline
<table><tr>
<td valign=top><a href="incline.assy"><img src="././incline.svg" alt="incline" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A carriage on a rail at 30 degrees, bounded at the rail's lower end, started 200 mm up</td>
</tr></table>

### locked
<table><tr>
<td valign=top><a href="locked.assy"><img src="././locked.svg" alt="locked" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The pendulum with its joint locked</td>
</tr></table>

### loose
<table><tr>
<td valign=top><a href="loose.assy"><img src="././loose.svg" alt="loose" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A block held by nothing, 100 mm above its base</td>
</tr></table>

### nudged
<table><tr>
<td valign=top><a href="pendulum.assy"><img src="././nudged.svg" alt="nudged" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The same pendulum, started 5 degrees from hanging straight down</td>
<td valign=top>Parameters:<br/><ul>
<li>start: 5</li>
</ul>
</td>
</tr></table>

### nut
<table><tr>
<td valign=top><a href="nut.assy"><img src="././nut.svg" alt="nut" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A nut on an upright screw with a 10 mm lead, started 100 mm up</td>
</tr></table>

### pendulum
<table><tr>
<td valign=top><a href="pendulum.assy"><img src="././pendulum.svg" alt="pendulum" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The bar hung from the frame, released horizontal</td>
<td valign=top>Parameters:<br/><ul>
<li>start: 90</li>
</ul>
</td>
</tr></table>

### spherical
<table><tr>
<td valign=top><a href="spherical.assy"><img src="././spherical.svg" alt="spherical" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The plate on a ball, twisted 90 degrees and tilted 5</td>
</tr></table>

### stage
<table><tr>
<td valign=top><a href="stage.assy"><img src="././stage.svg" alt="stage" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The plate on two moves against a face, started 50 mm up and 100 mm along</td>
</tr></table>

### wall
<table><tr>
<td valign=top><a href="wall.assy"><img src="././wall.svg" alt="wall" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The plate on a planar joint against a face, started 50 mm up, 100 mm along and turned 30 degrees</td>
</tr></table>

### wound
<table><tr>
<td valign=top><a href="wound.assy"><img src="././wound.svg" alt="wound" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>The pendulum unbounded, started at 270 degrees</td>
</tr></table>

## Scenes

### bolted
<table><tr>
<td valign=top><a href="bolted.assy"><img src="././bolted.svg" alt="bolted" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>An empty world with whatever is simulated in it bolted down by its root</td>
<td valign=top>Parameters:<br/><ul>
<li>subject: pendulum</li>
<li>subject_kind: assembly</li>
<li>subject_offset: 0 0 400 0 0 1 0</li>
</ul>
</td>
</tr></table>

## Parts

### arm
<table><tr>
<td valign=top><a href="arm.py"><img src="././arm.svg" alt="arm" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A 20 x 50 x 20 mm arm with a 10 mm bore through it, 10 mm in from one end</td>
</tr></table>

### bar
<table><tr>
<td valign=top><a href="bar.py"><img src="././bar.svg" alt="bar" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A 300 x 20 x 10 mm bar, its eye on the end that sits on the origin</td>
</tr></table>

### frame
<table><tr>
<td valign=top><a href="frame.py"><img src="././frame.svg" alt="frame" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A 40 mm cube, its axle on the +Y face</td>
</tr></table>

### plate
<table><tr>
<td valign=top><a href="plate.py"><img src="././plate.svg" alt="plate" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A 200 x 200 x 10 mm plate, centred on its origin and flat in its X-Z plane</td>
</tr></table>

### ring
<table><tr>
<td valign=top><a href="ring.py"><img src="././ring.svg" alt="ring" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A ring with a 10 mm bore and 30 mm outside, 10 mm tall</td>
</tr></table>

### rod
<table><tr>
<td valign=top><a href="rod.py"><img src="././rod.svg" alt="rod" style="width: auto; height: auto; max-width: 200px; max-height: 200px;"></a></td>
<td valign=top>A round rod 9 mm across and 300 mm long, up its Z axis from the origin</td>
</tr></table>

## Interfaces

<br/><br/>

*Generated by [PartCAD](https://partcad.org/)*
