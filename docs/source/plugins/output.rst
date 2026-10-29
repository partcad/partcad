#################
Output file types
#################

An **output plugin** teaches PartCAD to write a file. ``pc export`` writes 3D
and CAD files, ``pc render`` writes 2D projections, and which file types either
of them knows is an ``export:`` or a ``render:`` section -- one subsection per
file type, each naming the script that writes it and the sandbox that script
needs.

PartCAD ships implementations for the formats everybody uses (STEP, BREP, STL,
3MF, OBJ, IGES, glTF, three.js, PNG, SVG, DXF, ...), so a package usually writes
these sections only to **configure** a built-in type -- where its files go, at
what resolution, from which viewpoint. Declaring a ``path`` is what turns the
same section into a plugin.

:ref:`output-files` is the reference for every field and for how the two
sections fall back on each other. This chapter is about the plugin case.

What an output type is for
==========================

- **A format PartCAD does not write** -- a vendor's exchange format, a simulator's
  scene file, a format with a license PartCAD cannot carry.
- **A document rather than a shape**: a report, a label, a cut list, a packing
  slip. Anything a command can be asked to write for an object is a render type.
- **The other half of an** :doc:`importer </plugins/importers>`. Reading a
  format and writing it are one piece of knowledge, so the package that declares
  the reader declares the writer beside it, and ``pc convert`` then moves
  objects between the two.
- **A dialect of a format PartCAD already writes**, where a particular
  downstream tool wants something specific.

Using one
=========

Import the package and name the type, with that package's name in front of it:

.. code-block:: shell

  pc export -t sim-mujoco:mjcf :cell      # a scene, as a MuJoCo model
  pc render -t svg :bracket               # a built-in type

A type can also be declared for an object so that it is produced whenever the
object is, with its own parameters -- which is the usual way to use one:

.. code-block:: yaml

  parts:
    panel:
      render:
        sim-mujoco:mjcf:
          prefix: models/

Writing one
===========

.. code-block:: yaml

  export:
    demo:
      path: write_demo.py          # the script that writes the file
      package: <(optional) the package holding it, when not this one>
      extension: demo              # used when the file name is derived
      prefix: <(optional) where the file goes, relative to the package>
      exclude: <(optional) kinds of object not to write this type for>
      reproducible: <(optional) true to require the same bytes every time>
      pythonVersion: <(optional) the sandbox interpreter>
      pythonRequirements:          # what that sandbox needs
        - trimesh==4.5.3
      precision: 6                 # anything else is a parameter of this type

**Which section to declare it in is a promise, not a detail.** An ``export:``
type promises geometry another tool can go on working with; a ``render:`` type
promises an output file and nothing more. A drawing, a picture or a report is the
latter -- declare it under ``render:``, where it stays reachable from both
commands, rather than under ``export:``, where it would promise a part it cannot
deliver.

Two fields are worth dwelling on:

``reproducible``
  Whether the same object has to produce the same bytes every time. It is
  ``false`` by default because the reproducible path is often the slower one;
  every drawing checked in under ``examples/`` sets it, because a checked-in
  file that changes on every run is a diff rather than a baseline. See
  ``output.REPRODUCIBLE_KEY``.

``exclude``
  The object kinds this type is not written for. A sketch has no business being
  exported as an STL, and saying so once here is better than failing per object.

An example
==========

`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ and
`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_ are the
pair to read. Each declares, for one format, all four of the plugins that format
needs: the :doc:`importer </plugins/importers>` that reads it, the output type
that writes it, the :doc:`application entry </plugins/applications>` that opens
it, and the :doc:`simulation plugin </plugins/simulations>` that runs it.

That is the point of the example rather than an accident of packaging. The
export is what the simulator is handed its scene through, so the two cannot
disagree about the format; and because the exporter for a simulation plugin's
``format:`` is looked up in the plugin's own package as well as in the scene's,
a plugin **implements the format it reads**:

.. code-block:: shell

  pc export -t sim-gazebo:world :workcell    # writes workcell.world plus its meshes
  pc export -t sim-mujoco:mjcf :cell         # a scene
  pc export -t sim-mujoco:mjcf :arm          # or an assembly

A package that re-tunes that export for its own scenes still wins over the
plugin's own declaration, which is what ``formatOptions:`` on the simulation
declaration is for: a physics run wants every body free to move, the opposite of
what a scene means on its own.
