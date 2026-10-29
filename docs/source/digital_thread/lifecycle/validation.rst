Validation
##########

.. toctree::
   :maxdepth: 2
   :hidden:

   testing.rst
   simulation.rst


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
  what it found when it fails. :doc:`/digital_thread/lifecycle/testing` lists them all.

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

In the UI
=========

**Validation** is always there, since every object has checks. It holds three
tabs, two of which have anything in them today, and each of those has a chapter
of its own:

:doc:`Test </digital_thread/lifecycle/testing>`
  Every check ``pc test`` runs, in the order it runs them, each with its
  verdict -- and, for the one selected, what it asks, what it found this time,
  and what to do about it. The first tab, and always enabled.

:ref:`Simulation <sim-in-the-ui>`
  Every simulation the object declares, run and played back: whether its
  ``validation:`` held, the video of the run, and the ``before`` and ``after``
  the expression was evaluated over. For a part, an assembly or a scene that
  declares ``simulate:``.

**Process Emulation**
  The question of how *making* it would go. Reserved, always disabled, and
  holding nothing yet (see :doc:`/digital_thread/lifecycle/operations`).

.. image:: /images/dt-validation.png
  :width: 100%
  :align: center
  :alt: The Validation group: its three tabs, every check pc test runs, and the verdicts

Both working tabs **run** what they show, the first time they are looked at --
the checks as ``pc test <object>`` runs them, a simulation as ``pc sim -f
<name>`` runs it -- and through the same cache, so the panel and the command
line give the same answer and **Run again** is how to ask afresh. An object that
belongs to no package, such as a shape shown from a script, has nothing to ask
PartCAD about, and the Test tab says so.


On the command line
===================

``pc test`` is the whole of this phase in one command. It takes an object, or
``-P <package>`` for every object of a package and everything below it, and runs
every check that has something to ask of each one:

.. code-block:: shell

  pc test :bracket                 # one object
  pc test -P //...                 # a tree of packages
  pc test --fast-only -P //...     # leaving out what says it is slow
  pc --cache-bypass test :bracket  # asking again rather than reading the cache

``pc sim`` runs the simulations alone -- ``-f <name>`` for one of them, and
``--json`` to print everything the simulator reported rather than only the
verdict. ``pc cae fea`` and its siblings run the engineering analyses, whose
findings ``pc test`` reports as checks of their own (see
:doc:`/digital_thread/lifecycle/analysis`).

Every verdict is cached under everything it depends on, so the command line, the
panel and CI give the same answer and an unchanged object costs a lookup.

.. _validating-a-scene:

Simulating a scene
------------------

A scene can be the thing a claim is about, not only the world it is tested in:
a stack of blocks that stands, a pile that does not slide. It declares
``simulate:`` exactly as a part or an assembly does (see :ref:`sim-declaring`),
and is simulated as the subject of a world -- the built-in one, or a scene of the
package's own -- whose link places it with ``scene:``, since PartCAD hands that
world ``subject_kind: scene``:

.. code-block:: yaml

  scenes:
    stable:
      type: assy                      # two blocks, one set on the other
      simulate:
        stands:
          simulation: sim-mujoco:mujoco
          offset: [[0, 0, 10], [0, 0, 1], 0]
          validation: |
            max(abs(after["bodies"][n]["pos"][2] - before["bodies"][n]["pos"][2]) for n in before["bodies"]) < 5.0

``pc sim stable`` runs it, and ``pc test`` holds the scene to it as its
``sim`` check like any other object. ``examples/feature_simulate`` declares its
three stacks this way.

Validating continuously
=======================

A check that runs only when somebody remembers to run it is a check that stops
being run. ``pc test -P <package>...`` in CI holds every change to every check of
every object; ``--fast-only`` leaves out the objects that say they are slow
(see :ref:`fast-only`). Verdicts are cached under everything they depend on, so
an unchanged object costs a lookup, and ``pc --cache-bypass test`` asks again
regardless.

Agent skills
============

``/pc:validate``
  The skill for this phase. It runs ``pc test`` and ``pc sim``, renders the
  object from every angle that matters with its ports and interfaces drawn,
  reads the bill of materials and the assembly instructions of an assembly, and
  gives every requirement a verdict with the evidence named. The ``features:``
  half of the requirements -- prose, which no program can measure -- is judged
  here and nowhere else.

``/pc:sim-assembly-fea``
  Turns the forces a simulation measured into an FEA scenario on one part, which
  is then checked like any other (see
  :doc:`/digital_thread/lifecycle/analysis`).

``/pc:render``
  Produces the views that are the evidence for a feature nothing can measure.

A skill runs the same commands, through the same cache, so a verdict an agent
reports is a verdict you can reproduce by hand.
