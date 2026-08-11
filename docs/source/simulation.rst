Simulation and URDF
###################

PartCAD can now read a `URDF <https://wiki.ros.org/urdf>`_ file as an assembly
(``type: urdf``) and write one back out (``pc export -t urdf``). This page is
the design record for that work: what the two directions actually preserve,
what they cannot, and what it would take for PartCAD to hold everything a
physical simulation needs.

It is a proposal. Nothing below the "What exists today" section is implemented.

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
geometry, and hands back plain data. The core registers the referenced meshes as
parts and builds the very same ``Assembly``/``AssemblyChild`` tree an ASSY file
produces.

Writing a URDF
==============

``wrapper_render_urdf`` is handed the assembly *tree* rather than the compound it
decodes to. Each node becomes a link, each parent/child relation a fixed joint
carrying that child's placement, and each node with geometry gets an STL written
next to the URDF. A shape that appears more than once is written once and
referenced by every link that uses it.

Inertial properties are the one thing the exporter adds rather than carries:
OCCT gives the volume, the centre of mass and the inertia tensor about it, and a
density turns those into a mass. Since PartCAD has nowhere to record what a part
is made of, the density is a parameter of the export with a default, not a
property of the part - which is the first gap this page proposes to close.

What the round trip preserves
=============================

``examples/produce_assembly_assy:logo`` exported to URDF and read back as a
``urdf`` assembly produces a tree with the same nesting, the same number of
children at every level and the same placements, built from the same geometry.
That is the whole of what survives.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Preserved
     - Lost
   * - The tree of placed shapes
     - Every name (PartCAD names carry package paths; ROS names cannot)
   * - Placements, to full double precision
     - Parametrization: an ASSY parameter, an enrich, an alias
   * - Geometry, as a triangle mesh
     - Exact B-rep geometry; the mesh is a tessellation at a chosen tolerance
   * - Shape sharing (one mesh, many links)
     - Which part in which package a link came from - the digital thread itself

And in the other direction, reading a URDF drops mass and inertia, joint types,
axes, limits and dynamics, ``mimic`` relations, materials and colors, collision
geometry (when it differs from the visual geometry), sensors, transmissions,
``ros2_control`` blocks and every Gazebo extension. PartCAD reports the count of
each rather than passing over them in silence, so the loss is visible at import
time.

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
- **The parts a URDF points at have no declaration.** They are whatever files
  the URDF names, so they are materialized into the package in memory and
  marked ``internal``. A concept of "a part that exists because an assembly
  needed it" did not exist before.
- **Mapping the robot's root link to the assembly itself** is what makes the
  round trip structurally exact instead of growing a wrapper level each time.

None of that was hard. The hard part is everything the geometry does not cover,
which is the rest of this page.

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

**Lose nothing, even before modelling it.** Anything PartCAD does not yet
understand should survive an import as opaque, target-tagged passthrough, so
that a round trip is lossless long before it is fully modelled.

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

2. Physical properties on a part
================================

.. code-block:: yaml

  parts:
    bracket:
      type: step
      material: //pub/materials:aluminum-6061
      physical:
        # Everything here is optional. What is absent is computed from the
        # solid and the material; what is present overrides it and says why.
        mass: { value: 0.812 kg, source: measured }
        centerOfMass: [12.4, 0, 31.0]
        inertia:                       # about the centre of mass, part frame
          ixx: ..., ixy: ..., ixz: ..., iyy: ..., iyz: ..., izz: ...
        surface:
          friction: { static: 0.8, dynamic: 0.7, anisotropy: { direction: [1,0,0], ratio: 0.4 } }
          restitution: 0.2
          contact: { stiffness: 1e6 N/m, damping: 1e3 N*s/m }

A ``pc info`` on such a part should show the derived values next to the declared
ones, and ``pc lint`` should flag the classic defects: zero mass, an inertia
tensor that is not positive definite, one that violates the triangle inequality,
or a declared mass that disagrees with geometry times density by more than a
tolerance.

