Simulation and URDF
###################

PartCAD can read a `URDF <https://wiki.ros.org/urdf>`_ file as an assembly
(``type: urdf``), write one back out (``pc export -t urdf``), and convert an
assembly between URDF and ASSY in either direction (``pc convert assembly``).
This page is the design record for that work: what the conversions actually
preserve, what they cannot, and what it would take for PartCAD to hold
everything a physical simulation needs.

The "What exists today" section describes what is built. Everything after it is
a proposal, and none of it is implemented.

.. contents::
   :local:
   :depth: 2

==================
What exists today
==================

Reading a URDF
==============

``AssemblyFactoryUrdf`` drives ``wrapper_import_urdf`` in a python sandbox. The
sandbox parses the file with ROS's own ``urdf_parser_py``, walks the joint tree
from the root link with every joint at its zero position, resolves each link's
geometry, and hands back plain data. The core registers one part per shape -
``<assembly>/<link>`` for a link that is one, and ``<assembly>/<link>/<n>``
under a sub-assembly for a link that is several - and builds the very same
``Assembly``/``AssemblyChild`` tree an ASSY file produces.

The links go into **one flat list**, each at its absolute placement. The joint
tree is the robot's kinematics; an assembly is one static configuration of it,
so nesting a sub-assembly per joint would make an arm as deep as it has joints
and say nothing the placement does not. The relative placements are recorded in
a link table instead, which is what the ASSY conversion turns into joints.

Nothing is rewritten that does not have to be: a ``<mesh>`` becomes a part that
reads the very file the URDF named, and the ``<origin>`` that places it becomes
a location rather than a transform baked into a copy of the geometry. Only
``<box>``/``<cylinder>``/``<sphere>`` are generated, because there is no file to
point at.

A link is built from its **collision** geometry when it states both, since that
is the shape a simulator resolves contact against; ``ignoreCollision`` reverses
that per link or wholesale. The geometry that was not used is not discarded: it
becomes the part ``<assembly>/<link>/<visual|collision>``, defined and
exportable but not placed in the assembly.

What the link says about its physics is **copied field by field into named
PartCAD properties**, in PartCAD's own units. ``<inertial>`` becomes ``mass``,
``centerOfMass`` and ``inertia``; the friction and contact settings of a
``<gazebo>`` block become ``friction``, ``contactStiffness`` and the rest;
``<material>`` becomes ``material`` and ``color``. A joint's ``<limit>``,
``<dynamics>``, ``<safety_controller>`` and ``<mimic>`` become the ``motion``
and ``physics`` sections of the interface it turns into. Nothing is nested under
the name of the format it came from, and nothing is opaque.

That choice has a cost and it is deliberate: URDF that no property covers stops
the import, naming what it found. Core URDF is a closed vocabulary, so an
unknown element there means PartCAD is out of date and the remedy is to extend
the tables in ``wrapper_import_urdf.py``. ``<gazebo>`` is an open extension
point, so an unknown setting there is reported rather than fatal unless the
assembly asks for ``strict: true``. The export mirrors it: a PartCAD property
URDF cannot state is reported at info level rather than dropped in silence.

Nor does anything record the link's name or its parent. The part *is* named
after the link, and the joint tree is the URDF file - which is still on disk and
is read afresh - or, once converted, the ``connect:`` sections of the ASSY. A
second copy in a properties section would only be a second thing to keep right.

Writing a URDF
==============

``wrapper_render_urdf`` is handed the assembly *tree* rather than the compound it
decodes to. Each node becomes a link, each parent/child relation a fixed joint
carrying that child's placement, and each node with geometry gets an STL written
next to the URDF. A shape that appears more than once is written once and
referenced by every link that uses it.

A sub-assembly whose children are named *under* it - ``wrist`` holding
``wrist/1`` and ``wrist/2`` - goes back out as one link with a ``<visual>`` per
shape, at the offset each was placed at, rather than as a frame link with a link
per shape. So a link of several visuals survives the round trip as itself. The
slash is the whole of the rule, and it needs nothing recorded anywhere: it is
the same convention the import uses to name those parts in the first place.

