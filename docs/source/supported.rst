###############################
Supported formats and features
###############################

What PartCAD reads, writes and does, in one place. An item marked *(in progress)* is accepted by the
schema or planned, and not yet delivered. The :doc:`design` chapter says what each kind of object is, and
:doc:`configuration` how it is declared.

=================
Operating systems
=================

- Windows
- Linux
- macOS

=======
Caching
=======

Rendered models (OpenSCAD, CadQuery, build123d and Chili3D included) are cached:

- In memory
- On disk
- In a memcached server shared by a team or a CI fleet (``cacheRemote``)
- In an S3 bucket that outlives both (``cacheS3``)

See :ref:`caching`.

=============
Collaboration
=============

- Versioning of CAD designs using Git

  - Mechanical
  - Electronics
  - Software: firmware images, binaries and disk images shipped as objects of a package, reproducible by
    vendor and SKU, by file, or by ``fileHash``

- Automated generation of Markdown documentation
- Parametric (hardware and software) bill of materials
- Publish models online on PartCAD.org
- Publish models online on your website *(in progress)*
- Publish configurable parts and assemblies online *(in progress)*
- Purchase of assemblies and parts online, both marketplace and SaaS *(in progress)*
- Automated purchase of parts via the command line

================
Part models (3D)
================

Using scripting languages:

- `CadQuery`_
- `build123d`_
- `Chili3D`_
- `OpenSCAD`_
- `SDF`_

Using CAD files:

- STEP
- BREP
- STL
- 3MF
- OBJ
- glTF (``.gltf`` with its buffers, or ``.glb``)

Using file formats of third-party tools:

- `KiCad EDA`_ (PCB)
- FreeCAD documents (``.FCStd``), without FreeCAD: read with `cadmpeg`_, downloaded on first use

Using a part type the package defines itself (``partTypes``), including one that reads a file format of its
own:

- `SolidCraft`_ designs (``.solidcraft``), Rhino (``.3dm``) and IGES, from the SolidCraft plugin package
  (`partcad-solidcraft`_), which downloads SolidCraft on first use or runs in its own container image

==================================
Part and interface blueprints (2D)
==================================

Using scripting languages:

- `CadQuery`_
- `build123d`_

Using file formats:

- DXF
- SVG

====================
Assembly models (3D)
====================

- Using the ``Assembly YAML`` format (see :doc:`assy`)

  - Automatically maintaining the bill of materials
  - Generating user-friendly visual assembly instructions (PDF and HTML instruction books)

- Using URDF, with links, joints and physics
- Using a STEP file that stays the source
- ``pc filter`` declares a second assembly made of some of the links of an existing one: a sub-assembly
  carved out of a big one without editing it by hand

===========
Scenes (3D)
===========

Placed arrangements of objects: a workcell, a table, a simulation world.

- Stating where things are, rather than how they got there
- Reading and writing an engine's own scene format through the package that implements it:
  `partcad-sim-gazebo`_ for a Gazebo world (SDFormat), `partcad-sim-mujoco`_ for MJCF, each also declaring
  the reader, the exporter and the ``pc ide open`` entry for its engine

==========
Simulation
==========

What an object is supposed to do once the world is switched on. See :doc:`simulation`.

- ``simulate:`` on a part, an assembly or a scene: a scene, where in it the object goes, and the condition
  that says whether it went as it should
- What becomes a rigid body: every element of a scene, recursively, and everything inside an assembly
  attached to it, its connections that keep a degree of freedom joints; a scene element may be
  ``fixed: true`` to the world, and a scene may place a scene
- ``pc sim``, which runs it and validates the result
- ``pc test`` holds every object to it, as its ``sim`` check: write the claim first, then make it pass
- Simulation plugins, declared the way export and render implementations are: a scene goes in, ``before``
  and ``after`` come out. The simulator is a package, not part of the ``partcad`` wheel:
  `partcad-sim-mujoco`_ runs one in MuJoCo and `partcad-sim-gazebo`_ one in Gazebo
- ``mu`` on a material, so that what a part is made of decides whether it stands up: written out as
  SDFormat's ``<mu>``, URDF's ``<mu1>`` and MJCF's ``friction``

====================
Engineering analysis
====================

What the part does before anything is cut.

- ``pc cae fea``, finite element analysis: the part says what holds it (``fix:``) and what pulls on it
  (``load:``) in terms of its own interfaces, so the boundary conditions survive a change of geometry
- ``pc cae dynamic``, modal analysis: the natural frequencies of a part, held as it is
- ``pc cae thermal``, heat transfer: what is held at a temperature, heated and cooled
- ``pc cae cfd``, computational fluid dynamics: where the flow goes in and out, the rest a wall
- Each a map of named scenarios, as ``simulate:`` is of simulations: ``pc cae fea`` runs them all, ``-f`` one,
  and ``pc test`` holds the part to every one
- The **FEA**, **Dynamic FEA**, **Heat Transfer** and **CFD** tabs of the Digital Thread list the scenarios of
  the object on screen, and run the one selected

=========
Materials
=========

What a part is made of, as an object of a package.

