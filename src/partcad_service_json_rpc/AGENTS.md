# partcad_service_json_rpc

JSON-RPC service interface to `partcad`. Ships the `partcad-json-rpc` executable, which exposes PartCAD over a
JSON-RPC 2.0 interface whose methods mirror the CLI's actions. Source: `./src/partcad_service_json_rpc`.
Tests: `./tests/partcad_service_json_rpc`. It is one of the packages inside the single `partcad` wheel; run all
commands below from the repo root unless noted.

By default the service runs a per-workspace **daemon**, served over an AF_UNIX socket at
`~/.partcad/workspaces/<hash>/socket` (a named pipe on Windows). `--stdio` serves one foreground connection over
stdin/stdout, and `--http [ADDR]` serves JSON-RPC at `POST /rpc` with notifications over Server-Sent Events at
`GET /events` (no auth yet). The `ide/vscode` extension and the `pc` CLI are both clients of the daemon.

The daemon owns two things its clients do not, and both decide what belongs on which side of the wire:

1. **A warm PartCAD context** — the loaded package graph, so a client does not pay `import partcad` (~1.6s) and
   a package reload per command. It also means the daemon's copy of a package is the *authoritative* one: a
   package-mutating command (`add`, `import`) must be a daemon client and evict the context it changed
   (`_invalidate_context`). A `partcad.yaml` edited by hand is caught on the way in instead: `_ctx`, which every
   operation on a context goes through, calls `Context.reload_changed_packages()` for the packages the request is
   about (`_config_check_targets`) and everything they declare as dependencies, transitively. A package whose
   configuration changed size or modification time is reloaded with the packages underneath it -- not the whole
   context -- and each package is compared at most once per `CONFIG_CHECK_INTERVAL` (15 s). A package reached
   without being declared is not checked; that is accepted. An edit to a file a part is built from reloads
   nothing: a part hashes its files once, so a warm context that has already keyed it keeps that key until its
   package is reloaded or the daemon is restarted.
   A **failed** load is not kept either, for a reason of its own: the errors saying why are logged while the
   context is being built, so a cached one would be a single command reporting "configuration file is not
   found" and exiting non-zero followed by any number of commands answering with nothing and exiting zero --
   one request that "fails" once and "works" from then on, and two spellings of it (`...` and `./...`) that
   look like one of them is broken when what differs is which was typed first. So `context.create` drops a
   context whose root package did not load and reads it again, which is also what makes a `partcad.yaml`
   written after that first command visible without stopping the daemon. It costs nothing, because a root that
   did not load imported no dependencies. That covers the root and only the root: an error logged while some
   *other* package of the graph loaded (an unreachable dependency, an object a plugin could not enumerate) is
   still reported once, by whichever command paid for the load, so the same command still exits non-zero then
   zero. Remembering those with the packages they belong to, and re-reporting them for every answer that
   includes one, is the rest of this problem and is not done yet.
   The context is warm across connections, which is why `activate` **reloads** `partcad` rather than importing
   it: `Session.load_partcad` drops `partcad` and `partcad.*` from `sys.modules` (along with `partcad_cli*` and
   `partcad_ide_client*`, but never this package, whose session is doing the dropping) and imports again,
   so one package load's global state does not leak into the next. That makes reload-safety a property
   `partcad` has to have, and one nothing else exercises — the *first* client of a daemon takes the import
   path and every later one takes the reload path. It broke exactly that way: `partcad/__init__.py` aliased
   the `partcad_utils` modules with `globals()[name] = module`, and since `partcad.globals` is a submodule that
   `from .globals import ...` binds onto the package, the reload re-ran that line against a namespace where
   `globals` was no longer the builtin. Every window after the first got `'module' object is not callable`.
   `tests/partcad_service_json_rpc/test_partcad_reload.py` holds the invariant now. Keep module-level code in
   `partcad/__init__.py` free of anything that a second execution against the first execution's namespace would
   read differently.

2. **The runtimes** — the sandboxed Python environments (`ctx.get_python_runtime()`) that every CAD wrapper runs
   in: `wrapper_import_assy` for STEP assemblies, the conversion wrappers behind `convert`/`--target-format`,
   the render/export wrappers. Those runtimes belong to the daemon's environment and **need not exist on the
   client side at all** — a thin client cannot do this work itself even in principle. Any command that drives a
   wrapper is therefore a daemon command.