The joint *tree* does not survive: the export mirrors the assembly, and a URDF
assembly is flat, so what comes out is a root frame with every link fixed to it
directly. That is an honest reading - the exported joints are all fixed because
PartCAD holds one static configuration, and a star of fixed joints is what that
is. The chain is preserved where it means something, in
``pc convert assembly -t assy``, and a faithful re-export would read it back
from there rather than from anything stashed on the parts.

What a part states about itself is written into the URDF element that states it:
mass, centre of mass and inertia into ``<inertial>``, friction and the contact
parameters into a ``<gazebo>`` block, ``material``/``color`` into
``<material>``. Only a part that says nothing gets computed inertial properties:
OCCT gives the volume, the centre of mass and the inertia tensor about it, and a
density turns those into a mass. Since PartCAD still has nowhere to record what
a part is *made of*, that density is a parameter of the export with a default
rather than a property of the part - the first gap this page proposes to close.

A link's name, and the properties looked up under it, come from the label on the
shape the exporter is handed - and there is one way that goes wrong today. The
shape cache is keyed by geometry, deliberately, so that two parts reading the
same mesh file do not compute it twice; but the entry carries the name and label
of whichever part wrote it, and the other part reads back wearing a name that is
not its own. Every consumer of a cached shape has that problem, and the URDF
export is simply the first to key on the answer. The fix belongs in the cache,
which should hand a shape back under the name it was asked for, so it is left
for a change of its own. Until it lands, exporting parts that share geometry
with other parts in the package can name a link after the wrong one and miss the
properties declared on it; ``test_export_reports_properties_urdf_cannot_state``
is marked ``xfail`` for exactly that reason.

Converting between the two
==========================

``pc convert assembly`` rewrites the package rather than just producing a file.
To URDF it writes the ``.urdf`` and its meshes and switches the declaration
over. To ASSY it writes an ``stl`` part for every link, an interface pair for
every joint, and an ``.assy`` whose nodes use ``connect:`` - so the result is an
assembly stated the way PartCAD states one, not a transcription of coordinates.
How the joints become interfaces is `URDF joints as PartCAD interfaces`_ below.

What the round trip preserves
=============================

``examples/produce_assembly_assy:logo`` exported to URDF and read back as a
``urdf`` assembly puts every shape back where it was, under the name it had,
built from the same geometry - flattened, because a URDF has no way to say
"these parts belong together" other than by joining them. That is the whole of
what survives.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Preserved
     - Lost
   * - Every shape, at the placement it had
     - Every name (PartCAD names carry package paths; ROS names cannot)
   * - Placements, to full double precision
     - Nesting: an ASSY may group its parts, a URDF's grouping is its joint tree
   * - Names of the assembly's own children
     - Parametrization: an ASSY parameter, an enrich, an alias
   * - Geometry, as a triangle mesh
     - Exact B-rep geometry; the mesh is a tessellation at a chosen tolerance
   * - Shape sharing (one mesh, many links)
     - Which part in which package a link came from - the digital thread itself

In the other direction, reading a URDF loses less than it used to but still
loses. Mass, inertia, friction, contact parameters and appearance become named
properties of the part and are written back on export; joint types, axes, limits
and dynamics become the ``motion`` and ``physics`` of the generated interfaces
when the assembly is converted to ASSY; the geometry a link was not built from
becomes a part of its own. What is genuinely gone is the *effect* of a joint -
the assembly is one configuration, so a movable joint is a placement and not a
degree of freedom - along with transmissions, sensors and ``ros2_control``
blocks, and the ``<origin>`` of geometry that ends up unplaced. PartCAD reports
the count of each rather than passing over them in silence, so the loss is
visible at import time and in ``pc info``.

What it took to implement
=========================

Worth recording, because the shape of the work says something about where the
gap is:

- **No change to the assembly representation was needed.** ``Assembly``,
  ``AssemblyChild`` and ``Part`` expressed everything the *geometric* half of
  URDF needs, on the first try. That is the good news and the bad news: the
  representation is exactly rich enough for shapes and placements, and has no
  place at all for anything else.
- **The wrapper protocol had to grow a raw mode.** ``ocp_serialize.decode()``
  turns an assembly envelope into a single ``TopoDS_Compound``, which is right
  for every other exporter and fatal for this one - URDF *is* the tree. Hence
  ``wrapper_common.handle_input(decode=False)``.
