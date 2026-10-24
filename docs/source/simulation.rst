##########
Simulation
##########

A part, an assembly or a scene can say what it is supposed to *do* once it is
placed in a world and the world is switched on -- stand, stay stacked, sink, float, turn its
heavy side down -- and PartCAD can check that claim by simulating it, the same
way ``pc test`` checks that it can be made. This page is how to use that:
declaring a simulation, the world it runs in, the physical properties it reads,
running it, the engines that do the physics, writing the condition that decides
whether it passed, and the robot description formats -- URDF, SDFormat, MJCF --
that the same machinery reads and writes.

Why it is built the way it is, what has been decided and not built yet, and the
plan, are in the simulation `design record`_.

.. _design record: https://github.com/partcad/partcad/blob/devel/docs/design/simulation.md
.. _partcad-sim-mujoco: https://github.com/partcad/partcad-sim-mujoco
.. _partcad-sim-gazebo: https://github.com/partcad/partcad-sim-gazebo

.. contents::
   :local:
   :depth: 2

.. _sim-purpose:

======================
What simulation is for
======================

A drawing says what a product *is*. Much of what makes it right is what it
*does*: a stack of parts that stands, a fixture that does not tip, a float that
rises, a hull that turns its keel down. None of that can be read off the
geometry, and a claim that nobody checks is one readers learn to trust and
should not.

So a part, an assembly or a scene states the claim, in a ``simulate:`` section -- the
world it is placed in, where it goes, the engine that runs it, and a condition
over what happened -- and PartCAD runs it and judges it:

- ``pc sim`` runs the simulations an object declares and reports what each
  engine said;
- ``pc test`` holds every object to them, as its ``sim`` check, every time it
  runs.

The second is what makes it worth writing the claim *first*. Declare what the
part has to do, watch ``pc test`` fail, and change the design until it passes:
test-driven development, for a physical product. Once it passes it stays
checked, and an edit that breaks the claim -- a heavier part, a slipperier
material, a centre of mass moved -- fails the next test run rather than the
first prototype.

PartCAD implements no physics of its own. An engine is a package that a project
imports -- `partcad-sim-mujoco`_ for MuJoCo, `partcad-sim-gazebo`_ for
Gazebo -- and PartCAD's part is everything around it: placing the object in the
world, writing that world out in the engine's own format with every part's mass
and friction in it, running the engine in a sandbox that installs it, and
judging the result. A simulation is therefore as good as the engine's model and
the physical properties it is handed, and :ref:`sim-limitations` says what is
not modelled.

.. _sim-quick-start:

===========
Quick start
===========

``examples/feature_simulate`` is a package of small claims that can each be
checked, run in MuJoCo through `partcad-sim-mujoco`_. From that directory:

.. code-block:: shell

  pc sim stable         # two aluminium blocks, squarely stacked: nothing moves
  pc sim unstable       # the top block 18 mm off the edge: it falls off
  pc sim slippery       # 'stable' in PTFE, in a tilted world: the top block slides off
  pc sim block          # an aluminium cube rests on the floor, and sinks in water
  pc sim float          # a sealed 3 g cube rises in water, and falls in a vacuum
  pc sim buoy           # the float with its weight low down rights itself
  pc test -f sim        # every one of them, as the check pc test runs

Nothing has to be installed first. The MuJoCo plugin is a dependency of the
package, and PartCAD installs MuJoCo into the sandbox it runs the plugin in.

A declaration is a dependency on an engine and one entry under ``simulate:``.
This is ``stable``:

.. code-block:: yaml

  dependencies:
    sim-mujoco:
      type: git
      url: https://github.com/partcad/partcad-sim-mujoco.git
      track: main                          # `pc update` pins `revision:` to it

  scenes:
    stable:
      type: assy
      simulate:
        stands:
          desc: Nothing moves, even pulled sideways by a quarter of its weight
          simulation: sim-mujoco:mujoco        # the engine, from the package above
          scene: :tilted                       # a world of this package's own
          offset: [[0, 0, 10], [0, 0, 1], 0]   # stand the stack's bottom face on its floor
          validation: |
            max(
                sum((a - b) ** 2 for a, b in zip(after["bodies"][name]["pos"], before["bodies"][name]["pos"])) ** 0.5
                for name in before["bodies"]
            ) < 5.0

The validation says that no block moved 5 mm in any direction. ``pc sim
stable`` says whether it held; ``pc sim --json stable`` prints everything
the engine reported as well, which is where to look before writing a validation
of your own.

``stable`` is a **scene** rather than an assembly, and so are the other two
stacks: two blocks set one on another are an arrangement, not a product, so
each block is a body of its own, free to slide and to fall. See
:ref:`sim-bodies`.

The rest of the example reads the same way. ``stable`` and ``unstable`` are the
same two blocks and differ by 18 mm. ``stable`` and ``slippery`` differ by one
word, the material, and both run in ``tilted``, a scene whose gravity leans 15
degrees: on a level floor nothing pushes a block sideways, so its friction is
never asked anything. ``tank`` is a scene filled with water. ``float`` and
``buoy`` are the same cube as ``block``, and state what they weigh because a
sealed float is hollow and its geometry does not say so. The example's
``README.md`` walks through each of them.

``examples/feature_simulate_joints`` is the other half: assemblies whose parts
move on their joints -- a pendulum, and one of every other kind of joint -- each
held to its closed form, in MuJoCo and, for every kind Gazebo builds, in Gazebo.
See :ref:`sim-mechanisms`.

.. _sim-declaring:

======================
Declaring a simulation
======================

``simulate:`` is an optional section of a part, an assembly or a scene. Each entry is one
simulation under a name of its own -- the name is what ``-f`` selects and what a
report prints beside the verdict -- and states:

``scene``
  The world the object is placed in, by full path. It may be left out: the
  default, ``//builtin/scene:subject``, is an empty world that holds the object
  and nothing else, which is what "does this stand up on its own" means. A world
  with more in it -- a fixture to stand on, a tank of water, a tilted floor -- is
  a scene of your own; see :ref:`sim-scenes`.

``offset``
  Where the object's origin goes in that scene, as a location
  (``[[x, y, z], [axis x, axis y, axis z], angle]``, in millimetres and degrees).
  It is stated here rather than in the scene because it is a fact about *this*
  object -- where its origin sits relative to the floor it is meant to stand on
  -- and the scene is shared. The blocks of ``feature_simulate`` are drawn about
  their own centres, so each stack is lifted 10 mm to stand on the floor;
  ``buoy`` is also turned 60 degrees, to be released tilted.

``simulation``
  The engine plugin that runs it, by full path: ``sim-mujoco:mujoco`` is the
  ``mujoco`` simulation of the package this one imported as ``sim-mujoco``.
  There is no default, since PartCAD implements no simulator; see
  :ref:`sim-engines`.

``params``
  Values of the plugin's own parameters for this run -- ``duration``,
  ``samples``, ``gravity`` and the others each plugin lists (see
  :ref:`sim-engines`).

``validation``
  A Python expression over what the engine reported, true when what happened is
  what was supposed to happen; see :ref:`sim-validation`.

``desc``
  The claim in words, for whoever reads the result.

``feature``
  The feature of the object's :ref:`requirements` that this simulation
  demonstrates, by name, or a list of them. Nothing that runs the simulation
  reads it: it is what lets a reader of the requirements -- the IDE's
  Requirements tab, an agent running ``/pc:validate`` -- see which features a
  simulation stands behind. ``pc test`` fails an object one of whose simulations
  names a feature its requirements do not declare.

An object may declare as many simulations as it likes, and two of them can
make opposite claims about one part in two worlds: ``float`` rises in ``tank``
and falls in the default scene, which is a vacuum.

Relative names in a declaration -- ``sim-mujoco:mujoco``, ``:tilted`` --
resolve from the package the object is in, not from where the command was run,
so ``pc test -P //...`` run at the root of a tree resolves each of them the way
``pc sim`` in that package would.

``simulate:`` is not part of what the object is built from: declaring or
editing a simulation does not rebuild the object. The section's schema is under
:ref:`simulate`.

.. _sim-scenes:

================
Scenes as worlds
================

A simulation is never of an object alone: it is of an object *in a world*. That
world is an ordinary :ref:`scene <scenes>`, of any scene type, with one thing
about it that makes it a simulation scene -- it takes the object as a parameter.

The default scene
=================

``//builtin/scene:subject`` holds the object being simulated and nothing else.
It states no gravity, so a run in it is under the engine's own -- Earth's, along
-Z -- and no medium, so it is a vacuum. The floor the object stands on and the
light it is drawn in are not part of the scene: each engine's exporter writes
its own (see :ref:`sim-engines`).

Writing a simulation scene
==========================

When a simulation runs, PartCAD sets three parameters of the scene it names, and
a scene that is to hold the object declares them:

