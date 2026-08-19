# Standalone PartCAD bundles

The Python wheels on PyPI assume the user has Python, knows which Python, and is willing to keep an environment
alive for it. This directory builds the alternative: a self-contained bundle, produced by
[PyInstaller](https://pyinstaller.org/), that carries its own interpreter and every dependency. Users install it
with [`install.sh`](../../install.sh) and never see Python.

| | wheels | standalone bundle |
| --- | --- | --- |
| Install | `pip install -U partcad-cli` | `curl -fsSL .../install.sh \| sh` |
| Needs Python | yes, 3.10-3.14 | no |
| Size | ~15MB plus whatever pip resolves | ~875MB unpacked, ~290MB compressed (Linux, OpenSCAD included) |
| Optional extras (`ai`, `lint`) | installed on demand | always included |
| Importable as a library | yes | no, it is only the CLI |

## One build per OS version

A wheel is portable because Python is. A frozen bundle is not: it links against the C library and the system
frameworks of the machine that froze it, so it runs there and on anything newer, and on nothing older. A single
"linux" bundle would therefore quietly mean "whatever Linux the builder happened to be running", and would stop
starting for users the day that image moved.

So there is one build per supported OS version, and the archive name carries it. The platform id is
`<os>-<os-version>-<arch>`, which for the builds CI produces is exactly the runner image label (minus any `-arm`
suffix) plus the architecture:

| | x86_64 | arm64 |
| --- | --- | --- |
| Linux | `ubuntu-22.04-x86_64`, `ubuntu-24.04-x86_64` | `ubuntu-22.04-arm64`, `ubuntu-24.04-arm64` |
| macOS | — (needs macos-13, see below) | `macos-15-arm64`, `macos-26-arm64` |
| Windows | `windows-2022-x86_64`, `windows-2025-x86_64` | — |

The Ubuntu names say what built the bundle, not what is required to run it: any distribution can run these, and
what differs between the two is the minimum glibc. `install.sh` offers a machine it cannot identify as Ubuntu
the 22.04 build, which has the lower floor.

Three lists have to agree, and nothing enforces it: the matrix in `.github/workflows/build-standalone.yml`,
`LINUX_BUILDS`/`MACOS_BUILDS` in `install.sh`, and the platform loop in the release check in
`deploy.yml`. A name in the matrix that the installer never asks for is dead weight; one the installer asks for
that the matrix does not build is a failed install. Each of the three says so at the point where it is defined.

`build.sh` detects the platform id from the machine when it is not told one, which is what a local build wants.
CI passes `--platform=` instead: the runner image label is the authoritative answer to which OS version it is,
and recovering that from the running system is guesswork on Windows in particular.

There is no macOS x86_64 bundle: it would need macos-13, and no macos-13 job has ever started on the current
runner plan (see the note in `test.yml`). There is no Windows arm64 bundle either -- not a platform PartCAD
releases for.

## Files

- `partcad.spec` - the PyInstaller spec. It is the interesting file: it lists what PyInstaller cannot find on
  its own, and says why for each entry.
- `entrypoint.py` - what the frozen executables run, in place of the console scripts a wheel would generate.
- `build.sh` - prepares the environment, freezes, smoke tests, and packs the archive.

The bundle contains three console executables that share one interpreter, `PYZ`, and set of libraries/data:
`pc` and `partcad` (the CLI) and `partcad-json-rpc` (the JSON-RPC service the VS Code extension launches by
default). All three run `entrypoint.py`, which dispatches on `sys.argv[0]`: `partcad-json-rpc` starts the
service, anything else runs the CLI. A third executable adds only a small bootloader stub, not another copy of
the ~290MB payload.

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

On an Apple silicon Mac, build from a **non-conda** interpreter. PartCAD needs conda for the CAD sandbox, so a
conda `python3` is usually first on `PATH` — and freezing from one produces a bundle that segfaults. `pygit2`
reads the libgit2 config search path through a variadic C call, which cffi dispatches at run time through
`_cffi_backend`; the conda-forge cffi 2.x build mis-marshals variadic arguments on Apple arm64 (the PyPI wheel,
linked against Apple's system libffi, does not). Nothing catches it downstream: the crashing path only runs
when a clone fails to authenticate and PartCAD retries it with the ambient git config ignored, so the bundle
passes every check and then crashes for users. `build.sh` refuses to freeze a `_cffi_backend` that is not the
PyPI build; if it does, either build from a plain `python.org`/`pyenv` interpreter or force the wheel in:

```bash
python -m pip install --upgrade --force-reinstall --no-deps --only-binary=:all: cffi
```

CI is not exposed to this — `build-standalone.yml` provisions Python with `actions/setup-python`, which has no
conda anywhere near it. The same crash in the *wheel*-based CI jobs, whose runners do use conda, is handled
separately in `.github/actions/setup-all/action.yml`.

The results land in `dist/standalone/`: the `partcad/` bundle, an archive named
`partcad-<version>-<platform>.tar.gz` (`.zip` on Windows), and its `.sha256`. The archive name is a contract
with `install.sh`, which resolves the machine it runs on to one of the same platform ids. Pass
`--platform=<id>` to name the archive explicitly rather than after this machine.

The bundle embeds the interpreter it was built with, so `PYTHON` decides the Python version users end up
running. CI builds with 3.14, the newest version PartCAD supports (`requires-python = ">=3.10,<3.15"`) and
deliberately ahead of the 3.13 the wheels publish from: a standalone user cannot change the interpreter after
the fact the way someone installing the wheels can, so shipping the oldest supported one would leave them on it
for the life of the bundle. Nothing older is exercised. `ocp_vscode` (what `pc inspect` hands shapes to) long
required 3.11 or newer, which is why the floor used to be documented as 3.11; it and its dependencies now all
declare `>=3.10`, but only the version CI builds with is tested. A dependency that cannot be imported cannot be
frozen, so `build.sh` imports them all before it builds and says which import failed.

## What the frozen bundle changes, and what it does not

Freezing replaces the *installation*, not the architecture. PartCAD still runs CAD scripts (CadQuery,
build123d, OpenSCAD) in a separate Python interpreter that it provisions itself with conda, and still clones
package repositories with `git`. Both remain external prerequisites of the standalone bundle, exactly as they
are for the wheels. `pc healthcheck` reports what is missing.

## OpenSCAD

The Linux and Windows bundles carry OpenSCAD, pinned to the version in `build.sh` and downloaded from
`files.openscad.org` at build time (checksum-verified). `partcad.healthcheck.openscad.find_executable()` prefers it over
any OpenSCAD on the host, and falls back to `shutil.which` when there is no bundled copy — which is what the
wheels always do. A user can opt out of the bundled copy with `--ignore-bundled-openscad` /
`IGNORE_BUNDLED_OPENSCAD=1` (`user_config.ignore_bundled_openscad`), which makes the resolver skip the
payload and use the host's OpenSCAD — handy when the pinned version is too old, or on a minimal Linux host
where the AppImage's library dependencies are absent.

| | what ships | self-contained |
| --- | --- | --- |
| Linux x86_64 | the AppImage, unpacked | no — needs `libGL`, `libX11`, `libxcb`, fontconfig, freetype, glib, harfbuzz from the host |
| Linux arm64 | nothing | — |
| Windows | the portable build | yes — one statically linked `openscad.exe`, no DLLs |
| macOS | nothing | — |

Linux arm64 carries nothing because upstream publishes the pinned 2021.01 AppImage for x86_64 only; running it
under emulation is not something a bundle should quietly require. `pc` there uses the host's OpenSCAD, exactly
as the wheels do.

The AppImage ships *unpacked* because running it as an image needs FUSE, which a minimal host may not have.

It is **not** declared in `partcad.spec`: `build.sh` copies it into the bundle after PyInstaller has run.
Declaring it in `datas` does not keep PyInstaller's hands off it — shared libraries found among data files
are reclassified as binaries and collected into the top level of the bundle, which puts OpenSCAD's Qt, ICU
and glib beside the ones Python needs, on the frozen application's own library search path, and duplicates
~100MB. That means a bare `pyinstaller partcad.spec` produces a bundle without OpenSCAD; `build.sh` is the
supported way to build one, as it already is for the dependency pre-flight.

macOS is excluded because the 2021.01 release predates Apple silicon and ships an x86_64-only `.dmg`, which
on the arm64 bundle would require Rosetta 2 — absent from a clean machine. Development snapshots may be
universal binaries, but they are snapshots and their architecture has not been confirmed; `lipo -archs` on a
mounted snapshot `.dmg` would settle it.

To move to a different OpenSCAD, change `OPENSCAD_VERSION` in `build.sh`. Upstream publishes a `.sha256` next
to each artifact and the build verifies it, so nothing else needs updating — but note the published checksum
files name a `releases/` path rather than the bare file, which is why the build compares the hash alone.

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

## The snap

On Linux the `ubuntu-24.04` bundles are also wrapped as snaps, one per architecture. It is packaging only --
the snap carries the bundle unchanged, and adds nothing to freeze -- so nothing in this directory has to change
when it is built. The snaps are not published anywhere yet. See [`../snap/README.md`](../snap/README.md).

## Releasing

`deploy.yml` calls the `Standalone` workflow on a push to `main` and uploads every archive to the same GitHub
release as the wheels; the release is refused if any platform is missing. `install.sh` downloads from there by
default. The snaps are not part of the release: the `snap` job does not even run on that path.
