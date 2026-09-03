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

Anything that can reach that port displays into the same viewer, including a `pc inspect` run in a plain
terminal. Set `PARTCAD_IDE_PORT` to move both ends off the default port.

The panel is a strip of tabs over the one object, not just a canvas. The 3D view is always the first; the rest
appear where they apply:

| tab | what it shows |
| --- | --- |
| **3D** | The shape, drawn here from what arrived over the socket above. |
| **Bill of Materials** | For an assembly or a scene: every part it is made of, recursively, counted. |
| **Instructions** | For an assembly that declares its steps: the assembly guide, step by step. |
| **Supply** | Where the objects in view can be bought, and a quote per supplier. |

Only the 3D view comes over the viewer protocol. The others are questions about `<package>:<name>` that this
extension puts to the PartCAD daemon, fetched the first time a tab is looked at and cached until the next
object is shown — so an object belonging to no package gets the 3D view alone.

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
`{{ parameters }}` is checked too: what those stand in for is unknown until the
template is rendered, so a schema finding that depends on such a value is left
out rather than guessed at. Set `partcad.lint.enabled` to `false` to turn this
off.

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
* **KiCad**, for a part of type `kicad`. What is opened is the board (`.kicad_pro`) beside the STEP the part
  is, because that is the file KiCad has anything to say about.

This runs on your machine and never goes anywhere near the PartCAD daemon: the extension runs `pc open`, which
looks for the application installed here and starts it. If there is none, and `partcad.open.useDocker` is on,
PartCAD runs it in a Docker container instead -- one container per application, named after it
(`partcad-freecad`, `partcad-blender`, `partcad-gazebo`, `partcad-kicad`), created from the application's image (or
`partcad.open.dockerImage`) the first time and reused afterwards, with your
workspace and the PartCAD daemon's socket mounted at the paths they have here, so one path means the same thing
on both sides. Its windows come out on your X display. On Linux that is the display you are already using; on
macOS and Windows it needs an X server (XQuartz, VcXsrv) that PartCAD cannot install for you, so it tells you
which one to install and what to allow rather than starting a container whose windows go nowhere. Remove the
container of the application in question (`docker rm -f partcad-freecad`, `partcad-blender`,
`partcad-gazebo` or `partcad-kicad`) to have the next open create a fresh one. With
`partcad.open.useDocker` off, a machine that has neither the application nor Docker is told so rather than
left with a menu entry that quietly does nothing.

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

`pc upgrade` run inside a bundle this extension downloaded will refuse and tell you to update the extension
instead: the extension owns that bundle, and upgrading it from underneath would leave a copy the extension does
not know about.

## More documentation

To learn more about PartCAD and for a more detailed tutorial,
see [the PartCAD documentation website](https://partcad.readthedocs.io/).
