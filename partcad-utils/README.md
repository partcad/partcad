# partcad-utils

Shared lightweight utilities for the [PartCAD](https://github.com/partcad/partcad)
ecosystem: logging, telemetry, user configuration, and the client/daemon
rendezvous.

These modules are deliberately free of any CAD-kernel dependency, so importing
them is cheap. That is what lets the thin clients — `partcad-cli`, the
`partcad-json-rpc` service/daemon, and the VS Code extension — reuse the exact
same logging and configuration code as the `partcad` core without paying the
cost of importing the full `partcad` package on every invocation.

## Contents

- `logging`, `logging_ansi_terminal` — PartCAD's logging and the ANSI terminal
  renderer (progress footer for processes/actions).
- `logging_remote_server`, `logging_remote_client` — forward structured log and
  process/action events from a daemon to a client, where they are rendered
  locally (ANSI or plain).
- `telemetry`, `telemetry_none`, `telemetry_sentry` — the telemetry subsystem.
- `user_config` — the user configuration model.
- `framing`, `workspace`, `win_pipe` — the client/daemon rendezvous (see below).
- `utils` — small shared helpers.

## The client/daemon rendezvous

`framing` is the LSP-style `Content-Length` codec both ends speak. `workspace`
(and `win_pipe`, its Windows counterpart) says which socket serves which
workspace and whether anything is answering on it.

They are here, rather than on either side, because neither side owns them: a
daemon binds the address these compute and a client looks for it at the same
address, so a copy on each side is a copy that can disagree — and a disagreement
means a client silently starting a second daemon beside the one already serving.

Everything a *client* then does with a daemon — connecting, stopping it, waiting
for it, enumerating the local ones — is
[`partcad-client-utils`](../partcad-client-utils/README.md); serving is
[`partcad-service-json-rpc`](../partcad-service-json-rpc/README.md).

The `partcad` package aliases these modules back under its own namespace
(`partcad.logging` is `partcad_utils.logging`), so existing code that imports
them from `partcad` continues to work unchanged.
