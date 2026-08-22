# partcad-ide-client

The Python side of the protocol that connects [PartCAD](https://partcad.org/) to the PartCAD IDE
extension's **PartCAD Viewer**.

`partcad` imports this package lazily, from `Shape.show()` and `Interface.show()` only. The PartCAD IDE
extension installs it into the same interpreter it installs `partcad` into. Nothing else needs it, and
nothing here imports `partcad`, OCP, or any other CAD library — by the time geometry reaches this package it
has already been tessellated into glTF inside a PartCAD sandbox.

## Protocol

The IDE binds `127.0.0.1:9137` (constant, with `SO_REUSEADDR` and `SO_REUSEPORT`) and this client connects to
it. The port is fixed rather than negotiated so a `partcad` process started outside the IDE — a CLI run, a
notebook, a test — can find a running viewer with no discovery step. Set `PARTCAD_IDE_PORT` to move both ends
off the default.

A frame is a 10-byte header (`PCAD` magic, version, payload kind, big-endian payload length) followed by a
UTF-8 JSON payload. Geometry rides inside a `show` message as deflate-compressed, base64-encoded binary glTF:

```json
{
  "type": "show",
  "id": "…",
  "name": "//some/package:part",
  "kind": "part",
  "keepCamera": true,
  "objects": [{ "name": "…", "label": "…", "gltf": "…" }]
}
```

The IDE answers every message with an `ack`.

zlib is used rather than the zstd that PartCAD's BREP envelopes use, because both ends of *this* pipe have to
decompress, and zlib is in the standard library of both Python and Node.

## Usage

```python
import partcad_ide_client as ide

if ide.is_available():
    ide.show([ide.make_object(glb_bytes, name="//pkg:part")], name="//pkg:part")
```

## License

Apache License 2.0.
