#######################################
Importers, applications and simulations
#######################################

.. _import-section:

=========
Importers
=========

``urdf``, ``sim-mujoco:mjcf`` and ``sim-gazebo:world`` are not object types
PartCAD hard-codes. Each is one entry of an ``import:`` section -- a declaration
saying which script reads that format, what its sandbox needs, and which object
kinds it may produce -- and a package writes one to teach PartCAD a format of its
own. That is not a hypothetical: ``urdf`` is the only one of the three PartCAD
ships, and the other two are entries of exactly this kind in the plugin package
for their engine.

.. code-block:: yaml

  import:
    demo:
      desc: The DemoCAD scene format
      path: read_demo.py           # the reader, in this package
      extension: demo              # the source file's extension
      kinds: [assembly, scene]     # what it may be declared as
      noun: model                  # what one is called in a log line
      pythonRequirements:
        - cadquery-ocp==7.9.3.1.1
      precision: 6                 # anything else is the reader's parameter
      dropped:
        joint: "joints (the object shows the bodies at their initial pose)"

An object then names it the way it names any object type. A reader in the same
package is named directly; one in another package is named by full path, exactly
as a :ref:`partType <part-types>` or a ``simulation:`` plugin is:

.. code-block:: yaml

  scenes:
    cell:
      type: sim-gazebo:world       # the reader in the imported package
      path: cell.world

The reader itself is handed the file and its parameters, and returns a tree of
placed shapes as plain data -- each node naming the *file* its geometry is read
from rather than carrying geometry. The part factory for that file's own format
reads it afterwards, so a mesh a scene references is never copied or rewritten.
Only the primitives a format defines (a box, a cylinder, a sphere) have no file
to name, and the reader writes those out itself. See
``wrappers/wrapper_import.py`` for the contract in full.

Two fields are worth dwelling on. ``kinds:`` is a claim the core holds the
declaration to: a format that describes one robot is an assembly and declaring
it under ``scenes:`` is an error, while a format used for both -- MJCF is the
one that routinely is -- says both and lets the section decide. ``dropped:``
words what the reader counted: every one of these formats describes something a
static tree cannot hold, and the division of labour is that the *reader* counts
what it had to drop and the *declaration* says what to call it.

The section shares its name with what ``dependencies:`` used to be called, and
that spelling is reported rather than silently migrated now: a package whose
``import:`` entries carry a ``type:`` of ``git``/``tar``/``local``/``external``,
or any of the transport-only keys (``url``, ``relPath``, ``revision``, ...), is
told to rename the section, and those entries are dropped instead of being
fetched as packages. Nothing is migrated for it.

How loudly depends on whose package it is. In the package you are standing in it
is an error and the package is broken -- the command exits non-zero and nothing
loads out of it, because that is the file you can fix. In an imported package it
is a warning naming the package, the entry and the fix: such a package is very
often somebody else's, several levels below anything you wrote, and one of them
anywhere in an index must not fail every command that merely walks past it. That
package goes on providing everything else it declares; what is lost is exactly
what the section named.

PartCAD ships **one** of these, in ``//builtin/import``: ``urdf``, which stays
there because a URDF describes a robot rather than any one engine's world, and
ROS, MuJoCo, PyBullet and Isaac all read it. ``mjcf`` and ``world`` belong to
`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ and
`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_
respectively, beside the exporter and the simulator that share their knowledge
of the format: reading a format and writing it are one piece of knowledge, and
this is what lets the pair travel together and be versioned together.

Each of those packages declares the reader, the writer, the simulator and the
``open:`` entry for its format, and the wheel carries none of them. So
``type: sim-gazebo:world`` and ``type: sim-mujoco:mjcf`` are the spellings that
resolve, in a package that imports the plugin; a bare ``type: world`` resolves to
nothing and says which package to name.

.. _open-section:

============
Applications
============

