# The PartCAD snap

A third way to install the PartCAD command line tools, next to the [wheels on PyPI](../../docs/source/installation.rst)
and the [standalone bundle](../pyinstaller/README.md). It is not a third *build* — the snap wraps the very same
PyInstaller bundle the standalone archives ship, so there is one frozen artifact and one answer to the question of what
was released.

**Not published yet.** CI builds these snaps and uploads them as workflow artifacts; nothing puts them on the Snap
Store or on a GitHub release, so `snap install partcad` does not work today. Publishing needs store credentials and,
because the snap is classic, a manual store review — see [Publishing](#publishing) for the step that is missing.

| | wheels | standalone bundle | snap |
| --- | --- | --- | --- |
| Install | `pip install -U partcad` | `curl -fsSL .../install.sh \| sh` | `snap install --classic partcad`, once published |
| Needs Python | yes, 3.10-3.14 | no | no |
| Platforms | Linux, macOS, Windows | one build per supported OS version | linux amd64 and arm64 |
| Sees the host's conda/git | yes | yes | no, see below |
| Upgrades | `pip install -U` | re-run `install.sh` | automatic, by snapd |
| Root to install | no | no | yes |

## Files

- `../../.snapcraft.yaml` — the recipe. It has to sit at the repository root. The directory `snapcraft` runs in is
  the project directory: it is what gets copied into the build environment and what `source:` resolves against, and
  snapcraft looks for the recipe only at four paths within it — the root itself (as `snapcraft.yaml` or
  `.snapcraft.yaml`), `snap/`, or `build-aux/snap/`. Keeping it here instead would mean running snapcraft from
  `dev-tools/`, which would leave `dist/standalone/partcad` outside the project directory. Of the root-level
  spellings, the dotfile is the one that leaves no directory behind.
- `build.sh` — makes sure the bundle exists, checks it, and drives `snapcraft`.

## One base, two architectures

The standalone bundles fan out over OS versions because a frozen bundle only runs on the OS version that built it
and newer. The snap does not need that axis: a `core24` snap carries its own Ubuntu 24.04 runtime onto whatever
distribution the user has, so one base covers every Linux. What it does fan out over is the architecture, because
the payload is a native frozen bundle — `amd64` and `arm64`, each packed on a runner of that architecture from the
matching `ubuntu-24.04` bundle. There is no cross-building.

The build *host* still has to be the base's release, which is why the CI job is pinned to the `ubuntu-24.04` images
rather than `ubuntu-latest`.

## Building

From the repository root, on Ubuntu 24.04 (the release matching the snap's `core24` base):

```bash
sudo snap install snapcraft --classic
dev-tools/snap/build.sh
```

That builds the standalone bundle first if `dist/standalone/partcad` is not already there, which takes a while and
pulls in the CAD dependencies — see [the standalone README](../pyinstaller/README.md). Pass `--no-bundle` when the
bundle is already in place; that is what CI does, after unpacking the archive its `build` job produced.

`snapcraft` runs in **destructive mode** by default: it builds directly on the machine, which is fast and needs no
container, and which is why the host has to be the same Ubuntu release as the base. On any other distribution, or to
keep the build off the host, use LXD instead:

```bash
dev-tools/snap/build.sh --use-lxd
```

The result lands in `dist/snap/`: `partcad_<version>_<arch>.snap` and its `.sha256`, for the architecture of the
machine you built on. Install it locally with

```bash
sudo snap install --dangerous --classic dist/snap/partcad_<version>_<arch>.snap
sudo snap alias partcad.pc pc
```

`--dangerous` because a locally built snap is unsigned; `--classic` because of the confinement, below.

## Commands

The snap declares three apps, one per executable in the bundle:

| app | command after `snap install` | what it is |
| --- | --- | --- |
| `partcad` | `partcad` | the CLI |
| `pc` | `partcad.pc` | the same CLI under the name people actually type |
| `json-rpc` | `partcad.json-rpc` | the JSON-RPC service the VS Code extension launches |

Only the app whose name matches the snap gets the bare name; the rest are namespaced. `snap alias partcad.pc pc` fixes
that locally, and an automatic alias for `pc` is something the Snap Store has to grant.

## Confinement

The snap is **classic**, and there is no strict-confinement version of it to fall back to. PartCAD is a developer tool
that works on the user's own files: it reads and writes CAD projects anywhere on disk, clones git repositories,
provisions conda sandboxes and runs CAD scripts in them, and serves a daemon over a socket that the VS Code extension
connects to. Strict confinement would cut all of that off at the snap's own directories.

What it does not buy back is the host's `conda` and `git` — see the section on those below. Classic confinement is
about reaching the user's *files*, not about inheriting the user's shell.

The price is a manual review before the Snap Store will publish it, which is one of the two reasons nothing is
published yet. A locally built or CI-built `.snap` installs with `--dangerous --classic` in the meantime.

For the same reason, snapcraft's `classic` and `library` linters are switched off in `.snapcraft.yaml`, and its
`enable-patchelf` build attribute is deliberately left unset: PyInstaller's shared libraries find each other through
`$ORIGIN` and the bundle's own bootloader, so rewriting their rpaths would break the bundle rather than fix it. The
comments in `.snapcraft.yaml` say the same at the point where it matters.

## Where it keeps its state

PartCAD normally keeps its cache, its conda sandboxes and its git/tar clones in `~/.partcad`. A packaged application
has no business writing there, so `.snapcraft.yaml` sets `PC_INTERNAL_STATE_DIR` to `$SNAP_USER_COMMON` —
`~/snap/partcad/common`, which snapd creates before the app starts. It survives refreshes (unlike `$SNAP_USER_DATA`,
which is keyed by revision), and `snap remove --purge` takes it away with the snap.

The CI job checks this from both ends, because nothing about `pc version` succeeding would show that the variable took
effect, and snapd creates `~/snap/partcad/common` for every snap it runs whether the app uses it or not: it asserts
that snapd exports the variable, and that none of `cache`, `git`, `tar`, `external`, `sandbox` appeared in
`~/.partcad`.

The user *configuration* file is deliberately not moved with it. PartCAD reads `~/.partcad/config.yaml` from the home
directory directly, without consulting `PC_INTERNAL_STATE_DIR`, so one configuration keeps applying across the snap,
the standalone bundle and the wheels. Redirecting that too would need a change in `partcad_utils`, not here.

The telemetry id stays there too, and for a stronger reason: it identifies a user, so an id that moved with the state
directory would make one machine look like several. `UserConfig.get_generated_id_path()` is the single definition of
where it lives — it used to be derived independently by the writer and by `pc system telemetry info`/`clear`, which
agreed only for as long as nothing set `PC_INTERNAL_STATE_DIR`. This snap was the first thing that did, which is how
the split was found; `tests/partcad/unit/test_telemetry_id_path.py` pins it.

## conda and git are not found, and that is fine

A snap does not carry the user's shell environment, so a conda installed under `$HOME` — the usual place — is not
visible to it, and neither is a git outside the standard system prefixes. This is accepted rather than worked around:
PartCAD already handles both. `pythonSandbox` defaults to `conda` only when a conda is importable or on `PATH`, and to
`none` otherwise, so CAD scripts run without a sandbox; git dependencies are simply unavailable. `pc healthcheck`
reports both as missing, and the CI job runs it for the record without letting it fail the build.

Anyone who needs the conda sandbox or git dependencies should use the standalone bundle or the wheels, which run with
the user's own environment.

## What ships in it

Everything the standalone bundle carries, unchanged: the interpreter, every Python dependency including the optional
extras, the CAD kernel, and OpenSCAD on amd64 (the arm64 bundle carries none — see the standalone README).

## CI

The `Standalone` workflow (`.github/workflows/build-standalone.yml`) builds both snaps in its `snap` job, from the
`partcad-standalone-ubuntu-24.04-x86_64` and `partcad-standalone-ubuntu-24.04-arm64` artifacts its `build` job
produced, then installs each and runs it. Taking the `ubuntu-24.04` bundle rather than whatever `ubuntu-latest` built
is what keeps the payload and the `core24` runtime on the same libraries; a bundle frozen against a newer glibc than
the base provides would install and then fail to start, and the "install and run" step is what would catch it.

The job is skipped on the release path and in the merge queue. Nothing downstream consumes its output, and a job whose
artifacts no release carries has no business being able to block one.

<a name="publishing"></a>

## Publishing

Not wired up. It needs a `SNAPCRAFT_STORE_CREDENTIALS` secret and, because the snap is classic, a manual review by the
Snap Store before the first upload is accepted. Once both exist, the step to add to the `snap` job is:

```bash
snapcraft upload dist/snap/partcad_<version>_<arch>.snap --release=stable
```

Until then `deploy.yml` deliberately does not download, check for, or upload these artifacts.