- **Units and conventions cost a module.** URDF is metres, radians and
  fixed-axis roll-pitch-yaw; PartCAD is millimetres, degrees and axis-angle.
  ``wrappers/urdf_common.py`` exists to keep that conversion in one tested
  place rather than spread across two wrappers.
- **The parts a URDF points at have no declaration.** They are whatever the URDF
  names, so they are materialized into the package in memory as
  ``<assembly>/<link>`` and the package resolves such a name by building the
  assembly that owns it. A concept of "a part that exists because an assembly
  produced it" did not exist before, and it turns out to be the right one: those
  parts are ordinary parts, inspectable and exportable, not an internal detail.
- **Mapping the robot's root link to the assembly itself was a mistake too.**
  It made an export come out with one link fewer, which looked like fidelity,
  but it only worked because each part recorded which link it *was*: the export
  matched the assembly node against a stored link name. Once that stored name
  went away - and it had to, since the part is already named after the link -
  the assembly went back to being what it is, a container. An export now writes
  a root frame with no geometry and every link fixed to it, which reads back as
  the same four placed links; the round trip is stable, just one honest link
  longer.
- **A link of several shapes is a sub-assembly, and combining them was a
  mistake.** Merging a link's visuals into one generated shape made the joint
  algebra fall out neatly - every part's origin was the link frame - but it
  bought that by rewriting the model: the mesh files the URDF pointed at were
  replaced by a generated compound and the ``<origin>`` that placed each one
  disappeared into the geometry. Keeping them as parts of a sub-assembly, each
  reading its own file at its own offset, costs one extra term in the joint
  algebra (below) and a table of where each link's item sits relative to the
  link frame. That is the right trade: a digital thread that rewrites what it
  was handed is not one.
- **Nesting a sub-assembly per joint was also a mistake, for the opposite
  reason.** It preserved the URDF's tree faithfully and cost an arm one level of
  depth per joint, in a representation that has no joints in it. Two different
  things were being expressed by one mechanism - "these shapes are one link",
  which is grouping, and "this link hangs off that one", which is kinematics -
  and only the first is structure. Flattening the second and recording the
  relative placements in a table beside the tree is what let the ASSY conversion
  keep the kinematics *and* the assembly stay shallow.
- **An opaque properties section was a mistake, and the least obvious one.** The
  first version carried what a URDF said under ``physics: {urdf: ...}``, keeping
  the source format's own structure so that an export could hand it straight
  back. It round-tripped perfectly and told PartCAD nothing: a mass was a mass
  only to the URDF exporter, and no other part of the system could read it,
  check it, or state one of its own. Copying each value into a named PartCAD
  property with a PartCAD unit is more code and a closed list to maintain, and
  it is what makes the property *PartCAD's* rather than a souvenir of where it
  came from. The rule that falls out of it - refuse URDF nothing maps, report
  PartCAD properties URDF cannot state - is what keeps the list honest, because
  the alternative to a loud failure is a quiet loss.
- **The same went for the link's identity.** Recording which link a part came
  from, and which link that link hung off, looked like cheap insurance. It was
  two more things to keep consistent with the names and the connections that
  already said it, and it let the exporter take a shortcut that stopped working
  the moment the record was removed. Hierarchy that has to be preserved belongs
  in the *name*, where a slash already means containment; relations between two
  things belong in the connection between them.
- **A cache entry is keyed by geometry, and carried an identity it should not
  have.** Two parts that read the same mesh file hash the same, so the second
  one came back wearing the first one's name and label. Nothing had noticed,
  because nothing had keyed anything off those; the URDF exporter names its
  links from them. Restamping on the way out of the cache, exactly as the write
  path stamps on the way in, was the fix.
- **Two long-standing gaps in the interface code surfaced.** The schema has
  always allowed ``ports: {name:}`` and ``implements: {iface:}`` with no value,
  and both crashed - nothing had written them before, because nothing had
  generated interfaces programmatically. Generating them found it at once.

None of that was hard. The hard part is everything the geometry does not cover,
which is the rest of this page.

.. _URDF joints as PartCAD interfaces:

URDF joints as PartCAD interfaces
=================================

This is the part worth dwelling on, because it is where the two models actually
have to be reconciled rather than translated.