A command stays in the client only when its inputs and outputs are the *client's own* state, which cannot cross
the wire: `init` (bootstraps a workspace before any package exists), `config` (prints the client's resolved
`user_config`, including its `--threads-max`/`PC_*` overrides), `healthcheck` (diagnoses the client host),
`daemon start|stop`, `system status ...` and `system telemetry clear|info`. File paths are not a reason to
stay local: a client sends an absolute path, `Project._validate_path` rejects anything outside the package, and
`Project.rel_path` reports it back relative to the package that owns it — so the output does not depend on
anyone's working directory.

`system status`, `system status config` and `system status env` each have a daemon-side twin — `daemon.status`,
`daemon.status.config`, `daemon.status.env` — because the answers differ: the daemon's internal state
directory, the configuration it resolved from its *own* environment when something first started it, and that
environment itself, which is the one thing a client cannot reconstruct. None of them is the configuration a
caller's command runs under; that travels with every `context.create` and is rebuilt per request. All three
print through `partcad_utils.config_report`, which is also where the redaction lives — the daemon scrubs a
credential before logging it, so a value the client has no business holding never reaches the wire.

Building the context from the caller's configuration covers whatever the context reads. It does not cover what
the **process** owns, and an option that sizes something process-wide has to be re-applied per request instead.
`threadsMax` is the one so far: the sandbox process slots (`partcad.sandbox_lock`) are the daemon's, sized at
import from its own configuration, and were deaf to every `PC_THREADS_MAX` and `--threads-max` sent afterwards.
So `context.create` calls `pc.sandbox_lock.follow()` with the configuration it is about to build from, and `_ctx`
calls it again with the context's own -- requests are served one at a time, and another client's may have
moved the slots in between. A request that names no context at all carries no configuration either, and is
served with the slots the last one left. `--http` is the exception to "one at a time": it dispatches requests
concurrently, so there the ceiling is the one the most recent request set. The thread pools (`partcad.sync_threads`) are not resized: they are not
a strict limit, and nothing about them needs to follow the configuration -- nested work cannot starve a pool of
any size (see `partcad.sync_threads`), and what does decide how much of the machine a command takes, the sandbox
processes, already follows every request.

## Layout

- `core/` — transport-agnostic operations shared with the legacy VS Code LSP server: `session.py` (PartCAD
  state + log streaming), `events.py` (the event emitter and the event-name contract),
  `operations.py` (the operation functions).
- `rpc/` — `dispatcher.py` (JSON-RPC 2.0 parse/dispatch/error mapping) and `methods.py` (the CLI-shaped method
  registry; `rpc.discover` returns the catalog).
