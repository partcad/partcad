# PartCAD

## Overview

This repository contains all open source software that forms the PartCAD ecosystem. It ships **one** Python
distribution, `partcad`, plus a `partcad-cli` compatibility shim; everything else here is an editor extension,
a CAD addon, or documentation.

### The packages, all inside the one wheel

* [src/partcad](./src/partcad/AGENTS.md):

  The core logic that enables maintaining digital thread for manufacturable physical products.

* [src/partcad_cli](./src/partcad_cli/AGENTS.md):

  The CLI interface to most of `partcad` functionality — the `pc` and `partcad` commands.

* [src/partcad_service_json_rpc](./src/partcad_service_json_rpc/AGENTS.md):

  A JSON-RPC service (`partcad-json-rpc` executable) exposing `partcad` functionality with methods that mirror
  the CLI. By default it runs a per-workspace background **daemon** (served over a socket / Windows named
  pipe); it can also serve over stdin/stdout or HTTP. It is the backend for `ide/vscode`, for `cad/freecad`,
  and for most `pc` commands, and the CLI manages it via `pc daemon start`/`stop`.

  The daemon owns the warm PartCAD context **and** the sandboxed Python runtimes that CAD wrappers execute in,
  so a client need not have a CAD environment at all. That is what decides whether a command runs in the client
  or on the daemon — see "Command boundary" in `src/partcad_cli/AGENTS.md`.

  **A remote daemon is never told to upgrade itself.** There is no upgrade or self-update method in the
  JSON-RPC surface and none may be added; that is a protocol rule, and it is the reason this package does not
  import `partcad_client`. Updating a *local* installation is `pc upgrade`, run by the client on its own
  machine.

* [src/partcad_utils](./src/partcad_utils):

  The lightweight pieces **every** package shares without a CAD-kernel dependency: logging, telemetry, user
  configuration — and the client/daemon rendezvous, `framing` and `workspace` (which socket serves which
  workspace, and whether anything is answering on it). The rendezvous lives here precisely because neither end
  owns it: a copy on each side is a copy that can disagree, and a disagreement is a client silently starting a
  second daemon.