A URDF joint relates two link *frames*: at the zero configuration, the child
link's frame sits at the joint's ``origin`` in the parent link's frame, and the
joint's ``axis`` says how it may move from there. PartCAD does not relate frames;
it relates **ports**, and its rule is that two connected ports *face* each
other - the connection composes the target's placement, the target port, a half
turn, the freedom-of-movement offsets, and the inverse of the source port.

So one side has to carry the flip. The mapping is:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - URDF
     - PartCAD
   * - joint (parent side)
     - a **socket** interface with one port at its origin, which the parent part
       implements at the joint origin, under an instance named after the joint
   * - joint (child side)
     - a **plug** interface whose one port sits at the half turn, which the child
       part implements once, at its own origin
   * - the two are the same joint
     - ``mates:`` on the plug, naming the socket
   * - ``axis``, ``limit`` lower/upper
     - ``motion: {axis, limits}``, in degrees or millimetres, plus an interface
       ``parameter`` (``angle`` for a revolute joint, ``offset`` for a prismatic
       one) that makes it move
   * - ``safety_controller``, ``mimic``
     - ``motion: {softLimits, mimic}`` - both bound the movement, so both are
       kinematics
   * - ``limit`` effort/velocity, ``dynamics``
     - ``physics: {maxEffort, maxVelocity, damping, friction}`` - what the
       movement costs
   * - a joint's ``<gazebo>`` block
     - ``physics: {springStiffness, springReference, stopCfm, ...}``
   * - ``calibration``
     - nothing: a limit-switch reference used when a real robot is
       commissioned, which says nothing about the model. Counted and reported
   * - a link's attachment
     - ``connect: {with: <plug>, name: <parent>, to: <socket>, toInstance: <joint>}``

All of this is stated in the *link* frame, which is not necessarily where a
link's geometry sits: a link that is one shape placed at an ``<origin>`` has its
part's frame at that offset, and a link of several is a sub-assembly whose frame
is the link's. So the conversion re-expresses each link in the link frame before
writing its mesh - one term, recorded per link by the importer and applied in
one place - and everything downstream can then assume the part's origin *is* the
link's. Folding that term into the interface instances instead would have worked
too, and would have spread it across every socket and plug in the file.

Putting the flip on the plug is what keeps the *socket* readable: the parent
implements it at exactly the joint origin, which is a number a reader can check
against the URDF. It costs one wrinkle, in the axis. The half turn ``T`` is a
180 degree rotation about ``(1, 1, 0)``, and a rotation conjugated by it is the
same rotation about the mapped axis, ``(x, y, z) -> (y, x, -z)``. So the
parameter's ``dir`` is the joint axis under that map, while ``motion.axis``
keeps it as URDF stated it - which is also the socket port's own frame, since
that port sits at the joint origin. The record stays readable; the executable
half stays correct.

The units change at the boundary and only there. A URDF limit is radians for a
revolute joint and metres for a prismatic one; what lands in ``motion.limits``
is degrees and millimetres, because those are PartCAD's units and a property
that keeps its source format's unit is a property nothing else can use. The
reader converts once, and every consumer downstream - the generated parameter,
the schema, a person reading the file - sees one convention.

Two things fall out of this that are worth more than the mapping itself.

**Interfaces are reusable, instances are not.** What varies between two joints of
the same kind is *where* they are, and that lives in the ``implements:``
instance location, not in the interface. So every fixed joint in a robot is the
same interface, and so is every revolute joint with the same axis and limits.
The converter deduplicates on exactly that - the joint's type, axis, limits,
dynamics and mimic - and a four-wheeled robot comes out with one interface pair
for its wheels rather than four. There is deliberately no attempt to match
against the existing library of interfaces: a URDF joint says nothing about the
*hardware* that implements it, so claiming it is an ``m3-screw-6mm`` would be an
invention. Custom interfaces per joint kind, reused where they agree, is the
honest reading.

**A pose becomes expressible.** The parameter the converter generates is not
decoration: ``connect: {toParams: {angle: 90}}`` in the generated ASSY places
the child exactly where the URDF joint at 90 degrees would, and everything
below it follows. That is a static assembly gaining the first half of a
kinematic one, using machinery PartCAD already had. What is still missing is the
other half - a *named configuration* of the whole assembly rather than a value
written into one connection - which is item 5 below.