``subject``
  The full path of the object being simulated (``//package:part``). It is
  assigned whatever else the declaration says, which is what lets one scene
  serve every object that names it.

``subject_kind``
  ``part``, ``assembly`` or ``scene``, because an ASSY link names each with a
  key of its own (``part:``, ``assembly:``, ``scene:``). A scene placed in the
  world keeps every element of it a body of its own (see :ref:`sim-bodies`).

``subject_offset``
  The declaration's ``offset``, as seven numbers separated by spaces -- the
  translation, then the axis, then the angle. Not the location as it is written
  everywhere else, because a parameter value has to be spellable inside an
  instance name, where ``,`` and ``;`` are separators.

An ASSY file is a Jinja2 template (see :ref:`sim-templates`), and that is how
the scene places the object. This is ``tilted.assy`` from
``examples/feature_simulate``, whole:

.. code-block:: jinja

  {%- set offset = param_subject_offset.split() %}
  links:
    - {{ param_subject_kind }}: "{{ param_subject }}"
      name: subject
      location: [[{{ offset[0] }}, {{ offset[1] }}, {{ offset[2] }}], [{{ offset[3] }}, {{ offset[4] }}, {{ offset[5] }}], {{ offset[6] }}]

and its declaration, which gives each parameter a default so that the scene on
its own -- what ``pc render`` draws and ``pc ide view`` shows -- holds
something:

.. code-block:: yaml

  scenes:
    tilted:
      type: assy
      path: tilted.assy
      gravity: [2.539, 0, -9.476]   # 9.81 m/s^2, leaning 15 degrees towards +X
      parameters:
        subject:
          type: string
          default: stable
        subject_kind:
          type: string
          default: scene
        subject_offset:
          type: string
          default: "0 0 10 0 0 1 0"

A scene that declares no ``subject`` parameter cannot hold the object, and a
simulation that names one fails. Anything else the world needs -- a fixture, a
ramp, a bin -- is linked into the scene beside the subject, like any other part
of it.

Gravity, and the fluid a scene is filled with
=============================================

A scene may say what its world is like as well as where things are in it: the
gravity in it, and the fluid it is filled with.

.. code-block:: yaml

  scenes:
    tank:
      type: assy
      path: tank.assy
      gravity: [0, 0, -9.81]   # m/s^2, in the scene's own frame
      medium: :water           # a material, resolved the way a part's is

``gravity:`` is a vector, so a world whose Z axis is not up says so, and so does
a ramp with no edge -- ``tilted`` above is a level floor under a gravity that
leans, which for sliding is the same thing. ``medium:`` names a
:ref:`material <materials>`, and its ``density`` and ``viscosity`` are what the
engine drags and buoys a body with; ``//pub/std/manufacturing/material/fluid``
catalogues ``air``, ``water`` and ``seawater``. Both are optional, and leaving
them out is what every engine assumes: its own gravity, in a vacuum. The keys,
their units and what is refused are in :ref:`scenes`; what each engine makes of
a medium is in :ref:`sim-engines`.

A ``simulate:`` cannot ask the default scene for water. The fluid a part is
simulated in is a fact about the world, like the fixture it stands on, so a
package that wants its part under water writes a scene that is under water, as
``tank`` is. A medium parameter on the built-in scene would be a second way of
saying the same thing, resolved against ``//builtin/scene`` rather than against
the package that wrote it.

**Which gravity a run is under**, in order: the declaration's own
``params: {gravity: [...]}``, for that run; the scene's ``gravity:``; the
engine's default (MuJoCo's 9.81 m/s², SDFormat's 9.8, both along -Z).

.. _sim-bodies:

===================
What becomes a body
===================

Which parts of a world move together is the decision everything in a simulation
rests on, and PartCAD makes it from what the two kinds of arrangement already
mean: an **assembly** is a product somebody put together, and a **scene** only
states where things are.

.. list-table::
   :header-rows: 1
   :widths: 34 33 33

   * - How a link is placed
     - Inside an assembly
     - Inside a scene
   * - ``location:``
     - attached to what holds it
     - a body of its own
   * - ``connect:`` that keeps no degree of freedom
     - attached to what it is connected to
     - a body of its own
   * - ``connect:`` that keeps one (see :ref:`assy-joints`)
     - a joint to what it is connected to
     - a body of its own
   * - an assembly
     - attached or jointed by its link, as a part is; its own joints still move
     - one tree of bodies, its root free
   * - a scene (``scene:``)
     - not allowed
     - every element a body of its own, recursively

- **Every element of a scene is a body of its own**, and so is every element of a
  scene placed inside it. A scene's ``connect:`` places one object against
  another and attaches nothing, which is what makes a stack of blocks a scene:
  each block is where it is, and nothing holds it there.
- **Everything inside an assembly is attached.** Parts attached to each other are
  *one* rigid body -- there are no fixed joints -- whose mass, centre of mass and
  inertia are its parts' added up (see :ref:`sim-physics`). A connection that
  keeps a degree of freedom is a joint between two bodies, so an assembly is one
  body, or a tree of them on its joints.
- **An assembly placed in a scene** is one tree of bodies, and its root body is
  free.
- **An element marked** ``fixed: true`` is welded to the world -- a table, a
  tank's walls, a robot bolted to the floor. Free is the default, so without it
  every element of a scene falls under gravity. ``fixed:`` is a scene's to say:
  an assembly is fixed or free as a whole, by the link that places it in a scene,
  and fixing a scene fixes every element of it.

.. code-block:: yaml

  # workcell.assy, declared under 'scenes:'
  links:
    - part: bench
      fixed: true                  # stays where it is
    - assembly: robot              # one tree of bodies, its root bolted down
      fixed: true                  # where the bench's mount puts it - a scene's
      connect: {name: bench, with: base, to: mount}   # 'connect:' only places
    - scene: parts_tray            # every part in it a body of its own
      location: [[400, 0, 800], [0, 0, 1], 0]

A scene that is itself the claim -- a stack that stands, a pile that does not
slide -- declares ``simulate:`` the way a part does, and the world it is
simulated in places it with a ``scene:`` link, which ``subject_kind`` asks for.
``pc sim`` and ``pc test`` find one by its name, as they find a part. The ASSY keys are under
:ref:`assy-scenes`.

The rule is PartCAD's one copy of it, in the module the engine plugins import
for it (``kinematics.py``, beside ``mass_properties.py``): the bodies of a tree,
each with its parts, its frame, what it hangs off and its combined mass, and each
joint with its kind and the frames a format states one in. **MuJoCo writes
it**: `partcad-sim-mujoco`_ makes one MJCF body per body of the rule, welds a
``fixed: true`` element to the world, and writes every joint (see
:ref:`sim-mechanisms`), and so does the URDF export, a link per body and a
joint per pair (:ref:`sim-urdf`). **Gazebo does not yet**: a Gazebo run still makes every
part with geometry a free body of its own, which is the rule for a scene of
parts and not for the parts of an assembly. See :ref:`sim-limitations`.

.. _sim-mechanisms:

Mechanisms
==========

An assembly whose connections keep a degree of freedom is a **mechanism**, and
what it does can often be worked out on paper -- which makes it the kind of
claim a simulation is best at checking. ``examples/feature_simulate_joints`` is
a pendulum, checked against its closed form, beside one assembly of every other
kind of joint, checked against theirs (its ``README.md`` has the table):

.. code-block:: shell

  pc sim pendulum      # released horizontal, it passes the bottom at sqrt(2 g d / (I/m))
  pc sim nudged        # swinging 5 degrees, its period is 2 pi sqrt((I/m) / (g d))

Three things make one, and each is a declaration PartCAD already reads:

- **A joint.** A connection whose interfaces keep a freedom once joined --
  ``motion: revolute`` on the frame's ``axle`` interface, here -- is a joint
  between two bodies (see :ref:`assy-joints`). Name it with ``joint:``, since the
  name is what a validation reads: ``after["joints"]["swing"]["pos"]``.
- **Where it starts.** ``toParams`` places the joint where the run starts, and
  the parameter at zero is the joint's zero. The engine is told the same, so a
  reading of a joint is its value as PartCAD states it: the pendulum starts at
  ``90`` and passes ``0`` at the bottom.
- **What holds it.** An assembly placed in a scene is one tree of bodies whose
  root is free, so a pendulum in the scene PartCAD ships falls, frame and all.
  Simulate it in a scene that places it ``fixed: true`` -- the example's
  ``bolted`` -- and the root is welded to the world while the joints still
  move.

.. code-block:: yaml

  # bolted.assy, declared under 'scenes:', with the parameters the default scene takes
  links:
    - {{ param_subject_kind }}: "{{ param_subject }}"
      name: subject
      fixed: true
      location: ...

How each kind of joint is written -- a hinge or a slide per freedom, a ball,
an equality for a screw's thread or a ``mimic``; what of a joint's ``physics:``
is written and what is reported -- is in the plugin's documentation. Two things
are worth knowing when writing a claim:

- **Sample the run finely enough for the claim.** A validation that asks when
  something happened reads ``result["samples"]``; ``params: {samples: ...}``
  sets how many, and ``timestep`` how finely the engine steps between them. The
  pendulum reads every millisecond on a half-millisecond step in MuJoCo, and
  reads the instant it reaches the bottom *between* the two readings either
  side of it, which places it far more finely than either. That is also what
  lets one validation hold in Gazebo, whose readings are its pose messages, 60
  a second of the wall clock: a Gazebo run that asks for more than that is run
  slower than real time to get them, so the joint examples ask Gazebo for one
  every 21 ms or so, and each lands up to one message late.
- **The two bodies of a joint do not collide with each other.** A pin sits in
  its bore by design, and the engine is told so.

.. _sim-physics:

=================================
Materials and physical properties
=================================

Whether a stack stands, a float rises or a block slides is decided by what the
parts are made of as much as by their shape. The model an engine is handed
carries, for every part, its mass, its centre of mass and its inertia, its
sliding friction, and -- for a scene filled with a fluid -- the volume it
displaces and where that volume is centred. PartCAD works each of them out once,
the same way for every engine, for ``pc info`` and for the URDF export, so what
``pc info`` says a part weighs is what a simulation of it weighs.

What a part is made of
======================

A :ref:`material <materials>` is a set of facts about a substance, declared in a
``materials:`` section and shared like any other object. A simulation reads
three of them: ``density``, in kg/m³, which gives a part its mass, centre of
mass and inertia; ``mu``, the dimensionless coefficient of sliding friction; and
``viscosity``, in Pa·s, which only a fluid states. The standard catalogues
listed there cover the usual plastics, metals and fluids.

A part names its material with the ``material`` parameter, on the part types
that make one homogeneous body (see :ref:`parameters`), and the part type
records the answer as the ``material`` property of the shape it makes, which is
what every exporter reads. That is also how two parts built by one script can be
made of different things, as ``block`` and ``block_ptfe`` are in
``feature_simulate``:

.. code-block:: yaml

  parts:
    block:
      type: cadquery
      path: block.py
      parameters:
        material:
          type: string
          default: ":aluminium"   # or //pub/std/manufacturing/material/metal:al-6061-t6

Stating what the material cannot say
====================================

A part states a value under ``properties: physics:`` when its geometry and its
material cannot say it. A sealed float is drawn as the solid it displaces, but
it is hollow, so it states its mass; a float with a lead weight in its bottom
also states where it balances:

.. code-block:: yaml

  parts:
    buoy:
      type: cadquery
      path: block.py
      properties:
        physics:
          mass: 0.004                # kg
          centerOfMass: [0, 0, -6]   # mm, in the part's own frame

A stated value beats the material, because a measured part beats the substance
it is made of, and whatever the part does not state is still worked out: the
float above turns the way its solid says it does, at the weight it states.

Where each value comes from
===========================

Each value is the first of these that applies -- what the part states; what its
solid comes to at the density of its material; and, for an export only, the
export's ``density`` parameter or else 2700 kg/m³ (aluminium). Friction is what
the part states, or else its material's ``mu``, or else the engine's default.
The mass, the centre of mass and the inertia come from one density, so they
cannot disagree. The full order, and every property a part can state, is under
:ref:`properties`.

The volume a part displaces and that volume's centroid -- its centre of
buoyancy -- are always measured from the solid, never stated: a float states 3 g
and still pushes aside the whole 8 cm³ of its cube, and is lifted from the
cube's middle whatever its stated centre of mass. That difference between where
a body balances and where it is lifted is what turns ``buoy`` upright.

Two cases are worth knowing about. A part that names no material with a density,
and states no mass, has no known mass: ``pc info`` says so rather than inventing
one, while an export -- and so a simulation -- weighs it at 2700 kg/m³, because
an engine handed a body with no mass makes one up regardless. Give it a
material. And a part with no solid in it, an open mesh, has no volume to weigh
or to buoy.

What pc info shows
==================

``pc info`` reports all of this as ``MassProperties``: each value with its unit
and where it came from -- ``stated``, ``the material :aluminium``,
``derived: 8000 mm^3 at 2700 kg/m^3``, ``measured``. An assembly reports its
parts added up in its own frame and names any part it could not weigh, and the
material itself is reported as ``Material``, with its density and its friction.
See ``pc info`` in :doc:`cli`.

The values are cached, keyed on the part's geometry and on what they were
derived from, so an edit to the CAD, to the material's density or to a stated
value is picked up, and an edit to anything else costs nothing.

Every one of these quantities is SI except lengths, which are millimetres, and
angles, which are degrees -- the units every engine states them in, so nothing
is converted on its way into a model (see the note under :ref:`materials`).
They are plain numbers: a unit written into a value, ``"9.81 m/s^2"``, is not
accepted.

.. _sim-running:

====================
Running a simulation
====================

``pc sim``
==========

.. code-block:: shell

  pc sim block                # every simulation the part 'block' declares
  pc sim stable               # a scene, found by its name like a part
  pc sim -f sinks block       # one simulation, by name
  pc sim                      # everything this package declares
  pc sim -P ...               # and everything in the packages below it
  pc sim --json -S slippery   # and the whole of what the engine reported

It exits non-zero when a validation does not hold or a run cannot be made. A
declaration with no ``validation:`` is run and reported as having run, which is
how to look at what a plugin reports before writing the condition. Each run
gets a directory of its own under PartCAD's state directory, one per object and
simulation and emptied by the next run, holding the scene file the engine was
handed, its meshes, whatever the plugin wrote and the pictures it took (see
:ref:`sim-snapshots`). See ``pc sim`` in :doc:`cli` for every option.

Two of those options are about what is asked and what is kept:

.. code-block:: shell

  # The same claim, with Gazebo instead of the engine the declaration names
  pc sim stable --plugin //pub/feature/simulate/gazebo:gazebo
  # The state the run started from and ended in, as files
  pc sim -f sinks block --before before.yaml --after after.json

``--plugin`` runs a simulation with another plugin than the one it names;
everything else the declaration says -- the scene, the offset, the parameters,
the validation -- is asked of that plugin instead, and the answer is cached as
the different question it is. ``--before`` and ``--after`` write the two states
a validation is evaluated over, as YAML, or as JSON with ``--json`` or a path
ending in ``.json``. They write one simulation's, so name the object and, when
it declares several, the simulation with ``-f``.

.. _sim-test:

``pc test``'s ``sim`` check
===========================

``pc test`` holds an object to the same claims every time it runs, as its
``sim`` check -- ``pc test -f sim`` runs that check alone -- so a ``simulate:``
is checked whenever the package is tested rather than whenever somebody
remembers to ask. It runs a simulation through the same code ``pc sim`` does,
and shares its cache.

It applies to a part, an assembly or a scene that declares ``simulate:`` and to
nothing else, so a package of bolts pays nothing for it. The verdicts:

.. list-table::
   :header-rows: 1
   :widths: 62 38

   * - What happened
     - Verdict
   * - Every simulation the object declares ran, and every ``validation:`` held
     - pass
   * - A ``validation:`` did not hold, or could not be evaluated
     - fail
   * - A run could not be made: no ``simulation:`` named, a plugin or a scene
       that cannot be found, a simulator that will not install on this
       platform, a sandbox that will not build, a crash
     - fail
   * - A run did not finish within its budget (see :ref:`sim-timeouts`)
     - fail
   * - The plugin names a ``container:`` or a ``dockerImage``, and this machine
       has no container runtime
     - skip, with a ``WARNING`` carrying the whole report
   * - The declaration states no ``validation:``
     - skip when a package or a tree is tested; fail when the object is named

A failure names the object, the simulation and the reason. Not running is a
failure rather than a skip, for the reason the engineering analyses give (see
:ref:`engineering-analysis`): the object asked a question, and a plugin that
answered nothing has failed. The one excuse is a plugin that was never given the
environment it said it needs -- it named an image, and there is nowhere for an
image to run. MuJoCo is a wheel and its plugin names no image, so a MuJoCo run
that fails has failed on any machine; the Gazebo plugin names one, so a Gazebo
run that cannot be made on a machine with no container runtime is skipped. A
plugin or a scene that cannot be found is never excused: it is wrong wherever
the package is opened. A run that timed out is a failure for the same reason,
with the same one excuse: a run that hangs is a defect -- of the plugin, of the
model, or of how long the package says the run takes -- and skipping it would
pass a claim nobody can ever check.

A declaration with no ``validation:`` has nothing to be judged by, so ``pc
test`` does not run it, and what that costs depends on what was asked. Testing a
package, it is skipped with a ``WARNING`` saying why: the claim may be one
somebody is still writing, and the rest of the package deserves its verdict.
Testing the object by name -- ``pc test stable`` -- it fails: somebody asked
whether this object does what it says, and it says nothing.

``--fast-only`` passes over an object that declares a ``timeout:``, as it does
for every check. An object's simulations are checked where the object is tested
in its own right, and not again for every assembly whose manufacturability
check walks the parts it is made of.

.. _sim-timeouts:

When a run hangs or crashes
===========================

Every run has a **budget**: how long it may take, in wall-clock seconds, from
the moment the plugin's interpreter starts. Building the sandbox and installing
the engine into it come before that and are not counted, and neither is
exporting the scene. The budget is the first of these that says anything:

#. ``simulation.timeout`` in ``~/.partcad/config.yaml``, or
   ``PC_SIMULATION_TIMEOUT``: this machine's, over everything else -- the one
   setting for somebody who cannot edit the package, on a slow machine or in a
   CI job that would rather fail fast;
#. ``timeout`` in the declaration's ``params:``, for one simulation that is
   known to be slow (or quick);
#. ``timeout`` in the plugin's own declaration;
#. otherwise the larger of five minutes and ten seconds for every second of
   simulated ``duration``.

A value that is not a positive number of seconds is passed over, so the budget
can be moved and never switched off.

.. code-block:: yaml

  simulate:
    settles:
      simulation: sim-gazebo:gazebo
      params:
        duration: 120.0
        timeout: 1800        # half an hour of wall clock for two minutes simulated

.. code-block:: shell

  PC_SIMULATION_TIMEOUT=3600 pc test -f sim   # every run on this machine gets an hour

When the budget is spent the run is **stopped, with everything it started** --
the engine's server and whatever is watching it -- and fails, saying which
plugin, which budget, what set it and how to raise it:

.. code-block:: text

  ERROR: //pkg:stack: the simulation 'stands' failed: timed out after 300 s: //pkg/gazebo:gazebo
  did not finish within its budget of 300 s (the default: the larger of 300 s and 10 s for each
  of the 10 s simulated) and was stopped, with everything it started. If the run is simply slow,
  give it longer: 'params: {timeout: <seconds>}' on the simulation, or 'simulation.timeout' /
  PC_SIMULATION_TIMEOUT for every run on this machine

It is stopped from inside the sandbox, by the wrapper that runs the plugin,
because that is where the engine is: in the ``docker`` sandbox all PartCAD
started is a ``docker exec``. PartCAD keeps a bound of its own half a minute
longer, for a run so wedged that nothing inside it can act, and kills the whole
process tree when that one passes, on Windows too.

A plugin that dies instead -- a non-zero exit, a signal, output that is not an
answer -- fails with how it ended and the last lines it wrote to standard error,
which is where a traceback ends and a crash says what killed it:

.. code-block:: text

  ERROR: //pkg:stack: the simulation 'stands' failed: //pkg/mujoco:mujoco ended without an
  answer: killed by signal 11 (SIGSEGV). The end of what it wrote to standard error:
  ...

Whatever a plugin leaves running when it returns is stopped too, since a
process that outlives the run holds its output open and the run would last as
long as it does.

Neither a timeout nor a crash is cached, and ``pc test`` remembers no verdict
reached on one, so the next run tries again. The engine plugins add nets of
their own and stop a little before the budget is spent, to say how far they got:
the MuJoCo plugin stops a run whose state has diverged and names where, and the
Gazebo plugin stops waiting the moment its server dies and quotes what the
server said. Each one's README says what it checks.

.. _sim-snapshots:

Pictures of a run
=================

Every run is also asked for two pictures of the scene: one before anything
moved and one when the run is over. They are what the IDE's **Validation →
Simulation** tab shows side by side, and the one thing a reader can check a
verdict against without reading numbers -- a validation that passed for the
wrong reason, a block that fell *through* another rather than off it, is plain
to see in them.

They are taken from where the scene is looked at when it is rendered: the
``viewport_origin`` and ``viewport_up`` of its ``render: png:`` configuration,
read exactly as ``pc render -t png`` reads them -- the scene's own, or failing
that its package's -- and the corner a part is drawn from when neither says
anything. So a package that has said how its world is best looked at has said
it once, for both:

.. code-block:: yaml

   scenes:
     workcell:
       type: assy
       parameters:
         subject:
           type: string
           default: ""
       render:
         png:
           viewport_origin: [0, -100, 30]   # from the front, a little above
           viewport_up: [0, 0, 1]

The plugin is handed this in the request as ``snapshot`` -- the viewpoint, the
picture's ``width`` and ``height`` (the PNG's), and the name of the file each
picture goes to, relative to the directory the run may write into -- and says
which it drew in its result:

