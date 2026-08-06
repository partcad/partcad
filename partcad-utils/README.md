# partcad-utils

Shared lightweight utilities for the [PartCAD](https://github.com/partcad/partcad)
ecosystem: logging, telemetry, and user configuration.

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
- `utils` — small shared helpers.

The `partcad` package aliases these modules back under its own namespace
(`partcad.logging` is `partcad_utils.logging`), so existing code that imports
them from `partcad` continues to work unchanged.
