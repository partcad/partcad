# PartCAD

## Overview

This monorepo contains all open source software that forms the PartCAD ecosystem.

* [partcad](./partcad/AGENTS.md):

  The core logic that enables maintaining digital thread for manufacturable physical products.

* [partcad-cli](./partcad-cli/AGENTS.md):

  The CLI interface to most of `partcad` functionality.

* [partcad-service-json-rpc](./partcad-service-json-rpc/AGENTS.md):

  A JSON-RPC service (`partcad-json-rpc` executable) exposing `partcad` functionality with methods that mirror
  `partcad-cli`. By default it runs a per-workspace background **daemon** (served over a socket / Windows named
  pipe); it can also serve over stdin/stdout or HTTP. It is the default backend for `partcad-ide-vscode` and
  the backend for most `pc` commands, and the CLI manages it via `pc daemon start`/`stop`.

  The daemon owns the warm PartCAD context **and** the sandboxed Python runtimes that CAD wrappers execute in,
  so a client need not have a CAD environment at all. That is what decides whether a command runs in the client
  or on the daemon — see "Command boundary" in `partcad-cli/AGENTS.md`.

  It does **not** update PartCAD itself, and does not discover or stop daemons: those are
  `partcad_client`, run by the client. See `partcad-client` below.

* [partcad-utils](./partcad-utils/README.md):

  The lightweight pieces **every** component shares without a CAD-kernel dependency: logging, telemetry, user
  configuration — and the client/daemon rendezvous, `framing` and `workspace` (which socket serves which
  workspace, and whether anything is answering on it). The rendezvous lives here precisely because neither end
  owns it: a copy on each side is a copy that can disagree, and a disagreement is a client silently starting a
  second daemon.

* [partcad-client](./partcad-client/README.md):

  What a **client** does, and a daemon must not: discovering the daemon serving a workspace and connecting to
  it (`daemon`, `client`), and replacing this installation of PartCAD (`selfupdate`).

  All of it acts on **this machine**, from the process running out of it. A daemon can be remote, where
  "update PartCAD" would mean updating somebody else's installation and "stop the local daemons" somebody
  else's daemons; and a daemon that went looking for its neighbours would be racing every client on the
  machine. A client is one process acting on its own machine, which is what makes `pc upgrade` stopping every
  local daemon a sane thing to do rather than a distributed algorithm.

  `selfupdate` itself knows nothing even about that: a caller passes `before_install`, which `pc upgrade` uses
  to stop the local daemons and wait for them. `pc upgrade` (the host-level command; `pc update` refetches a
  package's imports and is unrelated) and the VS Code extension's "Update PartCAD" both end up here — the
  extension by running `pc upgrade` — as does the extension's daemon discovery, through `pc daemon start`.
  Nothing about daemons or upgrading is reimplemented in TypeScript.

* [partcad-ide-vscode](./partcad-ide-vscode/AGENTS.md):

  Visual Studio Code extension for navigating through objects in a `partcad` project and UI interface to some of `partcad` functionality. Hosts the `PartCAD Viewer`.

* [partcad-ide-client](./partcad-ide-client/AGENTS.md):

  The Python side of the socket protocol `partcad` uses to display shapes in the IDE's `PartCAD Viewer`. Lazily imported by `partcad`, installed by `partcad-ide-vscode`.

* [partcad-ide-standalone](./partcad-ide-standalone/AGENTS.md):

  The **PartCAD IDE**: a rebranded [VSCodium](https://vscodium.com/) build carrying the extension above, the
  extensions this repository recommends, and the standalone command line tools -- one application to download,
  for users who have no Python and no editor set up. It always opens in the PartCAD workbench. Installed with
  `install.sh --ide`.

* [partcad-cad-freecad](./partcad-cad-freecad/AGENTS.md):

  The `PartCAD` addon (workbench) for FreeCAD: browse packages, parts and assemblies as a hierarchy, set an
  object's parameters in a generated dialog, and import the result into the open document as a STEP file. Like
  `partcad-ide-vscode` it is a thin client of `partcad-service-json-rpc` (the standalone PyInstaller bundle),
  because FreeCAD's embedded Python cannot host `partcad` itself.

* [README.md](./README.md) and [docs](./docs/README.md):

  Human-friendly documentation.

## Development process

Full narrative guide (Docker/dev-container setup, PR merge criteria): `docs/source/contributing.rst`.
Component-specific commands: `partcad/AGENTS.md`, `partcad-cli/AGENTS.md`, `partcad-ide-vscode/AGENTS.md`,
`partcad-ide-client/AGENTS.md`, `partcad-cad-freecad/AGENTS.md`.

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
poetry install        # installs partcad + partcad-cli in editable mode
```

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
poetry run pytest partcad partcad-cli partcad-utils partcad-client partcad-service-json-rpc partcad-cad-freecad \
  partcad-ide-client \
  -x -p no:error-for-skips -p no:warnings --dist no                                        # unit tests (matches CI)
poetry run behave                                                                        # integration tests (./features)
```

CI fans these out over operating systems, and a pull request runs a reduced matrix: both Ubuntu 22.04 images
and the second macOS are dropped. The full matrix runs nightly, on a manual dispatch, on a push, and on a
pull request whose title or description contains `#deepTest`. `.github/actions/test-depth` is the one place
that decides; `docs/source/contributing.rst` explains it to contributors. Note that a push to `devel` runs no
matrix at all unless its head commit message starts with `Version updated` — the `set-matrix` job, and every
job that depends on it, is skipped otherwise.

Lint/format (Python): `black`, `flake8`, `isort` — configured in `pyproject.toml`.

### Packaging

Five artifacts ship from this repo: the Python wheels (`partcad`, `partcad-cli` on PyPI), the standalone PyInstaller
bundles for users who have no Python, the PartCAD IDE, which carries those bundles inside it, the VS Code extension's
`.vsix`, and the snap, which wraps the Linux bundle and is built but not published yet. Adding a runtime dependency,
an optional extra, or a file that is read at runtime can be invisible to the frozen bundle and break it while the
wheels stay fine — see `dev-tools/pyinstaller/README.md` before doing any of those. Note that the bundles fan out over
*OS versions* (`ubuntu-22.04-x86_64`, `macos-26-arm64`, …), and that the same platform list appears in three places
that nothing keeps in sync; the README says which, and which of them a pull request skips without `#deepTest`. The
`.vsix` is built once, on Linux, by `.github/workflows/nox.yml`, which `build.yml` and `deploy.yml` both call;
`partcad-ide-standalone/build.sh` runs the same `nox` session per platform, because the `bundled/libs` inside the
package holds compiled wheels. Changing `.vscode/extensions.json` changes what the IDE ships with — see
`partcad-ide-standalone/README.md`. The snap carries whatever the bundle carries, so it needs nothing extra of its
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

### Verifying a commit landed

Do not infer success from the absence of an error. Confirm it:

```bash
git log -1 --stat        # the new commit and its file list
git status --short       # working tree state afterward
```

Check that the hook output actually shows hooks running (`Passed`/`Skipped` lines) rather than the whole run
being bypassed, and that the committed file set matches what you intended to stage.