.. code-block:: python

   output = {
       "success": True,
       "before": {...},
       "after": {...},
       "snapshots": {"before": "snapshot-before.png", "after": "snapshot-after.png"},
   }

Pictures are optional. A plugin that cannot draw on the machine it runs on, or
that predates them, reports none and the run is exactly as good: no verdict
depends on a picture. ``pc sim`` says where the pictures of each run were
written, and ``--json`` lists them under ``snapshots``. Both plugins draw them
from their engine's own geometry at the engine's own poses, on the CPU, so a
picture needs no GPU in the sandbox.

.. _sim-caching:

Caching runs
============

A run is cached the way an engineering analysis is (see "Analyses, routes and
simulations" under :ref:`caching`): what the plugin reported together with the
whole run directory, so asking the same question again puts those files back
and runs nothing, and only a run that succeeded is kept -- never one that timed
out or crashed.

For a simulation the question is the scene -- which covers the object, a
parameter of it, and so its geometry and everything it is built from -- plus the
plugin and every option it resolved to, its environment, the declaration's
``params``, the exporter and its options, the pictures the run is asked to
take, and the content of every script involved. A ``medium:`` is in it as the
facts it resolved to rather than as a name, so a correction to the density of
``:water`` in the package that catalogues it runs the simulation again. The
pictures come back with a cached run like any other file it wrote, and a scene
looked at from somewhere else is a different question, which runs again.

A ``validation:`` is not part of the question: editing one re-judges the cached
run rather than repeating it, in ``pc sim`` and in ``pc test`` alike. ``pc
test``'s verdict is cached too, keyed on the declarations as written,
``validation:`` included, and on the key of every run it was judged on, so
nothing else changes it. A skip, a run that did not deliver, a declaration that
does not resolve and one with no ``validation:`` are worked out afresh every
time.

.. _sim-engines:

==============
Engine plugins
==============

An engine is a package, imported like any other dependency. Each of the two
PartCAD maintains declares four things about its engine's own format, because
they are one piece of knowledge: a reader for it (``import:``), a writer
(``export:``), the simulation (``simulation:``) and the application that opens
it (``open:``). Importing the package is what makes all four work at once.

.. list-table::
   :header-rows: 1
   :widths: 12 26 22 40

   * - Engine
     - Package
     - Simulation
     - Where the engine comes from
   * - MuJoCo
     - `partcad-sim-mujoco`_
     - ``sim-mujoco:mujoco``
     - the ``mujoco`` wheel, which PartCAD installs into the plugin's sandbox --
       nothing to install by hand
   * - Gazebo
     - `partcad-sim-gazebo`_
     - ``sim-gazebo:gazebo``
     - a ``gz`` on ``PATH`` or in a ROS installation, or else the container image
       the plugin names, which needs a container runtime

The names assume the package is imported as ``sim-mujoco`` or ``sim-gazebo``,
as every example here does. Each plugin's repository documents its engine in
full; what follows is what a claim depends on.

What a run is
=============

Before the plugin starts, PartCAD builds the scene with the object in it and
writes it out in the engine's format, with every part's mass, inertia and
friction in it and, for a scene that states them, its gravity and its medium.
The plugin is handed that file, steps it for ``duration`` seconds of simulated
time, and reports the state of the world before and after (see
:ref:`sim-validation`).

**What is free in a run is free to move.** The plugin asks the export for
that, through the ``formatOptions`` of its declaration -- ``static: false`` --
since a file written to be looked at welds every body to the world instead. In
MuJoCo, the bodies are the ones :ref:`sim-bodies` says: every element of a scene
is a body of its own, an assembly is one tree of bodies on its joints, and an
element marked ``fixed: true`` is welded to the world. In Gazebo every part with
geometry is still a rigid body of its own, which is the rule for a scene of
parts and not yet for the parts of an assembly (see :ref:`sim-limitations`).
Each exporter also writes a ground plane under the world and a light over it.

The parameters both plugins take, as fields of the plugin's declaration or for
one run in a declaration's ``params:``:

.. list-table::
   :header-rows: 1
   :widths: 16 18 66

   * - Parameter
     - Default
     - Meaning
   * - ``duration``
     - ``10.0``
     - Seconds of simulated time to run for.
   * - ``timestep``
     - the engine's
     - The integration step, in seconds.
   * - ``gravity``
     - the scene's
     - In m/s², in the scene's frame; overrides the scene's ``gravity:`` for
       this run.
   * - ``samples``
     - ``0``
     - Report the state at this many evenly spaced instants as well, as
       ``samples``.
   * - ``timeout``
     - see :ref:`sim-timeouts`
     - The run's budget, in wall-clock seconds. PartCAD stops the run when it
       is spent; both plugins stop a little before, to say how far they got.

Friction and contact
====================

Each part's friction coefficient is written into every format in its own
spelling -- MJCF's first ``friction`` component, SDFormat's
``<surface><friction><ode><mu>``, URDF's ``<gazebo><mu1>`` -- and is the same
dimensionless number in all of them. A part that states no friction and names no
material with a ``mu`` gets the engine's default, which is a number nobody
chose.

A contact has two sides, and how their coefficients combine is the engine's
model rather than the part's. The two engines do not agree:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Engine
     - The coefficient of a contact between A and B
   * - MuJoCo
     - the **larger** of the two (no exporter here sets the ``priority`` that
       would change that)
   * - Gazebo (DART)
     - the **smaller** of the two

So two blocks of one material meet at that material's ``mu`` in both. A block
on the floor does not: the ground plane each exporter writes states no friction,
which is 1.0 in both formats, so in MuJoCo every block grips the floor at 1.0 or
more, and in Gazebo at its own ``mu`` or less. In ``slippery``, run in MuJoCo, it
is the top PTFE block that slides off the bottom one, and not the stack along
the floor.

MuJoCo's contacts are soft: a body under a steady sideways load slips at a small
steady rate even well inside its friction cone, and with MuJoCo's own defaults
an aluminium stack slid apart in a world tilted by only 6 degrees. So the MJCF
exporter writes MuJoCo's own remedies into every model -- elliptic friction
cones, an ``impratio`` of 10 and three NoSlip iterations, which are its
``cone``, ``impratio`` and ``noslip_iterations`` parameters -- and with them a
stack holds or slides as its friction says. Measured that way, two 20 mm cubes
in ``tilted`` for ten seconds, with nothing changed but the coefficient both are
given:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Sliding friction
     - What happens to the top block
   * - 0.04 (PTFE)
     - slides 69 mm and falls 20 mm, its own height, to the floor
   * - 0.1
     - slides 63 mm and falls
   * - 0.2
     - slides 56 mm and falls
   * - 0.25
     - slides 32 mm and falls
   * - 0.28
     - slides 34 mm and falls
   * - 0.3
     - stays: 0.5 mm of creep, 0.4 mm of settling
   * - 0.4
     - the same
   * - 1.05 (aluminium)
     - the same

A block on a 15-degree slope slides when its friction is below tan 15°, 0.268;
MuJoCo's soft contacts put the line a little higher, between 0.28 and 0.3, so a
claim close to a threshold needs margin. On a level floor with gravity straight
down every row stays put, PTFE included, because nothing pushes a block sideways.

``friction2``, a coefficient across a second direction, travels between SDFormat
and URDF. MJCF has no second direction -- its other two ``friction`` components
are torsional and rolling coefficients, which are different quantities -- so a
``friction2`` is reported as one MJCF cannot state, and torsional and rolling
friction in an MJCF file that is read are counted as dropped.

A scene filled with a fluid
===========================

What the two engines make of a scene's world:

.. list-table::
   :header-rows: 1
   :widths: 46 27 27

   * - Effect
     - MuJoCo
     - Gazebo
   * - the scene's ``gravity:``
     - modelled
     - modelled
   * - drag, from the fluid's density and viscosity
     - modelled
     - not modelled
   * - buoyancy, ρ · V · g
     - modelled
     - not modelled
   * - acting at the centre of buoyancy, so that a body with its weight low down
       rights itself
     - modelled, in ``pc sim``
     - not modelled
   * - a free surface: floating at a waterline, partly submerged
     - not modelled
     - not modelled
   * - added mass, lift, the Magnus effect
     - not modelled
     - not modelled

**MuJoCo** is handed the fluid's density and viscosity, which turn on its
passive fluid model: drag, quadratic in speed from the density and linear from
the viscosity, acting on the box each body's mass and inertia describe. That
model has no buoyancy at all, so the MJCF exporter adds it, as Archimedes has
it: a lift of the fluid's density times the volume PartCAD measured times
gravity, acting at the centre of buoyancy. Where that point is not the centre of
mass, the lift turns the body, which is what rights ``buoy``: released tilted 60
degrees in ``tank``, it turns its heavy side down within a second. The lift's
turning moment is applied by the plugin at every step of a run, so the same
model opened in MuJoCo's own viewer floats but does not right itself.

**Gazebo** writes the scene's gravity and nothing for its medium, and its export
says so: the buoyancy system Gazebo Harmonic has measures a mesh without its
scale, which would buoy PartCAD's millimetre meshes by a billion times their
volume, and a world that names any system of its own loses all of Gazebo's
default ones. A Gazebo run of a scene filled with water is a run in a vacuum.

Writing a plugin of your own
============================

A simulation plugin is declared the way an export implementation is -- a script,
the sandbox it needs, and its parameters -- and the contract is narrow: a scene
with the object in it goes in, as a file in the format the plugin names, and
JSON carrying ``before`` and ``after`` comes out -- and, if it can draw them,
the two pictures of :ref:`sim-snapshots`. See :ref:`simulate`.

The exporter that writes that file is handed the scene's tree (``decode:
false``), and whatever it writes, which nodes are one body and how the joints
between them move are not its to work out: ``kinematics.bodies()`` -- importable
in its sandbox the way ``mass_properties`` is -- answers both, the same way for
every format, from what each node of the tree says it holds (``kind``), whether
it is ``fixed``, and its ``joint``.

