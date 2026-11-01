.. _simulate:

###########
Simulations
###########

A **simulation plugin** teaches PartCAD to run a physics simulator. It is the
third kind of implementation declared in the same form as
:doc:`an output type </plugins/output>` -- a ``path`` to a script, the sandbox
that script needs, and the parameters it is handed -- and it is what turns an
object's claim about its *behaviour* into something that can be checked.

A part says what it **is**. ``simulate:`` is where a part, an assembly or a
scene says what it is supposed to **do** once it is placed in a world and the
world is switched on -- or, more often, what it is supposed *not* to do: not
fall over, not slide off, not come apart. ``pc sim`` runs those, and ``pc test``
holds the object to them every time it runs, as its ``sim`` check.

**PartCAD ships no simulator.** It ships the concept -- this section, the
sandbox a plugin runs in, and the export a scene reaches the simulator through
-- and a package supplies the physics.

What a simulation plugin is for
===============================

- **Proving a behavioural requirement.** A ``simulate:`` entry that names a
  ``feature:`` of the object's ``requirements:`` becomes the evidence for that
  feature, which is otherwise a sentence no program can measure.
- **Catching what geometry cannot show.** A stack that stands, a gripper that
  holds, a robot that does not tip on a slope: nothing about the shapes says any
  of it.
- **Regression-testing motion.** The simulations run in ``pc test``, through the
  cache, so a change that makes a mechanism bind is a failed check rather than a
  discovery.
- **Wrapping one engine once.** A plugin brings the engine, the scene format it
  reads and the vocabulary it reports in, so every package using it writes the
  same kind of ``validation:``.

Using one
=========

Declare the simulation on the object, naming the plugin by full path:

.. code-block:: yaml

  parts:            # or assemblies:, or scenes:
    <name>:
      simulate:
        <simulation name>:
          desc: <(optional) what this simulation is about>
          scene: <(optional) the scene to place this object in, by full path>
          offset: <(optional) OCCT Location object: where in that scene it goes>
          simulation: <the simulation plugin, by full path; there is no default>
          validation: <(optional) a Python expression that is true when it went as it should>
          params: <(optional) parameter values handed to the plugin>

What each key means is in :ref:`sim-declaring`, the scene an object is placed in
and how to write one in :ref:`sim-scenes`, and what a ``validation:`` is
evaluated over in :ref:`sim-validation`.

Every run is also asked for a picture of the scene before and after, taken from
where the scene is rendered from: the ``viewport_origin`` and ``viewport_up`` of
its ``render: png:``, or of its package's when the scene states none; see
:doc:`/digital_thread/lifecycle/simulation`.

Then:

.. code-block:: shell

  pc sim :bracket                # every simulation the object declares
  pc sim -f holds-the-shelf :bracket   # one of them
  pc sim --json :bracket         # everything the simulator reported, not just the verdict
  pc test -f sim :bracket        # the same runs, as a check

Every run is also asked for a picture of the scene before and after, taken from
where the scene is rendered from: the ``viewport_origin`` and ``viewport_up`` of
its ``render: png:``, or of its package's when the scene states none.

Writing one
===========

A simulation plugin is the third kind of implementation a package can declare,
beside the export and render ones of :ref:`output-files`, and it is declared in
exactly the same form -- a ``path`` to a script, the sandbox that script needs,
and the parameters it is handed:

.. code-block:: yaml

  simulation:
    <name>:
      desc: <(optional) textual description>
      path: <the script that runs the simulation>
      package: <(optional) the package holding it, when it is not this one>
      format: <the file type the scene is exported to before the plugin starts>
      formatOptions: <(optional) export parameters for that conversion>
      pythonVersion: <(optional) the sandbox interpreter>
      pythonRequirements: <(optional) what that sandbox needs installed>
      <anything else>: <a parameter handed to the script>

The contract is narrow on purpose: **a scene with the subject in it goes in, as
a file in the format** ``format:`` **names, and JSON carrying** ``before`` **and**
``after`` **comes out.** The scene arrives as a file because a simulator reads
its own model format and PartCAD already knows how to write several -- which is
also what keeps a plugin free of any CAD dependency.

The exporter for ``format:`` is looked up in the plugin's own package as well as
in the scene's, beneath it, which is how a plugin implements the format it
reads: an engine's scene format belongs to that engine's plugin, so each plugin
declares the ``export:`` that writes it beside the ``simulation:`` that runs it,
and a package that re-tunes that export for its own scenes still wins.
``formatOptions:`` is how the plugin asks for the export -- a physics run wants
every body free to move, the opposite of what a scene means on its own.

The script runs in a PartCAD sandbox with two globals. ``request`` holds the
plugin's declared parameters, overridden by the ``params:`` of the declaration
being run, and then ``scene_file`` (the absolute path of the exported scene),
``scene_format``, ``scene_name``, ``subject`` (the full path of the object being
simulated), ``subject_kind`` and ``simulation`` (the declaration's name).
``path`` is a directory the run may write anything into -- a trajectory, a log
-- which is kept and cached with the result. The script sets ``output``, or
defines ``process(path, request)`` returning it:

.. code-block:: python

  output = {"success": True, "before": {...}, "after": {...}}
  output = {"success": False, "exception": "..."}

A success without ``before`` and ``after``, each an object, is refused. What is
inside them, and anything else beside them, is the plugin's own vocabulary:
PartCAD carries it to the ``validation:`` expression and reads none of it. The
two plugins PartCAD maintains share one vocabulary, described in
:ref:`sim-validation`, and a plugin that reports the same is one whose
validations read the same.

An example
==========

**PartCAD ships none of these.** A simulator is somebody's program with a
release cycle of its own, so PartCAD ships the concept -- this section, the
sandbox a plugin runs in, and the export a scene reaches it through -- and a
package supplies the physics. :ref:`sim-engines` lists the two there are.

Each of the two is one package carrying everything its format needs -- the
:doc:`importer </plugins/importers>` that reads it, the
:doc:`export type </plugins/output>` that writes it, the
:doc:`application entry </plugins/applications>` that opens it, and the
simulation plugin that runs it:

.. list-table::
   :header-rows: 1

   * - package
     - engine
     - the type to name
   * - `partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_
     - `MuJoCo <https://mujoco.org/>`_
     - ``sim-mujoco:mujoco``
   * - `partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_
     - `Gazebo <https://gazebosim.org/>`_
     - ``sim-gazebo:gazebo``

``examples/feature_simulate`` is the worked example. Its scenes are arrangements
of blocks that each declare a ``simulate:`` entry with a ``validation:`` over how
far anything moved: ``stable`` is supposed to stand, ``unstable``, ``slippery``
and ``tilted`` are supposed not to, and ``tank`` is filled with water so that
buoyancy and drag are exercised too.

.. code-block:: shell

  cd examples/feature_simulate
  pc sim :stable                 # the stack that stands
  pc sim --json :stable          # the body positions before and after
  pc test -f sim                 # all of them, as checks

:ref:`sim-engines` says what each engine models and what it does not, and
:ref:`sim-validation` the vocabulary the two PartCAD maintains report in -- a
plugin that reports the same is one whose validations read the same.

See :doc:`/digital_thread/lifecycle/simulation` for the whole chapter on
simulating, and :ref:`sim-declaring` for every key of the declaration.