``pc ide open`` launches a third-party application on the file it is given. Which
applications it knows is an ``open:`` section -- one entry per application, and
data all the way down: where the application is on each operating system, what
to run it as, which container to fall back to when it is not installed, and what
it can read. None of it is logic. Finding the binary, creating the container,
forwarding the X display and converting a file the application cannot read is
the same for every tool and happens once, in ``partcad_client.external``.

.. code-block:: yaml

  open:
    democad:
      displayName: DemoCAD
      formats: [demo, step, stl]         # what it opens, best first
      container:                         # when it is not installed here
        image: example/democad:latest
      binaries: [democad, democad-bin]   # on PATH and in the container
      macosApps: [DemoCAD.app]
      windowsGlobs: ["DemoCAD*/bin/democad.exe"]
      flatpakId: org.example.DemoCAD

``pc ide open --with democad ./cell.demo`` then works, in a workspace whose packages
import that one. PartCAD ships three of these in ``//builtin/open`` -- FreeCAD,
KiCad and Blender. A package's entry replaces a built-in of the same name, which
is how the plugin for a simulation engine comes to own the application for it: both
`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_ and
`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ declare
theirs, so a workspace that imports either already gets the entry from there.

``formats:`` is the one that decides most: what the application opens, **best
first** -- its own formats (``fcstd``, ``blend``, ``kicad_pcb``) and PartCAD's
part types (``step``, ``stl``). An object in one of them is handed over as it is.
Any other is converted to the first one on the list that PartCAD can write, and
``pc ide open`` then waits for the application to close: when the converted copy was
changed, it is converted back into the object's own format and written over its
source, where that source is a file (a STEP, an STL...) rather than a script.

Two more are how an application that cannot read what it was handed still gets
to open something. ``companions:`` names the extensions the application really
opens, for a file that sits beside the one PartCAD was pointed at -- a ``kicad``
part *is* the STEP file KiCad's CLI writes, and the board is the project next to
it. ``sceneType:`` says which description language an application reads, for
one that reads an arrangement rather than geometry: MuJoCo reads MJCF, so a
Gazebo world it is pointed at is written out as MJCF first.

``container:`` has the shape a plugin's implementation gives it -- ``image``, and
``python`` for an image whose ``python3`` is not on ``PATH`` -- and the container
is started the way every other PartCAD container is (see
:ref:`useDockerRemote <use-docker-remote>`), with the file mounted or, under ``useDockerRemote``,
uploaded. ``image:``, ``ownFormats:``, ``meshVia:`` and ``imports:`` are what an
entry said before ``container:`` and ``formats:``; they are still read, into
those, and ``pc ide open`` says once that they are deprecated.

``pc ide open`` is otherwise a **client-side** command and stays one: it is handed a
path, the file is already on disk, and the window belongs to whoever ran the
command -- a daemon can be remote. So the built-in entries are read straight out
of the wheel the client is running from, with no context and no daemon, and only
the applications a *package* declares are asked of the daemon (``open.tools``).
It answers which applications exist; it never opens one, and there is no method
for opening a file.

.. _simulate:

===========
Simulations
===========

A part says what it *is*. ``simulate:`` is an optional section of a part or an
assembly where it says what it is supposed to **do** once it is placed in a
world and the world is switched on -- or, more often, what it is supposed not to
do: not fall over, not slide off, not come apart. ``pc sim`` runs them, and
``pc test`` holds the object to them every time it runs, as its ``sim`` check
(see "Running a simulation" in :doc:`simulation`).

.. code-block:: yaml

  parts:            # or assemblies:
    <name>:
      simulate:
        <simulation name>:
          desc: <(optional) what this simulation is about>
          scene: <(optional) the scene to place this object in, by full path>
          offset: <(optional) OCCT Location object: where in that scene it goes>
          simulation: <(optional) the simulation plugin, by full path>
          validation: <(optional) a Python expression that is true when it went as it should>
          params: <(optional) parameter values handed to the plugin>

