.. _engineering-analysis:

Analysis
########

.. toctree::
   :maxdepth: 2
   :hidden:

   analysis_fea.rst
   analysis_dynamic.rst
   analysis_thermal.rst
   analysis_cfd.rst


Analysis is what engineering says about a design before anything is made: what
it weighs and where its centre of mass is, how it carries a load, how a fluid
flows around it, how it behaves once gravity and contact are switched on. Each
answer is worked out from the design as it is now, so it is never an answer
about last week's version.

What PartCAD captures
=====================

Physical properties
-------------------

What an object weighs, its centre of mass, its inertia, its friction: stated in
a ``physics:`` section, lent by its :ref:`material <materials>` (a density, a
friction coefficient), or worked out from the solid -- and, for an assembly,
combined from its parts. ``pc info`` reports each value with where it came from,
and a requirement on one is checked against the same value (see
:doc:`/digital_thread/lifecycle/requirements`).

Engineering analyses
--------------------

A part says what holds it, what it carries and how it is heated and cooled, in a
section named after the analysis -- ``fea:`` for a finite element analysis,
``dynamic:`` for the frequencies it rings at, ``thermal:`` for heat transfer,
``cfd:`` for computational fluid dynamics -- because the conditions are a
property of the part rather than of the solver asked about it. Each section is a
map of named scenarios, one per question of that kind the part is asked, the way
``simulate:`` is a map of simulations. Each condition names an interface the
part implements, so it lands where the part connects. ``pc cae fea``, ``pc cae
dynamic``, ``pc cae thermal`` and ``pc cae cfd`` run the scenarios through the
implementation configured -- all of them, or one with ``-f`` -- and report what
each finds. A scenario may name the feature of the requirements it demonstrates
(``feature:``), which makes it evidence for that feature, as a simulation's is.
See :ref:`engineering-analysis` and :ref:`cae`.

Simulations
-----------

A part, an assembly or a scene says what it is supposed to *do* in a
``simulate:`` section: the scene it is placed in, the simulation plugin that runs
it, and a ``validation:`` condition over what happened that holds when it went as
it should -- "after ten seconds on a 10° slope it is still upright". ``pc sim``
runs them. A simulation may name the feature of the requirements it demonstrates
(``feature:``), which makes it evidence for that feature. See
:doc:`/digital_thread/lifecycle/simulation` and :ref:`simulate`.

Analysis and validation
=======================

An analysis answers a question; validation asks whether the answer is the one
that was needed. The same runs serve both: ``pc test`` runs every scenario of
every ``fea:``, ``dynamic:``, ``thermal:`` and ``cfd:``, and every ``simulate:``
entry, declared as its checks of the same names (``sim`` for a simulation), and
fails an object any of whose scenarios finds a problem or whose simulation does
not behave as it says (see :doc:`/digital_thread/lifecycle/validation`).

In the UI
=========

**Analysis** holds a tab per analysis, each enabled for a part that declares
scenarios of it and disabled -- with the reason on hover -- for everything
else. Each lists the scenarios down the left, runs the one selected with the
solver chosen over it, and shows the model it produced and what it found. Each
has a chapter of its own:

:doc:`FEA </digital_thread/lifecycle/analysis_fea>`
  Does the part hold up under what it carries: the stress in it, and how far it
  moves. Read from ``fea:``.

:doc:`Dynamic FEA </digital_thread/lifecycle/analysis_dynamic>`
  At which frequencies does it ring, held as it is held, and in what shape.
  Read from ``dynamic:``.

:doc:`Heat Transfer </digital_thread/lifecycle/analysis_thermal>`
  How hot does it get, heated and cooled as it is. Read from ``thermal:``.

:doc:`CFD </digital_thread/lifecycle/analysis_cfd>`
  How does a fluid flow through it -- where the part *is* the fluid volume.
  Read from ``cfd:``.

.. image:: /images/dt-analysis.png
  :width: 100%
  :align: center
  :alt: The Analysis group: its four tabs, the scenario list, and the result of the one selected

These tabs are the exception to "every tab is a question": looking at one
**runs** the analysis. That is why each is a chapter rather than a line -- what
it costs, what it needs installed and what its failure means are particular to
the analysis.

The simulations are not here. They are run from
:ref:`Validation → Simulation <sim-in-the-ui>`, because what a simulation
answers is whether the object does what it says it does, which is a question of
validation rather than of analysis.


On the command line
===================

.. code-block:: shell

  pc info :bracket                     # the physical properties, and where each came from
  pc cae fea :bracket                  # every scenario of one analysis
  pc cae fea -f loaded :bracket        # one of them, by name
  pc cae thermal :heatsink             # another analysis
  pc sim -a gearbox                    # the simulations, which are the other half of this phase
  pc test -f fea :bracket              # an analysis as the check pc test makes of it

