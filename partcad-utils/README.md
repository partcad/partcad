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
- `selfupdate` — updating the PartCAD installation itself, whether it is the
  Python wheels or the standalone bundle (see below).
- `utils` — small shared helpers.

## Updating PartCAD itself

`selfupdate` is what `pc update` runs, and — through `pc update --partcad-only` —
what the VS Code extension's "Update PartCAD" runs. It is the only implementation
of the operation, and it lives here rather than in the service because updating
an installation is a **client-side** act: it is this machine's copy of PartCAD
being replaced, by the process running from it. A daemon must not do it. A daemon
can be remote, where "update PartCAD" would mean updating somebody else's
installation, and a daemon that went looking for other daemons to stop would be
racing every client on the machine.

So this module knows nothing about daemons. A caller that has one passes
`before_install`, which runs once a newer version is confirmed and before the
first byte is written; `pc update` uses it to stop its own workspace's daemon and
wait for it. Nothing is written over the running installation either: a new
standalone bundle is installed beside the old one, under
`<install-dir>/<version>/`, so a daemon that was not stopped keeps serving from
intact files until it is restarted.

The `partcad` package aliases these modules back under its own namespace
(`partcad.logging` is `partcad_utils.logging`), so existing code that imports
them from `partcad` continues to work unchanged.
