# PartCAD Viewer

The panel is a strip of tabs over one object, not a canvas:

| Tab | Shown for | Where it comes from |
| --- | --- | --- |
| **3D** | everything | the viewer protocol, from whichever `partcad` asked for the shape to be shown |
| **Bill of Materials** | assemblies | the daemon's `bom` (what `pc bom` prints) |
| **Instructions** | assemblies | the daemon's `assembly.guide` (the book `pc render -t html\|pdf` writes) |
| **FEA** | parts | the daemon's `cae.analyze` (what `pc cae fea` runs) |
| **CFD** | parts | the daemon's `cae.analyze` (what `pc cae cfd` runs) |
| **Supply** | everything | the daemon's `supply.quote` (the cart `pc supply quote` fills) |

The 3D view is always the first: "show this part" means the geometry. The rest are questions about
`<package>:<name>` that only the extension host can put to the daemon — the panel's CSP forbids every network
request, and the daemon is behind a JSON-RPC connection anyway — so the renderer asks (`fetchTab`) and the host
answers (`tabData`), the first time a tab is looked at. That is also why the show message carries the object's
**package**: a name on its own cannot spell what to ask about, and a show that does not say (a shape belonging
to no package, a `partcad` older than the field) gets the 3D view alone rather than tabs that could only fail.

Nothing about a bill of materials, an instruction book or a quote is implemented in TypeScript. All three are
the CLI's own operations, asked for as data rather than as a file, so what the panel shows and what `pc` prints
cannot drift apart.

## How a shape gets onto the screen

```text
partcad (any process)                       ide/vscode (extension host)     webview
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
| `src/partcad/viewer.py` | Core entry point: runs the wrapper, calls the client |
| `src/partcad/wrappers/wrapper_show.py` | Sandbox: BREP envelopes → compressed glTF |
| `src/partcad_ide_client/protocol.py` | **Normative** description of the wire format |
| `src/partcad_ide_client/client.py` | Python client |
| `src/viewer/protocol.ts` | The same wire format, in TypeScript |
| `src/viewer/PartcadViewerServer.ts` | The listening socket |
| `src/viewer/PartcadViewer.ts` | The "PartCAD Viewer" webview panel, and the tab fetches |
| `src/webview/viewer.ts` | The panel shell inside the webview: tabs, routing |
| `src/webview/messages.ts` | The `postMessage` contract between the two, and the daemon payloads |
| `src/webview/scene.ts` | The three.js renderer behind the 3D tab |
| `src/webview/bom.ts` | The Bill of Materials tab |
| `src/webview/document.ts` | The Instructions tab: `partcad/document.py`'s model, drawn |
| `src/webview/supply.ts` | The Supply tab: the list, and one item's suppliers |
| `src/webview/cae.ts` | The FEA and CFD tabs: the result model, and the findings |
| `src/partcad/cae.py` | What a part declares about an analysis, and in what units |
| `src/partcad/assembly_guide.py` | The instruction book, built once for every format |
| `src/partcad/document.py` | The renderer-independent document model |

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
`tests/partcad/unit/test_viewer.py` and `src/test/suite/viewerProtocol.test.ts` are what catch a drift.

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

## The tabs beside the 3D view

Each non-3D tab is fetched on first look and cached until the next show, so opening one costs one daemon round
trip and switching back to it costs none. Every request carries the generation of the object it was made for and an
answer for an older one is dropped: a bill of materials walks the whole assembly tree and a supply quote goes
out to the network, so a round trip easily outlives a change of selection.

**Bill of Materials** is `Assembly.get_bom_detailed_async()` — the tree flattened and counted, with the store
data that says what to order — in the columns `pc bom` prints it in.

**Instructions** is the very document `pc render -t html|pdf` writes: built once in
`partcad/assembly_guide.py` as the renderer-independent model in `partcad/document.py`, handed over by
`assembly.guide` through `document.to_data(embed_images=True)`, and drawn by `src/webview/document.ts` one page
at a time. The illustrations are inlined as data URIs rather than pointed at, because they live in a temporary
directory that is deleted as soon as the document is built — and because the CSP forbids fetching anything
anyway. An assembly PartCAD cannot write instructions for (not an ASSY file, or not meant to be built) is
refused with the reason, and the tab shows that.

**FEA** and **CFD** are the one thing in this panel that *does* something rather than asks about
something: selecting the tab runs a solver, through the same `Shape.analyze_async()` that `pc cae fea` and
`pc cae cfd` run. A part with no `fea:`/`cfd:` section of its own is told so in the tab, which is why the tab
is offered for every part rather than only for the ones that declare it -- "this part says nothing about FEA"
is the answer somebody who went looking for the tab came to read.

Three things about them are worth knowing:

* **Which solver ran is a field over the model, centred.** It is pre-filled with the implementation the host
  actually asked for -- from `cae.defaults`, which is the user configuration's `caeFeaImplementation` /
  `caeCfdImplementation` -- and it is filled in even when the analysis failed, because that is exactly when
  the user needs to see what was tried and type something else. Editing it and pressing Run or Enter re-asks
  with that implementation, which is the same override `pc cae fea --implementation` is.
* **The model is drawn according to its extension**, because which format an analysis writes is the
  implementation's decision and not PartCAD's. `glb`/`gltf`/`stl` get an orbit camera; `png`/`jpg`/`svg` and
  the other still-image types get an image that pans and zooms (wheel to zoom about the pointer, drag to pan,
  double-click to reset). Anything else is named, along with what could have been drawn, and the path the
  model was written to. The model arrives as bytes rather than as that path: a webview has no file system in
  reach, and the daemon may not even be on this machine.
* **The findings are the bottom fifth of the pane, and only when there are any.** An analysis that found
  nothing is a pass, and a pass gives the model the whole pane. This is also what `pc test` checks: its `fea`
  and `cfd` tests fail a part whose analysis produced any finding.

The 3D viewer here is deliberately not `scene.ts`. That one is a studio -- an environment map, a light rig,
contact shadows, auto-rotation -- and an analysis result is the opposite kind of picture: its colours are the
answer, so relighting them falsifies them, and it is read rather than admired, so it must hold still.

**Supply** fills a `ProviderCart` exactly as `pc supply quote` does — an assembly becomes the things to order,
a part is one thing — and asks every supplier of each line item **on its own**. One cart per line item, not one
per supplier: a cart of the whole assembly comes back as a single price for all of it, which cannot say what
any one part costs. An assembly therefore opens on the list of things to order and clicking one zooms in on
where that one can be bought; a part has no list to choose from and opens on the options themselves.

A package that declares no `suppliers:` is the ordinary case, not a failure, so the lookup is skipped for its
items rather than run and reported: in the IDE `pc_logging.error` is a modal popup, and
`Context.find_part_suppliers()` raises one per part.