- A ``materials:`` section, and standard catalogues to inherit from rather than restate:
  ``//pub/std/manufacturing/material/plastic`` and ``.../metal``, named by designation and temper
  (``al-6061-t6``, ``ss-316l``, ``ti-6al-4v``, ``petg``, ``peek``)
- Reported by ``pc info``, carried into the bill of materials, and used by simulation (``mu``) and by
  analysis

=============
Manufacturing
=============

How it gets made, and the program that makes it.

- Manufacturing methods: ``additive``, ``subtractive``, ``sheet_metal`` and ``forming``
- ``pcbBasic`` *(in progress: the schema accepts it; the manufacturability test is not implemented yet)*
- ``pc cam`` produces the route files: the object's outline offset by the cutter radius and cut at a series
  of depths, the 2.5D program a CNC router or a mill runs
- A made part is procured as the **stock it is made from**, so the bill of materials orders sheet and bar
  rather than a part nobody sells
- **Build vs Buy**: a switch per line item deciding whether it is made or bought, with the lines that can be
  neither marked ``Incomplete``; the choice is what the bill of materials and the instructions below are
  then written against
- ``pc instructions`` writes the assembly instructions as PDF or HTML: this assembly's own steps, or with
  ``-r``/``-b`` the steps of every sub-assembly built and how to make every part built, each put in just
  before the step that first needs it

=========
AI agents
=========

Tooling for AI agents doing mechanical design. See :doc:`mcp`.

- Agent Skills any ``SKILL.md``-aware coding agent can load (``ai-agents/`` in the repository), installed by
  ``pc init``, and distributed as the ``pc`` plugin for Claude Code (see :ref:`claude-plugin`)

  - Generate a part, an assembly or a 2D sketch (``/pc:gen``, ``/pc:gen-part``, ``/pc:gen-assembly``,
    ``/pc:gen-sketch``): the agent authors the CAD script and validates it by rendering
  - Describe an existing object (``/pc:describe``), search the catalog (``/pc:search``), add interfaces
    (``/pc:add-interfaces``)
  - Validate an object against its ``requirements:`` (``/pc:validate``): ``pc test`` for the ports,
    interfaces and physics it measures, and the agent's judgement of every feature from simulations,
    renders, the bill of materials and the assembly instructions
  - Set a project up (``/pc:init``, ``/pc:setup``)

- An MCP server (``pc mcp``) any MCP client can drive PartCAD through: list, inspect, render (as an image),
  test and export objects, and every other daemon method behind one ``execute`` tool. It is in the MCP
  Registry, in the ``pc`` plugin, registered by the VS Code extension and written into new packages by
  ``pc init``
- ``--no-ansi`` output on every command, so an agent parses plain text rather than progress bars
- Free-form ``comment:`` context in ``Assembly YAML``, written for whoever reads the assembly next

==================
The Digital Thread
==================

- Object-Oriented Programming approach to maintaining part interfaces and mating information
- Live preview of 3D models while working in Visual Studio Code, with the requirements an object declares
  and whether ``pc test`` finds them met, 2D renders, dimensioned drawings, engineering analysis, the
  build-or-buy decision, the bill of materials, the assembly instructions and supplier quotes on tabs beside
  the 3D view, and a software fallback that still draws the model in a window with no WebGL, such as a
  virtual machine or a remote desktop (see :doc:`features`)
- Open an object in the application that made it (``pc ide open``): FreeCAD, Blender, KiCad, and Gazebo or
  MuJoCo from the plugin package for that engine, SolidCraft from its plugin package. Installed locally, or
  run in a container when it is not; an object the application cannot read is converted on the way, and
  what is edited there is brought back into the object's own file when it closes
- Ask the IDE what it is showing (``pc ide state``): the Explorer's selection, the Inspector's parameters,
  and the Digital Thread's tab, filters and a screenshot, for an AI agent working beside you to look at what
  you see

=======
Outputs
=======

2D projections, from any viewing angle (``--view``, or an arbitrary one), with the connection ports and
interfaces drawn on top if asked:

- SVG
- PNG
- JPEG
- DXF

Documents:

- Markdown package and assembly documents
- PDF and HTML assembly instruction books

3D models exported to CAD files:

- STEP
- BREP
- STL
- 3MF
- ThreeJS
- OBJ
- IGES
- glTF
- URDF
- Gazebo world (SDFormat) and MJCF (MuJoCo), from the plugin package for that engine
- `SolidCraft`_ designs (``.solidcraft``), from the SolidCraft plugin package

Output types a package implements itself, for both ``render:`` and ``export:``. See :doc:`config_output`.

.. _CadQuery: https://github.com/CadQuery/cadquery
.. _build123d: https://github.com/gumyr/build123d
.. _Chili3D: https://github.com/xiangechen/chili3d
.. _OpenSCAD: https://openscad.org/
.. _SDF: https://github.com/fogleman/sdf
.. _KiCad EDA: https://www.kicad.org/
.. _cadmpeg: https://github.com/cadmpeg/cadmpeg
.. _SolidCraft: https://github.com/bherbruck/solidcraft
.. _partcad-solidcraft: https://github.com/partcad/partcad-solidcraft
.. _partcad-sim-gazebo: https://github.com/partcad/partcad-sim-gazebo
.. _partcad-sim-mujoco: https://github.com/partcad/partcad-sim-mujoco
