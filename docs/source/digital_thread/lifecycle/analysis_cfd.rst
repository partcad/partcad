.. _dt-analysis-cfd:

###
CFD
###

**CFD** is the question how a fluid flows through a part: a computational fluid
dynamics analysis, reporting the flow and the pressure in it. It is the one
analysis where the part **is the fluid**: the solid handed to the solver is the
volume the fluid occupies -- a bore, a duct, a plenum -- not the wall around it.

The question is asked by a ``cfd:`` section on the part, a map of named
scenarios, and answered by a solver a package supplies.
:doc:`/digital_thread/lifecycle/analysis` explains what every analysis has in
common.

What the scenario says
======================

``load:``
  where the flow is driven in, as a force on the inlet's surface -- so the
  pressure driving it is that force over exactly the port's area.

``outlet:``
  where it leaves, at the reference pressure.

``fix:``
  walls, where one has to be named.

**Every surface that is neither an inlet nor an outlet is a wall**, held
no-slip, so a bore's lateral surface is a wall without being named -- and could
not be named by a sketch anyway, a sketch being flat where that surface is a
cylinder.

.. code-block:: yaml

  parts:
    duct:
      type: build123d
      path: duct.py          # the fluid volume, not the pipe around it
      cfd:
        through:
          desc: Driven in at the inlet, leaving at the outlet
          load:
            duct-inlet: 0.005 N
          outlet:
            - duct-outlet

A condition lands on the surface its port stands for, and for an inlet that
matters more than anywhere else: a port is a coordinate frame, and a frame
cannot say how wide an inlet is. An interface that draws its port with a sketch
-- a ``basic`` ``circle:`` for the end of a bore -- has that sketch imprinted on
the part before the solver runs, and the force is spread over exactly the area
it covers.

In the UI
=========

The scenarios are listed down the left with the first selected, each marked
with how its last run went, and selecting one runs it. What is shown is the
flow field the implementation produced -- drawn as the format it chose, so a 3D
result is turned and zoomed and a 2D one is panned and zoomed as a picture --
with the findings under it. **Analysed by** chooses the solver, **Analyse** runs
it again.

.. image:: /images/dt-analysis-cfd.png
  :width: 100%
  :align: center
  :alt: The Analysis group's CFD tab: the scenario list and the flow field

The tab is enabled for a part that declares ``cfd:`` and disabled for everything
else.

On the command line
===================

.. code-block:: shell

  pc cae cfd :duct                                              # every scenario
  pc cae cfd -f through :duct                                   # one of them
  pc cae cfd -i //pub/feature/cae/openfoam:cfd :duct            # with a named solver
  pc ide view --analysis-cfd :duct                              # shown in the panel
  pc test -f cfd :duct                                          # as the check pc test runs

Who runs it
===========

The default is `partcad-cae-openfoam
<https://github.com/partcad/partcad-cae-openfoam>`_, which runs
`OpenFOAM <https://www.openfoam.com/>`_; ``caeCfdImplementation`` names another.
`Elmer <https://www.elmerfem.org/>`_, `MOOSE <https://mooseframework.inl.gov/>`_
and `code_saturne <https://www.code-saturne.org/>`_ do this analysis too.

An example
==========

`examples/feature_cae <https://github.com/partcad/partcad/tree/main/examples/feature_cae>`_
declares ``pipe``: the bore of a 10 × 100 mm pipe, driven by 5 mN at the inlet
and leaving at the outlet, every other surface a no-slip wall. Fully developed
laminar flow has a closed form -- Hagen-Poiseuille -- and the package's
``README.md`` prints the flow rate each solver measured beside it. Both of its
ports are drawn with the bore's circle, which is what makes the driving
pressure exactly the inlet force over the bore's area, and the part's own
``render:`` section draws that boundary so it can be looked at.

Agent skills
============

``/pc:validate``
  Runs every scenario as part of giving each requirement a verdict, and reports
  one that names a ``feature:`` as evidence for that feature.
