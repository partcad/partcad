#####################
Assemblies and scenes
#####################

.. _assemblies:

==========
Assemblies
==========

Declare assemblies
------------------

Assemblies are defined using the ``partcad.yaml`` file in the package folder. The syntax for defining assemblies is as follows:

.. code-block:: yaml

  assemblies:
    <assembly name>:
      type: <assy|step|urdf>  # Assembly YAML, a STEP file with an assembly structure,
                              # or a URDF robot description. A format a plugin package
                              # implements is named through it: "sim-mujoco:mjcf".
      path: <(optional) the source file path>
      fileFrom: <(optional) "url" to download the source file instead of keeping it in the package>
      fileUrl: <(fileFrom=url only) the URL to download the source file from>
      parameters:  # (optional)
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>
      dependencies: # (optional) the list of filenames the caching logic checks for changes
        - <macros.j2>
        - <other.assy>
      offset: <(optional) OCCT Location object, e.g. "[[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]">
      timeout: <(optional) seconds building this assembly may take without a word, default: 300;
               also what "--fast-only" leaves it out for>

      # What this assembly contributes to every connection it takes part in.
      connect: # (optional) same as for parts
        hold: <(optional) name of an interface, or the list of them, to hold this assembly by>
        holdInstance: <(optional) instance of each interface listed in "hold", in the same order>
        holdForceMin: <(optional) least force to hold this assembly with, in N, default: 3>
        holdForceMax: <(optional) most force to hold this assembly with, in N, default: 7>
        holdForce: <(optional) sets both "holdForceMin" and "holdForceMax">

      # The ports and interfaces of the things inside it that this assembly
      # presents as its own. See "Ports and interfaces of an assembly" below.
      map: # (optional)
        <new port name>: [<node>, <port of that node>]
        <new instance name>: [<node>, <interface that node implements>, <instance of it>]
        <another port name>: [<port of this assembly's own>]
        <a name near another>: # the long form, which also moves and turns
          node: <(optional) node; without it, what is named is this assembly's own>
          port: <port>  # or "interface: <interface>" and "instance: <instance>"
          moveX: <(optional) mm along X of what is named; moveY, moveZ alike>
          turnX: <(optional) degrees about X, after the moves; turnY, turnZ alike>

      # Declared the way a part declares them, for what the map cannot say.
      implements: # (optional) the list of interfaces to implement
        <interface name>:
          <instance name>: <OCCT Location object>
          <other instance>: { port: <a port of this assembly> }
      ports: # (optional) the list of ports in addition to the inherited ones
        <port name>: <OCCT Location object>

The ``assy`` type is used to define assemblies in `Assembly YAML` format, and
the ``step`` type reads the structure out of a STEP file (see :ref:`assembly_step`).
The ``urdf`` type reads a robot description as an assembly directly
(see :doc:`simulation`). A format an engine's plugin package implements is named
through that package -- ``sim-mujoco:mjcf`` for a MuJoCo model, which is also a
:ref:`scene <scenes>` type, the section that declares it being what decides which
it is.
The ``path`` parameter specifies the source file path, and the ``parameters`` section allows for defining parameters that can be used within the assembly.
The source file does not have to be a part of the package: ``fileFrom`` and
``fileUrl`` pull it from a remote location on first use, exactly as they do for
:ref:`parts` (see :ref:`files`). This holds for every assembly type -- a vendor's
STEP assembly is declared with its URL and read from there.

``timeout`` is for an assembly that is known to be slow. PartCAD waits five
minutes for the daemon to say *something* while it works, and one large assembly
built or rendered in a sandbox can say nothing for longer than that; one that
declares ``timeout: 1800`` is waited on for half an hour instead, for as long as
it is being worked on. It never shortens the wait, and it does not change the
assembly's cache key. Declaring it also marks the assembly as slow:
``--fast-only`` leaves it out of a render, a test or a listing, which is what a
sweep over a large tree in CI wants (see :ref:`fast-only`). A scene takes the
same key.

``dependencies`` is for the files the source file pulls in by itself -- a Jinja
macro file, another ``.assy`` it includes. The parts and assemblies an ``assy``
file links to need no listing there: an assembly's cache key covers theirs, so
editing one of them rebuilds every assembly using it. The same holds for the
sketch of an ``extrude`` or ``sweep`` part, and for the assembly a ``compound``
part is made from.

.. _assembly-ports:

Ports and interfaces of an assembly
-----------------------------------

An assembly is connected to other things the way a part is: by its ports, and by
the interfaces those ports belong to (see :ref:`interfaces`). What it does not
have is a part's way of getting them. A part is one solid and says where its
ports are on it; an assembly is made of parts that already carry ports, already
placed -- and an assembly's port is one of those, seen from outside.

So an assembly does not state a coordinate somebody worked out by hand. It says
which one it means:

.. code-block:: yaml

  assemblies:
    motor-mount:
      type: assy
      map:
        # a port of a node, under a name of this assembly's choosing
        output: [bracket, TR-thru-3-opening-m3]
        # an instance of an interface a node implements, under a new instance
        # name; the interface itself is what it is
        mount: [bracket, nema-17-motor-bracket-3, outer]

The key is the new name. The value names what is being externalized: two
elements are **a node and one of its ports**, three are **a node, an interface it
implements and the instance of it**. Nothing else changes as a result: a mapped
port is a port of this assembly like any other, and a mapped interface instance
brings in exactly what an ``implements:`` of the same interface would have --
the same port names (``mount-3mm-thru-opening-m3``), the same freedom of
movement, and the same ancestors, so an assembly that externalizes an
``m4-thru-3`` can be connected as an ``m4-thru`` like anything else.

What the map does **not** do is rename an interface. The interface is read off
the node and kept: it is a contract, and an assembly is in no position to
restate one. The *instance* name is the assembly's to choose, because an
instance is a place rather than a kind -- the bracket calls it ``outer``, and the
mount it is part of calls it ``mount``.

Which nodes can be named
^^^^^^^^^^^^^^^^^^^^^^^^

The first element is the **node name from the Assembly YAML file** -- a link's
``name:``, or the part or assembly name where the link has none (see
:doc:`assy`) -- and not the name of the part. An assembly places the same part
six times; five of those are not the one being externalized.

The anonymous ``links:`` containers an ASSY file is built out of contribute
nothing to the name: they are the file's own structure rather than things, so
every node is named exactly as the file names it however deeply the file nests
it. A node inside a *named* container is reached through it, with ``/``::

  map:
    left-foot: [frame/bracket, L-30mm-slotted-3mm-thru-opening-m4]

A node name may be written in terms of the assembly's own parameters, the way
``ports:`` and ``implements:`` may be -- ``map: {mount: ["%which%", handle]}`` --
which is how an assembly parametrized by what it holds externalizes the right
one.

A sub-assembly that some package declares is a different matter: it is an object
with a boundary of its own, and the map does not reach inside it. To reach a
port in there, that sub-assembly externalizes it and this one maps *that*. A
boundary is crossed one object at a time, which is what keeps an assembly free
to be rearranged inside without breaking whatever connects to it.

What a map cannot say
^^^^^^^^^^^^^^^^^^^^^

Some of an assembly's connections are not a port of anything inside it -- the
face a fixture is clamped by, a datum the whole product is aligned to. Those are
declared the way a part declares them, with ``ports:`` and ``implements:``,
which an assembly takes in exactly the same spelling as :ref:`parts`.

The two are read in order: the map first, then ``ports:``, then ``implements:``.
So a declaration may refer to what the map produced -- an ``implements:``
instance may sit at a mapped port instead of at a coordinate:

.. code-block:: yaml

  assemblies:
    motor-mount:
      type: assy
      map:
        output: [bracket, TR-thru-3-opening-m3]
      implements:
        my-mounting-face:
          front: { port: output }   # where the map put it

A ``ports:`` entry that uses a name the map already produced wins, and says so
in the log: two things under one name is a mistake worth hearing about.

The boundary
^^^^^^^^^^^^

What an assembly externalizes is what it *has*, everywhere: ``pc info`` lists
those ports, the viewer marks them, ``pc render --with-ports`` draws them, a
``connect:`` in an ASSY file reaches them, and ``pc search --interface`` finds
the assembly by them. What is inside it and not externalized is its own
business. An assembly that declares no ``map:``, no ``ports:`` and no
``implements:`` therefore has no ports at all -- which is the answer to "what
can I connect to this", not a failure. ``pc render --with-internals`` looks
inside one anyway, for finding the connection that went wrong (see :doc:`cli`).

.. _map-own:

New names for what an object has
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

An entry with no node names something the object has of its own, and gives it a
name that says what it is for. That is what a ``map:`` is for on a part, and on
an enrich or an alias of anything: their own is what they point at, the same
geometry with the same ports. Anything else's own is what it declares in
``ports:`` and ``implements:``. In the list form that is ``[<port>]``; the long
form spells out by key what the list form says by position -- ``node``,
``port``, or ``interface`` and ``instance`` -- and is the one that can name an
interface of the object's own, since ``[<interface>, <instance>]`` would read as
a node and a port.

The long form also places the new name *near* what it names rather than on it:
``moveX``, ``moveY`` and ``moveZ`` in millimetres and ``turnX``, ``turnY`` and
``turnZ`` in degrees, in the frame of what is named -- the moves, then the
turns, the way an interface's freedom of movement is applied. A leg cut to
length from a standard post knows where its own corners are; the desk it is for
says where on it an apron goes:

.. code-block:: yaml

  parts:
    leg:
      type: enrich
      source: //pub/std/imperial/dimensional-lumber:lumber
      with: {width: 4, height: 4, length: 29.25}
      map:
        top: [y1-x0-z1]            # a corner of the post, by what it is for
        apron:
          port: x1-y1-z1
          moveY: "%-0.75 * 25.4%"  # in from the edge, and written in terms of 'with'
        apron-turned:
          port: x1-y1-z1
          turnZ: 90

An interface instance is mapped the same way, and the result is a new instance
of the same interface: ``corner: {interface: m3-thru, instance: TL, moveX: -1}``
adds ``corner`` beside ``TL``.

The names a map gives are *added* to what the object has. An enrich or an alias
of a part keeps every port and interface of what it points at, as it does
without a ``map:``, unless it declares ``ports:`` or ``implements:`` of its own
or moves the geometry with ``offset:`` -- the rule it has always followed. An
assembly, which has no ports but the ones it states, has the ones its map
names.

An entry that names a port of what an enrich or an alias points at follows
the reference's ``offset:``, since the port moves with the geometry it is on.
One that declares ``scale:`` cannot map those ports at all: where a port is on
the scaled geometry is not something a map can say, and it is reported.

Other assembly types
^^^^^^^^^^^^^^^^^^^^

``map:`` is written for ``assy``, where the node names are the ones somebody
wrote in the file. It works for ``step`` and ``urdf`` assemblies as best it can
-- the nodes are then the components or the links, named as the imported file
names them, which is not something this package controls. Where that does not
fit, those assemblies state their ports the way a part does, with ``ports:`` and
``implements:``.

.. _assembly-manufacturing:

**Manufacturing.** ``assy`` is the only manufacturing method an assembly has:
it is put together by following the instructions in its own Assembly YAML file,
rather than made the way a part is. Every assembly of type ``assy`` gets that
method with the type, so ``manufacturing`` never has to be spelled out:

.. code-block:: yaml

  assemblies:
    motor-mount:
      type: assy
      manufacturable: true
      # manufacturing: { method: assy } is implied by the type

Whether an assembly is *held to* that -- whether ``pc test`` checks that its
parts can be obtained and its connection instructions followed -- is what
``manufacturable`` says, exactly as for parts.

The optional ``offset`` parameter specifies the location of the assembly using an OCCT Location object.
See "Implementation Detail" for more information on the OCCT Location object.

Here is an example of an assembly definition:

.. code-block:: yaml

  assemblies:
    example_assembly:
      type: assy
      path: example.assy
      parameters:
        length:
          type: float
          default: 100.0
      offset: [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]

In this example, an assembly named ``example_assembly`` is defined with a parameter ``length`` and an offset.

URDF
----

The ``urdf`` type uses a `URDF <https://wiki.ros.org/urdf>`_ file - the robot
description format of ROS - as an assembly directly, with no conversion step:

.. code-block:: yaml

  assemblies:
    robot:
      type: urdf
      path: <(optional) the source file path, "<assembly name>.urdf" by default>
      ignoreCollision: <(optional) true, or a list of link names; false by default>
      packagePaths: # (optional) roots to resolve "package://" mesh references against
        - <../meshes>
      strict: <(optional) fail on an unknown "<gazebo>" setting; false by default>

``pc add assembly urdf <path>`` writes that declaration for a URDF that is
already inside the package. ``pc import assembly <path>`` is the other choice:
it converts instead of declaring, leaving the package with an ``stl`` part per
link, an interface pair per joint and an ``.assy``, exactly as
``pc convert assembly -t assy`` does below. Both commands work the way they do
for a STEP file - ``add`` points at a file, ``import`` turns one into PartCAD's
own objects.

**One part per shape, in one flat list.** A link that has a single ``<visual>``
(or ``<collision>``) becomes the part ``<assembly name>/<link name>``. A link
that has several becomes a *sub-assembly* of one part each, named
``<assembly name>/<link name>/<element name or index>``. Every link is a direct
child of the assembly, placed where the joints between it and the robot's root
link put it with **every joint at its zero position**, and each shape keeps the
offset its own ``<origin>`` gave it. The result is the same in-memory
representation an `Assembly YAML`_ file produces, so everything else -
rendering, export, BoM, inspection - treats the two alike. The assembly is the
container that holds the links, the robot's root link included; it is not one
of them and carries no properties of its own.

The joint tree deliberately does not become nesting. A URDF's tree is its
*kinematics*, and an assembly is one static configuration of it, so a link
hanging off another says nothing that the link's own placement does not already
say - while nesting per joint would make an arm as deep as it has joints. The
relative placements are not lost: they are what ``pc convert assembly -t assy``
turns into joints, below. The only nesting left is the one that means something,
a link whose several shapes group together.

Those parts are ordinary parts. ``pc ide view robot/forearm`` and
``pc export -t step robot/wrist`` work on them like on any other. They are not
declared in ``partcad.yaml`` - the URDF is what declares them - so a package
handed one of these names builds the assembly that owns it first.

**Nothing is rewritten that does not have to be.** A ``mesh`` reference becomes
a part that reads the very file the URDF named (``package://``, ``file://`` and
paths relative to the URDF file are all resolved), for the mesh formats PartCAD
reads - ``stl``, ``obj``, ``step``, ``brep`` and ``3mf``. The ``<origin>`` that
places it becomes a PartCAD location, not a transform baked into a copy of the
geometry. A mesh ``scale`` is honoured: URDF reads mesh coordinates as metres
after scaling, PartCAD works in millimetres. Only ``box``, ``cylinder`` and
``sphere`` are generated, because there is no file to point at.

A link that states both a visual and a collision shape is built from the
**collision** one: that is what a simulator resolves contact against, and a
model that bothers to state both means it to be the physical shape.
``ignoreCollision: true`` reverses that for every link, and a list of link names
reverses it for those links only.

What a link says about its physics becomes **named PartCAD properties** of the
part, one property per URDF value and in PartCAD's own units: ``<inertial>``
becomes ``mass``, ``centerOfMass`` and ``inertia``, and the friction and contact
settings of a ``<gazebo>`` block become ``friction``, ``contactStiffness`` and
the rest. Its ``<material>`` becomes ``material`` and ``color``. Nothing is
stashed under a container of its own, nothing records the link's name or its
parent - the part *is* named after the link, and the joint tree is this very
file - and URDF that PartCAD has no property for stops the import rather than
being carried opaquely. ``strict`` extends that to ``<gazebo>``, whose
vocabulary is open and where an unknown setting is otherwise only reported.

The geometry a link was *not* built from is kept too, as the part
``<assembly name>/<link name>/<visual|collision>``: defined and exportable, but
not placed in the assembly. What cannot be represented at all (joint kinematics,
transmissions, sensors) is counted and reported; ``pc info`` shows the tally.
:doc:`simulation` describes the gap and what closing it would take.

The reverse direction is ``pc export -t urdf``, which writes a ``.urdf`` file
plus a directory of the STL files it references, from any part or assembly.
Each node of the assembly tree becomes a link, each parent/child relation a
fixed joint, and a shape used more than once is written out once. What a part
states about itself is written into the URDF element that states it - the mass
and inertia into ``<inertial>``, the friction and contact properties into a
``<gazebo>`` block, the colour into ``<material>`` - and only a part that says
nothing gets inertial properties computed from its geometry. A property PartCAD
holds that URDF has no way to state is reported rather than dropped in silence
(see :doc:`simulation`).

``pc convert assembly`` goes further than exporting: it rewrites the package
around the assembly and switches its declared type.

.. code-block:: shell

  pc convert assembly -t assy robot   # urdf -> assy
  pc convert assembly -t urdf logo    # assy -> urdf

Converting to ASSY writes an ``stl`` part for every link, an interface pair for
every joint, and an ``.assy`` that places its parts with ``connect:`` rather
than with coordinates. Converting to URDF writes the ``.urdf`` and its meshes.
Neither direction has an ad-hoc equivalent: ``pc adhoc convert`` refuses both
formats, because an ASSY file is a set of references to the parts of a package
and a URDF becomes a part per link - neither means anything without one.

Assembly YAML
-------------

Here is an example of an assembly defined using `Assembly YAML`:

+---------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Configuration                                     | Result                                                                                                                  |
+===================================================+=========================================================================================================================+
| .. code-block:: yaml                              | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_assembly_assy/logo.svg?raw=true                |
|                                                   |   :width: 400                                                                                                           |
|   # partcad.yaml                                  |                                                                                                                         |
|   assemblies:                                     |                                                                                                                         |
|    logo:                                          |                                                                                                                         |
|      type: assy  # Assembly YAML                  |                                                                                                                         |
|                                                   |                                                                                                                         |
|   # logo.assy                                     |                                                                                                                         |
|   links:                                          |                                                                                                                         |
|   - part: /produce_part_cadquery_logo:bone        |                                                                                                                         |
|     location: [[0,0,0], [0,0,1], 0]               |                                                                                                                         |
|   - part: /produce_part_cadquery_logo:bone        |                                                                                                                         |
|     location: [[0,0,-2.5], [0,0,1], -90]          |                                                                                                                         |
|   - links:                                        |                                                                                                                         |
|     - part: /produce_part_cadquery_logo:head_half |                                                                                                                         |
|       name: head_half_1                           |                                                                                                                         |
|       location: [[0,0,2.5], [0,0,1], 0]           |                                                                                                                         |
|     - part: /produce_part_cadquery_logo:head_half |                                                                                                                         |
|       name: head_half_2                           |                                                                                                                         |
|       location: [[0,0,0], [0,0,1], -90]           |                                                                                                                         |
|     name: {{name}}_head                           |                                                                                                                         |
|     location: [[0,0,25], [1,0,0], 0]              |                                                                                                                         |
|   - part: /produce_part_step:bolt                 |                                                                                                                         |
|     location: [[0,0,7.5], [0,0,1], 0]             |                                                                                                                         |
+---------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+

The example above shows an assembly created using ``Assembly YAML``.
Other methods to define assemblies are coming soon (e.g. using ``CadQuery`` or ``build123d``).
The assembly file syntax is described in the ``Assembly YAML`` section of this documentation.

.. _assembly_step:

STEP
----

A STEP file that carries an assembly structure already says what an assembly
says: a tree of named components, each placed by a transform. The ``step`` type
reads it and uses it as the assembly itself, with no intermediate file:

.. code-block:: yaml

  assemblies:
    gearbox:
      type: step
      path: <(optional) the source file path, "{assembly name}.step" otherwise>
      precision: <(optional) decimal places each component's placement is rounded to, 5 by default>

``pc add assembly step <file>.step`` writes that declaration for an existing
file.

Every component of the STEP file becomes an ordinary PartCAD part, named
``<assembly name>/<component name>``. Those parts are inspected, rendered,
exported and referenced from other assemblies like any other part -- they are
simply declared by the STEP file rather than by ``partcad.yaml``:

.. code-block:: shell

  pc ide view -a :gearbox             # the assembly
  pc ide view :gearbox/output_shaft   # one component of it

A group inside the STEP file becomes a nested assembly, so the tree PartCAD
shows is the tree the CAD tool exported. Components that are the same geometry
in several places are recognized as one part placed several times, which is what
makes the bill of materials come out right.

Nothing is written into the package: the geometry PartCAD extracts for each
component is derived data and lives in PartCAD's own internal state directory.
The source file itself does not have to be in the package either -- with
``fileFrom``/``fileUrl`` (see :ref:`files`) a vendor's STEP assembly is declared
by its URL and downloaded the first time it is used:

.. code-block:: yaml

  assemblies:
    gearbox:
      type: step
      fileFrom: url
      fileUrl: https://example.com/vendor/catalog/gearbox.step

Compared to ``pc import assembly``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``pc import assembly`` reads the very same file with the very same reader, but
it is a one-shot conversion: it writes a STEP file per component and an
``Assembly YAML`` file into the package, and from then on the package owns them
and the original file is never consulted again.

Use ``type: step`` when the STEP file is to remain the source of truth: a
vendor's file, a file regenerated by another CAD tool, or a file pulled from a
URL. Every change to it is picked up on the next use, and nothing has to be
kept in sync by hand.

Use ``pc import assembly`` when the structure is to be taken over: the resulting
parts and ``.assy`` file are ordinary package content that can be renamed,
re-arranged, given interfaces and connections, or replaced part by part.

References
----------

It is also possible to declare assemblies by referencing other assemblies that are
already defined elsewhere. Both methods work the same way they do for
:ref:`parts`: an assembly takes parameters like anything else, so an assembly
with other values is another instance of the same assembly, and that is what an
``enrich`` of it asks for.

.. list-table::
  :header-rows: 1
  :widths: 10 50 40

  * - Method
    - Configuration
    - Description
  * - Alias
    - .. code-block:: yaml

        assemblies:
          <alias-name>:
            type: alias
            source: </path/to:existing-assembly>
    - Create a shallow clone of the existing assembly. For example, to make it
      easier to reference it locally.
  * - Enrich
    - .. code-block:: yaml

        assemblies:
          <enriched-assembly-name>:
            type: enrich
            source: </path/to:existing-assembly>
            with:
              <param1>: <value1>
    - Create an opinionated alternative to the existing assembly by setting
      some of its parameters, the same way a part is enriched.

Procurement
-----------

Not every assembly has to be assembled: some are sold assembled, as a kit or as
a pre-built module. Such an assembly is declared purchasable the same way a part
is (see :ref:`procurement`):

.. code-block:: yaml

  assemblies:
    <assembly name>:
      # ...
      vendor: <(optional) the name of the vendor selling the assembly>
      sku: <(optional) the vendor's stock keeping unit (SKU) of the assembly>
      count_per_sku: <(optional) the number of assemblies in one SKU, 1 by default>

``vendor``, ``sku`` and ``count_per_sku`` have the same meaning as they do for
parts, with the assembly itself being what is ordered.

.. code-block:: yaml

  assemblies:
    gearbox:
      type: assy
      vendor: gobilda
      sku: "3103-0001-0001"  # shipped assembled

An assembly that has both ``vendor`` and ``sku`` set is considered purchasable,
and is not required to declare how it is manufactured: ``pc test`` only checks
that a supplier carries it. An assembly without them is manufactured by producing
its parts and putting them together, which requires everything it is procured
from -- its parts, and the sub-assemblies that are sold assembled -- to be
obtainable by itself.

Declaring an assembly purchasable does not stop it from being modelled and
rendered as usual: the links between its parts still describe what is inside the
box.

This is also where ``pc supply find`` and ``pc supply quote`` stop looking
inside. An assembly is otherwise procured as the objects it is made of, and the
same question is asked about each sub-assembly in turn: one that is sold
assembled is ordered as a single item, and one that is not is broken down
further. Pass ``--recursive`` to order the parts even where the assembly holding
them could have been bought whole -- for example to compare the cost of building
it against the cost of buying it.

.. code-block:: shell

  # A chassis that uses the gearbox above: the gearbox is quoted as one unit,
  # and everything nobody sells assembled is quoted as the parts it is made of
  $ pc supply quote //robot:chassis

  # Quote every part of the chassis instead, the gearbox taken apart too
  $ pc supply quote --recursive //robot:chassis

An assembly embedded in the parent's own source file (the nested ``links:`` of
an Assembly YAML file) is not an object of any package, so there is no name to
order it by. Such an assembly is always procured as its contents, and declaring
a vendor for it has no effect.

