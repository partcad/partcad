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

One and only one method for placing the object is acceptable.
Therefore the sections `location`, `connectPorts` and `connect` are mutually exclusive.
Both `connectPorts` and `connect` are used to connect parts to each other by matching their ports.
`connect` is universal, while `connectPorts` is specific to connecting with ports and without interface mating.

The `with` and `to` fields are used to specify the names of interfaces.
Where `with` is the interface of the part that is getting added to the assembly,
and `to` is the interface of the part that is already in the assembly.
The `withInstance` and `toInstance` fields are used to specify the names of interface instances.
The `withPort` and `toPort` fields are used to specify the names of ports.

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
      pushForceMax: <(optional) maximum linear force, in N, default: 5>
      turnDirection: <(optional) "cw" (clockwise) or "ccw" (counterclockwise), default: "cw">
      turnTorqueMax: <(optional) maximum torque, in N*m, default: 0>
      threadStep: <(optional) axial distance per full turn, in mm, default: 0.00>
      holdWith: <(optional) interface, or list of interfaces, to hold this object by>
      holdWithInstance: <(optional) instance of each interface listed in "holdWith">
      holdTo: <(optional) interface, or list of interfaces, to hold the target object by>
      holdToInstance: <(optional) instance of each interface listed in "holdTo">

The units are SI, with the exception of lengths, which are in millimetres like
everywhere else in PartCAD:

+--------------------+------------------------+-----------------------------------------+
| Field              | Quantity               | Unit                                    |
+====================+========================+=========================================+
| ``pushForceMax``   | force                  | ``N`` (newton)                          |
+--------------------+------------------------+-----------------------------------------+
| ``turnTorqueMax``  | torque                 | ``N*m`` (newton-metre)                  |
+--------------------+------------------------+-----------------------------------------+
| ``threadStep``     | length                 | ``mm`` (millimetre)                     |
+--------------------+------------------------+-----------------------------------------+

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

When `holdWith` is omitted, it defaults to the `hold` field of the part or the
assembly being added (see :ref:`hold`). When `holdTo` is omitted, it defaults to
the `hold` field of the object being connected to. When neither is set, the
assembler is free to hold the object however it sees fit.

`holdWithInstance` and `holdToInstance` select which instance of the interface
to hold by, for the cases where the object implements more than one instance of
it. They are matched positionally against `holdWith` and `holdTo`. When omitted,
the instance defaults to the `holdInstance` field of the part or the assembly,
and, failing that, to the first instance of the interface.

.. _hold:

Holding an object
-----------------

The defaults for the `how` fields above are declared once, next to the part or
the assembly itself, in `partcad.yaml`:

  .. code-block:: yaml

    parts:
      example-bracket:
        type: step
        hold: <(optional) interface, or list of interfaces, to hold this part by>
        holdInstance: <(optional) instance of each interface listed in "hold">

    assemblies:
      motor-mount:
        type: assy
        hold: <(optional) same as for parts>
        holdInstance: <(optional) same as for parts>