.. _sim-validation:

====================
Writing a validation
====================

``validation:`` is one Python expression, evaluated over three names:

``before`` and ``after``
  The state of the world when the run started and when it ended, as the plugin
  reported it.

``result``
  The whole of what the plugin returned, ``before`` and ``after`` included.

It may call the builtins that work over numbers and collections -- ``abs``,
``all``, ``any``, ``min``, ``max``, ``sum``, ``len``, ``zip``, ``sorted``,
``round``, ``pow``, ``range``, ``enumerate``, ``map``, ``filter`` and the type
constructors -- and nothing else: no imports, no ``math``, nothing that reaches
the filesystem (``x ** 0.5`` is a square root). That is not a security boundary;
it is what keeps a validation readable as an assertion. An expression that
raises is a validation that did not hold, and is reported with the exception.

What the plugins report
=======================

PartCAD reads nothing inside ``before`` and ``after``: what is in them is the
plugin's vocabulary. The two plugins PartCAD maintains report the same one, so a
validation reads the same against either engine:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Content
   * - ``time``
     - Simulated seconds at the reading.
   * - ``bodies.<name>.pos``
     - The body's position, ``[x, y, z]`` in **millimetres**, in the world's
       frame -- for a body hanging off a mechanism as much as for one standing
       free, in either engine.
   * - ``bodies.<name>.quat``
     - The body's orientation, ``[w, x, y, z]``, in the world's frame.
   * - ``joints.<name>.type``
     - ``revolute``, ``continuous`` (a turn with no limit), ``prismatic`` or
       ``ball``. Moving to the joint's PartCAD type (:ref:`joints`), keyed by
       PartCAD's joint name, as the engine plugins take up the native joint
       types: ``continuous`` then reads ``revolute``.
   * - ``joints.<name>.pos``, ``joints.<name>.vel``
     - Degrees and deg/s for a turn, millimetres and mm/s for a move. A ball
       joint reports ``quat`` and an angular velocity ``[x, y, z]`` in deg/s
       instead.
   * - ``joints.<name>.effort``
     - What the model's actuators exert along the joint, in N·m or N. MuJoCo
       only.
   * - ``bodies.<name>.loads``
     - What acts on the body: its weight, its contacts, the force and the moment
       each of its joints passes it. See :ref:`sim-loads`.
   * - ``bodies.<name>.mass``, ``com``, ``acc``, ``angvel``, ``angacc``
     - Its mass in kg, its centre of mass in mm, how that is accelerating in
       m/s², and how fast the body turns and how fast that changes, in deg/s and
       deg/s² -- all in the world's frame.

