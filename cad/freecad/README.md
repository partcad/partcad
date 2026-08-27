# PartCAD for FreeCAD

Browse [PartCAD](https://partcad.org/) packages inside FreeCAD, set a part's or an assembly's parameters, and
import the result into the document you are working on.

![Apache 2.0](../apache20.svg)

## What it does

- **Explorer panel.** Every package, assembly, part, interface and sketch PartCAD can reach, as a tree — the
  same hierarchy `pc list all -r` prints. Packages expand on demand, because a recursive walk of the public
  repository clones every package it touches.
- **A dialog generated from the object.** Selecting a part or an assembly (double click, Enter, or the *Import
  Selected* command) opens a dialog with one control per declared parameter: a check box for a `bool`, a combo
  box for an `enum`, a spin box for an `int`, a text field for a `float`, a `string` or an array.
- **Import as STEP.** Confirming the dialog renders that exact parameter combination to a temporary STEP file
  and inserts it into the active document (creating one if there is none). The temporary file is removed
  afterwards; what is left is ordinary FreeCAD geometry, labelled after the PartCAD object and its parameters.

## Requirements

- FreeCAD 0.21 or newer (tested against the 1.x line).
- Network access the first time, to fetch the PartCAD service.
- `git` and `conda`/`mamba` on `PATH` for the packages and CAD scripts PartCAD builds in a sandbox — the same
  prerequisites the PartCAD command line tools have. `pc healthcheck` reports what is missing.

You do **not** need Python skills, a Python environment, or a PartCAD installation. The addon drives the
standalone `partcad-json-rpc` service — a self-contained bundle carrying its own interpreter — because
FreeCAD's embedded Python cannot be asked to host PartCAD itself.

## Installing

Copy (or symlink) this directory into FreeCAD's `Mod` folder as `PartCAD`, then restart FreeCAD:

| system | `Mod` folder |
| --- | --- |
| Linux | `~/.local/share/FreeCAD/Mod/` |
| macOS | `~/Library/Preferences/FreeCAD/Mod/` |
| Windows | `%APPDATA%\FreeCAD\Mod\` |

```bash
git clone https://github.com/partcad/partcad.git
ln -s "$PWD/partcad/cad/freecad" ~/.local/share/FreeCAD/Mod/PartCAD
```

Select **PartCAD** in FreeCAD's workbench dropdown afterwards.

FreeCAD's Addon Manager cannot install this yet: it installs a *repository*, and this addon is one directory of
the PartCAD monorepo. The `package.xml` here is what the Addon Manager reads once that changes.

## First use

1. **PartCAD → Open Package…** and pick a directory holding a `partcad.yaml`. If it holds none, the addon
   offers to create one there.
2. The first time, it offers to download the PartCAD service (~60 MB compressed, ~180 MB unpacked). An
   existing installation is used instead of downloading — one made by
   [`install.sh`](https://github.com/partcad/partcad#installation), by the PartCAD VS Code extension, or by an
   earlier run of this addon.
3. Expand the tree, then double-click a part or an assembly to import it.

Progress and errors are reported in FreeCAD's **Report view** (View → Panels → Report view), prefixed with
`PartCAD:`.

## Where the service comes from

The addon looks for `partcad-json-rpc` in this order:

1. `PC_CAD_SERVICE_PATH`, if it points at an executable;
2. a bundle this addon downloaded before;
3. an `install.sh` installation (`~/.local/share/partcad/<version>/`, `~/.local/bin/`);
4. anything named `partcad-json-rpc` on `PATH`.

If none is found, it downloads one: the **latest GitHub release** carrying a bundle for your platform, or — when
that release publishes no bundle for it — the **latest `devel` build**. Downloading a `devel` build uses the
GitHub Actions artifact API, which rejects anonymous requests even for a public repository, so it needs a token
in `PC_CAD_GITHUB_TOKEN` (or `GITHUB_TOKEN` / `GH_TOKEN`) with public repository read access.

## Environment variables

| variable | effect |
| --- | --- |
| `PC_CAD_DEVEL` | Use the latest `devel` CI bundle instead of a release. |
| `PC_CAD_GITHUB_TOKEN` | Token for the Actions artifact API (`GITHUB_TOKEN` / `GH_TOKEN` also work). |
| `PC_CAD_SERVICE_PATH` | Use this `partcad-json-rpc` executable, skipping the search entirely. |
| `PC_CAD_BUNDLE_DIR` | Where a downloaded bundle is unpacked (default: FreeCAD's user data directory). |
| `PC_CAD_PACKAGE_DIR` | Open this package directory instead of the remembered one. |
| `PC_CAD_REPOSITORY` | GitHub repository to download from (default: `partcad/partcad`). |
| `PC_CAD_BRANCH` | Branch whose CI bundle to use (default: `devel`). |

## Notes and limitations

- Sketches and interfaces are listed for orientation but cannot be imported: there is no solid to hand FreeCAD.
- The import is geometry, not a live link — changing a parameter means importing again.
- The addon shares the PartCAD daemon with `pc` and the VS Code extension, so a package one of them updates is
  what the others see.

## License

Apache License 2.0, the same as the rest of [PartCAD](https://github.com/partcad/partcad).
