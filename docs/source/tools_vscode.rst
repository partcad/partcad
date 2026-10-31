#############
VS Code / IDE
#############

The PartCAD extension is the primary graphical interface to PartCAD. It adds a PartCAD workbench with an
Explorer view for browsing packages, an Inspector for viewing objects and editing their parameters, and the
**Digital Thread** panel over whichever object is selected.

One extension, three editors: Visual Studio Code, :doc:`VSCodium </tools_vscodium>`, and the
:ref:`PartCAD IDE <partcad-ide>`, which is a VSCodium build that ships it. This chapter is about all three --
what differs between them is only how the extension gets there, which is the next section.

It carries no PartCAD of its own. Like the :ref:`Desktop Application <partcad-ide>` and the
:ref:`CAD add-ons <cad-addons>`, it is a client of the ``partcad-json-rpc`` service, so it sees the same
packages and the same cache as ``pc`` does on the same machine -- and anything it can do, :doc:`/cli` can do
too.

==========
Installing
==========

.. code-block:: shell

  code --install-extension PartCAD.partcad-official

Or search for **PartCAD** in the Extensions view, or use the
`marketplace page <https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad-official>`_. If you
already have ``pc``, ``pc ide install`` does it for you -- and works the same for
:doc:`VSCodium </tools_vscodium>` and for the Desktop Application.

Every `release <https://github.com/partcad/partcad/releases>`_ also carries the packaged extension as
``partcad-<version>.vsix``, to pin a version or to install where the marketplace is not reachable:
``code --install-extension partcad-<version>.vsix``.

Make sure Python is configured and a `conda <https://docs.conda.io/>`_ environment is set up in the editor
before using PartCAD, or install the :ref:`Desktop Application <partcad-ide>`, which brings its own.

.. note::

  The extension used to be published as ``OpenVMP.partcad``. That entry is now a shim that depends on
  ``PartCAD.partcad-official``, so an existing installation updates into the new one by itself and there is
  nothing to do by hand.

===============
What it does
===============


The PartCAD extension for Visual Studio Code is the primary graphical interface to PartCAD. It adds a PartCAD
workbench with an Explorer view for browsing packages and an Inspector view for viewing objects and editing
their parameters. Install it from the
`VS Code marketplace <https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad-official>`_. See
the :doc:`tutorial </tutorial>` for a step-by-step walkthrough.

Opening a package runs the code its parts are written in, so in a folder Visual Studio Code has not been told
to trust (Restricted Mode) the extension starts nothing: it asks for trust, the Explorer says why it is empty,
and every PartCAD command offers **Manage Workspace Trust** instead of running. PartCAD starts as soon as the
folder is trusted, without reopening the window. The :ref:`PartCAD IDE <partcad-ide>` does not ask -- it
exists to run PartCAD, and trusts every folder.

The extension exposes the following actions from the Explorer view and the command palette:

Packages
========

- **Initialize new package** — Create a ``partcad.yaml`` package in the current workspace (a custom-path
  variant is also available).
- **Open package** — Open an existing package.
- **Reload the package** and **Restart PartCAD** — Refresh the view or restart the PartCAD backend after a
  change.
- **Update PartCAD** — Update the PartCAD installation used by the extension.
- **Show Terminal** — Open the ``PartCAD`` terminal again after it was closed (see :ref:`partcad-terminal`).

Objects
=======

- **Add** a part, assembly, scene, sketch, or interface.
- **Import** a part, assembly, scene, or sketch from an existing file.
- **Display** (inspect) a part, assembly, scene, sketch, or interface in the ``Digital Thread``; parts can
  also be opened for display and editing together, or their source edited directly.
- **Test** a part, assembly, or scene.
- **Open in >** — Open the object's own source file in the application that made it: **FreeCAD** or
  **Blender** for a part or an assembly, **KiCad** for a part of type ``kicad``, and **Gazebo** or
  **MuJoCo** for a scene held in that engine's own format (``sim-gazebo:world``, ``sim-mujoco:mjcf``) when
  the workspace imports the package that declares the engine. This runs
  on your machine rather than on the daemon: the extension runs ``pc ide open`` (see :doc:`/cli`), which starts an
  application installed here, or runs one in a container when there is none and ``partcad.open.useDocker``
  is on, which it is by default. An object in a format the application does not open is converted on the
  way -- a script to STEP for FreeCAD, a solid to STL for Blender. The editor then waits, behind a banner
  saying so and with every PartCAD command paused, until the application is closed; what was saved in it is
  brought back into the object's own file, converted back when it had been converted.

