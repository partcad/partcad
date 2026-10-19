# A part under the loads its mechanism puts on it

A simulation of an assembly says what acts on every **body** in it at every
reading -- what each joint passes, every contact, every weight -- and which
**part** is welded into which body, and where. A stress analysis of one part
starts from exactly that, so this package goes from one to the other on a real
mechanism: one arm of [OpenVMP](https://github.com/openvmp/openvmp-models)'s
Don1 robot, and the worm gear in its knee.

```shell
pc sim -a arm --json     # both runs, and what acts on every body at their end     sections 1 and 2
pc cae fea :knee-gear    # the gear under what the worm holds it with              sections 3 and 4
pc test                  # both, as checks
```

The step in between -- from what acts on a body to what acts on one part of
it -- is engineering rather than arithmetic, and is what the
[`/pc:sim-assembly-fea`](../../ai-agents/common/skills/sim-assembly-fea/SKILL.md)
skill does. `knee-gear`'s `fea:` section is what it wrote, and every number in
it is worked out below.

![The arm at the end of 'dropped', as MuJoCo drew it](dropped.png)

## 1. The arm, and what holds its knee

`arm` is Don1's lower arm and upper arm, joined at the knee the way
`robot/corner` joins them: the upper arm's hub on the end of the knee shaft.
In the robot, that shaft carries a goBILDA 28-tooth worm gear, and a worm on
the lower arm turns the gear. A worm drive does not run backwards, so whatever
the upper arm does, the knee stays where the motor left it, and the gear's
teeth are what hold it there.

A rigid-body simulation has no teeth to push on, so `arm.assy` keeps the
knee's turn free (`motion: dof: [turnZ]`) and puts the worm's hold on that
joint as a **spring**: 2000 N·m/rad, about what a MOD 1.25 worm, its gear and
the shaft between them give, at rest where the knee starts
(`springReference`), damped to about a tenth of critical. The arm gives a
little and stops ringing, as the real one does.

The scene, `hung`, bolts the subject's root body -- the lower arm -- to the
world (`fixed: true`), and `dropped` places it upside down, with the upper arm
level from the knee. Let go, the upper arm drops onto the worm's give, swings,
and comes to rest.

Both arms' parts name no material, so MuJoCo is handed PartCAD's default
density, 2700 kg/m³: the lower arm's body is 1.480 kg and the upper arm 0.8644
kg, with its centre of mass 305.5 mm out from the knee's axis. The meshes are
handed over coarser than the exporter's own (`export: mjcf:` in
`partcad.yaml`): at the default the worm's thread is more triangles than
MuJoCo reads from one file.

## 2. What the run is held to

At rest the worm holds the moment of the upper arm's weight about the knee,
and gives as far as that moment turns the spring:

| | formula | here |
| --- | --- | --- |
| the moment the worm holds | m g d | 0.8644 kg × 9.81 m/s² × 0.3055 m = 2.591 N·m |
| how far the knee gives | m g d / k | 2.591 / 2000 = 1.295 mrad = 0.0742° |
| how far it swings past that, let go at once | 1 + e^(−πζ/√(1−ζ²)), ζ ≈ 0.1 | about 1.73 times as far |

