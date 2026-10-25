.. _open-section:

############
Applications
############


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

``pc ide open`` is otherwise a **client-side** command and stays one: it is handed a
path, the file is already on disk, and the window belongs to whoever ran the
command -- a daemon can be remote. So the built-in entries are read straight out
of the wheel the client is running from, with no context and no daemon, and only
the applications a *package* declares are asked of the daemon (``open.tools``).
It answers which applications exist; it never opens one, and there is no method
for opening a file.
