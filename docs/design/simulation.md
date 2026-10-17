# Simulation: design

This is the design record for physical simulation in PartCAD: what the pieces are, why they are shaped the way they
are, what is decided, and what is planned. How to *use* any of it is the user documentation's job
(`docs/source/simulation.rst` and the configuration reference it links to); this file is for whoever changes it.

Status words used below: **built** is on `devel` (with the pull request it came in, where that helps); **decided** is agreed
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
 part / assembly / scene            scene (an ASSY template)             engine plugin package
 ───────────────────────            ────────────────────────             ─────────────────────
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

A named section of a part, an assembly or a scene (section 7). Each entry states:

| Key | Meaning |
|---|---|
| `scene` | The world, by full path. Default `//builtin/scene:subject`. The subject's full path is assigned to the scene's `subject` parameter unconditionally; a scene that declares no such parameter is refused. |
| `offset` | Where the object's origin goes in the scene's frame: the fact about *this* object (where its origin sits relative to the floor it stands on) that a shared scene cannot know. Handed to the scene as `subject_offset`, seven numbers, because a parameter value has to be spellable in an instance name. |
| `simulation` | The plugin, by full path. No default: PartCAD implements no simulator. |
| `params` | Overrides of the plugin's parameters for this run (`duration`, `samples`, `gravity`, ...). |
| `validation` | A Python expression over `before`, `after` and `result`. Evaluated with a fixed set of builtins and no modules -- not a security boundary (a package can declare a CadQuery part), but what keeps a validation readable as an assertion. |
| `desc` | For whoever reads the report. |
| `feature` | The feature (or features) of the object's `requirements:` this simulation demonstrates. Read by nothing that runs it: it is what the IDE's Requirements tab and the `/pc:validate` skill read to say which features a simulation stands behind, and `pc test`'s `requirements` check fails a name the requirements do not declare (`partcad/requirements.py`). |

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
| `bodies.<name>.pos` | Body position, mm, in the world's frame. |
| `bodies.<name>.quat` | Body orientation, `w x y z`, in the world's frame. |
| `joints.<name>.type` | `revolute`, `continuous`, `prismatic` or `ball`. A turn with no finite limit is reported `continuous` whatever the file called it. |
| `joints.<name>.pos` / `vel` | deg and deg/s for a turn; mm and mm/s for a move. A ball joint reports `quat` and an angular velocity instead. |
| `joints.<name>.effort` | Actuator effort, N·m or N (MuJoCo's `qfrc_actuator`), when the engine reports one. |
| `samples` | The same readings at evenly spaced instants, when asked for. |

Free joints are not reported as joints -- the body pose already says it -- and a model with no joints reports
`joints: {}`. Joint reporting is **built** (sim-mujoco #6, sim-gazebo #5). What an engine cannot report is named in
`warnings` rather than reported as zero: Gazebo's joint-state publisher never fills effort and publishes two of a ball
joint's three coordinates.

**Names are PartCAD's and poses the world's (built).** Every `<name>` above is PartCAD's -- a body's from
`kinematics` (section 7a), a joint's from section 8.4, `<joint>.<parameter>` for a joint an engine writes as several --
whatever the file had to call it (section 4.4), and so is a name in `warnings` and the `world` a Gazebo result
carries. A body's pose is its frame in the world's, in both engines: MuJoCo's `xpos`/`xquat`, and in Gazebo its
model's pose composed with its link's -- Gazebo publishes a link relative to its model, and a body hanging off a
mechanism's root was reported in its model's frame until this. What lets the plugin say either is a **sidecar** its
exporter writes beside the scene when `formatOptions` asks for it with `names_file: true`, which both plugins do:

```json
{"version": 1, "format": "mjcf",
 "names":  {"<kind>": {"<PartCAD name>": "<name in the file>"}},
 "bodies": {"<PartCAD body>": {"path": ["<model>", "<link>"]}},
 "joints": {"<reported joint>": {"path": ["<model>", "<joint>"], "joint": "<PartCAD joint>"}}}
```

`<scene file>.names.json`, in the run directory with the meshes (`naming.sidecar_path`). `names` is what the
transcoder did, by kind (`scene`, `body`, `joint`); a `path` is the file's names from the outermost element down --
one MJCF body, an SDFormat model and its link. An entry is an object so that what a later exporter knows about a body
or a joint is a key added rather than a shape changed: the joint redesign (#795) is to record each joint's starting
value there, which an engine that writes every joint at zero re-zeroes its reading by. A reader ignores keys it does
not know; `version` changes only for one a reader of the old shape would misread. A scene file with no sidecar -- an
override exporter, an older PartCAD -- is reported under the names in it, and Gazebo then as it publishes poses, each
relative to its parent. The sidecar is beside the file rather than inside it because both engines would have to be
taught to carry it (MJCF's `<custom><text>`, an SDFormat namespaced element) and Gazebo's world is copied before it
runs (sim-gazebo `prepare_world`); a file in the run directory travels with the meshes, which `upload` sandboxes already
send both ways.

### 4.3 What an exporter is handed (built)

A scene exporter writes the assembly *tree* (`shape_tree`, which every implementation is handed beside the compound it
decodes to), because the format *is* the tree: every node's name, label and placement are data, not baked into
geometry. With
`properties: true` it is also handed, per node:

- the node's **resolved physics** -- stated values merged over derived ones (section 5), each with its unit;
- the material facts (`mu` → `friction`);
- for a scene that states them, the **world**: gravity and the medium's density and viscosity (section 6, built in
  #757).

Whatever it asks for, every node of the tree also says what it holds -- `kind`, `part`, `assembly` or `scene` --
every element a scene welds to the world says `fixed: true`, and a node a connection moves carries its `joint`
(section 8). Those are what the body rule of section 7 reads, and `wrappers/kinematics.py` is that rule, for every
exporter (built, step 9).

### 4.4 Names in a file format (built)

PartCAD's names stay PartCAD's: the default world is the scene `world`, a body is `leg-2`, a joint `shoulder_pan`. A
file format has rules of its own about names, and **each format declares them beside its own code**, as a
`naming.Rules`: its alphabet, a length limit if it has one, whether it tells `Cube` from `cube`, and its reserved names
and patterns. `wrappers/naming.py` -- pure Python beside `kinematics`, importable by a plugin the same way -- is the one
mechanism they all go through: a `Transcoder` per namespace (the names that must differ from each other) maps each
PartCAD name to an internal one, **the identity wherever the name is valid and free**, otherwise every run of
characters the format refuses made one `_`, then `-2`, `-3` ... until it is valid and unused, exactly as PartCAD tells
two bodies of one name apart. It is deterministic in claim order, idempotent per (kind, name), and keeps the mapping
both ways. Names an exporter makes up itself (a model's root link, a dummy link, a mesh, the ground plane) are
*derived* from the same pool after every PartCAD name is claimed, so a derived name is the one that yields. A name
written differently is reported, once, as a warning naming both.

| Format | Declared in | Namespaces | Alphabet | Reserved | Source |
|---|---|---|---|---|---|
| URDF | `export_urdf.URDF_NAMES` | links, joints (urdfdom checks each) | `A-Za-z0-9_.-` | `world`, `__*__` | urdfdom requires uniqueness and nothing else; the alphabet and the reserved names are what its readers need -- sdformat's `parser_urdf` (SDFormat's reservations; a `world` link *is* the world, as for ROS and MoveIt), ROS TF (no leading `/`) |
| MJCF | sim-mujoco `MJCF_NAMES`, `MJCF_BODY_NAMES` | one per element type | anything an XML attribute holds, no control characters | a body called `world` (the `<worldbody>`) | MuJoCo 3.16's compiler, checked: any characters, any length, unique per type, case-sensitive |
| SDFormat | sim-gazebo `SDF_NAMES` | one for the whole world (Gazebo reports poses by bare name) | `A-Za-z0-9_.-`, never `::` | `world`, `__*__` | libsdformat's `isReservedName` and `recursiveSiblingNoDoubleColonInNames`; the narrower alphabet is gz-transport's, since a world's and a model's names are parts of topics |
| a file beside the file (a mesh) | `naming.FILE_NAMES` | per directory | `A-Za-z0-9_-` | Windows' device names, with any extension | compared ignoring case (Windows, macOS), 200 characters |

So a scene called `world` is `world` in PartCAD and in a validation, and `world-2` only inside an SDFormat file -- the
ad hoc `partcad_world` rename is gone. MJCF needs no change for it at all (the model is not a body), and only a *body*
called `world` is written as `world-2` there.

The other exporters need no rules, because they write no PartCAD names: glTF, 3MF, OBJ, STL, STEP, IGES, BREP and
three.js are handed the geometry and write it unnamed (glTF's one node name is the fixed `edges`), and where a format
does carry names they are free text -- glTF's are not even required to be unique, and a STEP string is encoded by the
writer.

## 5. Physical properties

### 5.1 Materials (built; kg/m³ since #755)

`materials:` is a section of `partcad.yaml`, packaged and shared like parts. A material states `density` (kg/m³),
`mu` (the sliding friction coefficient, dimensionless) and, for a fluid, `viscosity` (dynamic, Pa·s). A part names one
through `properties.material`, or through a `material` parameter that the factory records as that property -- which
is how two parts built from one script can be made of different things.

The public catalogs are packages of their own (`std-manufacturing-materials-metals`, `-plastic`, and the fluids --
air, fresh water and seawater at 15 °C -- inside `partcad-index`). A catalog declares the PartCAD release that reads
its units; converting the catalogs from g/mm³ to kg/m³ raises that requirement, so an older PartCAD refuses a catalog
rather than computing masses a million times too large.

Planned on a material, so that one substance drives rendering, the manufacturing cost estimate and the simulation
alike:

- **appearance**, physically based: colour or albedo, metalness, roughness, transparency, normal maps. It matters to a
  simulation once a camera is in the loop -- a perception stack trained in simulation is sensitive to all of it -- and
  SDFormat and USD both carry a PBR description, while URDF carries an RGBA colour and a texture file;
- **restitution**;
- **static and dynamic friction**, with an optional anisotropy. Today's `friction`/`friction2`/`frictionDirection` is
  ODE's shape of it, kept because it is what URDF states; the modelled version is a static and a dynamic coefficient,
  and the URDF exporter flattens it on the way out.

```yaml
materials:
  aluminum-6061:
    density: 2700               # kg/m³
    mu: 1.05                    # today
    friction: { static: 0.61, dynamic: 0.47 }   # planned
    restitution: 0.3                            # planned
    appearance: { color: "#b8b8b8", metalness: 1.0, roughness: 0.35 }   # planned
```

### 5.2 Resolving a part's physics (built, #755)

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

How the cache entries relate. What a shape reports about itself -- its `properties:` facts, its material -- is cached
in an entry of its own beside the geometry (the geometry's key with `-props` appended). Both are filled by the one run
that instantiates the shape, and they are read apart: a consumer after a part's material need not pull its BREP out
of the cache, and a cache written before that entry existed is a miss for the properties and not for the geometry. The
derived mass properties are a third entry (`<hash>.mass`), keyed as above. A hit answers without the geometry; a miss
works the values out from what the geometry's own entry carries -- the volume, the centroid, and the inertia at unit
density that OCCT measures as the shape is built -- so a miss costs arithmetic, not a rebuild. Inside a cached
assembly the children carry the properties they were built with; only the object asking is restamped from its own
configuration on every read.

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
and an example's claim has to hold under it (built, sim-mujoco #8 and #761).

Contact solver settings are the plugin's to choose and to document. MuJoCo's default soft contacts let a body creep
under a sustained tangential load -- an aluminium block (μ 1.05) crept 33 mm down a 6° slope in ten seconds, which is
a static-friction claim answered by the solver rather than by the friction. The MuJoCo plugin therefore writes
`cone="elliptic" impratio="10" noslip_iterations="3"`, under which the same block moves under half a millimetre at 15°
(built, sim-mujoco #8).

Contact is physically a property of a **surface pairing** -- restitution, contact stiffness and damping, slip
compliance, and the solver knobs that go with them (`kp`, `kd`, `min_depth`, `max_vel`, `soft_cfm`, `soft_erp`) -- and
every engine in use approximates it per body. PartCAD therefore stores per-body values and lets each engine combine
them; a pairing-level declaration (a material pair with its own coefficients) is a possible later step, and would be
written as MJCF `<contact><pair>` and as SDFormat surface parameters on both collisions.

One plugin-side detail: a body PartCAD could not weigh -- a mesh with no solid in it -- gets the density written on its
MJCF geoms, so that MuJoCo weighs it at the right density rather than at its own default, which is water's.

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

`convexHull` and `convexDecomposition` (V-HACD and its successors) are computed in a sandbox and cached like any derived
shape, with a `tolerance` for how far the stand-in may depart from the solid; `primitive` fits a box, cylinder, sphere
or capsule to it; `part` points at a hand-simplified part version-controlled beside the real one -- which is also what
a URDF import would produce instead of a part with a suggestive name; `none` takes the body out of contact.

It is independently valuable: the same stand-ins make rendering and interference checking cheaper, and they are what
lets a URDF import's `ignoreCollision` choice -- build a link from its collision geometry or from its visual one --
become "keep both, related".

## 6. Scenes as worlds

### 6.1 Gravity and medium (built, #757)

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
  opened in MuJoCo's own viewer, without PartCAD's script, floats but does not right itself (built, #763,
  sim-mujoco #9, sim-gazebo #8; `examples/feature_simulate:buoy`, released at 60°, ends upright).
- **Gazebo** writes `<world><gravity>` and reports a medium as not modelled: its buoyancy system ignores mesh
  `<scale>`, which would make PartCAD's millimetre meshes a billion times too buoyant.

Not modelled anywhere yet: a **free surface** (the medium fills the world, so a floating body rises without limit
rather than floating at its waterline), added mass, and lift. A free surface needs the submerged volume and its
centroid per step, which PartCAD can compute exactly from the B-rep and an engine can only approximate.

### 6.2 What else a world is (planned)

Gravity and the medium went first because underwater and aerospace validation turn on them, and because neither
needed anything new below the scene: a gravity is three numbers, and a fluid is a material with one more fact on it.
What else belongs to a world, and is planned:

- **The ground and the lights.** The exporters write them today from parameters of their own (`ground_plane`,
  `light`, `sun`), because a scene has nowhere to say them.
- **A surface.** A medium fills the whole world. A waterline -- air above, water below, a body floating where they
  meet -- is a world with regions in it, which Gazebo's graded buoyancy can express and MuJoCo's fluid model cannot.
  Section 6.1 says what PartCAD can contribute: the exact submerged volume and its centroid.
- **Wind and current**: a velocity of the medium, which MuJoCo states as `<option wind>`; `medium:` grows from a
  material reference into a mapping to carry it.
- **A body fixed to the world** is built (`fixed: true`, section 7); the initial pose of every object is not.
- **Not the engine's step size, solver or iteration count.** Those belong to an engine rather than to a world; a
  `simulate:` passes them to its plugin as `params`, and a plugin documents its defaults.

This is SDFormat's `<world>`; a scene is where each of these belongs.

## 7. Bodies

Which nodes of a tree become separate rigid bodies is the decision everything else in a simulation rests on. Until
step 9 the scene exporters decided it with a switch (`flatten: true` makes every node with geometry its own free
body), which is why a stack of blocks can fall over and also why every real product falls apart in simulation.
**Built** (step 9, #784): it follows what PartCAD already says the two kinds of object mean (`scene.py`): an assembly
is a product that was put together, and a scene only states where things are. The MJCF exporter and the URDF export
write it (steps 10 and 11, sections 8.8b and 8.8c); the SDFormat exporter is step 12, and keeps its switches until then.

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
  `fixed: true`. Without it every element of a scene falls under gravity.

Consequences that came with building it:

- The stacks in `examples/feature_simulate` are arrangements, not products, so they are **scenes**, and a scene
  declares `simulate:` (it is simulated as the subject of the default world, or of another scene) (built).
- An ASSY link can place a **scene** (`scene:`), which is what a scene inside a scene, and the default world holding a
  scene, need (built).
- The exporters' `flatten`/`static` switches go away: the tree says what is attached, and a scene element's `fixed`
  says what is welded to the world (steps 10-12; built for MJCF, where `flatten` is gone and `static` now only says
  whether a free root is welded, section 8.8b).

### 7a How step 9 resolved the open details (built, #784)

Building the rule settled what the text above left open:

- **What the tree says.** Every node an assembly or a scene places carries `kind` (`part`, `assembly`, `scene`), and
  so does the root of every assembly and scene; an element a scene fixes carries `fixed: true`, and a free one nothing
  (`shape_envelope.KEY_KIND`, `KEY_FIXED`). Both are stamped by whatever placed the node, like the joint, so they are
  the placement's and a part placed loose in one scene and bolted in another is one cache entry. The payload's shape
  changed, so the cache format is 10. A tree without kinds is read by what each node carries -- children make an
  assembly, geometry a part -- which is what a lone part has always been.
- **A `links:` list inside a scene is a scene**: the ASSY factory builds containers of its own kind, as the imported
  factory always has, so a scene's grouping does not weld its elements together.
- **Refusals.** `scene:` in an assembly is an error and the link is left out; `fixed:` in an assembly, a `fixed:` that
  is not a boolean, and one on a file's root node (which is the scene itself: whether it is fixed is said by what
  places it) are reported and ignored. The ASSY schema states all three keys, and each flavor is derived from it --
  the assembly flavor forbids `scene` and `fixed`, the scene flavor `how` -- so neither is a copy. A file no package
  declares still leans to the assembly flavor; its `scene:` or `fixed:` is reported with the advice to declare it
  under `scenes:`.
- **What `fixed` fixes.** On a link that places an assembly it welds the assembly's root body, and the joints inside
  still move; on a link that places a scene, or on a `links:` list, every element inside.
- **A scene as a subject.** `simulation.subject_kind()` accepts a scene, the default world places it with `scene:` from
  `subject_kind: scene`, `pc sim -S` names one and a package walk includes scenes, and `pc test`, which already walked
  scenes, now runs their `sim` check. A generated README lists a package's scenes beside its assemblies, so the
  stacks did not disappear from their example's page for becoming what they are.
- **The helper** is `wrappers/kinematics.py`, beside `mass_properties` and importable in a sandbox the same way. Its
  API is in its docstring; in short:
  - `bodies(tree, properties)` -> the bodies, parents before children, with what the rule set aside in `problems`.
    A body is named after the label of the node that placed it, made unique as joint names are (`leg`, `leg-2`); so an
    assembly's root body is named after the link that placed the assembly, not after its first part. Its frame is that
    node's, at the starting configuration; its parent is a body, `WORLD`, or None for a free root; its physics is its
    parts combined by `mass_properties.of_body()`, except that an assembly welded whole into it that states its own
    mass is taken at its word (a robot description's link of several shapes), and one whose parts span bodies is
    weighed by its parts and reported.
  - A body's `joint` is the node's steps re-expressed for the body pair: a fixed step of role `parentFrame` -- the
    target node's frame in the parent body -- in front of them. The target is the first sibling of that label placed
    before the child, as the connection found it; one that is not there leaves the joint on the container's body, and
    says so. A sub-assembly connected through a port a `map:` exposes from deep inside it is jointed at its root body:
    re-rooting is section 8.9's, and not done.
  - `classify(joint)` -> the kind (section 8.8's names, plus `chain` and `fixed`), the freedoms in exporter units (mm
    along a unit axis, degrees; a parameter whose `dir` is not of unit length is scaled, and its range, value and
    coupling with it), and one decomposition of the joint, `origin . M_1(v_1) ... M_n(v_n) . tail`, each `M_i` about
    its axis through its point in the frame the ones before moved -- which is MJCF's joints-in-one-body and every
    format's single-axis joint. A native kind's points are its origin: a ball's centre, a universal joint's crossing,
    a cylindrical, screw or planar joint's axis.
  - Frames: `origins` (each freedom's frame against the one before; a URDF chain), `tail` (the child body in the
    moving joint frame), `location(values)`, each freedom's axis and anchor in either body (`axis_in_child`,
    `anchor_in_child` at the starting values are an MJCF joint's `axis` and `pos`), and `origin_in_child` (a native
    joint's frame in the child body: an MJCF ball's `pos`).
- **Classification details.** A turn bounded on either side is `revolute`, with None on a side that is not; one bounded
  on neither is `continuous`, whatever its declaration called it (so `motion: revolute` with no limits anywhere is
  continuous, as section 4.2 already reports one). A planar joint is two moves *then* the turn about their normal, the
  order `motion: planar` implies and a native planar joint means; the other order is a chain. Only a screw is a native
  joint with a coupling in it: a coupled pair that is not on one axis, or any other coupled set, is a chain. Lines are
  compared at the core's merge tolerance (1e-6), so two axes the core merged are one here too.
- **Placements.** A part's world placement is its body's times its placement in the body, by definition and so
  exactly; composed node by node from the root it agrees to rounding, and to the bit for the node a body is rooted at.
  So every element of a scene of parts sits where `flatten: true` put it, to the bit -- which is why the three stacks'
  runs did not change (they reported the same positions and orientations, before and after, to the last digit). The
  joint invariant (the product of the steps at their starting values is the child's placement) holds on the body
  pair to rounding and not to the bit: the tree carries placements as axis and angle, whose round trip is exact to a
  few units in the last place. Bit for bit stays the core's, where `joint.Composition` is the placement.
- **One convention kept.** A node whose shapes are labelled under its own label (`wrist` holding `wrist/1`) is one body
  wherever it is, scenes included, as every reader and exporter of a robot description has always taken it.
- **What is not honoured yet.** The MJCF exporter and the URDF export read all of it (steps 10 and 11), and a `type:
  urdf` assembly fills in its joints. The SDFormat one does not: in a Gazebo run every part with geometry is still a
  free body, so an assembly still comes apart and a `fixed:` element still falls.

What steps 10-12 take from it: call `bodies(request["wrapped"], request["properties"])` instead of walking the tree,
write one body per `Body` with `mass_parts()` as its inertial and its parts' geometry at their `placement`, a fixed
body's parent as the world, and its joint by `joint.kind`:

- **Step 10 (MJCF)**: nest each body under its parent's at `joint.location()` (the posed configuration); a free root
  gets a `<freejoint>`, a `WORLD` one none; a native `ball` is one `ball` at `origin_in_child()`, anything else
  one `hinge`/`slide` per freedom with `pos`/`axis` from `anchor_in_child`/`axis_in_child`, `ref` the freedom's
  `value` and `range` its bounds (in MJCF's angle unit); a coupling (`follows`, `ratio`, `offset`) and a `mimic` are
  `<equality joint polycoef>`; a floating degree of freedom below the root is three slides and a ball.
- **Step 11 (URDF)**: one link per body plus a dummy link per freedom past the first, at `joint.origins`, the child
  link's frame being the moving joint frame and its parts at `joint.tail . placement`; `revolute`/`continuous`/
  `prismatic`/`planar`/`floating` native, everything else a chain; the zero pose, with the starting value reported
  lost; and the URDF factory filling `AssemblyChild.joint` from its joint table, so that a URDF round-trips its
  kinematics (through ASSY too, but for chains folded through links with no geometry; section 8.8c).
- **Step 12 (SDFormat)**: one link per body, a `<joint>` per joint at `classification.origin`, a native
  `revolute` (never `continuous`), `prismatic`, `screw` (thread from the coupling), `universal` or `ball`, chains
  through dummy links as URDF; a `WORLD` parent as a joint to `world`.

## 8. Joints

**The core model is built (#766); the MJCF exporter (step 10, section 8.8b) and the URDF export (step 11, section
8.8c) write joints; SDFormat is step 12.** A connection between two interfaces becomes a joint when the connection keeps any degree of
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

A `motion:` that states both a `type` and a `dof` list must agree with itself; a disagreement is reported and `dof`
wins, and where they agree `type` supplies the range. `limits` apply to a revolute, a prismatic and a screw's turn; on
any other kind they are reported and ignored.

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

### 8.8a How the core model resolved the open details (built, #766)

Building the model (`AssemblyChild.joint`, `pc info`'s "Joints", the checks) settled what the text above left open:

- **Merging two freedoms** happens only if nothing free between them fails to commute with them, with the adjustments
  between them taken at their values rather than at zero. Placements change -- by rounding only -- only where both
  sides give a merged freedom a non-zero value.
- **Axis frames.** A mating's `motion:` states its axis in the frame of the interface that declares it; a connection's
  in the contact frame. A `dof` name at either level means that parameter on whichever interface has it.
- **Inheritance.** `motion` and `physics` are inherited from a single drop-in parent or an `alias:`, not from every
  `inherits:` instance -- an interface that inherits four hole patterns does not inherit four joints.
- **Physics** is one record per joint; any disagreement between the two interfaces is reported (8.7).
- **Where the findings are reported**: `pc test`'s `connect` check, not `pc lint`, because a lint verdict is cached per
  file and these findings depend on interfaces declared in other packages.
- **Closed loops** in an ASSY file are refused in three forms: a link placed twice, a connection to a later link that
  connects back, and a link connected to itself. A connection to a target not yet placed used to crash.
- **Scenes** place exactly as before and make no joints (section 7).
- **The invariant holds**: the factory now takes each connected child's location from the product of its steps, and
  all 39 connected children of the 19 ASSY assemblies and scenes under `examples/` -- and a converted URDF at rest and
  posed -- come out bit for bit where they were.

What step 10 (MJCF) takes from it: each envelope node carries `joint`, whose steps are parent-relative (port, half turn,
adjustments, free steps, source port⁻¹); the steps before a free one place its `pos` and `axis` in the child body; a
screw's coupling (`ratio`, `offset`) and a `mimic` are joint equalities; an unlimited bound is `None`; the starting value
is the `ref`. One classifier of free steps into joint kinds, shared by the MJCF, URDF and SDFormat exporters, belongs in
`partcad/wrappers/` beside `mass_properties`. One gap found on the way, for step 11: the URDF converter writes no `axis`
when a joint states none, so URDF's default X axis comes out as Z (fixed in step 11: the reader states X).

### 8.8b How the MJCF exporter resolved the open details (built, #786, sim-mujoco #12)

Writing the bodies and joints out of `kinematics` (section 7a) settled what section 8.8 left to the exporter:

- **The table holds as written**, every row: a hinge or a slide per freedom with `pos`/`axis` from
  `anchor_in_child`/`axis_in_child`, `ref` the starting value and `range` the bounds; a `ball` at `origin_in_child()`;
  a floating joint as three slides and a ball. A floating joint's ball is centred where the turns cross, which is fixed
  in the body it turns; `origin_in_child` is that point only with the moves at zero, so the exporter reads it there --
  a ball's own `origin_in_child()` needs no such care. Every placement MuJoCo computes from the file, at `ref` and
  moved away from it, is where `joint.location(values)` puts the body, to 1e-9 m.
- **Names.** A joint written as one MJCF joint is named exactly as PartCAD names it, so `after["joints"]["swing"]`
  reads it. One written as several is `<name>.<parameter>` for each (`nut-bolt.turnZ`, `nut-bolt.moveZ`), and a
  floating joint's ball `<name>.ball`. Bodies take `kinematics`' names, so a second body of one name is `cube-2` where
  the exporter used to write `cube_1`. Every name goes through MJCF's own rules since section 4.4, which keep it as it
  is but for a body called `world`, and a run reads them back out of the sidecar.
- **Angles are degrees** (`<compiler angle="degree">`), MJCF's default and PartCAD's unit, so a hinge's `ref`, `range`
  and `springref` are written as declared. `polycoef` is not converted by the compiler, so a coupling is in radians and
  metres.
- **A bound on one side only** is written as a range whose open end is a million degrees, or a kilometre, away; MJCF
  ranges have two ends. An MJCF ball can bound only the whole angle it turns through, so a ball's three turns' limits
  are reported and not written.
- **Couplings are written the way MuJoCo holds them.** MuJoCo softens a joint equality by the two joints' inverse
  inertia, which it adds up without the polynomial's coefficient. A screw written as "the slide follows the hinge by
  1.6 mm a radian" therefore barely held at all -- a nut on a 10 mm thread fell 800 mm and turned a quarter turn --
  while "the hinge follows the slide by 628 radians a metre" holds to micrometres. So an equality is written with the
  coefficient of at least one; a linear relation inverts exactly.
- **The two bodies of a joint do not collide.** MuJoCo filters a child's contacts with its parent, except where the
  parent is welded to the world -- a pendulum's frame, a bolted robot -- and collides each body with the convex hull of
  the other's mesh, which fills a bore. Every joint gets a `<contact><exclude>`: without it a carriage sat on its rail.
- **Physics.** `damping`, `friction` (as `frictionloss`) and `springStiffness` are SI per unit of the joint's own motion,
  as MuJoCo takes them, and are written on every freedom of a joint but a coupled one (a screw's move is paid for by
  its turn). `springReference` is converted as `ref`. `maxEffort` is not written: `actuatorfrcrange` clamps what
  actuators apply, and there are none until step 14, which is also where `armature` (a motor's rotor inertia) comes
  from; `maxVelocity` has no MuJoCo counterpart. Both, `softLimits` and the ODE settings are reported as unsupported.
- **`static`** now means only "weld every body nothing holds to the world": true for a file somebody opens, false in
  the simulation's `formatOptions`. The joints inside an assembly are written either way, so a pendulum opened in
  MuJoCo's viewer swings. `flatten` is gone, and reported when passed.
- **What it changed for a scene of parts: nothing.** Every element is the free body it was, at the same pose; the
  stacks, the floats and the buoy validate as before.
- **The example** is `examples/feature_simulate_joints`: a 300 x 20 x 10 mm bar hung by its end on `motion: revolute`,
  in a scene that places it `fixed: true`. Released horizontal it passes the bottom at 567.410 deg/s against
  sqrt(2 g d / (I/m)) = 567.410, and reaches it in 0.2650 s against K(sin 45°) sqrt((I/m) / (g d)) = 0.26477 (the
  first reading past it, 1 ms apart); started 5° from the bottom its period is 0.8980 s against 2 pi sqrt((I/m) /
  (g d)) = 0.89726 -- 0.05 % of it the amplitude, the rest the sampling.

### 8.8c How the URDF export resolved the open details (built, step 11, #788)

Writing joints to URDF, reading them from one and converting between the two settled what 8.8 left open for URDF:

- **The exporter is `kinematics` and nothing else.** `export_urdf.py` calls `bodies()` and writes a link per body and a
  joint per body pair by `classify()`, through a plain-data `Planner` that the tests move through configurations and
  compare with the joint's own `location()`, row by row of the table in 8.8: `revolute`, `continuous`, `prismatic`,
  `planar` (its `<axis>` the third freedom's, the normal, at `classification.origin`) and `floating` are native; a
  cylindrical, universal, ball or screw joint and a chain are one single-axis joint per freedom at `joint.origins`
  through dummy links `<joint>_link1` ..., the child link at `inverse(joint.tail)`. A screw's follower is `<mimic>` of
  its turn by the lead (`ratio`, converted to metres a radian), and pays no `<dynamics>`. The first joint of a chain
  keeps the joint's name and each one after it the URDF joint its freedom was read from (a freedom's `source` says
  `joint`), so a chain read in comes back under its own names.
- **Links.** Each part welded into a body is a `<visual>` and a `<collision>` of its own, named after the part when the
  link has several (what reading it back names `<assembly>/<link>/<name>` by). An assembly's root body is named after
  the one direct child all its parts are in, when there is one (a robot's base link), and after the assembly
  otherwise. Its physics is `body.physics` re-expressed in the link frame; its `<gazebo>` block is the body node's
  settings, else what its parts agree on, a disagreement reported.
- **The root.** One free root is the URDF's root link, its frame the tree's origin (so the shapes are where the tree
  put them, and nothing welds it); a body fixed to the world hangs off a link `world` by a `fixed` joint; and with
  several roots - a scene - every free one hangs off `world` by a `floating` joint, reported, since a URDF has one root.
- **What URDF requires and PartCAD does not state** is a reported default and an export parameter: `effort` (1000 N·m
  or N) and `velocity` (100 rad/s or m/s) where a joint states no `maxEffort`/`maxVelocity`, a bound open on one side
  `OPEN_BOUND` (a million degrees or millimetres) away, a dummy link of `dummyMass` 0.001 kg and `dummyInertia` 1e-6
  kg·m². The starting value is lost and reported once, joint by joint. A `mimic` between joints is converted both
  ways in PartCAD's units on both sides (degrees or millimetres per degree or millimetre, which the reader now states
  too, and which the MJCF exporter reads the same way); a joint's `<gazebo>` settings are written back as the reader
  reads them.
- **A rigid connection says what it is attached to.** The body rule welded a child that a `connect:` holds rigidly to
  its *container's* body, which is wrong as soon as its target moves - a gripper bolted to a turning wrist, a URDF
  link on a fixed joint under a moving one. A node placed by a rigid connection now carries the target's label
  (`shape_envelope.KEY_ATTACHED`, stamped by `Assembly._place`, assemblies only), and `bodies()` welds it into the
  target's body at the target's frame there times the two nodes' relative placement. A joint that names no sibling
  (`parent: None`) is to the container, without a problem: what a URDF link hanging off a root link with no geometry
  is. Those are the two additions to the helper; the payload changed, so the cache format is 11.
- **The URDF factory fills `AssemblyChild.joint`.** The reader states each link node's joint in the envelope form
  (`Joint.to_envelope`): the parent's shape offset undone, each URDF joint origin on the way and the freedoms it keeps
  (`freedoms`, one list read by the factory and the converter alike), this link's shape offset - every freedom at zero;
  and a link on a fixed joint names its parent under `attached`. `AssemblyFactoryImported` builds a
  `partcad.joint.Joint` from it (`Joint.from_envelope`), knowing no format, so a plugin's reader can state joints the
  same way. Links with no geometry are no nodes, so the joints through one compose into one joint of their freedoms,
  named after the first, and a `mimic` between two of them is a coupling. `pc info -a` lists a URDF assembly's joints.
  Movable joints are no longer counted as dropped.
- **The converter writes the explicit form**, and the contact frame is the URDF joint frame. The half turn is on the
  socket's port, not the plug's: the parent still implements the socket at the joint origin, the plug sits at the
  child link's own origin, and a half turn twice is none - so every parameter's `dir` is the URDF axis verbatim
  (`joint_axis_in_port_frame` and its `(y, x, -z)` are gone), `motion: {dof: [...]}` names the parameters, a
  continuous joint's parameter states no range, a planar joint's are `moveX`/`moveY`/`turnZ` (or `offset`, `offset-2`,
  `angle` off the principal axes) and a floating one's all six, and `connect: {joint:}` keeps the URDF's name. The
  export of a converted URDF is therefore the URDF's own frames and axes back, which 8.8's "the remapped-axis wrinkle
  disappears" needed. Interfaces are deduplicated as before, on the reader's record.
- **What a round trip keeps**, as tests (`test_urdf_round_trip.py`): URDF -> read -> export -> read keeps every
  movable joint's name, type, frame, axis, limits, effort, velocity, dynamics, soft limits and mimic, and every shape to
  a micrometre; URDF -> ASSY -> export keeps the same for every joint except one in a chain of movable joints through a
  link with no geometry, which the converter folds into its last joint (below); an ASSY's hand-written revolute, ball and screw read back as themselves. Lost:
  the starting value; a link on a fixed joint, which is a shape of its parent's link; the name of a link with no
  geometry, replaced by a dummy link; and, in the converter only, the kinematics of a chain through such a link, folded
  into its last joint and reported, since one connection cannot hold freedoms about two points.

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

```yaml
parts:
  gripper:
    type: step
    ports:
      tcp: [[0, 0, 180], [0, 0, 1], 0]      # a tool centre point is a port like any other
```

### 8.11 Named configurations (planned)

With degrees of freedom in place, a connection's `toParams` is the value of one joint. What is missing one level up is
a name for a value of *all* of them:

```yaml
assemblies:
  robot:
    type: assy
    configurations:
      home:   { shoulder_pan: 0, elbow: 0 }
      stowed: { shoulder_pan: -90, elbow: 135 }
    configuration: home        # the one the assembly shows
```

The keys are joint names (section 8.4) and the values are in the joints' units. A configuration overrides the
`toParams` of the joints it names; it is a parameter of the assembly, hashed into its cache key like any other, so
`pc ide view 'robot;configuration=stowed'` works through the parameter machinery an ASSY file already has. A
`simulate:` names the configuration it starts from (`initial:`, section 13), and the URDF exporter has somewhere to
write a starting pose at last -- an SRDF `group_state`. Everything that exists today, a tree of rigid placements, is
what evaluating a configuration produces, so no consumer of the representation has to change.

### 8.12 Devices, actuation and control (planned)

Which joints are driven, by what, through which reduction, and what a controller sees: ROS 1 spelled it
`<transmission>`, ROS 2 spells it `<ros2_control>` with hardware components and command and state interfaces, and
simulators additionally want actuator limits and often a motor model. These are robot-level, not link-level, so they
attach to the assembly; an assembly takes the same `properties:` section a part does, and nothing reads one there yet.

Sensors -- cameras with intrinsics, resolution, clipping and distortion; depth cameras; lidars with ray patterns and
ranges; IMUs; contact and force-torque sensors -- are each attached to a frame, with an update rate and a noise model.
URDF has no sensor element at all; they arrive through `<gazebo>` extension blocks, which is the clearest evidence that
URDF is a kinematics format with a simulation format bolted on.

```yaml
assemblies:
  robot:
    devices:
      front_camera:
        type: camera
        frame: head/camera_mount     # a port (section 8.10)
        rate: 30                     # Hz
        image: { width: 1280, height: 720, format: R8G8B8 }
        fov: 60                      # deg
        noise: { type: gaussian, stddev: 0.007 }
      shoulder_motor:
        type: actuator
        joint: shoulder_pan
        gearRatio: 100
        torqueConstant: 0.05         # N·m/A
        rotorInertia: 1.2e-5         # kg·m², written as MJCF 'armature' through the reduction
```

PartCAD models the handful of device types every simulator agrees on -- camera, depth, lidar, IMU, contact,
force-torque, and an actuator on a joint -- and, following section 2, reports any other device it is handed rather than
carrying it as passthrough. The URDF reader counts sensors, transmissions and `ros2_control` blocks as dropped today.

### 8.13 Native joint types, reconsidered (decided, being built)

**Decided, not built yet.** The decisions are in 8.13.9; where one differs from what the text first proposed, the
text says so in place. It revisits section 8.2's kinds, 7a's classification and 8.8's table,
for two reasons. The vocabulary has pairs that name one thing, and a catch-all (`chain`) that is not a type. And two
of the three exporters write what their format has no type for through links of 1 g that nobody built (`DUMMY_MASS`
in `export_urdf.py` on #788 and in `export_world.py` on sim-gazebo #11), and write every joint at zero because their
format has no starting value. This section proposes:

- one native type per physical joint;
- each type's translation into every engine, with no invented mass;
- a starting value in every engine;
- limits in each engine's own terms;
- an example per type;
- and what changes for what exists.

Section 8.6 does not change: the representation still has no type in it, and what follows is about what `classify()`
derives from it and what each exporter writes. The section is appended rather than inserted as 8.9 because code cites
8.9 and 8.12 by number.

Every claim about an engine below was checked in the engine's own documentation or source, at the version the
plugins run:

| Engine | Version | Where it was checked |
|---|---|---|
| MuJoCo | `mujoco>=3.2,<4,!=3.15.0` (sim-mujoco `partcad.yaml`); read at 3.16.0, the latest | `doc/XMLreference.rst` (<https://mujoco.readthedocs.io/en/stable/XMLreference.html>), `src/xml/xml_util.cc`, `src/engine/engine_core_constraint.c` |
| Gazebo | `osrf/ros:jazzy-simulation` (sim-gazebo `container/Dockerfile`), which is Harmonic: gz-sim 8; gz-physics 7, whose default engine is DART and whose other engine is bullet-featherstone; libsdformat 14, which reads SDFormat up to 1.11 | `sdf/<version>/joint.sdf` (<http://sdformat.org/spec?ver=1.11&elem=joint>); gz-physics `dartsim/src/SDFFeatures.cc` and `bullet-featherstone/src/SDFFeatures.cc` on `gz-physics7`; gz-sim `src/SdfEntityCreator.cc` on `gz-sim8`; libsdformat's URDF reader, `src/parser_urdf.cc` on `sdf14` |
| URDF | the ROS specification | <https://wiki.ros.org/urdf/XML/joint> |

#### 8.13.1 What a mechanism needs

The **lower pairs** are the six joints two bodies make by touching over a surface. They are the complete set of such
joints, and each one is a native type:

| Physical joint | Freedoms | Native type |
|---|---|---|
| revolute (pin) | one turn | `revolute` |
| prismatic (slider) | one move | `prismatic` |
| cylindrical | a turn and a move, on one line | `cylindrical` |
| helical (screw) | the same two, coupled by a lead | `screw` |
| spherical | three turns through one point | `ball` |
| planar | two moves in a plane, and the turn normal to it | `planar` |

Two more are not joints but the two ends of the range. **Fixed** has no freedom: its bodies merge (section 7).
**Free** has no constraint: the child is a body of its own. One compound joint earns native status too: the
**universal** (Hooke) joint, two turns whose lines cross. It is everywhere (drive shafts, gimbals, every two-axis
wrist), and SDFormat and DART both have it natively.

Considered and left out:

- **`revolute2`**, two turns whose lines do not cross. SDFormat has it, Harmonic's DART builds it as a weld (8.13.4),
  and MJCF writes it as two hinges anyway, so it is a composite.
- **Gear, rack, belt and constant-velocity joints.** These are couplings *between* joints (8.9), not joints.
- **Cam, pin-in-slot, point-on-plane, ball-in-cylinder.** These are higher pairs or composites. A higher pair is
  contact, and contact belongs to the geometry (5.4).
- **Closed loops.** A loop is a constraint, not a type (8.9).

Everything else is a **composite**: a set of freedoms that no lower pair has. Physically, a composite is a chain of
bodies that the declaration leaves out: the carriage of an XY stage, the cross of a two-axis joint, the ring of a
gimbal. This is why a 1 g link is wrong and not just inelegant. It stands in for a body the mechanism really has, with
a mass nobody measured.

#### 8.13.2 Pairs that name one thing

| Pair | One physical joint? | Proposal |
|---|---|---|
| `continuous` and `revolute` with no bound | yes: a hinge, and its bounds are a property of it | `revolute`, with each bound optional. `continuous` stays as a spelling of `revolute` with both bounds open, and `pc lint` says so |
| `floating`, a free root, a scene element | yes: a body nothing holds | `floating` makes the child a body of its own (section 7's table gains a row). Each engine writes it as its own free body, never as six freedoms under the parent. URDF is the exception: a URDF is one tree with one root and has no free body, so there it is URDF's `floating` joint, all six freedoms relative to the parent, which keeps the declared relative motion |
| `planar` and `dof: [moveX, moveY, turnZ]` | yes, by construction | `type` is the short form of the list (below). The other order, the turn first and then the moves, is the same pair in other coordinates, so it classifies as `planar` too |
| `ball` and three turns | yes, for any three independent turns through one point | the three turns are only the coordinates its readings are reported in |
| `motion.type` and `dof:` | yes | `dof` is the declaration and `type` is its short form: it expands to 8.2's list, and stated beside a `dof` it is an assertion. A disagreement is an error (today it is reported, and `dof` wins) |
| `limits:` and a parameter's range | yes: both are a freedom's travel | the parameter's range is the travel. `limits` is how the short form states the range of the parameter it implies. If both are stated and differ, that is an error |
| `chain` | no: it is not a type | renamed **`composite`**, and not a value of `motion.type`. It is what a `dof` list classifies as when no native type fits it |
| `fixed` and no `motion` | no | not a duplicate. `fixed` is the override that locks a joint (`connect: {motion: fixed}`), and its result is no joint |
| `screw` and a coupled `cylindrical` | yes | there is only one way to declare it (`screw`, from `threadStep`), so it is kept |

**A defect found on the way.** `universal` implies "two turns, about `axis` and about the port's X axis". So
`axis: [1, 0, 0]` implies two turns about the same line, and 8.3 merges those into one. The second axis should be the
port's X, or the port's Y when `axis` is parallel to X.

**An open bound is stated by not stating it.** Sometimes a parameter's range would bound a freedom that is meant to be
open. For that case, `limits: {lower: -.inf, upper: .inf}` says so. YAML's own infinity is a number, so the schema
needs nothing new, and `kinematics` carries it the way it carries `None` today. This is what `continuous` becomes.

#### 8.13.3 The canonical set

`classify()` returns exactly one of these for every set of free steps:

| Type | Free steps | Coordinates (what a reading is) | Bounds |
|---|---|---|---|
| (none) | none | -- | -- |
| `revolute` | one turn | the turn, in degrees | on either side, or neither |
| `prismatic` | one move | the move, in mm | on either side, or neither |
| `cylindrical` | a turn and a move on one line, uncoupled, in either order | both | on each, as above |
| `screw` | the same, the move following the turn | the turn; the move follows it | the turn's |
| `universal` | two turns whose lines cross | both, in order; the first is fixed in the parent | on each |
| `ball` | three independent turns through one point, in any order | the rotation, and the three turns where they decompose it | one angle: how far it turns from its zero (`limits: {upper: 30}`) |
| `planar` | two moves and the turn normal to their plane, moves first or turn first | all three | on each |
| `floating` | three independent moves, and three independent turns through one point | all six, read from the child's pose in the parent | none |
| `composite` | anything else | each freedom | on each |

This changes `_kind()` in three ways: one turn is `revolute` whatever its bounds; `planar` is accepted in both
orders; and `chain` is renamed `composite`.

A ball's limit is one angle, because one angle is all a ball can be bounded by without a gimbal in it, and it is how
MuJoCo bounds a ball. To bound each turn separately, declare the turns as a composite. Per-turn ranges on a ball then
become an error, instead of being reported and dropped.

#### 8.13.4 Translation, without links nobody built

This is what each engine is told, and what it builds internally (MuJoCo's `mjModel` joint type, or the DART joint
class gz-physics constructs):

| Type | MJCF (MuJoCo) | SDFormat 1.11 (Gazebo Harmonic, DART) | URDF |
|---|---|---|---|
| (none) | one body, with a geom per part | one link | one link |
| `revolute` | `hinge` (`mjJNT_HINGE`) | `revolute` (`RevoluteJoint`) | `revolute`; `continuous` when both bounds are open |
| `prismatic` | `slide` (`mjJNT_SLIDE`) | `prismatic` (`PrismaticJoint`) | `prismatic` |
| `cylindrical` | a `hinge` and a `slide` in one body | **refused** | **refused** |
| `screw` | a `hinge` and a `slide`, with an `<equality><joint polycoef>` between them | `screw` (`ScrewJoint`) | **refused** |
| `universal` | two `hinge`s in one body | `universal` (`UniversalJoint`) | **refused** |
| `ball` | `ball` (`mjJNT_BALL`) | `ball` (`BallJoint`) | **refused** |
| `planar` | two `slide`s and a `hinge` in one body, in the declared order | **refused** | `planar` |
| `floating` | a body directly in `<worldbody>`, with a `<freejoint>` (`mjJNT_FREE`) | a link with no joint, in a model of its own; DART gives it a `FreeJoint` | `floating` |
| `composite` | its hinges and slides, in order, in one body | **refused** | **refused** |

**MuJoCo can state all of it.** A body may hold several joints, applied in order. A ball may share a body with slides,
but not with hinges or another ball. A free joint "is only allowed in bodies that are children of the world body", and
an equality takes only scalar joints (XMLreference, `body/joint/type` and `equality/joint`).

So `floating` moves from "three slides and a ball under the parent" to a top-level free body. That is MuJoCo's own
construct, and it also fixes the physics. MuJoCo filters a child's contacts with its parent, and the exporter excludes
the pair of every joint (8.8b), so a loose part nested under whatever holds it would pass straight through it.

**SDFormat has a joint for five of the eight types and a free body for a sixth, and Harmonic builds all six.**

- SDFormat 1.11's types are `continuous`, `revolute`, `gearbox`, `revolute2`, `prismatic`, `ball`, `screw`,
  `universal` and `fixed`. There is no cylindrical or planar type, and a joint joins exactly two links.
- gz-physics 7's DART builds `ball`, `prismatic`, `revolute`, `screw` and `universal`. Anything else (`continuous`,
  `revolute2`, `gearbox`) is built as a weld: it logs a `gzerr` line and the run goes on (`ConstructSdfJoint`).
  So `continuous` and `revolute2` are never written. Section 8.8 called this weld silent; it does log, but nothing
  fails.
- bullet-featherstone builds only `fixed`, `revolute`, `prismatic` and `ball`.
- A second joint whose child already has a parent joint is refused by DART, and so is a joint that closes a loop.
  So two single-freedom joints between the same two links are not a way round the gaps.
- A link with no joint is SDFormat's free body.

**URDF has six types:** `revolute`, `continuous`, `prismatic`, `fixed`, `floating` and `planar`.

**Where an engine has no native construct, the export refuses.** The refusal names the joint, its type and the
engine, and gives two ways on: simulate the mechanism in MuJoCo, or model the body the joint abstracts and join it by
native joints. For a cylindrical pair that body is a sleeve and its carriage; for a universal joint in URDF it is the
cross. Nothing is ever written with a mass PartCAD did not derive.

Considered and not proposed:

- **Massless links**, meaning a URDF `<link>` with no `<inertial>`.
  - This is URDF's own idiom for a frame, it is what ROS kinematics tools read, and it invents no mass.
  - But every consumer that simulates refuses it. libsdformat's URDF reader reports a link with no `<inertial>` as
    `LINK_INERTIA_INVALID` and leaves out the link and its joints, unless a fixed joint lumps it into another. It also
    writes no joint at all for `planar` or `floating`.
  - MuJoCo's compiler offers `boundmass` only as "a quick fix for poorly designed models that contain massless moving
    bodies, such as the dummy bodies often used in URDF models", and adds that "in MuJoCo there is no need to create
    dummy bodies" (XMLreference, `compiler/boundmass`).
  - For a URDF that is read only for its kinematics, massless links would be right; see decision 1 in 8.13.9.
- **A ball's `<axis>` in Gazebo.**
  - Harmonic's DART applies a ball's `<axis>` (its damping, friction, spring and limits) to each of the three
    coordinates of its `BallJoint` (`ConstructBallJoint`). SDFormat's specification does not say this.
  - That limit bounds each component of the rotation vector. The result is a box, which matches a cone only within a
    principal plane.
  - The damping is worth writing; the limit is reported (8.13.6).

#### 8.13.5 Starting values

| Engine | Native starting value | Proposal |
|---|---|---|
| MuJoCo hinge and slide | `ref`, "the joint value corresponding to the initial model configuration"; the transform at runtime is `qpos - qpos0` | `ref` is the starting value, and the body is written at the start, as built (8.8b) |
| MuJoCo ball | none: "the quaternion (1,0,0,0) corresponds to the initial configuration in which the model is defined" | re-zeroed |
| MuJoCo free | the body's pose is `qpos0` | the body is written at its start |
| MuJoCo, any joint | `<key qpos>`, which is copied into `mjData.qpos` only "when the simulation state is set to this keyframe": by a program, not at load | used only for a bounded ball that starts away from its zero (below) |
| SDFormat | `<axis><initial_position>` is in 1.6 and 1.7, deprecated in 1.8 (`required="-1"`), and gone from 1.9 on. gz-sim 8 reads no starting value from a world (`SdfEntityCreator.cc`), and the system that would set one from `<model_state>` (gz-sim #2359) is an unmerged draft | re-zeroed |
| URDF | none | kept at PartCAD's zero, and the start reported (decision 2) |

**Re-zeroing.** Where an engine has no starting value, the joint is re-expressed so that the engine's zero *is*
PartCAD's start. The child is written where the assembly shows it, and every axis is written where that configuration
puts it. Precisely, take the decomposition `kinematics` gives every joint (7a),

```text
location(v) = origin . M_1(v_1) . T_1 . M_2(v_2) ... T_{n-1} . M_n(v_n) . tail
```

where each `T_i` is the fixed frame between two freedoms. A freedom's motion about or along its own line adds up and
commutes with itself, `M_i(s + e) = M_i(s) . M_i(e) = M_i(e) . M_i(s)`, and it leaves that line where it is. Let the
starting values be `s_i`, and let the engine's values be `e_i = v_i - s_i`. Then:

- **Joints in series** (MJCF's joints in one body, URDF's and SDFormat's single-axis joints): each joint's frame
  absorbs its own start, `origin' = origin . M_1(s_1)` and `T_i' = T_i . M_{i+1}(s_{i+1})`. Every axis keeps its
  components in its own frame.
- **One native joint with several freedoms** (SDFormat `universal`, URDF `planar`, either format's `screw`): the start
  of each freedom that commutes with all the freedoms after it goes into the joint frame `J`, and the last freedom's
  start goes into the child's frame.
  - `universal`: `J' = origin . R_1(s_1)` and `tail' = R_2(s_2) . tail`.
  - `planar` with the moves first: `J' = origin . T_x(s_x) . T_y(s_y)` and `tail' = R(s_θ) . tail`. Putting the
    planar turn's start into `J'` instead would rotate the engine's moves against PartCAD's, and that is the one way to
    get this wrong.
  - A screw's or a cylindrical's two freedoms commute, so both starts go into `J'`.
- **A ball**: `J' = J . R_s`, where `R_s` is the starting rotation. The engine's rotation `R_e` is then the turn away
  from the start, and PartCAD's rotation is `R_s . R_e`.
- **A free body** is written at its start, and its pose is the engine's coordinates.

This is what shifts with it, for a scalar freedom with start `s`:

| | PartCAD | Engine, re-zeroed |
|---|---|---|
| reading | `v` | `e = v - s` |
| velocity | `v'` | the same |
| bounds | `[l, u]` | `[l - s, u - s]`; an open side stays open |
| spring reference | `r` | `r - s` |
| soft limits (URDF only) | `[l, u]` | `[l - s, u - s]` |
| mimic, `v_f = m v_l + c` | `c` | `c + m s_l - s_f` |
| screw | the move follows the turn by the lead | the same lead, with `J'` at both starts |

MJCF's `ref` needs none of this for a hinge or a slide. Its `range`, `springref` and `polycoef` are already stated
about `qpos`, which there is PartCAD's value.

**A bounded ball under MJCF.** Its cone is about the ball's zero (8.13.3). MuJoCo bounds a ball "relative to the
reference configuration", and re-zeroing makes that reference the start.

- A bounded ball that starts at its zero is written as above, and re-zeroing changes nothing (`R_s` is the identity).
- One that starts anywhere else is **not** re-zeroed: re-zeroing would move the cone's centre to the start, and the
  cone is about PartCAD's zero. The ball's frame stays `J`, and the body is written at the ball's zero orientation, so
  MuJoCo's reference configuration is PartCAD's zero. The start goes into a `<key>`, whose `qpos` for the ball is
  `R_s` as a quaternion in `J`, and the plugin resets to it (`mj_resetDataKeyframe`). The joint map's start for that
  ball is the identity, because the engine's quaternion is then PartCAD's rotation itself. This is reported, because
  a file opened by hand then shows the ball at its zero.

**Readings back.** Each plugin reports a joint under PartCAD's name and in PartCAD's units, whatever it was written as.

- `joints[name]` has `pos` and `vel`. Each is a number for a joint with one freedom, and an object keyed by parameter
  for a joint with several (`{"turnZ": 30.0, "moveZ": 0.83}`).
- A ball and a free body also have `quat`.
- A ball's three turns are reported when its axes can decompose a rotation, which needs each next pair of axes to be
  perpendicular (Davenport's condition). The turnX, turnY, turnZ that `motion: ball` implies meet it. Otherwise only
  `quat` is reported.
- This replaces today's `<name>.<parameter>` keys, so one validation reads MuJoCo and Gazebo alike.

**The joint map.** For each engine joint, the plugin needs:

- which PartCAD joint and parameter it is, and its kind;
- the unit factor (degrees per radian, millimetres per metre);
- the start, `s` or `R_s`;
- for a free body, its parent body.

The exporter writes this map and the simulator reads it. It is computed once, in `kinematics` (by `rezeroed()` and
`reading()`), and no plugin carries a copy.

**Decided (6): it travels in the names sidecar** (`<file>.names.json`, `naming.write_sidecar`, #799), as each joint
entry's `map`, beside the names it already carries -- one file from the exporter to the simulator, not two. The
sidecar is what a simulation's `formatOptions: {names_file: true}` asks for; a file exported for somebody to open has
none, and needs none, since nothing reads its joints back. Carrying the map inside each format instead was considered
(MJCF `<custom><text>`, which `mjModel` keeps; an SDFormat element in a declared namespace, which libsdformat has
preserved since 1.7; an unknown URDF element, which urdfdom ignores) and is not done: it would be three spellings of
one map, each with its own reader.

#### 8.13.6 Limits

Units convert at the boundary, as they do now. MJCF is in degrees and metres: `<compiler angle="degree">` converts
`range`, `ref`, `springref` and a ball's range, but not `polycoef`. SDFormat and URDF are in radians and metres.

| | MJCF | SDFormat 1.11 (DART) | URDF |
|---|---|---|---|
| both bounds | `range`, with `limited="true"` | `<limit><lower><upper>` | `<limit lower upper>` |
| one side open | the open side is `inf` or `-inf` (see below), replacing the `1e6` sentinel | the open side is omitted (see below), replacing `1e16` | no open bound exists, so the `OPEN_BOUND` sentinel stays, reported (see below) |
| neither | `limited="false"` | no `<lower>` or `<upper>` | `continuous`; a prismatic with both sides open uses the sentinel, reported |
| ball | `range="0 a"`: the angle it turns through | none in the specification, so reported; DART's per-coordinate box (8.13.4) is not the same limit | refused anyway |
| universal, planar, composite | each hinge's and slide's `range` | the limits on `<axis>` and `<axis2>` (universal) | URDF's `planar` takes none: reported |
| screw | the hinge's; a bound on the move is written as the turn's, through the lead | the turn's, in radians | refused |
| `softLimits` | none, since they are a controller's: reported | none: reported | `<safety_controller>`, shifted with the start |
| `maxEffort`, `maxVelocity` | none until actuators arrive (step 14): reported | `<limit><effort><velocity>`, which become DART's force and velocity limits | `<limit effort velocity>`, which URDF requires |

Why each engine's open bound is spelled the way it is:

- **MJCF:** MuJoCo's XML reader parses `inf` and `-inf` (`ParseInfOrNan` in `xml_util.cc`, already there in 3.2.0).
  The compiler asks only that `range[0] < range[1]`. And the limit constraint on the open side measures an infinite
  distance, so it never activates (`engine_core_constraint.c`).
- **SDFormat:** an omitted bound defaults to `-inf` or `inf` from 1.10 on (it was `1e16` before), and DART takes both
  as its position limits (`CopyStandardJointAxisProperties`). Using this moves the export from SDFormat 1.9 to 1.11,
  which Harmonic reads.
- **URDF:** `lower` and `upper` default to 0, and both are required on a `revolute` and a `prismatic`. This is the only
  place a sentinel stays.

The stiffness of a stop (MJCF `solreflimit` and `solimplimit`, SDFormat `<limit><stiffness><dissipation>`) is not in
PartCAD's model, and is not proposed here.

#### 8.13.7 Examples

There is one example per type, in `examples/feature_simulate_joints` beside the pendulum. Each one starts away from
its zero, so every run checks the starting value and its mapping back, in every engine. Each is held either to a
closed form or to a bound it cannot pass without the joint being wrong. The run lengths and sampling follow the
pendulum's: a reading every millisecond, and a step of half a millisecond.

A stop's own give (a few degrees at speed, under MuJoCo's default softness) is not what these test. So a bound is
checked against where the body would be without it, not to a fraction of a degree.

| Assembly | Type | It checks | MuJoCo | Gazebo |
|---|---|---|---|---|
| `pendulum`, `nudged` (built) | `revolute`, bounded on both sides | passes the bottom at sqrt(2 g d / (I/m)), gets there in K(sin 45°) sqrt((I/m) / (g d)), and keeps the small-angle period 2 pi sqrt((I/m) / (g d)) | yes | yes, once SDFormat joints land |
| `wound` | `revolute`, unbounded | the same bar, started at 270°: reads 270 at the start, and 360 at the bottom at the same 567.41 deg/s. A reading wrapped into ±180, or a lost start, would read −90 or 0 | yes | yes |
| `door` | `revolute`, bounded on one side | released at −90° with only `upper: 30`: passes the bottom at the closed-form speed (so nothing on the open side stopped it), and is turned back before 45° where it would otherwise reach 90° | yes | yes |
| `incline` | `prismatic`, bounded on one side | a carriage on a frictionless rail at 30°, started 200 mm up, with `lower: 0`: follows 200 − ½ g sin 30° t², which is 101.9 mm at 0.2 s, and stops at the stop | yes | yes |
| `collar` | `cylindrical` | a collar with an arm, on a shaft at 30° to the horizontal, its turn started at 5°: in one run, slides as ½ g sin 30° t² and swings with period 2 pi sqrt((I/m) / (g cos 30° d)). The two motions are exactly uncoupled | yes | refused |
| `nut` | `screw` | a ring with a 10 mm bore and 30 mm outside, on a 10 mm lead, started 100 mm up: falls at g / (1 + (I/m)(2 pi / p)²) = 0.1948 m/s², turning 36° per millimetre | yes | yes |
| `hooke`, `hooke_across` | `universal` | a 200 x 200 x 10 mm plate hung by the middle of an edge, started 5° on one axis or the other: period 2 pi sqrt((I/m) / (g d)), with I/m = L²/3 + w²/12 (0.8190 s) about one axis and L²/3 + t²/12 (0.7327 s) about the other. The other turn stays at 0 | yes | yes |
| `spherical` | `ball` | the same plate on a ball, started tilted 5° as in `hooke_across` but twisted 90°: it swings in its own plane, at 0.8190 s. That checks that both turns of the start were kept. The twist stays at 90 | yes | yes |
| `cone` | `ball`, bounded | an inverted bar on a ball bounded at 20°, started 5° from upright: it falls against the cone and stays inside 30°, where without the cone it would fall to 180° | yes | not declared: SDFormat cannot state the bound |
| `wall` | `planar` | a plate on a planar joint in a vertical plane, started at (50 mm, 100 mm, 30°): falls ½ g t², which is 49.05 mm in 0.1 s, and its other two readings do not move | yes | refused |
| `loose` | `floating` | a block placed 100 mm above its base with `motion: floating`: falls 49.05 mm in 0.1 s, and comes to rest *on* the base. That is the contact the old three slides and a ball excluded | yes | yes |
| `locked` | (none) | the pendulum with `connect: {motion: fixed}`: one body, `joints: {}`, and the bar stays where it started | yes | yes |
| `stage` | `composite` | two moves in a vertical plane: falls ½ g t² and does not move sideways | yes | refused |

URDF has no simulator here. Instead, `test_export_urdf_joints.py` exports each of these assemblies and checks that the
native type is written or that the export refuses, and it checks the round trip of the native ones. Gazebo's refusals
are checked by unit tests too, rather than by examples that fail.

#### 8.13.8 Migration

- **`motion.type`:**
  - `continuous` still reads, as `revolute` with `limits: {lower: -.inf, upper: .inf}`, and `pc lint` says so. The
    schema marks it deprecated. Every `motion:` the URDF converter has written keeps the meaning it had.
  - A `type` that disagrees with the `dof` beside it fails the `connect` check, instead of being reported.
  - `universal`'s second axis changes only where `axis` is the port's X, which was degenerate before.
- **`kinematics`:**
  - `CONTINUOUS` goes, and `CHAIN` becomes `COMPOSITE`.
  - `classify()` gains planar's other order and the ball's single bound.
  - `rezeroed()` and `reading()` are new.
  - The plugins move with it, and require that release; section 2 rules out a compatibility fallback.
- **MJCF (sim-mujoco):**
  - `OPEN_BOUND` becomes infinity.
  - `floating` becomes a top-level body with a `<freejoint>`.
  - A bounded ball writes `range="0 a"`, instead of reporting its three turns' bounds as dropped.
  - Readings are keyed by PartCAD joint name, with per-parameter objects, instead of `<name>.<parameter>` keys.
  - Nothing changes for the pendulum: `swing` has one freedom and reads as it did.
- **URDF (#788):**
  - The dummy links go, and so do the `dummyMass` and `dummyInertia` options (passing one is reported).
  - Cylindrical, screw, universal, ball and composite joints are refused, unless `formatOptions: {composites:
    massless}` asks for them as chains through links with no `<inertial>` (decision 1).
  - Starting values stay at PartCAD's zero and are reported, as now (decision 2).
  - The URDF reader is unchanged: a URDF that already uses the dummy-link idiom imports as the chain it states.
- **SDFormat (sim-gazebo #11):**
  - The dummy links go.
  - Cylindrical, planar and composite joints are refused.
  - `floating` becomes a link with no joint, in a model of its own.
  - The export writes SDFormat 1.11 instead of 1.9, and omits open bounds instead of writing `1e16`.
  - Starting values are re-zeroed, instead of being reported.
  - Its comment that the `SetModelState` system "is Ionic's" is corrected: it is gz-sim #2359, an unmerged draft.
- **This record:** once this is agreed, these are rewritten to match it:
  - 8.2's table;
  - 7a's "Classification details";
  - 8.8's table, and its "Rules the table does not show" on dummy links and starting positions;
  - steps 11 and 12 of the roadmap.
- **What is reported:**
  - An engine's refusal is an error, naming the joint, its type, the engine, and the ways on.
  - A ball's bound in SDFormat, a planar joint's bounds in URDF, and any bound on a free body are warnings, as now.
  - A bounded ball that starts away from its zero in MJCF is reported, because of the keyframe.
  - `continuous` gets a lint notice.
  - A starting value is reported lost only by the URDF exporter, which keeps PartCAD's zero (decision 2).

#### 8.13.9 What was decided

Decided on 2026-10-17. Each item says what was decided first, then what was weighed.

1. **Refusal, or massless links for URDF.** *Decided: refuse by default, and offer the opt-in.* The proposal was to
   refuse. The alternative was an opt-in (`formatOptions: {composites: massless}`) for a URDF that is read only for
   its kinematics, by ROS's `robot_state_publisher` or MoveIt, where links without `<inertial>` are the idiom. Every
   simulator that reads such a URDF then drops or refuses those links. SDFormat does not get them either way. Both:
   a refusal is the default, because a URDF is most often loaded by something that simulates it, and the opt-in
   serves the readers that do not; the refusal names the option.
2. **URDF's zero.** *Decided: keep PartCAD's zero, and report the start.* The proposal was to re-zero, so that any
   program loading the URDF starts the mechanism as the assembly shows it. The cost is that a URDF of real hardware
   then has its joint zeros at the assembly's start, not where its encoders read zero. The alternative is an option
   that keeps PartCAD's zero and reports the start lost, until named configurations (8.11) give the start an SRDF
   `group_state`. A URDF describes the robot, and what reads it (ROS's tools, a robot's drivers) takes joint zero to
   be the hardware's; re-zeroing stays for the engines, where the file is PartCAD's own and the plugin maps every
   reading back.
3. **`continuous`:** *decided: a deprecated spelling* of an unbounded `revolute`, with a `pc lint` notice, rather
   than an error. The URDF converter stops writing it.
4. **A `type` that disagrees with its `dof`:** *decided: an error*, from the `connect` check, rather than a report as
   now.
5. **A ball's bound:** *decided: one angle*, as MuJoCo bounds a ball, with per-turn ranges on a ball an error. The
   alternative is to keep per-turn ranges, which no engine can write natively.
6. **Where the joint map travels:** *decided: as a section of the names sidecar* (8.13.5), not inside the file as
   first proposed.
7. **Readings:** *decided: one entry per PartCAD joint*, as a number or a per-parameter object, in PartCAD's units,
   replacing `<name>.<parameter>`.
8. **`planar` in either order:** *decided: either order*, rather than only moves-then-turn with the other order a
   composite.
9. **Gazebo's gaps.** *Decided: accepted.* Cylindrical and planar pairs are common enough that refusing them in
   Gazebo will be felt. The proposal accepts that, because the alternative is a body nobody built. Whether DART
   would run massless intermediate links is untested, and nothing here depends on the answer.

## 9. Simulations as tests

`pc test` runs every `simulate:` declaration of every part, assembly and scene as its `sim` check (`pc test -f sim`), so the
TDD loop is `pc test` -- red until the design does what it claims (built, #756). `pc sim` remains the command
that runs and reports simulations; both go through one implementation.

**Verdicts.**

| Outcome | Verdict |
|---|---|
| the run happened and the validation holds | pass |
| the run happened and the validation does not hold, or raises | fail |
| the run could not be made: plugin or scene not found, a sandbox that will not build, a crash | fail |
| the run did not finish within its budget, or the plugin crashed or answered with something that is not an answer | fail |
| the plugin names a `container:` or `dockerImage`, and this machine has no container runtime | skip, with a warning carrying the report |
| the declaration states no `validation:` | skip in a run over a package or a tree; fail when the object is named |

Not running is a failure, not a skip: a declaration is a question, and a plugin that was asked and delivered nothing
has failed. The one excuse is the case where the implementation was never given the environment it said it needs --
it named an image, and there is nowhere for an image to run. An implementation that names no image gets no excuse:
it said it runs in an ordinary sandbox. The same rule governs the `fea` and `cfd` checks, from one shared base class.

**Claims must be true.** An example's simulation is a test in CI; a claim that passes for the wrong reason, or does
not pass, is a defect. Examples carry closed-form answers where one exists -- a pendulum's period
(`examples/feature_simulate_joints`, built), energy conservation,
a free fall, a body that floats because it is less dense than the fluid -- the way `examples/feature_cae` compares a
cantilever with beam theory. The `slippery` example was a counter-example: on a level floor nothing pushed its top
block sideways, so the claim that friction made it slide was false. It now stands in a `tilted` scene whose gravity
leans 15° off the vertical -- no ramp part, no edge, every stack placed as drawn -- where a block slides when μ < 0.268:
the aluminium stack holds to 0.46 mm against a 5 mm bound, and the PTFE one loses its top block, which slides 69 mm
(built, #761). The friction table in the user documentation is measured in the same scene (#762).

**A timeout is a failure.** A run that hangs is a defect -- of the plugin, of the model it was handed, or of how long
the package says the run takes -- and a check that skipped it would pass a claim nobody can ever check. It takes the
same one excuse as every other run that did not deliver, through the same `ImplementationTest._verdict()`, and is
reported the same way: the object, the simulation, the plugin, the budget and what set it, and how to raise it. A
plugin that crashed is reported with how it ended and the last lines of its standard error. See section 11 for how a
run is bounded.

**What a validation can say.** Today: positions and orientations of bodies, and joint states, at the start, at the end
and at sampled instants. Planned: inputs (an initial configuration and joint drives, section 13) and temporal helpers
over the samples (always, eventually, within).

## 10. Caching

Three kinds of derived data are cached in the existing tiers (`cacheFiles`, memcache, S3):

- **Geometry**, keyed on the object's own configuration and everything it is built from (built).
- **Derived physical properties** -- mass, volume, centre of mass, inertia -- keyed on the shape's key plus the density
  and the stated values the derivation read (built, #755).
- **Simulation runs**: the plugin's result together with the whole run directory -- the scene file, its meshes,
  whatever the plugin wrote (built, #753). The key is the scene's own key (which covers the subject, a parameter of the
  scene), plus the plugin, its resolved options, its declared environment, the declaration's `params`, the exporter and
  its options, and the content of both scripts and of PartCAD's wrappers. Only successful runs are stored, since
  installing a missing solver changes no key -- and neither does giving a run longer, so a timeout or a crash is never
  stored either. The budget a run was given is not in the key: it bounds the run and does not change its answer.

A `validation:` is not part of a run's key: editing it re-judges the cached run rather than repeating it. The
**verdict** `pc test` records is keyed on the run's key plus the validation expressions, so that nothing stale is served
and a validation edit costs an evaluation, not a simulation -- 0.04 s on the example, with no engine started (built,
  #756). Skips, failed runs and declarations without a `validation:` are not recorded. `simulate:` itself is not part
of a shape's cache key: declaring or editing a simulation does not rebuild the object.

**What an implementation runs has to be in the key.** #753 keys a run on the content of the implementation's script and
the exporter's script, and on PartCAD's wrappers -- not on the other files those scripts import from their own package
(`mujoco_common.py`, `snapshot_raster.py`, ...), nor on the package's revision. A plugin update that changes only such a
module therefore served the previous result until `--cache-bypass`. Simulation, CAE and CAM runs are now keyed on
`Implementation.source_cache_key()`: every `.py` file of the implementing package by relative path and content (line
endings normalised), plus the commit for a package imported from git -- which also covers the data files a fetched
plugin ships -- and PartCAD's own `wrappers/` the same way. Not every file: CAE models and render outputs are written
into packages and would change the key on every run. So a data file a *local* plugin reads is the one input still
outside the key. No absolute path, mtime or sandbox detail enters it; each file is read once per process and then
`stat`ed, 9.7 ms the first time for the MuJoCo plugin and 0.05 ms after (built, #765).

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
  release, so a pin written before a chain of core pull requests lands is a guess at a number: the pins written during review assumed
  the chain merges in order, one release each, and are corrected to the real release when it is known.
- **Runs are isolated.** Two runs on one machine must not see each other: Gazebo runs get a per-run transport partition
  (`GZ_PARTITION`), because two worlds of the same name otherwise read each other's pose and joint messages -- which
  `pc test` running several simulations at once makes routine. A partition the user set is kept as the parent
  (`<theirs>:partcad-<id>`); using it as is would put every run back into one partition (built, sim-gazebo #7).
- **Runs are bounded, from both sides of the sandbox** (built, #797). Every run has a wall-clock budget, the first of:
  `simulation.timeout` in the user configuration (`PC_SIMULATION_TIMEOUT`), which is the machine's and over
  everything; `params: {timeout}` on the declaration; the plugin's own `timeout:`; else
  `max(300 s, 10 s x duration)`. A value that is not a positive number is passed over, so the bound moves and never
  switches off. The budget counts from when the interpreter starts: provisioning a sandbox is shared and legitimately
  slow, and is bounded nowhere here, as for every other implementation.
  - *Inside the sandbox*, `wrapper_simulate.py` hands the budget to the plugin as `request["timeout"]`, leads a process
    group, and when the budget is spent answers `{"success": false, "timed_out": <s>}`, stops everything the plugin
    started (found through `/proc` or `ps`, `wrappers/process_tree.py`; `taskkill /T` on Windows) and exits 124. It
    has to be in there: in the `docker` sandbox PartCAD's child is a `docker exec` client, and killing that leaves the
    interpreter and its engine running in a shared, long-lived container. On every way out, the wrapper also stops
    whatever the plugin left running, since a leftover process holding standard error holds the run open.
  - *Outside*, PartCAD waits the budget plus `TIMEOUT_GRACE` (30 s), for an interpreter so wedged that the wrapper's
    watchdog thread cannot run (held in native code, stopped). A bounded run is started as a session of its own (a
    new process group on Windows), and `runtime.kill_process_tree` kills its descendants (`psutil`), the group, and
    the process (`taskkill /T` on Windows). Inside a container, that reaches the `docker exec` client only; the
    wrapper is the net there. This bound must not need the event loop: on macOS, CPython's threaded child watcher
    (3.14.8) takes a *stopped* child for an exited one and reaps it with a blocking `waitpid` in the loop's own thread,
    which holds every timer, `wait_for`'s included, for as long as the child stays stopped. So `runtime.communicate`
    starts a thread that kills the tree `BACKSTOP` (5 s) after the bound if nothing has, and reports that as the
    timeout. Found by the frozen-plugin test hanging the macOS job; a pull request never runs macOS (it is in the
    merge queue's tier), which is why it reached `devel`.
  - A non-zero exit, a signal, an empty answer and an answer that is not a JSON object are `SimulationCrash`, carrying
    the last 30 lines of standard error; a spent budget is `SimulationTimeout`. Neither is a traceback, and neither is
    cached.
  - *The plugins* add a second line behind these, and stop a little before the budget so that what they report says
    how far they got: MuJoCo stops a run whose state is no longer finite, or that MuJoCo itself warns has become
    unstable, naming the time and the body or joint, and refuses an absurd `duration`, `timestep` or `samples` before
    stepping (sim-mujoco #14); Gazebo polls its server while it waits, fails at once with the server's exit status and
    the end of its standard error when it dies, bounds the wait for the first message, and kills the process group of
    the server and its watchers on every way out (sim-gazebo #12).
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

The joint mapping (`pc convert assembly -t assy`): a joint becomes a **socket** interface whose one port is the half
turn, which the parent implements at the joint origin under an instance named after the joint, and a **plug**
interface with one port at its origin, which the child implements at its own origin, with `mates:` on the plug. The
half turn on the socket's port is what the connection undoes, so the contact frame is the URDF joint frame: the
socket's freedom-of-movement parameters (`angle`, `offset`, or the principal names of a planar or floating joint) have
the URDF axis as their `dir`, verbatim, and `motion: {dof: [...]}` names them (built, step 11; until then the flip was
on the plug and every axis was remapped). Interfaces are deduplicated on the joint's type, axis, limits, dynamics and
mimic: a four-wheeled robot gets one interface pair for its wheels. No attempt is made to match the library of real
interfaces: a URDF joint says nothing about the hardware that implements it.

A `type: urdf` assembly carries its joints without converting: each link node a movable joint moves states that
joint, and the factory fills `AssemblyChild.joint` from it (section 8.8c). The export writes a link per rigid body and
a joint per pair of them, so a URDF read, exported and read again keeps its kinematics, and so does one converted to
ASSY and exported, except where the converter folds a chain of movable joints through a link with no geometry into its
last joint (section 8.8c).

Three mechanisms the URDF support needed, which the joint work builds on:

- **Units and conventions in one module.** URDF is metres, radians and fixed-axis roll-pitch-yaw; PartCAD is
  millimetres, degrees and axis-angle. `wrappers/urdf_common.py` keeps that conversion in one tested place, and the
  engine plugins import it rather than repeating it.
- **Parts that exist because an assembly produced them.** The parts a URDF points at have no declaration of their
  own; they are materialized into the package as `<assembly>/<link>` (and `<assembly>/<link>/<n>` under a link of
  several shapes), and the package resolves such a name by building the assembly that owns it. They are ordinary parts,
  inspectable and exportable, not an internal detail.
- **One link-frame term.** A link that is one shape placed at an `<origin>` has its part's frame at that offset, and a
  link of several is a sub-assembly whose frame is the link's. The ASSY conversion re-expresses each link in the link
  frame before writing its mesh -- one term per link, recorded by the importer and applied in one place -- rather than
  folding it into every socket and plug, so that everything downstream may assume the part's origin is the link's.

What does not survive: names (PartCAD names carry package paths), nesting, parametrization, exact B-rep geometry, and
the digital thread itself; a joint's starting value, which URDF cannot state; a link on a fixed joint as a link of its
own, since it is one body with its parent; and the name of a link with no geometry. Until step 11 the joints did not
survive either: every one was written `fixed`, to a root link with no geometry.

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
| URDF | built: a link per body and a joint per pair (step 11, #788) |
| MJCF | built, in sim-mujoco; the bodies of section 7 and the joints of section 8 (step 10) |
| SDFormat | built, in sim-gazebo; models and free bodies until section 8 |
| USD (UsdPhysics) | planned: Isaac Sim and the wider DCC ecosystem; the generic six-degree-of-freedom joint maps the representation of section 8.6 one to one |

## 13. Roadmap

Each step is useful on its own, which is the test of whether the decomposition is right.

| # | Step | State |
|---|---|---|
| 0 | `simulate:`, plugins, `pc sim`, the default scene; property tables; URDF read/write; MJCF and SDFormat in plugins | built |
| 1 | Cache analysis, route and simulation results across sandbox types | built (#753) |
| 2 | Command names in the docs and plugins; the `pc ide open --with mujoco` text | built (#754, sim-mujoco #4, sim-gazebo #3) |
| 3 | Mass properties from materials; kg/m³; one resolution, cached; shown in `pc info` | built (#755, sim-mujoco #5, sim-gazebo #4, the metal and plastic catalogs) |
| 4 | Scenes state gravity and a medium; fluid materials; buoyancy | built (#757, sim-mujoco #7, sim-gazebo #6, partcad-index #17) |
| 5 | Joint states in `before`/`after` | built (sim-mujoco #6, sim-gazebo #5) |
| 6 | `pc test` runs simulations; verdicts and their cache | built (#756) |
| 7 | `slippery` in a tilted scene, and MuJoCo contact settings | built (#761, sim-mujoco #8) |
| 7a | The friction table, measured | built (#762) |
| 7b | Buoyancy at the centre of buoyancy | built (#763, sim-mujoco #9, sim-gazebo #8) |
| 7c | Per-run Gazebo partitions | built (sim-gazebo #7) |
| 7d | Run keys cover what an implementation package ships | built (#765) |
| 7e | `resolve_resource_path` and colons in parameter values | built (#760) |
| 7f | Skills prepare generated objects for simulation | built (#759) |
| 7g | The user documentation refactored to how to use it; this record for the design | built (#758, #764) |
| 7h | Every run bounded, inside and outside the sandbox; crashes reported with their stderr; plugins detect divergence and a dead server | built (#797, sim-mujoco #14, sim-gazebo #12) |
| 8 | **Joints, core model**: `motion` degrees of freedom (explicit and implied), combination, joint names, `AssemblyChild.joint`, `pc info` and the `connect` check | built (#766) |
| 9 | **Bodies**: the assembly/scene rule, ASSY links that place a scene, `simulate:` on a scene, `fixed:`; the `feature_simulate` stacks become scenes; `wrappers/kinematics.py` | built (#784) |
| 10 | **MJCF joints**, with a pendulum example checked against its closed form | built (#786, sim-mujoco #12) |
| 11 | **URDF joints**, and the converter writing `dof:`; the round trip keeps the kinematics, but for chains the converter folds | built (#788) |
| 12 | **SDFormat joints** | decided |
| 13 | Inputs: `initial:` (a configuration) and `drive:` (position, velocity or effort targets over time) on `simulate:`; temporal helpers for validations | planned |
| 14 | Devices: actuators (torque constant, gear ratio, rotor inertia as MJCF `armature`) and sensors (encoders, IMU, force-torque, contact; cameras later) attached to ports | planned |
| 15 | Controller in the loop: a `software:` object, or a Python controller stepped by the plugin; ROS 2 through Gazebo | planned |
| 16 | Collision geometry (section 5.4) | planned |
| 17 | Named frames (8.10) and named configurations of an assembly | planned |
| 18 | Closed loops (8.9); a free water surface (6.1); USD export | planned |
| 19 | Unit-suffixed values through one parser | planned |

## 14. Open questions

- **`pc sim` with no `validation:`.** `pc test` skips it in a package run and fails it when the object is named. `pc sim`
  is unchanged for now, and the recommendation is to keep it so: `pc sim --json` on a declaration with no validation is
  how one sees what a plugin reports before writing the condition.
- **Physics of a summed joint.** The proposal in 8.7 (agree or let the mating say) is not confirmed.
- **The target-side sign convention** (8.3). It is today's placement behaviour; whether to keep it or change it before
  degrees of freedom make it visible in every joint's limits is open.
- **Native joint types** (8.13): decided on 2026-10-17 (8.13.9), and being built.

## 15. Lessons recorded

Worth keeping, because each was a mistake that looked reasonable at the time, and the shape of the correction says
where the design's boundaries are.

- **The assembly representation needed no change for URDF's geometry.** `Assembly`, `AssemblyChild` and `Part`
  expressed everything on the first try -- which is the good news and the bad: the representation is exactly rich
  enough for shapes and placements and had no place at all for anything else.
- **An exporter of a tree has to be handed the tree.** Decoding an envelope into one compound is right for every other
  exporter and fatal for a robot description. It was first an opt-in (`decode: false`), which left every exporter that
  did not opt in unable to read anything a node said about itself -- a drawing could not know a part's colour. Every
  implementation is now handed both, `wrapped` and `shape_tree`, out of one decoding of each shape.
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
- **Generating declarations finds the gaps hand-writing never reaches.** The schema had always allowed
  `ports: {name:}` and `implements: {iface:}` with no value, and both crashed; nothing had written them until the URDF
  conversion generated interfaces programmatically, and it found both at once.
- **A claim in an example is a test.** `slippery` said friction made a block slide off a level stack; nothing pushed it,
  and nothing checked until `pc test` ran simulations. An example whose claim is not checked is one readers learn to
  trust and should not.
- **A constraint is as stiff as the way it is written.** A screw's thread written as "the slide follows the hinge"
  and as "the hinge follows the slide" is one relation, and MuJoCo held only the second: it softens an equality by
  inverse inertia it adds up without the coefficient. Nothing in the file was wrong, and only a run against the
  thread's own ratio said so -- as only a run said that a carriage sat on its rail where MuJoCo's own contact filter
  does not reach.
- **Two units for one quantity is a defect, not a convention.** Material density was g/mm³ while the physics the
  exporters wrote was kg/m³, and the first fix added a second public spelling. Density is kg/m³ everywhere now.
- **"No fixed joints" is about how a weld is written, not about forgetting what is welded to what.** Step 9's body
  rule put every child that kept no freedom into its container's body, which was right for every example it was
  checked against and wrong for the first URDF with a fixed joint under a moving link: the forearm stayed with the
  base while the shoulder turned. A rigid connection now says what it is attached to.
- **A frame convention chosen for readability can cost a round trip.** The converter put the half turn on the plug to
  keep the socket's port at the URDF origin, which made every axis a remapped one and every exported link frame a half
  turn off the URDF's. Putting it on the socket's *port definition* keeps the implemented location at the URDF origin
  and the axes verbatim, and the round trip exact.
