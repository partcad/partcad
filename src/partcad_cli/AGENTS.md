# partcad-cli

CLI interface (`pc` / `partcad` commands) to most `partcad` core functionality. Source:
`./src/partcad_cli`. Tests: `./tests/partcad_cli`. It is one of the packages inside the single `partcad` wheel,
not a distribution of its own; run all commands below from the repo root unless noted.

`pc daemon start` / `pc daemon stop` manage the per-workspace background daemon from
[`partcad_service_json_rpc`](../partcad_service_json_rpc), through
[`partcad_client`](../partcad_client): `start` goes through
`partcad_client.client.start_daemon()` (forwarding the daemon-affecting globals —
`--offline`, `--force-update`, `--python-sandbox` when one was actually chosen, verbosity — which otherwise stop
at the client's own `user_config`), while `stop` calls `partcad_client.daemon.stop_daemon()`. `start` asks for a
daemon started *with those settings*: one already running with others restarts (`daemon.settings`, see
`partcad_service_json_rpc/config_restart.py`) rather than being reused with the flags dropped. Every other
command takes whatever daemon is running, since it sends its own configuration with each request.

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
letter as well as its spirit — `selfupdate` lives in the deliberately cheap `partcad_client`, so the
command never imports the heavy `partcad`.

`pc upgrade` owns the daemon handling the upgrade needs, because `selfupdate` deliberately has none. Every
daemon on this machine is executing the files about to be replaced, so it stops **all** of them and waits
(`daemon.stop_all_daemons()`) through the `before_install` hook — after a newer version is confirmed, before
anything is written, so a no-op upgrade costs nobody their warm context. Doing that from a client is what keeps
it simple: one process acting on its own machine, rather than daemons policing each other. A survivor is
reported rather than fatal, because the new version is installed beside the old one and the old one is not
removed until the command exits. The VS Code extension's "Update PartCAD" runs `pc upgrade`, so the two cannot
drift apart.

**`pc cae` is a daemon command, and the one thing about it that is not is the exit code.** An analysis reads
the package graph and drives a CAD wrapper, which puts it squarely on the daemon's side; what stays in the
client is that `pc cae fea` exits non-zero when the analysis produced a finding, so it can be used as a gate
in a script. Both subcommands are the same operation with the analysis as an argument -- `click/analysis.py`
holds the options and the body, the way `click/viewport.py` holds the three that `pc render` and
`pc adhoc render` share, so the two commands are a name and a docstring each and cannot drift apart.

**`pc cam` is a daemon command too, and it is the one that is package-level.** A route reads the package graph
and drives a CAD wrapper, like an analysis. What differs is what "no argument" means: `pc cae fea` is asked of
one part, while `pc cam` with nothing named produces a route for every sketch and part of the package that
declares a `cam:` section -- so the enumeration lives on the daemon (`Project.routable_shapes_async()`), and
what stays in the client is the exit code and `--json`. It exits non-zero if any object it was *asked about*
produced no route, and reports every one of them rather than stopping at the first: a route is a file, and an
object whose section is wrong must not cost the other nineteen theirs.

**`pc filter` is a daemon command with one argument that is resolved here, and the reason is where the file
is.** Writing a declaration puts it squarely on the daemon's side, like every other package-mutating command --
a client doing it itself would leave the warm context serving the package as it was before. But the
`<filter-file|filter-expression>` argument is a *filename first*, and the file is on the machine the user typed
the command on: a daemon can be remote, where the path names nothing, or names something else. So
`click/link_filter.py` resolves it here and sends the mask (a small mapping of link names), never the path --
and a mistyped filename costs a message rather than a round trip. The same module adds `--filter` to
`pc render` and `pc export`, so the three commands cannot come to read the argument differently; what a filter
*means* is `partcad_utils.assy_filter`, read by both ends.

**`pc lint` sits on both sides of the line, one mode each.** `pc lint [-P/-r]` checks a *package*: which
packages, resolved how, with which files, is the package graph, so it is a thin daemon client like any other.
`pc lint --file` checks the *files named on the command line*, in this process: an ASSY file and a
`partcad.yaml` are both Jinja2 templates rendered to YAML and matched against a schema, which needs no package
graph, no CAD runtime and no context — and with `--stdin` the content is a buffer an editor has not saved,
which the daemon cannot see at all. There is deliberately no RPC method for it: sending it would ship the
client's own file across a wire to have it read back, and would leave the editor silent exactly when the
package fails to load *because* of that file — which for a `partcad.yaml` is every time it is wrong. The
checker (`partcad_client.lint`, over `partcad_utils.assy_lint`) is the same one the daemon runs over a package,
so an editor and CI cannot disagree. The VS Code extension runs `pc lint --file`, so the two cannot drift apart
either. `--schema` picks the flavor of an ASSY file; a `partcad.yaml` has none — nothing points at a package
configuration — so it is ignored for one, and the detection is not even run.

**`pc ide open` is on the in-process side for a stronger version of the same reason.** Opening a file in a
third-party CAD application puts a window on a screen, and the only screen a command can put one on is the one
in front of the user who ran it: a daemon can be remote, where that window would appear on somebody else's
desk, on a machine that may have no display at all -- and the path on the command line names a file only the
client has. It needs no package graph and no context either, so there is deliberately no RPC
method for *opening a file* and none may be added. The application, the container PartCAD keeps for one that is
not installed, and the X forwarding into it are `partcad_client.external`, so the command never imports the heavy
`partcad`. Taking a path rather than a `<package>:<part>` name follows from the same rule: resolving a name is
a package-graph question, which is exactly the round trip this command does not make. The VS Code extension's
"Open in..." context menu runs `pc ide open --json`, so the two cannot drift apart.

**One step inside it does cross the wire, and it is the exception that states the rule.** Two applications read
one thing only: Blender reads meshes, and MuJoCo reads MJCF. A part that is not already a mesh, or a scene that
is not already an MJCF model, has to be converted before it is handed over -- and both conversions drive a CAD
wrapper, whose sandboxed Python runtime lives in the daemon's environment and
may not exist on the client at all. So `pc ide open --with blender` and `pc ide open --with mujoco` send
`adhoc.convert`, the same method
`pc adhoc convert` sends, on the same absolute paths, with `kind` saying whether a part or a scene is being
converted: file in, file out, `needs_context=False`, nothing left on
the daemon to go stale, and no new method in the registry. The same call runs the other way when the
application closes and the converted copy was edited -- back into the object's own format, over its source.
The window still opens here. Which types are meshes,
and which are scene descriptions,
is `partcad_client.object_types` -- an inlined copy of PartCAD's tables, so the client stays cheap to import,
with `tests/partcad/unit/test_client_object_types.py` failing when the copy drifts.

`pc ide open` makes one other daemon call, `open.tools`, and for the same kind of reason: **which** applications
exist is a fact about the packages a workspace imports, and only the daemon has the package graph. PartCAD's
own five are read straight off disk out of the wheel, so the call is made only where a `partcad.yaml` is
actually found — a `pc ide open` outside a workspace starts no daemon and creates no context. The daemon says
which applications there are; it never opens one, and there is still no method that opens a file.

`pc ide install` and `pc ide open <directory>` are in-process too, and make **no** daemon call either: one
installs the PartCAD extension into an editor on this machine, the other opens a folder as that editor's
workspace, in the PartCAD workbench (`partcad_client.ide`). Both change this machine -- its editor, its screen --
which a daemon that can be remote must never be asked to do, for the reason `pc upgrade` is a client command.
The workbench half needs the extension's cooperation, because an editor's command line can open a folder but not
run a command in the window it opens: the CLI leaves a request file under `~/.partcad/ide/requests/` before
opening the folder, and `ide/vscode/src/workbenchRequest.ts` takes it. The file's layout is the contract between
the two and is written down in both.

`pc ide view`'s tab flags (`--design-3d`, `--analysis-fea`, ...) are generated from
`partcad_ide_client.protocol.VIEWER_TABS`, one per tab, and the tab goes to the daemon with `inspect.object` and
from there onto the show itself (`KEY_TAB`) -- not as a message of its own from the client: the show is what
decides which tabs apply, and two IDE windows sharing the viewer port share it by connection, so a second
message could reach the other window.

`pc ide state` is in-process for the same reason and makes **no** daemon call at all: it asks the PartCAD IDE
on this machine what it is showing, over the socket the IDE already listens on for `show`
(`partcad_ide_client.state`). The IDE is wherever the person is; a daemon can be remote.

Those two are the only daemon calls an in-process command makes, and `IN_PROCESS_DAEMON_CALLS` in
`tests/partcad_cli/unit/test_command_boundary.py` is where it is written down -- one method at a time, so
widening it is a decision somebody makes on purpose.

A command stays **in-process** only when it operates on the client's own state, which does not cross the wire:
`init` (creates the workspace, before any package or context exists, and adds the `Render` command to the
repository's `.vscode/launch.json` — see `src/partcad/launch_config.py`; the daemon's `init` operation
does the same, so both entry points leave the same repository behind), `config` (prints the client's resolved
`user_config` with its `--threads-max`/`PC_*` overrides), `healthcheck` (diagnoses this host), and **all of
`pc system ...`** — `system status`, `system reset` and `system set telemetry ...` act on the machine the CLI
runs on, by definition: its internal state directory, its user configuration — and `upgrade`, which replaces
that machine's installation. Still unmigrated: `supply/*`,
`add sketch`, `add dep`.

`pc daemon ...` is the other side of that pair, command for command: `daemon start|stop` manage the process,
while **`daemon status`** (with its `config` and `env` subcommands), **`daemon reset`** and **`daemon set
telemetry ...`** are the daemon-side counterparts of the `pc system` commands of the same name — they report
and change the daemon's own internal state directory and configuration, not the client's. The two coincide today, because the daemon runs on the
same machine; they will not once a daemon can be remote, which is why both halves exist. `daemon reset` clears
the daemon's state directory and the warm contexts that reference it. It runs unconditionally, because the caller has already decided and a
background daemon has nobody to ask for confirmation; a destructive confirmation, when one is wanted, belongs
in the client, before the call. (The daemon and the CLI share a machine today, so the two state directories
coincide; they will not once a daemon can be remote, which is why the commands are separate. `daemon reset`
carries a TODO to gate it behind access control before that happens.)

## `...`: the package name that means "and everything below it"

`//pub/examples...` is that package and every package below it — the same request `-r` makes, written where
the package is named. It works on an object name too, in front of the `:`: `pc render ...:bolt` is every bolt
from here down, and `//pub/examples...:bolt` is every bolt of that subtree whatever `-P` said. `-r` is kept
and still means what it meant; the documentation is written with `...`.

**A command does not parse it.** The package and object arguments go over the wire as the user typed them, and
`operations._request()` on the daemon reads both spellings into one answer — see "`package`, `object` and the
`...` suffix" in [`partcad_service_json_rpc/AGENTS.md`](../partcad_service_json_rpc/AGENTS.md). There are three
clients of that daemon, and a syntax each of them parsed for itself is a syntax they would each get slightly
wrong. So adding the suffix to a command is a `--help` string here and, where the command has none yet, a
`recursive` branch there.

Two commands keep a `-r` that is **not** this: `pc supply find` and `pc supply quote`, where `-r` means "break
every assembly down to its parts" and has nothing to do with the package graph. Do not fold those in.

The client's whenever the client sends one — as of the moment the command ran. `service.py::run` resolves the
CLI's own `user_config` (file + `PC_*` environment + command line) and sends a copy of it,
`UserConfig.to_dict()`, with every `context.create`; the daemon rebuilds it with `UserConfig.from_dict()` and
builds the context from *that*, never from `pc.user_config`. A client that sends no `userConfig` leaves the
daemon on its own configuration instead (see below).

This is not a nicety. The daemon is warm and shared per workspace, so its own configuration is whatever the
environment held when something first started it — possibly days ago, possibly from a VS Code window. Reading
options there would silently drop every `--devel-index`, `--force-update`, `--offline` and `PC_*` the command
was actually invoked with, and there is no launch argument that can fix it because the daemon is usually
already running. Adding a user-configuration option therefore means adding its key to `OPTION_KEYS` (or
`SECTION_PATHS`) in `partcad_utils/user_config.py`; an option missing from those lists is one the daemon keeps
resolving from its own environment.

The daemon keeps the configuration each warm context was built from (`session.context_user_configs`) and
rebuilds the context when a caller's differs, because a package graph resolved under one configuration cannot
answer for another. A client that sends no configuration — the VS Code extension, which configures the daemon
once through its launch arguments — keeps getting the daemon's own.

**`pc system status` and `pc daemon status` each have three answers, and the pair of them is how you tell the
two sides apart.** Bare, each reports the internal data on its own machine. `... status config` reports the
configuration that side resolved, and `... status env` the `PC_*` variables that side's process was started
with. All six print through `partcad_utils.config_report`, which is where the redaction rules live: a
configuration option that is a secret is named there one by one, and an environment variable is scrubbed when
its name carries an auth word between underscores (`TOKEN`, `KEY`, `SECRET`, `PASSWORD`, `CREDENTIAL`, `AUTH`
— not `DSN`, and the module says why). Two options are reported by *shape* rather than by value, because
"is it set" is the wrong answer for both: `git.auth` keeps the host, username and key path that say *which*
credential and drops the password and passphrase, and the `user` section keeps only which of its fields are
configured — it is personally identifiable information in its entirety, and `PIIConfig` fills in two of its
keys unconditionally, so a truthiness test would claim a name and an address were on file for a machine that
has never been told any. Two copies of a redaction rule are one copy that stops redacting, which
is why the daemon does not have its own; the daemon also scrubs before logging, so a value the client has no
business holding never reaches the wire.

The daemon's `config` answer is deliberately *not* the configuration your command ran under — that one travels
with every `context.create`, as this section says above. It is the daemon's own, resolved from its own
environment whenever something first started it, which is what a client sending no configuration gets. The
`env` answer is the one thing the client cannot reconstruct at all — on POSIX. On Windows `connect()` serves
the request from a one-shot stdio child of the client rather than from the named-pipe daemon, so both answers
describe a process that inherited the caller's environment; the command still reports whatever process did the
work, which is what it promises. `tests/partcad_cli/unit/test_status.py` asserts each half on its own platform,
having first asserted the POSIX half on both and failed on Windows for exactly that reason.

PartCAD **never prompts** for anything mid-operation. Credentials for private Git dependencies are configured
upfront under `git.auth` in the user configuration, and `GitCallbacks` fails with a message naming that setting
when they are missing — a prompt inside a background daemon or a CI job is a hang, not a question. `git.auth`
travels in the configuration copy for the same reason as everything else, and the git helpers take the
context's configuration rather than the process-wide singleton so the copy is what actually authenticates.

Both halves of this split are enforced by `tests/unit/test_command_boundary.py`, which also checks that every
method name a command sends exists in the daemon's registry. The in-process and unmigrated lists live at the
top of that file; update them there when a command intentionally moves.

## Setup

All commands on this page run **inside the dev container**, not on the host — see "Where commands run" in the
root [AGENTS.md](../../AGENTS.md) for how to enter it. Dependencies are already installed in the image; re-run
`poetry install` only after changing `pyproject.toml`. The virtualenv is not auto-activated, so prefix the
commands below with `poetry run` (e.g. `poetry run pytest ...`, `poetry run pc ...`).

```bash
poetry install   # from repo root; installs the whole `partcad` wheel in editable mode
```

## Test and validate changes

Two validation steps are required for any change under `src/partcad_cli/` — both must pass, unit tests alone
are not sufficient because CI also gates on the example run:

1. Unit tests:

   ```bash
   pytest tests/partcad_cli -x -p no:error-for-skips -p no:warnings --dist no   # matches CI (test-pytest job)
   ```

2. End-to-end CLI validation against the example projects (matches CI's `test-examples-partcad` job in
   `.github/workflows/test.yml`):

   ```bash
   cd examples
   pc list all -r --fast-only //pub/examples/partcad
   pc test -r --fast-only --package //pub/examples/partcad
   pc render -r --fast-only --package //pub/examples/partcad
   ```

   `--fast-only` is what CI passes on every recursive run over `//pub`: it leaves out each assembly and scene
   that declares a `timeout:`, the ones its package says are slow. Drop it when the change is about those.

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
black --check src/partcad_cli tests/partcad_cli
flake8 src/partcad_cli tests/partcad_cli
isort --check --filter-files src/partcad_cli tests/partcad_cli
```

All three gate — each is a `pre-commit` hook and a `Lint (...)` job in `test.yml`, and the tree satisfies
all three, so a finding from any of them is yours. See the root [AGENTS.md](../../AGENTS.md) for the two flags that
are load-bearing (`--filter-files`, and the `Flake8-pyproject` plugin without which flake8 reads no config
at all).

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