MuJoCo ends the second at 89.9258° -- 0.0742° short of 90 -- and swings to
89.872° on the way, 1.72 times as far, at t = 0.020 s. `dropped`'s
`validation:` checks both, the first to a percent. They are about joints, so
any simulation plugin answers them, and `dropped_in_gazebo` holds Gazebo to the
very same text: it ends at 89.9258° too, and is seen at 1.67 times as far at
t = 0.0215 s (Gazebo's readings are the first pose message past each instant,
so it sees the swing's bottom a little late).

## 3. What acts on the gear's body

A plugin that reports loads (the MuJoCo plugin, and Gazebo for what Gazebo
measures) says, at the end of the run, what acts on the lower arm's body --
which the gear, its hub, the knee shaft, the worm and everything else of the
lower arm are welded into. `part_loads.py`, beside the skill, puts them in
the gear's own frame, the frame its ports and so its `fea:` section are
written in:

```shell
pc --no-ansi sim -a arm -f dropped --json > sim.json
python part_loads.py loads sim.json knee-worm-gear/gear
```

| load | at, mm | force, N | moment about `at`, N·m |
| --- | --- | --- | --- |
| the knee: what the upper arm passes to the lower one | (−40.0, 0, 0) | (0, −7.747, −3.449) | (**−2.590**, 0.137, −0.308) |
| the weld to the world | (−0.3, −170.7, 62.8) | (0, 21.008, 9.353) | (4.060, 0, 0) |
| the body's own weight, at its centre of mass | (−0.2, −118.6, 56.2) | (0, −13.261, −5.904) | -- |

They add up to nought, to the last printed digit: the body is at rest and
every load on it was reported. The gear's apparent gravity, `g − a`, is the
scene's gravity at rest -- (0, −8.962, −3.990) m/s², the gear standing on its
edge -- and that is its `gravity:`.

Gazebo (`-f dropped_in_gazebo`) reports the knee's row and the weight's to the
same four figures, and no weld: it makes no force-torque sensor on a joint to
the world, and says so in `warnings`. So its loads do not add up -- they need
not -- and nothing below reads the weld: the gear's analysis starts from the
same `fea:` whichever engine ran.

## 4. From the body's loads to the gear's

None of those three acts on the gear as such. The gear is part of a body, and
what passes between two parts of one body is something no rigid-body
simulation reports. So the step is statics, and it goes like this.

**What goes through the gear.** The knee's load arrives at (−40.0, 0, 0): on
the gear's own axis, its X, which is the knee shaft's. Of it, the moment about
that axis, −2.590 N·m, is what turns the shaft, and in the robot the shaft can
only pass it on through the gear to the worm. The rest -- the 8.48 N of the
upper arm's weight and the bending about the other two axes -- goes through
the shaft into its two bearings, past the gear. So the gear carries 2.590 N·m,
and nothing else from the knee.

**Where it leaves.** The gear is bolted to its hub by the four threaded holes
on its hub side, which is how `assembly-worm-gear` bolts it, and the hub is on
the shaft. Those holes are the gear's `fix:`.

**Where it enters.** At the tooth in mesh with the worm. The worm's axis runs
through its bore along its own Y, through (−5.257, 0, 33.934) in its frame;
`part_loads.py point` puts that line in the gear's frame:

```shell
python part_loads.py point sim.json worm/worm knee-worm-gear/gear -5.257 0 33.934
python part_loads.py point sim.json worm/worm knee-worm-gear/gear 0 1 0 --direction
```

It passes the gear's axis 24.000 mm away -- the drive's centre distance --
along (0, −0.358, −0.934), the tangent of the gear at 159° about X from +Y.
The gear's `gear-28t` interface draws each of its 28 teeth as a port of one
instance, and tooth 13 is 0.6 mm from that point. That is the port loaded.

**How hard.** On the 17.75 mm pitch radius of a MOD 1.25 wheel of 28 teeth
shifted by 0.2 (`gear-28t;module=1.25,shift=0.2`), with the 20° pressure
angle of a standard MOD gear:

| | formula | here |
| --- | --- | --- |
| along the pitch circle | T / r | 2.590 / 0.01775 = 145.9 N, along (0, −0.358, −0.934) |
| toward the axis | T / r · tan 20° | 53.1 N, along (0, 0.934, −0.358) |
| together | | **(0, −2.7, −155.2) N** |

Its moment about X is +2.590 N·m: it turns the gear *against* the torque the
shaft puts in, which is what holding is. The worm's lead, 5.7°, adds
2.590 / 0.01775 × tan 5.7° = 14.6 N along the gear's axis; which way it
points depends on friction in a drive that holds, so it is left out, and the
`fea:` comments say so.

## 5. The analysis

`knee-gear` is the goBILDA gear by reference (`type: alias`): the gear's
geometry, interfaces and ports are goBILDA's, and the loads are this arm's, so
they belong to the package that has the arm. The reference states its own
`fea:`, and its own `cae: fea:` for the material -- goBILDA's 2314 series is
brass (its `desc:` says so), taken as free-cutting brass, C36000: 97 GPa, 0.31, 124 MPa at yield, 8500
kg/m³.

Its `fea:` names CalculiX, which **reads** a load's direction and a gravity
(its `reads: [force, gravity]`). PartCAD refuses to hand directed loads to an
implementation that does not declare that, rather than let it pull every load
straight down; that refusal is what an older CalculiX gets here.

| mesh (`mesh_size`) | elements | peak von Mises | peak displacement |
| --- | --- | --- | --- |
| 0.03 of the gear, the one declared | 27,475 | 67.6 MPa | 0.00525 mm |
| 0.02 | 57,292 | 83 MPa | 0.00535 mm |

The allowable is the yield over CalculiX's safety factor of 1.5, 82.7 MPa, so
at the declared mesh it **passes** with no findings. The displacement has
converged; the peak stress has not, and will not. The load is a traction of
155 N over the 21 mm² of tooth 13 within `port_radius` of the port, the peak
is at the root of that tooth where the patch ends, and a load that stops dead
at an edge puts a stress there that grows as the mesh resolves the edge. A real
mesh with the worm tapers off instead. Read the peak as the stress at the root
of a tooth carrying the load near its pitch line, to within the difference
between the two rows: about at the allowable, and well under the yield.

**Every load lands on a surface.** goBILDA's ports are drawn where a mating
part sits -- a hole's sketch over the hole, a tooth's at its pitch line -- so
none of their sketches lies on a face of the gear. PartCAD applies such a
condition to the surface within `port_radius` (5 % of the part, 2.04 mm here)
of the port instead, and `pc cae fea` says so once for every port, with the
area that came to: 54.4 mm² around each bolt hole -- the face around its
mouth and its thread -- and 24.6 mm² of tooth 13. CalculiX finds the mesh
nodes near each port for itself, and spreads the load over the surface among
them by area.

**Any implementation that reads a direction and a gravity will do.** The
same `fea:` section, from the same request, in each one's own image:

| implementation | elements | peak von Mises | peak displacement | findings |
| --- | --- | --- | --- | --- |
| [CalculiX](https://github.com/partcad/partcad-cae-calculix) | 27,475 | 67.6 MPa | 0.00525 mm | none |
| [Elmer](https://github.com/partcad/partcad-cae-elmer) | 28,133 | 72.9 MPa | 0.00421 mm | none |
| [Code_Aster](https://github.com/partcad/partcad-cae-code-aster) | 28,132 | 64.0 MPa | 0.00421 mm | none |
| [MOOSE](https://github.com/partcad/partcad-cae-moose) | 28,133 | 58.9 MPa | 0.00455 mm | none |

```shell
pc cae fea :knee-gear -i //pub/feature/cae/elmer:fea
```

They agree on the displacement to within how each holds the bolt holes
(CalculiX holds every node near a hole, inside the material too; the others
the surface), and on the stress to within what the edge of the loaded patch
does on each one's mesh. At 0.02 Code_Aster reads 79.8 MPa and MOOSE 62.5 MPa;
Elmer's direct solver runs out of memory there (317,295 unknowns). Which
engine ran the simulation does not matter: MuJoCo and Gazebo hand every one of
them the same loads.

## 6. At the worst moment

The skill reads the **end** of the run, which is what was asked of it. The
largest load on the gear came at the bottom of the first swing, at t =
0.020 s: −4.582 N·m about its axis, 1.77 times the end's (`part_loads.py loads
sim.json knee-worm-gear/gear --reading 3`). The analysis is linear and the
gear's own weight is under a newton against 155 N, so at that
instant the same mesh would read about 67.6 × 1.77 = 120 MPa -- over the
82.7 MPa allowable, under the yield. Let go with nothing to slow it, the knee
loads its gear harder than standing still does, and a stress analysis of the
standing arm alone would not say so.
