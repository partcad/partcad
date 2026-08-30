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
   client that edits `partcad.yaml` behind the daemon's back leaves it serving stale contents, which is why a
   package-mutating command (`add`, `import`) must be a daemon client and evict the context it changed
   (`_invalidate_context`).
   The context is warm across connections, which is why `activate` **reloads** `partcad` rather than importing
   it: `Session.load_partcad` drops every `partcad*` module out of `sys.modules` and imports the package again,
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
`daemon start|stop`, and `system telemetry clear|info`. File paths are not a reason to stay local: a client
sends an absolute path, `Project._validate_path` rejects anything outside the package, and `Project.rel_path`
reports it back relative to the package that owns it — so the output does not depend on anyone's working
directory.

## Layout

- `core/` — transport-agnostic operations shared with the legacy VS Code LSP server: `session.py` (PartCAD
  state + log streaming), `events.py` (the event emitter and the event-name contract),
  `operations.py` (the operation functions).
- `rpc/` — `dispatcher.py` (JSON-RPC 2.0 parse/dispatch/error mapping) and `methods.py` (the CLI-shaped method
  registry; `rpc.discover` returns the catalog).
- `transport/` — `framing.py` (Content-Length codec), `stdio.py`, `socket_server.py` (threaded AF_UNIX server,
  the daemon's transport), `http.py` (optional HTTP+SSE).
- `daemon.py` — workspace root discovery, hashing, socket path, liveness (`rpc.discover` probe), stale recovery,
  double-fork/detach, `daemon.stop`. `win_pipe.py` — the Windows named-pipe counterpart (untested on POSIX/CI).
- `client.py` — `DaemonClient` and `start_daemon`, used by the CLI (and any Python caller) to reach the daemon.
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
pytest tests/partcad_service_json_rpc -x -p no:error-for-skips -p no:warnings --dist no   # matches CI
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
poetry run isort --check src/partcad_service_json_rpc tests/partcad_service_json_rpc
```

## Method surface

Method names mirror `partcad-cli` subcommands: `inspect.part|sketch|interface|assembly|file`,
`export.part|assembly`, `ai.regenerate|change`, `add.part|assembly`, `package.load|path|refresh`, `init`,
`list.all`, `bom`, `supply.quote`, `test`, `info`, `activate`, and `rpc.discover`. Server-to-client
notifications carry the same semantics as the extension's legacy `?/partcad/*` events (`info`/`warn`/`error`, `items`,
`stats`, `terminal`, `execute`, and the `*Done`/lifecycle signals).

Three of them answer the tabs of the IDE's PartCAD Viewer, which is a webview with no file system and no
network in reach: `bom`, `assembly.guide` and `supply.quote`. Each is the CLI's own operation returning **data**
rather than writing a file -- `assembly.guide` is the instruction book `pc render -t html|pdf` writes, as
`partcad.document`'s renderer-independent model with the illustrations inlined (they live in a temporary
directory that is deleted as soon as the document is built); `supply.quote` fills the cart `pc supply quote`
fills and quotes each line item on its own, because a cart of the whole assembly comes back as one price for
all of it. Note that `supply.quote` deliberately does *not* go through `Context.find_suppliers()`: that reports "no
suppliers" as an error, and in the IDE an error is a modal popup, one per part.

There is deliberately no prompt in the protocol. A daemon has nobody to ask, and a request that blocks
waiting for an answer it cannot receive is a hang, not a question -- anything a command needs is either an
argument or configured upfront in the user configuration (see `git.auth` for private Git dependencies).

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