* [src/partcad_client](./src/partcad_client):

  What a **client** does, and a daemon must not: discovering the daemon serving a workspace and connecting to
  it (`daemon`, `client`), replacing this installation of PartCAD (`selfupdate`), and opening a file in a
  third-party CAD application on this machine (`external`).

  All of it acts on **this machine**, from the process running out of it. A daemon can be remote, where
  "update PartCAD" would mean updating somebody else's installation and "stop the local daemons" somebody
  else's daemons; and a daemon that went looking for its neighbours would be racing every client on the
  machine. A client is one process acting on its own machine, which is what makes `pc upgrade` stopping every
  local daemon a sane thing to do rather than a distributed algorithm.

  `selfupdate` itself knows nothing even about that: a caller passes `before_install`, which `pc upgrade` uses
  to stop the local daemons and wait for them. `pc upgrade` (the host-level command; `pc update` refetches a
  package's imports and is unrelated) ends up here, as does the VS Code extension's "Update PartCAD" — by
  running `pc upgrade`. Nothing about daemons or upgrading is reimplemented in TypeScript.

  It also refuses: `pc upgrade` run inside a bundle the editor extension downloaded errors out and says to
  update the extension instead, since the extension owns that bundle.

  `external` is the same rule applied to a window instead of an installation. `pc open` (and the VS Code
  extension's per-part "Open in..." menu, by running it) starts FreeCAD on the screen of whoever ran the
  command — on this machine, with this machine's file, and never over the wire; there is no RPC method for
  opening a file and none may be added. A machine with no local installation can run the application in a
  container PartCAD keeps for it, named after the tool (`partcad-freecad`), with the workspace and the
  daemon's socket mounted at the paths they have here and the host's X display forwarded into it.

  One application in that table reads meshes and nothing else — Blender — so an object that is not already one
  is converted to STL before it is handed over. That conversion is the single thing `pc open` asks the daemon
  for, because a CAD wrapper is what does it; the window still opens here, and the registry still has no
  `open` method. Which object types are meshes is `object_types`, an inlined copy of PartCAD's own tables (a
  client must stay cheap to import) that a completeness test keeps honest.

* [src/partcad_ide_client](./src/partcad_ide_client/AGENTS.md):

  The Python side of the socket protocol `partcad` uses to display shapes in the IDE's `PartCAD Viewer`. Lazily
  imported by `partcad.viewer`, and by nothing else.

### Everything else

* [ide/vscode](./ide/vscode/AGENTS.md):

  Visual Studio Code extension for navigating through objects in a `partcad` project and UI interface to some
  of `partcad` functionality. Hosts the `PartCAD Viewer`. It is a **JSON-RPC client and nothing else** — it
  talks to `partcad-json-rpc` and contains no Python of its own. Published as `PartCAD.partcad-official` — the
  name is not `partcad` because the shim below holds that one, and the marketplace does not let two publishers
  share an extension name.

* [ide/vscode-shim](./ide/vscode-shim/AGENTS.md):

  The `OpenVMP.partcad` marketplace entry, as a transition shim: no code, one `extensionDependencies` on
  `PartCAD.partcad-official`. The extension above used to be published by the `OpenVMP` publisher, and a
  publisher is half of an extension's identity — the new entry is a *different* extension as far as the
  marketplace and the editor are concerned, and nothing carries an installation across. So the old entry is not
  abandoned; it is replaced by a package that pulls the new one in, and an existing installation updates into
  it. Same shape as `dev-tools/shim/` below, and temporary in the same way. Do not give it a `main` or a
  `contributes`: both extensions are installed at once afterwards, and anything it contributed would be
  contributed twice. Its `name` stays `partcad`, which is the other half of the identity it has to keep — and
  the reason the extension above had to take a different one.

* [ide/standalone](./ide/standalone/AGENTS.md):

  The **PartCAD IDE**: a rebranded [VSCodium](https://vscodium.com/) build carrying the extension above, the
  extensions this repository recommends, and the standalone command line tools -- one application to download,
  for users who have no Python and no editor set up. It always opens in the PartCAD workbench. Installed with
  `install.sh --ide`.

* [cad/freecad](./cad/freecad/AGENTS.md):

  The `PartCAD` addon (workbench) for FreeCAD: browse packages, parts and assemblies as a hierarchy, set an
  object's parameters in a generated dialog, and import the result into the open document as a STEP file. Like
  `ide/vscode` it is a thin client of the JSON-RPC service (the standalone PyInstaller bundle), because
  FreeCAD's embedded Python cannot host `partcad` itself.

* [dev-tools/shim/](./dev-tools/shim/pyproject.toml):

  The `partcad-cli` compatibility package: no modules, no entry points, one dependency on `partcad`. It exists
  so that an older `pip install partcad-cli` keeps working. Do not give it modules or entry points — two
  distributions owning one import name or one console script break each other on uninstall, silently.

* [README.md](./README.md) and [docs/source](./docs/source):

  Human-friendly documentation. `docs/source` is the Sphinx tree published to
  [Read the Docs](https://partcad.readthedocs.io/); `docs/source/index.rst` has its table of contents.

## Development process

Full narrative guide (Docker/dev-container setup, PR merge criteria): `docs/source/contributing.rst`.
Package-specific commands: `src/partcad/AGENTS.md`, `src/partcad_cli/AGENTS.md`,
`src/partcad_service_json_rpc/AGENTS.md`, `src/partcad_ide_client/AGENTS.md`. Other components:
`ide/vscode/AGENTS.md`, `ide/standalone/AGENTS.md`, `cad/freecad/AGENTS.md`.

### Where commands run

**Validation and commits run inside the dev container, not on the host.** The container is the only environment
where the pinned toolchain and the `pre-commit` hooks are available. `.devcontainer/devcontainer.json` is the
single source of truth for it — the image, the dev container features, the mounts, the `SKIP` hook list, and
the `pre-commit install` that runs as `postStartCommand`. Do not copy those values elsewhere; read them there.

Human contributors normally enter this environment through the VS Code Dev Containers extension. An agent
working in a terminal cannot, so use the `@devcontainers/cli` instead. It reads the same
`.devcontainer/devcontainer.json` and produces the same environment.

Start the environment (**on the host**, once per session; the first run is slow while features install):

```bash
npx --yes @devcontainers/cli up --workspace-folder .
```

Run any command **inside** the environment:

```bash
npx --yes @devcontainers/cli exec --workspace-folder . <command>
```

Everything below is written as the command to pass to `exec`.

#### When there is no dev container to enter

`devcontainer up` needs a Docker daemon, and some machines have none — a cloud agent session, a bare CI
runner. There the container is not a thing to insist on; it is a thing that cannot happen, and the fallback is
to install into the checkout and run everything directly:

```bash
./dev-tools/setup-native.sh          # poetry install, OpenSCAD, and what installing outside the container gets wrong
```

Then drop the `devcontainer exec` prefix from every command below and keep the `poetry run` one.

That script installs **OpenSCAD** as part of setting up, because PartCAD treats it as part of the toolchain
rather than as an optional extra — the standalone bundles carry one, `pc healthcheck` asks after it, and a
`.scad` part fails without it rather than degrading. It stops if it cannot get one, rather than leaving that
to be found by a test run half an hour later.

This is still a fallback and not a second supported environment. What it does not give you:

* **`pre-commit`.** It is installed by the container's image, not by `poetry install`, and `.git/hooks/` is
  written by `pre-commit install` running *inside* the container. So on such a machine there is no hook to
  fail and `git commit` silently runs no gate at all — which is worse than a hook that refuses, because
  nothing tells you. Run what the hooks run (`pytest`, `behave`, and the linters) before committing, and read
  their output; CI runs them either way.
* **A Docker daemon.** The KiCad example needs one, and so does the `docker` Python sandbox — which is now the
  default wherever a daemon answers *and* PartCAD's base image can be had, so a machine with Docker running is
  a machine that renders in it. (The `remote` sandbox needs no daemon here at all: it needs a reachable
  `partcad-service-remote-docker`, which has one.) Nothing has to be declared for a machine that simply has
  no daemon: the KiCad test skips on one that is unreachable exactly as it does on one that was turned off.
  `PC_USE_DOCKER=false` (or `useDocker: false`) is the explicit opt-out — for a machine that *has* a daemon
  and should not use it, and for a container image built without one, which can then say so once rather than
  discovering it per subject. It skips on *that* and nothing else: an image it cannot pull, a `kicad-cli` that errors, a
  part that comes back empty are all still failures, because those are the subject being broken rather than
  the machine not having a container runtime.
* **conda.** Without it the Python sandbox falls back to `venv`, which is a real sandbox and passes the suite;
  it just cannot provision an *interpreter version*, so a package asking for a Python this host does not have
  renders on the host's and says so. See `pythonSandbox` in `src/partcad_utils/user_config.py`.

**Never run the whole `behave` suite here — run the one feature a change touches.** Every scenario takes a
throwaway `$HOME` (the `Given I have temporary $HOME` in each feature's `Background`), so a scenario that
renders anything builds a CAD sandbox of its own from nothing and deletes it afterwards: ~2.7 GB and minutes
of `pip` each, across 166 scenarios, and several of them on disk at once under `behavex`'s parallel workers.
That is hours and tens of GB, and on a machine with a fixed disk allowance it ends in "no space left on
device" rather than in a result. So:

```bash
poetry run behave features/<name>.feature      # yes
poetry run behave                              # no, not here
```

A green whole-suite `behave` is **not** a prerequisite for opening a pull request from such a machine; CI
shards that suite and runs it there. Say in the pull request which features you did run.

One failure mode is worth recognising on sight, because nothing about it names its cause: **two wheels that
install the same file can leave the checkout segfaulting.** Poetry installs in parallel, so both workers can
write that one path at once and what lands is a blend of the two — reported as success by both. An `import` of
a native module like that dies inside the dynamic loader, so pytest *collection* ends with `Fatal Python
error: Segmentation fault` and no failing test to point at. `dev-tools/check_installed_files.py --fix` detects
and repairs it, and `setup-native.sh` runs it. Do not go looking for a bug in the change under test.

The pair that did this was `cadquery-ocp` and `cadquery-ocp-novtk`, both of which ship one 160 MB
`OCP/OCP.cpython-*.so`. `cadquery-ocp` is no longer named in `pyproject.toml` — nothing here imports
`cadquery` in process, and build123d pulls the novtk build in regardless — so one distribution owns the file
and this cannot happen to *that* file any more. The checker stays because the next such pair will not
announce itself either.

It also catches the other half of it, which **an existing checkout hits exactly once**: an uninstall deletes
the files its RECORD names, including the ones the wheel beside it also installed. So `poetry sync` removing
`cadquery-ocp` takes `OCP/` away from `cadquery-ocp-novtk`, which stays installed, and `import OCP` stops
working with nothing said about it anywhere. `check_installed_files.py --fix` reports and repairs that too.

### Environment setup

Dependencies are already installed in the image. Only re-run this if you change `pyproject.toml`:

```bash
poetry install        # installs the `partcad` distribution -- all six packages -- in editable mode
```

**If `pc` fails with `ModuleNotFoundError: No module named 'partcad_cli.click.command'`, the `.venv` predates
the one-wheel layout.** It still holds the editable install of the old root project, `partcad-dev`, whose `.pth`
points at the six deleted `<package>/src` directories and whose `pc` script points at the pre-rename entry point.
`poetry install` does not replace it, because the distribution was renamed and Poetry does not know it is there;
`pip uninstall partcad-dev` refuses to remove it. The old source tree lingers too: `git` leaves `partcad/`,
`partcad-cli/` and their four siblings behind when the only files left in them are ignored ones. Delete both and
install again — the `.. warning::` beside `poetry install` in `docs/source/contributing.rst` has the commands.

The project virtualenv is not auto-activated, and `pytest`, `pc`, and `partcad` are **not** on `PATH` — prefix
project commands with `poetry run`.

Pass the global `--no-ansi` flag whenever `pc` is run non-interactively — in scripts, in batch jobs, and
especially when an LLM agent parses the output. Without it, `pc` draws animated ANSI progress bars whose control
characters corrupt captured output; with it, output is plain text with `INFO:`/`ERROR:` prefixes. Note that
`--no-ansi` routes those logs to **stderr** (plain `logging`), whereas the default ANSI renderer writes to
**stdout** — so capture both streams (`2>&1`) when parsing. The flag is global and goes before the subcommand:
`poetry run pc --no-ansi info`.

Note that `poetry.toml` sets `in-project = true`, so the virtualenv lives at `./.venv` inside the bind-mounted
workspace and is shared between host and container. Running `poetry` on the host after running it in the
container (or vice versa) makes each side rebuild `.venv`, because the interpreter paths baked into it are only
valid on one side. Keep Python work on one side — the container — to avoid the thrash. `.venv` is gitignored,
so this never affects a commit.

### Tests

From the repo root, inside the environment:

```bash
poetry run pytest tests cad/freecad \
  -x -p no:error-for-skips -p no:warnings --dist no                                        # unit tests (matches CI)
poetry run behave                                                                        # integration tests (./features)
```

CI fans these out over operating systems, and how much of that fan-out a run gets is decided in two places,
which answer two different questions.

`.github/actions/test-depth` answers **how deep**, in three tiers. A pull request gets `pr`: every image
except macOS, and the oldest and newest supported Python only. Both Windows images stay on every tier and
that is deliberate — Windows is where a path separator written on Linux goes wrong, so it is the platform a
pull request most needs, not the one to economise on. The merge queue gets `queue`, which is what a pull
request used to get — every current image, macOS included, and the full Python range — so the coverage a
pull request drops is coverage the commit still earns before it lands, once per merge rather than once per
push. Everything else gets `deep`: the nightly schedule, a manual dispatch, any push, and a pull request
whose title or description contains `#deepTest`. `#deepTest` runs exactly what it ran before any of this
existed. It answers a second, narrower question the same way: `#images` rebuilds PartCAD's own container
images (see below).

A third gate, `.github/actions/container-images`, answers **which images this run is about**. PartCAD's
container images — the Python sandbox bases and the KiCad sandbox — are tagged with the release, and only the
version bump on `devel` writes those tags, so until this existed a change to `tools/containers` built the new
images and then tested against the last release's: a Dockerfile fix could not be proven on the pull request
that made it, which is how the `pycairo` fix sat in the repository while every PNG went on failing. Such a run
now builds and publishes `<release>-<branch>` and exports `PC_CONTAINER_IMAGE_TAG`, which
`partcad_utils.container_image.image_tag` reads and every reader of those images goes through — so the tests
in that run reach what that run built. It is turned on by a change under `tools/containers/` (a
`changed-scopes` bucket) or by `#images` in the pull request, and it is off otherwise, which is why an
ordinary pull request still pays nothing for it. A branch tag is safe to publish from an unreviewed branch
because nothing but that run asks for it; the release tag, which somebody else pulls, is still only ever
written by the bump. Both `CI` and `CI-Dev` call that action rather than deciding for themselves — they hand
the answer to the same `Container (KiCad)` build, and two answers would be two tags for one image.

`.github/actions/changed-scopes` answers **which jobs at all**, by sorting the changed files into buckets: a
documentation-only change runs the documentation build and nothing else, an `ai-agents/` change runs the
Claude Code plugin, a `.devcontainer/` change runs the container's behave and `pc` jobs but not its pytest.
It is fail-safe — a path it does not recognise counts as both source and a dependency, so it runs everything a source change runs, the standalone bundles included. It does not turn on the four subjects that only their own directory turns on (the documentation, the extension, the IDE, the plugin), and that is not a gap: each is built from one fixed directory, so a path outside them cannot change what they contain —
and it is a job condition rather than a `paths:` filter, because `merge_group` supports no `paths:` filter
(so a trigger-level list is one the merge queue ignores, which is how a README typo used to freeze four
standalone bundles in the queue) and because a workflow skipped by `paths:` never creates the check run a
*required* check waits for, while a skipped job reports `skipped`, which counts as passing. Do not move these
gates back onto the triggers.

One bucket boundary in there is a deliberate trade rather than a fact, and it is the standalone bundles.
`Standalone` is gated on **dependencies** (`pyproject.toml`, `poetry.lock`, root `requirements*`) and on
`dev-tools/pyinstaller/`, `dev-tools/snap/`, `.snapcraft.yaml` and `install.sh` — not on `src/**`. Freezing
is the most expensive thing here, and what makes a bundle differ from a working wheel is nearly always what
went into it. A source change *can* break the freeze all the same (see `dev-tools/pyinstaller/README.md`),
and the safety net for that is what `devel` does after the merge: the version bump that follows it is the same tree
with a version on it, and `build-standalone.yml` freezes there. Short of `#deepTest` that bump is the only thing that
builds a bundle for a source change, so do not narrow what a push to `devel` runs.

`docs/source/contributing.rst` explains both to contributors. Note that a push to `devel` runs no matrix at all unless
its head commit message starts with `Version updated` — the `set-matrix` job, and every job that depends on it, is
skipped otherwise. That holds for every workflow now, `Standalone` and `IDE` included. Those two used to run on the
merge as well: the same tree was built twice, minutes apart, and the first set of artifacts carried the version that
merge had just replaced. Neither carries a `paths:` filter on its push trigger any more, because the gate is what
decides and a filter in front of it could only ever hide it — a bump touches `pyproject.toml` and
`ide/vscode/package.json` today, and the day `dev-tools/bumpversion.toml` stops naming such a file nothing would ever
be built on `devel` again, with nothing to say so.

**Neither gate trusts pytest's exit code.** On Windows it disagrees with the run in both directions — exit `0`
with a test having failed (which is what #444 was written for), and exit `127` after a session where every test
passed (which is what `Pytest (windows-*, 3.12)` does today). So the `pytest` `pre-commit` hook and the
`Pytest` job both set `PYTEST_RESULT_MARKER` to a PID-unique path they then read, and the `pytest_sessionfinish`
hook in the repository's root `conftest.py` writes `success` into it only when pytest's **final** exit status is
clean **and** it counted no failed tests. It is the outermost wrapper and reads `session.exitstatus` rather than
the status it is handed, because pytest's terminal reporter can still raise that status after the inner session
hooks have run — `--max-warnings` being exceeded is how — and reading the argument would record a success for a
session pytest then failed. That hook belongs at the root and nowhere else: a copy scoped to one package's tests
records nothing for a run that does not collect that directory, and a gate reading no marker fails — which is
also what keeps a crash mid-suite from passing. Do not move it, do not make it a plain (non-wrapper) hook, and
do not let anything read the exit code instead.

The dev container's own jobs in `test-dev.yml` lost a run's result a second way, and it is worth recognising
because it looks like nothing: a `devcontainers/ci` `runCmd` is one script, so the step's result is the **last**
command's. `Run: pytest` ended with `echo DONE` and reported a passing job over a failed test — for as long as
nobody compared the job's colour with the JUnit it had just uploaded. `Run: behave` and `Run: pc` ended with
`coverage xml`, which succeeds after a failing run because coverage writes its data whatever the program exited
with. Every one of those scripts now starts with `set -e`, and the two that have a report to write keep the
status and `exit` it at the end. Do not end such a script with a command whose success is not the result.

That dev container also cannot use the `docker` Python sandbox, and PartCAD now knows it: it holds the *host's*
`/var/run/docker.sock`, so the daemon it talks to resolves bind mounts against the host's filesystem rather than
the container's. `mounts_are_shared` in `runtime_python_docker.py` asks that question by writing a file and
having a throwaway container look for it, so the sandbox is reported unavailable there and conda is used
instead, rather than every part failing on a path. It is one probe per process; see the docstring for what a
wrong answer costs in each direction.

The packages under `examples/` are a third suite. The images and `README.md` files there are what
`cd examples && pc render -r` produces, and they are checked in so that a change in how PartCAD renders is a
diff someone has to look at rather than something a reader of the README discovers. If a change affects a
projection or a generated document, re-render and commit the result. The `example-images` `pre-commit` hook
catches the cheap half of this instantly (a README pointing at an image that is not checked in); the
`Examples (PartCAD)` job in `test.yml` renders everything and fails if the tree changed, on one cell of the
matrix because what is checked in is one rendering. Every output type PartCAD implements is byte-stable, DXF
included: the built-in DXF renderer suppresses the timestamp and GUIDs a DXF is otherwise stamped with and
pins the order of its `CLASSES` section, under the `reproducible` parameter of the `dxf` file type (on by
default). An implementation another package supplies may not be, and those files are named one by one in that
job's `UNSTABLE` list — keep it short, and give every entry a reason there and in the package it belongs to.

Lint/format (Python): `black`, `flake8`, `isort` — configured in `pyproject.toml`.

### Packaging

Six artifacts ship from this repo: **one Python wheel** (`partcad`, carrying all six packages and all four entry
points, with a `partcad-cli` shim published beside it from `dev-tools/shim/` so the older install instruction keeps
working), the standalone PyInstaller bundles for users who have no Python, the PartCAD IDE, which carries those
bundles inside it, the VS Code extension's `.vsix` (with the `ide/vscode-shim` `.vsix` published beside it, for the
same reason the wheel has one), the `pc` plugin for Claude Code, and the snap, which wraps the Linux bundle and is
built but not published yet.

There used to be five wheels pinning each other at `==`. Do not add a second distribution back: within one
distribution a pin is an import, and two distributions owning one import name break each other on uninstall
without pip noticing. Adding a runtime dependency, an optional extra, or a file that is read at runtime can be
invisible to the frozen bundle and break it while the wheel stays fine — see `dev-tools/pyinstaller/README.md`
before doing any of those. Note that the bundles fan out over
*OS versions* (`ubuntu-22.04-x86_64`, `macos-15-arm64`, …), and that the same platform ids appear in several
places that mostly nothing keeps in sync; the README says which, and which of them a pull request skips
without `#deepTest`. The
`.vsix` is built once by `.github/workflows/vsix.yml`, which `build.yml` and `deploy.yml` both call, and
`ide/standalone/build.sh` runs the same `npm run vsce-package` for the copy inside the IDE. One build
serves every platform: the extension is a JSON-RPC client with no Python and no compiled content in it. The
same workflow packages the transition shim beside it, under the extension's version — which the shim does not
state anywhere, but reads at package time, so the two cannot drift. A shim older than the entry it replaces is
one the marketplace never delivers, and a second literal to bump is how that happens. Changing
`.vscode/extensions.json` changes what the IDE ships with — see `ide/standalone/README.md`. The plugin is built
the same way, by `.github/workflows/plugin.yml`, and published two ways by `deploy.yml`: `pc-<version>.zip` on
the release, and the `plugin-dist` branch, which is what `/plugin marketplace add partcad/partcad@plugin-dist`
reads. It has no version of its own — `plugin.json` is in `dev-tools/bumpversion.toml` like everything else —
and it must not get one back: it had one, and stayed at 0.1.0 for twenty-three releases because publishing it
meant remembering a tag nobody pushed. **The skills it is made of also ship in the wheel**, through two symlinks
under `src/partcad/ai_agents` into `ai-agents/`, because `pc init` installs them into the repository it creates a
package in and the wheel is what a user has: the plugin for Claude Code, `pc-`-prefixed copies for Cursor. The
skills stay at the top of the repository where a visitor finds them, and there is one copy of each file.
So `ai-agents/common` is *both* the plugin and the distribution, which is why `.github/actions/changed-scopes`
classifies it into both buckets, why `pyproject.toml` and `dev-tools/pyinstaller/partcad.spec` both name it as
data, and why a new file under a skill has to be covered by the `package-data` patterns or it is simply absent
from what gets installed. **The build refuses a checkout that dropped those symlinks** — `pyproject.toml` names
an in-tree PEP 517 backend, `dev-tools/build-backend/`, which is `setuptools.build_meta` plus that one
precondition on `build_wheel` and `build_sdist`. Without it the artifact is silently empty: `skills/**/*`
matches nothing where `skills` is a text file holding a path, `plugin.json` matches that same kind of file and
is packaged as its content, and the wheel then installs, imports and runs `pc version` with no skills in it.
`build_editable` is *not* guarded, on purpose: an editable install reads the working tree live, and refusing
there would fail `poetry install` over a data file. See `ai-agents/README.md`. The snap
carries whatever the bundle carries,
so it needs nothing extra of its
own; `dev-tools/snap/README.md` covers what is specific to it (confinement, aliases, the base, its state directory).
Its build tooling lives beside that README, but the recipe, `.snapcraft.yaml`, stays at the repository root and
cannot move down into `dev-tools/` with it: the directory `snapcraft` runs in is the project directory — what gets
copied into the build environment and what `source:` resolves against — and snapcraft looks for the recipe only at
four paths within it, the root itself, `snap/`, or `build-aux/snap/`. Running it from `dev-tools/` instead would
leave the `dist/standalone/partcad` bundle it packages outside that directory. The dotfile is the
root-level spelling that leaves no directory behind; the comment at the top of the file says all of this too.

### Committing

This repo uses `pre-commit` (config at `dev-tools/pre-commit-config.yaml`) to run formatting/lint checks,
`pytest`, and `behave` on commit. These hooks are required to pass in CI before a PR can merge — do not skip
them with `--no-verify` unless explicitly instructed to.

Run the commit inside the environment:

```bash
npx --yes @devcontainers/cli exec --workspace-folder . git commit -m "<message>"
```

Check the gates before committing, so hook failures are separated from commit problems:

```bash
pre-commit run --config dev-tools/pre-commit-config.yaml
```

Hooks that reformat files (`trailing-whitespace`, `end-of-file-fixer`) rewrite them in place — re-stage
anything they touch, then commit.

**If `git commit` fails with `` `pre-commit` not found ``, you are committing on the host, not in the
container.** `.git/hooks/pre-commit` is generated by `pre-commit install` running *inside* the container, so it
hardcodes an interpreter path that exists only there. The fix is to re-run the commit inside the environment.
It is never to retry with `--no-verify`, and never to install `pre-commit` on the host — host tool versions are
not the pinned ones, which is how a commit passes locally and then fails CI.

**If the commit fails with `Author identity unknown`**, the container has no git identity. The VS Code extension
copies your host gitconfig in; the CLI does not, and anything written to the container's home directory is lost
when the container is recreated. Set the identity repo-locally instead — `.git/config` lives in the bind-mounted
workspace, so it survives recreates and is never committed:

```bash
git config --local user.name "<your name>"
git config --local user.email "<your email>"
git config --local user.signingkey "<your key id>"   # only if you sign
git config --local commit.gpgsign true               # only if you sign
```

Do not mount your host `~/.gitconfig` into the container to solve this. If it contains `url.*.insteadOf` rules
rewriting `https://github.com/` to SSH (a common setup), the `git-lfs` feature's post-create step will try SSH,
find no key in the container, and fail the whole `up`.

**If the commit fails to sign** (`gpg failed to sign the data`), the container has your public key but not your
private key. The VS Code extension forwards your GPG agent automatically; the CLI does not. Forward the agent's
extra socket when starting the environment, which keeps the private key on the host:

```bash
npx --yes @devcontainers/cli up --workspace-folder . \
  --mount "type=bind,source=$(gpgconf --list-dirs agent-extra-socket),target=/run/host-gpg-agent.sock"
```

Then point the container's agent socket at it (the socket lives in `/run/user/$(id -u)/gnupg/`, not `~/.gnupg/`):

```bash
gpgconf --kill gpg-agent
ln -sf /run/host-gpg-agent.sock /run/user/$(id -u)/gnupg/S.gpg-agent
```

Verify with `gpg --list-secret-keys` — your key should appear, served by the forwarded host agent.

**If `pre-commit` fails to install a hook with `Permission denied (publickey)`**, a rewrite rule in your
gitconfig is turning its fetch of the hook repository into an SSH fetch. `url."ssh://git@github.com/".insteadOf
= https://github.com/` is a common setup, and the VS Code extension copies your gitconfig into the container,
rewrite rules included — so pre-commit clones `https://github.com/...` and git dials `git@github.com`. A VS Code
terminal has the forwarded SSH agent and succeeds; a `devcontainer exec` shell has no agent and does not. Two
ways out, on the host:

* Scope the rule to `pushInsteadOf` rather than `insteadOf`, which is usually what the rule is for anyway: push
  over SSH, fetch anonymously over https.
* Or use the host's SSH agent, which is already bound in at `/run/host-ssh-agent.sock` —
  `.devcontainer/host-sockets-init.sh` resolves `SSH_AUTH_SOCK` on the host and `devcontainer.json` binds it,
  the same way the Docker socket arrives. Nothing points at it by default, because in the editor the extension
  forwards an agent of its own and sets `SSH_AUTH_SOCK` to that; in a `devcontainer exec` shell, which forwards
  none, `export SSH_AUTH_SOCK=/run/host-ssh-agent.sock` is the whole of it. No `--mount` of your own, so no
  recreating the container — which is what would leave it with no gitconfig at all, hence the repo-local
  identity above. An empty directory at that path means no agent was bound in, and there are two ways to get
  one: on a POSIX host, none was running when the container started — start one and restart the container. On
  a **native Windows host there will never be one**, because the Windows agent is the named pipe
  `\\.\pipe\openssh-ssh-agent` and a Linux container cannot be handed a named pipe as a unix socket; take the
  `pushInsteadOf` option above instead, or work from a VS Code terminal, where the extension forwards the
  Windows agent itself. (WSL2 is a POSIX host for this purpose and behaves like the first case.)

`GIT_CONFIG_GLOBAL=/dev/null` does not work around it: pre-commit strips `GIT_*` from the environment of the git
it runs, keeping only `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_*`/`GIT_CONFIG_VALUE_*`, and those can only add
configuration, not remove a rewrite. Note that this only bites on a hook repository that is not in
`~/.cache/pre-commit` yet — a new `rev:`, or a fresh cache volume. The four Poetry hooks are declared
`repo: local` in `dev-tools/pre-commit-config.yaml` precisely so that they need no repository at all.

### Verifying a commit landed

Do not infer success from the absence of an error. Confirm it:

```bash
git log -1 --stat        # the new commit and its file list
git status --short       # working tree state afterward
```

Check that the hook output actually shows hooks running (`Passed`/`Skipped` lines) rather than the whole run
being bypassed, and that the committed file set matches what you intended to stage.
