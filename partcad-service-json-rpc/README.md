# partcad-service-json-rpc

JSON-RPC service interface to [PartCAD](https://github.com/partcad/partcad). Installs the `partcad-json-rpc`
executable, which exposes PartCAD functionality over a JSON-RPC 2.0 interface whose methods mirror
[`partcad-cli`](../partcad-cli) actions.

## Transports

- **socket / daemon (default):** a per-workspace background daemon holds a warm PartCAD context and serves it
  over an AF_UNIX socket at `~/.partcad/workspaces/<hash>/socket` (a named pipe on Windows). Running
  `partcad-json-rpc` finds the workspace root, prints the socket path, and — if no live daemon is found — starts
  a detached one. Multiple clients (the VS Code extension, `pc` invocations, additional windows) share the one
  warm context. `daemon.stop` (or `pc daemon stop`) terminates it.
- **stdin/stdout:** `partcad-json-rpc --stdio` serves one connection over stdin/stdout in the foreground
  (LSP-style `Content-Length` framing, bidirectional) — no daemon.
- **HTTP (optional):** `partcad-json-rpc --http [HOST:PORT]` (default `127.0.0.1:8017`) serves JSON-RPC at
  `POST /rpc` and streams notifications over Server-Sent Events at `GET /events`. No authentication yet.

The daemon serializes operations across connections and routes each request's notifications back to the
connection that made it.

## Usage

```bash
# Default: ensure the per-workspace daemon and print its socket path.
partcad-json-rpc

# Serve one connection over stdin/stdout (what a client can spawn directly).
partcad-json-rpc --stdio

# Serve over HTTP instead.
partcad-json-rpc --http 127.0.0.1:8017
```

The `pc` CLI manages the daemon with `pc daemon start` and `pc daemon stop`.

Global flags mirror the `pc` CLI (`--verbose`/`--quiet`, `--offline`, `--force-update`, `--google-api-key`,
`--openai-api-key`, `--python-sandbox`).

Call `rpc.discover` to list the available methods and their summaries.

## Install

Shipped as a Python wheel (`pip install partcad-service-json-rpc`) and as the third executable in the
standalone PartCAD bundle built by `dev-tools/pyinstaller` (alongside `pc` and `partcad`).

See [AGENTS.md](./AGENTS.md) for development and the repo root [CLAUDE.md](../CLAUDE.md) for the monorepo
overview. Licensed under the Apache License, Version 2.0.
