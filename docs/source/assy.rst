Assembly YAML
#############

============
Introduction
============

Assembly YAML is an approach to define assemblies using a simple YAML file.
This file format was introduced in PartCAD for the first time.

======
Syntax
======

Each Assembly YAML (ASSY) file is a YAML file consisting of a tree of nodes.
Each node is either a reference to an external part, a reference to an
external assembly, or a container for such references.

Containers
----------

The top-level node of an ASSY file is a container node.
The container nodes have the following syntax:

  .. code-block:: yaml

    name: <(optional) name>
    description: <(optional) description>
    location: <(optional) OCCT Location object> # e.g. [[0,0,0], [0,0,1], 0]
    links:
      - <other node>
      - <other node>
      - <other node>
      - <other node>

Parts
-----

The following syntax is used to create a node that places a part in the assembly:

  .. code-block:: yaml

    part: <name of a part from this package or a global path "{/package}:{part}">
    name: <(optional) name to use for this part in this assembly>
    location: <(optional) OCCT Location object> # e.g. [[0,0,0], [0,0,1], 0]
    connectPorts: # alternative to "location", used to connect by ports
      with: <(optional) name of the port in this part, if more than one exists>
      name: <the name of the target part in this assembly to connect to>
      to: <(optional) name of the port in the target part to connect to, if more than one exists>
      comment: <(optional) free form text, see "Comment" below>
      how: <(optional) assembly instructions, see "How" below>
      exploded: <(optional) the gap to show in the exploded view of this step, in mm>
    connect: # alternative to "location" and "connectPorts", used to connect by interfaces
      with: <(optional) name of the interface in this part, if more than one exists>
      withInstance: <(optional) name of the instance of the interface in this part, if more than one exists>
      withPort: <(optional) name of the port in this part to connect with>
      name: <the name of the target part in this assembly to connect to>
      to: <(optional) name of the interface in the target part to connect to, if more than one compatible one exists>
      toInstance: <(optional) name of the instance of the interface in the target part to connect to, if more than one exists>
      toPort: <(optional) name of the port in the target par to connect to>
      comment: <(optional) free form text, see "Comment" below>
      how: <(optional) assembly instructions, see "How" below>
      exploded: <(optional) the gap to show in the exploded view of this step, in mm>

One and only one method for placing the object is acceptable.
Therefore the sections `location`, `connectPorts` and `connect` are mutually exclusive.
Both `connectPorts` and `connect` are used to connect parts to each other by matching their ports.
`connect` is universal, while `connectPorts` is specific to connecting with ports and without interface mating.

The `with` and `to` fields are used to specify the names of interfaces.
Where `with` is the interface of the part that is getting added to the assembly,
and `to` is the interface of the part that is already in the assembly.
The `withInstance` and `toInstance` fields are used to specify the names of interface instances.
The `withPort` and `toPort` fields are used to specify the names of ports.

The `exploded` field does not affect the assembly itself: it is how far apart
the two parts are drawn in the exploded view of this step in the assembly
instruction book (`pc render -t pdf` and `pc render -t html`).
Without it, the two are spaced by half of the largest dimension of the two.

Assemblies
----------

The following syntax is used to create a node that places an assembly in the assembly:

  .. code-block:: yaml

    assembly: <name of an assembly from this package or a global path "{/package}:{assembly}">
    ... # same as for parts

Comment
-------

The `comment` field of a `connect` or `connectPorts` section is free form text.

  .. code-block:: yaml

    connect:
      name: example-bracket
      comment: |
        The motor is easier to align if the bracket is laid face down first.

It is supplementary context for a human, or for an LLM, that is reading the
assembly. PartCAD never parses it and never acts upon it.

.. warning::

   `comment` is **not** a place for assembly instructions.
   Everything that is required to perform the assembly must be codified in the
   other ASSY fields, so that the tools that consume the assembly - and not just
   the people reading it - have the complete picture.
   Anything stated only in `comment` is invisible to them.

How
---