A body is named after the link that places it -- an ASSY link's ``name:`` --
and made unique where two would collide. Walking every body, ``for name in
before["bodies"]``, is the robust form, and the one every example uses.

**A validation reads PartCAD's names**, whatever the engine's file had to call
things. Each format has rules of its own about names -- SDFormat reserves
``world``, which is what PartCAD's default world is called, and MJCF has a body
called ``world`` of its own -- so a name the file cannot hold is written there
under another one (``world-2``), the export says so in a warning, and the run
reports it under PartCAD's name again: ``after["bodies"]["world"]`` for a body
called ``world``, in MuJoCo and in Gazebo alike. What the engine called it is in
``<scene file>.names.json`` in the run's directory, if you need it.

A free body is not reported as a joint, since ``bodies`` already says where it
is; so a scene of parts reports ``joints: {}``. A mechanism's joints are
reported under the names PartCAD gives them (see :ref:`sim-mechanisms`), and
a joint the engine writes as several -- a screw's turn and move -- as
``<name>.<parameter>`` each. A joint's ``pos`` is its value as PartCAD states
it: the ``toParams`` it starts at, and nought at its zero.

Beside ``before`` and ``after``, ``result`` carries ``samples`` -- a list of the
same readings at evenly spaced instants, when the run asked for any -- and what
the run was: which engine ran it, the ``duration``, the ``gravity`` it was
actually under in m/s², and the ``medium`` for a MuJoCo run in a fluid. Whatever
the engine could not report is named in ``warnings`` rather than reported as
zero.

