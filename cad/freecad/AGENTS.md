# cad/freecad

The **PartCAD** addon (workbench) for [FreeCAD](https://www.freecad.org/). It shows PartCAD packages, parts and
assemblies as a hierarchy — the same one `pc list all -r` walks — asks for an object's parameters, and imports
the result into the active FreeCAD document as a STEP file.

This directory *is* the addon: FreeCAD loads a directory under its `Mod/` folder by executing the `Init.py` and
`InitGui.py` at its root, with that directory on `sys.path`. There is no wheel and no build step. See
[README.md](./README.md) for how a user installs and uses it.

## Why it talks to the service instead of importing partcad

FreeCAD embeds its own Python interpreter, which a user cannot be asked to grow a PartCAD installation in (and
which PartCAD's CAD dependencies would fight with). So the addon is a **thin client of
[`partcad_service_json_rpc`](../../src/partcad_service_json_rpc)**, running as the frozen PyInstaller bundle: it speaks
framed JSON-RPC to the per-workspace daemon, exactly as `pc` and the VS Code extension do, and shares the warm
context with them. Nothing in this directory imports `partcad`.

`provision.py` finds that bundle: an `install.sh` installation, one the VS Code extension downloaded, one on
`PATH`, or one it downloads itself. Downloads come from the latest GitHub release that carries a bundle for the
host platform; when the latest release publishes no such bundle — the standalone archives are a later addition
than the wheels, so a release may have none — it falls back to the newest `devel` CI artifact, as it does
whenever `PC_CAD_DEVEL` is set.

## Layout

Inside `partcad_freecad`, only `gui/` and `importer.py` need FreeCAD or Qt to import; everything else is plain
Python, which is what makes the suite runnable in CI where neither exists. `InitGui.py` is not part of that
package and does import FreeCAD — it is the root entry point FreeCAD itself executes.

- `InitGui.py` / `Init.py` — what FreeCAD executes; registration only.
- `package.xml` — Addon Manager metadata.
- `partcad_freecad/framing.py`, `client.py` — the JSON-RPC wire protocol (a copy of the service's own codec;
  the addon cannot import the service's Python package, that is the point of the frozen bundle).
- `partcad_freecad/provision.py` — locating/downloading/unpacking the standalone bundle.
- `partcad_freecad/service.py` — the operations the addon uses, and the notification stream they really answer
  through (`items`, `log`, the `*Failed` signals).
- `partcad_freecad/model.py` — the package/object tree built from an `items` notification.
- `partcad_freecad/params.py` — the parameter model: what to render, and how to read a control's value back.
- `partcad_freecad/importer.py` — temporary STEP naming, and the insert into a FreeCAD document.
- `partcad_freecad/gui/` — `qt.py` (the PySide2/PySide6 shim), `worker.py` (calls off the Qt thread),
  `dialog.py` (the generated parameter dialog), `explorer.py` (the tree), `controller.py` (the flows),
  `commands.py` (the FreeCAD commands).

## Test and validate changes

From the repository root, inside the [dev container](../../AGENTS.md):

```bash
poetry run pytest cad/freecad -x -p no:error-for-skips -p no:warnings --dist no   # matches CI
```

`tests/test_gui_qt.py` drives the real widgets and **skips** when no Qt binding is installed, which is the case
in CI (Qt arrives with FreeCAD, not with the test environment). Install one to run it:

```bash
pip install PySide6-Essentials     # then the same pytest command runs them offscreen
```

`tests/test_gui_imports.py` covers what remains untested without Qt: that every GUI module imports, against
stand-ins for `PySide` and FreeCAD. It is what catches an enum on the wrong class or a renamed helper, which
would otherwise only fail when a user first activates the workbench.

There is no test that runs FreeCAD itself. Changes to `importer.insert_step` — the only function that touches
the FreeCAD document API — have to be exercised by hand, in FreeCAD.

## Lint / format

```bash
poetry run black --check cad/freecad
poetry run flake8 cad/freecad
```

## Manual check

Symlink this directory into FreeCAD's `Mod` folder and start FreeCAD:

```bash
ln -s "$PWD" ~/.local/share/FreeCAD/Mod/PartCAD     # ~/Library/Preferences/FreeCAD/Mod on macOS
```

Then switch to the PartCAD workbench, open `examples/produce_part_cadquery_primitive` from this repository, and
import `cube` — it has parameters, so it exercises the dialog, the export and the import in one go.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting and lint checks on commit and
are required to pass in CI before a PR can merge.
