Qualification
#############

.. toctree::
   :maxdepth: 2
   :hidden:

   qualification_tests.rst
   simulation.rst


Qualification is the question whether the object is what it was asked to be,
and whether every claim its declaration makes holds: that it builds, that it can
be made, that its parts do not overlap, that every feature to be made has a
tolerance, that it weighs what it has to, that it does what its simulations say.
It is asked last and asked again whenever anything changes, which is what makes
the rest of the thread trustworthy. (This phase used to be called Validation.)

Every question is a **qualification test**, and every test is of one of four
**subtypes**. What tells them apart is what they produce, and so how they are
shown:

``basic``
  A verdict and what was said about it, in words: it builds, it can be made or
  bought, its connections hold, its requirements are met. Most of the built-in
  tests.

``topology``
  A verdict and a *place on the object*: the volumes two parts share, the faces
  and edges of a part to be made that nothing tolerances. What a failure is about
  is left behind as geometry, and shown on the object with everything else faded.

``sim``
  The simulations the object declares, run: the object placed in a world, the
  world switched on, and a condition over the state before and after. Shown as
  the run itself -- the video, the pictures, and ``before`` and ``after``.

``other``
  A check of another tool's own, which a plugin supplies, in that tool's
  vocabulary: a power budget, a bus's bandwidth. Shown as the report the tool
  wrote.

The **built-in** tests are always applied, each to the objects it has something to
ask of -- a test that does not apply says why. A test a **plugin** supplies, and
every simulation, runs only where an object declares it. :doc:`/digital_thread/lifecycle/qualification_tests`
lists the built-in ones.

Declaring it
============

Everything an object says about how it is qualified is in one section of its
declaration, ``qual:``, one mapping per subtype:

.. code-block:: yaml

  parts:
    bracket:
      type: step
      path: bracket.step
      manufacturing:
        method: subtractive
        source: :stock
      qual:
        basic:
          cmf:                       # the parameters of a built-in test
            require: true
        topology:
          tolerance-surfaces:
            minArea: 1.0             # faces smaller than 1 mm^2 are not reported
        sim:
          stands:                    # a simulation (see the Simulation chapter)
            path: sim-mujoco:mujoco
            validation: after["bodies"]["bracket"]["pos"][2] > -1
        other:
          budgets:                   # a test a plugin supplies
            path: //pub/qual/lockwire:lockwire
            lockfile: rover.lockwire.yaml

Under ``basic:``, ``topology:`` and ``other:``, an entry named after a built-in
test is that test's **parameters** -- ``<object>.qual.basic.<test>.<param>: <value>``
-- and an entry that says ``path:`` is a test a **plugin** supplies, which must be
declared: ``path:`` names the plugin, and every other key is handed to it. Under
``sim:`` every entry is a simulation, whose ``path:`` names the simulation plugin
(it was ``simulation:``, under a section called ``simulate:``; both are still
read, as are the older ``interference:``, ``connectivity:`` and ``cmf:`` keys a
few built-in tests took their parameters from).

None of this is part of what the object *is*: editing ``qual:`` does not rebuild
the object, and each test folds what it reads of it into its own verdict's key.

Qualification plugins
---------------------

A package supplies a test the way it supplies a simulator, in a ``qual:`` section
of its own ``partcad.yaml``:

.. code-block:: yaml

  qual:
    lockwire:
      desc: Lockwire's power, mass, bus and torque budgets
      path: lockwire_qual.py         # the script
      subtype: other                 # basic, topology or other
      kinds: [assembly, part]        # what it can be asked of
      pythonRequirements: [lockwire]
      lockfile: lockwire.yaml        # a parameter, with its default

The script runs in a sandbox with what it declares it needs, is handed the
object -- its name, its package's directory, and the object itself as a file
when the plugin declares a ``format:`` -- and answers a verdict, findings, and,
by subtype, the geometry a topology finding is about or the report an ``other``
tool wrote. ``src/partcad/wrappers/wrapper_qual.py`` is the contract.
``plugins/qual-lockwire`` in the PartCAD repository is one, for
`Lockwire <https://lockwirerobotics.com/>`_.

On the command line
===================

``pc qual test`` is the whole of this phase in one command. It takes an object,
or ``-P <package>`` for every object of a package and everything below it, and
runs every test that has something to ask of each one -- of every subtype, or of
the ones named:

.. code-block:: shell

  pc qual test :bracket                     # one object, every subtype
  pc qual test --topology :bracket          # the topology tests alone
  pc qual test --basic --other -P //...     # two subtypes, a tree of packages
  pc qual test --simulation :bracket        # its simulations
  pc qual test --fast-only -P //...         # leaving out what says it is slow
  pc --cache-bypass qual test :bracket      # asking again rather than reading the cache