The `how` field of a `connect` or `connectPorts` section describes how the
object is expected to be brought into place. All of its fields are optional,
and so is the section itself: an omitted field means the default below.

  .. code-block:: yaml

    how:
      stage: <(optional) name of the group of steps performed at the same time>
      pushForceMax: <(optional) maximum linear force, in N, default: 5>
      pushDistance: <(optional) staging distance, in mm, derived from the object by default>
      turnDirection: <(optional) "cw" (clockwise) or "ccw" (counterclockwise), default: "cw">
      turnTorqueMax: <(optional) maximum torque, in N*m, default: 0>
      threadStep: <(optional) axial distance per full turn, in mm, default: 0.00>
      holdWith: <(optional) interface, or list of interfaces, to hold this object by>
      holdWithInstance: <(optional) instance of each interface listed in "holdWith">
      holdWithForceMin: <(optional) least force to hold this object with, in N, default: 3>
      holdWithForceMax: <(optional) most force to hold this object with, in N, default: 7>
      holdWithForce: <(optional) sets both "holdWithForceMin" and "holdWithForceMax">
      holdTo: <(optional) interface, or list of interfaces, to hold the target object by>
      holdToInstance: <(optional) instance of each interface listed in "holdTo">
      holdToForceMin: <(optional) least force to hold the target object with, in N, default: 3>
      holdToForceMax: <(optional) most force to hold the target object with, in N, default: 7>
      holdToForce: <(optional) sets both "holdToForceMin" and "holdToForceMax">

The units are SI, with the exception of lengths, which are in millimetres like
everywhere else in PartCAD:

+-------------------------+------------------------+-----------------------------------------+
| Field                   | Quantity               | Unit                                    |
+=========================+========================+=========================================+
| ``pushForceMax``        | force                  | ``N`` (newton)                          |
+-------------------------+------------------------+-----------------------------------------+
| ``pushDistance``        | length                 | ``mm`` (millimetre)                     |
+-------------------------+------------------------+-----------------------------------------+
| ``turnTorqueMax``       | torque                 | ``N*m`` (newton-metre)                  |
+-------------------------+------------------------+-----------------------------------------+
| ``threadStep``          | length                 | ``mm`` (millimetre)                     |
+-------------------------+------------------------+-----------------------------------------+
| ``hold*Force``          | force                  | ``N`` (newton)                          |
| ``hold*ForceMin``       |                        |                                         |
| ``hold*ForceMax``       |                        |                                         |
+-------------------------+------------------------+-----------------------------------------+

Pushing an object into place is a linear motion, so ``pushForceMax`` bounds a
**force** in newtons. Turning it is a rotation, so ``turnTorqueMax`` bounds a
**torque** in newton-metres.

.. note::

   ``pushForceMax`` was called ``pushTorqueMax`` in the first draft of this
   section. The old spelling is still accepted, with a warning, and means the
   same thing.

`threadStep` is the **lead**: the axial distance the object advances per full
turn. For a multi-start thread that is the pitch multiplied by the number of
starts, not the pitch itself.
When it is non-zero, the assembler manages the pushing force and the turning
torque together, so that the resulting motion reproduces the given thread (or,
more generally, rotation) pattern, staying within `pushForceMax` and
`turnTorqueMax`. The default of `0.00` means a straight push with no turning.

A thread belongs to the interfaces rather than to any one connection, so it is
normally declared there and left out here - see :ref:`interface-thread` below.
Given on a connection, it overrides what the interfaces say for that one step.

`pushDirection` is not a field: it is deduced from the connection itself and
reported alongside the rest. It is the direction, in the assembly's
coordinates, that the object travels while it is pushed into place - so the
object starts at `pushDistance` back along it.

The interfaces are what it is deduced from. The positive Z axis of an interface
points **into** the object the interface belongs to, which is exactly the way a
part coming to meet it has to travel. `examples/feature_interface` shows this
directly: both faces of the same 3mm bracket are instances of one interface,
the ``outer`` one at ``z=0`` unrotated and the ``inner`` one at ``z=3`` turned
around, so the two axes point at each other through the material. Each of the
four M3 screws in that example is connected to one of those faces, and its
deduced direction points from the screw through the bracket towards the motor -
reversing, as it must, when the motor is placed on the other side.