The object's own full path is assigned to the scene's ``subject`` parameter --
unconditionally, and whatever else the entry says. That is what lets one scene
serve every object that names it, and nothing special is declared for it: a
simulation scene is an ordinary scene with an ordinary parameter, and the
Jinja2 template its file is read as (see :doc:`assy`) is what places the subject.

``scene:`` does not have to be given: the default is ``//builtin/scene:subject``,
an empty world holding the subject and nothing else, which is what "does this
stand up on its own" means. ``simulation:`` does have to be given -- PartCAD
implements no simulator, so a package imports one and says which:

.. code-block:: yaml

  dependencies:
    sim-mujoco:
      type: git
      url: https://github.com/partcad/partcad-sim-mujoco.git

  assemblies:
    stack:
      type: assy
      simulate:
        stands:
          simulation: sim-mujoco:mujoco
          # The blocks are drawn about their own centres, so lift the stack to
          # stand its bottom face on the floor of the scene.
          offset: [[0, 0, 10], [0, 0, 1], 0]
          validation: |
            max(
                abs(after["bodies"][name]["pos"][2] - before["bodies"][name]["pos"][2])
                for name in before["bodies"]
            ) < 2.0

``offset:`` is stated here rather than in the scene because it is a fact about
*this* object -- where its origin sits relative to the floor it is meant to
stand on -- and the scene is shared.

``validation:`` is a Python expression evaluated over ``before`` and ``after``,
the two objects the plugin produced, and ``result``, the whole of what it
returned. It is the only thing PartCAD reads out of a result: what is *inside*
those objects is the plugin's vocabulary, and the expression is written by
whoever knows both the object and the plugin. An entry that states none runs and
reports, and passes nothing; ``pc test`` counts it as passing once it has run,
since running is the whole of what it asked.

Simulation plugins
------------------

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

**PartCAD ships none of these.** A simulator is somebody's program with a
release cycle of its own, so PartCAD ships the concept -- this section, the
sandbox a plugin runs in, and the export a scene reaches it through -- and a
package supplies the physics.
`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ is the
MuJoCo one: it is handed the scene as MJCF, steps it under gravity for
``duration`` seconds of simulated time, and reports each body's position (in
millimetres) and orientation before and after. Running it needs no MuJoCo on the
machine, since the plugin runs in a PartCAD sandbox that installs one.

Friction is a material property
-------------------------------

Whether a stack of blocks stands up is not a property of its geometry. Two 20 mm
blocks squarely stacked stay put when they are aluminium (``mu: 1.05`` -- dry
aluminium galls) and the top one slides off when they are PTFE (``mu: 0.04``),
and nothing about the arrangement changes in between.

So it is stated where it belongs, on the :ref:`material <materials>`, and a part
that names one gets it. A part names one the way it always has -- with the
``material`` parameter, on a part type that accepts one (see :ref:`parameters`) --
and the factory records the answer as the shape's ``material`` property, which
is what reads it from there on:

.. code-block:: yaml

  parts:
    block:
      type: cadquery
      path: block.py
      parameters:
        material:
          type: string
          default: ":aluminium"

``mu`` then becomes the shape's ``friction`` property unless the shape states a
``friction`` of its own, and every format writes it in its own spelling --
SDFormat's ``<friction><ode><mu>``, URDF's ``<gazebo><mu1>``, MJCF's first
``friction`` component. A part that says nothing gets whatever the simulator
defaults to, which is a number nobody chose.

Note which section that is. ``parameters:`` is what is *asked of* the type that
produces the shape and is where a package writes what it wants; ``properties:``
is what the shape *turned out to be*, and is filled in by whatever built it -- a
URDF reader naming a link's material, a STEP reader finding one in the file, or
the part factory recording what its type was asked for. A package does not write
``properties:`` by hand.

See :doc:`simulation` and ``examples/feature_simulate``.
