# partcad-service-json-rpc

JSON-RPC service interface to `partcad`. Ships the `partcad-json-rpc` executable, which exposes PartCAD over a
JSON-RPC 2.0 interface whose methods mirror `partcad-cli` actions. Source: `./src/partcad_service_json_rpc`.
Tests: `./tests`. Part of the shared Poetry workspace rooted at the repo root — depends on the `partcad` package
in this monorepo (`../partcad`); run all commands below from the repo root unless noted.

The service serves over stdin/stdout by default (LSP-style `Content-Length` framing, bidirectional) and,
optionally, over HTTP (`--http [ADDR]`: JSON-RPC at `POST /rpc`, notifications over Server-Sent Events at
`GET /events`; no auth yet). The `partcad-ide-vscode` extension launches it as its default backend.

## Layout

- `core/` — transport-agnostic operations shared with the legacy VS Code LSP server: `session.py` (PartCAD
  state + interactive prompt + log streaming), `events.py` (the event emitter and the event-name contract),
  `operations.py` (the operation functions).
- `rpc/` — `dispatcher.py` (JSON-RPC 2.0 parse/dispatch/error mapping) and `methods.py` (the CLI-shaped method
  registry; `rpc.discover` returns the catalog).
- `transport/` — `framing.py` (Content-Length codec), `stdio.py` (default), `http.py` (optional HTTP+SSE).
- `__main__.py` — the `partcad-json-rpc` entry point: CLI-style flags mirroring `pc` globals, transport
  selection.

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
black --check partcad-service-json-rpc
flake8 partcad-service-json-rpc
isort --check partcad-service-json-rpc
```

## Method surface

Method names mirror `partcad-cli` subcommands: `inspect.part|sketch|interface|assembly|file`,
`export.part|assembly`, `ai.regenerate|change`, `add.part|assembly`, `package.load|path|refresh`, `init`,
`list.all`, `test`, `info`, `activate`, `prompt.respond`, and `rpc.discover`. Server-to-client notifications
carry the same semantics as the extension's legacy `?/partcad/*` events (`info`/`warn`/`error`, `items`,
`stats`, `terminal`, `execute`, `prompt`, and the `*Done`/lifecycle signals).

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
