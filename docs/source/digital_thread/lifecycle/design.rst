Design
######

.. toctree::
   :maxdepth: 2
   :hidden:

   design_3d.rst
   design_2d.rst
   design_draft.rst


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

In the UI
=========

**Design** is what the Digital Thread opens on, and it is three tabs over one
object -- the same geometry asked for three different ways. Each has a chapter
of its own:

:doc:`3D </digital_thread/lifecycle/design_3d>`
  The shape to turn, with a tree of what it is made of -- its links, its ports
  and its interfaces -- to switch on and off. The tree is the assembly's
  structure, so this is where a link placed by the wrong port shows itself. It
  is the only tab always there, and the only one an object outside any package
  has.

:doc:`2D </digital_thread/lifecycle/design_2d>`
  The object rendered to a picture by PartCAD, as ``pc render`` renders it, and
  saved from the tab. The same boxes decide what is drawn and which ports are
  drawn on it.

:doc:`Draft </digital_thread/lifecycle/design_draft>`
  A dimensioned drawing of a part or an assembly, laid out by a drawing package
  rather than by PartCAD, which the tab names.

.. image:: /images/dt-design.png
  :width: 100%
  :align: center
  :alt: The Digital Thread's Design group: its three tabs, the object tree and the 3D view

The panel is driven by whatever is selected in the PartCAD Explorer, and the
:ref:`view panel <dt-design-3d>` down its right -- the orientation gizmo, the
axis views, the sections and the viewpoint -- is shared by all three: a section
set on the 3D tab is the section the 2D and Draft tabs draw.

The editing loop runs through this group. **Edit** in the Explorer opens the
file an object *is* -- the script a part is written in, an ASSY file, a
package's ``partcad.yaml`` -- in an editor beside the panel, and **Display**
puts the result back on screen; what a save costs is only what changed, since
every answer is keyed on the files it was built from. See
:ref:`Edit <vscode-edit>` in :doc:`/tools_vscode`.


On the command line
===================

- ``pc info`` says what an object is and what it measures: its bounding box,
  volume, ports and interfaces, parameters and physical properties.
- ``pc render`` draws it -- a picture from any view, with its ports and
  interfaces drawn on, or a dimensioned drawing -- and ``pc export`` writes it in
  another format (see :ref:`output-files`). ``pc convert`` changes what the
  object *is*, by rewriting its declaration to point at the new file.
- ``pc list`` and ``pc search`` find what already exists, here or in
  :doc:`the public repository </public_repository>`, so that a part is reused
  rather than drawn again.
- ``pc ide view`` shows an object in the Digital Thread from a terminal, and
  ``pc ide open`` opens it in a CAD application on this machine.
- ``pc lint`` reads a ``partcad.yaml`` or an ASSY file as it renders and reports
  what is wrong with it before anything is built.

Agent skills
============

``/pc:gen``
  Decides whether the request is a part, an assembly or a sketch and follows the
  matching skill below. The one to use when it does not matter which it is.

``/pc:gen-part``, ``/pc:gen-assembly``, ``/pc:gen-sketch``
  Model from a description. Each validates what it wrote by rendering it -- from
  several angles, because a single projection hides whatever is behind it -- and
  comparing each view against the description it started from.

``/pc:add-interfaces``
  Adds ``interfaces``, ports and ``implements:`` to a part that has none, so it
  can be mated by connection instead of by hand-written coordinates. It works
  the positions out of the geometry and proves them twice: by drawing them on
  the part, and by mating two instances in a throwaway assembly.

``/pc:search``, ``/pc:describe``
  Find an existing object, and write a description of one from its measured size
  and its renders into the object's ``summary:``.

``/pc:render``, ``/pc:export``, ``/pc:convert``
  Produce pictures and files from what is declared.
