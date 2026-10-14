Analysis
########

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
:doc:`requirements`).

Engineering analyses
--------------------

A part says what holds it, what it carries and how it is heated and cooled, in a
section named after the analysis -- ``fea:`` for a finite element analysis,
``dynamic:`` for the frequencies it rings at, ``thermal:`` for heat transfer,
``cfd:`` for computational fluid dynamics -- because the conditions are a
property of the part rather than of the solver asked about it. Each condition
names an interface the part implements, so it lands where the part connects.
``pc cae fea``, ``pc cae dynamic``, ``pc cae thermal`` and ``pc cae cfd`` run them
through the implementation configured, and report what they find. See
:ref:`engineering-analysis` and :ref:`cae`.

Simulations
-----------

A part, an assembly or a scene says what it is supposed to *do* in a
``simulate:`` section: the scene it is placed in, the simulation plugin that runs
it, and a ``validation:`` condition over what happened that holds when it went as
it should -- "after ten seconds on a 10° slope it is still upright". ``pc sim``
runs them. A simulation may name the feature of the requirements it demonstrates
(``feature:``), which makes it evidence for that feature. See
:doc:`../simulation` and :ref:`simulate`.

Analysis and validation
=======================

An analysis answers a question; validation asks whether the answer is the one
that was needed. The same runs serve both: ``pc test`` runs every ``fea:``,
``dynamic:``, ``thermal:``, ``cfd:`` and ``simulate:`` declared as its checks of
the same names (``sim`` for a simulation), and fails an object whose analysis
finds a problem or whose simulation does not behave as it says (see
:doc:`validation`).

In the Digital Thread
=====================

**Analysis** holds a tab per analysis -- **FEA**, **Dynamic FEA**, **Heat
Transfer** and **CFD** -- for a part. Each
runs the analysis the part declares with the implementation typed beside it,
and shows the model it was run on and what it found. The simulations are run
from **Validation → Simulation**, since what a simulation answers is whether the
object does what it says it does.