==========================================
What a physical simulation actually needs
==========================================

URDF is the smaller half of the story. Gazebo does not simulate URDF: it
converts it to `SDF <http://sdformat.org/>`_ on load, and SDF is what expresses
a simulatable world. MuJoCo's MJCF and Isaac Sim's USD physics schemas differ in
spelling but ask for the same information. Taking the union of them, a
simulation needs the following, and PartCAD today has none of it.

Mass properties
===============

Mass, centre of mass, and the inertia tensor about the centre of mass, in a
stated frame. URDF requires them per link and defaults them to zero, which makes
a model load and then behave nonsensically - a zero-mass link is the single most
common defect in published URDFs.

These are *derivable* from a solid plus a density, which is exactly what the
exporter does today. What is missing is the density, and behind it the notion of
what a part is made of.

Collision geometry
==================

Simulators separate the shape that is drawn from the shape that collides,
because contact resolution against a hundred-thousand-triangle visual mesh is
both slow and numerically ill-behaved. The usual answers are a primitive
(box/cylinder/sphere/capsule), a convex hull, or a convex decomposition
(V-HACD and friends). MuJoCo goes further and *only* collides convex shapes,
silently taking the hull of anything else.

PartCAD has one shape per part. A part has no way to say "collide me as this
simpler thing".

Contact and surface properties
==============================

Friction (isotropic and anisotropic - SDF's ``mu``/``mu2`` with a direction
``fdir1``, plus torsional friction), restitution, contact stiffness and damping,
slip compliance, and the solver knobs that go with them (``kp``, ``kd``,
``min_depth``, ``max_vel``, ``soft_cfm``, ``soft_erp``). These are properties of
a surface pairing, approximated per-body by every engine in use.

Kinematics
==========

The joint: its type (fixed, revolute, continuous, prismatic, ball, planar,
floating, screw, universal), its axis, the frames on the two bodies it relates,
its position/velocity/effort limits, its dynamics (damping, Coulomb friction,
spring stiffness and reference), and relations between joints (``mimic``, gear
ratios).

URDF is restricted to a *tree*: it cannot express a closed kinematic loop, which
is why four-bar linkages and parallel manipulators are written in SDF or with an
explicit loop-closing constraint. SDF can.

Actuation and control
=====================

Which joints are driven, by what, through which reduction, and what interfaces
a controller sees. ROS 1 spelled this ``<transmission>``; ROS 2 spells it
``<ros2_control>`` with hardware components, command interfaces and state
interfaces. Simulators additionally want actuator limits and often a motor
model.

Sensors
=======

Cameras (with intrinsics, resolution, clipping, distortion), depth cameras,
lidars (with ray patterns and ranges), IMUs, contact sensors, force-torque
sensors - each attached to a *frame*, each with an update rate and a noise
model. URDF has no sensor element at all; they arrive through ``<gazebo>``
extension blocks, which is the clearest evidence that URDF is not a simulation
format so much as a kinematics format with a simulation format bolted on.

Appearance
==========

Colors and materials matter to simulation once a camera is in the loop: a
perception stack trained in simulation is sensitive to albedo, roughness,
metalness, normal maps and transparency. SDF and USD both carry a PBR material
description; URDF carries an RGBA color and a texture filename.

The world
=========

Gravity, the ground, lighting, the initial pose of every model, wind,
atmosphere, and the physics engine's own parameters (step size, solver type and
iteration count, contact parameters). This is SDF's ``<world>``, and it is
exactly the "scenes" PartCAD has always intended to have.

Frames
======

Everything above hangs off named coordinate frames: the link frame, the joint
frame, a tool centre point, a sensor mount, a grasp pose. SDF has explicit
``<frame>`` elements and poses stated ``relative_to`` them. PartCAD has
locations, but no named frames to state them against.

=========
Proposal
=========

Principles
==========

**Derive what can be derived; store only what cannot.** PartCAD's advantage over
a hand-written URDF is that it holds the actual geometry. Mass, centre of mass
and inertia should be computed from the solid and a material, not typed in - and
a typed-in value should be an explicit override that says why it exists (a
measurement, a vendor datasheet, a stand-in for content PartCAD does not model).