.. _scenes:

======
Scenes
======

A **scene** is a placed arrangement of objects: a workcell, a table with the
parts laid out on it, a simulation world. It is built the way an assembly is,
out of the very same files, and everything that works on an assembly works on a
scene -- it renders, it exports, it has a bill of materials, ``pc ide view``
shows it.

What separates the two is intent, and one rule follows from it. An assembly is a
*product*: it says what it is made of and, through the ``how:`` section of each
``connect:``, how it is put together, which is what the
assembly instruction book (``pc render -t pdf``) is generated from. A scene
states only an end state. Nothing in it was assembled, so there is nothing to
say about the assembling, and ``how:`` is rejected rather than ignored (see
:doc:`assy`).

Declare scenes
--------------

.. code-block:: yaml

  scenes:
    <scene name>:
      type: <assy>  # Assembly YAML read as a scene. An engine's own scene format is
                    # implemented by that engine's plugin package and named through it:
                    # "sim-gazebo:world" (a Gazebo world), "sim-mujoco:mjcf" (a MuJoCo model).
      desc: <(optional) textual description>
      path: <(optional) the source file path>
      fileFrom: <(optional) "url" to download the source file instead of keeping it in the package>
      fileUrl: <(fileFrom=url only) the URL to download the source file from>
      fileHash: <the bytes to expect; required with "fileFrom", see "Files">
      parameters:  # (optional) same as for assemblies
        <param name>:
          type: <string|float|int|bool>
          default: <default value>
      dependencies: # (optional) the list of filenames the caching logic checks for changes
        - <macros.j2>
      offset: <(optional) OCCT Location object>
      manufacturable: <(optional) false by default; a scene is not a product to be made>
      gravity: <(optional) [x, y, z] in m/s^2; the engine's own, Earth's along -Z, by default>
      medium: <(optional) the material the scene is filled with; a vacuum by default>

      # 'sim-gazebo:world' only -- the reader's own parameters, declared by the
      # package that implements it and passed straight through to it
      ignoreCollision: <(optional) build a link from its visual geometry instead>
      modelPaths: <(optional) roots to resolve 'model://' references against>

