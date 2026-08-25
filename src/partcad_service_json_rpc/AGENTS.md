# partcad-service-json-rpc

JSON-RPC service interface to `partcad`. Ships the `partcad-json-rpc` executable, which exposes PartCAD over a
JSON-RPC 2.0 interface whose methods mirror `partcad-cli` actions. Source: `./src/partcad_service_json_rpc`.
Tests: `./tests`. Part of the shared Poetry workspace rooted at the repo root — depends on the `partcad` package
in this monorepo (`../partcad`); run all commands below from the repo root unless noted.

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
[AGENTS.md](../AGENTS.md). Dependencies are already installed in the image; re-run `poetry install` only after
changing `pyproject.toml`. The virtualenv is not auto-activated, so prefix commands with `poetry run`.

```bash
poetry install   # from repo root; installs partcad-service-json-rpc (and partcad) in editable mode
```

## Test and validate changes

```bash
pytest partcad-service-json-rpc -x -p no:error-for-skips -p no:warnings --dist no   # matches CI
```

Manual smoke over stdio (framed JSON-RPC; `rpc.discover` needs no package loaded):

```bash
poetry run partcad-json-rpc          # then send a framed request on stdin
poetry run partcad-json-rpc --http   # serve on 127.0.0.1:8017 instead
```

## Lint / format

```bash
poetry run black --check partcad-service-json-rpc
poetry run flake8 partcad-service-json-rpc
poetry run isort --check partcad-service-json-rpc
```

## Method surface

Method names mirror `partcad-cli` subcommands: `inspect.part|sketch|interface|assembly|file`,
`export.part|assembly`, `ai.regenerate|change`, `add.part|assembly`, `package.load|path|refresh`, `init`,
`list.all`, `test`, `info`, `activate`, and `rpc.discover`. Server-to-client notifications
carry the same semantics as the extension's legacy `?/partcad/*` events (`info`/`warn`/`error`, `items`,
`stats`, `terminal`, `execute`, and the `*Done`/lifecycle signals).

There is deliberately no prompt in the protocol. A daemon has nobody to ask, and a request that blocks
waiting for an answer it cannot receive is a hang, not a question -- anything a command needs is either an
argument or configured upfront in the user configuration (see `git.auth` for private Git dependencies).

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