Each analysis has a chapter of its own above, with the keys its section takes
and the packages that implement it. What follows here is what they have in
common.

Running an analysis
===================


A part can say what holds it, what it carries, how it is heated and where a
fluid goes through it, and PartCAD can put that question to a solver. There are
four questions, each its own command: ``pc cae fea`` for a finite element
analysis, ``pc cae dynamic`` for its natural frequencies, ``pc cae thermal`` for
heat transfer, and ``pc cae cfd`` for computational fluid dynamics. The
conditions live on the part, in a section named after the analysis, because they
are a property of the part rather than of whoever analyses it -- a bracket is
bolted down at the same holes whichever solver is asked about it. A part is
asked more than one question of each kind -- a shelf bracket loaded, and the
same bracket knocked sideways -- so the section is a map of named
**scenarios**, the way ``simulate:`` is a map of named simulations:

.. code-block:: yaml

  # partcad.yaml

  parts:
    bracket:
      type: build123d
      path: bracket.py
      fea:
        loaded:
          desc: A full shelf on it
          feature: carries-a-shelf   # the requirement it demonstrates
          fix:
            - m3-screw        # every instance of this interface is held still
          load:
            hook: 5 kg        # every instance of this one carries this
            rail:
              left: 30 N      # or one named instance at a time
              right: 30 N
        knocked:
          fix:
            - m3-screw
          load:
            hook: [0 N, 50 N, 0 N]   # a force with a direction
      dynamic:
        bolted-down:
          fix:
            - m3-screw        # held there, and left to ring
      thermal:
        in-use:
          temperature:
            m3-screw: 40 C    # held at a temperature
          heat:
            hook: 2 W         # heat put in through the port's surface

``pc cae fea :bracket`` runs every scenario of the analysis and ``-f`` runs one
(``pc cae fea -f loaded :bracket``); ``pc test`` holds the part to all of them.
Beside its conditions a scenario may say what it is (``desc:``), which feature
of the part's :ref:`requirements <requirements>` it demonstrates
(``feature:``, a name or a list -- the IDE's Requirements tab lists it there, as
it lists a simulation), who runs it (``implementation:``, below) and the
implementation's parameters for that scenario alone (``params:``, a finer
``mesh_size`` say). A scenario cannot be named after any of those keys or after a
condition. A section written the way it was before scenarios -- ``fea:`` holding
``fix:`` and ``load:`` itself -- is still read, as one scenario named
``default``, and PartCAD says once that it is deprecated: move its conditions
under a name.

Every key names :ref:`interfaces <interfaces>` the part implements, so the same
declaration that says where a part connects also says where it is held, pulled,
heated and cooled. A ``load`` is a force: write a number and a unit, or a bare
number for a mass in kilograms, which PartCAD weighs into newtons at 9.8 N/kg. A
``temperature`` is in Celsius, a ``heat`` a power in watts, a ``convection`` a
film coefficient in W/(m²·K). ``cfd:`` reads ``load:`` as where the flow is
driven in and ``outlet:`` as where it leaves; every other surface of the fluid
volume is a wall. :ref:`pc cae <cae>` lists every key each analysis takes.

A condition lands on the **surface its port stands for**. A port is a coordinate
frame, and a frame cannot say how wide an inlet is; a sketch can. An interface
that draws a port with a sketch -- a ``basic`` ``circle:`` for the end of a bore
-- has that sketch placed by the port's frame, Z out of the surface, and PartCAD
imprints it on the part before the solver runs: the implementation is handed the
faces each port covers, and a force or a power is spread over exactly their area.
A port with no sketch covers the face it lies on.

PartCAD ships no solver. The analysis is run by an implementation package,
declared in a ``cae:`` section exactly as an export or a render implementation is
declared in its own (see :ref:`cae-section`), and named by the user
configuration option named after the analysis: ``caeFeaImplementation``,
``caeDynamicImplementation``, ``caeThermalImplementation`` and
``caeCfdImplementation``. The defaults, and the other implementations there are:

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

Each package's README says what it needs and what every parameter means. Each
names a ``dockerImage`` carrying its solver and mesher, so a container runtime is
all it asks of a host that has neither installed -- and each also runs a solver
installed on the host, when there is no container runtime or it is turned off.
``pc cae fea --implementation`` overrides the choice for one run, and so does
choosing or typing another solver in "Analysed by" over the model in the IDE's
analysis tabs.

A scenario may also name its own, which is what it was written against:

.. code-block:: yaml

    fea:
      loaded:
        implementation: //pub/feature/cae/calculix:fea
        fix: [m3-screw]
        load: {hook: 5 kg}