3. Collision geometry
=====================

A part gains an optional second shape, declared the same way any other shape is:

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
hand-simplified collision shape gets version-controlled next to the real one;
``primitive`` fits a box/cylinder/sphere/capsule to the geometry.

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

5. Kinematics: joints in assemblies
===================================

This is the substantial change. Today an ASSY node places a child with a
``location``, or connects it by ``connect``/``connectPorts``. A third form:

.. code-block:: yaml

  links:
    - part: base
      name: base
    - part: arm
      name: arm
      joint:
        type: revolute
        parent: base
        origin: [[0,0,20], [0,0,1], 0]      # or connect/connectPorts, as today
        axis: [0, 0, 1]
        limits: { lower: -180deg, upper: 180deg, effort: 12 N*m, velocity: 2 rad/s }
        dynamics: { damping: 0.1, friction: 0.05 }
        state: 0deg                          # the configuration this assembly shows
        mimic: { joint: arm2, multiplier: -1 }

Two things follow from this, and they are the reason it is worth doing.

**A static assembly becomes one sample of a parametrized one.** ``state`` is the
joint value the assembly is evaluated at. Everything that exists today - a tree
of rigid placements - is what you get by evaluating the joints at their states,
so no consumer of the representation has to change. But ``pc inspect
'robot;shoulder=45deg'`` becomes meaningful, and the same machinery that already
passes parameters to an ASSY file drives a pose.

**Joints should mostly be derived, not written.** PartCAD's interfaces and
mating already describe how two parts go together, and interface parameters
already generate offsets. Give an interface a degrees-of-freedom description - a
bearing bore is revolute about its axis, a linear rail is prismatic along its
own - and a joint falls out of a ``connect:`` that is already there. Writing
``axis: [0,0,1]`` by hand next to a bearing whose axis is already known is the
kind of duplication the rest of PartCAD exists to remove.

For a closed loop (a four-bar linkage), a node may state more than one joint;
the exporter then has to pick a spanning tree and emit the remainder as an
explicit loop constraint, or refuse and say so, since URDF cannot express it.

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

9. Passthrough, so nothing is lost
==================================

.. code-block:: yaml

  assemblies:
    robot:
      type: urdf
      passthrough: keep      # store unmodelled content verbatim, tagged by target

Everything the importer does not understand - ``<gazebo>`` blocks,
``<ros2_control>``, vendor extensions - is kept as opaque XML tagged with the
format it came from, attached to the link or joint it referenced, and written
back out on export to that same format. This is worth doing *first*: it makes a
URDF round trip lossless while the rest of the proposal is still being built,
and it is the difference between PartCAD being usable in a robotics workflow and
being a one-way trip out of one.

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

1. **Passthrough** (item 9). Makes the URDF round trip lossless immediately.
2. **Units** (item 10). Everything after this depends on it and it gets harder
   to add later.
3. **Materials and physical properties** (items 1-2). Turns the exporter's
   density parameter into a model property and makes the exported inertials
   trustworthy.
4. **Collision geometry** (item 3). Independently valuable - it also makes
   rendering and interference checking cheaper.
5. **Frames** (item 4), folded into the existing ports/interfaces mechanism.
6. **Joints** (items 5-6). The largest change, and the one that turns an
   assembly into a mechanism.
7. **SDF export**, which is the first target able to carry all of the above.
8. **Sensors** (item 7) and **scenes** (item 8).

Non-goals
=========

- PartCAD should not become a simulator, or wrap one. It should describe a
  product well enough that a simulator can be handed it.
- PartCAD should not model every engine-specific solver parameter as a
  first-class concept. Those are passthrough (item 9) unless they turn out to
  describe something physical.
- Reading a URDF should not become lossless by making PartCAD's model a copy of
  URDF's. The point is a model that URDF, SDF, MJCF and USD are all views of.