The declaration points at the file that holds the scene and nothing else: there
is no assembly object in between. An ``.assy`` file in an ``assemblies:``
section is an assembly, and the very same file in a ``scenes:`` section is a
scene.

.. code-block:: yaml

  scenes:
    workcell:
      type: assy
      desc: The robot, the fixture and the bin, where they stand on the bench

    warehouse:
      type: sim-gazebo:world
      desc: A Gazebo world, used where it lies

Scenes take parameters, aliases and enriches exactly as assemblies do:

.. code-block:: yaml

  scenes:
    workcell_wide:
      type: enrich
      source: :workcell
      with:
        spacing: 900

Gravity, and the fluid a scene is filled with
---------------------------------------------

A scene is a world as well as an arrangement, and may say two things about that
world which an assembly cannot: the gravity in it, and the fluid it is filled
with.

.. code-block:: yaml

  scenes:
    tank:
      type: assy
      gravity: [0, 0, -9.81]
      medium: //pub/std/manufacturing/material/fluid:water

``gravity:`` is a vector in **m/s^2**, in the scene's own frame: ``[0, 0, -9.81]``
is Earth with Z up, ``[0, 0, -1.62]`` the Moon, ``[0, 0, 0]`` free fall. It is
SI because every physical quantity PartCAD states is SI -- only lengths and
angles are millimetres and degrees (see the note under :ref:`materials`) -- and
it is also the number every reader knows, every engine states, and the unit a
``simulate:`` passes its plugin a gravity in; see :doc:`simulation`. A scene
that states none leaves it to the engine, whose own default is Earth's along -Z.