The Explorer also lists the ``software`` a package ships. Selecting one shows its path and its ``fileHash``
in the Inspector and leaves the ``Digital Thread`` as it is: software is a file, not geometry, so there is
nothing to render.

Digital Thread
==============

Displaying an object opens the ``Digital Thread``, which is a strip of tabs over that one object rather than
a bare canvas: groups of tabs, each with tabs of its own -- **Design**, **Analysis**, **Manufacturing** and
**Validation**, followed by **Operations**, which has nothing in it yet and is always disabled. Design
is always the first (see :doc:`/digital_thread/introduction` for what each group is for):

- **Design** — the object itself, three ways, in tabs of its own:

  - **3D** — the shape, tessellated by PartCAD and drawn here, to turn and zoom. Always present.
  - **2D** — the object rendered to a picture, as ``pc render`` renders it: PNG, JPEG or SVG,
    chosen from a list. For a part, an assembly, a scene or a sketch.
  - **Draft** — a dimensioned technical drawing of a part or an assembly, made by a drawing package the way
    ``pc render -e`` uses one. **Drawn by** names it: ``//pub/feature/render/draftwright`` unless you choose or
    type another, and the formats are whatever it declares (PDF, SVG and DXF). The first drawing takes a few
    minutes while PartCAD installs draftwright.

  2D and Draft each have a **Save…** button that saves the file on screen wherever you choose. A picture is
  shown on the tab, and can be zoomed with the mouse wheel, dragged, and put back with a double-click; a PDF or
  a DXF cannot be shown there, and is saved and opened in another program instead.
- **Analysis** — what engineering analysis says about the object:

  - **FEA**, **Dynamic FEA**, **Heat Transfer** and **CFD** — for a part that declares scenarios of that
    analysis: the scenarios, and for the one selected what :ref:`pc cae <cae>` produced and what it found.
- **Manufacturing** — what making it takes:

  - **Build vs Buy** — for a part or an assembly: every part, piece of stock and sub-assembly it is made of,
    with a picture, a count, its size, weight and material, and a switch saying whether it is built or bought.
    A line that can be only one of the two has its switch fixed, and one that can be neither is marked
    **Incomplete**. The choices are kept on your machine, and ``pc instructions`` reads them too.
  - **Build** — for whatever is built: the order to make it in, with the instructions for the selected step.
  - **Buy** — for whatever is bought: what it can be bought from, and a quote per supplier.
  - **Bill of Materials** — for a part or an assembly: what has to be procured to have it, as ``pc bom``
    lists it. A made part is the stock it is made from, and a sub-assembly that declares a vendor and an SKU
    is one item ordered whole.
  - **Assembly** — for an assembly: the assembly instructions, as PDF or HTML, to read and save
    (``pc instructions``).

  Manufacturing is for a part or an assembly; for a scene, a sketch or an interface it is disabled.
- **Validation** — whether the object is what it claims to be, and does what it is supposed to:

  - **Test** — every check ``pc test`` runs, with how each came out on this object: passed, failed, warned,
    skipped, or not applicable and why. The check selected shows what it found and what it is, when it applies
    and what to do when it fails (:doc:`/digital_thread/lifecycle/testing`). An interference leaves an assembly of the two
    parts and what they share, to open in 3D. Always the first tab, and always enabled; an object that belongs
    to no package has nothing to ask PartCAD about, and the tab says so.
  - **Simulation** — for a part, an assembly or a scene that declares a ``simulate:`` section (see :doc:`/digital_thread/lifecycle/simulation`):
    the simulations it declares, listed on the left with the first one selected. Selecting one runs it, as
    ``pc sim -f <name>`` does, and shows whether its ``validation:`` held, and plays the video of the run the
    simulation plugin recorded (see :ref:`sim-video`), in a player with the usual controls -- play and pause,
    replay, a step back and forward, a position to drag, the speed, and full screen. Until it is played, the
    player shows two pictures of the scene the plugin took -- before anything moved on the left, and when the
    run was over on the right, an arrow between them -- and a run with no video shows those two side by side.
    All of it is from where the scene is looked at when it is rendered. A plugin that takes no pictures has
    not failed: a line says so where they would be.

    Whether each run held is a green or red mark before its name in the list. Above the pictures, as on the
    Draft tab, **Simulated by** names the plugin that runs it -- filled in with the one it names, offering the
    ones PartCAD knows of, and taking any other name typed into it; another runs it with that one, like
    ``pc sim --plugin`` -- and **Simulate** runs it afresh. Under the
    pictures, **Criteria**, **Before** and **After** open on a click: the ``validation:`` expression, and the
    ``before`` and ``after`` the plugin reported, which are what that expression is evaluated over.
  - **Process Emulation** — nothing yet; always disabled.

  Validation is always enabled, for its Test tab; Simulation is disabled for anything that declares no
  simulation.

