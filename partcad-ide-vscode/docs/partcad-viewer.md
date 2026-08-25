# PartCAD Viewer

How a shape gets from a `partcad` process onto the screen.

```text
partcad (any process)                       partcad-ide-vscode (extension host)     webview
────────────────────                        ───────────────────────────────────     ───────
Shape.show() / Interface.show()
  │
  │ BREP envelopes (no OCP in this process)
  ▼
partcad.viewer.tessellate()
  │
  ▼
wrapper_show.py  ── in a sandbox ──▶ build123d.export_gltf(binary=True)
  │                                          │
  │                                  GLB ──▶ zlib ──▶ base64
  ▼
partcad_ide_client.show()
  │
  │  TCP 127.0.0.1:9137, framed JSON  ───────▶  PartcadViewerServer
  │  ◀───────────────────────────────────────  ack
                                               │
                                               │ zlib.inflate, base64
                                               ▼
                                          PartcadViewer  ── postMessage ──▶  three.js
                                                                             GLTFLoader
```

## Why it is shaped this way

**The core never holds a live OCP object.** PartCAD carries geometry as BREP-byte envelopes and does every
CAD operation in a sandboxed interpreter. Tessellation is a CAD operation, so it happens in `wrapper_show.py`,
not in the process that called `show()`.

**The viewer is a browser and has no CAD kernel.** It cannot read BREP, so what crosses the socket is a
tessellated binary glTF. This is what replaced handing live OCP objects to the `ocp_vscode` package, which
required a full CAD stack both in the core *and* in whatever interpreter the IDE was driving.

**The IDE is the server, on a constant port.** Any `partcad` — one the IDE started, one in a terminal, one in a
notebook — can find a running viewer with no discovery handshake. The port is bound with `SO_REUSEADDR` and
(where the runtime supports it) `SO_REUSEPORT`, and only on loopback: the payloads are the user's geometry and
the protocol has no authentication.

## Files

| Where | What |
| --- | --- |
| `partcad/src/partcad/viewer.py` | Core entry point: runs the wrapper, calls the client |
| `partcad/src/partcad/wrappers/wrapper_show.py` | Sandbox: BREP envelopes → compressed glTF |
| `partcad/src/partcad_ide_client/protocol.py` | **Normative** description of the wire format |
| `partcad/src/partcad_ide_client/client.py` | Python client |
| `src/viewer/protocol.ts` | The same wire format, in TypeScript |
| `src/viewer/PartcadViewerServer.ts` | The listening socket |
| `src/viewer/PartcadViewer.ts` | The "PartCAD Viewer" webview panel |
| `src/webview/viewer.ts` | The three.js renderer inside the panel |

## Coordinates and units

`build123d.export_gltf` writes glTF's own conventions: **metres**, and **Y up** (it bakes a −90° rotation about
X into the node transform to get there from OCCT's Z-up). So geometry arrives correctly oriented and the
renderer must *not* rotate it again.

Port markers are the exception. They are raw PartCAD locations — millimetres, Z-up — because they never go
through the exporter, so the renderer puts them under a group carrying exactly those two conversions.

## Compression

The glTF payload is zlib (deflate), not the zstd that PartCAD's BREP envelopes use. Both ends of *this* pipe
have to decompress it, and zlib is in the standard library of both Python and Node; zstd only reached Node in
23.8, well past what VS Code ships.

There are three implementations of that two-line codec, because none of the three can import either of the
others (the sandbox has no `partcad_ide_client`, the client has no `partcad`, the extension is not Python):
`ocp_serialize.encode_gltf`, `partcad_ide_client.protocol.encode_gltf`, and `decodeGltf` in `protocol.ts`.
`partcad/tests/unit/test_viewer.py` and `src/test/suite/viewerProtocol.test.ts` are what catch a drift.

## Rendering

`src/webview/viewer.ts` reproduces what `react-partcad-prerendered`'s `src/components/Part.js` does — the
viewer PartCAD already ships on the web — so a part looks the same in the IDE as it does on partcad.org: an
auto-rotating orbit camera framed on the model, drei `<Stage>`-style lighting with contact shadows, the
hemisphere and point lights `Part.js` adds, `MeshPhongMaterial`, and a loading overlay showing model size and
progress.

It departs from `Part.js` in three places, each for a reason:

- **No React or react-three-fiber.** A lot of bundle for a single canvas.
- **`RoomEnvironment` instead of `environment="city"`.** drei's presets are HDRIs fetched from a CDN. The
  panel's CSP forbids any network request, and an IDE has to work offline.
- **No −90° X rotation on the model.** `Part.js` loads OBJ, which has no scene graph and no units, so it has to
  stand the geometry up itself. glTF has both — see "Coordinates and units" above.

Positional lights use `decay: 0`. With three's physical default of 2, irradiance is `intensity/d²`, and a 10 mm
part in metre units sits ~0.03 from the rig — intensity 1 would arrive as ~1000 and burn the model to a white
silhouette. `Part.js` never hits this because its OBJ models are in millimetres.
