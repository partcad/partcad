Simulation, URDF and SDFormat
#############################

PartCAD can read a `URDF <https://wiki.ros.org/urdf>`_ file as an assembly
(``type: urdf``), write one back out (``pc export -t urdf``), and convert an
assembly between URDF and ASSY in either direction (``pc convert assembly``).
It does the same for `SDFormat <http://sdformat.org/>`_ -- what Gazebo describes
a simulation *world* in -- against a :ref:`scene <scenes>` rather than an
assembly: ``type: world``, ``pc export -S -t world``, ``pc convert scene``. And
it does the same for `MJCF <https://mujoco.readthedocs.io/en/stable/XMLreference.html>`_,
what `MuJoCo <https://mujoco.org/>`_ describes a model in: ``type: mjcf``,
``pc export -t mjcf``, as an assembly or as a scene.

It can also **run** one. ``simulate:`` is where a part or an assembly says what
it is supposed to do -- or not do -- once it is placed in a world and the world
is switched on, and ``pc sim`` places it, runs it and checks the claim. This
page is the design record for all of that: what the conversions actually
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

A URDF reaches a package by the same two commands any other foreign file does,
and they mean the same two things they mean for a STEP file. ``pc add assembly
urdf <path>`` *declares* it: the package points at the file, the file stays a
URDF, and its links become parts as it is read. ``pc import assembly <path>``
*converts* it: the package gains an ``stl`` part per link, an interface pair per
joint and an ``.assy``, and nothing points at the URDF afterwards. The import is
the conversion described in `Converting between the two`_, run against a
declaration that lives only for the length of it - which is what lets the source
file sit anywhere, the way a STEP file being imported does.

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

