---
name: sim-assembly-fea
description: Turn what a simulation of an assembly measured into a stress analysis of one part in it - run the assembly's `simulate:` entry, read the forces and moments acting on the body the part is welded into at the end of the run (the "after" state), work out which of them load the part and where, and write the part an `fea:` section that applies them as forces with directions in its own frame (with its apparent gravity), then run `pc cae fea` and, in an IDE, show the result in the Digital Thread. Use for /pc:sim-assembly-fea, or when the user asks how a simulated motion stresses a part, wants an FEA "under the loads from the simulation", or asks whether a gear, a shaft or a bracket survives what a mechanism does to it.
---

# pc:sim-assembly-fea

Find out what a mechanism does to one of its parts, and analyse the part under
it. `$ARGUMENTS` names three things: the **assembly**, the **simulation** (the
name of an entry in its `simulate:`), and the **part** (a link path in the
assembly, such as `lower/knee-worm-gear/gear`, or a part name such as
`motion/worm_gear_28t` when only one placement of it is in the assembly). Ask
for whichever is missing; `pc --no-ansi info -a <assembly>` prints the
assembly's `simulate:` entries, and the result of a run lists its parts.

What you produce is an `fea:` section -- the part's boundary conditions -- whose
every number came out of the simulation, a run of `pc cae fea` with its result,
and a short account of how each load got from the simulation to the part.

A rigid-body simulation knows what acts on each **body**, and a body is often
several parts welded together. What passes between two parts of one body is
the body's own business: no simulation reports it. So reading the loads is
arithmetic, which the helper beside this file does for you, and turning them
into the part's loads is engineering, which you do and explain. Never present
the second as if it were the first.

Pass `--no-ansi` on every run (it is global and goes before the subcommand). Make
sure PartCAD is available as `/pc:init` describes.

## 1. Run the simulation

```sh
mkdir -p /tmp/pc-sim-fea
pc --no-ansi sim -a <assembly> -f <simulation> --json > /tmp/pc-sim-fea/sim.json 2> /tmp/pc-sim-fea/sim.log
```

`--json` prints the whole result on standard output and the log goes to
standard error, so keep them apart. Check, in this order:

- the run happened (`"error": null`); a run that did not is reported with what
  it said, and there is nothing to analyse;
- the result has `parts` -- which body each part is in -- and the bodies have
  `loads`. A plugin that reports neither is older than loads, or was run with
  `params: {loads: false}`: say so, and stop. MuJoCo reports every load;
  Gazebo reports what each joint passes and each body's weight, and names in
  `warnings` what it does not (a weld to the world, contacts, accelerations);
- what `warnings` says. A load an engine could not report is named there, and
  an analysis that leaves it out has to say so.

The loads this skill uses are the **`after`** reading -- the state the run ended
in. If the user asks about the worst moment rather than the end, run with
`params: {samples: N}` and pick the sample with the largest load on the part's
body; say which instant you used.

## 2. Read the loads in the part's frame

```sh
python <this skill's directory>/part_loads.py loads /tmp/pc-sim-fea/sim.json <part>
```

It finds the part's body and where the part sits in it, and prints every load on
that body with `at` (mm), `force` (N) and `torque` (N·m about `at`) in the
**part's own frame** -- the frame its ports, and so an `fea:` section, are
written in -- beside:

- `apparent_gravity`: the scene's gravity less the acceleration of the part's
  origin, `g - a`, in m/s² and the part's frame -- on a body that turns, its
  centre of mass's and what the turning adds that far from it. That is the
  part's `gravity:` below: its own weight, and what its acceleration flings it
  by;
- `total`: the loads added up. For a body every load of which was reported it is
  the body's mass times its acceleration; on Gazebo it need not be.

`point` puts a point (or with `--direction` a direction) of another part's frame
into this part's -- which is how you find where a mating part touches it:

```sh
python <this skill's directory>/part_loads.py point /tmp/pc-sim-fea/sim.json <other part> <part> X Y Z
```

Read each load: what it is (`kind`), what it comes from (`from`), and for a
joint its name (`joint`). Find the connection that made each joint in the ASSY
file -- its `joint:` or `<child link>-<target link>` -- and note which
interfaces of which parts it joins. `pc --no-ansi info <part>` lists the
part's interfaces, instances and ports, with each port's location in its frame.

## 3. Work out what loads the part

Every condition of an `fea:` section lands on a port of an interface the part
implements, so each load has to end at one. Three cases:

**The part is the whole body.** Every load on the body acts on the part. A joint's
load lands on the interface the connection used on this part; a contact lands on
the port nearest its `at`. Its gravity is `apparent_gravity`.

