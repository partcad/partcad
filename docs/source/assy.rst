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
    connect: # alternative to "location" and "connectPorts", used to connect by interfaces
      with: <(optional) name of the interface in this part, if more than one exists>
      withInstance: <(optional) name of the instance of the interface in this part, if more than one exists>
      withPort: <(optional) name of the port in this part to connect with>
      name: <the name of the target part in this assembly to connect to>
      to: <(optional) name of the interface in the target part to connect to, if more than one compatible one exists>
      toInstance: <(optional) name of the instance of the interface in the target part to connect to, if more than one exists>
      toPort: <(optional) name of the port in the target par to connect to>

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