`pushDistance` is how far away from its final place the object starts: the
distance, along `pushDirection`, between the staging pose and the pose where
its `with` ports coincide with the target's `to` ports.
When it is omitted, it is derived from the object being connected, as **1.5
times that object's own length along the Z axis of the interface location** it
is connected by - far enough for the object to clear the target before the
insertion move begins. That measurement needs the object's geometry, so it is
made only when something asks for it, never while the assembly is merely being
instantiated. If the geometry cannot be built at all, the distance is reported
as unset rather than guessed.

`stage` names a group of steps that are expected to be connected **at the same
time** rather than one after another: consecutive nodes carrying the same
`stage` form one such group.
It is a free-form label, so it can say what the group is for.
A `stage` that is interrupted by another one and then resumes is reported, since
the steps it names are then not consecutive and will not be performed together.

  .. code-block:: yaml

    links:
      - part: example-bracket

      # Both screws are snugged at the same time, not one after the other.
      - part: socket-head-m3-screw-6mm
        name: screw-tl
        connect:
          name: example-bracket
          to: m3-thru-3
          toInstance: outer-TL
          how: { stage: snug, turnTorqueMax: 0.2 }
      - part: socket-head-m3-screw-6mm
        name: screw-br
        connect:
          name: example-bracket
          to: m3-thru-3
          toInstance: outer-BR
          how: { stage: snug, turnTorqueMax: 0.2 }

`holdWith` names the interface of the object that is getting added to the
assembly, to be used to hold that object while it is connected.
`holdTo` names the interface of the object that is already in the assembly,
which is held the same way.
Either may be a single interface name or a list of them.

  .. code-block:: yaml

    - part: socket-head-m3-screw-6mm
      connect:
        name: example-bracket
        to: m3-thru-3
        toInstance: outer-TL
        comment: Tighten this screw last, once the other three are started.
        how:
          turnTorqueMax: 1.2
          threadStep: 0.5
          holdWith: m3-screw-6mm
          holdTo: nema-17-motor-bracket-3
          holdToInstance: outer

When `holdWith` is omitted, it defaults to the `hold` field of the `connect`
section of the part or the assembly being added (see :ref:`hold`). When `holdTo`
is omitted, it defaults to the `hold` field of the object being connected to. When neither is set, the
assembler is free to hold the object however it sees fit.

`holdWithInstance` and `holdToInstance` select which instance of the interface
to hold by, for the cases where the object implements more than one instance of
it. They are matched positionally against `holdWith` and `holdTo`. When omitted,
the instance defaults to the `holdInstance` field of that same section, and,
failing that, to the first instance of the interface.

`holdWithForceMin` and `holdWithForceMax` bound the force each end is held
with, in newtons - enough to keep the object from moving, not so much as to
damage it. `holdWithForce` sets both at once, and `holdToForce*` are the same
for the object being connected to. Each bound is resolved on its own, from the
first of these that gives it:

1. the bound itself, `holdWithForceMin` or `holdWithForceMax`;
2. `holdWithForce`, which sets both;
3. the `holdForceMin`/`holdForceMax` field of the `connect` section of the part
   or the assembly (see :ref:`hold`);
4. the `holdForce` field of that same section, which sets both;
5. the defaults, **3 N** for the minimum and **7 N** for the maximum.

A minimum that ends up above its maximum is a contradiction rather than a
range: it is reported, and both bounds fall back to the defaults.

.. _interface-thread:

The thread of an interface
--------------------------

An interface may declare the thread that connections made through it advance
along, and whether it cuts its own:

  .. code-block:: yaml

    interfaces:
      m3:
        abstract: True
        threadStep: <(optional) axial distance per full turn, in mm>
        selfScrew: <(optional) whether this interface cuts its own thread, default: false>

Both are inherited by the interfaces that inherit this one, so a thread is
spelled out once, on the interface that introduces it. In
`examples/feature_interface` the abstract `m3` interface carries `0.5` and the
abstract `m4` carries `0.7` - the real pitches of those screws - and every
opening, screw and hole pattern derived from them connects with the right
thread without repeating it.

