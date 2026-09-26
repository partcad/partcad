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

## The 3D view

The pane is a control pane on the left and the canvas beside it. The control pane is a **tree of what is on
screen**, with a checkbox on every item, and the Metadata and Animate boxes and the Opacity slider at the
bottom of it — all of them say what is drawn, so all of them are one pane. There is no name in the corner of the canvas: the first item
of the tree is the object, and it says the same thing where it can also be switched off.

**The tree is the object.** What arrives over the protocol is one node tree and nothing else, whatever is being
shown, and the pane is that tree read out as rows:

| Object | The tree |
| --- | --- |
| a **part** or a **sketch** | one node: itself |
| an **assembly** or a **scene** | a node per thing it holds, nested as deeply as it goes — the very hierarchy PartCAD instantiates it as |
| an **interface** | a node per port it is drawn with, and a sub-assembly per interface it inherits |

There is no per-kind case anywhere in the renderer or the pane, and a tree one node deep is not a shape either
of them knows about. Under every node, whatever kind of node it is, the pane lists what that node declares about
connections: a row per interface instance with the ports it is made of underneath it, and a `ports` row for the
ports that belong to no interface. A port is listed exactly once — one coordinate frame, one checkbox.

**A port is drawn as its triad and as the boundary it is drawn with.** The triad is what a port *is*: a
coordinate frame, with the long blue line its `+Z`. Most ports also name a sketch — the circle of a hole, the
profile of a rail — and that is the shape the connection happens across, which is what makes an opening in a part
readable as one. It is drawn in the blue of that Z axis, unlit and not tone-mapped, so the two read as one
annotation rather than as two things that happen to be blue (`PORT_COLOR` in `nodes.ts`, and
`src/test/suite/viewerPorts.test.ts`, which holds the value to what `AxesHelper` actually puts in its geometry).
Both are registered under the port's own item, so one checkbox draws or hides the pair.

It is **half opaque**, and that is a property of the annotation rather than a setting: a boundary is drawn across
the opening it is the shape of, so a solid one hides the very hole it is pointing at. It writes no depth, so the
near and far faces of a through hole both show. And the **Opacity slider does not touch it** — the slider is
about the shape, an annotation has an opacity of its own, and a material that says it is one is skipped
(`userData.annotation`, read by `setOpacity`). Otherwise moving the slider at all would take the 50% away, and
returning it to 100% would hide every hole behind a solid disc.

**An edge that bounds no face is drawn as a line.** glTF carries line segments as well as triangles, but
`export_gltf` writes a shape's free edges only beside its faces — a sketch of open lines alone, such as the bend
lines of `examples/produce_part_sheet_metal`, used to come out as a file with nothing in it, and the panel showed
nothing. `wrapper_gltf._to_glb` writes those edges itself, as a `LINES` primitive in the frame the exporter writes
its triangles in, and only when the exporter drew none; the renderer gives every line one unlit material of its
own (`restyle` in `scene.ts`).

**What a shape's metadata says about its elements is pinned to them.** A node carries the `metadata` PartCAD built
it with, untouched, and its `annotations` are one record per element — for a DXF, what its XDATA says against a
line: the angle, the radius and the direction of a bend. Every record with something said in it becomes a text
callout at the middle of its element's points, headed by its layer where it has one (`callouts.ts`, tested by
`src/test/suite/viewerCallouts.test.ts`). The callouts are DOM over the canvas (`CSS2DRenderer`), built node by
node like every other pane, and belong to the node's own item, so the box that hides a node hides what is said
about it; the **Metadata** box, on by default, hides all of them at once. The box is offered only while the model on
screen has at least one callout (`hasCallouts`), and keeps its state from one object to the next.

The sketches arrive on the **root node**, keyed by the reference the ports name (`port_sketches.py`): one entry
per sketch however many ports point at it, so a bolt pattern of four holes carries one circle, parsed once and
drawn four times. They are placed like a child node — the port's location, converted — because they have been
through the exporter; the triads are placed in PartCAD's own frame, because they have not.