That sits between the other two: ``-i`` on the command line wins, then the
scenario, then the user configuration. It is how a package ships an analysis that works
for whoever opens it, without every reader first pointing their own
configuration at the right place.

A **relative** package name here -- ``calculix:fea`` rather than
``//pub/feature/cae/calculix:fea`` -- means the package this one imported under
that name, and is resolved from the package the declaration is written in. That
is not where a name a *user* types is resolved from: ``pc cae fea -i
calculix:fea`` means the ``calculix`` beside the user, like every other name a
command line carries. The difference matters under ``pc test -P //...`` over a tree of
packages, which runs with the tree's root current while every part in it sits one
or more packages below.

What comes back from each scenario is two things: the model, written to
``<part>.<analysis>.<scenario>.<extension>`` in whichever format the
implementation chose (``bracket.fea.loaded.glb``), and the **findings** -- a
JSON array of what the analysis has to say about the part. ``pc test`` gains a
check per analysis -- ``fea``, ``dynamic``, ``thermal``, ``cfd`` -- that runs
every scenario of it and fails a part any of whose scenarios produced a finding,
naming the scenario; they apply only to a part that declares the matching
section, so a package of bolts pays nothing for them. There is one way to pass -- the
analysis ran and reported nothing -- and everything else **fails**: a malformed
section, a plugin that cannot be resolved (not a dependency, misspelt, declaring
no such file type), a plugin that resolves and cannot run (no mesher, no solver,
a sandbox that will not build, a crash), and an analysis that ran and found
something.

Not running is deliberately not a skip. A skip says the question does not apply
here; a part that declares ``fea:`` has asked, and a plugin that was asked and
delivered nothing has failed. The consequence is the point: declaring ``fea:``
in a shared package makes ``pc test`` fail for everyone who has not installed
what that implementation needs. A package that does not want that should not
declare the section. What the failure carries is *why* -- the implementation's
own sentence, plus which implementation was asked and which machine it did not
work on, because "gmsh is not installed" is a puzzle and the same sentence under
``//pub/feature/cae/calculix:fea on Linux-aarch64`` is an answer.

There is **one** excuse, and it is the case where the implementation was never
given the environment it says it needs. An implementation naming a ``container:``
or a ``dockerImage`` is stating that a container is how what pip cannot install
arrives; on a machine with no container runtime that statement has nowhere to
land, nothing was ever asked, and the check skips with a ``WARNING`` carrying the
whole report rather than failing. It is narrow in both directions. An
implementation that names no image gets no excuse at all -- it said it runs in an
ordinary sandbox, and a machine with a working sandbox is a machine it was
supposed to work on. And a container runtime that *is* here removes the excuse
entirely: a registry that cannot be reached, an image that will not start, a
solver missing from the image are all things somebody can fix, and calling them
"unavailable" would hide exactly the failures a plugin's own CI exists to catch.

A Docker daemon running **Windows** containers does not count as a container
runtime for this, or for choosing a sandbox. Every image PartCAD builds, pulls or
documents is a Linux image, and such a daemon answers a ping and then fails every
pull with ``no matching manifest for windows/amd64``.

The same policy, from the same code, decides ``pc test``'s ``sim`` check, which
holds a part, an assembly or a scene to the ``simulate:`` claims it makes: a simulator
that resolved and did not run is a failure, but for the one excuse, and a
simulation plugin that cannot be found is never excused. See "Running a
simulation" in :doc:`/digital_thread/lifecycle/simulation`.

``examples/feature_cae`` is the set of cases to check an implementation against
-- a cantilever analysed for stress, for its natural frequencies and for heat,
and a pipe for flow, one scenario each, each with a closed-form answer to compare
the solver with.
The pipe's inlet and outlet are drawn with the bore's circle, so the pressure
driving it is the inlet's force over exactly the bore's area. That example's
``README.md`` has what each implementation measured.

See :ref:`pc cae <cae>` for the command and the units it accepts.

Agent skills
============

``/pc:sim-assembly-fea``
  Turns what a simulation measured into a stress analysis of one part. It runs
  the assembly's ``simulate:`` entry, reads the forces and moments acting on the
  body the part is welded into at the end of the run, works out which of them
  load that part and where, and writes a new named scenario into the part's
  ``fea:`` section beside any already there. It is the bridge between the two
  halves of this phase: a simulation says what the world does to an assembly,
  and this turns that into the load case one part has to survive.

``/pc:validate``
  Runs every analysis scenario as part of giving each requirement a verdict, and
  reports a scenario that names a ``feature:`` as evidence for that feature.

There is no skill that writes an ``fea:`` section from a description. The
conditions are an engineering judgement about how the part is really held and
loaded, and a plausible-looking guess at them produces a plausible-looking
number that is wrong.
