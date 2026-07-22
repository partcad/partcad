# partcad-cli

PartCAD is the first package manager for CAD models and a framework for managing
manufacturable physical products. It aims to complement Git with everything
necessary to substitute commercial Product Lifecycle Management (PLM) tools.

This Python package provides the PartCAD command line interface. It is installed
as two equivalent commands, `pc` and `partcad`, which expose most of the
functionality of the [`partcad`](https://pypi.org/project/partcad/) core module.

## Installation

```shell
pip install -U partcad-cli
```

PartCAD works best when [conda](https://docs.conda.io/) is installed. On Windows,
run PartCAD inside a conda environment.

## Usage

Run `pc --help` to see all commands, and `pc <command> --help` for the options of
a specific command. The most common commands are:

- `pc init` — Create a new PartCAD package in the current directory.
- `pc install` — Download and set up all imported packages.
- `pc list` — List parts, sketches, assemblies, interfaces, and packages.
- `pc add` / `pc import` — Add or import a part, sketch, or assembly.
- `pc inspect` — View a part, assembly, or scene visually.
- `pc test` — Run tests on a part, assembly, or scene.
- `pc render` / `pc export` — Render 2D projections or export 3D models to a file.
- `pc ai regenerate` — Regenerate an object with a configured AI model.
- `pc supply` — Quote and order parts through providers.

See the [command reference](https://partcad.readthedocs.io/en/latest/cli.html) for
the full list of commands.

## Documentation

See [the main PartCAD repo](https://github.com/partcad/partcad/) and
[the documentation website](https://partcad.readthedocs.io/) for more information.
For the PartCAD core Python module, see the [`partcad`](https://pypi.org/project/partcad/)
package instead.
