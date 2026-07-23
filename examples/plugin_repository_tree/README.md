# Repository plugin: a hierarchy of packages

This example extends `../plugin_repository_basic` from a single package to a
**hierarchy of packages**, all served by one repository plugin.

## What it demonstrates

- A top-level `type: external` package that, when its children are listed,
  reports that it **contains several sub-packages**.
- Each sub-package is itself an `external` package backed by the same repository
  plugin, forwarding the same queries to the plugin with an additional
  **`subfolder`** key that scopes the request to that part of the tree.
- Inner packages define their own lists of **sketches, parts and assemblies**,
  each enumerated and fetched lazily.
- The top-level package also hosts a **supply provider** that every inner part
  can be quoted/ordered through — showing that a plugin-backed package is
  indistinguishable from a local one: it can host any kind of object, including
  providers, and can have children.

## Structure served by the plugin

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

Listing the top-level package returns its child package names (the `deps` key);
listing a child forwards the object queries with its `subfolder`; fetching a
part forwards the same with the object name.

## Intended usage

```shell
pc list packages example
pc list parts -r example
pc inspect example/motors:<assembly>
pc supply quote example/brackets:<part>
```

## Status

The consumption syntax is final and mirrors `../plugin_repository_basic`. The
plugin script that serves the hierarchy implements the generic key/value
data-access protocol — the same accessors as a local package
(`object_config` / `object_configs` / child enumeration), keyed by
`<subfolder>/deps` and `<subfolder>/objects/<kind>[/<name>]`, cached through
`ProjectExternalRepository.request()`. It is pending finalization of that
protocol; this README specifies the contract it implements.
