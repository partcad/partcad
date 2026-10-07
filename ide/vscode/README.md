# PartCAD

[PartCAD](https://github.com/partcad/partcad) is the standard for documenting manufacturable physical products. It comes with a set of tools to maintain product information and to facilitate efficient and effective workflows at all product lifecycle phases.

PartCAD is more than just a traditional CAD tool for drawing. In fact, it's not for drawing at all. The letters "CAD" in PartCAD stand for "computer-aided design" in a more generic sense, where "design" stands for the process of getting from an idea to a clear and deterministic specification of a manufacturable physical product using a computer (including the use of AI models). While PartCAD started as the first package manager for hardware, it is now the next-generation CAD that can turn a single visionary individual into a one person corporation, or make one future Product Manager as productive (and much faster!) as 10 corporate engineering departments of the past.

PartCAD is constantly evolving, with new features and integrations being added all the time. [Contact us](mailto:support@partcad.org) to discuss how [PartCAD](https://partcad.org/) can revolutionize your product development process.

## PartCAD VSCode Extension

This extension helps create PartCAD packages and explore packages that are already published.
To learn more about PartCAD, see [the documentation](https://partcad.readthedocs.io/) or [the project repo](https://github.com/partcad/partcad).
Also, make sure to visit [our website](https://partcad.org/) and browse [the repository of published 3D models](https://partcad.org/repository).

![Screenshot 1](https://github.com/partcad/partcad/blob/main/docs/source/images/vscode1.png?raw=true)

![Screenshot 2](https://github.com/partcad/partcad/blob/main/docs/source/images/vscode2.png?raw=true)

## PartCAD Viewer

Selecting a part, assembly, scene, sketch or interface opens it in the **PartCAD Viewer** tab. PartCAD
tessellates the shape in a sandboxed runtime and sends the result to this extension as compressed glTF over a
socket on `127.0.0.1:9137`, so the viewer needs no CAD library of its own. The Python side of that connection
is the `partcad_ide_client` package, which ships inside `partcad` itself.

Anything that can reach that port displays into the same viewer, including a `pc ide view` run in a plain
terminal. Set `PARTCAD_IDE_PORT` to move both ends off the default port.

The panel is a strip of tabs over the one object, not just a canvas: groups, **Design** (the object
itself), **Analysis** (analysing it) and **Manufacturing** (making it), each with tabs of its own, then
**Validation** and **Operations**, which are always disabled for now. Every group
shows all of its tabs, disabling what does not apply, and Analysis and Manufacturing are disabled
themselves when none of theirs does - hovering over a disabled group says why; each opens on the tab last opened in it while that one applies,
and on the first that does otherwise.

| tab | what it shows |
| --- | --- |
| **Design → 3D** | The shape, drawn here from what arrived over the socket above. |
| **Design → 2D** | The object rendered to a PNG, JPEG or SVG picture, as `pc render` renders it, with **Save…**. |
| **Design → Draft** | For a part or an assembly: a dimensioned technical drawing by `//pub/feature/render/draftwright`, in the formats it offers (PDF, SVG, DXF), with **Save…**. |
| **Analysis → FEA**, **CFD** | For a part: the analysis `pc cae` runs, and what it found. |
| **Manufacturing → Build vs Buy** | For a part or an assembly: every part, piece of stock and sub-assembly it is made of, with a picture, a count, its size, weight and material, and a **Build**/**Buy** switch on each. A line that can only be bought or only be built has its switch fixed, saying why; a line that can be neither is marked **Incomplete**; building a line brings in what it is made of, buying it hides that. The choices are kept on this machine, in `~/.partcad/garage/default/bvb/`, and `pc instructions` reads them too. |
| **Manufacturing → Build** | For whatever is built: the order to make it in - a part's stock first and the part last; an assembly's links, each built part preceded by the step that makes it, and with **Recursively** each built sub-assembly before the link that adds it. Selecting a step shows its page of the instructions: how to make a part (and its CAM toolpath, where it is cut), or the step that adds a link. |
| **Manufacturing → Buy** | For whatever is bought: where it can be bought, and a quote per supplier. |
| **Manufacturing → Bill of Materials** | For a part or an assembly: what has to be procured to have it, as `pc bom` lists it - a made part as the stock it is made from, a sub-assembly with a vendor and an SKU as one item ordered whole. |
| **Manufacturing → Assembly** | For an assembly: the assembly instructions as a PDF or HTML document, with **Recursive** and **Build parts** (`pc instructions -r -b`) and **Save…**. Manufacturing is disabled for a scene, a sketch or an interface. |

Only the 3D view comes over the viewer protocol. The others are questions about `<package>:<name>` that this
extension puts to the PartCAD daemon, fetched the first time a tab is looked at and cached until the next
object is shown — so an object belonging to no package gets the 3D view alone. In a window without WebGL —
a virtual machine, a remote desktop, a GPU the editor could not use — the 3D view and the FEA and CFD models are
drawn with WebGPU where the window has it, and without the graphics card otherwise: flat-shaded and slower, with
a big model drawn as boxes while it is being turned. It says so in a corner, and hovering there says how to have
the graphics card back.

### 3Dconnexion SpaceMouse

The 3D view can be navigated with a 3Dconnexion SpaceMouse: the cap moves the model the way it is pushed and
twisted, and the **Fit** button (the right-hand one on a two-button device) frames it again. On Windows and
macOS the viewer reads the device on its own — move the cap once with the viewer open for the editor to notice
it. On Linux it reads it from [spacenavd](https://spacenav.sourceforge.net/), which has to be installed and
running (`sudo apt install spacenavd`, for example). Only the viewer in the focused window moves.
`partcad.spaceMouse.sensitivity` sets the speed, `partcad.spaceMouse.invert` reverses individual axes, and
`partcad.spaceMouse.enabled` turns it off.

## The PartCAD terminal

What PartCAD is busy with -- its log and the progress of a long operation -- appears in the `PartCAD` terminal.
It opens the first time there is something to show, to the right of a shell named `Shell`: a terminal running
your default shell, with the PartCAD command line tools on its `PATH`, for starting a coding agent side by side
with what PartCAD is doing.

Close it whenever you like. It stays closed until you run **PartCAD: Show Terminal** or pick **PartCAD** from the
terminal panel's **+** menu, and then it opens with everything it missed. Set `partcad.reopenTerminal` to `true`
to have new output reopen it instead, and `partcad.popupTerminal` to bring it to the front on every new line. If
PartCAD stops working in the window -- no PartCAD service, or one that will not start or keeps stopping -- it
opens on its own and says why, with a popup if it was closed.

## The command line in the integrated terminal

While the extension is active, terminals opened in the window get the PartCAD command line tools on their
`PATH`, so `pc` and `partcad` work without installing anything separately or editing a shell profile. VS Code
marks such a terminal and will show you which extension changed the environment. Terminals already open when
the extension activates keep the environment they started with; reopen one to pick the tools up. Set
`partcad.addToolsToTerminalPath` to `false` to keep a PartCAD of your own on the `PATH` instead.

## Creating PartCAD packages

After this extension is installed, the PartCAD workbench becomes available.

Usually, the first step suggested by the workbench is to initialize the current workspace
as a new PartCAD package.
After that new parts and assemblies can be added
using the corresponding buttons in the PartCAD explorer view.

## Creating parts

If you have a CAD file created in some other tool then click
the `Add a CAD file to the current package` button in
the PartCAD Explorer's toolbar (hover the mouse over the middle left view
to see toolbar icons on the top of the view) and select the file
(STEP, STL, 3MF etc) from the current workspace.

If you want to add a script file (CadQuery, build123d, OpenSCAD etc)
that you can edit in VS Code,
then click the `Add a CAD script to the current package` button
in the PartCAD Explorer's toolbar.
If you select a file that does not exist
then you will be prompted for the template to use.

When you edit scripts that are registered in the current PartCAD package,
saving the file makes it displayed in the PartCAD Viewer view.

## Creating assemblies

This is what PartCAD (or, at least, its VS Code Extension) is actually for.

Click `Add an assembly file to the current package` and select a file with
the ".assy" extension. ASSY (Assembly YAML) follows YAML syntax.
The list of parts has to be added as children under the `links` node.

Select the desired part or assembly in PartCAD Explorer.
After that navigate to the next line under the `links` node and type "- pa"
(which is what you do when you want to add a child item with the name "part")
and let VS Code use the first suggested code completion suggestion.
This will add the selected part or assembly to the currently edited assembly.

When you edit ASSY files that are registered in the current PartCAD package,
saving the file makes it displayed in the PartCAD Viewer view.

### Checking assemblies while you edit

An ASSY file is a Jinja2 template that renders to YAML, and the result has to
match the ASSY schema. The extension checks all three of those while the file is
open -- template errors, YAML errors and schema errors, such as a mistyped key or
a `location` that is not an OCCT location -- and reports them in the Problems
view at the line they came from. A file that uses `{% for %}` loops or
`{{ parameters }}` is checked as it renders, with the default values of the
parameters its declaration in `partcad.yaml` gives it: a finding inside a loop
is reported once, at the loop's body, and one about a computed value at the
`{{ }}` that computed it. A file no package declares yet is checked without
rendering, and anything that depends on a template value is left out rather than
guessed at. An assembly or a part marked `manufacturable: true` is also held to
what something that is to be made needs: items connected rather than placed, and
parts that say how they are made or bought.

The **PartCAD > Lint** settings say how:

* `partcad.lint.enabled` turns the check off.
* `partcad.lint.includePaths` adds directories that templates may
  `{% include %}` from, relative to the workspace folder -- for files a package
  above yours provides through `includePaths`, when that package is not in a
  directory above the file.
* `partcad.lint.extraParams` renders files with other parameter values than
  their defaults, written as `pc --extra-param` takes them:
  `desk.length=60` (or `//pub/furniture:desk.length=60`).

ASSY files and `partcad.yaml` are languages of their own in the editor, "PartCAD
ASSY" and "PartCAD Package Configuration": highlighted as YAML, with the
template's `{% %}`, `{{ }}` and `{# #}` tags highlighted on top. That also keeps
YAML extensions from checking them as plain YAML, which reported template tags
such as `{% for %}` as errors.

With [Code Spell Checker](https://marketplace.visualstudio.com/items?itemName=streetsidesoftware.code-spell-checker)
installed, the words these files are written in -- `assy`, `cadquery`,
`connectPorts`, every other key and value the ASSY and package schemas spell,
and Jinja2's `endfor` -- are not flagged as typos in them. Everything else,
such as a `desc:`, is still checked.

## Opening an object in another application

Right-click an object in the PartCAD Explorer and pick **Open in > ...** to open the file it is defined by in
the application that made it. It is the object's own source file that is opened, so this is the way to reach it
in a tool that draws, next to what the extension does with it.

* **FreeCAD**, for a part or an assembly.
* **Blender**, for a part or an assembly. Blender reads meshes and nothing else, so an object that is not
  already one (a STEP file, a CadQuery script) is converted to STL first and Blender is given that; an STL, an
  OBJ or a glTF is imported as it is. The converted copy lives under PartCAD's own directory for this
  workspace, never beside your file, and is reused until the object changes.
* **Gazebo**, for a scene that *is* a Gazebo world -- one of type `world`, which is also what
  **Export > Gazebo world...** writes out of any scene.
* **MuJoCo**, for a scene held in a simulator's format -- one of type `mjcf` or `world`. MuJoCo reads MJCF
  and no other model format, so a world is written out as MJCF first and MuJoCo is given that, the same way
  a solid is converted for Blender.
* **KiCad**, for a part of type `kicad`. What is opened is the board (`.kicad_pro`) beside the STEP the part
  is, because that is the file KiCad has anything to say about.

This runs on your machine and never goes anywhere near the PartCAD daemon: the extension runs `pc ide open`, which
looks for the application installed here and starts it. If there is none, and `partcad.open.useDocker` is on (the default),
PartCAD runs it in a Docker container instead -- one container per application, created from its image (or
`partcad.open.dockerImage`) the first time and reused afterwards, with the file mounted at the path it has
here, or, with `useDockerRemote` on, sent to the container and back. Its windows come out on your X display.
On Linux that is the display you are already using; on macOS and Windows it needs an X server (XQuartz,
VcXsrv) that PartCAD cannot install for you, so it tells you which one to install and what to allow rather
than starting a container whose windows go nowhere. `pc system prune` removes these containers like every
other one PartCAD starts. Turn
`partcad.open.useDocker` off to use installed applications only. Either way, a machine that has neither the
application nor Docker is told so rather than left with a menu entry that quietly does nothing.

While the application is open, VS Code waits for it: a banner fills the editor saying what is being edited
and where, and every PartCAD command is paused, so that nothing is built from a version that is about to
be replaced. Make your changes, save them and close the application; what you saved is brought back into
the object's own file -- converted back into its format, when it had to be converted to be opened (a STEP
part opened in Blender comes back as STEP). A part generated by a script cannot be written back into, so
its edit is kept where it was made and the message says where. **Stop waiting** on the banner, or Cancel on
the progress notification, gives you the editor back and leaves the application open, but what you save in
it after that is not brought back.

## Inspecting published PartCAD packages

To see a good example of a package with parts, it is recommended to browse
`pub` -> `robotics` -> `parts` -> `gobilda`.

To see a basic example of a package with assemblies, it is recommended to browse
`pub` -> `furniture` -> `workspace` -> `basic`.
Please, note, that there are customizable parameters that can be tweaked in the PartCAD Inspector view
(the bottom left view).

To see an example of a package with more complex assemblies, it is recommended to browse
`pub` -> `robotics` -> `multimodal` -> `openvmp` -> `robots` -> `don1`.
Please, note, that it takes A LOT OF resources to render the full `robot` assembly.
It's easier to test some parts of the robot like `link-lower-arm` or `link-base`.

## Implementation notes

### Where PartCAD itself comes from

This extension is a client. It talks to a `partcad-json-rpc` executable, and it finds one in this order: the
`partcad.servicePath` setting, an existing standalone installation, a bundle it downloaded before, `~/.local/bin`,
and finally your `PATH`. That last one means `pip install partcad` in a Python environment of your own is enough
— the extension picks it up and downloads nothing. If it finds none of them, it offers to download a standalone
bundle, which needs no Python at all.

Nor any conda: PartCAD builds every shape in a conda sandbox, and the bundle carries the conda that builds it,
so a machine with none still renders parts. A `conda` or `mamba` you have installed is used in preference to
the bundled copy — see
[the standalone README](https://github.com/partcad/partcad/blob/main/dev-tools/pyinstaller/README.md#conda).

`pc upgrade` run inside a bundle this extension downloaded will refuse and tell you to update the extension
instead: the extension owns that bundle, and upgrading it from underneath would leave a copy the extension does
not know about.

## More documentation

To learn more about PartCAD and for a more detailed tutorial,
see [the PartCAD documentation website](https://partcad.readthedocs.io/).
