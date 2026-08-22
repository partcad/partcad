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
      exploded: <(optional) the gap to show in the exploded view of this step, in mm>
    connect: # alternative to "location" and "connectPorts", used to connect by interfaces
      with: <(optional) name of the interface in this part, if more than one exists>
      withInstance: <(optional) name of the instance of the interface in this part, if more than one exists>
      withPort: <(optional) name of the port in this part to connect with>
      name: <the name of the target part in this assembly to connect to>
      to: <(optional) name of the interface in the target part to connect to, if more than one compatible one exists>
      toInstance: <(optional) name of the instance of the interface in the target part to connect to, if more than one exists>
      toPort: <(optional) name of the port in the target par to connect to>
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