**A load acts at one of the part's own ports.** A joint whose connection is at
an interface of this part (its `at` is at one of the part's ports) passes its
force there: that is a `load:` on that port.

**The load reaches the part through what it does.** The part is welded into a
larger body, and a load on the body passes through it on its way somewhere:
a gear carries the torque of the shaft it is keyed to, a lever carries the force
at its tip, a bracket carries what hangs from it. Work it out by statics, and
write down how:

- Find the **path**: where the load enters the part and where it leaves. The
  ASSY says what the part is connected to; the loads say what is pushed where.
  Loads that bypass the part (a shaft's bending carried by its bearings, not by
  the gear on it) are not its loads.
- **Hold the part where its load leaves to the rest of its body** -- the bolts
  of a hub, the bore it is pressed on: those interfaces are its `fix:`, and the
  analysis finds their reactions. Fixing one side and loading the other is how a
  stress analysis is posed; the loads need not balance, the fixed side does.
- **Load it where the load enters**, as the force that does the job there. A
  gear transmitting a torque `T` about its axis carries, at the tooth in mesh,
  a tangential force `T / r` (`r` the pitch radius, in metres) along the pitch
  circle, and a separating force `T / r · tan α` (`α` the pressure angle, 20°
  unless the part says otherwise) toward its axis; a worm wheel's axial force is
  the worm's tangential one, `T / r · tan λ` for a lead angle `λ`, and is small --
  say whether you included it. Which tooth is in mesh is the one nearest the
  mating part: put the mating part's teeth (or its axis) into this part's frame
  with `point`, and take the nearest tooth port (`pc info` lists them). A torque
  the gear's own frame gives as `torque` about its axis is the `T` -- check the
  axis against the part's geometry, and the sign: the force has to turn the gear
  *against* the torque the rest of the body applies, which is what holds it.
- A moment that lands on one port has no spelling in `fea:` (a `load:` is a
  force). Load two ports a known distance apart with the couple, or move the
  `fix:` there and load the rest.

Every load becomes a **force with a direction**, `[x N, y N, z N]` in the part's
frame, and the part's `gravity:` is `apparent_gravity`. Leave out a load of
nought; round to three or four significant figures.

## 4. Write the `fea:` section

On the part itself if the package being worked in declares it. A part from a
dependency -- a bought gear, a vendor's bracket -- is analysed through a
reference to it in the package that declares the assembly: the loads are a fact
about this product, not about the part. Name it after the part and the product,
and keep the source's geometry and ports:

```yaml
parts:
  knee-gear:
    type: alias
    source: //pub/robotics/parts/gobilda:motion/worm_gear_28t
    desc: The knee's worm gear, as the arm loads it at the end of its 'held' simulation
    fea:
      # Who reads a direction and a gravity: an implementation whose 'reads:'
      # lists 'force' and 'gravity'. CalculiX, Elmer, Code_Aster and MOOSE do.
      implementation: //pub/feature/cae/calculix:fea
      # Where its load leaves: bolted to the hub by its four threaded holes.
      fix:
        //pub/robotics/parts/gobilda:4xM4-16mm-pattern-threaded-thru-4mm: [outer]
      load:
        # Where it enters: the knee's -2.59 N*m about the gear's axis, held by the
        # worm at tooth 13 (pitch radius 17.75 mm): 145.9 N along the pitch circle
        # and 53.1 N toward the axis (20 deg pressure angle).
        "//pub/robotics/parts/gobilda:gear-28t;module=1.25,shift=0.2":
          "13-tooth": [0 N, -2.7 N, -155.2 N]
      # g - a in the gear's frame: its own weight, standing on its edge.
      gravity: [0, -8.962, -3.990]
```

- A name under an interface is an instance of it, or one of its **ports** -- the
  way one tooth of a gear, whose teeth are the ports of one instance, is named.
  `pc info <part>` lists both.
- `implementation:` has to name one that **reads** what the section states: a
  direction (`force`) and a `gravity`. PartCAD refuses an analysis to one that
  does not, saying so, rather than letting it pull every load straight down.
- The material: an alias may carry its own `cae: fea:` -- `youngs_modulus`,
  `poissons_ratio`, `yield_strength` (Pa), `density` (kg/m³) -- for what the part
  is made of, when the implementation's defaults (steel) are not it. Say where
  the numbers come from.
- Comments say, for every condition, which load of which simulation it came
  from, at what time, and the arithmetic. A reader has to be able to redo it.

## 5. Run the analysis

```sh
pc --no-ansi cae fea :<part> 2>&1
```

The log carries the peak stress and displacement the implementation measured,
and the **findings** -- what it wants acted on (an empty list is a pass). Read the
warnings too: a condition that reached no material did nothing, and an analysis
with a condition doing nothing is answering another question. A port whose
sketch "lies on no surface" (a gear's tooth, whose sketch is its cross-section
at the pitch circle; a hole's outline over the hole) is applied to the surface
within `port_radius` of the port instead, and PartCAD says so and how much
area that was: check it is the surface you meant. CalculiX applies every
condition to the mesh nodes near its port either way, and names a port it found
no node near. Any implementation whose `reads:` lists `force` and `gravity`
will do -- CalculiX, Elmer, Code_Aster, MOOSE; on the same part they should
agree to within what their meshes differ by. The model is written
beside the package as `<part>.fea.glb`. `pc test -f fea :<part>` runs the same
analysis as a check.

If the daemon was already running when you edited an ASSY file, `pc daemon stop`
first: it rereads a changed `partcad.yaml` on its own, and an ASSY file it does
not.

## 6. Show it, where there is somewhere to show it

In an IDE -- `TERM_PROGRAM` is `vscode` (Visual Studio Code, VSCodium, the
PartCAD IDE), or `pc --no-ansi ide state` answers rather than saying no IDE is
running -- open the result in the Digital Thread, on its FEA tab:

```sh
pc --no-ansi ide view --analysis-fea :<part>
```

Opening the tab runs the analysis, as clicking it does, and shows the stresses
with the findings under them. Elsewhere, say where the model file is.

## 7. Report

- The simulation and the instant (`after`, at `t` s), and the engine.
- Every load on the part's body, and what became of it: a condition on which
  port, or why it does not load the part.
- The `fea:` section you wrote, and where.
- What the analysis measured (peak stress against the allowable, displacement)
  and its findings, and what was left out: an axial force, a contact the engine
  did not report, a moment that was not spelled.
