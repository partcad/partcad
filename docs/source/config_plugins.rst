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

Two more are about what an application is really handed. ``companions:`` names
the extensions the application really opens, for a file that sits beside the one
PartCAD was pointed at -- a ``kicad`` part *is* the STEP file KiCad's CLI writes,
and the board is the project next to it. ``sceneType:`` says which description
language an application reads, for one that reads an arrangement rather than
geometry, and ``sceneExtensions:`` the extensions a file in it is stored in:
MuJoCo reads MJCF, kept in ``.xml``. A scene in that language is handed over as
it is, and one in any other is refused rather than converted, with the export
that writes it -- the language is the engine plugin's, and a file handed to
``pc ide open`` has no package around it to reach that plugin through.

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
          simulation: <the simulation plugin, by full path; there is no default>
          validation: <(optional) a Python expression that is true when it went as it should>
          params: <(optional) parameter values handed to the plugin>

What each key means is in :ref:`sim-declaring`, the scene an object is placed in
and how to write one in :ref:`sim-scenes`, and what a ``validation:`` is
evaluated over in :ref:`sim-validation`.

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

**PartCAD ships none of these.** A simulator is somebody's program with a
release cycle of its own, so PartCAD ships the concept -- this section, the
sandbox a plugin runs in, and the export a scene reaches it through -- and a
package supplies the physics. :ref:`sim-engines` lists the two there are.

See :doc:`simulation` and ``examples/feature_simulate``.