The URDF exporter (``//builtin/export``'s ``export_urdf.py``) is handed the
assembly *tree* rather than the compound it decodes to - which is what
``decode: false`` on its declaration asks for. Each node becomes a link, each parent/child relation a fixed joint
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

A link's name, and the properties written under it, come from the shape the
exporter is handed, and both travel on that shape together. This used to be the
one place the shape cache showed through: the cache is keyed by geometry,
deliberately, so that two parts reading the same mesh file do not compute it
twice, and the entry used to carry the name of whichever part wrote it - so the
other part read back wearing a name that was not its own, and the properties
looked up under that name were the wrong part's or nobody's. The entry no longer
stores that outer layer at all. What identifies the shape being asked for - its
name, its label, its placement, and what it reports about itself - is stamped
onto the payload from the asking object's own configuration every time an entry
is read, so parts that share geometry each get themselves back.

The stamp reaches the shape that was asked for and no further. Inside a cached
assembly the children sit in the entry with the names, labels and properties
they were built with, because down there they are not who is asking - they are
what the tree is made of, as much a part of the answer as the geometry. So a
link exported from a part is that part; a link exported from a child of a cached
assembly is whatever that child was when the tree was cached, and it takes a
change the assembly actually hashes, or ``pc system reset``, to build it again.

What a shape reports about itself is cached too, in an entry of its own beside
the geometry - the geometry's key with ``-props`` appended. Both are filled by
the one run that actually instantiates the shape, and they are read apart: a
consumer after a part's material need not pull its BREP back out of the cache,
and a cache written before that entry existed is a miss for the properties and
not for the geometry. It is not what the stamp above is made of, though: that
entry is keyed on the geometry, so what sits in it belongs to the geometry -
which is where a *derived* property (item 2 below) would land. What the object
asking reports is its own ``properties:`` section, and only that.

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

Reading a Gazebo world
======================

A ``.world`` file reaches a package the same two ways a URDF does, and they mean
the same two things. ``pc add scene world <path>`` *declares* it: the package
points at the file, the file stays SDFormat, and the shapes its models place
become parts as it is read. ``pc import scene <path>`` *converts* it: the
package gains one part per shape and an ``.assy`` scene that places them, and
nothing points at the world file afterwards.

The two formats meet at the world's initial state. ``SceneFactoryWorld`` drives
``wrapper_import_world`` in a python sandbox, which parses the XML with the
standard library, places every model at its ``<pose>`` and every link at its own
pose inside the model, and hands back plain data. The core registers one part
per shape -- ``<scene>/<model>/<link>``, and ``<scene>/<model>/<link>/<n>`` for a
link made of several -- and builds the very same tree an ASSY scene produces.

Unlike the URDF reader, this one **keeps the nesting**: SDFormat's models are
containers of links and of other models, which is exactly what a PartCAD
sub-assembly is, so nothing has to be flattened. The URDF reader flattens
because a URDF's tree is its *kinematics*, and that is a different thing from
containment.

Everything else is the same trade: a ``<mesh>`` becomes a part that reads the
very file the world named, ``<box>``/``<cylinder>``/``<sphere>`` are written out
as STEP under PartCAD's own state directory (the world file is not touched), and
what a link says about itself -- mass, inertia, friction, contact, colour --
becomes named PartCAD properties, the very same ones the URDF reader states.

What a static arrangement cannot hold is counted and reported rather than passed
over in silence: joints, lights, sensors, plugins, actors, physics settings, and
the ``<plane>`` every ground plane is. ``pc info`` lists the tally.

The one part most likely to come up empty is ``<include>``. It names a model by
URI, and outside a Gazebo installation there is no model database to resolve one
against; what is resolvable -- a relative path, a ``file://``, a ``model://``
that lands in ``modelPaths`` or beside the world file -- is read, and the rest is
reported.

Writing a Gazebo world
======================

``pc export -S -t world`` writes a scene as a ``.world`` file plus the mesh files
it references. Like the URDF exporter it is handed the assembly tree itself
(``decode: false``), because the models, the links, the poses and the properties
are built from what the tree says and decoding would throw all four away.

Anything placed in the world is a ``<model>``, anything with a subtree is a
``<model>`` wherever it sits, and a node that is geometry is a ``<link>`` with a
``<visual>`` and a ``<collision>``. Meshes are written in millimetres and
referenced with ``<scale>0.001 0.001 0.001</scale>``, and poses are in metres
and radians, exactly as the URDF exporter does it.

Two things the file gets that the scene never said, because a world without them
is not usable: a ``sun`` light and a ground plane. Both are export parameters
(``sun``, ``ground_plane``) and both can be turned off. Every model is written
``<static>true</static>`` for the same kind of reason -- a scene states where
things are, and a dynamic model would start falling the moment the world loaded
-- and that too is a parameter (``static``).

A PartCAD property SDFormat has no spelling for is reported at info level rather
than dropped in silence, the mirror image of the reader refusing to invent one.

.. note::

   "SDF" is two unrelated things in PartCAD. The ``sdf`` *part* type is a signed
   distance function. SDFormat is what this section is about, and it is called
   ``world`` everywhere in PartCAD -- the scene type, the export file type, and
   the extension of the files themselves.

Reading and writing MJCF
========================

MJCF is what MuJoCo describes a model in, and it is the third description of a
placed arrangement PartCAD reads. ``type: mjcf`` declares one, in
``assemblies:`` or in ``scenes:``, and ``pc export -t mjcf`` writes one.

It is the only one of the three that is **both** an assembly type and a scene
type, and that is not a hedge. A URDF describes one robot and a ``.world``
describes one world, so each of them reaches PartCAD as one kind of object. An
MJCF file is routinely used for both -- the same element holds a manipulator and
the table it is bolted to -- and nothing in the file says which it is. So both
types exist, one reader serves them
(``AssemblyFactoryMjcf``/``SceneFactoryMjcf``), and the package says what it
meant by declaring it in one section or the other.

The reader maps ``<worldbody>`` onto the tree the other two readers produce: a
body is a sub-assembly, a body of one geom *is* that geom named after the body,
a body of several holds one part per geom under ``<object>/<body>/<geom>``, and
every geom becomes a part of the package. Three things about MJCF are easy to
get wrong and are handled in ``mujoco_common.py`` rather than at each call site:

* **Angles are degrees by default** -- the opposite of URDF and SDFormat, which
  are radians with no way to say otherwise. ``<compiler angle="radian">`` says
  so; a file that omits the element is in degrees.
* **An orientation has five spellings** -- ``quat``, ``axisangle``, ``euler``
  (in whichever sequence ``<compiler eulerseq>`` names), ``xyaxes`` and
  ``zaxis`` -- and all five appear in real models. All five are read; only
  ``quat`` is ever written, because it is the one spelling that needs no
  ``<compiler>`` to be read back.
* **Sizes are half-sizes.** A box's ``size`` is its half-extents and a
  cylinder's is ``(radius, half-length)``, where SDFormat and URDF state the
  whole thing.

``<default>`` classes are applied (including ``childclass``), ``<include>`` is
spliced in before anything is read, and everything a static arrangement cannot
hold -- joints, actuators, tendons, sensors, lights, cameras, contacts,
keyframes -- is counted and reported exactly as the other two readers report
what they drop.

The exporter is handed the assembly tree itself (``decode: false``) for the
reason the URDF and world exporters are, and writes one ``<body>`` per node with
a ``<geom type="mesh">`` per shape. Meshes are written in millimetres and
referenced with ``scale="0.001 0.001 0.001"``, and MuJoCo reads **binary** STL
only, which is why ``ascii`` defaults to false and an ``ascii: true`` is
reported rather than quietly written.

Three of its parameters exist because a simulation needs what a scene does not
say:

``static``
   A scene states where things are, so every body is welded to the world unless
   this is turned off, which gives each of them a ``<freejoint>``. A simulation
   of a model that cannot move has nothing to report.

``flatten``
   Write every node that holds geometry as a body of the ``<worldbody>`` itself,
   at the world pose the tree puts it at, rather than nesting the bodies as the
   tree nests. A nested body with no joint above it is one rigid body with its
   parent -- right for a rigid product, wrong for a stack of blocks that is
   meant to be able to fall over.

``light`` and ``ground_plane``
   What makes the file usable rather than what the scene says, the same way the
   world exporter's ``sun`` and ``ground_plane`` are. The plane is a ``<geom>``
   of the ``<worldbody>`` itself, so it is static whatever ``static`` says.

Every description is a Jinja2 template
======================================

An ASSY file has always been rendered as a `Jinja2 <https://jinja.palletsprojects.com/>`_
template before it is parsed, which is what lets one file describe a family of
assemblies. A URDF, a ``.world`` and an MJCF model are declared exactly the same
way and were not, so a package could parameterize one kind of arrangement and
not the other three. All four share one implementation now, and the parameters
reach every one of them under the same names: ``param_<name>`` for each declared
parameter, and ``name`` for the object's own.

.. code-block:: yaml

   scenes:
     cell:
       type: mjcf
       path: cell.xml
       parameters:
         conveyor_length: 2.0

.. code-block:: xml

   <body name="conveyor">
     <geom type="box" size="{{ param_conveyor_length / 2 }} 0.3 0.05"/>
   </body>

The rendered file is written under PartCAD's own state directory rather than
beside the original -- rendering is derived data, and instantiating an object
must not drop files into the user's source tree -- and the file is left exactly
as it is when rendering changes nothing, which is the usual case. What the file
*references* keeps resolving against the directory the package declared it in:
each reader is handed that directory separately, which is what keeps a
``package://`` mesh, a ``model://`` include and an ``<asset>`` file working in a
template.

Running a simulation
====================

``simulate:`` is an optional section of a part or an assembly. Each entry in it
is one simulation, and states four things:

``scene:``
   The scene the object is placed in, by full path. The object's own full path
   is assigned to that scene's ``subject`` parameter -- unconditionally, and
   whatever else the entry says -- which is what lets one scene serve every
   object that names it. Nothing special is declared for it: a simulation scene
   is an ordinary scene with an ordinary parameter, and a Jinja2 template is
   what places the subject.

   The default is ``//builtin/scene:subject``, an empty world holding the
   subject and nothing else. A package that needs more -- a fixture to drop the
   part onto, a conveyor to push it along -- writes a scene of its own.

``offset:``
   Where in that scene the object goes, in the scene's frame. It is stated here
   rather than in the scene because it is a fact about *this* object -- where
   its origin sits relative to the floor it is meant to stand on -- and the
   scene is shared.

``simulation:``
   The simulation plugin that runs it, by full path. The default is
   ``//builtin/simulate:mujoco``.

``validation:``
   A Python expression over ``before`` and ``after`` that says whether what
   happened is what was supposed to happen.

.. code-block:: yaml

   assemblies:
     stack:
       type: assy
       simulate:
         stands:
           desc: Nothing moves, because there is no reason for anything to move
           offset: [[0, 0, 10], [0, 0, 1], 0]
           validation: |
             max(
                 abs(after["bodies"][name]["pos"][2] - before["bodies"][name]["pos"][2])
                 for name in before["bodies"]
             ) < 2.0

``pc sim`` runs them -- one object, or everything a package declares, or
everything a package tree declares with ``-r`` -- and exits non-zero when a
validation does not hold. ``--json`` prints the whole of what each plugin
reported. ``examples/feature_simulate`` is two assemblies of two blocks each,
identical but for 18 millimetres, whose simulations therefore end differently.

Simulation plugins
==================

A simulation plugin is the third kind of implementation a package can declare,
beside the export and render ones, and it is declared in exactly the same form:
a ``path`` to a script, the sandbox that script needs, and its parameters. What
differs is what it does with them. The contract is deliberately narrow:

  **a scene with the subject in it goes in, JSON carrying ``before`` and
  ``after`` comes out.**

.. code-block:: yaml

   simulation:
     mujoco:
       path: simulate_mujoco.py
       format: mjcf
       formatOptions:
         static: false
         flatten: true
       pythonRequirements:
         - mujoco>=3.2,<4
       duration: 10.0

The scene arrives as a **file**, in the format ``format:`` names, because a
simulator reads its own model format and PartCAD already knows how to write
several; ``formatOptions:`` is how that export is asked for, and is where a
physics plugin says that it wants every body free to move. That also keeps a
plugin free of OCP: it is handed a path.

``before`` and ``after`` are all PartCAD knows about a result. What is *inside*
them, and anything else beside them, is the plugin's own vocabulary -- the
MuJoCo plugin states where every body ended up, in millimetres; another might
state a temperature field -- and PartCAD neither reads nor validates it. It
carries the two objects to the ``validation:`` expression the package wrote and
reports what that says. Every judgement in that sentence belongs to the package.

The built-in plugin loads the MJCF, steps it for ``duration`` seconds of
simulated time, and reports each body's position and orientation before and
after. Running it needs no MuJoCo on the machine: the plugin runs in a PartCAD
sandbox that installs one.

Opening a scene in a simulator
==============================

``pc open --with gazebo`` hands a ``.world`` file to Gazebo, and
``pc open --with mujoco`` hands an MJCF model to MuJoCo. Both open a window on
the machine the command was run on, never through the daemon -- see
``partcad_client.external`` for why.

MuJoCo reads MJCF and no other model format, so a Gazebo world it is pointed at
is not a slow way of opening a scene, it is a file it cannot read. PartCAD
writes it out as MJCF first. That conversion is the one thing here that does
cross the wire, for the reason converting a solid into a mesh for Blender does:
it drives a CAD wrapper, whose runtime lives in the daemon's environment. An
ASSY scene is refused rather than converted -- it is nothing but references to
the parts of a package, and an ad-hoc conversion has no package to resolve them
against.

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
=========

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
  exporter computes exactly this, from the ``density`` parameter of its
  ``export:`` configuration, and throws it away afterwards - it should be a property of the part that every
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

A part carries a ``properties:`` section holding ``material``, ``color`` and
``physics``; an interface carries ``motion:`` and ``physics:``. Every property
in them is a PartCAD property with a PartCAD unit and a closed definition in the
schema. A URDF import reads its
values into them one at a time and the URDF export writes each one back into the
element that states it. The two rules that keep the list honest are the loud
failures: URDF that no property covers stops the import, and a property URDF
cannot state is reported when the file is written.

What is still missing:

- **``<ros2_control>`` and ``<transmission>``**, which are robot-level rather
  than link-level, and so have nowhere to attach yet. The assembly needs a
  place to attach robot-level physics - an assembly takes the same
  ``properties:`` section a part does, but nothing yet reads one there, because
  every property so far belongs to something inside the container.
- **Properties that are not a link's or a joint's.** A URDF's ``<gazebo>``
  blocks also carry sensors and simulator plugins, which items 7 and 8 cover;
  until then they are counted and reported, not carried.
- **Any check at all that a declared property still applies.** ``properties:``
  does not take part in the shape cache *key*, which is right - it says nothing
  about the geometry - but it also means nothing notices when the geometry moves
  out from under it. A mass read from a URDF survives an edit to the CAD that
  invalidates it, silently. ``pc lint`` is where that belongs, and it needs
  item 2 to have something to compare against.

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
