# ide/standalone

Builds the **PartCAD IDE**: a [VSCodium](https://vscodium.com/) build, rebranded, with the extensions from
`../.vscode/extensions.json` installed and the standalone command line tools inside it. Shell (`build.sh`) plus
Python helpers in `./tools`, no package to install. `README.md` explains what each step does and why; this file
is the commands.

Nothing here is imported by `partcad`, and it produces no wheel. It downloads a published VSCodium release and
edits it; it does not build an editor from source.

## Build

From the repository root:

```bash
ide/standalone/build.sh --with-cli-bundle dist/standalone/partcad   # the whole thing
ide/standalone/build.sh --no-extensions --no-archive                # fast, for branding work
ide/standalone/build.sh --help
```

`--with-cli-bundle` takes what `dev-tools/pyinstaller/build.sh --no-archive` leaves in `dist/standalone/partcad`.
Node.js is needed unless `--vsix` points at an already-built PartCAD extension: the extension is built here
the same way it is built everywhere else, with `npm ci && npm run vsce-package` (see "Build / package" in
`../vscode/AGENTS.md`), and the other extensions are packaged with `vsce`. `cairosvg`, `Pillow`, `rcedit` and
-- on Windows -- Inno Setup 6.3+ (`ISCC.exe`, for `installer/partcad-ide.iss`) are optional, and the build
reports what it skipped without them. Output lands in `dist/ide/`.

## Software WebGL is on

The build writes `resources/app/out/partcad-main.js` and points `package.json`'s `main` at it. All it does is
`app.commandLine.appendSwitch('enable-unsafe-swiftshader')` and then `await import('./main.js')`.

The PartCAD Viewer renders with WebGL, and since Chromium M136 a machine whose GPU process fails to start gets
no WebGL at all rather than a software one -- `code --status` says `webgl: disabled_off`. That is not exotic: a
confined package that cannot see the driver, an NVIDIA setup, a VM, a remote display. The IDE is the download
for people who have no editor set up, so "the 3D view is blank and the fix is a Chromium switch" is not a
position to leave them in. The switch only *permits* the software fallback; a machine with a working GPU still
uses it, and pays nothing.

Three things about how it is done:

- **An entry point, not a launcher flag.** No launcher covers every start: the Linux desktop entry
  `install.sh` writes runs the binary directly rather than `bin/partcad-ide`, and a macOS bundle opened from
  Finder is passed no arguments at all. `package.json`'s `main` is the one path all of them go through.
- **A dynamic `import`, because the application is `"type": "module"`.** A static import is hoisted above the
  statement it has to follow, so `main.js` would run *before* the switch was set and the whole thing would be
  silently inert.
- **Neither file is checksummed.** `product.json`'s `checksums` covers `vs/**` (the workbench, the preload, the
  extension host), so this does not trip the "installation appears corrupt" warning. `out/main.js` is left
  alone.

`tools/verify_bundle.py` fails the build if the wrapper is missing, if `main` does not point at it, or if it
does not contain the switch -- each of which leaves an IDE that either has no software WebGL or does not start.

## Test

```bash
python -m pytest ide/standalone/tests -o addopts=              # the build tooling
node --test ide/standalone/bootstrap/test/*.test.js           # the IDE bootstrap extension
```

`-o addopts=` because the repository-wide `pyproject.toml` options pull in coverage and reporting plugins these
tests have no use for. They are not part of the `pytest tests` run or of the `pre-commit` hook;
`.github/workflows/build-ide-standalone.yml` runs them, before it spends an hour building.

The bootstrap tests need nothing installed -- `node --test` is in Node, and `test/vscode-stub.js` is as much of
the `vscode` module as the extension touches. They cover the first start (the package it creates, the workspace
it opens, the welcome window that follows the window reopening), which is otherwise only visible in a built and
installed IDE. Pass the files rather than the directory: `node --test <dir>` is not the same thing in every
Node release.

There is no unit test for `build.sh` itself. What checks it is `tools/verify_bundle.py`, which the build runs on
its own result, and the `install` job in that workflow, which installs the archive and runs what comes out.

## Change what ships

- **An extension**: add it to `../.vscode/extensions.json`. Only touch `extensions.json` here when it cannot be
  installed from Open VSX or cannot be redistributed, and say which in the `reason`.
- **Branding, or a default setting**: `product.overlay.json`. A `null` removes a key; `${VERSION}` is the
  PartCAD version.
- **What the IDE does on startup**: `bootstrap/extension.js` -- including the package it creates in
  `~/.partcad/projects/start` and opens as the first workspace. It is plain JavaScript, packaged as it is --
  no compile step, so keep it that way.
- **The welcome window**: the walkthrough in `bootstrap/package.json`, with the text of its steps in
  `bootstrap/media/`. Every step links to the page of `partcad.readthedocs.io` that explains it, and the test
  below fails on a link to a page that is not in `docs/source`.
- **Which examples it offers**: `bootstrap/examples.json`. The packages themselves stay in `examples/` --
  `tools/copy_examples.py` copies the ones it names, and whatever they reference, into the extension at build
  time, and fails the build when the two disagree. `tests/test_bootstrap.py` checks that its buttons run commands that exist and that its
  steps point at files that are there; moving the starter package means moving it in the install jobs of
  `.github/workflows/build-ide-standalone.yml` and in `docs/source/installation.rst` too, which that test
  also enforces.
- **What the Windows installer sets up**: `installer/partcad-ide.iss`. Never change its `AppId`: Windows
  recognizes an upgrade, and an uninstall, by that and nothing else.
- **The VSCodium release**: `build.sh --vscodium-version <tag> --record`, then restore the comments `--record`
  strips from `vscodium.json`.

## Commit

`pre-commit` (`dev-tools/pre-commit-config.yaml`) runs `shellcheck` on `build.sh` and `install.sh`. The Python
here is formatted with `black` like the rest of the repository (line length 120).
