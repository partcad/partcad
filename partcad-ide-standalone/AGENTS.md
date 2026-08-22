# partcad-ide-standalone

Builds the **PartCAD IDE**: a [VSCodium](https://vscodium.com/) build, rebranded, with the extensions from
`../.vscode/extensions.json` installed and the standalone command line tools inside it. Shell (`build.sh`) plus
Python helpers in `./tools`, no package to install. `README.md` explains what each step does and why; this file
is the commands.

Nothing here is imported by `partcad`, and it produces no wheel. It downloads a published VSCodium release and
edits it; it does not build an editor from source.

## Build

From the repository root:

```bash
partcad-ide-standalone/build.sh --with-cli-bundle dist/standalone/partcad   # the whole thing
partcad-ide-standalone/build.sh --no-extensions --no-archive                # fast, for branding work
partcad-ide-standalone/build.sh --help
```

`--with-cli-bundle` takes what `dev-tools/pyinstaller/build.sh --no-archive` leaves in `dist/standalone/partcad`.
Node.js is needed (the extensions are packaged with `vsce`); `cairosvg`, `Pillow`, `rcedit` and -- on Windows --
Inno Setup 6.3+ (`ISCC.exe`, for `installer/partcad-ide.iss`) are optional, and the build reports what it
skipped without them. Output lands in `dist/ide/`.

## Test

```bash
python -m pytest partcad-ide-standalone/tests -o addopts=       # the build tooling
```

`-o addopts=` because the repository-wide `pyproject.toml` options pull in coverage and reporting plugins these
tests have no use for. They are not part of the `pytest partcad partcad-cli` run or of the `pre-commit` hook;
`.github/workflows/build-ide-standalone.yml` runs them, before it spends an hour building.

There is no unit test for `build.sh` itself. What checks it is `tools/verify_bundle.py`, which the build runs on
its own result, and the `install` job in that workflow, which installs the archive and runs what comes out.

## Change what ships

- **An extension**: add it to `../.vscode/extensions.json`. Only touch `extensions.json` here when it cannot be
  installed from Open VSX or cannot be redistributed, and say which in the `reason`.
- **Branding, or a default setting**: `product.overlay.json`. A `null` removes a key; `${VERSION}` is the
  PartCAD version.
- **What the IDE does on startup**: `bootstrap/extension.js`. It is plain JavaScript, packaged as it is -- no
  compile step, so keep it that way.
- **What the Windows installer sets up**: `installer/partcad-ide.iss`. Never change its `AppId`: Windows
  recognizes an upgrade, and an uninstall, by that and nothing else.
- **The VSCodium release**: `build.sh --vscodium-version <tag> --record`, then restore the comments `--record`
  strips from `vscodium.json`.

## Commit

`pre-commit` (`dev-tools/pre-commit-config.yaml`) runs `shellcheck` on `build.sh` and `install.sh`. The Python
here is formatted with `black` like the rest of the repository (line length 120).
