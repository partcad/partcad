# The PartCAD snap

A third way to install the PartCAD command line tools, next to the [wheels on PyPI](../../docs/source/installation.rst)
and the [standalone bundle](../pyinstaller/README.md). It is not a third *build* — the snap wraps the very same
PyInstaller bundle the standalone archives ship, so there is one frozen artifact and one answer to the question of what
was released.

**Publishing is wired up, and waits on the store.** CI releases every version bump on `devel` to the Snap Store's
`edge` channel and every release from `main` to `stable` — once the `SNAPCRAFT_STORE_CREDENTIALS` secret exists.
Until then it builds and tests the snaps and skips the upload with a notice. The store side (registering the name, the
classic-confinement review, the credentials) is a one-time manual setup; [Publishing](#publishing) walks through it.

| | wheels | standalone bundle | snap |
| --- | --- | --- | --- |
| Install | `pip install -U partcad` | `curl -fsSL .../install.sh \| sh` | `snap install --classic partcad`, once published |
| Needs Python | yes, 3.10-3.14 | no | no |
| Platforms | Linux, macOS, Windows | one build per supported OS version | linux amd64 and arm64 |
| Carries a conda | no | yes | yes, from the bundle |
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

The price is a manual review before the Snap Store will publish it — see [Publishing](#publishing). A locally built
or CI-built `.snap` installs with `--dangerous --classic`.

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

## The host's conda and git are not found, and that is fine

A snap does not carry the user's shell environment, so a conda installed under `$HOME` — the usual place — is not
visible to it, and neither is a git outside the standard system prefixes.

For conda that no longer costs anything, and this section used to say it did. The snap wraps the standalone bundle,
the bundle carries its own conda (see the standalone README), and a payload inside the snap is visible to it whatever
the user's shell says — so `pythonSandbox` defaults to `conda` here as everywhere else and CAD scripts get their
sandbox. The CI job asserts exactly that. What the snap still does not get is the user's *own* conda, and with it the
package cache they have already filled: it builds its sandbox from scratch the first time, into
`~/snap/partcad/common`.

git is accepted rather than worked around: git dependencies are cloned through `libgit2` as everywhere else, and what
the snap cannot see is the user's git configuration. `pc healthcheck` reports it missing, and the CI job runs the
check for the record without letting that half fail the build.

Anyone who needs their git configuration, or wants to share a conda package cache they already have, should use the
standalone bundle or the wheels, which run with the user's own environment.

## What ships in it

Everything the standalone bundle carries, unchanged: the interpreter, every Python dependency including the optional
extras, the conda that provisions the CAD sandbox, and OpenSCAD on amd64 (the arm64 bundle carries none — see the
standalone README). No CAD kernel: the bundle stopped freezing one in, and every shape is built in the sandbox.

## CI

The job lives in `.github/workflows/snap.yml`, a reusable workflow with two callers:

| caller | when | channel |
| --- | --- | --- |
| `Standalone` (`build-standalone.yml`) | pull request, manual dispatch | none: build and test only |
| `Standalone` (`build-standalone.yml`) | version bump on `devel` | `edge` |
| `Deployment` (`deploy.yml`) | push to `main`, after the GitHub release is published | `stable` |

Each caller has already frozen the Linux bundles in the same run, and `snap.yml` wraps the
`partcad-standalone-ubuntu-24.04-x86_64` and `partcad-standalone-ubuntu-24.04-arm64` artifacts. Taking the
`ubuntu-24.04` bundle rather than whatever `ubuntu-latest` built is what keeps the payload and the `core24` runtime on
the same libraries; a bundle frozen against a newer glibc than the base provides would install and then fail to
start, and the "install and run" step is what would catch it. Which architectures a run packs is `SNAP_CORE` and
`SNAP_QUEUE_ONLY` in `build-standalone.yml` — amd64 alone on a pull request, both everywhere else — and `deploy.yml`
reads that same list through the called workflow's `snap-matrix` output rather than keeping its own.

The `build` job packs, installs and runs each architecture; the `publish` job runs only when a channel was asked for,
only after every architecture passed, and uploads them all. It is serialized per channel, so two runs cannot
interleave their releases.

On the release path the snap runs *after* the release rather than inside `Standalone`, so a snap that fails to build
or upload cannot hold back the wheels, the bundles or the IDE. A tag (the release rehearsal, which goes to Test
PyPI) builds no snap: there is no test Snap Store to rehearse against, and the `devel` version bump has already built
and tested the same tree.

<a name="publishing"></a>

## Publishing

What the workflows need is one repository secret, `SNAPCRAFT_STORE_CREDENTIALS`. **Without it nothing fails**: the
`publish` job writes a notice into the run's summary and succeeds. That is also what every fork gets.

Getting it is a one-time setup, done by a maintainer, on an Ubuntu machine (or any machine with
`sudo snap install snapcraft --classic` and a desktop keyring — `snapcraft login` will not work over a bare SSH
session).

### 1. An account and the name

1. Create an **Ubuntu One** account at <https://login.ubuntu.com> (it is the Snap Store's login), and sign in to
   <https://snapcraft.io> with it once, which creates the developer account and asks you to accept the developer
   agreement. Use an address the project controls rather than a personal one if you can: the account owns the
   name, and moving a snap between accounts is a request to the store team. Turn on two-factor authentication.
2. Register the name, either at <https://snapcraft.io/register-snap> or with

   ```bash
   snapcraft login
   snapcraft register partcad
   ```

   If `partcad` is already registered to somebody else, the store offers a dispute form; a project that owns the
   upstream (`partcad.org`, `github.com/partcad`) normally gets the name.
3. Optionally, add co-maintainers: <https://snapcraft.io/snaps> → `partcad` → *Collaboration*, or turn the account
   into a *brand* account for an organization.

### 2. Classic confinement

The snap is `classic` (see [Confinement](#confinement)), and the store refuses a classic snap until a human has
granted it. Ask on the forum:

1. Open a topic in the **store-requests** category of <https://forum.snapcraft.io>, titled e.g.
   *"Classic confinement request for partcad"*.
2. Say what the snap is and why strict confinement cannot work. The [Confinement](#confinement) section above is the
   argument, and it falls squarely in the store's "developer tools that act on the user's files and run arbitrary
   build tools" category. Link the recipe (`.snapcraft.yaml`) and the source repository.
3. Ask for the **`pc` alias** in the same topic — an automatic alias `pc` → `partcad.pc` — so that users do not
   have to run `snap alias` themselves (see [Commands](#commands)). It is reviewed the same way.

The reviewers usually want an uploaded revision to look at. The simplest way is to upload one CI already built by
hand: download the `partcad-snap-amd64` artifact from a `Standalone` run on `devel`, unzip it, and

```bash
snapcraft upload partcad_<version>_amd64.snap
```

without `--release`. The upload goes into manual review; mention it in the forum topic.

### 3. The credentials

Export a login that can do nothing but upload and release this one snap, with an expiry:

```bash
snapcraft export-login \
  --snaps=partcad \
  --channels=edge,stable \
  --acls=package_access,package_push,package_update,package_release \
  --expires=2027-10-01 \
  snapcraft-credentials.txt
```

The file holds a single line of base64. Treat it like a password: it is not tied to a machine, and anyone holding it
can publish `partcad` to those channels until it expires. Delete it once it is in GitHub.

### 4. GitHub

**Add the secret only once the classic review has been granted.** Before that, the store accepts each upload and then
holds it for manual review, which `snapcraft upload` reports as a failure — every `devel` version bump would go red.

1. Repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
2. Name: `SNAPCRAFT_STORE_CREDENTIALS`. Value: the contents of `snapcraft-credentials.txt`, exactly as written.

Or, with the GitHub CLI: `gh secret set SNAPCRAFT_STORE_CREDENTIALS --repo partcad/partcad < snapcraft-credentials.txt`.

A repository secret, not an environment one: `snap.yml` is called both from `devel` (for `edge`) and from `main`
(for `stable`), and its jobs declare no environment. Note the expiry somewhere a maintainer will see it; an expired
login fails the `publish` job with an authentication error, and the fix is step 3 and step 4 again.

### 5. After the first release

- The store listing: <https://snapcraft.io/partcad/listing> takes the icon, screenshots and links, which the recipe
  does not carry.
- The documentation: the "not published yet" notes in `docs/source/installation.rst` can go, along with
  `--dangerous` in its install command.
- Releases go out through `snapcraft upload --release`; promoting an `edge` revision by hand
  (`snapcraft release partcad <revision> stable`) also works and is how to roll `stable` back.