**Keep the CAD the source of truth.** Simulation artifacts - tessellated meshes,
convex hulls, computed inertia - are derived data. They belong in the shape
cache, content-hashed like every other derived shape, so that changing the CAD
invalidates them. This is what the digital thread means here.

**Model the concept, not the format.** ``mu``/``mu2`` is ODE's spelling of
friction. PartCAD should store friction and let each exporter spell it. The
formats disagree on almost everything except what they are trying to describe.

**Lose loudly, never quietly.** The tempting version of this principle is "lose
nothing": carry whatever PartCAD does not model as opaque, format-tagged
passthrough so that a round trip is lossless long before it is understood. That
is what ``physics:`` was at first, and it was the wrong trade. A value stored
under the name of the format it came from is readable by exactly one exporter;
it is not a property of the part, it is a souvenir. The version that survived
copies each value into a named PartCAD property with a PartCAD unit, keeps the
list of them closed, and makes the two failure modes loud: input nothing maps
stops the import, and a property the target format cannot state is reported when
it is written. A round trip is then lossless *and* the values mean something to
the rest of the system. Everything below extends that list; none of it reopens
the passthrough.

1. Materials as first-class objects
===================================

A new object kind alongside parts and sketches, so that materials are packaged,
versioned and shared the way parts already are:

.. code-block:: yaml

  # //pub/materials:partcad.yaml
  materials:
    aluminum-6061:
      density: 2700 kg/m^3
      appearance:
        color: "#b8b8b8"
        metalness: 1.0
        roughness: 0.35
      friction: { static: 0.6, dynamic: 0.5 }
      restitution: 0.3

This single addition is what turns the exporter's density parameter into a
property of the model, and it does double duty: the same material drives
rendering, the manufacturing cost estimate that ``partcad`` already reasons
about, and the simulation.

2. Physical properties a part does not have to state
====================================================

A part's ``physics:`` section already holds the modelled properties -
``mass``, ``centerOfMass``, ``inertia``, ``friction``, the contact parameters -
each with a PartCAD name and a PartCAD unit. What it does not do is *derive*
any of them, check any of them, or distinguish a measured value from a guess.
Three additions, in increasing order of how much they are worth:

- **Derivation.** With a material behind it (item 1), a part that states no
  ``mass`` has one: the solid's volume times the material's density, cached like
  any other derived value and invalidated when the CAD changes. The same for
  ``centerOfMass``, ``inertia`` and the surface properties. Today the URDF
  exporter computes exactly this, from a density passed on the command line,
  and throws it away afterwards - it should be a property of the part that every
  consumer sees.
- **Provenance.** A declared value should say why it exists, since "measured on
  the bench" and "copied from a vendor datasheet" and "invented so the
  simulation would load" are not the same claim:

  .. code-block:: yaml

    physics:
      mass: 0.812
      massSource: measured   # measured | datasheet | estimated | derived

- **Checking.** ``pc lint`` should flag the classic defects, all of which are
  common in published URDFs and all of which load without complaint: zero mass,
  an inertia tensor that is not positive definite, one that violates the
  triangle inequality, and a declared mass that disagrees with volume times
  density by more than a tolerance.

Anisotropic friction is the one property that needs more structure than it has
today: ``friction``/``friction2``/``frictionDirection`` is ODE's shape of it,
kept because it is what URDF states. A modelled version would be a static and a
dynamic coefficient with an optional anisotropy, and the URDF exporter would
flatten it on the way out.

3. Collision geometry
=====================

A URDF's collision geometry is not lost today - a link that states both shapes
is built from the collision one and the visual one becomes a part of its own -
but the *relation* between the two is: they are two parts that happen to be
named alike, and nothing says one is the simplified stand-in for the other. A
part should be able to say it:

.. code-block:: yaml

  parts:
    bracket:
      type: step
      collision:
        type: convexDecomposition   # or: convexHull | primitive | part | none
        maxHulls: 8
        tolerance: 0.5mm

``convexHull`` and ``convexDecomposition`` are computed in a sandbox and cached
like any derived shape; ``part`` points at another PartCAD part, which is how a
hand-simplified collision shape gets version-controlled next to the real one -
and is exactly what a URDF import would then produce instead of a part with a
suggestive name; ``primitive`` fits a box/cylinder/sphere/capsule to the
geometry.

