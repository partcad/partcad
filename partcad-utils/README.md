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
- `assy_lint`, `schema/assy.json` — checking an ASSY file (see below).
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
[`partcad-client`](../partcad-client/README.md); serving is
[`partcad-service-json-rpc`](../partcad-service-json-rpc/README.md).

## Checking ASSY files

`assy_lint` masks the Jinja2 constructs in an ASSY file with equally sized
filler, parses the result as YAML, and validates it against `schema/assy.json`.
Masking rather than rendering is what lets every finding keep the line and column
it came from — and what makes the check possible at all without the parameter
values, which are only known once a package is loaded.

It is here for the same reason `framing` and `workspace` are: neither side owns
it. The daemon checks a package's ASSY files when `pc lint` walks the package
graph; every client checks the one file somebody is editing, in its own process
([`partcad_client.lint`](../partcad-client/README.md), which is what
`pc lint --file` runs). Both answer the same question about the same documents,
so a second copy would be a copy that can disagree — and a disagreement here
means an editor and CI contradicting each other about a file.

This is the one module with dependencies beyond the rest of the package
(`jinja2`, `pyyaml`, `jsonschema`). All three are pure-Python and CAD-free, so
the "importing this is cheap" contract holds.

The `partcad` package aliases these modules back under its own namespace
(`partcad.logging` is `partcad_utils.logging`), so existing code that imports
them from `partcad` continues to work unchanged.