What starts out ticked follows from depth and nothing else. The object's own ports are drawn, because those are
the few it says are its own; the ports of everything inside it are not, because an assembly of forty parts has a
frame at every hole of every one of them and all of that at once is not a view of anything.

The `ports` and `interfaces` rows **start folded**. The hierarchy is what the pane is for, and those two run to a
dozen rows for a part and hundreds for an assembly; unfolded they bury what they are attached to. An interface
*instance* is not one of those groups — it is one interface with the ports it is made of — so it stays open inside
the folded group. Folding is about the rows and not about what is drawn: the object's own ports are still shown.

**Pointing at a part or a sub-assembly flickers it** — seven times a second, driven by the clock rather than by a
frame count, so the rate holds whatever the renderer manages (`FLICKER_HZ` and `flickerOn` in `nodes.ts`). It is
the one thing that says "this row is that shape" without moving the camera or recolouring anything. A
sub-assembly has no geometry of its own, so what flickers is its whole subtree; the ports and interfaces in that
subtree do not, because what is being pointed at is the shape, and a port is already told apart by the triad
drawn at it. Only what is already drawn flickers: an item switched off in the pane stays off, since making it
appear on hover would say the opposite of what its box says.

A box switches its item and everything under it off without touching what is under it, so unchecking an assembly
node hides the ports inside it and checking it again brings back exactly the ones that were on. A ticked box
whose subtree is not entirely on is shown indeterminate, which is the only way a collapsed row can say that
something below it is hidden. What the user switched off survives a show of the same object — the one that says
`keepCamera`, an edit saved and re-rendered — for the reason the camera does.

The camera is framed on everything the show carries, checked or not: a model that reframed itself on every
checkbox would be unusable.

**Placements are not baked into the geometry.** A node's `gltf` is its own shape in its own coordinate system
and its `location` says where the node sits, exactly as the BREP form carries it, so the renderer composes the
locations down the tree — one `THREE.Group` per node, and a port's triad under the node that declares it. One
glTF per node rather than one for the whole object, because a node is what a reader switches off, and what it
switches off has to be its own buffer to be hideable.

## How a shape gets onto the screen

```text
partcad (any process)                       ide/vscode (extension host)     webview
────────────────────                        ───────────────────────────────────     ───────
Shape.show() / Interface.show()
  │
  │ get_representation(ctx, FORM_GLTF)
  ▼
shape_gltf.convert_async()                  one node tree, BREP at its nodes
  │                                         (no OCP in this process)
  ▼
wrapper_gltf.py  ── in a sandbox ──▶ build123d.export_gltf(binary=True), per node
  │                                          │
  │                                  GLB ──▶ zlib ──▶ base64
  ▼
partcad_ide_client.show()                   the same tree, glTF at its nodes
  │
  │  TCP 127.0.0.1:9137, framed JSON  ───────▶  PartcadViewerServer
  │  ◀───────────────────────────────────────  ack
                                               │
                                               │ zlib.inflate, base64, per node
                                               ▼
                                          PartcadViewer  ── postMessage ──▶  three.js
                                                                             GLTFLoader
```

## Why it is shaped this way

