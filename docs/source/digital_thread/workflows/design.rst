Design
######

Design is what the object *is*: its geometry, the numbers it is built from, and
how it connects to the objects around it. In PartCAD a design is not a drawing
anybody makes by hand but a declaration a program builds -- so it can be
rebuilt, varied, reviewed as a diff, and asked questions of by every other phase.

What PartCAD captures
=====================

Objects
-------

:ref:`Sketches <sketches>`
  Two-dimensional shapes: basic outlines, DXF and SVG files, scripts. What a
  part is extruded or swept from, and what the boundary of a port is drawn with.

:ref:`Interfaces <interfaces>`
  How objects connect: a named set of ports, implemented by parts and
  assemblies, inherited from more general interfaces, and mated with the
  interfaces they fit. An M3 through hole is an interface; so is a LEGO stud.

:ref:`Parts <parts>`
  A solid, built by a script (CadQuery, build123d, OpenSCAD, ...) or read from a
  file (STEP, BREP, STL, ...), with :ref:`parameters <parameters>` that vary it
  and ports where other objects attach (see :ref:`part-types`).

:ref:`Assemblies <assemblies>`
  Parts and other assemblies put together: each link placed by connecting one of
  its ports to a port of something already placed rather than by coordinates
  where it can be, so that the assembly says what holds each item and moves when
  its parts change (see :doc:`/assy` and :ref:`joints`).

:ref:`Scenes <scenes>`
  Where assemblies are placed in a world -- the floor a robot stands on, the
  slope a simulation tilts it on. A scene is not something anybody makes.

Properties
----------

What an object is made of (:ref:`materials`), what it is called by whoever sells
it, its colour, and any other :ref:`properties <properties>` -- read by the
phases after this one rather than by the geometry.

Reuse
-----

An object is used by name, from its own package or from any package imported:
``//pub/std/metric/m3:m3-thru`` is the same interface wherever it is used. A
file fetched from elsewhere is pinned with its hash, so that the design says
exactly which bytes it was built from (see :ref:`reproducibility`).

Working on a design
===================

- ``pc info`` says what an object is and what it measures: its bounding box,
  volume, ports and interfaces, parameters and physical properties.
- ``pc render`` draws it -- a picture from any view, with its ports and interfaces
  drawn on, or a dimensioned drawing -- and ``pc export`` writes it in another
  format (see :ref:`output-files`).
- ``pc ide view`` shows it in the Digital Thread; ``pc ide open`` opens it in a
  CAD application on this machine.
- The agent skills write and change designs: ``/pc:gen-part``,
  ``/pc:gen-assembly`` and ``/pc:gen-sketch`` model from a description,
  ``/pc:add-interfaces`` adds the ports another object will connect to, and
  ``/pc:describe`` and ``/pc:render`` look at what is there.

In the Digital Thread
=====================

**Design** is what the panel opens on, and has three tabs:

- **3D**: the object to turn, with a tree of what it is made of -- its links,
  ports and interfaces -- to switch on and off.
- **2D**: the object rendered to a picture by PartCAD, as ``pc render`` would,
  with the same boxes deciding what is drawn and which ports are drawn on it.
- **Draft**: a dimensioned drawing of a part or an assembly.
