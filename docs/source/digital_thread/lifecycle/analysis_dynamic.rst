.. _dt-analysis-dynamic:

###########
Dynamic FEA
###########

**Dynamic FEA** is the question at which frequencies a part rings, held as it is
held: a modal analysis of the solid, reporting its natural frequencies and the
shape it moves in at each one. It is what says whether a bracket will be shaken
by the motor bolted to it.

The question is asked by a ``dynamic:`` section on the part, a map of named
scenarios, and answered by a solver a package supplies.
:doc:`/digital_thread/lifecycle/analysis` explains what every analysis has in
common.

What the scenario says
======================

One condition:

``fix:``
  a list of interface types held still, or a map from a type to the instances
  of it meant. The natural frequencies of everything else are what is found.

There is no load. A modal analysis asks what the part does when nothing drives
it, so ``load:`` is refused here rather than ignored -- it would read as a
boundary condition and not be one. How many modes are reported is the
implementation's parameter (``modes``), stated in the package's ``cae:``
section or per scenario in ``params:``.

.. code-block:: yaml

  parts:
    bracket:
      type: build123d
      path: bracket.py
      dynamic:
        bolted-down:
          desc: Held at its screws and left to ring
          fix:
            - m3-screw

In the UI
=========

The scenarios are listed down the left with the first selected, each marked
with how its last run went, and selecting one runs it. What is shown is the
model the implementation produced -- the mode shapes, drawn as geometry to turn
and zoom -- with the frequencies and any findings under it.

**Analysed by** names the solver and takes another; **Analyse** runs the
scenario again. Both work exactly as they do on the
:doc:`FEA tab </digital_thread/lifecycle/analysis_fea>`.

.. image:: /images/dt-analysis-dynamic.png
  :width: 100%
  :align: center
  :alt: The Analysis group's Dynamic FEA tab: the scenario list and the mode shape

The tab is enabled for a part that declares ``dynamic:``, and disabled -- with
the reason on hover -- for everything else.

On the command line
===================

.. code-block:: shell

  pc cae dynamic :bracket                                     # every scenario
  pc cae dynamic -f bolted-down :bracket                      # one of them
  pc ide view --analysis-dynamic :bracket                     # shown in the panel
  pc test -f dynamic :bracket                                 # as the check pc test runs

Who runs it
===========

The default is `partcad-cae-elmer
<https://github.com/partcad/partcad-cae-elmer>`_, which runs
`Elmer <https://www.elmerfem.org/>`_; ``caeDynamicImplementation`` names
another. `Code_Aster <https://www.code-aster.org/>`_ and
`MOOSE <https://mooseframework.inl.gov/>`_ do this analysis too.

An example
==========

`examples/feature_cae <https://github.com/partcad/partcad/tree/main/examples/feature_cae>`_
declares ``cantilever``'s ``clamped`` scenario: the same steel bar, clamped at
the root and left to ring. Its first natural frequency is a closed form, and
the package's ``README.md`` compares what the solver reported with it. The
scenario asks for six modes, which is enough to see the first bending pair, the
first torsion mode and the second bending pair.

Agent skills
============

``/pc:validate``
  Runs every scenario as part of giving each requirement a verdict, and reports
  one that names a ``feature:`` as evidence for that feature.

As with FEA, nothing writes a ``dynamic:`` section from a description: what
holds the part is a judgement about the real assembly.
