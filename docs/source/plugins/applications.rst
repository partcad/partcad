.. _open-section:

############
Applications
############

An **application plugin** teaches PartCAD which third-party program opens a
file, and how. ``pc ide open`` launches one on the object or file it is given,
and which applications it knows is an ``open:`` section -- one entry per
application, and **data all the way down**: where the application is on each
operating system, what to run it as, which container to fall back to when it is
not installed, and what it can read.

None of it is logic. Finding the binary, creating the container, forwarding the
X display and converting a file the application cannot read is the same for
every tool and happens once, in ``partcad_client.external``. That is why adding
an application is a few lines of YAML rather than a code change.

What an application entry is for
================================

- **Opening an object in the tool that suits it** -- a board in KiCad, a mesh in
  Blender, a solid in FreeCAD -- straight from the package, without exporting by
  hand first.
- **Teaching PartCAD an in-house or a vendor tool**, so everybody opens it the
  same way and nobody keeps a path to it in their head.
- **Giving a machine with nothing installed a way in.** An entry naming a
  ``container:`` runs the application in a container with the host's display
  forwarded into it.
- **Letting a simulator's plugin own its own viewer.** The package that reads a
  format declares the application entry for it too, so importing that package is
  all it takes.

Using one
=========

.. code-block:: shell

  pc ide open :bracket                   # whatever suits it
  pc ide open --with freecad :bracket     # a particular application
  pc ide open --with democad ./cell.demo  # a file, in a workspace that imports the plugin

``pc ide open`` **blocks until the application closes**, and an edit to a
converted copy is converted back over the object's source when that source is a
file. The VS Code extension's per-part "Open in..." menu runs the same command.

Writing one
===========

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
MuJoCo reads MJCF, kept in ``.xml``. A scene in that language -- by its declared
type, or else by one of those extensions, since the file itself is not read --
is handed over as it is, and one in any other is refused rather than converted,
with the export that writes it -- the language is the engine plugin's, and a
file handed to ``pc ide open`` has no package around it to reach that plugin
through.

``container:`` has the shape a plugin's implementation gives it -- ``image``, and
``python`` for an image whose ``python3`` is not on ``PATH`` -- and the container
is started the way every other PartCAD container is (see
:ref:`useDockerRemote <use-docker-remote>`), with the file mounted or, under ``useDockerRemote``,
uploaded. ``image:``, ``ownFormats:``, ``meshVia:`` and ``imports:`` are what an
entry said before ``container:`` and ``formats:``; they are still read, into
those, and ``pc ide open`` says once that they are deprecated.

A package's entry **replaces a built-in of the same name**, which is how the
plugin for a simulation engine comes to own the application for it.

What it is, and is not
======================

``pc ide open`` is otherwise a **client-side** command and stays one: it is handed a
path, the file is already on disk, and the window belongs to whoever ran the
command -- a daemon can be remote. So the built-in entries are read straight out
of the wheel the client is running from, with no context and no daemon, and only
the applications a *package* declares are asked of the daemon (``open.tools``).
It answers which applications exist; it never opens one, and there is no method
for opening a file.

An example
==========

PartCAD ships three entries in ``//builtin/open`` -- FreeCAD, KiCad and Blender
-- and they are the three to read before writing one, because between them they
cover every interesting case:

``freecad``
  The plain case. ``formats: [fcstd, step, brep, iges, stl, obj]`` -- its own
  project file first, then what a part already is when PartCAD reads it from a
  file, with **STEP leading the conversions** so that a script converted for
  FreeCAD arrives as the solid it is rather than as triangles. Its
  ``container:`` image is ``:latest`` rather than pinned, because somebody
  asking for a container wants the current FreeCAD.

``kicad``
  The ``companions:`` case, and the one worth understanding before writing an
  entry. ``formats: [kicad_pro, kicad_pcb, kicad_sch]`` -- the project and the
  two files it is made of -- and ``companions: [.kicad_pro, .kicad_pcb,
  .kicad_sch]``. A ``kicad`` part *is* the STEP file KiCad's CLI writes out of
  the board; the board is the project beside it, and that is what opening KiCad
  means. **Nothing PartCAD can write is a board**, so a file with no project
  beside it is refused rather than converted. Its image is the one PartCAD
  already builds for ``kicad`` parts, pinned to the running release, so there is
  one KiCad container in the product rather than two.

``blender``
  The mesh case. ``formats: [blend, stl, obj, ply, glb, fbx, x3d]`` -- its own
  ``.blend`` first, then the meshes it imports, with STL first among those
  because it is the first one PartCAD writes and **every part type converts to
  it**, which makes this one rule rather than a table of exceptions.

Both of the simulator packages declare an entry of their own:

.. list-table::
   :header-rows: 1

   * - package
     - application
     - what it opens
   * - `partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_
     - Gazebo
     - a scene already in SDFormat (``sceneType:``)
   * - `partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_
     - MuJoCo
     - a scene already in MJCF, kept in ``.xml``

.. code-block:: shell

  pc ide open --with freecad :bracket     # converted to STEP first, if it is a script
  pc ide open --with blender :bracket     # meshed to STL on the way in
  pc ide open --with mujoco ./cell.xml    # handed over as it is
  pc system status                        # among other things, which applications were found

A scene in a language the application does not read is **refused rather than
converted**, naming the export that would write it: the language belongs to the
engine's plugin, and a file handed to ``pc ide open`` has no package around it to
reach that plugin through.
