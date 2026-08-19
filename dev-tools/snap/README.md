# The PartCAD snap

A third way to install the PartCAD command line tools, next to the [wheels on PyPI](../../docs/source/installation.rst)
and the [standalone bundle](../pyinstaller/README.md): `snap install partcad`. It is not a third *build* — the snap
wraps the very same PyInstaller bundle the standalone archives ship, so there is one frozen artifact and one answer to
the question of what was released.

| | wheels | standalone bundle | snap |
| --- | --- | --- | --- |
| Install | `pip install -U partcad-cli` | `curl -fsSL .../install.sh \| sh` | `snap install --classic partcad` |
| Needs Python | yes, 3.10-3.14 | no | no |
| Platforms | Linux, macOS, Windows | linux-x86_64, macos-arm64, windows-x86_64 | linux-x86_64 |
| Upgrades | `pip install -U` | re-run `install.sh` | automatic, by snapd |
| Root to install | no | no | yes |

## Files

- `../../snap/snapcraft.yaml` — the recipe. It has to sit in `snap/` at the repository root: that is both where
  `snapcraft` looks for it and what fixes the project directory it copies into its build environment. Putting it here,
  next to the rest of the build tooling, would leave `dist/standalone/partcad` outside that directory.
- `build.sh` — makes sure the bundle exists, checks it, and drives `snapcraft`.

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

The result lands in `dist/snap/`: `partcad_<version>_amd64.snap` and its `.sha256`. Install it locally with

```bash
sudo snap install --dangerous --classic dist/snap/partcad_<version>_amd64.snap
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
provisions conda sandboxes under `~/.partcad` and runs CAD scripts in them, and serves a daemon over a socket that the
VS Code extension connects to. Strict confinement would cut all of that off at the snap's own directories, and would
not carry the host's `conda` or `git` on `PATH` either — and those two stay host prerequisites here exactly as they are
for the wheels and the bundle.

The price is a manual review before the Snap Store will publish it. Until that happens, the `.snap` attached to each
[GitHub release](https://github.com/partcad/partcad/releases) installs with `--dangerous --classic`.

For the same reason, snapcraft's `classic` and `library` linters are switched off in `snapcraft.yaml`, and its
`enable-patchelf` build attribute is deliberately left unset: PyInstaller's shared libraries find each other through
`$ORIGIN` and the bundle's own bootloader, so rewriting their rpaths would break the bundle rather than fix it. The
comments in `snapcraft.yaml` say the same at the point where it matters.

## What ships in it

Everything the standalone bundle carries, unchanged: the interpreter, every Python dependency including the optional
extras, the CAD kernel, and OpenSCAD. `git` and `conda`/`mamba` are resolved from the host. `partcad.pc healthcheck`
reports what is missing.

## CI and releasing

The `Standalone` workflow (`.github/workflows/build-standalone.yml`) builds the snap in its `snap` job, from the
`partcad-standalone-linux-x86_64` artifact its `build` job produced, then installs it and runs it. `deploy.yml` calls
that workflow on a push to `main` and uploads the `.snap` to the same GitHub release as the wheels and the archives.

One coupling is worth knowing about, because nothing declares it: the bundle is frozen on the `build` job's runner
(`ubuntu-latest`) and then runs inside a `core24` snap, i.e. on Ubuntu 24.04 libraries. Those agree today. If
`ubuntu-latest` moves ahead of 24.04, the bundle will link against a newer glibc than `core24` provides and the
installed snap will fail to start — the `snap` job's "install and run" step is what catches that. The fix is to move
the base forward (`core26` and so on) or to pin the Linux bundle's runner to the base's release.

Publishing to the Snap Store is not wired up: it needs a `SNAPCRAFT_STORE_CREDENTIALS` secret and, for a classic snap,
that manual review. `snapcraft upload dist/snap/partcad_<version>_amd64.snap --release=stable` is the step to add once
both exist.
