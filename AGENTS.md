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
  command — on this machine, with this machine's file, and never over the wire; there is no RPC method for it
  and none may be added. A machine with no local installation can run the application in a container PartCAD
  keeps for it, named after the tool (`partcad-freecad`), with the workspace and the daemon's socket mounted
  at the paths they have here and the host's X display forwarded into it.

* [src/partcad_ide_client](./src/partcad_ide_client/AGENTS.md):

  The Python side of the socket protocol `partcad` uses to display shapes in the IDE's `PartCAD Viewer`. Lazily
  imported by `partcad.viewer`, and by nothing else.

### Everything else

* [ide/vscode](./ide/vscode/AGENTS.md):

  Visual Studio Code extension for navigating through objects in a `partcad` project and UI interface to some
  of `partcad` functionality. Hosts the `PartCAD Viewer`. It is a **JSON-RPC client and nothing else** — it
  talks to `partcad-json-rpc` and contains no Python of its own. Published as `PartCAD.partcad`.

* [ide/vscode-shim](./ide/vscode-shim/AGENTS.md):

  The `OpenVMP.partcad` marketplace entry, as a transition shim: no code, one `extensionDependencies` on
  `PartCAD.partcad`. The extension above used to be published by the `OpenVMP` publisher, and a publisher is
  half of an extension's identity — the new entry is a *different* extension as far as the marketplace and the
  editor are concerned, and nothing carries an installation across. So the old entry is not abandoned; it is
  replaced by a package that pulls the new one in, and an existing installation updates into it. Same shape as
  `shim/` below, and temporary in the same way. Do not give it a `main` or a `contributes`: both extensions are
  installed at once afterwards, and anything it contributed would be contributed twice.

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

* [shim/](./shim/pyproject.toml):

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

CI fans these out over operating systems, and a pull request runs a reduced matrix: both Ubuntu 22.04 images
and the second macOS are dropped. The full matrix runs nightly, on a manual dispatch, on a push, and on a
pull request whose title or description contains `#deepTest`. `.github/actions/test-depth` is the one place
that decides; `docs/source/contributing.rst` explains it to contributors. Note that a push to `devel` runs no
matrix at all unless its head commit message starts with `Version updated` — the `set-matrix` job, and every
job that depends on it, is skipped otherwise.

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

Five artifacts ship from this repo: **one Python wheel** (`partcad`, carrying all six packages and all three
entry points, with a `partcad-cli` shim published beside it from `shim/` so the older install instruction keeps
working), the standalone PyInstaller bundles for users who have no Python, the PartCAD IDE, which carries those
bundles inside it, the VS Code extension's `.vsix` (with the `ide/vscode-shim` `.vsix` published beside it, for
the same reason the wheel has one), and the snap, which wraps the Linux bundle and is built but
not published yet.

There used to be five wheels pinning each other at `==`. Do not add a second distribution back: within one
distribution a pin is an import, and two distributions owning one import name break each other on uninstall
without pip noticing. Adding a runtime dependency, an optional extra, or a file that is read at runtime can be
invisible to the frozen bundle and break it while the wheel stays fine — see `dev-tools/pyinstaller/README.md`
before doing any of those. Note that the bundles fan out over
*OS versions* (`ubuntu-22.04-x86_64`, `macos-26-arm64`, …), and that the same platform list appears in three places
that nothing keeps in sync; the README says which, and which of them a pull request skips without `#deepTest`. The
`.vsix` is built once by `.github/workflows/vsix.yml`, which `build.yml` and `deploy.yml` both call, and
`ide/standalone/build.sh` runs the same `npm run vsce-package` for the copy inside the IDE. One build
serves every platform: the extension is a JSON-RPC client with no Python and no compiled content in it. The
same workflow packages the transition shim beside it, under the extension's version — which the shim does not
state anywhere, but reads at package time, so the two cannot drift. A shim older than the entry it replaces is
one the marketplace never delivers, and a second literal to bump is how that happens. Changing `.vscode/extensions.json` changes what the IDE ships with — see
`ide/standalone/README.md`. The snap carries whatever the bundle carries, so it needs nothing extra of its
own; `dev-tools/snap/README.md` covers what is specific to it (confinement, aliases, the base, its state directory).

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
* Or forward the SSH agent the way the GPG one is forwarded above,
  `--mount "type=bind,source=$SSH_AUTH_SOCK,target=/run/host-ssh-agent.sock"`, and
  `export SSH_AUTH_SOCK=/run/host-ssh-agent.sock` in the container. Adding a mount means recreating the
  container, and recreating it with the CLI is what leaves it with no gitconfig at all — hence the repo-local
  identity above.

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