.. _sim-loads:

What holds each body, and how hard
==================================

Every body in a reading says what acts on it, as ``loads`` -- the loads a stress
analysis of the body, or of a part in it, starts from. Each load is one thing
acting on the body:

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - ``kind``
     - What it is
   * - ``joint``
     - What one of its joints passes it: the joint to the body it hangs from,
       and each joint of a body hanging from it. ``joint`` names it.
   * - ``fixed``
     - What holds a body a scene fixes: its weld to the world.
   * - ``contact``
     - Every contact with one other body, added up; ``contacts`` says how many.
   * - ``gravity``
     - Its weight, at its centre of mass.
   * - ``buoyancy``
     - The lift of the fluid it is in, at its centre of buoyancy.

and says where it comes from (``from``: the body at the other end, ``world`` for
the world and the ground, the body itself for its weight and its lift), where it
acts (``at``, mm, in the world's frame), the ``force`` on *this* body in N, and
the ``torque`` about ``at`` in N·m, both in the world's frame:

.. code-block:: json

  "upper": {
    "pos": [0.0, 126.8, 530.4], "quat": [0.5, 0.5, 0.5, 0.5],
    "mass": 0.864, "com": [0.0, 432.3, 568.3],
    "acc": [0.0, 0.0, 0.0], "angvel": [0.0, 0.0, 0.0], "angacc": [0.0, 0.0, 0.0],
    "loads": [
      {"kind": "joint", "from": "subject", "joint": "knee", "at": [-39.7, 126.8, 530.4],
       "force": [0.0, 0.0, 8.48], "torque": [2.59, -0.337, 0.0]},
      {"kind": "gravity", "from": "upper", "at": [0.0, 432.3, 568.3],
       "force": [0.0, 0.0, -8.48], "torque": [0.0, 0.0, 0.0]}
    ]
  }

A joint's load is everything it passes from one body to the other: what its
constraint holds against, and what its spring, its damper, its friction and an
actuator on it exert along the freedom it keeps. So a hinge held by a stiff
spring -- a worm drive that does not back-drive, say -- reports the moment that
holds the arm up, and a hinge with nothing on it reports none about its axis.
The body hanging from a joint reports its load from the body above, and the body
above the same load reversed. A free body's six freedoms pass nothing, and are
not a load.

**They add up**: the forces on a body are its ``mass`` times its ``acc``, and a
validation can say so -- the knee above carries the arm's weight and the moment
of it, with the arm at rest:

.. code-block:: python

  (
      abs(next(l for l in after["bodies"]["upper"]["loads"] if l["kind"] == "joint")["force"][2]
          - after["bodies"]["upper"]["mass"] * 9.81) < 0.01
  )

**Which body a part is in.** A body is the parts welded together (see
:ref:`sim-bodies`), so a load on a body is not yet a load on any one part in it.
``result["parts"]`` says which body each part is in: each part by its path of
labels (``subject/lower/knee-worm-gear/gear``), the part it is, the body, and
where it sits in that body's frame. With the body's pose in a reading that is
where the part is, which is what turns a body's loads into a part's -- the
``/pc:sim-assembly-fea`` skill does that, and writes the part a stress analysis
that applies them (:ref:`pc cae <cae>`). What passes between two parts welded
into one body is the body's own business: a rigid simulation does not see it,
and says nothing about it.

A run that asks for poses alone says ``params: {loads: false}``. MuJoCo reports
every load; Gazebo reports what its joints transmit and each body's weight, and
says in ``warnings`` what it cannot (see :ref:`sim-engines`).

Some validations
================

No body moved 5 mm in any direction:

.. code-block:: python

  max(
      sum((a - b) ** 2 for a, b in zip(after["bodies"][n]["pos"], before["bodies"][n]["pos"])) ** 0.5
      for n in before["bodies"]
  ) < 5.0

Something ended up more than 5 mm lower than it started -- a block fell off:

.. code-block:: python

  max(before["bodies"][n]["pos"][2] - after["bodies"][n]["pos"][2] for n in before["bodies"]) > 5.0

Everything rose more than 100 mm -- it floats:

.. code-block:: python

  min(after["bodies"][n]["pos"][2] - before["bodies"][n]["pos"][2] for n in before["bodies"]) > 100.0

Upright at the end -- the vertical component of a body's own Z axis, worked out
from ``quat``, is 1 when it is upright and 0 when it lies on its side:

.. code-block:: python

  all(
      1 - 2 * (after["bodies"][n]["quat"][1] ** 2 + after["bodies"][n]["quat"][2] ** 2) > 0.9
      for n in before["bodies"]
  )

Held at every sampled instant and not only at the end -- nothing rose or sank
5 mm on the way -- with ``params: {samples: 20}``:

.. code-block:: python

  all(
      abs(s["bodies"][n]["pos"][2] - before["bodies"][n]["pos"][2]) < 5.0
      for s in result["samples"]
      for n in before["bodies"]
  )

Choose thresholds well clear of both outcomes. A stack that holds still creeps
and settles by half a millimetre, because contacts are soft; a block that comes
off moves tens. A threshold between the two, like the 5 mm above, says which
happened and nothing else.

.. _sim-formats:

=========================
Robot description formats
=========================

The machinery that writes a world out for an engine also reads and writes the
formats robots and worlds are described in, so a model somebody else wrote is an
object you can place parts in, and an object built out of parts is a model an
engine can run.

.. _sim-urdf:

URDF
====

`URDF <https://wiki.ros.org/urdf>`_ is the one of these PartCAD implements
itself, because it describes a robot rather than any one engine's world, and
ROS, MuJoCo, PyBullet and Isaac all read it.

Reading one
-----------

.. code-block:: shell

  pc add assembly urdf robot.urdf   # declare it: the URDF stays a URDF, read in place
  pc import assembly robot.urdf     # convert it: parts, interfaces and an .assy

``add`` declares an assembly of type ``urdf``. Its links become parts named
``<assembly>/<link>`` -- ordinary parts, which ``pc ide view robot/forearm`` and
``pc export -t step robot/wrist`` work on like any other -- placed with every
joint at zero, but for a joint whose limits leave zero out: a legged robot's
knee that cannot straighten, a gripper that cannot close to nought. Such a joint
starts at the bound nearest zero, where the robot can stand, rather than against
its own stop, which would fail ``pc test``'s ``connect`` check; and the links
below it are placed with it there. A link's ``<inertial>``, the friction and contact settings of its
``<gazebo>`` block and its ``<material>`` become named properties of its part,
in PartCAD's units, and are written back on export. URDF that PartCAD has no
property for stops the import, naming what it found, rather than being carried
along unread. How links become parts, which of a link's shapes is used, and the
declaration's options are under :ref:`assembly-urdf`.

Its **joints are the assembly's**, so a ``urdf`` assembly is a mechanism as it
is read, without converting it: each movable joint is the joint of the link it
moves, with its axis, limits, dynamics, soft limits and mimic (``pc info
robot`` lists them, as it does an ASSY assembly's), and each link on a fixed
joint is welded to its parent -- one rigid body with it, which turns when the
parent does (:ref:`sim-bodies`). A joint with no ``<axis>`` turns about URDF's
default, X. A link with no geometry is no part, so the joints on either side of
it are one joint of their freedoms together, named after the first.

``import`` converts instead, the way ``pc convert assembly -t assy`` does below,
and leaves the package holding PartCAD's own objects with nothing pointing back
at the URDF.

.. _sim-urdf-export:

Writing one
-----------

.. code-block:: shell

  pc export -t urdf -a robot   # robot.urdf, plus a directory of the STL meshes it references

The export writes the mechanism the assembly is: **a link per rigid body** and
**a joint per pair of bodies**, by the rule of :ref:`sim-bodies`. Every part
welded into a body is a ``<visual>`` and a ``<collision>`` of its link, at its
place in the link and named after the part, so a link of several shapes -- a
URDF's, read in, or several parts bolted together -- goes out as itself; a shape
used more than once is written once. An assembly's root body is the URDF's root
link, named after the one part it is made of when it is made of one (a robot's
base) and after the assembly otherwise. A part on its own is one link, and an
assembly in which nothing moves is one link of all its parts. Links and joints
keep PartCAD's names wherever URDF's readers can hold them; a name they cannot
-- a link called ``world``, which Gazebo, ROS and MoveIt all take to be the
world itself, or one with a ``/`` or a space in it -- is written under the
nearest one they can (``world-2``, ``a_b``), and the export says which.

Every link carries the mass, centre of mass and inertia of its body -- its
parts' added up, each at its own density, or what a measured link states about
itself (:ref:`sim-physics`) -- in ``<inertial>``, its friction and contact
properties in a ``<gazebo>`` block, and each shape's material and colour in its
``<material>``.

Each joint is written by its type (:ref:`joints`):

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - The joint is
     - In URDF
   * - ``revolute``, bounded on either side
     - ``revolute``, with ``<limit>``
   * - ``revolute``, bounded on neither
     - ``continuous``
   * - ``prismatic``
     - ``prismatic``, with ``<limit>``
   * - ``planar``, the moves first or the turn first
     - ``planar``, its ``<axis>`` the normal
   * - ``floating``: a body of its own
     - ``floating``, from the link of the body it was connected to
   * - ``cylindrical``, ``screw``, ``universal``, ``ball`` or ``composite``
     - **refused**: URDF has no type for it

A refusal is an error that names every joint the URDF cannot hold, its type, and
the ways on: simulate the mechanism in MuJoCo, which writes every type; or model
the body the joint stands for -- for a cylindrical pair a sleeve and its carriage,
for a universal joint the cross -- and join it by native joints. Nothing is
written with a mass PartCAD did not derive.

A URDF that is read **only for its kinematics** -- by ROS's
``robot_state_publisher`` or by MoveIt -- can have them all the same:

.. code-block:: yaml

  export:
    urdf:
      composites: massless   # default: refuse

writes each such joint as a ``revolute``, ``continuous`` or ``prismatic`` joint
per freedom through links with no ``<inertial>`` named ``<joint>_link1``,
``<joint>_link2`` ..., which is URDF's own idiom for a frame; a screw's move is a
``<mimic>`` of its turn by the lead. Every simulator that reads a URDF drops or
refuses those links (libsdformat leaves out a link with no ``<inertial>`` and its
joints), so the export says so, joint by joint.

Frames and units:

- **The child link's frame is the joint's moving frame**, so ``<axis>`` is the
  freedom's own axis as its parameter's ``dir`` states it, and every part sits in
  its link where the joint leaves the body. A URDF converted to ASSY and exported
  again comes back with its own link frames and axes.
- **Metres and radians** at the boundary and nowhere else: limits, velocities,
  soft limits and a mimic's offset are converted from millimetres and degrees;
  ``<dynamics>`` (``damping``, ``friction``) is already per radian or per metre
  in SI, as PartCAD states it (:ref:`assy-joints`). ``maxEffort`` and
  ``maxVelocity`` are ``<limit effort velocity>``, a joint's ``softLimits`` its
  ``<safety_controller>``, its ``mimic`` a ``<mimic>``, and the solver settings
  of its ``physics:`` (``springStiffness``, ``stopCfm``...) its ``<gazebo>``
  block.
- **The root.** A free root body is the URDF's root link, placed where the tree
  places it. A body welded to the world (a scene element marked ``fixed: true``)
  hangs off a link named ``world`` by a ``fixed`` joint, which is how a URDF says
  "bolted down"; and since a URDF has one root, the free bodies of a scene of
  several hang off ``world`` by ``floating`` joints.

What a URDF cannot state is **reported**, never dropped in silence:

- **the starting value** of a joint (what ``toParams`` sets it to): URDF has no
  starting position, and what reads one -- ROS's tools, a robot's drivers --
  takes a joint's zero to be where its hardware reads zero, so the robot is
  written at PartCAD's zero of every joint rather than re-zeroed at its start;
- **a chain through massless links**, under ``composites: massless``, and a screw
  written as one, as approximate, since few simulators honour a ``<mimic>``;
- **a default**: URDF requires ``<limit effort velocity>`` on a ``revolute`` and a
  ``prismatic`` joint, and one that states no ``maxEffort`` or ``maxVelocity``
  gets the export's ``effort`` (1000 N·m or N) and ``velocity`` (100 rad/s or
  m/s) -- large enough to limit nothing a passive mechanism does. URDF has no
  open bound: a ``revolute`` open on one side, or a ``prismatic`` on either, is
  written a million degrees or millimetres away there;
- the bounds of a ``planar`` or a ``floating`` joint's freedoms, a ball's one
  bound, the soft limits or mimic of a joint written as a chain, and a property
  PartCAD holds that URDF has no element for;
- ``dummyMass`` or ``dummyInertia``, where a package still passes them: the
  export took them once, for links of a mass nobody measured, and writes none.

``effort``, ``velocity`` and ``composites`` are parameters of the export, set in
a package's own ``export:`` entry for ``urdf`` like any other
(:ref:`output-files`).

Converting
----------

.. code-block:: shell

  pc convert assembly -t assy robot   # urdf -> assy
  pc convert assembly -t urdf logo    # assy -> urdf

``pc convert assembly`` rewrites the package rather than producing a file. To
URDF, it writes the ``.urdf`` and its meshes and switches the declaration over.
To ASSY, it writes an ``stl`` part for every link, an interface pair for every
joint, and an ``.assy`` that places the parts with ``connect:`` -- an assembly
stated the way PartCAD states one, not a transcription of coordinates.

.. _sim-urdf-joints:

How joints become interfaces
----------------------------

Each URDF joint becomes a pair of :ref:`interfaces <interfaces>`, and each link
is connected to its parent through them:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - URDF
     - PartCAD
   * - the joint, parent side
     - a **socket** interface with one port, which the parent part implements at
       the joint's origin, under an instance named after the joint
   * - the joint, child side
     - a **plug** interface, which the child part implements at its own origin,
       with ``mates:`` naming the socket
   * - ``axis``, ``limit`` lower and upper
     - a freedom-of-movement parameter of the socket per degree of freedom --
       ``angle`` for a revolute or continuous joint, ``offset`` for a prismatic
       one, ``moveX``, ``moveY`` and ``turnZ`` for a planar one about Z, all six
       for a floating one -- whose ``dir`` is the URDF axis and whose range is
       the limits in degrees or millimetres; and ``motion: {dof: [...]}``
       naming them. A continuous joint's parameter states no range, which is
       how an open bound is stated: it is a ``revolute`` open on both sides,
       and nothing writes ``continuous`` into the package.
   * - ``safety_controller``, ``mimic``
     - ``motion: {softLimits, mimic}``
   * - ``limit`` effort and velocity, ``dynamics``
     - ``physics: {maxEffort, maxVelocity, damping, friction}``
   * - a joint's ``<gazebo>`` block
     - ``physics: {springStiffness, springReference, stopCfm, ...}``
   * - ``calibration``
     - nothing: a reference for commissioning a real robot, which says nothing
       about the model; counted and reported
   * - the child link's attachment
     - ``connect: {with: <plug>, name: <parent>, to: <socket>, toInstance: <joint>,
       joint: <joint>}``, so the joint keeps the URDF's name

The parent implements the socket exactly at the joint's origin, so the numbers in
the ``.assy`` can be checked against the URDF. The socket's port is the half turn
that two connected ports face each other by, which a connection undoes: the frame
the parameters are read in is the URDF joint frame itself, so each ``dir`` is the
URDF axis as the URDF states it -- URDF's default of X where it states none -- and
an export writes the URDF's own frames back. Limits are converted from radians and
metres once, on the way in. A fixed joint's socket declares ``dof: []``, and its
child is welded to its parent.

Joints of one kind -- the same type, axis, limits, dynamics and mimic -- share
one interface pair, since what differs between them is where they are, which is
the instance's location: a four-wheeled robot gets one pair for its wheels.
Nothing is matched against the library of real interfaces, because a URDF joint
says nothing about the hardware that implements it.

The parameters are what let the assembly be **posed**: ``connect: {toParams:
{angle: 90}}`` places the child where the URDF joint at 90 degrees would, and
everything below it follows; it is also the joint's starting value
(:ref:`assy-joints`). The converter writes one itself for a joint whose limits
leave URDF's zero out: such a joint starts at the bound nearest zero, which is
its parameter's ``default`` and its connection's ``toParams``, so the converted
assembly is drawn with that joint there -- as the robot can stand, and as a
``urdf`` assembly reads it. Its export is still the URDF at its own zero.

.. _sim-urdf-round-trip:

What a round trip keeps
-----------------------

A URDF read as a ``urdf`` assembly and exported is the robot it was, and so is
one converted to ASSY and exported, except that the converter folds a chain of
movable joints through a link with no geometry into its last joint, and says so:
every movable joint under its name, with its
type, its frame, its axis, its limits, its dynamics, its soft limits and what it
mimics, and every shape where it was. An ASSY assembly exported and read back is
the mechanism it was, joint for joint. What changes is what PartCAD and URDF
mean by a link:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Kept
     - Lost, or changed
   * - every movable joint: name, type, frame, axis, limits, effort, velocity,
       dynamics, soft limits, mimic, and the joint's ``<gazebo>`` settings
     - the starting value of a joint, which URDF has no place for; the URDF is
       the robot at zero
   * - every link that is a rigid body of its own, under its name
     - a link on a fixed joint: it is one body with its parent, so it comes back
       as a shape of the parent's link, where it was
   * - the kinematics of a chain through a link with no geometry, read as a
       ``urdf`` assembly
     - that link's name: it composes into a joint URDF has no type for (two
       turns through it are a universal joint), which comes back under
       ``composites: massless`` as the chain it was, through a massless link
       named after the joint; converted to ASSY, the chain is folded into its
       last joint
   * - a cylindrical, universal, ball or screw joint, under
       ``composites: massless``, as a chain through massless links, read back
       as the joint it was
     - the joint's single native element; a screw's coupling is a ``<mimic>``
       few simulators honour; and, without the option, the export, which
       refuses
   * - every shape, at the placement it had, under the name of its part within
       its link
     - every name that carries a package path, which a ROS name cannot; nesting:
       an ASSY may group its parts, and a URDF's only grouping is its links
   * - geometry, as a triangle mesh
     - exact B-rep geometry; the mesh is a tessellation at a chosen tolerance
   * - shape sharing: one mesh, many links
     - parametrization: an ASSY parameter, an enrich, an alias
   * - mass, inertia, friction, contact settings and appearance -- per body,
       combined from its parts
     - which part in which package a link came from -- the digital thread itself

