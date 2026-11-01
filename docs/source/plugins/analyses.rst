#######################
Analyses and toolpaths
#######################

``cae:`` and ``cam:`` are two more sections of the same shape as
:doc:`an output type </plugins/output>` -- a ``path`` to a script, the sandbox it
needs, and the parameters it is handed -- and they are where **an engineering
analysis** and **a machine route** are implemented.

They are the two kinds of plugin where the *question* lives on the object and
only the *answer* lives in the plugin. A part says what holds it, what it
carries and how it is heated, in an ``fea:``, ``dynamic:``, ``thermal:`` or
``cfd:`` section; it says what is cut out of it in its ``manufacturing:``
section. Those are properties of the part rather than of whoever is asked about
it -- a bracket is bolted down at the same holes whichever solver runs, and a
panel is 18 mm thick whichever router cuts it -- so the plugin supplies the
solver and never the conditions.

What they are for
=================

``cae:`` -- analyses
  Structural analysis (``fea``), the frequencies a part rings at (``dynamic``),
  heat transfer (``thermal``) and fluid flow (``cfd``). A plugin wraps a solver
  and a mesher and reports **findings**: what it has to say about the part.

``cam:`` -- toolpaths
  The program a machine cuts the part with. A plugin wraps a post-processor for
  a controller that wants a dialect of its own.

The reason both are plugins is the same: a solver is somebody's program with a
release cycle, a licence and an install procedure of its own, and a controller
dialect is somebody's firmware. PartCAD ships the concept -- the sections, the
sandbox, the scenarios, the caching, the checks -- and a package supplies the
program.

Using one
=========

**For an analysis**, PartCAD ships no implementation, so one has to be named.
The user configuration option for each analysis says which package and file type
runs it by default -- ``caeFeaImplementation``, ``caeDynamicImplementation``,
``caeThermalImplementation``, ``caeCfdImplementation``:

.. code-block:: shell

  pc cae fea :bracket                                   # every scenario
  pc cae fea -f loaded :bracket                          # one of them
  pc cae fea -i //pub/feature/cae/calculix:fea :bracket   # a different implementation, this run

A scenario may also name its own with ``implementation:``, which is how a
package ships an analysis that works for whoever opens it. The order is: ``-i``
on the command line, then the scenario, then the user configuration.

**For a route**, PartCAD *does* ship one -- ``//builtin/cam`` writes G-code, and
``camImplementation`` names it by default:

.. code-block:: shell

  pc cam                      # every object of the package that declares a route
  pc cam :panel               # one object
  pc cam -i vendor:grbl :panel # somebody's dialect

:doc:`/digital_thread/lifecycle/analysis` and
:ref:`machine routes <cam-routes>` are the chapters on using these; the list of
solver packages there is the list of plugins that exist.

Writing one
===========

.. code-block:: yaml

  cae:
    fea:
      path: solve_fea.py
      pythonRequirements:
        - ccx2paraview==3.2.0
      extension: glb          # required: PartCAD has no default to guess at
      mesh_size: 2.0          # a parameter of this implementation

Three things differ from an output type, and all three follow from an analysis
not being a file type of the object:

**There is no built-in package to fall back on.** An export implementation
cannot stand in for an analysis, and an ``fea`` declared under ``export:`` is an
export format that happens to be called ``fea``.

**``extension`` is required.** Which model format an analysis writes -- a 3D
field, a 2D plot -- is the implementation's decision, and guessing on its behalf
would put a name on a file whose contents are something else.

**The implementation reports findings.** Beside ``success`` it returns
``findings``, a JSON array of what it has to say about the part. An empty one is
a pass, and is what the analysis checks of ``pc test`` require.

A plugin that needs a solver ``pip`` cannot install names a ``dockerImage``
carrying it, which is the one case where a check that could not run is excused
rather than failed -- and only on a machine with no container runtime at all.
:doc:`/digital_thread/lifecycle/analysis` sets out that policy in full, because
it decides what a shared package costs everybody who opens it.

An example
==========

Six solver packages exist, each wrapping one program:

.. list-table::
   :header-rows: 1

   * - package
     - solver
     - analyses
   * - `partcad-cae-calculix <https://github.com/partcad/partcad-cae-calculix>`_
     - `CalculiX <https://www.calculix.de/>`_
     - ``fea`` (the default)
   * - `partcad-cae-elmer <https://github.com/partcad/partcad-cae-elmer>`_
     - `Elmer <https://www.elmerfem.org/>`_
     - ``fea``, ``dynamic`` (the default), ``thermal`` (the default), ``cfd``
   * - `partcad-cae-openfoam <https://github.com/partcad/partcad-cae-openfoam>`_
     - `OpenFOAM <https://www.openfoam.com/>`_
     - ``cfd`` (the default)
   * - `partcad-cae-code-aster <https://github.com/partcad/partcad-cae-code-aster>`_
     - `Code_Aster <https://www.code-aster.org/>`_
     - ``fea``, ``dynamic``, ``thermal``
   * - `partcad-cae-moose <https://github.com/partcad/partcad-cae-moose>`_
     - `MOOSE <https://mooseframework.inl.gov/>`_
     - ``fea``, ``dynamic``, ``thermal``, ``cfd``
   * - `partcad-cae-code-saturne <https://github.com/partcad/partcad-cae-code-saturne>`_
     - `code_saturne <https://www.code-saturne.org/>`_
     - ``cfd``

Each names a ``dockerImage`` carrying its solver and mesher, so a container
runtime is all it asks of a host that has neither installed -- and each also
runs a solver installed on the host, when there is no container runtime or it is
turned off. Each package's README says what every parameter means.

``examples/feature_cae`` is the set of cases to check an implementation
against -- a cantilever analysed for stress, for its natural frequencies and for
heat, and a pipe for flow, one scenario each, **each with a closed-form answer
to compare the solver with**. That is what makes it a conformance suite rather
than a demonstration, and its ``README.md`` has what each implementation
measured. ``examples/feature_cam`` is the same idea for routes: three operations
on three objects, and a fourth that declares nothing and is passed over.

.. code-block:: shell

  cd examples/feature_cae
  pc cae fea :cantilever       # against whatever caeFeaImplementation names
  pc test -f fea               # the same scenarios, as a check
