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

## Updating the installation

```sh
# Report whether a newer PartCAD is available, and exit.
partcad-json-rpc --check-update

# Update this PartCAD installation, and exit.
partcad-json-rpc --self-update
```

Both exit instead of serving, and print a JSON report as their last line for a caller that would rather not
parse the prose it just streamed. `--update-to VERSION` installs a specific version; `--update-repository
OWNER/NAME` takes standalone builds from somewhere other than `partcad/partcad`.

This is `partcad_service_json_rpc.selfupdate`, the module `pc update` and the VS Code extension's "Update
PartCAD" also run, so every entry point updates the same way. It knows both shapes PartCAD ships in — the
wheels (upgraded with `pip`) and the standalone bundle (a release archive, checksum-verified, installed under
`<install-dir>/<version>/` beside the running copy) — and it stops every running daemon, and waits for it,
before installing anything. Nothing is stopped or written until a newer version has actually been found.

## Install

Shipped as a Python wheel (`pip install partcad-service-json-rpc`) and as the third executable in the
standalone PartCAD bundle built by `dev-tools/pyinstaller` (alongside `pc` and `partcad`).

See [AGENTS.md](./AGENTS.md) for development and the repo root [CLAUDE.md](../CLAUDE.md) for the monorepo
overview. Licensed under the Apache License, Version 2.0.