``pc qual add`` declares a test, writing ``<object>.qual.<subtype>.<name>`` into
the object's package:

.. code-block:: shell

  pc qual add --other --path //pub/qual/lockwire:lockwire --set lockfile=rover.lockwire.yaml rover budgets
  pc qual add --topology --set minArea=1.0 bracket tolerance-surfaces

``pc test`` and ``pc sim`` are the older spellings: ``pc test`` runs every subtype,
and ``pc sim`` runs the simulations, with ``-f <name>`` for one of them, ``--json``
to print everything the simulator reported, and ``--before``/``--after``/``--video``
to save what a run produced. ``pc cae fea`` and its siblings run the engineering
analyses, whose findings are basic tests of their own (see
:doc:`/digital_thread/lifecycle/analysis`).

Every verdict is cached under everything it depends on, so the command line, the
panel and CI give the same answer and an unchanged object costs a lookup.

In the UI
=========

**Qualification** is always there, since every object has tests. It holds a tab
per subtype, and one more that is reserved:

**Basic**
  Every basic test, in the order they run, each with its verdict -- and, for the
  one selected, what it asks, what it found this time, and what to do about it.
  Always enabled.

**Topology**
  Every topology test, the same way, and for a failure, the place it is about:
  **Show** opens the object in the 3D view with the finding -- the overlap, the
  untoleranced faces, the untoleranced edges as tubes -- in a colour of its own
  and everything else faded, and a chip over the view to clear it.

:ref:`Simulation <sim-in-the-ui>`
  Every simulation the object declares, run and played back: whether its
  ``validation:`` held, the video of the run, and the ``before`` and ``after``
  the expression was evaluated over. For a part, an assembly or a scene that
  declares simulations.

**Other**
  Every test a plugin supplies that the object declares, with the report its tool
  wrote, as a table. For an object that declares one.

**Process Emulation**
  The question of how *making* it would go. Reserved, always disabled, and
  holding nothing yet (see :doc:`/digital_thread/lifecycle/operations`).

.. image:: /images/dt-validation.png
  :width: 100%
  :align: center
  :alt: The Qualification group: its tabs, every test and the verdicts

Every tab **runs** what it shows the first time it is looked at -- the tests as
``pc qual test --<subtype> <object>`` runs them, a simulation as ``pc sim -f
<name>`` runs it -- and through the same cache, so the panel and the command line
give the same answer and **Run again** is how to ask afresh. An object that
belongs to no package, such as a shape shown from a script, has nothing to ask
PartCAD about, and the tabs say so.

.. _qualifying-a-scene:

Simulating a scene
------------------

A scene can be the thing a claim is about, not only the world it is tested in:
a stack of blocks that stands, a pile that does not slide. It declares
simulations exactly as a part or an assembly does (see :ref:`sim-declaring`),
and is simulated as the subject of a world -- the built-in one, or a scene of the
package's own -- whose link places it with ``scene:``, since PartCAD hands that
world ``subject_kind: scene``:

.. code-block:: yaml

  scenes:
    stable:
      type: assy                      # two blocks, one set on the other
      qual:
        sim:
          stands:
            path: sim-mujoco:mujoco
            offset: [[0, 0, 10], [0, 0, 1], 0]
            validation: |
              max(abs(after["bodies"][n]["pos"][2] - before["bodies"][n]["pos"][2]) for n in before["bodies"]) < 5.0

``pc qual test --simulation stable`` runs it, as does ``pc sim stable``.
``examples/feature_simulate`` declares its three stacks this way.

Qualifying continuously
=======================

A check that runs only when somebody remembers to run it is a check that stops
being run. ``pc qual test -P <package>...`` in CI holds every change to every
test of every object; ``--fast-only`` leaves out the objects that say they are
slow (see :ref:`fast-only`). Verdicts are cached under everything they depend on,
so an unchanged object costs a lookup, and ``pc --cache-bypass qual test`` asks
again regardless.

Agent skills
============

``/pc:validate``
  The skill for this phase. It runs ``pc qual test`` and ``pc sim``, renders the
  object from every angle that matters with its ports and interfaces drawn, reads
  the bill of materials and the assembly instructions of an assembly, and gives
  every requirement a verdict with the evidence named. The ``features:`` half of
  the requirements -- prose, which no program can measure -- is judged there and
  nowhere else.

``/pc:sim-assembly-fea``
  Turns the forces a simulation measured into an FEA scenario on one part, which
  is then checked like any other (see :doc:`/digital_thread/lifecycle/analysis`).

``/pc:render``
  Produces the views that are the evidence for a feature nothing can measure.

A skill runs the same commands, through the same cache, so a verdict an agent
reports is a verdict you can reproduce by hand.