Every group always shows all of its tabs and disables the ones that do not apply, and a group none of whose
tabs apply is disabled itself, and says why when the mouse is over it. Design and its 3D tab are always enabled,
and are what the Digital Thread shows before anything has been selected. A group opens on the tab you last had open in
it, if that one applies to the object, and on the first one that does otherwise.

The 3D view arrives over the viewer protocol from whichever ``partcad`` asked for the shape to be shown; the
other tabs are questions put to the PartCAD daemon, fetched the first time the tab is looked at and cached
until the next object is shown. An object that belongs to no package gets the 3D view alone.

The 3D view and the analysis models use the graphics card where the window can (WebGL, else WebGPU). In a
window that cannot -- a virtual machine, a remote desktop, a graphics driver the editor could not use -- they draw
the model without it instead: flat-shaded and slower, and a big model is drawn as boxes while it is being turned. A
note in the corner of the view says so, and hovering over it says how to have the graphics card back.

Down the left of the 3D view is a list of **what is on screen**, with a checkbox on every line: unticking one
hides that line and everything under it, and ticking it again brings back exactly what was showing before.

.. _vscode-view-panel:

Down the right of every tab that shows the object -- 3D, 2D and Draft, each analysis, and Simulation -- is the
**view panel**, folded away until the button at the top of that edge (the editor's own "side bar" icon) brings it
out; it stays out, or folded, on every tab at once. From the top:

- an **orientation gizmo**, the object's X, Y and Z as they lie from where it is looked at. Drag it to turn the
  view, or click an axis to look along it; with the gizmo focused, the arrow keys turn the view a step at a time;
- a button per axis, **X**, **-X**, **Y**, **-Y**, **Z** and **-Z**, each looking along that axis from that end.
  They are the views ``pc render --view`` names -- X is ``right``, -Y is ``front``, Z is ``top`` with +Y up -- so
  the 2D tab's picture after one of them is the picture that command draws;
- a **section** slider per axis, each with two ends, which start at the two faces of the object's bounding box:
  moving an end inwards cuts that much off from that side, and the three together keep a box. The cut is made by
  PartCAD, on the exact geometry, before it is drawn -- the 3D view is shown again cut, and the 2D and Draft tabs
  draw the cut object -- so it is a section of the solid and not a clipping of the picture. It is one section for
  the 3D, 2D and Draft tabs, kept for as long as the object is on screen;
- the **viewpoint**: where the view is looked at from (**Origin**), which way is up (**Up**) and, in a 3D view,
  the point it looks at (**Target**), in millimetres in the object's frame. They are the ``viewport_origin`` and
  ``viewport_up`` a ``render:`` section takes, so they can be copied out into one, or onto
  ``pc render --viewport-origin``, and typed or pasted in -- ``1, 2, 3``, ``[1, 2, 3]`` and ``1 2 3`` all read.
  **Reset** goes back to the view the tab starts out with;
- **Animate** and **Opacity**, which turn the 3D view's model on its own and make it see-through. Animate is on
  from the start wherever the view has a graphics card to draw with, and while it is on a different object shown
  in the view starts at the angle the last one had turned to, so the model goes on turning as it is replaced.

What does not apply on a tab is disabled, and says why: a drawing package lays its views out itself, an
analysis's result is the solver's mesh rather than geometry PartCAD cuts, and a picture does not animate. On the
Simulation tab the viewpoint is where the plugin takes its pictures from, so choosing one runs the simulation
again with its pictures taken from there.

The list is the object itself. Every object PartCAD can show is a tree, and the pane is that tree:

- a **part** or a **sketch** is one line — itself;
- an **assembly** or a **scene** is a line per thing it holds, named as the ``.assy`` file names it, as deeply
  as the file nests them;
- an **interface** is a line per port it is drawn with, with a line per interface it inherits holding the whole
  of that one (see :doc:`/assy`).

Under each of those lines is what that object says about connections: a line per **interface** instance with the
ports it is made of underneath it, and a ``ports`` line for the ports that belong to no interface. Every port is
listed once and drawn as a coordinate frame — the same frames ``pc render --with-ports`` draws on a projection
(see :doc:`/cli`). An assembly's own ports are the ones it declares and the ones its ``map:`` externalizes, so
they are listed on the assembly's own line rather than on the things inside it.

A port that is drawn with a sketch — the circle of a hole, the profile of a rail — shows that too, in the blue of
the ``+Z`` line of its own frame: the shape the connection happens across, which is what makes an opening
readable as one. It is half see-through, so the opening it covers still reads as one, and the **Opacity** slider
leaves it alone — that slider is about the shape rather than about what is drawn on top of it. It is part of the
port, so the port's checkbox draws or hides both.

The ``<ports>`` and ``<interfaces>`` lines start folded up — for an assembly they run to hundreds of rows, and
unfolded they bury the hierarchy they hang off — and so does every part, since those two lines are all a part
has under it. They are written in italics, so that where they sit beside the parts of an assembly they do not
read as two more of them. Pointing at a part or a sub-assembly makes it **flicker** in the 3D view, which is how
to tell which of the shapes on screen a line is without moving the camera.

The 3D view, and the model of an FEA or CFD result, can also be navigated with a
`3Dconnexion <https://3dconnexion.com/>`_ **SpaceMouse**: the cap moves the model the way it is pushed and
twisted, and the device's **Fit** button (the right-hand one on a two-button model) frames the object again. On
Windows and macOS the viewer reads the device itself -- move the cap once with the viewer open for the editor to
notice it. On Linux it reads it through `spacenavd <https://spacenav.sourceforge.net/>`_, which has to be
installed and running (``sudo apt install spacenavd``, for instance); in a remote window -- a container, an SSH
host -- its socket has to be forwarded to where the workspace is, as the extension's README describes. Only the
viewer in the focused window moves, and only the tab on screen, so a SpaceMouse and two open windows do not
fight. ``partcad.spaceMouse.sensitivity`` sets the speed, ``partcad.spaceMouse.invert`` reverses individual axes,
and ``partcad.spaceMouse.enabled`` turns it off.

What the Digital Thread is showing can be asked of it from outside: ``pc ide state`` (see :doc:`/cli`) reports the tab
and sub-tab on screen, the filter and the selections of each sub-tab, and a screenshot of the one on screen -- together
with the Explorer's selection and the Inspector's parameters. It is what an AI agent working beside you reads to
see what you are looking at.

An object's own ports start out drawn. The ports of everything inside it do not: an assembly of forty parts has
a frame at every hole of every one of them, and all of it at once shows nothing. A line whose tick is grey
rather than solid is one that is showing while something under it is hidden — which is how a folded-up line says
so.

The analysis tabs are the exception to "questions": looking at one *runs* the analysis. Each is enabled for a
part that declares scenarios of that analysis, and lists them on the left the way the Simulation tab lists
simulations, in the order they are declared and with a mark for how each one's run went; the first is selected
when the tab opens, and selecting one runs it -- ``pc cae fea -f <scenario>`` -- the first time it is looked at,
and shows its answer from then on. Over the model is the Simulation tab's toolbar: **Analysed by** is filled in
with the solver the scenario names -- or the configured default -- offers the others ``//pub/feature/cae``
registers for the analysis, and takes any other name typed into it; another runs the scenario with it, so a
machine whose solver is elsewhere is one choice away from an answer rather than stuck on an error; **Analyse**
runs it afresh. The model is drawn
according to the format the implementation chose: a 3D result is turned and zoomed, a 2D one is panned and
zoomed as a picture. Any findings are listed under it; a scenario with nothing to report gets the whole pane.

.. _partcad-terminal:

Terminal
========

What PartCAD is busy with -- its log and the progress of a long operation -- appears in the ``PartCAD``
terminal. It opens the first time there is something to show, to the right of a shell named ``Shell``: a
terminal running your default shell, with the PartCAD command line tools on its ``PATH``, for starting a coding
agent side by side with what PartCAD is doing.

Close it whenever you like. It stays closed until you run **PartCAD: Show Terminal** or pick **PartCAD** from the
terminal panel's **+** menu, and then it opens with everything it missed. Set ``partcad.reopenTerminal`` to
``true`` to have new output reopen it instead, and ``partcad.popupTerminal`` to bring it to the front on every
new line. If PartCAD stops working in the window -- no PartCAD service, or one that will not start or keeps
stopping -- it opens on its own and says why, with a popup as well if it was closed.

.. _vscode-edit:

Edit
====

PartCAD is Code-CAD: every object is a file, and the file is the thing to
change. So the Explorer does more than list objects -- it puts you in the right
file, and the modelling loop runs between an editor on the left and the
``Digital Thread`` on the right.

**Edit**, on an object in the Explorer, opens the file that object *is*:

- a **part** written as a script -- CadQuery, build123d, chili3d or OpenSCAD --
  opens that script;
- an **assembly** of type ``assy`` or ``urdf`` opens that file;
- a **scene** of type ``assy``, or one that is an engine's own world or model
  (``sim-gazebo:world``, ``sim-mujoco:mjcf``), opens that file;
- a **package** in the tree opens its ``partcad.yaml``, and the button at the
  top of the Explorer, **Top level config**, opens the workspace's own.

An object with no source of its own -- an ``alias``, an ``enrich``, a part read
from a STEP or an STL file -- does not get the entry. What *declares* it is its
package's ``partcad.yaml``, which is one click further up the tree. A sketch
read from a DXF or an SVG has a file of its own and is not offered the entry
either, today; open it from the editor's own Explorer, or hand it to a drafting
application with **Open in > CADCraft** below.

``partcad.yaml`` and ``.assy`` are languages of their own here, with their own
syntax highlighting and their own icon, which is why an ASSY file does not read
as plain YAML.

**What a save costs is only what changed.** The PartCAD daemon keeps a warm
context between commands, and at every request it stats the ``partcad.yaml`` of
the packages that request is about: one whose configuration has changed is
dropped and read again from disk, together with the packages under it, while
everything beside it -- the other packages, the sandboxes, whatever they have
already built -- stays as it is. So a declaration edited here is the declaration
the next thing you do sees, with nothing to reload by hand and nothing to
restart. A *script* needs not even that: a built object is cached under a digest
of the files it was built from, so an edited script is a different question with
a different answer, and everything built out of that part -- every assembly that
places it, its bill of materials, its checks -- is asked again while the rest of
the package is read back from the cache (see :ref:`caching`).

What a save does **not** do is redraw the panel on its own. Showing the object
again is the other half of the loop: **Display** in the Explorer, or
``pc ide view`` typed in the ``PartCAD`` terminal beside it. **Reload the
package** and **Restart PartCAD** are there for what a stat cannot see -- a
dependency fetched by hand, a file outside the packages a request names --
rather than for ordinary editing.

Two things help while you type, and neither waits for a build:

- **Linting.** A ``partcad.yaml`` or an ASSY file is checked *as it renders* --
  the templates expanded, the schema applied, the names resolved -- on every
  keystroke and again on every save, and what is wrong is underlined where it is
  written. It is the same check ``pc lint`` runs, so the editor and CI cannot
  disagree.
- **Completion from the selection.** Whatever is selected in the Explorer can be
  written into the file you are editing. In an ASSY file or a ``partcad.yaml``,
  the ``partcad: <current PartCAD item>`` completion inserts the selected part or
  assembly as a link -- its ``package:``, its ``name:``, a ``location:`` to
  adjust and whatever parameter values the Inspector is showing. In a CadQuery or
  build123d script, the matching completion inserts the ``pc.get_part_cadquery``
  or ``pc.get_part_build123d`` call that fetches it, with the same package, name
  and parameters. Find the object in the tree, and let the completion spell it.
  See the :doc:`tutorial </tutorial>`.

For a change that is easier made by drawing than by typing, the next section is
the way out of the editor and back.

.. _vscode-open:

Open
====

**Open in >**, on an object in the Explorer, opens the object's own source file
in the application that made it -- a design application that draws, next to an
editor that does not. It is one command, ``pc ide open``, run **on your
machine**: nothing about it goes near the PartCAD daemon, which may be
somewhere else entirely, and there is no RPC method for opening a window.

Seven applications, each offered for the objects it can actually open:

**FreeCAD**
  A part or an assembly. A ``.FCStd`` document is opened as it is, and anything
  else is converted to STEP on the way.

**Blender**
  A part or an assembly. Blender reads meshes and nothing else, so an STL, an
  OBJ or a glTF goes as it is and everything else -- a STEP file, a CadQuery
  script -- is converted to STL first.

**SolidCraft**
  A part or an assembly, in a workspace that imports
  `partcad-solidcraft <https://github.com/partcad/partcad-solidcraft>`_, which
  is what declares it. A SolidCraft design opens as it is, with its history;
  STEP, IGES and meshes as they are; anything else is converted to STEP.

**CADCraft**
  A drawing: any sketch PartCAD reads from a file, and a part or an assembly
  read from a DWG or a DXF -- in a workspace that imports
  `partcad-cadcraft <https://github.com/partcad/partcad-cadcraft>`_. A DXF or a
  DWG opens as it is; an SVG sketch, or one written as a CadQuery or build123d
  script, is drawn as a DXF first.

**Gazebo**
  A scene that *is* a Gazebo world -- one of type ``sim-gazebo:world``, which is
  also what ``pc export -S -t sim-gazebo:world`` writes out of any scene. This
  is how a simulation is looked at rather than only run: the world the
  :ref:`Simulation tab <sim-in-the-ui>` hands the engine, open in the engine's
  own window. Declared by
  `partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_.

**MuJoCo**
  A scene that *is* an MJCF model -- ``sim-mujoco:mjcf``, which
  ``pc export -S -t sim-mujoco:mjcf`` writes out of any scene. MuJoCo reads MJCF
  and no other model format, and nothing converts a world into it on the way.
  Declared by
  `partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_.

**KiCad**
  A part of type ``kicad``. What opens is the board beside the STEP file the
  part is, because that is the file KiCad has anything to say about.

SolidCraft, CADCraft, Gazebo and MuJoCo are not PartCAD's own: each one's
``open:`` entry is declared by the plugin package for it (see
:doc:`/plugins/applications`), and ``pc ide open`` finds it only in a workspace
that imports that package. The menu entry is there regardless, and picking it
where the package is not imported shows what ``pc ide open`` does know rather
than guessing.

An application installed here is started here. Where there is none and
``partcad.open.useDocker`` is on -- it is, by default -- PartCAD runs it in a
container instead: one container per application, created from the application's
image (or ``partcad.open.dockerImage``) the first time and reused afterwards,
with the file mounted at the path it has here or, under ``useDockerRemote``,
sent across and back. Its windows come out on your X display: on Linux the one
you are already using, and on macOS or Windows an X server you install
(XQuartz, VcXsrv), which PartCAD asks for rather than starting a container whose
windows go nowhere. ``pc system prune`` removes these containers like every
other one PartCAD starts, and a machine with neither the application nor Docker
is told so rather than left with a menu entry that quietly does nothing.

**While it is open, the editor waits.** A banner fills the editor saying what is
being edited and where, and every PartCAD command is paused, so that nothing is
built from a version that is about to be replaced. Make the change, save it and
close the application: what you saved is brought back into the object's own file
-- converted back into its own format where it had to be converted to be opened,
and kept beside the file where it cannot be (a drawing made from a script). What
PartCAD then has is a changed file, which is the same thing as a change typed in
the editor.

Export
======

Objects can be exported directly from the extension to any of the following formats: **SVG**, **PNG**,
**JPEG**, **STEP**, **STL**, **3MF**, **ThreeJS**, **OBJ**, **IGES**, and **glTF**. An engine's own scene
format — a **Gazebo world** (SDFormat), a **MuJoCo model** (MJCF) — is written by the plugin package that
implements it, so it is named through that package and exported from the command line:
``pc export -t sim-gazebo:world``.