``pc convert assembly -t assy`` keeps all of that as interfaces and connections,
with one more loss: a chain of joints through a link with no geometry is folded
into the placement of the last of them, and said to be. The geometry a link was
not built from becomes a part of its own, ``<assembly>/<link>/<visual|collision>``,
and what an assembly cannot hold -- transmissions, sensors, ``ros2_control``
blocks -- is counted and reported at import and in ``pc info``, so the loss is
visible rather than silent.

.. _sim-engine-formats:

SDFormat and MJCF
=================

`SDFormat <http://sdformat.org/>`_, what Gazebo describes a world in, and
`MJCF <https://mujoco.readthedocs.io/en/stable/XMLreference.html>`_, what MuJoCo
describes a model in, are read and written the same way URDF is -- but by the
engine's plugin package rather than by PartCAD, so a package imports the plugin
and names the format through it:

.. list-table::
   :header-rows: 1
   :widths: 14 26 30 30

   * - Format
     - Package
     - Declared as
     - Written by
   * - SDFormat
     - `partcad-sim-gazebo`_
     - a scene of type ``sim-gazebo:world``
     - ``pc export -t sim-gazebo:world``
   * - MJCF
     - `partcad-sim-mujoco`_
     - a scene or an assembly of type ``sim-mujoco:mjcf``
     - ``pc export -t sim-mujoco:mjcf``

