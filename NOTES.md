# Notes

## Suggestions

* There is no Quick Start section on https://partcad.org/
  * - You can not wait, think "fly" - Jake's First Flight On Ikran

## Questions

* What is `build123d` in `OCP CAD VIEWER`
* What is `CadQuery` in `OCP CAD VIEWER`
* Can `OCP CAD VIEWER` use existing Python virtual env?
* Why `conda`?

## Problems

```
ERROR: OpenSCAD executable is not found. Please, install OpenSCAD first.
```

* It's an error from tutorial. Solution is `sudo apt-get install openscad`.


## Related issues

* [Poetry glibc version check](https://github.com/python-poetry/poetry/issues/9837)


```bash
python -m cProfile -o pc-version.prof $(command -v pc) version
flameprof -o /tmp/pc-version.svg -r $(command -v pc) version
```

```bash
conda info --envs
conda create -n ocp-cad-viewer python=3.10
conda activate ocp-cad-viewer
```

```bash
"/home/vscode/miniconda3/envs/ocp-cad-viewer/bin/python" -m pip install ocp_vscode==2.6.1 git+https://github.com/gumyr/build123d ## && exit
```

```bash
env -u CONDA_PREFIX_1  "/home/vscode/miniconda3/envs/ocp-cad-viewer/bin/python" -m pip install ocp_vscode==2.6.1 git+https://github.com/cadquery/cadquery.git && exit
```

## TODO

```
features/partcad-cli/
├── commands
│   ├── add
│   │   ├── assembly.feature - Add an assembly
│   │   ├── package.feature - Import a package
│   │   └── part.feature - Add a part
│   ├── info.feature - Show detailed info on a part, assembly or scene
│   ├── init.feature - Initialize a new PartCAD package in this directory
│   ├── inspect.feature - Visualize a part, assembly or scene
│   ├── install.feature - Download and prepare all imported packages
│   ├── list
│   │   ├── all.feature - List available parts, assemblies and scenes
│   │   ├── assemblies.feature - List available assemblies
│   │   ├── interfaces.feature - List available interfaces
│   │   ├── mates.feature - List available mating interfaces
│   │   ├── packages.feature - List imported packages
│   │   ├── parts.feature - List available parts
│   │   └── sketches.feature - List available sketches
│   ├── render.feature - Render the selected or all parts, assemblies and scenes in this package
│   ├── status.feature - Display the state of internal data used by PartCAD
│   ├── supply
│   │   ├── caps.feature
│   │   ├── find.feature
│   │   ├── order.feature - Supplier related commands
│   │   └── quote.feature
│   ├── test.feature - Render the selected or all parts, assemblies and scenes in this package
│   ├── update.feature - Update all imported packages
│   └── version.feature - Print PartCAD version and exit
└── pc.feature - Global options
```

```
Failing scenarios:
  features/partcad-cli/commands/list/packages.feature:5  List all PartCAD packages in uninitialized directory
```