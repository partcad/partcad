# Standalone PartCAD bundles

The Python wheels on PyPI assume the user has Python, knows which Python, and is willing to keep an environment
alive for it. This directory builds the alternative: a self-contained bundle, produced by
[PyInstaller](https://pyinstaller.org/), that carries its own interpreter and every dependency. Users install it
with [`install.sh`](../../install.sh) and never see Python.

| | wheels | standalone bundle |
| --- | --- | --- |
| Install | `pip install -U partcad` | `curl -fsSL .../install.sh \| sh` |
| Upgrade | `pc upgrade` (runs `pip`) | `pc upgrade` (fetches the release archive) |
| Needs Python | yes, 3.10-3.14 | no |
| Size | ~15MB plus whatever pip resolves | ~180MB unpacked, ~57MB compressed (Linux x86_64, OpenSCAD included) |
| Optional extras (`lint`, `memcache`, `aws`) | installed on demand | always included |
| Importable as a library | yes | no, it is only the CLI |
| CAD kernel | not a dependency either way — every shape is built in a conda sandbox | same, see `EXCLUDES` in the spec |

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
| Windows | `windows-2022-x86_64` | — |

The Ubuntu names say what built the bundle, not what is required to run it: any distribution can run these, and
what differs between the two is the minimum glibc. `install.sh` offers a machine it cannot identify as Ubuntu
the 22.04 build, which has the lower floor.

**Windows is one build, on purpose.** The per-OS-version split earns its keep only where a machine can be lined
up against it — an Ubuntu version from `/etc/os-release`, a macOS major version from `sw_vers`. Windows offers
no such comparison: `windows-2022`/`windows-2025` are runner image names, and the only route back to one of
them is the NT build number table in `build.sh`, which knows those two server builds and no version of Windows
anybody runs. So a second Windows build is one no client could ask for on purpose — redundant if it is equally
portable, unreachable if it is not — and Windows has no glibc-style floor for the two to differ in anyway: the
CRT the bundle needs ships either inside it or with the OS. The one build published is the older image's, which
is also the one the IDE embeds. Two would need the host-to-build mapping to exist first.

Two lists have to agree, and nothing enforces it: `PLATFORMS_CORE` plus `PLATFORMS_DEEP` in
`.github/workflows/build-standalone.yml`, and the platform loop in the release check in `deploy.yml`. A name in the
matrix that no release check expects is dead weight; one the check expects that the matrix does not build is a refused
release. Each says so at the point where it is defined. The clients keep no list of their own — they read the manifest
described below.

The split between `PLATFORMS_CORE` and `PLATFORMS_DEEP` is about cost, not support: a pull request builds the four core
platforms, and the three in `PLATFORMS_DEEP` (Ubuntu 22.04 on both architectures, and the second macOS) are added on a
deep run — the nightly schedule, a manual dispatch, a push, or `#deepTest` in the pull request. See
`.github/actions/test-depth`. A release runs on a push, so it is always deep and always builds all seven; `deploy.yml`
refuses to publish otherwise. Put `#deepTest` on a pull request that changes what is frozen.

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
service, anything else runs the CLI.

They are not three separate payloads. Since PyInstaller 6 an `EXE` carries the whole `PYZ`, so what it emits is
three byte-identical files -- ~14MB each -- rather than the bootloader stubs the one-directory layout suggests,
and a stream compressor cannot see across files that far apart, so the duplication costs as much again in the
archive. `build.sh` therefore keeps `pc` and replaces the other two with relative symlinks to it, right after
the freeze and before the smoke test that runs all three. `sys.argv[0]` is the name the user typed, so the
dispatch is unaffected, and the bootloader looks for `_internal` beside the resolved executable, which is the
same directory either way.

Windows keeps three real copies: its archive is a zip, which stores a symlink as a copy of its target anyway,
and creating one there needs a privilege a runner does not have. Every unpacker has to preserve the links --
`tarfile`'s `data` filter allows a relative link that stays inside the archive, and the two hand-rolled member
policies (`selfupdate._reject_unsafe_links`, the addon's `_safe_members`) enforce the same rule. The addon's
used to drop links outright, which was fine until `partcad-json-rpc`, the file it launches, became one.

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
`partcad-<version>-<platform>.tar.xz` (`.zip` on Windows), and its `.sha256`, where `<platform>` is the
`<os>-<os-version>-<arch>` id above. Pass `--platform=<id>` to name the archive explicitly rather than after
this machine. The archive name is a contract with four consumers: `install.sh`, `partcad_client.selfupdate`
(which is what `pc upgrade` and the VS Code extension use to update a bundle in place), the extension's own
first-time download (`src/common/provision.ts`), and the FreeCAD addon
(`cad/freecad/partcad_freecad/provision.py`). So is the archive's single top-level `partcad/`
directory: all of them unpack it and rename that directory to `<install-dir>/<version>/`, which is what lets a
new bundle be installed beside a running one instead of over it.

**Which build to download is not a property of the host.** A machine cannot know which OS versions a given
release was built for, so a release publishes a manifest saying so: `platforms.json`, generated from the
archives themselves by `dev-tools/release/platforms-manifest.sh` and uploaded by `deploy.yml` beside them.

```json
{
  "version": "0.7.177",
  "bundle": { "linux": { "x86_64": ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"] } },
  "ide": { "linux": { "x86_64": ["linux-x86_64"] } }
}
```

### The archive format

The command line bundle is packed with **xz**, not gzip. It is native code and an unpacked OpenSCAD, neither of
which gzip does well on: measured on a Linux x86_64 build, `xz -6` takes the download from 78MB to 57MB, for a
few seconds more on the builder (`-T0`, so it uses every core) and for the user unpacking it. `-9` is within a
couple of percent of `-6` here and costs far more memory per thread, so `-6`, xz's default, is what `build.sh`
passes.

Windows stays a `.zip`: it is what a machine with no `tar` can open, and the portable OpenSCAD inside it is
already compressed. The **IDE** stays a `.tar.gz` -- it is mostly an Electron runtime, which xz barely improves
on, and `ide/standalone/build.sh` packs it rather than this one. `install.sh` is the one place that
downloads both, and it picks the extension per artifact.

Nothing has to agree on the *format*: every unpacker reads the compression out of the archive (`tar -xf`,
`tarfile.open(..., "r:*")`). What has to agree is the file *name*, which is the same four-place contract the
platform id already lives in: `install.sh`, `partcad_client.selfupdate.archive_extension()`,
`provision.ts`'s `hostPlatform()`, and the addon's `provision.archive_extension()`. `dev-tools/release/platforms-manifest.sh`
scans for both tar flavours, because it is pointed at bundle and IDE directories alike.

One thing xz asks of the host that gzip does not: GNU tar runs `xz` as a helper program, so a very small Linux
system needs `xz-utils` installed. `install.sh` says so by name when the unpacking fails. bsdtar, which is what
macOS has, decompresses in-process and needs nothing.

Both artifact kinds are in it because they are named differently: the command line bundle carries the OS
version it was frozen on, the IDE does not (it ships its own Electron runtime and is built once per operating
system and architecture). Each list is ordered newest build first, and it is an inventory rather than an
answer: a client still drops the builds newer than the machine it runs on, and one that cannot identify its
host release walks the list backwards, oldest and most portable first. That policy is `select_platforms()` in
`partcad_client.selfupdate` and in the addon's `provision.py`, and `selectPlatforms()` in `provision.ts` --
three copies, because the addon cannot import PartCAD (its whole reason for using the frozen bundle) and the
extension is TypeScript. `install.sh` is the fourth and the reference implementation: it reads the same
manifest with `awk`, and applies the same policy from `uname`, `/etc/os-release` and `sw_vers`.

The bundle embeds the interpreter it was built with, so `PYTHON` decides the Python version users end up
running. CI builds with 3.14, the newest version PartCAD supports (`requires-python = ">=3.10,<3.15"`) and
deliberately ahead of the 3.13 the wheels publish from: a standalone user cannot change the interpreter after
the fact the way someone installing the wheels can, so shipping the oldest supported one would leave them on it
for the life of the bundle. Nothing older is exercised. The floor used to be documented as 3.11 because
`ocp_vscode` (what `pc inspect` used to hand shapes to) required it; `pc inspect` now talks to the PartCAD IDE
over a socket instead, and `partcad_ide_client` is bundled (it ships inside the `partcad` wheel itself) and is
pure standard library, so it adds no version floor of its own. A dependency that cannot be imported cannot be
frozen, so `build.sh` imports them all before it builds and says which import failed.

## What the frozen bundle changes, and what it does not

Freezing replaces the *installation*, not the architecture. PartCAD still runs CAD scripts (CadQuery,
build123d, OpenSCAD) in a separate Python interpreter that it provisions itself with conda, and still clones
package repositories with `git`. Both remain external prerequisites of the standalone bundle, exactly as they
are for the wheels. `pc healthcheck` reports what is missing.

## No CAD kernel

The bundle used to freeze one in: `cadquery-ocp`, `build123d` and `ocpsvg`, pinned to the sandbox versions.
That is gone, and it is the single biggest reason the bundle is what it now weighs -- a Linux x86_64 build went
from 1010MB unpacked to 78MB before OpenSCAD is copied in beside it.

It was carried for one caller. `Shape.convert("build123d"/"cadquery")` hands back a live object, which needs the
library in this process -- and that is a *library* API. This bundle is three console programs; it is not
importable, so nothing can call it. The paths the programs do reach never hold a live shape:

- Everything that builds, renders, exports, converts or tessellates a shape runs in the conda sandbox and comes
  back as a BREP-byte envelope the core carries without opening (`partcad.shape_envelope`, and the note at the
  top of `requirements.txt`).
- `Shape._to_envelope()` is the one place that would encode a live shape a factory built in-process, and no
  factory builds one: not a single module under `partcad/` outside `wrappers/` and `builtin/` imports a CAD
  library, and both of those directories run in the sandbox.
- `partcad.geom` builds an OCCT transform on demand. `_from_ocp()` reads the `ImportError` as "this is not an
  OCP object", which is the right answer in a process that has no OCP, and nothing calls the other two.

So `pc` from a bundle needs conda for CAD exactly as `pc` from a wheel does, exactly as it did before -- the
kernel it carried never ran. What it cost: OCP is ~250MB of extension module and OpenCASCADE libraries,
`build123d` pulls scipy, sympy, scikit-learn, numpy, IPython and ezdxf in at *import* time, and the VTK-enabled
`cadquery-ocp` the bundle pinned pulls VTK (another ~336MB) on top.

`EXCLUDES` in `partcad.spec` names all of it rather than relying on `build.sh` not installing it, so that a
bundle frozen from a developer's virtualenv -- which may well have build123d in it for other reasons -- is the
same bundle CI produces.

One thing to know if you are adding to this: the CAD stack was also, by accident, what dragged `cffi` into the
bundle. `pygit2` needs `_cffi_backend`, loads it from C, and names it nowhere PyInstaller can see; removing the
kernel removed the accident and broke every `pc` command that touches git. It is a hidden import now, and a
`build.sh` pre-flight entry. Expect more of that shape from anything else that leaves.

## What else is excluded, and why the list exists

`EXCLUDES` in `partcad.spec` is not only about the CAD kernel. The rest of it falls into four groups, and every
entry is there because *nothing the three console programs can reach imports it*:

- **The AI provider SDKs.** PartCAD used to generate parts with an LLM and the bundle carried `openai`,
  `ollama` and `google-genai` for it, because a frozen bundle cannot be extended with pip. PartCAD no longer
  drives a model -- it gives one tools to work with instead, as the Agent Skills in `ai-agents/` -- so the
  feature, the `ai` extra, the `ai-*` part types and the dependencies themselves are gone. The excludes stay as
  a floor: nothing has to be declared to arrive, and `googleapiclient` in particular ships a cached REST
  discovery document for every Google API, ~100MB of JSON, that PyInstaller's hook collects wholesale.
- **Packaging machinery** — `setuptools`, `pkg_resources`, `distutils`, `wheel`. Nothing in PartCAD imports
  them; the two dependencies that reach for `pkg_resources` (`sentry_sdk.utils`, `wrapt.importer`) both do it
  inside `try: ... except ImportError`. Keeping `pkg_resources` out is also what let the `setuptools<82` bound
  go from `build.sh`: PyInstaller adds the `pyi_rth_pkgres` runtime hook only when `pkg_resources` is in the
  graph, and that hook was the only reason for the pin.
- **Optional dependencies of dependencies** — `cryptography`/`OpenSSL` (`requests` and
  `urllib3.contrib.pyopenssl` reach for them, 11MB), `httpx`/`httpcore` (`aiobotocore` has an httpx backend
  beside its aiohttp one), `pydantic`/`pydantic_core` (4.5MB). Each is behind a `try: import` or a `find_spec`
  check, so their absence is a state the code already handles.
- **Test suites and interactive-only data** — `jsonschema.tests` and `aiohttp.test_utils`, which
  `collect_all`/`collect_submodules` sweep in whole and which are what drag `unittest` into a bundle that runs
  no tests; and `pydoc_data`, the help-topic database only `help()` reads.

Plus `sitecustomize`/`usercustomize`, which belong to the build *machine* rather than to PartCAD.

### The bundle should not depend on what the builder has installed

That is what the list is really for, and it is worth stating as a property to preserve: **freezing from a
virtualenv that has extra packages in it must produce the same bundle CI produces.** It is easy to lose. Three
mechanisms were quietly breaking it before these entries existed:

1. A hook collects a package because it is *installed*, not because it is reachable — `googleapiclient` is the
   ~100MB case.
2. A dependency has an optional backend guarded at run time but imported unconditionally in the source, so
   PyInstaller's static analysis follows it whenever it resolves — `aiobotocore` → `httpx`, `requests` →
   `cryptography`.
3. `collect_submodules` on a package whose submodules each import a third-party library. `sentry_sdk` ships an
   integration module for roughly forty frameworks; collecting them all made the bundle carry whatever subset
   of those frameworks the builder had. `telemetry_sentry.py` calls `sentry_sdk.init(default_integrations=False,
   ...)` with a single integration, so the spec collects `sentry_sdk` *except* `sentry_sdk.integrations.*` and
   names the two that are actually used.

The check is cheap: install something unrelated into the build virtualenv, freeze, and diff the bundle against
one frozen without it. With the AI SDKs, `cryptography`, `pydantic`, `httpx` and setuptools 8x installed, the
two are identical today.

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
- a new CLI subcommand - nothing to do, `command_modules()` in the spec enumerates the `commands` tree;
- a compiled extension that loads another module from C rather than importing it in Python - name it in
  `hiddenimports` *and* in `build.sh`'s pre-flight. `_cffi_backend`, which `pygit2` needs, is the worked
  example: nothing in the import graph mentions it, so nothing but a runtime failure reveals it missing.

And one in the other direction: a dependency that only the *sandbox* needs does not belong in the bundle at
all. That is what `EXCLUDES` is for, and the CAD kernel is the case that matters -- see [No CAD
kernel](#no-cad-kernel).

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