.. code-block:: yaml

  dependencies:
    sim-gazebo:
      type: git
      url: https://github.com/partcad/partcad-sim-gazebo.git
      track: main

  scenes:
    warehouse:
      type: sim-gazebo:world
      path: warehouse.world

A bare ``type: world``, or ``pc export -t mjcf``, resolves to nothing and says
which package to name. A world is always a scene; an MJCF file can be either,
and the section that declares it says which (see :ref:`scenes`, which also has
each reader's options).

.. code-block:: shell

  pc export -t sim-gazebo:world workcell              # a scene, as a Gazebo world
  pc export -t sim-mujoco:mjcf workcell               # or as an MJCF model
  pc convert scene -t assy warehouse                  # a world's shapes become parts of this package
  pc import scene -t sim-gazebo:world warehouse.world # the same, for a file not declared yet

Both readers are best-effort in the way the URDF one is: what a static
arrangement cannot hold -- joints, lights, sensors, actuators, engine plugins --
is counted and reported, and ``pc info`` lists it. A file written for looking at
is not one written for running: by default each exporter welds every body to
the world, because a scene on its own states where things are, and a simulation
asks the export for the opposite. What each format keeps, and every export
parameter, is documented in the plugin's repository, including the parts of
MJCF that are easy to get wrong (angles are degrees by default, an orientation
has five spellings, and a box's ``size`` is its half-extents).

.. _sim-templates:

Every description is a template
===============================

A URDF, a ``.world`` and an MJCF model are rendered as `Jinja2
<https://jinja.palletsprojects.com/>`_ templates before they are read, exactly
as an ASSY file is, so one file can describe a family of robots or worlds. The
parameters reach every one of them under the same names: ``param_<name>`` for
each parameter the object declares, and ``name`` for the object's own name.

.. code-block:: yaml

  scenes:
    cell:
      type: sim-mujoco:mjcf
      path: cell.xml
      parameters:
        conveyor_length: 2.0

.. code-block:: xml

  <body name="conveyor">
    <geom type="box" size="{{ param_conveyor_length / 2 }} 0.3 0.05"/>
  </body>

The rendered file is written under PartCAD's own state directory, never beside
the original, and the file is used as it is when rendering changes nothing. What
it references keeps resolving against the directory the package declared it in,
so a ``package://`` mesh, a ``model://`` include or an MJCF ``<asset>`` file
works in a template as it does outside one.

.. _sim-opening:

==============================
Opening a scene in a simulator
==============================

.. code-block:: shell

  pc ide open --with gazebo warehouse.world   # a Gazebo world, in Gazebo
  pc ide open --with mujoco stack.xml         # an MJCF model, in MuJoCo

Both open a window on the machine the command was run on -- from an
installation there, or with ``--use-docker`` from a container when there is
none -- and never on the daemon's machine, which can be somebody else's. The ``gazebo`` and ``mujoco``
applications are declared by the engine plugins, so they are offered in a
workspace that imports one. The editor extension's **Open in** menu runs the
same command, and offers each engine for scenes in its own format only.

Each engine is handed a file that already is in its format. MuJoCo reads MJCF
and nothing else, and ``pc ide open`` converts no scene into it: MJCF is written
by the MuJoCo plugin's exporter, and a file handed to ``pc ide open`` has no
package around it to reach that plugin through. A Gazebo world, or anything else
that is not MJCF, is refused with the export that does work -- write the scene
out first, and open what was written:

.. code-block:: shell

  pc export -t sim-mujoco:mjcf workcell
  pc ide open --with mujoco workcell.xml

An ASSY scene is refused too, for a reason of its own: it is nothing but
references to the parts of a package, and a file opened on its own has no
package to resolve them against. See ``pc ide open`` in :doc:`cli`.

.. _sim-limitations:

===========
Limitations
===========

What a run does not model today, so that a claim is not written against it:

- **Mechanisms in MuJoCo only.** PartCAD decides what becomes a body (see
  :ref:`sim-bodies`), and the MuJoCo plugin writes it -- the bodies, the welds
  and the joints. The Gazebo plugin does not yet: in a Gazebo run every part
  with geometry is still a free body of its own, so an assembly's parts come
  apart under gravity, its joints are not written and a ``fixed: true`` element
  is held by nothing but the floor under it. Writing them there is the next step
  for its exporter; see the `design record`_.
- **No closed loops.** A link is placed once, against a link already placed,
  so a four-bar linkage cannot be stated (see :ref:`assy-joints`).
- **Joints are what their interfaces say, and no more.** A joint's damping,
  friction and spring are written; its ``maxEffort`` and ``maxVelocity`` are
  not, because nothing drives a joint yet. A ball joint's limits, and a
  ``mimic`` between joints of more than one freedom, are reported rather than
  written. A coupling -- a screw's thread, a ``mimic`` -- is held as MuJoCo holds
  every constraint: very nearly, and a little softly under load.
- **No inputs.** A run starts at rest, where the scene places everything, and
  nothing moves it but gravity, contact and the fluid: no initial velocity, no
  motor, no controller, no sensor.
- **Contact is against the part's own shape.** There is no separate, simpler
  collision shape. MuJoCo collides only convex shapes and takes the convex hull
  of anything else, so in MuJoCo a pocket, a slot or the gap between a gripper's
  fingers is filled in.
- **One friction coefficient per body**, the sliding one, combined with the
  other body's by the engine's own rule (see `Friction and contact`_).
- **No water surface.** A fluid fills the whole world: a body lighter than it
  rises for as long as the run lasts rather than coming to float at a
  waterline, and nothing is ever partly submerged.
- **Sealed cavities are flooded.** A body displaces its solid's volume, so a
  hollow part is buoyed as if it were open. Draw a float as the solid it
  displaces, and state its mass.
- **No added mass, lift or Magnus effect**, and drag is MuJoCo's simplest model
  of it.
- **No fluid in Gazebo** at all: a Gazebo run of a scene filled with water is a
  run in a vacuum, and its export says so.
- **No units inside values**: a gravity is ``[0, 0, -9.81]``, not
  ``"9.81 m/s^2"``.
