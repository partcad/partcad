.. _dt-analysis-thermal:

#############
Heat Transfer
#############

**Heat Transfer** is the question how hot a part gets, heated and cooled as it
is: a steady-state thermal analysis of the solid, reporting the temperature
through it. It is what says whether a heatsink is big enough.

The question is asked by a ``thermal:`` section on the part, a map of named
scenarios, and answered by a solver a package supplies.
:doc:`/digital_thread/lifecycle/analysis` explains what every analysis has in
common.

What the scenario says
======================

Three conditions, each naming interfaces the part implements:

``temperature:``
  a temperature per interface type or named instance, in Celsius
  (``40 C``) -- the surface is held there.

``heat:``
  a power put in through the port's surface, in watts (``2 W``).

``convection:``
  a film coefficient in W/(m²·K) -- that surface is cooled against the ambient.

**Every other surface is insulated.** A part that states only where heat goes
in is a part with nowhere for it to go, so each scenario has to say how it
leaves: held at a temperature, or cooled by a film.

.. code-block:: yaml

  parts:
    heatsink:
      type: build123d
      path: heatsink.py
      thermal:
        in-use:
          desc: 2 W in at the die, the base held at ambient
          temperature:
            m3-screw: 40 C
          heat:
            die: 2 W
          convection:
            fins: 10

In the UI
=========

The scenarios are listed down the left with the first selected, each marked
with how its last run went, and selecting one runs it. What is shown is the
temperature field over the model the implementation produced, with the findings
under it; **Analysed by** chooses the solver and **Analyse** runs it again.

.. image:: /images/dt-analysis-thermal.png
  :width: 100%
  :align: center
  :alt: The Analysis group's Heat Transfer tab: the scenario list and the temperature field

The tab is enabled for a part that declares ``thermal:`` and disabled for
everything else.

On the command line
===================

.. code-block:: shell

  pc cae thermal :heatsink                                # every scenario
  pc cae thermal -f in-use :heatsink                      # one of them
  pc ide view --analysis-thermal :heatsink                # shown in the panel
  pc test -f thermal :heatsink                            # as the check pc test runs

Who runs it
===========

The default is `partcad-cae-elmer
<https://github.com/partcad/partcad-cae-elmer>`_, which runs
`Elmer <https://www.elmerfem.org/>`_; ``caeThermalImplementation`` names
another. `Code_Aster <https://www.code-aster.org/>`_ and
`MOOSE <https://mooseframework.inl.gov/>`_ do this analysis too.

An example
==========

`examples/feature_cae <https://github.com/partcad/partcad/tree/main/examples/feature_cae>`_
declares ``cantilever``'s ``tip-heated`` scenario: the root held at 20 °C and
1 W put in at the tip. The temperature the tip reaches is ``P·L/(k·A)``, and the
package's ``README.md`` prints what the solver measured beside it.

Agent skills
============

``/pc:validate``
  Runs every scenario as part of giving each requirement a verdict, and reports
  one that names a ``feature:`` as evidence for that feature.
