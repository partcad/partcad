#######
Plugins
#######

Most of what PartCAD can do, PartCAD does not hard-code. A **plugin** is a declaration in somebody's
``partcad.yaml`` saying which script does a job, what its sandbox needs, and what it produces -- and a
package that imports it can then use that job as if PartCAD had always had it.

That is why the list of formats PartCAD reads, the applications it opens a file in, and the simulators it
runs are not fixed: each is a section a package writes, and the wheel ships few of them. A plugin is an
ordinary package, versioned and imported like any other, so adding a capability to PartCAD is publishing a
package rather than changing PartCAD.

A plugin's script runs in a :doc:`sandbox </maintenance/sandboxes>`, which is what lets it bring its own
dependencies -- a mesh library, a solver, a vendor's SDK -- without those reaching your package or PartCAD
itself. What it produces is cached under the environment that produced it, the way everything else is.

==============
The kinds
==============

Each kind of plugin is a differently named section, and each answers a different question.

======================= ===================================================== ==========================
Section                 What it teaches PartCAD                               Documented in
======================= ===================================================== ==========================
``import:``             How to read a file format into objects                 :doc:`/plugins/importers`
``open:``               Which application opens a file, and how                :doc:`/plugins/applications`
``simulation:``         Which simulator runs a scene                           :doc:`/plugins/simulations`
``partTypes:``          How to build a part of a type the package defines      :ref:`part-types`
``render:``/``export:`` How to write an output file type                       :ref:`output-files`
``repositories:``       Where a package's objects come from, when not a file   :ref:`repositories`
``cae:``/``cam:``       Which analysis or toolpath implementation runs         :doc:`/digital_thread/workflows/analysis`, :doc:`/digital_thread/workflows/cam`
======================= ===================================================== ==========================

The first three have chapters of their own below, because they are the ones whose declaration has no other
home. The rest are documented beside the thing they produce.

=========================
Using somebody's plugin
=========================

Import the package that declares it, and use the type, format or application it added. Nothing else is
needed -- a plugin is not installed, it is depended on:

.. code-block:: yaml

  dependencies:
    sim-mujoco:
      type: git
      url: https://github.com/partcad/partcad-sim-mujoco

  scenes:
    bench:
      type: sim-mujoco:mjcf
      path: bench.xml

.. toctree::
   :maxdepth: 2

   importers.rst
   applications.rst
   simulations.rst
