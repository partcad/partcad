# Standalone PartCAD bundles

The Python wheels on PyPI assume the user has Python, knows which Python, and is willing to keep an environment
alive for it. This directory builds the alternative: a self-contained bundle, produced by
[PyInstaller](https://pyinstaller.org/), that carries its own interpreter and every dependency. Users install it
with [`install.sh`](../../install.sh) and never see Python.

| | wheels | standalone bundle |
| --- | --- | --- |
| Install | `pip install -U partcad-cli` | `curl -fsSL .../install.sh \| sh` |
| Needs Python | yes, 3.10-3.12 | no |
| Size | ~15MB plus whatever pip resolves | ~800MB unpacked, ~230MB compressed |
| Optional extras (`ai`, `lint`) | installed on demand | always included |
| Importable as a library | yes | no, it is only the CLI |

## Files

- `partcad.spec` - the PyInstaller spec. It is the interesting file: it lists what PyInstaller cannot find on
  its own, and says why for each entry.
- `entrypoint.py` - what the frozen executables run, in place of the console scripts a wheel would generate.
- `build.sh` - prepares the environment, freezes, smoke tests, and packs the archive.

## Building

From the repository root, inside the [dev container](../../docs/source/contributing.rst):

```bash
dev-tools/pyinstaller/build.sh
```

That installs the build dependencies into the active environment (including PartCAD itself, from this
checkout), so use a throwaway virtualenv rather than the project one:

```bash
python -m venv /tmp/pyi-venv
PYTHON=/tmp/pyi-venv/bin/python dev-tools/pyinstaller/build.sh
```

Pass `--no-install` to skip the dependency step when the environment is already prepared, and `--no-archive` to
stop after the bundle and skip packing it.

The results land in `dist/standalone/`: the `partcad/` bundle, an archive named
`partcad-<version>-<os>-<arch>.tar.gz` (`.zip` on Windows), and its `.sha256`. The archive name is a contract
with `install.sh`, which derives the same name from `uname`.

The bundle embeds the interpreter it was built with, so `PYTHON` decides the Python version users end up
running. CI builds with 3.11, and 3.11 or 3.12 is required: PartCAD itself still supports 3.10, but
`ocp_vscode` (what `pc inspect` hands shapes to) does not import there, and a dependency that cannot be
imported cannot be frozen. `build.sh` checks that before it builds and says which import failed.

## What the frozen bundle changes, and what it does not

Freezing replaces the *installation*, not the architecture. PartCAD still runs CAD scripts (CadQuery,
build123d, OpenSCAD) in a separate Python interpreter that it provisions itself with conda, and still clones
package repositories with `git`. Both remain external prerequisites of the standalone bundle, exactly as they
are for the wheels. `pc healthcheck` reports what is missing.

That sandbox is also why `partcad/wrappers/*.py` are bundled as *data* rather than frozen as modules: they are
handed to that other interpreter as a file path.

## Adding a dependency

A frozen bundle only contains what PyInstaller could prove is reachable. Anything imported by name at runtime
is invisible to it and has to be named in `partcad.spec`. When adding to PartCAD:

- an import written normally - nothing to do;
- an `importlib.import_module(...)` call, an optional extra, or a plugin discovered by entry point - add it to
  `partcad.spec` and say why;
- a non-Python file read at runtime - add it to `datas` in `partcad.spec`, and remember `__file__` inside a
  bundle points into the unpacked bundle directory, not into a `site-packages`;
- a new CLI subcommand - nothing to do, `command_modules()` in the spec enumerates the `commands` tree.

A missing entry does not fail the build. It fails at runtime, on the one code path that needed it, for users
only. The `Standalone` workflow (`.github/workflows/build-standalone.yml`) builds every platform and then
installs and runs the result, which is what catches this; run it with `workflow_dispatch` when in doubt.

## Releasing

`deploy.yml` calls the `Standalone` workflow on a push to `main` and uploads the archives to the same GitHub
release as the wheels. `install.sh` downloads from there by default.
