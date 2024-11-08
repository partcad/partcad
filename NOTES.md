# Notes

## Suggestions

- There is no Quick Start section on https://partcad.org/

## Questions

- What is `build123d` in `OCP CAD VIEWER`
- What is `CadQuery` in `OCP CAD VIEWER`
- Can `OCP CAD VIEWER` use existing Python virtual env?
- Why `conda`?

## Problems

```
ERROR: OpenSCAD executable is not found. Please, install OpenSCAD first.
```

- It's an error from tutorial. Solution is `sudo apt-get install openscad`.

## Related issues

- [Poetry glibc version check](https://github.com/python-poetry/poetry/issues/9837)

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

```bash
# Leave cute environment if any
[ -n "$VIRTUAL_ENV" ] && deactivate

export TESTBED_DIR=/tmp/testbed
mkdir -pv "${TESTBED_DIR}" && cd "${TESTBED_DIR}"
conda create --yes --name testbed python=3.11
conda info --envs
conda activate testbed
# python -m venv testbed
python -m pip install partcad-cli
```

```bash
export PATH=\
.venv/bin:\
/bin:\
/bin:\
/home/node/.local/bin:\
/home/node/.vscode-server/extensions/ms-python.python-2024.20.0-linux-x64/python_files/deactivate/bash:\
/home/node/miniconda3/bin:\
/home/node/miniconda3/envs/testbed/bin:\
/home/vscode/miniconda3/bin:\
/opt/pip/bin:\
/sbin:\
/usr/bin:\
/usr/local/bin:\
/usr/local/sbin:\
/usr/local/share/npm-global/bin:\
/usr/local/share/nvm/current/bin:\
/usr/sbin:\
/vscode/vscode-server/bin/linux-x64/f1a4fb101478ce6ec82fe9627c43efbf9e98c813/bin/remote-cli:\
/workspaces/partcad/.venv/bin:\
```

Play in vanilla container with VS Code Interpreter and Python extension:

- Try conda
- Try venv
- Try `donjayamanne.python-environment-manager` extension

Current problem is that something is contaminating PATH and putting this in the beginning of PATH:

- `/workspaces/partcad/.venv/bin`

```json
  "remoteEnv": {
    // export PATH="/home/vscode/miniconda3/bin:$PATH"
    "PATH": "${containerEnv:PATH}:/opt/pip/bin:.venv/bin:/home/vscode/miniconda3/bin"
  },
```

```bash
pip install yq
```
