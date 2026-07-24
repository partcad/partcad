# Repository plugin: a hierarchy of packages

This example extends `../plugin_repository_basic` from a single package to a
**hierarchy of packages**, all served by one repository plugin.

## What it demonstrates

- A top-level `type: external` package that, when its children are listed,
  reports that it **contains several sub-packages**.
- Each sub-package is itself an `external` package backed by the same repository
  plugin, forwarding the same queries to the plugin with an additional
  **`subfolder`** key that scopes the request to that part of the tree.
- Each sub-package serves its own parts, whose CadQuery scripts are fetched and
  **materialized** from the plugin on demand — showing that a plugin-backed
  package is otherwise indistinguishable from a local one and can have children.

## Structure served by the plugin

```
example/                         (external; subfolder="")
  ├── brackets/                  (external; subfolder="brackets")
  │     └── parts: l_bracket
  └── motors/                    (external; subfolder="motors")
        └── parts: shaft
```

Listing the top-level package returns its child package names (the `deps` key);
listing a child forwards the object queries with its `subfolder`; fetching a
part's file forwards `files/<path>` with the same prefix.

## Intended usage

```shell
pc list packages example
pc list parts -r example
pc inspect example/motors:shaft
```

## Files

| File | Role |
|------|------|
| `remote.py`      | The repository plugin PartCAD runs; serves the hierarchy over the key space. Covered by `test_tree_remote.py`. |
| `partcad.yaml`   | Declares the `external` package and the `remote` repository plugin. |

The plugin implements the generic key/value data-access protocol — the same
accessors as a local package (`object_config` / `object_configs` / child
enumeration), keyed by `<subfolder>/deps`, `<subfolder>/objects/<kind>[/<name>]`
and `<subfolder>/files/<path>`, cached through
`ProjectExternalRepository.request()`.