A connection inherits `threadStep` from the two interfaces it mates. They have
to agree on it: two different threads cannot be screwed together, and a
connection whose ends disagree is reported and fails ``pc test``. Unless, that
is, one of them declares `selfScrew` - a self-tapping screw, or the plain hole
one goes into. Then the thread of the end that does have to match one is the
thread that gets cut, and failing that the one the self-tapping end brings with
it.

Reading the instructions back
-----------------------------

Everything resolved from the sections above - the inherited threads, the
deduced push direction, the forces each end is held with - is reported by

.. code-block:: shell

    pc info -a <assembly>

under ``Connections``, one entry per connected object. That is the assembly's
own account of how it is built, for a person or for whatever performs it.

Testing the instructions
------------------------

Everything above is resolved leniently: a field that is missing takes its
default, and one that contradicts itself is reported and replaced with a
default, so that an assembly always builds. ``pc test`` is what looks past that
leniency. Its ``connect`` test fails an assembly whose instructions had to be
repaired to be usable, and passes one that is sound - **including one that says
nothing at all** and takes every default.

What it rejects today:

* a ``*Min`` above its corresponding ``*Max`` - ``holdWithForceMin`` above
  ``holdWithForceMax``, or ``holdToForceMin`` above ``holdToForceMax``. A
  minimum above a maximum is a contradiction rather than a range.
* two interfaces that disagree about their `threadStep` with neither declaring
  `selfScrew`.

.. code-block:: shell

    pc test -a connect-instructions

.. _hold:

Holding an object
-----------------

The defaults for the `how` fields above are declared once, next to the part or
the assembly itself, in `partcad.yaml`:

  .. code-block:: yaml

    parts:
      example-bracket:
        type: step
        connect: # (optional)
          hold: <(optional) interface, or list of interfaces, to hold this part by>
          holdInstance: <(optional) instance of each interface listed in "hold">
          holdForceMin: <(optional) least force to hold this part with, in N>
          holdForceMax: <(optional) most force to hold this part with, in N>
          holdForce: <(optional) sets both "holdForceMin" and "holdForceMax">

    assemblies:
      motor-mount:
        type: assy
        connect: # (optional) same as for parts
          hold: <...>

Everything an object contributes to every connection it takes part in lives in
that one `connect` section, rather than among the fields that describe the
object itself.

==========
Validation
==========

ASSY files are checked against a JSON schema
(``partcad-utils/src/partcad_utils/schema/assy.json``) that describes the
document *after* Jinja2 rendering: the node keys above, the shape of an OCCT
location, and the fact that ``location``, ``connectPorts`` and ``connect`` -- or
``part``, ``assembly`` and ``links`` -- exclude one another.

Because the file on disk is a template rather than the YAML it renders to, the
checker masks every Jinja2 construct before parsing: ``{{ expr }}`` becomes a
placeholder value and ``{% tag %}`` becomes blanks of the same size. The masked
document keeps the exact line and column layout of the file, so a template
error, a YAML error and a schema violation are all reported at the character
they came from, and a loop or conditional body is checked once. Anything the
mask makes unknowable -- what an expression evaluates to, which branch of an
``{% if %}`` is taken -- is left unreported rather than guessed at.

Run the checks over a package from the command line with:

  .. code-block:: shell

    pc lint

or narrow it to ASSY files only:

  .. code-block:: shell

    pc lint -f AssySchema

To check individual files instead, name them. This runs in the ``pc`` process
itself -- no daemon, no package to load -- so it answers even when the package
does not:

  .. code-block:: shell

    pc lint --file logo.assy --file desk.assy

Add ``--json`` for machine-readable findings (zero-based line and column
numbers), and ``--stdin`` to check content that has not been saved, which is how
an editor checks the buffer on screen:

  .. code-block:: shell

    pc lint --file logo.assy --stdin --json < draft.assy

The `PartCAD extension for VS Code <https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad>`_
runs exactly that while an ASSY file is open and shows the findings in the
Problems view. Set ``partcad.lint.enabled`` to ``false`` to turn that off.
