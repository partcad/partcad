.. _plugins:

#######
Plugins
#######

.. toctree::
   :maxdepth: 2
   :hidden:

   importers.rst
   part_types.rst
   output.rst
   analyses.rst
   simulations.rst
   applications.rst
   repositories.rst


Most of what PartCAD can do, PartCAD does not hard-code. A **plugin** is a declaration in somebody's
``partcad.yaml`` saying which script does a job, what its sandbox needs, and what it produces -- and a
package that imports it can then use that job as if PartCAD had always had it.

That is why the list of formats PartCAD reads, the applications it opens a file in, the solvers it asks and
the simulators it runs are not fixed: each is a section a package writes, and the wheel ships few of them. A
plugin is an ordinary package, versioned and imported like any other, so **adding a capability to PartCAD is
publishing a package rather than changing PartCAD**.

A plugin's script runs in a :doc:`sandbox </maintenance/sandboxes>`, which is what lets it bring its own
dependencies -- a mesh library, a solver, a vendor's SDK -- without those reaching your package or PartCAD
itself. What it produces is cached under the environment that produced it, the way everything else is.

The seven kinds
===============

Each kind of plugin is a differently named section, and each answers a different question. Every one of them
has a chapter below.

.. list-table::
   :header-rows: 1
   :widths: 22 46 32

   * - Section
     - What it teaches PartCAD
     - Chapter
   * - ``import:``
     - how to read a file format into objects
     - :doc:`/plugins/importers`
   * - ``partTypes:``
     - how to build a part of a type the package defines
     - :doc:`/plugins/part_types`
   * - ``render:`` / ``export:``
     - how to write an output file type
     - :doc:`/plugins/output`
   * - ``cae:`` / ``cam:``
     - which analysis or toolpath implementation runs
     - :doc:`/plugins/analyses`
   * - ``simulation:``
     - which simulator runs a scene
     - :doc:`/plugins/simulations`
   * - ``open:``
     - which application opens a file, and how
     - :doc:`/plugins/applications`
   * - ``repositories:``
     - where a package's objects come from, when not a file
     - :doc:`/plugins/repositories`

They are not seven unrelated mechanisms. Five of them -- ``render:``, ``export:``, ``cae:``, ``cam:`` and
``simulation:`` -- are **the same declaration with a different name**: a ``path`` to a script, the sandbox
that script needs, and the parameters it is handed. ``partTypes:`` and ``import:`` are that declaration
again, pointed at building a shape and at reading a file. So learning one is most of learning the rest, and
the chapters say where each differs rather than repeating the shape.

What they have in common
========================

**A plugin is depended on, not installed.** There is no plugin directory, no registry to publish to and
nothing to put on a machine. You import the package that declares one, and the type, format, solver or
application it added is then spelled with that package's name in front of it:

.. code-block:: yaml

  dependencies:
    sim-mujoco:
      type: git
      url: https://github.com/partcad/partcad-sim-mujoco

  scenes:
    bench:
      type: sim-mujoco:mjcf     # the import plugin that package declares
      path: bench.xml

A bare ``type: mjcf`` resolves to nothing, and PartCAD says which package to name. That is deliberate: two
packages may each implement a format called ``mjcf``, and which one a declaration meant has to be in the
declaration.

**A relative name is resolved from where it is written.** ``calculix:fea`` inside a package means the
package *that* package imported under the name ``calculix``, however deep in a tree it sits. A name you type
on the command line is resolved from where you are standing instead. The difference matters under
``pc test -P //...``, which runs with the tree's root current while every object in it sits packages below.

**A plugin brings its own environment.** ``pythonVersion`` and ``pythonRequirements`` on the declaration
describe the sandbox its script runs in, and they are read from the package that ships the script and from
nowhere else -- so a plugin's dependencies are the plugin's problem. A plugin needing something ``pip``
cannot install names a ``dockerImage`` or a ``container:`` instead, and is handed
``request["cache_dir"]`` to keep what it downloads on first use in.

**What a plugin produces is cached like everything else**, keyed on the object's configuration and on the
environment that produced it. A script whose behaviour changes says so with a module-level
``CACHE_VERSION``, read without running the script.
