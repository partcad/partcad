.. _dt-analysis-fea:

###
FEA
###

**FEA** is the question whether a part holds up under what it carries: a finite
element analysis of the solid, held where it is held and pulled on where it is
loaded, reporting the stress in it and how far it moves.

The question is asked by an ``fea:`` section on the part -- a map of named
**scenarios**, one per load case the part is asked about -- and answered by a
solver a package supplies. :doc:`/digital_thread/lifecycle/analysis` explains
what every analysis has in common; this page is what is particular to this one.

What the scenario says
======================

Two conditions, each naming :ref:`interfaces <interfaces>` the part implements,
so the declaration that says where the part connects is the one that says where
it is held and loaded:

``fix:``
  a list of interface types held still, or a map from a type to the instances
  of it meant.

``load:``
  a force per interface type, or per named instance. A number with a unit
  (``100 N``, ``5 kg``) or a bare number, which is a mass in kilograms weighed
  at 9.8 N/kg; or three of them, ``[x, y, z]`` in the part's own frame, which is
  a force *with a direction* -- what a simulation measures acting on a part.

An ``fea:`` scenario also takes ``gravity:``, the acceleration of free fall it
is analysed in, in m/s² and the part's own frame. That is for a part a
simulation found upside down or accelerating, whose weight is its mass times
``g - a``; without it the implementation weighs the part under its own gravity.

.. code-block:: yaml

  parts:
    bracket:
      type: build123d
      path: bracket.py
      fea:
        loaded:
          desc: A full shelf on it
          feature: carries-a-shelf   # the requirement it demonstrates
          fix:
            - m3-screw
          load:
            hook: 5 kg
        knocked:
          fix:
            - m3-screw
          load:
            hook: [0 N, 50 N, 0 N]

In the UI
=========

The scenarios are listed down the left, in the order they are declared, with
the first selected and a mark before each name saying how its last run went: a
green tick found nothing, a red cross found something, a red exclamation could
not run. Selecting one **runs** it -- this is the exception to "every other tab
is a question" -- and shows the stress field over the model it produced, to
turn and zoom like any other geometry, with what the analysis found listed
under it.

Over the model, **Analysed by** names the solver: filled in with the
scenario's own ``implementation:`` or the configured default, offering the
others ``//pub/feature/cae`` registers for this analysis, and taking any other
name typed into it -- so a machine whose solver is elsewhere is one choice away
from an answer rather than stuck on an error. **Analyse** runs it again.

.. image:: /images/dt-analysis.png
  :width: 100%
  :align: center
  :alt: The Analysis group's FEA tab: the scenario list, the stress field, and "Analysed by"

The tab is enabled for a part that declares ``fea:`` and disabled for everything
else, which it says when the mouse is over it.

On the command line
===================

.. code-block:: shell

  pc cae fea :bracket                                   # every scenario
  pc cae fea -f loaded :bracket                         # one of them
  pc cae fea -i //pub/feature/cae/elmer:fea :bracket    # with another solver
  pc ide view --analysis-fea --scenario loaded :bracket # the same, shown in the panel
  pc test -f fea :bracket                               # as the check pc test runs

What comes back is the model -- ``bracket.fea.loaded.glb``, in whichever format
the implementation chose -- and the **findings**, which ``pc test`` reports as
its ``fea`` check: a part any of whose scenarios found something fails.

Who runs it
===========

The default is `partcad-cae-calculix
<https://github.com/partcad/partcad-cae-calculix>`_, which runs
`CalculiX <https://www.calculix.de/>`_; ``caeFeaImplementation`` names another.
`Elmer <https://www.elmerfem.org/>`_, `Code_Aster
<https://www.code-aster.org/>`_ and `MOOSE <https://mooseframework.inl.gov/>`_
do this analysis too -- see the table in
:doc:`/digital_thread/lifecycle/analysis`.

An example
==========

`examples/feature_cae <https://github.com/partcad/partcad/tree/main/examples/feature_cae>`_
declares ``cantilever``: a 100 × 10 × 10 mm steel bar, clamped at one end and
pulled down by 100 N at the other, in a scenario named ``tip-load``. Its tip
deflection and its peak bending stress are both closed forms, and that
package's ``README.md`` prints what each solver measured beside the textbook
answer -- which is how an implementation is checked rather than believed.

Agent skills
============

``/pc:sim-assembly-fea``
  Writes an ``fea:`` scenario from what a simulation of the assembly measured:
  it reads the forces and moments acting on the body the part is welded into,
  works out which of them load the part and where, and adds a scenario named
  after the simulation and the reading they came from. It is the one skill that
  produces a load case, and it produces it from a measurement rather than from a
  description.

``/pc:validate``
  Runs every scenario as part of giving each requirement a verdict, and reports
  one that names a ``feature:`` as evidence for that feature.

There is deliberately no skill that writes an ``fea:`` section from prose. How
a part is really held and loaded is an engineering judgement, and a
plausible-looking guess at it produces a plausible-looking number that is wrong.
