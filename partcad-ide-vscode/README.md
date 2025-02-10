# PartCAD

[PartCAD](https://github.com/partcad/partcad) is the standard for documenting manufacturable physical products. It comes with a set of tools to maintain product information and to facilitate efficient and effective workflows at all product lifecycle phases.

PartCAD is more than just a traditional CAD tool for drawing. In fact, it’s not for drawing at all. The letters “CAD” in PartCAD stand for “computer-aided design” in a more generic sense, where “design” stands for the process of getting from an idea to a clear and deterministic specification of a manufacturable physical product using a computer (including the use of AI models). While PartCAD started as the first package manager for hardware, it is now the next-generation CAD that can turn a single visionary individual into a one person corporation, or make one future Product Manager as productive (and much faster!) as 10 corporate engineering departments of the past.

PartCAD is constantly evolving, with new features and integrations being added all the time. [Contact us](mailto:support@partcad.org) to discuss how [PartCAD](https://partcad.org/) can revolutionize your product development process.

## PartCAD VSCode Extension

This extension helps create PartCAD packages and explore packages that are already published.
To learn more about PartCAD, see [the documentation](https://partcad.readthedocs.io/) or [the project repo](https://github.com/openvmp/partcad).
Also, make sure to visit [our website](https://partcad.org/) and browse [the repository of published 3D models](https://partcad.org/repository).

![Screenshot 1](https://github.com/openvmp/partcad/blob/main/docs/source/images/vscode1.png?raw=true)

![Screenshot 2](https://github.com/openvmp/partcad/blob/main/docs/source/images/vscode2.png?raw=true)

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
saving the file makes it displayed in the OCP CAD Viewer view.

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
saving the file makes it displayed in the OCP CAD Viewer view.

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

### Failed to load PartCAD: \_nlopt

If you see the above error message then you are probably using Windows and not using Conda.
Please, switch to a Python environment created with Conda and Python >=3.10 and <=3.11.

## More documentation

To learn more about PartCAD and for a more detailed tutorial,
see [the PartCAD documentation website](https://partcad.readthedocs.io/).
