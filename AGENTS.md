# PartCAD

## Overview

This monorepo contains all open source software that forms the PartCAD ecosystem.

* [partcad](./partcad/AGENTS.md):

  The core logic that enables maintaining digital thread for manufacturable physical products.

* [partcad-cli](./partcad-cli/AGENTS.md):

  The CLI interface to most of `partcad` functionality.

* [partcad-ide-vscode](./partcad-ide-vscode/AGENTS.md):

  Visual Studio Code extension for navigating through objects in a `partcad` project and UI interface to some of `partcad` functionality.

* [README.md](./README.md) and [docs](./docs/README.md):

  Human-friendly documentation.

## Development process

Full narrative guide (Docker/dev-container setup, PR merge criteria): `docs/source/contributing.rst`.
Component-specific commands: `partcad/AGENTS.md`, `partcad-cli/AGENTS.md`, `partcad-ide-vscode/AGENTS.md`.

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
poetry run pytest partcad partcad-cli -x -p no:error-for-skips -p no:warnings --dist no  # unit tests (matches CI)
poetry run behave                                                                        # integration tests (./features)
```

`behave` gives each scenario a private `$HOME`, so it would start with a cold PartCAD cache every time. The suite
avoids that by building one internal state directory up front — the `//pub` clone plus the conda sandbox — and
copying it per scenario via `PC_INTERNAL_STATE_DIR`. The first run builds it (~10 min, ~3.5 GB); later runs reuse
it. Build or rebuild it explicitly with `poetry run python -m features.seed`, relocate it with
`PARTCAD_BEHAVE_DIR`, and delete that directory to force a rebuild. A scenario that needs a cold cache — one
asserting that `pc install` clones, or that the state directory is at the default `$HOME/.partcad` — must be
tagged `@cold-state`. See `features/seed.py`.

The build resumes rather than starting over, which is what lets CI cache the part worth caching: the object
cache and `.seed-exports.json`, the manifest saying which exports are already covered. That is ~2 MB standing in
for ~7.5 min of exports. The conda sandbox (~2.3 GB, ~70s to rebuild) and the git clones (~1.2 GB, ~90s) are
deliberately **not** cached — GitHub allows 10 GB of cache per repository and this repo already uses ~8.9 GB of
it for conda and pip, so anything cached here evicts those and makes every other job slower. `.seeded` is not
cached either: restored without the sandbox, the build would be skipped and every scenario would build a sandbox
inside its own throwaway copy.

Seeding is bounded, because it shares a CI job's deadline with the suite it exists to speed up — unbounded, it took 32 of a Windows job's 60 minutes and the suite was killed. The whole of it gets `PARTCAD_BEHAVE_SEED_BUDGET` seconds (default 1500) and the export phase gets `PARTCAD_BEHAVE_EXPORT_BUDGET` (default 600); exports left over are deferred, not dropped, and a later run picks them up from the manifest. If the budget runs out before the seed is usable, the suite runs unseeded rather than the job failing.

CI parallelises the suite by sharding it across jobs (`BEHAVE_SHARDS` in `test.yml`, split by
`dev-tools/behave_shard.py`), so each job runs plain serial `behave` over a slice of the feature files. Locally,
`.devcontainer/behave_hook.sh` instead uses `behavex` to parallelise within one machine. `behavex` does **not**
read the `tags` setting from `behave.ini`, so pass the exclusions yourself or `@ai` scenarios silently start
running: `poetry run behavex features -t '~@ai' --parallel-processes=4 --parallel-scheme=feature`.

Lint/format (Python): `black`, `flake8`, `isort` — configured in `pyproject.toml`.

### Packaging

Two artifacts ship from this repo: the Python wheels (`partcad`, `partcad-cli` on PyPI) and the standalone
PyInstaller bundles for users who have no Python. Adding a runtime dependency, an optional extra, or a file
that is read at runtime can be invisible to the frozen bundle and break it while the wheels stay fine — see
`dev-tools/pyinstaller/README.md` before doing any of those.

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
