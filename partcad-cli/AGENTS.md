# partcad-cli

CLI interface (`pc` / `partcad` commands) to most `partcad` core functionality. Source:
`./src/partcad_cli`. Tests: `./tests`. Part of the shared Poetry workspace rooted at the repo root — depends on
the `partcad` package in this monorepo (`../partcad`); run all commands below from the repo root unless noted.

`pc daemon start` / `pc daemon stop` manage the per-workspace background daemon from
[`partcad-service-json-rpc`](../partcad-service-json-rpc), through
[`partcad-client`](../partcad-client): `start` goes through
`partcad_client.client.start_daemon()` (forwarding the daemon-affecting globals —
`--offline`, `--force-update`, `--python-sandbox`, verbosity — which otherwise stop at the client's own
`user_config`), while `stop` calls `partcad_client.daemon.stop_daemon()`.

These two are also the VS Code extension's way in. It does not derive socket paths or probe liveness itself: it
runs `pc daemon start`, reads the endpoint from stdout, and connects — so there is one implementation of "where
is the daemon", not one per language.

## Command boundary

Command bodies are thin clients of that daemon (`click/service.py::run`) unless they cannot be. A command
belongs to the **daemon** when it reads or mutates the package graph, or when it drives a CAD wrapper — the
wrapper's Python runtime lives in the daemon's environment and may not exist on the client at all. That
includes commands with file arguments (`add`, `import`, `convert`): the client sends an absolute path, the
daemon rejects anything outside the package, and paths are printed relative to the package that owns them, so
the output never depends on a working directory. A package-mutating command *must* be a daemon client, or the
daemon's warm context keeps serving the pre-mutation package.

**`pc update` and `pc upgrade` sit on opposite sides of this line, which is why they are two commands and not
one command with a flag.** `pc update` refetches the packages a package imports — the package graph, so a thin
daemon client like any other. `pc upgrade` replaces this machine's copy of PartCAD
(`partcad_client.selfupdate`), which only the process running from it can do: a daemon can be remote,
where "upgrade PartCAD" would mean upgrading somebody else's installation. It stays within the boundary's
letter as well as its spirit — `selfupdate` lives in the deliberately cheap `partcad-client`, so the
command never imports the heavy `partcad`.

`pc upgrade` owns the daemon handling the upgrade needs, because `selfupdate` deliberately has none. Every
daemon on this machine is executing the files about to be replaced, so it stops **all** of them and waits
(`daemon.stop_all_daemons()`) through the `before_install` hook — after a newer version is confirmed, before
anything is written, so a no-op upgrade costs nobody their warm context. Doing that from a client is what keeps
it simple: one process acting on its own machine, rather than daemons policing each other. A survivor is
reported rather than fatal, because the new version is installed beside the old one and the old one is not
removed until the command exits. The VS Code extension's "Update PartCAD" runs `pc upgrade`, so the two cannot
drift apart.

A command stays **in-process** only when it operates on the client's own state, which does not cross the wire:
`init` (creates the workspace, before any package or context exists, and adds the `Render` command to the
repository's `.vscode/launch.json` — see `partcad/src/partcad/launch_config.py`; the daemon's `init` operation
does the same, so both entry points leave the same repository behind), `config` (prints the client's resolved
`user_config` with its `--threads-max`/`PC_*` overrides), `healthcheck` (diagnoses this host), and **all of
`pc system ...`** — `system status`, `system reset` and `system set telemetry ...` act on the machine the CLI
runs on, by definition: its internal state directory, its user configuration — and `upgrade`, which replaces
that machine's installation. Still unmigrated: `supply/*`,
`add sketch`, `add dep`.

`pc daemon ...` is the other side of that pair, command for command: `daemon start|stop` manage the process,
while **`daemon status`**, **`daemon reset`** and **`daemon set telemetry ...`** are the daemon-side
counterparts of the `pc system` commands of the same name — they report and change the daemon's own internal
state directory and configuration, not the client's. The two coincide today, because the daemon runs on the
same machine; they will not once a daemon can be remote, which is why both halves exist. `daemon reset` clears
the daemon's state directory and the warm contexts that reference it. It runs unconditionally, because the caller has already decided and a
background daemon has nobody to ask for confirmation; a destructive confirmation, when one is wanted, belongs
in the client, before the call. (The daemon and the CLI share a machine today, so the two state directories
coincide; they will not once a daemon can be remote, which is why the commands are separate. `daemon reset`
carries a TODO to gate it behind access control before that happens.)

PartCAD **never prompts** for anything mid-operation. Credentials for private Git dependencies are configured
upfront under `git.auth` in the user configuration, and `GitCallbacks` fails with a message naming that setting
when they are missing — a prompt inside a background daemon or a CI job is a hang, not a question.

Both halves of this split are enforced by `tests/unit/test_command_boundary.py`, which also checks that every
method name a command sends exists in the daemon's registry. The in-process and unmigrated lists live at the
top of that file; update them there when a command intentionally moves.

## Setup

All commands on this page run **inside the dev container**, not on the host — see "Where commands run" in the
root [AGENTS.md](../AGENTS.md) for how to enter it. Dependencies are already installed in the image; re-run
`poetry install` only after changing `pyproject.toml`. The virtualenv is not auto-activated, so prefix the
commands below with `poetry run` (e.g. `poetry run pytest ...`, `poetry run pc ...`).

```bash
poetry install   # from repo root; installs partcad-cli (and partcad) in editable mode
```

## Test and validate changes

Two validation steps are required for any change under `partcad-cli/` — both must pass, unit tests alone are
not sufficient because CI also gates on the example run:

1. Unit tests:

   ```bash
   pytest partcad-cli -x -p no:error-for-skips -p no:warnings --dist no   # matches CI (test-pytest job)
   ```

2. End-to-end CLI validation against the example projects (matches CI's `test-examples-partcad` job in
   `.github/workflows/test.yml`):

   ```bash
   cd examples
   pc list all -r //pub/examples/partcad
   pc test -r --package //pub/examples/partcad
   pc render -r --package //pub/examples/partcad
   ```

   If `pc`/`partcad` isn't resolvable even under `poetry run`, run the module directly instead:
   `poetry run python -m partcad_cli.click.command --no-ansi <same args>`.

## Manual CLI exercise

Under `poetry run`, the CLI is available as `pc` or `partcad`:

```bash
pc version
pc list all -r //pub/examples/partcad   # from ./examples, or any dir with a partcad.yaml
```

## Lint / format

```bash
black --check partcad-cli
flake8 partcad-cli
isort --check partcad-cli
```

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