``medium:`` names a :ref:`material <materials>`, resolved the way a part's
material is (``:brine`` is the ``brine`` this package catalogues), and its
``density`` (kg/m^3) and ``viscosity`` (Pa*s) are what a simulation drags and
buoys what moves through the scene with.
``//pub/std/manufacturing/material/fluid`` catalogues ``air``, ``water`` and
``seawater``. A scene that names none is a vacuum, which
is what every engine assumes.

Both defaults are what a scene meant before it could say either, so a scene
that says neither simulates and exports exactly as it always did. A medium that
names a material nothing answers to is an error rather than a vacuum, and
``pc info`` reports the world a scene resolved to -- the gravity and the facts of
the material it is filled with. What each engine makes of it, and what it does
not model, is in :doc:`simulation`.

Gazebo worlds
-------------

The ``sim-gazebo:world`` type reads an `SDFormat <http://sdformat.org/>`_
``.world`` file -- what Gazebo describes a simulation world in -- as a scene
directly, with no conversion step. It is declared by
`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_ rather than
by PartCAD itself, beside the exporter, the ``pc ide open`` entry and the simulator
that share their knowledge of the format, so a package that uses it imports that
package and names the type through it. Every model is placed where its ``<pose>`` puts it, every link
where its own pose puts it inside the model, and every shape becomes a part of
the package named ``<scene>/<model>/<link>``. Those parts are ordinary parts:
they can be inspected, rendered and exported on their own.

.. note::

   "SDF" means two unrelated things in PartCAD. The ``sdf`` *part* type is a
   signed distance function. This is **SDFormat**, and PartCAD calls it
   ``world`` throughout, after the files it lives in.

It is a best-effort reader: SDFormat describes a running simulation and a scene
describes where things are, so joints, lights, sensors, plugins, actors, physics
settings and the ground plane are counted and reported rather than passed over
in silence. ``pc info`` lists what was dropped. See :doc:`simulation` for the
whole picture.

The reverse direction is the ``sim-gazebo:world`` export file type, declared by
the same package:

.. code-block:: shell

  pc export -S -t sim-gazebo:world :workcell    # writes workcell.world plus its meshes

and ``pc convert scene`` moves a scene between the two formats, rewriting the
package around it:

.. code-block:: shell

  pc convert scene -t assy :warehouse                # the world's shapes become parts of the package
  pc convert scene -t sim-gazebo:world :workcell     # the scene becomes a Gazebo world file

``pc import scene -t sim-gazebo:world warehouse.world`` does the first of those
in one step for a file the package does not declare yet, leaving the package
holding PartCAD's own objects. ``pc add scene sim-gazebo:world warehouse.world``
declares the file where it lies instead.

MuJoCo models
-------------

The ``sim-mujoco:mjcf`` type reads a `MuJoCo <https://mujoco.org/>`_ model as a
scene, the same way ``sim-gazebo:world`` reads a Gazebo one. It is declared by
`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_, for the
reason the world type is declared by the Gazebo one: every body is placed where its ``pos``
and orientation put it inside the body that holds it, and every geom becomes a
part of the package named ``<scene>/<body>``.

It is the one format that is **both** a scene type and an assembly type, and
which of the two a given file is depends on the section that declares it rather
than on the file. A URDF describes one robot and a ``.world`` describes one
world; an MJCF file is used for both -- the same element holds a manipulator and
the table it is bolted to -- and nothing in it says which it is. So the package
says so:

.. code-block:: yaml

  assemblies:
    arm:
      type: sim-mujoco:mjcf
      path: arm.xml        # a product

  scenes:
    cell:
      type: sim-mujoco:mjcf
      path: cell.xml       # an arrangement

It is a best-effort reader in the same way the world reader is: joints,
actuators, tendons, sensors, lights, cameras, contacts and keyframes are counted
and reported, and ``pc info`` lists what was dropped. The reverse direction is
the ``sim-mujoco:mjcf`` export file type, which writes an ``.xml`` file plus the
meshes it references:

.. code-block:: shell

  pc export -S -t sim-mujoco:mjcf :cell     # a scene
  pc export -t sim-mujoco:mjcf :arm         # or an assembly

It is also the format ``pc sim`` hands a scene to MuJoCo in, and the one
``pc ide open --with mujoco`` expects a file to already be in; see :ref:`simulate`.
