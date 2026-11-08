# The shared part of the distributor plugins

`distributor.py` is in every `partcad-svc-commerce-<store>` package in this
directory, byte for byte, and so are `conftest.py` and `test_distributor.py`.
This copy is the one to edit; `copy.sh` puts it into every package and writes
the digest each package's own tests hold its copy to (`distributor.sha256`).

```shell
./incubator/_shared/copy.sh
```

It is the distributor counterpart of PartCAD's `plugin_models` (the toolkit for
model-site plugins), and it builds on it rather than copying it: the HTTP
client, its cache, the errors, the name grammar and the part types are
`plugin_models`', which PartCAD puts on the path of every plugin it runs
(PartCAD 0.9.17 or newer). What it adds is what a distributor is to PartCAD:

* **a catalogue** - categories as child packages, a search per package, a part
  per product named by the distributor's part number, its 3D model served as
  `files/<path>`, `vendor` and `sku` on every part, and the package's own store
  as every category's supplier;
* **a store** - `avail` and `quote` by the distributor's part number, or by a
  manufacturer and its part number; priced at the quantity actually ordered
  (the minimum, the order multiple, the price break it reaches), with stock
  said per line and never refused;
* **OAuth 2.0 client credentials**, with the token kept on disk until it
  expires (each api is a process of its own);
* **logging in** with an API key or a client ID and secret pasted into PartCAD's
  login banner, or handed over with `pc login --agent ... --set`.

Should these packages prove themselves, the next step is the one
`plugin_models` took: move `distributor.py` into PartCAD's wrappers as
`plugin_distributors.py`, tested with the rest of PartCAD, and drop the copies.
