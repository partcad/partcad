# Repository plugin: a hierarchy of packages served over a remote endpoint

This example extends `../plugin_repository_tree` from a single package to a
**hierarchy of packages**, all served by the same remote endpoint.

The "remote" endpoint is again a small Flask server implemented inside this
package, so the example runs standalone while modeling a real remote
repository.

## What it demonstrates

- A top-level `type: external` package that, when listed, reports that it
  **contains several sub-packages**.
- Each sub-package is itself an `external` package backed by the same repository
  plugin, forwarding the same queries to the same endpoint with an additional
  **`subfolder` parameter** that scopes the request to that part of the tree.
- Inner packages define their own lists of **sketches, parts and assemblies**,
  each enumerated and fetched lazily over the endpoint.
- The top-level package also hosts a **supply provider** that every inner part
  can be quoted/ordered through — demonstrating that a plugin-backed package is
  indistinguishable from a local one: it can host any kind of object, including
  providers, and can have children.

## Structure served by the endpoint

```
example/                         (external; subfolder="")
  ├── brackets/                  (external; subfolder="brackets")
  │     ├── sketches: ...
  │     └── parts:    ...
  ├── motors/                    (external; subfolder="motors")
  │     ├── parts:      ...
  │     └── assemblies: ...
  └── providers:
        supplier                 (used by parts across all sub-packages)
```

Listing the top-level package returns its child package names (via
`list_deps`); listing a child forwards `list` with its `subfolder`; fetching a
part forwards `get <name>` with the same `subfolder`.

## Intended usage

```shell
pc list packages example
pc list parts -r example
pc inspect example/motors:<assembly>
pc supply quote example/brackets:<part>
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

The consumption syntax above is final. The endpoint server (`server.py`) and
the repository plugin script (`remote.py`) implement the generic key/value
data-access protocol — the same accessors as a local package
(`object_config` / `object_configs` / child enumeration), plus per-request
caching through `ProjectExternalRepository.request()` keyed by
`<subfolder>/objects/<kind>[/<name>]` and `<subfolder>/deps`. They are pending
the finalization of that protocol; this README specifies the contract they
implement.
