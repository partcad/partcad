##################
Visual Studio Code
##################

The PartCAD extension is the primary graphical interface to PartCAD. It adds a PartCAD workbench with an
Explorer view for browsing packages, an Inspector for viewing objects and editing their parameters, and the
**Digital Thread** panel over whichever object is selected.

It carries no PartCAD of its own. Like the :ref:`Desktop Application <partcad-ide>` and the FreeCAD add-on,
it is a client of the ``partcad-json-rpc`` service, so it sees the same packages and the same cache as ``pc``
does on the same machine -- and anything it can do, :doc:`/cli` can do too.

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

The Digital Thread
==================

Displaying an object opens the ``Digital Thread``, which is a strip of tabs over that one object rather than
a bare canvas: groups of tabs, each with tabs of its own -- **Design**, **Analysis**, **Manufacturing** and
**Validation**, followed by **Operations**, which has nothing in it yet and is always disabled. Design
is always the first (see :doc:`/digital_thread/index` for what each group is for):

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
    and what to do when it fails (:doc:`/digital_thread/workflows/testing`). An interference leaves an assembly of the two
    parts and what they share, to open in 3D. Always the first tab, and always enabled; an object that belongs
    to no package has nothing to ask PartCAD about, and the tab says so.
  - **Simulation** — for a part, an assembly or a scene that declares a ``simulate:`` section (see :doc:`/digital_thread/workflows/simulation`):
    the simulations it declares, listed on the left with the first one selected. Selecting one runs it, as
    ``pc sim -f <name>`` does, and shows whether its ``validation:`` held, and two pictures of the scene the
    simulation plugin took -- before anything moved on the left, and when the run was over on the right --
    from where the scene is looked at when it is rendered. A plugin that takes no pictures has not failed:
    a line says so where they would be.

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
**Animate** and **Opacity** are at the bottom of the same pane.

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

The PartCAD terminal
====================

What PartCAD is busy with -- its log and the progress of a long operation -- appears in the ``PartCAD``
terminal. It opens the first time there is something to show, to the right of a shell named ``Shell``: a
terminal running your default shell, with the PartCAD command line tools on its ``PATH``, for starting a coding
agent side by side with what PartCAD is doing.

Close it whenever you like. It stays closed until you run **PartCAD: Show Terminal** or pick **PartCAD** from the
terminal panel's **+** menu, and then it opens with everything it missed. Set ``partcad.reopenTerminal`` to
``true`` to have new output reopen it instead, and ``partcad.popupTerminal`` to bring it to the front on every
new line. If PartCAD stops working in the window -- no PartCAD service, or one that will not start or keeps
stopping -- it opens on its own and says why, with a popup as well if it was closed.

Export
======

Objects can be exported directly from the extension to any of the following formats: **SVG**, **PNG**,
**JPEG**, **STEP**, **STL**, **3MF**, **ThreeJS**, **OBJ**, **IGES**, and **glTF**. An engine's own scene
format — a **Gazebo world** (SDFormat), a **MuJoCo model** (MJCF) — is written by the plugin package that
implements it, so it is named through that package and exported from the command line:
``pc export -t sim-gazebo:world``.
