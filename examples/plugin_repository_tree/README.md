# Repository plugin: parts listed over a remote endpoint

This example demonstrates a package whose parts are **enumerated and fetched
over network calls**, rather than read from a local file (as in
`../plugin_repository_basic`).

The "remote" endpoint is a small Flask server implemented inside this same
package. Conceptually it is a remote server: the repository plugin talks to it
over HTTP, so the same code would work against a real remote repository by
changing only the endpoint URL.

## What it demonstrates

- `type: external` import backed by a repository plugin (`type: basic`).
- The plugin answering the `list` query by calling the endpoint, so the set of
  parts is discovered at access time, not at package-load time.
- The plugin answering `get <name>` by fetching a single part's definition,
  without listing the whole repository first.

## Intended usage

```shell
# starts the bundled endpoint, then queries it through the package
pc list parts example
pc inspect example:<part>
```

## Consumption (see partcad.yaml)

```yaml
dependencies:
  example:
    type: external
    plugin: :remote        # a package served by the 'remote' repository plugin

repositories:
  remote:
    type: basic
    parameters:
      endpoint:
        type: string
        default: http://127.0.0.1:5000
```

## Status

The consumption syntax above is final. The endpoint server (`server.py`) and
the repository plugin script (`remote.py`) implement the generic key/value
data-access protocol (`ProjectExternalRepository.request()` with the
`objects/<kind>` and `objects/<kind>/<name>` keys). They are pending the
finalization of that protocol; this README specifies the contract they
implement.