4. Named frames
===============

.. code-block:: yaml

  parts:
    gripper:
      type: step
      frames:
        tcp:   { location: [[0,0,180], [0,0,1], 0] }
        mount: { port: base_flange }     # derived from an existing port

Frames are the attachment points for sensors, joints and grasp poses, and they
are what an exporter needs to write ``<frame>`` or a sensor's ``<origin>``.
PartCAD's ``interfaces`` and ``ports`` already describe named, located features
on a part; frames should be the same mechanism, not a parallel one.

5. Kinematics: a configuration, not a joint section
===================================================

The obvious proposal here used to be a ``joint:`` form for an ASSY node, next to
``location:`` and ``connect:``. Building the URDF mapping above argues against
it. A joint is not a third way to place a part - it is what a ``connect:``
*already is*, plus a value. An interface says what freedom of movement it allows
(``motion:``, ``parameters:``); a connection says which two things are joined
and, optionally, at what value (``toParams:``). Adding a parallel ``joint:``
section would restate the interface's own description at every use site, which
is the duplication the rest of PartCAD exists to remove.

What is actually missing is one level up: the assembly has no way to name a
*configuration*.

.. code-block:: yaml

  assemblies:
    robot:
      type: assy
      configurations:
        home:    { shoulder_pan: 0deg, elbow: 0deg }
        stowed:  { shoulder_pan: -90deg, elbow: 135deg }
      configuration: home    # which one this assembly shows

with the connections referring to the configuration rather than carrying a
literal:

.. code-block:: yaml

  - part: arm
    connect:
      to: shoulder_pan-socket
      toParams: { angle: "{{ joint.shoulder_pan }}" }

Everything that exists today - a tree of rigid placements - is what you get by
evaluating a configuration, so no consumer of the representation has to change.
But ``pc inspect 'robot;configuration=stowed'`` becomes meaningful through the
parameter machinery ASSY files already have, and an exporter gains something to
write a joint *state* from.

Two things this still needs, which the URDF work did not:

- **A joint identity.** ``toInstance: shoulder_pan`` names the joint today only
  by convention. A configuration has to address it, so the instance name has to
  become the joint's name in earnest.
- **Loops.** A four-bar linkage is a connection whose child is already placed.
  PartCAD's tree cannot express it and neither can URDF; SDF can. Until then the
  honest behaviour is to detect it and say so.

There remains a genuinely attractive case for *deriving* joints from the
existing interface library: a bearing bore is revolute about its own axis and a
linear rail is prismatic along its own, so an interface that says so once gives
every ``connect:`` that uses it a joint for free. That is the same ``motion:``
section the URDF conversion writes, applied to hand-authored interfaces instead
of generated ones - which is why ``motion:`` belongs on the interface and not on
the connection.

6. Internal representation
==========================

The corresponding change in ``partcad.assembly`` is small and additive:

- ``AssemblyChild`` gains ``joint`` (the kinematic relation to its parent, or to
  a named sibling) and ``frames``. ``location`` stays what it is - the resolved
  placement at the current joint states - so ``Assembly._get_shape_real()``,
  the BREP envelope, the cache and every exporter keep working unchanged.
- ``Assembly`` gains a ``configuration``: the map of joint name to value it was
  evaluated at, hashed into the cache key like any other parameter.
- ``Part`` gains ``physical`` and ``collision`` accessors that resolve declared
  values against derived ones, computing the derived ones in a sandbox on
  demand and caching them.
- The BREP envelope grows a sibling channel for non-geometric data, so a
  wrapper can be handed the physical properties without a second round trip.

7. Sensors, actuators and plugins
=================================

.. code-block:: yaml

  assemblies:
    robot:
      devices:
        front_camera:
          type: camera
          frame: head/camera_mount
          rate: 30Hz
          image: { width: 1280, height: 720, format: R8G8B8 }
          fov: 1.05rad
          noise: { type: gaussian, stddev: 0.007 }

PartCAD should model the handful of device types that every simulator agrees on
(camera, depth, lidar, imu, contact, force-torque) and treat the rest as
passthrough.

8. Scenes as worlds
===================

The scenes PartCAD has always planned are SDF worlds: gravity, ground, lights,
model instances with initial poses, and physics engine settings. A scene is also
where a *fixed to the world* joint belongs, which is the piece a single assembly
cannot express.

