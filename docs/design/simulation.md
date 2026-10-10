# Simulation: design

This is the design record for physical simulation in PartCAD: what the pieces are, why they are shaped the way they
are, what is decided, and what is planned. How to *use* any of it is the user documentation's job
(`docs/source/simulation.rst` and the configuration reference it links to); this file is for whoever changes it.

Status words used below: **built** is on `devel`; **in review** is an open pull request, named; **decided** is agreed
and not built; **open** is not agreed.

## Contents

1. [Goal](#1-goal)
2. [Principles](#2-principles)
3. [The pipeline](#3-the-pipeline)
4. [Contracts](#4-contracts)
5. [Physical properties](#5-physical-properties)
6. [Scenes as worlds](#6-scenes-as-worlds)
7. [Bodies](#7-bodies)
8. [Joints](#8-joints)
9. [Simulations as tests](#9-simulations-as-tests)
10. [Caching](#10-caching)
11. [Engine plugins](#11-engine-plugins)
12. [Robot description formats](#12-robot-description-formats)
13. [Roadmap](#13-roadmap)
14. [Open questions](#14-open-questions)
15. [Lessons recorded](#15-lessons-recorded)

## 1. Goal

A part or an assembly should be able to state what it is supposed to *do* in the physical world -- stand, not tip,
float level, hold a load, reach a pose within a time, keep a joint torque under its motor's rating -- and have
PartCAD check that claim by simulating it, the same way `pc test` already checks that it can be made. The intended
use is **test-driven development of physical products**: the claim is written first, `pc test` fails, and the design
changes until it passes. Robotics, underwater and aerospace projects are the target, and so is any electromechanical
system whose correctness is a matter of dynamics rather than of shape.

Non-goals, which are as much a part of the design as the goals:

- **PartCAD is not a simulator, and does not wrap one in its wheel.** A simulator is somebody else's program with its
  own release cycle; shipping one would make every PartCAD release a statement about which version of it you get,
  and would pin a large dependency on everyone who never simulates anything. Engines come from plugin packages
  (section 11).
- **No engine-specific passthrough.** A value stored under the name of the format it came from is readable by one
  exporter. Every property is a PartCAD property with a PartCAD unit; what a format states that PartCAD has no
  property for is refused on import or reported on export (section 2).
- **Reading a format does not make PartCAD's model a copy of that format.** URDF, SDFormat, MJCF and USD are all views
  of one model.

## 2. Principles

**Derive what can be derived; store only what cannot.** PartCAD's advantage over a hand-written robot description
is that it holds the actual geometry. Mass, centre of mass, inertia and volume are computed from the solid and its
material; a joint's type, axis and limits are derived from the freedoms an interface declares. A stated value is an
explicit override, and the place for a measurement or a datasheet figure -- not the normal way to get a number.

**The CAD is the source of truth.** Derived data -- tessellations, mass properties, a run's result -- is cached and
keyed on what it was derived from, so a change to the CAD invalidates it and nothing else does (section 10).

**Model the concept, not the format.** `mu`/`mu2` is ODE's spelling of friction; a `<freejoint>` is MJCF's spelling of
a body nothing holds. PartCAD stores the concept and each exporter spells it.

**Lose loudly, never quietly.** Input nothing maps stops the import, naming what was found; a property the target
format cannot state is reported when it is written. A round trip is then lossless *and* the values mean something to
the rest of the system. The alternative -- an opaque, format-tagged passthrough -- was built first and was wrong
(section 15).

**One unit per quantity.** Lengths are millimetres and angles degrees, as everywhere in PartCAD; every other physical
quantity is SI. That is the rule `docs/source/assy.rst` already states for an assembly's `how:` section, extended to
materials and physics:

| Quantity | Unit |
|---|---|
| length, position | mm |
| angle | deg |
| mass | kg |
| density | kg/m³ |
| inertia | kg·m² |
| dynamic viscosity | Pa·s |
| acceleration, gravity | m/s² |
| force / torque | N / N·m |
| linear / angular velocity | mm/s / deg/s |

There is no unit-aware scalar type yet; each field states its unit in the schema. Unit-suffixed strings
(`"2700 kg/m^3"`, `"30 deg"`) through one shared parser are planned (section 13) -- the CAE force parser in `cae.py`
is the seed of it.

**One implementation of every rule.** The resolution of a part's physics lives in core (`partcad/physics.py`); the
arithmetic exporters need lives in one module under `partcad/wrappers/` (`mass_properties.py`), which engine plugins
import exactly as they already import `urdf_common` and `ocp_serialize`. No plugin carries a copy of a density lookup
or an inertia transform. Plugins require the PartCAD release that provides what they use; there is no compatibility
fallback while simulation has no users to be compatible with.

## 3. The pipeline

```
 part / assembly                    scene (an ASSY template)             engine plugin package
 ───────────────                    ────────────────────────             ─────────────────────
 simulate:                          parameters: subject,                 export:      writes the format
   <name>:                            subject_kind, subject_offset       import:      reads it
     scene      ───────────────▶    gravity:, medium:          ──┐       simulation:  runs it
     offset                                                       │       open:        shows it
     simulation ────────────┐                                     │
     params                 │       pc sim / pc test              │
     validation             │       1. resolve plugin + scene     │
                            │       2. build the scene with the   │
                            │          subject in it              │
                            │       3. export it in the plugin's ◀┘
                            └─────▶    'format', with its
                                       'formatOptions'
                                    4. run the plugin's script in a sandbox
                                    5. evaluate 'validation' over before/after
                                    6. verdict; result and run directory cached
```

**Built.** `src/partcad/simulation.py` holds the declaration, resolution, the run and the validation;
`src/partcad/wrappers/wrapper_simulate.py` is the sandbox entry point; `pc sim` (`partcad_cli/click/commands/sim.py`)
is the command, and the daemon's `simulate.run` does the work. `//builtin/scene:subject` is the default scene: an
empty world holding the subject at its offset.

A simulation is never of an object alone. It is of an object *in a world*, which is why a declaration names a scene
and the scene takes the object as its `subject` parameter -- one scene serves every object that names it, and
nothing special is declared for it.

## 4. Contracts

### 4.1 The `simulate:` declaration (built)

A named section of a part or an assembly (a scene, too -- section 7). Each entry states:

| Key | Meaning |
|---|---|
| `scene` | The world, by full path. Default `//builtin/scene:subject`. The subject's full path is assigned to the scene's `subject` parameter unconditionally; a scene that declares no such parameter is refused. |
| `offset` | Where the object's origin goes in the scene's frame: the fact about *this* object (where its origin sits relative to the floor it stands on) that a shared scene cannot know. Handed to the scene as `subject_offset`, seven numbers, because a parameter value has to be spellable in an instance name. |
| `simulation` | The plugin, by full path. No default: PartCAD implements no simulator. |
| `params` | Overrides of the plugin's parameters for this run (`duration`, `samples`, `gravity`, ...). |
| `validation` | A Python expression over `before`, `after` and `result`. Evaluated with a fixed set of builtins and no modules -- not a security boundary (a package can declare a CadQuery part), but what keeps a validation readable as an assertion. |
| `desc` | For whoever reads the report. |

There is deliberately no unnamed short form: the name is what `-f` selects, what the report prints beside the verdict
and what names the run directory.

### 4.2 The plugin contract (built)

**A scene with the subject in it goes in, as a file; JSON carrying `before` and `after` comes out.** The file is in the
format the plugin's `format:` names, written by the exporter that format resolves to -- looked up in the scene's
package first and then in the plugin's own, which is how a plugin implements the format it reads.
`formatOptions:` is how the plugin asks for that export (a physics run wants every body free to move; a scene on its
own means the opposite).

The request carries the plugin's declared parameters, then the declaration's `params`, then `scene_file`,
`scene_format`, `scene_name`, `subject`, `subject_kind` and `simulation`. The plugin may write artifacts into the run
directory it is handed. It returns `{success, before, after, ...}`; `wrapper_simulate.py` refuses a success that lacks
`before` or `after` as objects.

What is *inside* `before` and `after` is the plugin's vocabulary, and PartCAD neither reads nor validates it. The two
plugins PartCAD maintains share one, so that a validation reads the same against either:

| Key | Content |
|---|---|
| `time` | Simulated seconds at the reading. |
| `bodies.<name>.pos` | Body position, mm. |
| `bodies.<name>.quat` | Body orientation, `w x y z`. |
| `joints.<name>.type` | `revolute`, `continuous`, `prismatic` or `ball`. A turn with no finite limit is reported `continuous` whatever the file called it. |
| `joints.<name>.pos` / `vel` | deg and deg/s for a turn; mm and mm/s for a move. A ball joint reports `quat` and an angular velocity instead. |
| `joints.<name>.effort` | Actuator effort, N·m or N (MuJoCo's `qfrc_actuator`), when the engine reports one. |
| `samples` | The same readings at evenly spaced instants, when asked for. |

Free joints are not reported as joints -- the body pose already says it -- and a model with no joints reports
`joints: {}`. Joint reporting is **in review** (sim-mujoco #6, sim-gazebo #5). What an engine cannot report is named in
`warnings` rather than reported as zero: Gazebo's joint-state publisher never fills effort and publishes two of a ball
joint's three coordinates.

### 4.3 What an exporter is handed (built, extended in review)

A scene exporter is handed the assembly *tree* rather than the compound it decodes to (`decode: false`), because the
format *is* the tree: every node's name, label and placement are data, not baked into geometry. With
`properties: true` it is also handed, per node:

- the node's **resolved physics** -- stated values merged over derived ones (section 5), each with its unit;
- the material facts (`mu` → `friction`);
- for a scene that states them, the **world**: gravity and the medium's density and viscosity (section 6, in review in
  #757).

## 5. Physical properties

### 5.1 Materials (built; units in review in #755)

`materials:` is a section of `partcad.yaml`, packaged and shared like parts. A material states `density` (kg/m³),
`mu` (the sliding friction coefficient, dimensionless) and, for a fluid, `viscosity` (dynamic, Pa·s). A part names one
through `properties.material`, or through a `material` parameter that the factory records as that property -- which
is how two parts built from one script can be made of different things.

The public catalogs are packages of their own (`std-manufacturing-materials-metals`, `-plastic`, and the fluids --
air, fresh water and seawater at 15 °C -- inside `partcad-index`). A catalog declares the PartCAD release that reads
its units; converting the catalogs from g/mm³ to kg/m³ raises that requirement, so an older PartCAD refuses a catalog
rather than computing masses a million times too large.

### 5.2 Resolving a part's physics (in review in #755)

Every exporter, `pc info` and the simulation read one resolution, in `partcad/physics.py`:

1. a value the part **states** in `physics:` (`mass`, `centerOfMass`, `inertia`) -- a measured part beats the
   substance it is made of;
2. otherwise a value **derived** from the solid and a density, where the density is the part's own `physics.density`,
   else its material's;
3. otherwise the export's `density` parameter, else 2700 kg/m³ -- the only place a number nobody chose survives, and
   reported as such.

Volume is always measured (a part cannot state one), and the resolved physics carries it because buoyancy needs it.
The derived values are cached, keyed on the shape's own cache key plus everything the derivation reads that the
geometry key does not cover -- the resolved density and where it came from, and the stated values that override --
so a CAD edit or a material edit invalidates them and nothing else does (section 10).

`pc info` shows each value with its source: `mass 0.0176 kg (derived: 8000 mm³ at 2200 kg/m³)`,
`density 2200 kg/m³ (the material …:ptfe)`, `volume 8000 mm³ (measured)`. An assembly shows its totals: the sum of the
masses, the combined centre of mass, and the inertia about it by the parallel-axis theorem.

A link or body made of several shapes is weighed shape by shape, each at its own density, so its mass, centre of mass
and inertia come from one consistent set of densities. The combination is `mass_properties.of_body()`.

What is planned on top of it: **provenance** of a stated value (`measured | datasheet | estimated`), and `pc lint`
checks for the classic defects of published robot descriptions -- zero mass, an inertia tensor that is not positive
definite or violates the triangle inequality, a stated mass that disagrees with volume × density by more than a
tolerance, and a stated value that no longer applies because the geometry moved under it.

### 5.3 Friction and contact (built)

A material states one coefficient, and it is written wherever the target format states it: the PartCAD `friction`
property, SDFormat's `<surface><friction><ode><mu>`, URDF's `<gazebo><mu1>`, the first component of MJCF's geom
`friction`. All four are the same dimensionless number, which is the whole reason it is worth carrying. `friction2`
travels between SDFormat and URDF; MJCF has no second direction (its other two components are torsional and rolling
coefficients, different quantities), so it is reported rather than written into a slot that means something else.

PartCAD writes each *body's* coefficient. How an engine combines the two sides of a contact is the engine's model, and
the engines differ: **MuJoCo takes the larger** of the two geoms' coefficients (unless priorities say otherwise), and
**Gazebo's DART the smaller**. So a contact between two bodies of one material uses that material's `mu` in both, and
in MuJoCo a body on the ground plane gets at least the plane's default of 1.0. Each plugin documents its engine's rule,
and an example's claim has to hold under it (in review in sim-mujoco #8 and #761).

Contact solver settings are the plugin's to choose and to document. MuJoCo's default soft contacts let a body creep
under a sustained tangential load -- an aluminium block (μ 1.05) crept 33 mm down a 6° slope in ten seconds, which is
a static-friction claim answered by the solver rather than by the friction. The MuJoCo plugin therefore writes
`cone="elliptic" impratio="10" noslip_iterations="3"`, under which the same block moves under half a millimetre at 15°
(in review in sim-mujoco #8).

### 5.4 Collision geometry (planned)

Simulators separate the shape that is drawn from the shape that collides, because contact against a hundred-thousand
triangle mesh is slow and numerically ill-behaved; MuJoCo collides only convex shapes and silently takes the hull of
anything else, which is wrong for a gripper's fingers. A part should be able to say how it collides:

```yaml
parts:
  bracket:
    type: step
    collision:
      type: convexDecomposition   # or: convexHull | primitive | part | none
      maxHulls: 8
```

`convexHull` and `convexDecomposition` are computed in a sandbox and cached like any derived shape; `part` points at a
hand-simplified part version-controlled beside the real one -- which is also what a URDF import would produce instead
of a part with a suggestive name.

## 6. Scenes as worlds

### 6.1 Gravity and medium (in review in #757)

A scene states the world it describes:

```yaml
scenes:
  tank:
    type: assy
    path: tank.assy
    gravity: [0, 0, -9.81]                                  # m/s²; the engine's own value when absent
    medium: //pub/std/manufacturing/material/fluid:water    # a material; vacuum when absent
```

The defaults are what every engine assumes, so a scene that says neither simulates exactly as it did before.
Precedence for gravity is the declaration's `params`, then the scene, then the engine's default; a plugin's own
declaration carries no gravity default, since a default there would override every scene.

What the engines make of a medium differs, and each plugin documents it:

- **MuJoCo** takes the fluid's density and viscosity in `<option>` and applies its passive fluid model, which is drag
  and nothing else. Buoyancy is added by the plugin: the displaced fluid's mass over the body's mass, from the
  resolved physics. The lift acts at the **centre of buoyancy** -- the centroid of the displaced volume, which differs
  from the centre of mass for a multi-material body or one with a stated centre of mass, and is what gives a hull its
  righting moment. Core resolves each part's `centerOfVolume` with its other derived properties (cached), and
  `mass_properties.displacement_of()` gives a body's displaced volume and its centroid. MuJoCo applies the lift through
  `gravcomp`, which acts at the centre of mass, so the exporter writes each body's centre of buoyancy into the model and
  the simulation script adds the moment `(r_b − r_m) × lift` at every step. The consequence worth knowing: the model
  opened in MuJoCo's own viewer, without PartCAD's script, floats but does not right itself (in review in #763,
  sim-mujoco #9, sim-gazebo #8; `examples/feature_simulate:buoy`, released at 60°, ends upright).
- **Gazebo** writes `<world><gravity>` and reports a medium as not modelled: its buoyancy system ignores mesh
  `<scale>`, which would make PartCAD's millimetre meshes a billion times too buoyant.

Not modelled anywhere yet: a **free surface** (the medium fills the world, so a floating body rises without limit
rather than floating at its waterline), added mass, and lift. A free surface needs the submerged volume and its
centroid per step, which PartCAD can compute exactly from the B-rep and an engine can only approximate.

### 6.2 What else a world is (planned)

Lights, wind and current, the engine's own step and solver settings, the initial pose of every object, and a body
fixed to the world (section 7). This is SDFormat's `<world>`; a scene is where each of them belongs.

## 7. Bodies

Which nodes of a tree become separate rigid bodies is the decision everything else in a simulation rests on. Today
the scene exporters decide it with a switch (`flatten: true` makes every node with geometry its own free body),
which is why a stack of blocks can fall over and also why every real product falls apart in simulation. **Decided:**
it follows what PartCAD already says the two kinds of object mean (`scene.py`): an assembly is a product that was put
together, and a scene only states where things are.

| How a node is placed | Inside an assembly | Inside a scene |
|---|---|---|
| `location:` | rigidly attached to its container | a body of its own |
| `connect:` with no degree of freedom | rigidly attached to its target | a body of its own |
| `connect:` with degrees of freedom | a joint to its target (section 8) | a body of its own |
| an assembly | one articulated body tree | one articulated body tree, its root free |
| a scene | -- | every element its own body, recursively |

- **Every element of a scene is its own body**, including the elements of a scene placed inside a scene. A scene's
  `connect:` places one object against another; it attaches nothing.
- **Everything inside an assembly is attached.** Parts rigidly attached to each other are **merged into one body**:
  PartCAD has no fixed joints. The body's mass, centre of mass and inertia combine its parts' (section 5.2), and a
  format that wants a frame per part (URDF consumers expect one per link) gets it from named frames (section 8.10),
  not from fixed joints.
- **An assembly's root** is free when the assembly is placed in a scene, and the body that everything else hangs off.
- **A body fixed to the world** -- a table, a tank's walls, a robot bolted to the floor -- is a scene element marked
  `fixed: true` (open, section 14). Without it every element of a scene falls under gravity.

Consequences that come with building it:

- The stacks in `examples/feature_simulate` are arrangements, not products, so they become **scenes**, and a scene can
  therefore declare `simulate:` (it is simulated as the subject of the default world, or of another scene).
- An ASSY link can place a **scene** (today a node places only `part:` or `assembly:`), which is what a scene inside a
  scene, and the default world holding a scene, need.
- The exporters' `flatten`/`static` switches go away: the tree says what is attached, and a scene element's `fixed`
  says what is welded to the world.

## 8. Joints

**Decided; not built.** A connection between two interfaces becomes a joint when the connection keeps any degree of
freedom once it is made. The degrees of freedom are declared in `motion:`, on the interfaces, on the mating between
them and on the connection, and they combine.

### 8.1 What exists already

- **A connection is a composition of rigid transforms in a defined frame.** `connect:` places the child at
  `target placement · target port · T · target offsets · source offsets · source port⁻¹`
  (`AssemblyFactoryAssy`), where `T` is the half turn about `(1, 1, 0)` that makes two ports face each other. Call the
  frame after `T` the **contact frame**. At zero offsets the source port coincides with it.
- **Every freedom-of-movement parameter is a degree of freedom in the contact frame.** `moveX/Y/Z` and `turnX/Y/Z`,
  and custom parameters with a `type` and a `dir`, are applied in the contact frame about its origin, in millimetres
  and degrees (`interface.py`, `get_offsets`). The six predefined ones are a complete six-degree-of-freedom
  description of a connection.
- **`motion:` and `physics:` on an interface are a record** of what kind of joint a connection is and what moving it
  costs (`motion.type/axis/limits/softLimits/mimic`; `physics.maxEffort/maxVelocity/damping/friction/spring*`). Only
  the URDF converter writes them, and it has to state the axis twice, in two frames: `motion.axis` as URDF stated it,
  and the parameter's `dir` under the map `(x, y, z) → (y, x, −z)` that `T` induces.
- **A mating already overrides an interface field by field** (its `how:`), and a connection overrides the mating.

What is missing is one bit per freedom. A slotted hole's `moveX` and a screw's `moveZ` are *adjustments*: fixed once
the screw is tightened. A bearing's `turnZ` stays free while the machine runs. Today both are the same kind of
parameter, and nothing says which ones remain free.

### 8.2 Declaring degrees of freedom

A degree of freedom is declared in `motion:`, explicitly or implicitly.

**Explicitly**, by naming the freedom-of-movement parameters that stay free. The parameter already says its kind, its
direction and its range, so nothing is restated:

```yaml
interfaces:
  hinge-bore:
    ports: { bore: [[0, 0, 0], [0, 0, 1], 0] }
    parameters:
      turnZ: [-150, 150, 0]     # where a connection may place it (existing)
    motion:
      dof: [turnZ]              # and it stays free once joined
    physics:
      damping: 0.05             # N·m·s/rad -- section 8.7
      maxEffort: 2.0            # N·m
      maxVelocity: 180          # deg/s
```

**Implicitly**, by naming a kind of joint. Every degree of freedom the kind implies is declared, about the port's Z axis
unless `axis:` says otherwise, between `limits:` when they are given:

| `motion.type` | Implied degrees of freedom |
|---|---|
| `fixed` | none |
| `revolute` | one turn about `axis`, within `limits` |
| `continuous` | one turn about `axis`, unlimited |
| `prismatic` | one move along `axis`, within `limits` |
| `cylindrical` | one turn and one move about and along `axis` |
| `screw` | one turn and one move about and along `axis`, coupled by the interface's `threadStep` |
| `universal` | two turns, about `axis` and about the port's X axis |
| `ball` | three turns about the port's origin |
| `planar` | two moves across the plane normal to `axis`, and one turn about it |
| `floating` | all six |

`motion: revolute` is the short form of `motion: {type: revolute}`. An implied degree of freedom uses the interface's
freedom-of-movement parameter of the same kind along the same axis when one exists -- which is what makes it
addressable from `toParams` -- and otherwise brings its own, named as the predefined parameter would be (`turnZ`,
`moveZ`) for a principal axis and `angle`/`offset` for another, which are the names the URDF converter already
writes. So every `motion:` the URDF converter has ever generated is an implicit declaration and keeps working; the
converter switches to writing the explicit form.

A `motion:` that states both a `type` and a `dof` list must agree with itself, and `pc lint` says where it does not.

### 8.3 Where it is declared, and how declarations combine

Three places, most specific first, exactly the precedence a mating's `how:` already has:

1. **the connection's own `motion:`** -- `connect: {..., motion: fixed}` locks a joint, for one test or one variant;
2. **the mating's `motion:`** -- what this pair of interfaces does, whatever each would do with another partner (a
   6 mm pin turns in an H7 bore and is fixed in a press-fit one);
3. **the two interfaces' `motion:`, combined.**

The combination is a **sum**, because the two sides' freedoms are in series -- which is how the placement composes
them already (target offsets, then source offsets):

- the degrees of freedom are the **union** of both sides';
- two that lie **on the same axis** are **one** degree of freedom whose range is the sum of the two ranges, whose
  value is the sum of the two values, and which is unlimited if either is.

"On the same axis" means the same kind (two turns or two moves) and the same line in the contact frame with every value
at zero; two moves need only parallel directions. Opposite directions match with the sign of one of them flipped.
Both sides' directions are read in the one contact frame, which is today's placement convention -- and it means a
target interface's `turnZ` turns the child about the *contact* frame's Z, which is the target port's Z reversed. A
target's +30° therefore turns the child −30° about the target port's own Z. Limits are directional, so the user
documentation states this once, plainly.

Two swivels in series, each declaring `turnZ: [-90, 90]`, are one revolute joint over −180° to 180°; a slotted plate
on a slotted bracket is one prismatic joint over the sum of the two slots. The same rule has one trap, and it is
documented rather than special-cased: a symmetric hinge whose two leaves *both* declare `turnZ: [0, 90]` comes out with
180° of travel. A freedom is declared on the side that provides it.

### 8.4 Joint identity

A joint is named `<child-link>-<target-link>`, from the ASSY link names (every link has one; see `assy.rst`), unless
the connection names it with **`joint:`** -- not `name:`, which is the target link:

```yaml
- part: upper_arm
  connect: { name: base, to: hinge-bore, toInstance: shoulder, joint: shoulder_pan, toParams: { turnZ: 30 } }
```

That name is what a validation reads (`after["joints"]["shoulder_pan"]["pos"]`), what `motion.mimic.joint` points at,
and what every exporter writes. Link names need not be unique -- four `leg` links connected to one `table` all yield
`leg-table` -- so duplicates are suffixed in link order (`leg-table`, `leg-table-2`, ...) and `pc lint` asks for an
explicit `joint:` on each. `toInstance` was a candidate and is not used: an interface's single instance is often
unnamed.

### 8.5 The value of a joint

`toParams` (and `withParams`) has always placed the child at a value of a freedom-of-movement parameter. For a degree
of freedom it now also means the **starting position** of the joint, and the parameter at zero is the joint's zero.
The assembly as drawn -- `pc ide view`, a render, an export of geometry -- is the mechanism at those values, exactly as
it is today. A freedom-of-movement parameter that is *not* a degree of freedom stays what it was: an adjustment,
fixed at its value.

### 8.6 Internal representation

The representation is deliberately generic, so that each format turns it into its own joint types (section 8.8). A
joint is the placement composition kept as an ordered list of steps instead of multiplied out:

```text
Joint
  name        "upper_arm-base", or connect.joint
  parent      the target link's path
  child       the connected link's path
  steps       an ordered list, each one of
                fixed(location)                               a port, the half turn, an adjustment
                free(kind: turn|move, axis, lower, upper,     one degree of freedom, in the contact frame
                     value, source, coupling)
  physics     damping, friction, springStiffness, springReference, maxEffort, maxVelocity
  softLimits, mimic
```

- `source` says which interface parameter (or parameters, when two were summed) a free step came from, so that a
  report can point at the declaration.
- `coupling` ties a free step to another one: a screw's move to its turn by `threadStep`, or a `mimic` to another joint.
- **There is no joint type in it.** A type is a format's way of naming a set of free steps; deriving one is the
  exporter's job.
- The product of the steps at their current values is the child's location -- so `AssemblyChild.location` stays
  exactly what it is, and the BREP envelope, the shape cache and every exporter that does not care about joints keep
  working unchanged.

`AssemblyChild` gains `joint` (or none, for a rigid attachment). ASSY `connect:` fills it in; so can any reader that
knows its joints -- the URDF assembly factory already holds the joint table and can fill it in directly, so that a
`type: urdf` assembly simulates as a mechanism without being converted first. The joints travel to the exporters on
the envelope nodes, beside the properties.

### 8.7 Physics of a joint

`physics:` on an interface, a mating or a connection, with the same three-level precedence as `motion:`. Where a summed
degree of freedom has physics from both interfaces, the two must agree or the mating must state its own; `pc lint`
reports a disagreement. (Summing them would be wrong: two dampers in series do not add.) Damping and joint friction
are per unit of the joint's motion in SI -- N·m·s/rad for a turn, N·s/m for a move -- because that is what every
engine takes and what the URDF reader already stores, copying `<dynamics>` unchanged. It is the one place an angle is
not in degrees; the schema does not say so today, and has to.

### 8.8 Writing joints out

Each exporter classifies the free steps of each joint and writes its own types:

| Free steps | URDF | MJCF | SDFormat | USD |
|---|---|---|---|---|
| none | parts merged into one link, a visual each | one body, a geom each | one link | one rigid body |
| one turn, limited | `revolute` | `hinge`, `range` | `revolute` | revolute joint |
| one turn, unlimited | `continuous` | `hinge`, unlimited | `revolute` without limits | revolute joint |
| one move | `prismatic` | `slide` | `prismatic` | prismatic joint |
| turn + move on one axis, coupled | revolute, plus prismatic with `mimic`, through a dummy link (reported) | `hinge` + `slide` + `<equality joint polycoef>` | `screw` | generic joint (coupling reported) |
| turn + move on one axis | revolute + prismatic through a dummy link | `hinge` + `slide` | revolute + prismatic through a dummy link | generic joint |
| two turns through a point | two revolutes through a dummy link | two `hinge`s | `universal` | generic joint |
| three turns through a point | three revolutes through two dummy links | `ball` | `ball` | spherical joint |
| two moves and the normal turn | `planar` | two `slide`s + `hinge` | chain through dummy links | generic joint |
| anything else | chain through dummy links | the joints in order in one body | chain through dummy links | generic joint |

Rules the table does not show:

- **SDFormat never gets `continuous`.** Gazebo's default physics engine (DART) silently builds a `continuous` joint as
  fixed, so an unlimited turn is a `revolute` with no limits.
- **MJCF needs no dummy links**: a body may hold several joints, applied in order. A free joint is allowed only on a
  body directly under the world, so a floating degree of freedom inside a tree is written as three slides and a ball.
- **Dummy links** in URDF and SDFormat need a small mass and inertia to be accepted by the engines; they are named
  after the joint, and their existence is reported.
- **Frames.** URDF's child-link frame is the joint frame at zero. The URDF exporter takes the *moving* contact frame
  as the child link's frame, so `<axis>` is the parameter's `dir` verbatim and the part sits in its link at
  `source port⁻¹` -- the remapped-axis wrinkle of the converter disappears from the export. MJCF states a joint's
  `pos` and `axis` in the child body's frame, which is the part's own; the exporter maps the contact-frame axis into it.
- **Starting position.** MJCF writes the body at the posed configuration and the joint's `ref` at the value, so that
  MuJoCo's zero is PartCAD's zero and the body is where the assembly shows it. URDF has no starting position; the
  exporter writes the zero pose and reports the value lost (a named configuration, planned, is what an SRDF
  `group_state` would carry). SDFormat: to be checked per version; reported when not written.
- **Units** convert at the boundary only: URDF and SDFormat in radians and metres, MJCF in degrees (its default) and
  metres.

### 8.9 What this does not cover yet

- **Closed loops.** A connection's target must already be placed and a child is placed once, so a four-bar linkage
  cannot be stated; nor can URDF state one. The plan is an explicit loop-closing constraint between two ports of two
  links, written as MJCF `<equality connect/weld>` and as an SDFormat joint between links of one model, and reported
  for URDF. Until then a connection whose child is already placed is detected and refused with a message saying so.
- **Couplings between joints** beyond `mimic` and `threadStep`: gear meshes, belts, rack and pinion. They are
  relations between two joints, not properties of either, and want their own declaration.
- **Re-rooting.** A sub-assembly connected by a port that `map:` exposes from a part deep inside it has to be re-rooted
  at that part, which reverses its internal joints on the way up. MJCF and URDF both need a tree rooted at the root.

### 8.10 Named frames (planned)

Frames are the attachment points for sensors, tool centre points and grasp poses, and what a format needs for
`<frame>`, an MJCF `<site>` or a URDF fixed link. Ports already are named, located frames on a part; frames are ports,
not a parallel mechanism, and an exporter may emit one per port it is asked to. This is also how URDF consumers get
back a frame per part after rigid attachment merges the parts into one link.

## 9. Simulations as tests

`pc test` runs every `simulate:` declaration of every part and assembly as its `sim` check (`pc test -f sim`), so the
TDD loop is `pc test` -- red until the design does what it claims (in review in #756). `pc sim` remains the command
that runs and reports simulations; both go through one implementation.

**Verdicts.**

| Outcome | Verdict |
|---|---|
| the run happened and the validation holds | pass |
| the run happened and the validation does not hold, or raises | fail |
| the run could not be made: plugin or scene not found, a sandbox that will not build, a crash | fail |
| the plugin names a `container:` or `dockerImage`, and this machine has no container runtime | skip, with a warning carrying the report |
| the declaration states no `validation:` | skip in a run over a package or a tree; fail when the object is named |

Not running is a failure, not a skip: a declaration is a question, and a plugin that was asked and delivered nothing
has failed. The one excuse is the case where the implementation was never given the environment it said it needs --
it named an image, and there is nowhere for an image to run. An implementation that names no image gets no excuse:
it said it runs in an ordinary sandbox. The same rule governs the `fea` and `cfd` checks, from one shared base class.

**Claims must be true.** An example's simulation is a test in CI; a claim that passes for the wrong reason, or does
not pass, is a defect. Examples carry closed-form answers where one exists -- a pendulum's period, energy conservation,
a free fall, a body that floats because it is less dense than the fluid -- the way `examples/feature_cae` compares a
cantilever with beam theory. The `slippery` example was a counter-example: on a level floor nothing pushed its top
block sideways, so the claim that friction made it slide was false. It now stands in a `tilted` scene whose gravity
leans 15° off the vertical -- no ramp part, no edge, every stack placed as drawn -- where a block slides when μ < 0.268:
the aluminium stack holds to 0.46 mm against a 5 mm bound, and the PTFE one loses its top block, which slides 69 mm
(in review in #761). The friction table in the user documentation is measured in the same scene (#762).

**What a validation can say.** Today: positions and orientations of bodies, and joint states, at the start, at the end
and at sampled instants. Planned: inputs (an initial configuration and joint drives, section 13) and temporal helpers
over the samples (always, eventually, within).

## 10. Caching

Three kinds of derived data are cached in the existing tiers (`cacheFiles`, memcache, S3):

- **Geometry**, keyed on the object's own configuration and everything it is built from (built).
- **Derived physical properties** -- mass, volume, centre of mass, inertia -- keyed on the shape's key plus the density
  and the stated values the derivation read (in review in #755).
- **Simulation runs**: the plugin's result together with the whole run directory -- the scene file, its meshes,
  whatever the plugin wrote (built, #753). The key is the scene's own key (which covers the subject, a parameter of the
  scene), plus the plugin, its resolved options, its declared environment, the declaration's `params`, the exporter and
  its options, and the content of both scripts and of PartCAD's wrappers. Only successful runs are stored, since
  installing a missing solver changes no key.

A `validation:` is not part of a run's key: editing it re-judges the cached run rather than repeating it. The
**verdict** `pc test` records is keyed on the run's key plus the validation expressions, so that nothing stale is served
and a validation edit costs an evaluation, not a simulation -- 0.04 s on the example, with no engine started (in review
in #756). Skips, failed runs and declarations without a `validation:` are not recorded. `simulate:` itself is not part
of a shape's cache key: declaring or editing a simulation does not rebuild the object.

**What an implementation runs has to be in the key.** #753 keys a run on the content of the implementation's script and
the exporter's script, and on PartCAD's wrappers -- not on the other files those scripts import from their own package
(`mujoco_common.py`, `snapshot_raster.py`, ...), nor on the package's revision. A plugin update that changes only such a
module therefore served the previous result until `--cache-bypass`. The fix keys simulation, CAE and CAM runs on the
implementing package's content, computed once per package per process and independent of the machine and the sandbox
type (in progress).

## 11. Engine plugins

An engine plugin package declares four things about one format, because they are one body of knowledge: `import:` to
read it, `export:` to write it, `simulation:` to run it and `open:` to show it. Importing the package is what makes the
scene type, the exporter, `pc sim` and `pc ide open --with` all work at once.

| Engine | Package | Format | Where the engine comes from |
|---|---|---|---|
| MuJoCo | `partcad/partcad-sim-mujoco` | MJCF (`sim-mujoco:mjcf`) | the `mujoco` wheel, in the plugin's sandbox |
| Gazebo | `partcad/partcad-sim-gazebo` | SDFormat (`sim-gazebo:world`) | a local `gz`, else the plugin's `dockerImage` |

URDF stays in PartCAD's own `//builtin/import` and `//builtin/export`: it describes a robot rather than any one
engine's world, and ROS, MuJoCo, PyBullet and Isaac all read it.

Rules for plugins:

- **No physics in the plugin.** A plugin reads the resolved physics it is handed and calls `mass_properties` for any
  arithmetic; it never resolves a density or moves an inertia tensor itself.
- **The version requirement matches the release** that provides what the plugin uses. While PartCAD and a plugin
  change together, a plugin's CI can be red until the release exists; that is accepted. Every merge to `devel` is a
  release, so a pin written before a chain of core pull requests lands is a guess at a number: the pins in review assume
  the chain merges in order, one release each, and are corrected to the real release when it is known.
- **Runs are isolated.** Two runs on one machine must not see each other: Gazebo runs get a per-run transport partition
  (`GZ_PARTITION`), because two worlds of the same name otherwise read each other's pose and joint messages -- which
  `pc test` running several simulations at once makes routine. A partition the user set is kept as the parent
  (`<theirs>:partcad-<id>`); using it as is would put every run back into one partition (in review in sim-gazebo #7).
- **Plugins document their engine's modelling choices**: contact combination and solver settings, what a medium does,
  what is not modelled, and what is reported in `warnings`.

## 12. Robot description formats

### 12.1 URDF (built)

`type: urdf` reads a URDF as an assembly; `pc export -t urdf` writes one; `pc convert assembly` rewrites the package
between URDF and ASSY. The reader parses with ROS's `urdf_parser_py` in a sandbox, walks the joint tree at zero, and
builds the same `Assembly`/`AssemblyChild` tree an ASSY file produces: **one flat list** of links at absolute
placements -- an assembly is one configuration of the robot, so nesting a level per joint would make an arm as deep as
it has joints and say nothing the placement does not -- with the relative placements recorded in a link table, which
is what the ASSY conversion turns into joints. A `<mesh>` becomes a part reading the file the URDF named; only
`<box>`, `<cylinder>` and `<sphere>` are generated. A link is built from its collision geometry when it states both,
and the other becomes the part `<assembly>/<link>/<visual|collision>`.

What a link says about its physics is copied into named PartCAD properties in PartCAD units (`<inertial>`, `<gazebo>`
friction and contact settings, `<material>`); a joint's `<limit>`, `<dynamics>`, `<safety_controller>` and `<mimic>`
become the `motion:` and `physics:` of the interfaces it turns into. URDF that no property covers stops the import (core
URDF is a closed vocabulary, so an unknown element means PartCAD is out of date); an unknown `<gazebo>` setting is
reported rather than fatal unless `strict: true`.

The joint mapping (`pc convert assembly -t assy`): a joint becomes a **socket** interface with one port at its origin,
which the parent implements at the joint origin under an instance named after the joint, and a **plug** interface whose
one port sits at the half turn, which the child implements at its own origin, with `mates:` on the plug. Putting the
flip on the plug keeps the socket readable against the URDF. Interfaces are deduplicated on the joint's type, axis,
limits, dynamics and mimic: a four-wheeled robot gets one interface pair for its wheels. No attempt is made to match
the library of real interfaces: a URDF joint says nothing about the hardware that implements it.

What does not survive today: names (PartCAD names carry package paths), nesting, parametrization, exact B-rep geometry,
and the digital thread itself -- and on export, the joints, which are all written `fixed` because PartCAD holds one
static configuration. Section 8 is what changes the last of those.

### 12.2 SDFormat and MJCF (built, in the engine plugins)

Read and written the same way -- an `import:` and an `export:` entry, the same sandbox, the same `dropped` counters --
by the engine's plugin package (section 11). Each documents, beside its code, what it preserves; what a static
arrangement cannot hold is counted and reported. MJCF is the one format routinely used for both an assembly and a
scene, and nothing in the file says which, so it declares both.

### 12.3 Every description is a template (built)

A URDF, a `.world` and an MJCF model are rendered as Jinja2 templates before they are read, exactly as an ASSY file
is, with the same parameters (`param_<name>`, `name`). The rendered file is written under PartCAD's state directory,
never beside the original, and references keep resolving against the directory the package declared it in.

### 12.4 Export targets

| Target | State |
|---|---|
| URDF | built; joints all fixed until section 8 |
| MJCF | built, in sim-mujoco; bodies and free joints until section 8 |
| SDFormat | built, in sim-gazebo; models and free bodies until section 8 |
| USD (UsdPhysics) | planned: Isaac Sim and the wider DCC ecosystem; the generic six-degree-of-freedom joint maps the representation of section 8.6 one to one |

## 13. Roadmap

Each step is useful on its own, which is the test of whether the decomposition is right.

| # | Step | State |
|---|---|---|
| 0 | `simulate:`, plugins, `pc sim`, the default scene; property tables; URDF read/write; MJCF and SDFormat in plugins | built |
| 1 | Cache analysis, route and simulation results across sandbox types | built (#753) |
| 2 | Command names in the docs and plugins; the `pc ide open --with mujoco` text | in review (#754, sim-mujoco #4, sim-gazebo #3) |
| 3 | Mass properties from materials; kg/m³; one resolution, cached; shown in `pc info` | in review (#755, sim-mujoco #5, sim-gazebo #4, the metal and plastic catalogs) |
| 4 | Scenes state gravity and a medium; fluid materials; buoyancy | in review (#757, sim-mujoco #7, sim-gazebo #6, partcad-index #17) |
| 5 | Joint states in `before`/`after` | in review (sim-mujoco #6, sim-gazebo #5) |
| 6 | `pc test` runs simulations; verdicts and their cache | in review (#756), after #761 |
| 7 | `slippery` in a tilted scene, and MuJoCo contact settings | in review (#761, sim-mujoco #8) |
| 7a | The friction table, measured | in review (#762) |
| 7b | Buoyancy at the centre of buoyancy | in review (#763, sim-mujoco #9, sim-gazebo #8) |
| 7c | Per-run Gazebo partitions | in review (sim-gazebo #7) |
| 7d | Run keys cover what an implementation package ships | in progress |
| 7e | `resolve_resource_path` and colons in parameter values | in review (#760) |
| 7f | Skills prepare generated objects for simulation | in review (#759) |
| 7g | The user documentation refactored to how to use it; this record for the design | in progress (with #758) |
| 8 | **Joints, core model**: `motion` degrees of freedom (explicit and implied), combination, joint names, `AssemblyChild.joint`, `pc info` and `pc lint` | in progress |
| 9 | **Bodies**: the assembly/scene rule, ASSY links that place a scene, `simulate:` on a scene, `fixed:`; the `feature_simulate` stacks become scenes | decided |
| 10 | **MJCF joints**, with a pendulum example checked against its closed form | decided |
| 11 | **URDF joints**, and the converter writing `dof:`; the round trip keeps the kinematics | decided |
| 12 | **SDFormat joints** | decided |
| 13 | Inputs: `initial:` (a configuration) and `drive:` (position, velocity or effort targets over time) on `simulate:`; temporal helpers for validations | planned |
| 14 | Devices: actuators (torque constant, gear ratio, rotor inertia as MJCF `armature`) and sensors (encoders, IMU, force-torque, contact; cameras later) attached to ports | planned |
| 15 | Controller in the loop: a `software:` object, or a Python controller stepped by the plugin; ROS 2 through Gazebo | planned |
| 16 | Collision geometry (section 5.4) | planned |
| 17 | Named frames (8.10) and named configurations of an assembly | planned |
| 18 | Closed loops (8.9); a free water surface (6.1); USD export | planned |
| 19 | Unit-suffixed values through one parser | planned |

## 14. Open questions

- **Fixed to the world.** `fixed: true` on a scene link, welding it to the world, with free as the default. Not yet
  confirmed.
- **`pc sim` with no `validation:`.** `pc test` skips it in a package run and fails it when the object is named. `pc sim`
  is unchanged for now, and the recommendation is to keep it so: `pc sim --json` on a declaration with no validation is
  how one sees what a plugin reports before writing the condition.
- **Physics of a summed joint.** The proposal in 8.7 (agree or let the mating say) is not confirmed.
- **The target-side sign convention** (8.3). It is today's placement behaviour; whether to keep it or change it before
  degrees of freedom make it visible in every joint's limits is open.

## 15. Lessons recorded

Worth keeping, because each was a mistake that looked reasonable at the time, and the shape of the correction says
where the design's boundaries are.

- **The assembly representation needed no change for URDF's geometry.** `Assembly`, `AssemblyChild` and `Part`
  expressed everything on the first try -- which is the good news and the bad: the representation is exactly rich
  enough for shapes and placements and had no place at all for anything else.
- **An exporter of a tree has to be handed the tree.** Decoding an envelope into one compound is right for every other
  exporter and fatal for a robot description; hence `decode: false`.
- **An opaque properties section was the least obvious mistake.** The first version carried what a URDF said under
  `physics: {urdf: ...}`. It round-tripped perfectly and told PartCAD nothing: a mass was a mass only to the URDF
  exporter. Copying each value into a named property with a PartCAD unit is more code and a closed list to maintain,
  and is what makes the property PartCAD's rather than a souvenir.
- **Identity belongs in the name, relations in the connection.** Recording which link a part came from, and which
  link it hung off, was two more things to keep consistent with the names and connections that already said it, and it
  let the exporter take a shortcut that stopped working the moment the record was removed.
- **Merging a link's shapes into one generated shape rewrote the model.** The mesh files a URDF pointed at were
  replaced by a compound and their `<origin>` disappeared into the geometry. A link of several shapes is a
  sub-assembly, each part reading its own file at its own offset; a digital thread that rewrites what it was handed is
  not one.
- **Nesting a level per joint, and mapping the root link to the assembly, were both mistakes** -- the first expressed
  kinematics with the mechanism meant for grouping, the second looked like fidelity and only worked because each part
  remembered which link it was.
- **A cache keyed on geometry must not carry identity.** Two parts reading one mesh hash the same, so the second came
  back wearing the first one's name. What identifies the shape asked for is stamped onto the payload on every read.
- **A claim in an example is a test.** `slippery` said friction made a block slide off a level stack; nothing pushed it,
  and nothing checked until `pc test` ran simulations. An example whose claim is not checked is one readers learn to
  trust and should not.
- **Two units for one quantity is a defect, not a convention.** Material density was g/mm³ while the physics the
  exporters wrote was kg/m³, and the first fix added a second public spelling. Density is kg/m³ everywhere now.