- `transport/` — `stdio.py`, `socket_server.py` (threaded AF_UNIX server, the daemon's transport), `http.py`
  (optional HTTP+SSE), and what the first two and the pipe server share: `dispatch.py` (the one dispatch thread,
  and each connection's requests) and `writer.py` (each connection's writer, and when it gives up on a client). The `Content-Length` codec they frame with is `partcad_utils.framing`, which the clients
  read too; see "Files cross as attachments" below.

  Requests are served one at a time, by one thread (`transport/dispatch.py`), by the socket server, the pipe
  server and `--stdio` alike: the session is every client's and is not safe to use from two threads (one emitter
  sink, contexts reloaded in place, `activate` reloading `partcad`). Connections take **turns** -- the next
  request served is the oldest of the next connection in line, not the oldest of all -- so a `pc` command typed
  while the editor has five tabs' requests queued waits for one of them, not five, and a connection's own
  requests are served in the order it sent them.

  **Reading, serving and writing are apart.** Each connection has a reader that only reads, so a request is
  queued rather than read only once the last one is done, and a writer of its own (`transport/writer.py`; the
  pipe's `PipeWriter`) that every response and notification is queued to -- so serving a request never waits
  on its client, and a client that stops reading (an extension host stopped in a debugger, a terminal paused
  with Ctrl-S) delays nobody else. That used to be the opposite: events were written by the thread serving the
  request, holding the dispatch lock, and one full socket stalled the daemon for everyone. **A client that stops
  reading is dropped, not waited for and not buffered for without limit**: after `WRITE_TIMEOUT` (60 s) in which
  it took nothing it was sent, or once more than `MAX_BACKLOG` (256 MB) is queued behind the frame being written.
  It sees its connection close -- the editor reconnects, `pc` says the service went away -- and its requests are
  cancelled. The writer docstring says why each bound is what it is. A request's events are queued before its
  answer, so they still arrive first; `--http` encodes answers and events on worker threads rather than on its
  event loop, and drops an event stream by the same policy.

  **`$/cancelRequest` is honoured** (`core/cancellation.py`), which is what `vscode-jsonrpc` sends when the token a
  request was made with is cancelled. A queued request is answered at once with LSP's RequestCancelled
  (`-32800`) and never runs. A running one is only flagged, and stops with `-32800` at its next **safe point**
  (`cancellation.check()`): the end of `_ctx`, the moment before an assembly is built (`_stage_subassemblies`
  found nothing left to stage), and the turn of each item of a recursive render, a CAM route, a Build vs Buy
  table, a recursive test, each CAE scenario and each simulation. Safe points are between units of work, never
  inside one, and `RequestCancelled` is a `BaseException` so that an operation reporting one object's failure and
  carrying on cannot swallow it. One that reaches no safe point is answered as usual. A client that can no longer
  be reached -- a write to it failed, as for `pc` interrupted with Ctrl-C -- has its requests cancelled the same
  way; one that only closed its sending half (stdin of `--stdio` at the end of a pipe) is still answered.

  A few requests are answered by the reader instead, beside whatever is being served: `daemon.stop`,
  `daemon.settings`, `log.mode`, `$/cancelRequest`, and the liveness probe `rpc.discover`
  (`partcad_utils.workspace.LIVENESS_METHOD`). The probe has to be: queued behind a long request -- or behind one
  that never ended, which is what a sandbox process that died used to leave (see "A sandbox process is waited for
  until it is dead" in `src/partcad/AGENTS.md`) -- it timed out, and `pc daemon stop`, which asks it first,
  reported that no daemon was running to the user the stalled client had just told to run it. Whatever is
  answered there must touch no session state: the emitter's sink belongs to the request being served. `log.mode`
  takes effect at once, even for a request of the same connection that is already running; the editor sends it
  before anything else.
- `daemon.py` — workspace root discovery, hashing, socket path, liveness (`rpc.discover` probe), stale recovery,
  double-fork/detach, `daemon.stop`. `win_pipe.py` — the Windows named-pipe counterpart.

  CI **does** run Windows (`windows-latest` and `windows-2022` in `test.yml`), which is worth knowing because
  it is not what kept these bugs alive. `test_daemon.py` and `test_client.py` guard themselves on
  `socket.AF_UNIX`, which CPython does not define on Windows, so the daemon's own tests are skipped on exactly
  the platform this counterpart is for — and nothing else called into it. Every bug listed below reached users
  that way: not unrunnable, just unrun.

  So the tests for it are written to need no Windows kernel and live where nothing skips them:
  `test_win_pipe.py` pins the argv and the redirection the spawn is given behind a stand-in `Popen`, and
  `test_daemon_windows.py` — a module of its own, deliberately without the AF_UNIX guard — drives
  `ensure_daemon`'s Windows branch, taking it for real on the Windows legs and with `os.name` forced to `"nt"`
  on POSIX. Keep it that way: a test only Windows can run is a test that was not protecting this code before.

  Because the daemon is a **detached new process** rather than a fork, it inherits nothing, and each of these
  had to be handed to it explicitly:

  - **What to run.** `_launcher_argv` names the frozen bundle as itself rather than as `python -m`: the bundle
    takes the service's own options and rejects `-m`, so the daemon simply was not there.
  - **What it was told.** `spawn_pipe_daemon` repeats the launcher's settings flags
    (`__main__.settings_argv`) in the child's argv. Without them, `pc --python-sandbox conda daemon start`
    printed a pipe served by a daemon using the default sandbox, and said nothing about it.
  - **Somewhere to speak.** `DETACHED_PROCESS` leaves the child with no console, so its output is redirected
    into the workspace's `daemon.log` — the same file the POSIX daemon redirects itself to, which it can
    because it is a fork and gets to run code first. Without it, a daemon that died before serving accounted
    for itself nowhere.
  - **Somewhere to run.** The root of the launcher's drive (`_daemon_cwd`), as the POSIX daemon runs in "/": not
    the client's directory, which Windows would then refuse to delete for as long as the daemon serves, and
    not another drive either. A path with a root and no drive (`\tmp\home`) is on the *current* drive, and a
    daemon run from its state directory on C: built every such sandbox there for clients on D:.

  And `ensure_daemon` **waits for the pipe to answer** before printing it: the POSIX branch binds and listens
  in this very process, so the socket exists the moment it is named, while a pipe does not exist until the new
  process gets that far, and connecting to a pipe that is not there fails instead of queueing.

  Where the pipe is and whether anything answers on it (`pipe_name`, `is_pipe_alive`) comes from
  `partcad_utils.win_pipe`, never from this package — the rendezvous belongs to neither end, exactly as
  `socket_path`/`is_alive` in `partcad_utils.workspace` do for POSIX. Importing `is_pipe_alive` from
  `.win_pipe`, which has no such name, is what shipped: on Windows `ensure_daemon` raised ImportError on the
  first line of the branch, and all a client saw was `partcad-json-rpc.exe ... exited 1`.
- `config_restart.py` — the daemon (socket and pipe alike) **restarts when `~/.partcad/config.yaml` changes**,
  which it otherwise read once, at start, for as long as it stayed warm. Restarting is *leaving*: it unlinks its
  endpoint at once, so the next client starts a fresh daemon that reads the new file, while the connections it
  still has finish their requests and are then sent `doRestart` (which the extension answers by reconnecting).
  The daemon never starts its successor — that is a client's job, with that client's flags. Polled by content,
  not mtime; `PC_DAEMON_RESTART_ON_CONFIG=0` turns it off. After a restart the socket path and the pid file
  belong to the successor, which is why `SocketServer` forgets its path once unlinked and `_cleanup` removes
  only a pid file holding its own pid.
- The client side is not here: `partcad_client.client` holds `DaemonClient`, `start_daemon` (which runs this
  package's launcher) and `connect()`. `connect()` works out the endpoint from `partcad_utils.workspace` and
  connects to it directly, running the launcher only when nothing answers -- so the launcher's fast path ("a
  daemon is listening: print it") is now taken by `pc daemon start` and the editor extension, and every decision
  past that one (the lock, replacing a stale or differently started daemon, the settings it is started with) is
  still the launcher's alone.
- `__main__.py` — the `partcad-json-rpc` entry point: channel selection (`--socket` default, `--stdio`,
  `--http`) and CLI-style flags mirroring `pc` globals.

## Setup

All commands run **inside the dev container**, not on the host — see "Where commands run" in the root
[AGENTS.md](../../AGENTS.md). Dependencies are already installed in the image; re-run `poetry install` only after
changing `pyproject.toml`. The virtualenv is not auto-activated, so prefix commands with `poetry run`.

```bash
poetry install   # from repo root; installs the whole `partcad` wheel in editable mode
```

## Test and validate changes

```bash
pytest tests/partcad_service_json_rpc -x -p no:error-for-skips -p no:warnings -n logical --dist worksteal   # matches CI
```

Manual smoke over stdio (framed JSON-RPC; `rpc.discover` needs no package loaded):

```bash
poetry run partcad-json-rpc          # then send a framed request on stdin
poetry run partcad-json-rpc --http   # serve on 127.0.0.1:8017 instead
```

## Lint / format

```bash
poetry run black --check src/partcad_service_json_rpc tests/partcad_service_json_rpc
poetry run flake8 src/partcad_service_json_rpc tests/partcad_service_json_rpc
poetry run isort --check --filter-files src/partcad_service_json_rpc tests/partcad_service_json_rpc
```

All three gate — each is a `pre-commit` hook and a `Lint (...)` job in `test.yml`, and the tree satisfies
all three, so a finding from any of them is yours. See the root [AGENTS.md](../../AGENTS.md) for the two flags that
are load-bearing (`--filter-files`, and the `Flake8-pyproject` plugin without which flake8 reads no config
at all).

## Method surface

Method names mirror `partcad-cli` subcommands: `inspect.part|sketch|interface|assembly|scene|file`,
`export.part|assembly|scene`, `ai.regenerate|change`, `add.part|assembly|scene`, `package.load|path|refresh`, `init`,
`list.all`, `bom`, `assembly.guide`, `supply.quote`, `cae.analyze|defaults|list`, `cam.route`, `filter.object`,
`test`, `info`, `activate`, and `rpc.discover`. Five methods mirror no subcommand:

* `assembly.instantiate`, which a client calls on its own behalf as the second half of a two-phase assembly
  build (see below).
* `daemon.debug`, which reports where the service runs from and whether a debugger is attached. The editor
  extension asks it once, when it is being debugged from a checkout, to decide whether to replace the daemon
  with one that attaches to the debugger (`debugger.py`, `PC_DEBUGPY`).
* `render.inline` and `render.formats`, behind the Digital Thread's 2D and Draft tabs. The first renders one object
  to one file type -- `pc render -t <format> [-e <package>]` for a single object -- in a temporary directory,
  and returns the file's bytes, name and extension rather than a path, since the daemon may be on another
  machine; the client keeps the file and saves it where the user says. The second lists the file types a
  package declares under `render:`, which is what a drawing package such as
  `//pub/feature/render/draftwright` offers.

  Both of those tabs also have a control pane now, and what it asks for rides on `render.inline`: `filter`,
  the links of the object to keep, and `with_ports`/`with_interfaces`/`with_internals`, which are the same
  things `pc render --filter` and `--with-*` ask for. The filter arrives as **data** rather than as the text a
  user typed, because resolving the argument means looking for a file on the machine that typed it (see
  "Command boundary" in `src/partcad_cli/AGENTS.md`); a string is still accepted and read as an expression,
  never as a path. `_link_filter` is the one reader of the parameter, so `render.objects`, `render.inline` and
  `filter.object` cannot come to disagree about it.

  `filter.object` is `pc filter`: a second object made of some of the links of the first. It is a daemon
  method because it writes a declaration, like every other package-mutating command -- a client doing it
  itself would leave this warm context serving the package as it was before.
* `manufacturing.tree`, `manufacturing.details` and `manufacturing.plan`, behind the Digital Thread's Build vs Buy and
  Build tabs (see `partcad/build_plan.py`). The tree is every line item an object is made of, each saying
  whether it can be bought, built, or both, and costs what `bom` costs -- nothing is built for it. The details
  are a thumbnail and the measurements of *several* objects per request, because this daemon answers one request
  at a time and a table of forty rows asked row by row would queue every other tab behind it; the thumbnails are
  kept in PartCAD's cache under the shape's key and the size (`partcad/thumbnail.py`). The plan is what has to be
  done, in order, given the user's Build vs Buy choices -- which the client sends with every request, since they
  are kept on the client's machine (`partcad_utils/garage.py`) and never read from disk here. With `document`
  it also carries the pages that explain each item, which for an assembly is the very instruction book
  `assembly.guide` writes, and `pages` maps each item to its page, so the step on screen and the page of the
  book are one. `assembly.guide` returns the plan and the pages too, takes `subassemblies` (`pc instructions -r`; `recursive`
  on a request that names an object already means a walk over packages, and is refused), `build_parts`,
  `choices` (or `bvb`, every object's, for a client that cannot resolve the name -- `pc instructions`) and,
  with `format`, the document written down as PDF or HTML, as bytes for the client to save on its side.
  `document: false` leaves the model out, for `pc instructions`, which keeps only the file and was sent every
  illustration a second time beside the copy inside it; `image_bytes` carries each picture of the model as its
  bytes and media type rather than as a data URI, which is how the IDE asks (and `manufacturing.plan` takes it
  too). An older daemon ignores both and sends what it always sent, which both clients still read.
* `requirements.check`, behind the Digital Thread's Requirements tab: an object's `requirements:` as data -- the features,
  each with the `simulate:` entries that name it (`feature:`), and a line per required port, interface and
  physical property. Without `verify` nothing is built and every verdict is `null`, which is what lets the
  extension ask on every show whether there is a tab to offer at all; with it each line carries the verdict
  `pc test`'s `requirements` check reaches, by the same code (`partcad/requirements.py`). An assembly is staged
  only when a physical property is to be checked, because that is what builds it -- what it weighs is worked out
  from the tree it is built as (`partcad/physics.py`), while its ports are read off a tree that needs no build.
* `test.report`, behind the Digital Thread's Test tab: every check `pc test <object>` runs, as a list -- each
  with its verdict (`passed`, `failed`, `warned`, `skipped`, `not-applicable`), what it said, what it left behind
  to be looked at, and its entry in `partcad/test/catalog.py`. Without `verify` nothing is run and only the checks
  that do not apply have a verdict; with it the checks run through the same cache `pc test` reads, so the two
  give the same answer (`partcad/test/report.py`). An assembly or a scene is staged first when it is run.

Server-to-client
notifications carry the same semantics as the extension's legacy `?/partcad/*` events (`info`/`warn`/`error`, `items`,
`stats`, `terminal`, `execute`, and the `*Done`/lifecycle signals).

Six of them answer the tabs of the IDE's Digital Thread, which is a webview with no file system and no
network in reach: `bom`, `assembly.guide`, `supply.quote` and the three behind the analysis tabs,
`cae.list`, `cae.analyze` and `cae.defaults`. The first three are the CLI's own operation returning **data**
rather than writing a file -- `assembly.guide` is the instruction book `pc render -t html|pdf` writes, as
`partcad.document`'s renderer-independent model with the illustrations inlined (they live in a temporary
directory that is deleted as soon as the document is built); `supply.quote` fills the cart `pc supply quote`
fills and quotes each line item on its own, because a cart of the whole assembly comes back as one price for
all of it. Note that `supply.quote` deliberately does *not* go through `Context.find_suppliers()`: that reports "no
suppliers" as an error, and in the IDE an error is a modal popup, one per part.

`cae.analyze` is the odd one of the six: it *runs* something rather than answering a question about the
package, and it is the same `Shape.analyze_async()` that `pc cae fea` runs -- for every scenario of the
analysis the part declares, or for the one `scenario` names, which is `pc cae fea -f` and what a tab asks.
Its answer is shaped like `simulate.run`'s: an entry per scenario under `analyses`, each with an `error`
that is null or the sentence saying why that scenario produced nothing -- one scenario's failure is that
entry's, not a JSON-RPC error, and does not stop the next -- and every finding under `findings`, tagged with
its scenario. What leaves nothing to run at all (no such part, no such section, no such scenario) is still a
`USAGE_ERROR`. `cae.list` is `simulate.list`'s twin: what each analysis declares, read and not run, which is
what enables and fills each analysis tab. Two things about `cae.analyze` are for the webview specifically.
`inline` asks for the model's bytes beside the path it was written to, because a panel
with no file system cannot open a path -- and the daemon may not even be on the viewer's machine. And
`cae.defaults` exists at all because the field over the model has to be *pre-filled*: which implementation runs
an analysis is user configuration, not a property of the object on screen, so there is nothing in the object's
answer to fill it from -- least of all when the answer is the failure of a solver that is not installed, which
is exactly when the user needs to see what was tried.

`cam.route` runs something too, and it is the one method whose unit is a *package* rather than an object. With
no `object` it routes every sketch and part that declares a `cam:` section and passes over the rest, so the
enumeration is here rather than in a client -- and it reports every failure instead of stopping at the first,
because a route is a file and one object's broken section must not cost the other nineteen theirs. It has no
`inline` twin: a route is text a machine reads, not something a webview draws.

### Files cross as attachments

A method that hands a file back -- `render.inline`, `cae.analyze` with `inline`, `simulate.run` with `inline`,
the thumbnails of `manufacturing.details`, the `file` of `assembly.guide`, and the model's pictures with
`image_bytes` -- returns its **bytes**, and the transport decides how they cross (`partcad_utils.framing`). To a
client that said it reads them, they are raw segments after the message, named in the JSON as
`{"$attachment": <index>}` and announced in an `Attachment-Lengths` header beside `Content-Length`; to any
other they are base64 text under the same key, which is exactly what that field held before attachments
existed. A client says so with `Accept-Attachments: 1` in the header of a message, and the transport keeps
that per connection (a `framing.Peer`), beside the ANSI renderer `log.mode` asks for and for the same reason:
the session is every client's at once. `DaemonClient` says it on every request, and so does the editor
extension (`ide/vscode/src/common/framing.ts`); the FreeCAD addon does not, and is handed no file anyway.
`--http` has no attachments: its answers are base64, as they were (`framing.to_json`).

Two things follow, and both matter. **A reader of such a field takes both forms** -- `framing.as_bytes` on
the Python side, `bytesOf` in the extension -- because a daemon older than this, or one reached over HTTP, still
sends base64. And **base64 happens at an edge or not at all**: the MCP server encodes a picture because MCP's
image content is base64, and nothing else here does. At forty megabytes this is the difference between 1.3 s
end to end with the daemon's GIL held for half a second, and 30 ms with it held for a few. One object named
twice in a message is one segment, which is why the cae model of the only scenario and the illustration on
several pages of a book cross once.

There is deliberately no second way for a file to reach a client -- a path on a local daemon's disk, say: two
ways of delivering one file are two ways to get it wrong, and attachments serve a remote daemon as well as a
local one. No request carries a file yet; the daemon's readers take attachments all the same, but a client
would have to learn whether its daemon does before sending one.

### An assembly is built in two phases

An assembly is built out of other assemblies, and building one of those can take minutes. Done inside the
request that asked for the parent, all of it is one request — for as long as the deepest tree takes, with
nothing the client can do but wait.

So the operations whose unit is one assembly look before they build: `inspect.assembly`, `export.assembly`,
their scene counterparts, `inspect.object`, `render.objects` when it names one assembly or scene, and
`assembly.instantiate` itself. What is staged is the shape being **instantiated**, which is the same work
whatever is done with it afterwards — shown in the viewer, written as an export file, written as a render —
so the first phase sits above that distinction and never asks which it is. The first phase reads the
assembly's declaration and asks which of the assemblies it places are not cached yet
(`Assembly.get_uncached_subassemblies_async`, which costs a declaration read and a `stat` per entry — never a
payload). None, and the request proceeds exactly as it always did. Some, and **nothing is
built**: the request comes back as the error code `-32004` naming them, and the client builds each one through
`assembly.instantiate` with `cacheOnly` — which leaves the geometry in the daemon's cache and sends back a
status — before asking again.

Nesting needs nothing extra. A staging request is an assembly request, so a sub-assembly with sub-assemblies
of its own answers `-32004` in its turn and the client recurses. The whole exchange takes longer than one
request would; what it buys is that no single request is longer than one assembly's own work.

Two things keep it from becoming a loop, and both are needed:

* The daemon never names an assembly it has already built on request (`Session.staged`, weak so that an
  evicted context takes its record with it). An entry too large to keep in memory and refused by every cache
  tier would otherwise be reported as missing forever. Named once, built once, and after that the parent
  builds it inline — slower than it should be, but an answer.
* The client never stages the same entry twice for one call, and reports the error if a service asks for one
  it has already built.

The protocol — the code, the method name, the flag, the payload — is `partcad_utils.staging`, and both ends
read it from there. The VS Code extension restates it in `ide/vscode/src/common/staging.ts` because it speaks
JSON-RPC itself; that is the one copy, and it has to stay in step. A client that does not implement any of
this gets an error message saying what to build first, which is the most a client that cannot act on it can be
given.

What is deliberately *not* staged: `bom`, `assembly.guide` and `supply.quote`, which walk the assembly tree
without building geometry; a `render.objects` or `test.run` whose unit is a package (recursive, or naming no
object) — what they would have to name is everything they are about to build, and they already report where
they have got to, object by object, as they go; and `convert.object`, which rewrites a declaration rather than
building the object it names.

There is deliberately no prompt in the protocol. A daemon has nobody to ask, and a request that blocks
waiting for an answer it cannot receive is a hang, not a question -- anything a command needs is either an
argument or configured upfront in the user configuration (see `git.auth` for private Git dependencies).

### `package`, `object` and the `...` suffix

A `package` ending in `...` -- and an `object` whose package half ends in one, `...:bolt` or
`//pub/examples...:bolt` -- means that package **and every package below it**, which is what the `recursive`
parameter has always meant. It is read **here**, by `operations._request()`, and not by the CLI: the CLI is one
of three clients, and a syntax each of them parsed for itself is a syntax they would each get slightly wrong.
`partcad_utils.utils.split_recursive_object()` is the one implementation, in `partcad_utils` because the
answer must not depend on a CAD kernel being importable.

So an operation that takes a package reads it as `selected, object_name, recursive = _request(params)` rather
than off `params` directly, and `recursive` is true when *either* spelling asked for it. Two consequences worth
knowing:

* The suffix can say **where** the walk starts, which the flag cannot, and an object name carrying one wins
  over `package` -- the rule a fully qualified `//package:name` already follows.
* A walk over a *named* object asks every package of the subtree for its own object of that name and passes
  over the ones that declare none (`_targets()`, over `Project.declares_object()`, which reads the declaration
  and builds nothing). Only a walk that found it nowhere is a failure, reported once by `_nowhere()`. Without
  that filter a name like `bolt` fails in every package that has no bolt -- and a render of such a package
  raises `EmptyShapesError`, which used to end the whole run.

An operation whose answer is about **one** object -- `bom`, `assembly.guide`, `cae.analyze`, `supply.quote`,
`inspect.object`, `convert.object` -- calls `_refuse_recursion()` and says so, rather than guessing between a
merged answer and a sequence of them. Adding recursion to one of those is a decision about what its result
becomes, not a parsing change.

### What a request's object is

A request names its object by name, and need not say what kind it is: a name is one object of its package
whatever its kind (see `partcad_utils/object_names.py`), so `operations._kind_of()` asks the package
(`Project.object_kind`), and `_kind_of_async()` from a coroutine. The kind flags (`sketch`, `interface`,
`assembly`, `scene`, `software`, read by `_object_kind()`) and the `kind` parameter of the methods the IDE calls
(`_said_kind()`) are still taken, at their word and without a lookup -- what they are for now is skipping it. A
name that is nothing at all becomes a part, so that the miss is reported by the part getter's "is not found",
as it always was; a method that does nothing with the kind it finds refuses it in its own words
(`_resolve_kind()`).

A walk over a named object (`_targets()`) asks each package what its own object of that name is, and returns
`(package, name, kind)`: the `bolt` of one package can be a part and the `bolt` of the next an assembly. A kind
said with a flag narrows the walk to objects of that kind instead.

### `params`: the values an object is asked for with

An object with particular parameter values *is* a name -- `bolt;length=10` -- and every method that takes an
object takes one. `params` is the same request one value at a time (`pc ... -p length=10`), and it arrives in
two shapes that mean the same thing: a list of `<name>=<value>` from `pc`, and a mapping from the editor, the
FreeCAD addon and an agent. `_assigned()` is the one reader of both, over
`partcad_utils.parameters.assignments` -- the CLI checks each value with that same function before sending --
and `_request()` and `_resolve_object()` write what it read into the object's name (`_assigned_name()`), so
every operation that reads its object through either takes parameters without a line of its own, and its log,
its files and its cache entries name the instance. A value given in `params` wins over one the name carries.

Two consequences worth knowing:

* Values with no object to give them to are a usage error, not something to drop. The exception is a request
  that names its object as `name` -- the editor's per-kind methods (`inspect.part`, `export.assembly`, ...),
  which hand `_assigned(params)` to the getter themselves and pass through `_request()` only to have their
  package found.
* Anything that asks what *kind* an object is must ask under the name it is **declared** as, which is the name
  without its values (`parse_parameterized_name`): nothing declares `bolt;length=10`. `bom` asked under the
  whole name, and took every part asked for with values for an assembly that is not found.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