9. The property tables, and keeping them honest (in place)
==========================================================

This is the item that is built, and doing it first was right: it makes a URDF
round trip nearly lossless while the rest of the proposal is still being
designed, and it is the difference between PartCAD being usable in a robotics
workflow and being a one-way trip out of one.

A part carries ``physics:``, ``material:`` and ``color:``; an interface carries
``motion:`` and ``physics:``. Every property in them is a PartCAD property with
a PartCAD unit and a closed definition in the schema. A URDF import reads its
values into them one at a time and the URDF export writes each one back into the
element that states it. The two rules that keep the list honest are the loud
failures: URDF that no property covers stops the import, and a property URDF
cannot state is reported when the file is written.

What is still missing:

- **``<ros2_control>`` and ``<transmission>``**, which are robot-level rather
  than link-level, and so have nowhere to attach yet. The assembly needs a
  ``physics:`` of its own - which it deliberately does not have today, because
  an assembly is a container and every property so far belongs to something
  inside it.
- **Properties that are not a link's or a joint's.** A URDF's ``<gazebo>``
  blocks also carry sensors and simulator plugins, which items 7 and 8 cover;
  until then they are counted and reported, not carried.
- **Any check at all that a declared property still applies.** ``physics:`` does
  not take part in the shape cache, which is right - it says nothing about the
  geometry - but it also means nothing notices when the geometry moves out from
  under it. A mass read from a URDF survives an edit to the CAD that invalidates
  it, silently. ``pc lint`` is where that belongs, and it needs item 2 to have
  something to compare against.

10. Units
=========

Simulation is SI; PartCAD is millimetres and degrees. The notation used
throughout this page - ``12 N*m``, ``2 rad/s``, ``2700 kg/m^3``, ``180deg`` -
should be real: a unit-aware scalar type, stored canonically, so that no
exporter has to guess and no user has to remember which of the two conventions a
given field is in. This is the smallest item on the list and the one that
prevents the largest class of silent errors.

11. Export targets
==================

With the above in place, the export matrix is:

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Target
     - Priority
     - Notes
   * - URDF
     - Done (geometry only)
     - The common denominator. Tree-only kinematics, sensors only via extensions.
   * - SDF
     - Next
     - What Gazebo actually simulates. Expresses everything in this proposal, worlds included, and is where a PartCAD *scene* maps naturally.
   * - MJCF
     - Later
     - MuJoCo. Needs convex collision geometry, which item 3 provides.
   * - USD
     - Later
     - Isaac Sim and the wider DCC ecosystem, through the UsdPhysics schemas.

Suggested order of work
=======================

Each step is useful on its own, which is the test of whether the decomposition
is right:

0. **Passthrough** (item 9) - *done*. The URDF round trip carries what PartCAD
   does not model instead of dropping it.
1. **Units** (item 10). Everything after this depends on it and it gets harder
   to add later - the generated ``motion:`` sections already have to state
   ``units: rad`` in prose because there is no way to state it in the value.
2. **Materials and physical properties** (items 1-2). Turns the exporter's
   density parameter into a model property and makes a computed inertial
   trustworthy, so that carrying one becomes the exception rather than the rule.
3. **Collision geometry** (item 3). Independently valuable - it also makes
   rendering and interference checking cheaper - and it is what would let the
   collision/visual choice ``ignoreCollision`` makes today become "keep both".
4. **Frames** (item 4), folded into the existing ports/interfaces mechanism.
5. **Configurations** (items 5-6). The largest change, and the one that turns an
   assembly into a mechanism rather than a photograph of one.
6. **SDF export**, which is the first target able to carry all of the above.
7. **Sensors** (item 7) and **scenes** (item 8).

Non-goals
=========

- PartCAD should not become a simulator, or wrap one. It should describe a
  product well enough that a simulator can be handed it.
- PartCAD should not model every engine-specific solver parameter as a
  first-class concept. But the alternative is not a passthrough container: it is
  to leave them out and say so when one is seen, which is what the import does
  for an unknown ``<gazebo>`` setting.
- Reading a URDF should not become lossless by making PartCAD's model a copy of
  URDF's. The point is a model that URDF, SDF, MJCF and USD are all views of.
