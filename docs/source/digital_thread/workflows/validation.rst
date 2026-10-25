Validation
##########

Validation is the question whether the object is what it was asked to be, and
whether every claim its declaration makes holds: that it builds, that it can be
made, that its parts do not overlap, that it weighs what it has to, that it does
what its simulations say. It is asked last and asked again whenever anything
changes, which is what makes the rest of the thread trustworthy.

Three ways of asking
====================

``pc test``
  Every claim that can be measured, by a list of checks that each ask one thing
  -- whether it builds, whether it can be made or bought, whether its parts
  overlap, whether its ports and physical properties are the ones required.
  Each check applies only to the objects it has something to ask of, and says
  what it found when it fails. :doc:`/digital_thread/workflows/testing` lists them all.

``pc sim``
  Every claim about behaviour: each simulation an object declares is run, and
  its ``validation:`` condition has to hold. ``pc test`` runs the same
  simulations as its ``sim`` check; ``pc sim --json`` also prints everything the
  simulator reported, which is how a validation that passed for the wrong reason
  is found.

``/pc:validate``
  Everything else. The agent skill runs ``pc test`` and ``pc sim``, renders the
  object from every angle that matters with its ports and interfaces drawn, reads
  the bill of materials and the assembly instructions of an assembly, and gives
  every requirement a verdict -- met, not met, or "cannot tell" -- with the
  evidence named. The features of the requirements, being prose, are judged here
  and only here.

In the Digital Thread
=====================

**Validation** is always there, since every object has checks. Its first tab,
**Test**, opens on it:

- On the left, every check ``pc test`` runs, in the order it runs them, each with
  its verdict: passed, failed, warned, skipped, or not applicable -- the last
  saying why, so a check that did not apply is never mistaken for one that
  passed.
- In the middle, the check selected: what it asks, when it does not apply, what
  each failure means and what to do about it -- the text of :doc:`/digital_thread/workflows/testing` -- and
  above it what the check found this time.
- For a failure that left something behind to look at, a button that opens it.
  An interference leaves an assembly of the two parts that overlap, placed where
  the assembly places them, and a sub-assembly named ``interference`` holding
  what they share: switch the two parts off and what is left is the overlap.

The checks run when the tab is opened, as ``pc test <object>`` runs them and
through the same cache, so the panel and the command line give the same answer;
**Run again** asks once more. An object that belongs to no package -- a shape
shown from a script -- has nothing to ask PartCAD about, and the tab says so.

**Simulation**, beside it, is for a part, an assembly or a scene that declares
``simulate:``: each simulation it declares, run as ``pc sim -f <name>`` runs it,
with whether its ``validation:`` held and a picture of the scene before and after
(see :doc:`/digital_thread/workflows/simulation`). **Process Emulation** holds nothing yet.

Validating continuously
=======================

A check that runs only when somebody remembers to run it is a check that stops
being run. ``pc test -P <package>...`` in CI holds every change to every check of
every object; ``--fast-only`` leaves out the objects that say they are slow
(see :ref:`fast-only`). Verdicts are cached under everything they depend on, so
an unchanged object costs a lookup, and ``pc --cache-bypass test`` asks again
regardless.

.. toctree::
   :maxdepth: 2

   testing.rst
