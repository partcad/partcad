# partcad-service-json-rpc

JSON-RPC service interface to [PartCAD](https://github.com/partcad/partcad). Installs the `partcad-json-rpc`
executable, which exposes PartCAD functionality over a JSON-RPC 2.0 interface whose methods mirror
[`partcad-cli`](../partcad-cli) actions.

## Transports

- **stdin/stdout (default):** JSON-RPC 2.0 with LSP-style `Content-Length` framing, bidirectional so the server
  can push notifications (logs, progress, package contents, interactive prompts).
- **HTTP (optional):** `partcad-json-rpc --http [HOST:PORT]` (default `127.0.0.1:8017`) serves JSON-RPC at
  `POST /rpc` and streams notifications over Server-Sent Events at `GET /events`. No authentication yet.

## Usage

```bash
# Default: serve over stdin/stdout (what the VS Code extension launches).
partcad-json-rpc

# Serve over HTTP instead.
partcad-json-rpc --http 127.0.0.1:8017
```

Global flags mirror the `pc` CLI (`--verbose`/`--quiet`, `--offline`, `--force-update`, `--google-api-key`,
`--openai-api-key`, `--python-sandbox`).

Call `rpc.discover` to list the available methods and their summaries.

## Install

Shipped as a Python wheel (`pip install partcad-service-json-rpc`) and as the third executable in the
standalone PartCAD bundle built by `dev-tools/pyinstaller` (alongside `pc` and `partcad`).

See [AGENTS.md](./AGENTS.md) for development and the repo root [CLAUDE.md](../CLAUDE.md) for the monorepo
overview. Licensed under the Apache License, Version 2.0.
