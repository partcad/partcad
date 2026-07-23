# Repository plugin: parts served by an RPC/web server

Where `../plugin_repository_basic` hardcodes its data in the plugin script, this
example serves it from an **RPC/web server** that the plugin calls over HTTP.

The server (`server.py`) is a small Flask app bundled with the example.
Conceptually it is a remote endpoint: the plugin talks to it over HTTP, so the
same plugin would work against a real remote repository by changing only the
endpoint URL. The server is short-lived — it only needs to answer the requests a
single `pc` invocation makes — and it is covered directly by `pytest`
(`test_server.py`), independently of PartCAD, since it is ordinary Python with
no CAD-kernel dependency.

## What it demonstrates

- `type: external` import backed by a repository plugin whose data comes from a
  live HTTP endpoint, not a local file.
- The plugin answering the object queries by calling the endpoint, so the set of
  parts is discovered at access time.
- Fetching a single part without listing the whole repository first.

## Components

| File | Role |
|------|------|
| `server.py`      | The Flask endpoint (the "remote" repository). Runnable and unit-tested standalone. |
| `test_server.py` | `pytest` coverage of the endpoint's list/get responses. |
| `remote.py`      | The repository plugin script PartCAD runs; forwards queries to the endpoint. |
| `partcad.yaml`   | Declares the `external` package and the `remote` repository plugin. |

## Intended usage

```shell
pc list parts example
pc inspect example:<part>
```

## Consumption (see partcad.yaml)

```yaml
dependencies:
  example:
    type: external
    plugin: :remote

repositories:
  remote:
    type: basic
    parameters:
      endpoint:
        type: string
        default: http://127.0.0.1:5000
```

## Status

The endpoint (`server.py`) and its `pytest` coverage are complete and run
standalone. The plugin script (`remote.py`) that PartCAD executes to reach the
endpoint is pending finalization of the generic key/value data-access protocol
(`ProjectExternalRepository.request()` with `objects/<kind>[/<name>]` keys).