**The core never holds a live OCP object.** PartCAD carries geometry as BREP-byte envelopes and does every
CAD operation in a sandboxed interpreter. Tessellation is a CAD operation, so it happens in `wrapper_gltf.py`,
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
| `src/partcad/viewer.py` | Core entry point: calls the client, and decides about the camera |
| `src/partcad/shape_envelope.py` | **The node**, in both forms, and the one composition that places one |
| `src/partcad/shape_gltf.py` | The glTF form: the same tree, tessellated in one sandbox |
| `src/partcad/wrappers/wrapper_gltf.py` | Sandbox: a tree's BREP → compressed glTF, node by node |
| `src/partcad/shape_ports.py` | What a node carries about connections |
| `src/partcad_ide_client/protocol.py` | **Normative** description of the wire format |
| `src/partcad_ide_client/client.py` | Python client |
| `src/viewer/protocol.ts` | The same wire format, in TypeScript |
| `src/viewer/PartcadViewerServer.ts` | The listening socket |
| `src/viewer/PartcadViewer.ts` | The "PartCAD Viewer" webview panel, and the tab fetches |
| `src/webview/viewer.ts` | The panel shell inside the webview: tabs, routing |
| `src/webview/messages.ts` | The `postMessage` contract between the two, and the daemon payloads |
| `src/webview/scene.ts` | The three.js renderer behind the 3D tab: the node tree as groups |
| `src/webview/nodes.ts` | The vocabulary the renderer and the pane share about the tree |
| `src/webview/frames.ts` | PartCAD's frame against glTF's, and the one conversion between them |
| `src/webview/tree.ts` | The 3D view's control pane: the rows, the boxes, and what is to be drawn |
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

**Placements are the exception, and so are ports.** Neither goes through the exporter: a node's `location` and a
port's are raw PartCAD locations, millimetres and Z-up. So a placement `L` is applied as `TO_GLTF * L *
FROM_GLTF` — convert the point into PartCAD's frame, move it there, convert the answer back — and a node's ports
go under a group carrying `TO_GLTF`, which leaves each port's own transform expressed exactly as PartCAD stated
it. Getting this wrong lays the model on its side or puts it a thousand times too far away.

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
auto-rotating orbit camera framed on the model, drei `<Stage>`-style lighting, the hemisphere and point lights
`Part.js` adds, `MeshPhongMaterial`, and a loading overlay showing model size and progress.

It departs from `Part.js` in four places, each for a reason:

- **No React or react-three-fiber.** A lot of bundle for a single canvas.
- **`RoomEnvironment` instead of `environment="city"`.** drei's presets are HDRIs fetched from a CDN. The
  panel's CSP forbids any network request, and an IDE has to work offline.
- **No −90° X rotation on the model.** `Part.js` loads OBJ, which has no scene graph and no units, so it has to
  stand the geometry up itself. glTF has both — see "Coordinates and units" above.
- **No shadows.** `<Stage shadows="contact">` puts a catcher under the model and casts onto it, which is a
  studio's floor; a CAD reader is looking at the shape, not at where it sits. A flat model made the cost plain:
  a sketch lies *in* that catcher, so it z-fought with the very thing whose shadow it was catching and shadowed
  itself, which is why a sketch could not be seen at all. The catcher, the shadow map and every cast/receive
  flag are gone rather than worked around. Materials are **double-sided** for the same family of reason:
  nothing says which way a lamina's one face points, and the camera orbits past both sides of it.

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
  with that implementation, which is the same override `pc cae fea --implementation` is. Once it has been
  typed in, it is the user's: a later answer no longer pre-fills over it, however long the run that produced
  the answer had been going.
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
auto-rotation -- and an analysis result is the opposite kind of picture: its colours are the
answer, so relighting them falsifies them, and it is read rather than admired, so it must hold still.

**Supply** fills a `ProviderCart` exactly as `pc supply quote` does — an assembly becomes the things to order,
a part is one thing — and asks every supplier of each line item **on its own**. One cart per line item, not one
per supplier: a cart of the whole assembly comes back as a single price for all of it, which cannot say what
any one part costs. An assembly therefore opens on the list of things to order and clicking one zooms in on
where that one can be bought; a part has no list to choose from and opens on the options themselves.

A package that declares no `suppliers:` is the ordinary case, not a failure, so the lookup is skipped for its
items rather than run and reported: in the IDE `pc_logging.error` is a modal popup, and
`Context.find_part_suppliers()` raises one per part.
