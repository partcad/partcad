# Digital Thread

The panel is a strip of tabs over one object, not a canvas:

| Tab | Shown for | Where it comes from |
| --- | --- | --- |
| **Requirements** | an object that declares `requirements:` | the daemon's `requirements.check` (the verdicts `pc test -f requirements` reaches) |
| **3D** | everything | the viewer protocol, from whichever `partcad` asked for the shape to be shown |
| **2D** | parts, assemblies, scenes, sketches | the daemon's `render.inline` (a picture `pc render` makes) |
| **Draft** | parts, assemblies | the daemon's `render.inline`, with a drawing package (`pc render -e`) |
| **FEA** | parts that declare `fea:` scenarios | the daemon's `cae.list` (what the part declares for each analysis) and `cae.analyze` (what `pc cae fea -f <name>` runs) |
| **Dynamic FEA** | parts that declare `dynamic:` scenarios | the daemon's `cae.list` and `cae.analyze` (what `pc cae dynamic -f <name>` runs: natural frequencies and mode shapes) |
| **Heat Transfer** | parts that declare `thermal:` scenarios | the daemon's `cae.list` and `cae.analyze` (what `pc cae thermal -f <name>` runs) |
| **CFD** | parts that declare `cfd:` scenarios | the daemon's `cae.list` and `cae.analyze` (what `pc cae cfd -f <name>` runs) |
| **Build vs Buy** | parts, assemblies | the daemon's `manufacturing.tree` and `manufacturing.details`, and the user's choices from `~/.partcad/garage` |
| **Build** | whatever is built | the daemon's `manufacturing.plan` (the order `pc instructions` writes its pages in) |
| **Buy** | whatever is bought | the daemon's `supply.quote` (the cart `pc supply quote` fills) |
| **Bill of Materials** | parts, assemblies | the daemon's `bom` (what `pc bom` prints) |
| **Assembly** | assemblies | the daemon's `assembly.guide` (the book `pc instructions -t html\|pdf` writes) |
| **Test** | everything | the daemon's `test.report` (the checks `pc test <object>` runs, and `partcad/test/catalog.py`) |
| **Simulation** | parts, assemblies that declare `simulate:` | the daemon's `simulate.list` (what the object declares) and `simulate.run` (what `pc sim -f <name>` runs) |

The 3D view is what a show opens on: "show this part" means the geometry. Requirements is the one tab in front
of it, and only for an object that declares any — see below. The rest are questions about
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

The `<ports>` and `<interfaces>` rows **start folded**, and so does every **part**. The hierarchy is what the pane
is for, and those two run to a dozen rows for a part and hundreds for an assembly; unfolded they bury what they are
attached to. A part — a node that holds no other node — has nothing under it but those two, so it is folded as
well: otherwise every part of an assembly is followed by two group rows before the next part, and the list of what
the assembly holds is broken up by rows that are not any of it. That rule does not ask about depth, so a part shown
on its own starts folded too. A sub-assembly stays open, and its own `<ports>` and `<interfaces>` rows sit among the
things it holds, which is why they are named in angle brackets and drawn in italics: a link can be called `ports`,
and a group row is not a link. An interface *instance* is not one of those groups — it is one interface with the
ports it is made of — so it stays open inside the folded group. Folding is about the rows and not about what is
drawn: the object's own ports are still shown.

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

The camera is framed on every shape the show carries, checked or not: a model that reframed itself on every
checkbox would be unusable. On the shapes, and not on the triads and boundaries drawn at their ports: a triad
reaches a quarter of the model out along its port's positive axes only, so counting them leans the frame toward
every port — including the ports of everything inside an assembly, which start out unticked. An interface, which
has no shape but its ports, is framed on those. It is fitted to the narrower of the canvas's two fields of view,
so a model in a narrow panel is not cut off at both sides.

**Placements are not baked into the geometry.** A node's `gltf` is its own shape in its own coordinate system
and its `location` says where the node sits, exactly as the BREP form carries it, so the renderer composes the
locations down the tree — one `THREE.Group` per node, and a port's triad under the node that declares it. One
glTF per node rather than one for the whole object, because a node is what a reader switches off, and what it
switches off has to be its own buffer to be hideable.

### A SpaceMouse

A 3Dconnexion SpaceMouse moves the camera of the 3D tab, and of the model an FEA or CFD analysis returned, in
3Dconnexion's **object mode**, the one its own driver defaults to: the cap is the model. Push it left and the
model goes left, push it in and the model goes away, twist or tilt it and the model turns about what the camera
is looking at. The second button — the right one of two, or the key labelled **Fit** — frames the model again.
Moving the cap pauses the Animate rotation without unticking it. `partcad.spaceMouse.enabled`,
`partcad.spaceMouse.sensitivity` and `partcad.spaceMouse.invert` (a list of the axes to reverse: `tx`, `ty`,
`tz`, `rx`, `ry`, `rz`) tune it.

The device reaches the renderer by one of two roads, and the platform picks, not the user:

| Where | Road |
| --- | --- |
| Windows, macOS | The **Gamepad API**, inside the webview. Chromium enumerates HID multi-axis controllers as gamepads there and does not blocklist 3Dconnexion's ids, and VS Code's webview iframe needs no `allow="gamepad"` because Chromium's default allowlist for it is `*`. No driver is needed, and it works for a remote workspace too, because the webview is always drawn locally. Chromium reveals a gamepad to a page only after it has been moved once with that page open. |
| Linux | **spacenavd**, read by the extension host over its socket (`/var/run/spnav.sock`, then `$XDG_RUNTIME_DIR/spnav.sock`) and forwarded over `postMessage`. spacenavd is how every Linux application reads the device, and it takes it for itself (`grab`, on by default in `spacenavd.conf`), so Chromium receives nothing from it while it runs; an older device reports relative motion besides, which is not a joystick at all. |

The extension host is on the workspace's machine, which in a remote window is not the one the SpaceMouse is
plugged into. Its spacenavd socket has to be brought there: this repository's dev container binds the host's at
`/var/run/spnav.sock` (`.devcontainer/host-sockets-init.sh` resolves it, and leaves an empty file where there is
none, because a bind that turns into a directory stops the container from starting), and over Remote-SSH a
`RemoteForward` to `$XDG_RUNTIME_DIR/spnav.sock` does it — the README has the line. Docker binds the socket
that is there when the container starts, so a spacenavd restarted under a running container is reached again
only once the container has been restarted. A remote window that finds no socket says so, once, in the `PartCAD`
output; nothing else would, since the cap is pushed and the model simply sits there.

While spacenavd is connected the Gamepad API is not consulted, so a device both roads can see does not move
the model twice. spacenavd tells every client about every push, so the host forwards its events only to a
panel that is visible in the focused window, and tells the renderer the same thing for the Gamepad API.

The one place that knows what the device's axes mean is `src/webview/spacemouse.ts`. spacenavd's events are
forwarded untouched, in its own frame and counts, and converted there (`fromSpacenav`), beside the Gamepad
API's (`fromHid`); `src/test/suite/viewerSpaceMouse.test.ts` holds each road to the other through spacenavd's
default axis map, because a reversed axis is plausible on screen and would not otherwise fail anything.

Each 3D view of the panel — the 3D tab (`scene.ts`) and the model of an analysis (`cae.ts`) — attaches itself
to the panel's one `spaceMouse` as a `Navigable` and asks it, once a frame from its own render loop, to move its
camera. Only the view whose pane is on screen is moved, and **Fit** frames that one: every view goes on drawing
while its pane is hidden, so a view that moved whenever the cap did would turn a camera nobody is looking at. A
push starts and ends like a drag, through the orbit controls' `start` and `end` events, so the canvas painter
draws a big model as boxes while the cap moves it too. The device's state lives with it rather than in `scene.ts`,
because the 3D view's module finishes loading only once its surface exists, and the host can have said whether
spacenavd is connected before then. A new 3D pane that does not attach is one the device does nothing in.

Which button is **Fit** depends on the road and, for spacenavd, on the device. The Gamepad API numbers buttons
in HID order, where the first two are Menu and Fit on every 3Dconnexion device, so Fit is always `1`.
spacenavd renumbers the scattered buttons of a SpaceMouse Pro and an Enterprise into a range of its own (Fit is
`5` and `13`), and a button event does not say which device it came from. So the host asks for spacenavd's
protocol v1 and then for the device type, again whenever a device comes or goes; a spacenavd too old to answer
predates the renumbering, so HID order is right for it too (`spacenavFit`).

The orbit controls keep the camera's up direction, so the navigation is a turntable: a roll about the line of
sight (`rz`) is dropped, and a tilt stops at the poles.

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
| `src/viewer/PartcadViewer.ts` | The "Digital Thread" webview panel, and the tab fetches |
| `src/webview/viewer.ts` | The panel shell inside the webview: tabs, routing |
| `src/webview/messages.ts` | The `postMessage` contract between the two, and the daemon payloads |
| `src/webview/scene.ts` | The three.js renderer behind the 3D tab: the node tree as groups |
| `src/webview/surface.ts` | What every 3D pane draws with: WebGL, else WebGPU, else the canvas painter |
| `src/webview/painter.ts` | The canvas painter: the scene filled on the CPU, for a window with no GPU it can use |
| `src/webview/nodes.ts` | The vocabulary the renderer and the pane share about the tree |
| `src/webview/frames.ts` | PartCAD's frame against glTF's, and the one conversion between them |
| `src/webview/tree.ts` | The 3D view's control pane: the rows, the boxes, and what is to be drawn |
| `src/webview/spacemouse.ts` | A SpaceMouse: which gamepad is one, what its axes mean, and how it moves the camera of the view on screen |
| `src/viewer/spacenav.ts` | spacenavd's socket, read in the extension host for Linux |
| `src/webview/render.ts` | The 2D and Draft tabs: the control pane, the file, and Save |
| `src/webview/bvb.ts` | The Build vs Buy tab: which lines are needed and how many, and the table |
| `src/webview/build.ts` | The Build tab: the build plan, and the page of the selected step |
| `src/webview/bom.ts` | The Bill of Materials tab |
| `src/webview/assembly.ts` | The Assembly tab: the instructions in a format, with Save |
| `src/webview/document.ts` | `partcad/document.py`'s model, drawn: a page, or the book paged through |
| `src/webview/supply.ts` | The Buy tab: the list, and one item's suppliers |
| `src/webview/requirements.ts` | The Requirements tab: the marks, and the features with what validates each |
| `src/webview/test.ts` | The Test tab: every check with its mark, and the one selected - its verdict, findings, artifacts and text |
| `src/partcad/test/report.py` | One object's `pc test` as a list of verdicts, for this tab |
| `src/partcad/test/catalog.py` | What each check is and what to do when it fails, for this tab and for the documentation |
| `src/partcad/requirements.py` | What a requirement means and whether the model meets it, for this tab and for `pc test` |
| `src/common/garage.ts` | Where the Build vs Buy choices are kept, on this machine |
| `src/webview/analysis.ts` | The Analysis tabs (FEA, Dynamic FEA, Heat Transfer, CFD): which apply, the scenarios declared, the Simulation tab's toolbar ("Analysed by", "Analyse"), and what each run answered |
| `src/webview/packagePicker.ts` | The package field "Drawn by", "Simulated by" and "Analysed by" are: an editable combo box, and the quick choices it offers |
| `src/webview/cae.ts` | What an Analysis tab draws of the selected scenario: the result model, and the findings |
| `src/webview/scenarioList.ts` | The list of declared entries the Simulation and Analysis tabs share: rows, verdict marks, the keyboard |
| `src/webview/simulation.ts` | The Simulation tab: the simulations declared, and the scene before and after one ran |
| `src/partcad/simulation.py` | What `simulate:` declares, how a run goes, and the pictures a plugin is asked to take |
| `src/partcad/cae.py` | What a part declares about an analysis -- its named scenarios -- and in what units |
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

## The package field

Three toolbars name somebody else's package to do the work -- the Draft tab's **Drawn by**, the Simulation tab's
**Simulated by**, and each Analysis tab's **Analysed by** -- and all three are one widget, `packagePicker.ts`: an
editable **combo box**. The field is always filled in, with the package that runs when nobody chooses one (what
the object names, or the configured default); its arrow, or Down, shows the quick choices under it -- the
packages PartCAD knows of for the job, with that one marked and saying why ("named by the scenario", "the
configured default") -- and typing narrows them to the ones that match; and any other name typed into it is
taken as well, because a package of the user's own is as good a package as any registered one. The quick
choices are made one way for all three (`quickChoices`), so they cannot come to disagree about what is offered.

A name is taken when it is chosen from the list, when Enter is pressed, and when the field is left with a new
one in it -- never while it is being typed -- and leaving it empty, or Escape with the list closed, puts back the
one in use. It is not a `<select>`, which cannot take a name it does not list, nor an `<input>` with a
`<datalist>`: Chromium filters a datalist by what the field says, and this field always says something, so the
list would only ever offer what is already chosen -- and it draws the list in the system's colours rather than
the editor's. The toolbar holding it is made once and kept, so an answer arriving does not take the field from
somebody typing in it, and the button beside it (**Simulate**, **Analyse**) is pressed without leaving the field,
so a name typed and not entered runs once, with that name.

## The 2D and Draft views

Each is the same pane: the control pane on the left, what to render to along the top, the file under it, and a
Save button. Both are `pc render` of one object to one file type, and what differs is who implements the type —
the 2D tab asks PartCAD's own renderers for a picture (PNG, JPEG, SVG), the Draft tab names a package that
draws, in **Drawn by** (the package field, above; `//pub/feature/render/draftwright` unless another is chosen or
typed), and offers whatever that package's `render:` section declares (`pc render -e`, and
`examples/feature_render_custom`). The file comes back as bytes rather than as a path, because the daemon may
be on another machine; the host keeps it in a temporary file so that Save has something to copy.

The control pane is the 3D view's, over the same node tree, with the same rules about what a box does to what
is under it — and it is the *same selection*: all three Design tabs read and write one store, so switching tabs
shows what was ticked and a box cleared on one is cleared on the others. What the boxes *produce* is what
differs, since nothing here can switch a shape off on a stage: the picture is made by PartCAD and arrives
finished. So the ticked boxes become a **filter**, sent with the render and applied to the assembly PartCAD
built — the same `--filter` `pc render` and `pc export` take, and the same mask `pc filter` writes a new object
from (see `docs/source/assy.rst`) — plus, on the 2D tab, **which ports** to draw. The render is asked for
again, after a short settling delay, whenever a box changes.

Four things follow from what the two tabs are:

* **The root's box is ticked and fixed.** The object is what is being rendered; there is no picture with it
  cleared.
* **Draft lists no ports or interfaces.** A dimensioned drawing is of the solid, and nothing is drawn at a port
  in one. It still *keeps* them: the selection is shared, so a port switched off on the 2D tab survives a visit
  to Draft, which has no row to hold it.
* **The 2D tab draws the ports the panel says**, by name — `--with-ports` / `--with-interfaces` for whether,
  and `--port` for which, so unticking one of a part's twelve ports takes that one frame off the picture.
  `--with-internals` comes with a port of something *inside* an assembly, since an assembly is otherwise taken
  at its word about which ports are its own. What starts out ticked is the 3D view's rule — the object's own
  ports and nothing deeper — because one selection cannot start out two ways; so the first 2D picture of an
  object that declares ports has them on it.
* **A part has nothing to filter.** Its tree is one node, so the pane lists the object and (on 2D) its ports,
  and no filter is sent.

A node is named in the filter by its **label**, which is the name the assembly addresses that link by: the
`name:` of the ASSY link, the part it places, or — for a child nothing named — its position, `link#2`. A port is
named by the path of those labels and then the port (`head:head_half_1:TL-m3`), which is exactly the name
PartCAD reports it under, so both sides compose one string from the same parts.

## The tabs beside the 3D view

**Test**, under Validation, is every check `pc test` runs, and is always enabled and first: every object has
checks, if only to say that they do not apply to it. An object that belongs to no package - a shape shown from a
script - has nothing to ask the daemon about, and the tab says so rather than offering a list. Opening it asks twice, in a row: `test.report` without `verify`, which
runs nothing and lists every check with those that do not apply saying why, and then with it, which runs the
checks as `pc test <object>` runs them and through the same cache, so the panel and the command line give the
same verdicts. The list is on screen, every other mark pending, for as long as the second takes. It opens on the
first failure, or else the first finding, or else the first check that applies, and keeps the one the reader
clicks. What each check is - when it applies and what to do when it fails - is its entry in
`partcad/test/catalog.py`, the same text the documentation's list of checks is generated from. A check that left
something behind to look at offers it with **Show in the Digital Thread**, which moves the panel to Design and
shows that object the way the explorer would (`showObject`, then the explorer's `partcad.inspect*` command,
without remembering it as the selection): for an interference, the two parts where the assembly places them and
a sub-assembly `interference` of what they share, registered by the daemon under a name worked out from the pair.

Each non-3D tab is fetched on first look and cached until the next show, so opening one costs one daemon round
trip and switching back to it costs none. Every request carries the generation of the object it was made for and an
answer for an older one is dropped: a bill of materials walks the whole assembly tree and a supply quote goes
out to the network, so a round trip easily outlives a change of selection.

**Requirements** is what the object was asked to be, which is read before what it is — so it is the one tab in
front of Design, and it is there only for an object that declares a `requirements:` section: a tab with nothing
to say in front of the strip would only push the others along. Whether there is one is asked on every show,
like Build vs Buy, and it is cheap: `requirements.check` without `verify` reads the declaration and builds
nothing. The strip is rebuilt when that answer changes whether the tab is offered, and a reader who was on the
tab for the last object lands on it again.

Opening the tab is what asks for the verdicts (`verify: true`), and they are exactly what `pc test -f
requirements` reaches, because both are `partcad/requirements.py`. While they are on the way every mark is
pending — a requirement nobody has measured yet is neither met nor unmet. Then each port, interface and physical
property required gets a green or a red mark (the editor's own test-explorer colours) beside what was required and
what was found. A `simulate:` entry or an analysis scenario naming a feature that is not declared, and a
requirement that cannot be read, are listed after them as problems, and fail the same way.

The features follow, as a table: the name, what the feature is, and what validates it — a banner per
`simulate:` entry that names it (`feature:`), then a banner per analysis scenario that names it (an entry of a
part's `fea:`, `dynamic:`, `thermal:` or `cfd:` with a `feature:`), labelled with its analysis as its tab is --
**FEA: loaded** -- because scenarios are named within an analysis, in a colour of its own and with the command
that runs it as its tooltip (`pc cae fea -f loaded`), then an **LLM** banner on every feature, whose tooltip
names the skill that does it: "Validate using /pc-validate". The LLM is on the features a simulation or an
analysis already stands behind as well, because each demonstrates the claim it was written for and cannot say
whether that is the whole of the feature.

**Bill of Materials** is `Assembly.get_bom_detailed_async()` — the tree flattened and counted, with the store
data that says what to order — in the columns `pc bom` prints it in.

**Build vs Buy** is the one tab asked for before it is looked at. Whether the Build tab and the Buy tab apply
depends on what the user decided here, over a tree only the daemon can read (`manufacturing.tree`: an
assembly's links, a part's stock, and what each declares about being built and bought — no geometry, so it is
cheap enough to ask on every show), so it is asked for on every show of a part or an assembly and the
Manufacturing strip is rebuilt when it arrives; until then Build and Buy are disabled and say why. The table is
worked out from that tree in the webview (`bvb.ts`), on every click, rather than asked for: the daemon answers
one request at a time, and a switch that waits for a round trip feels broken. The rule it applies — what a line
that can only be bought, only be built, or both is; that what a line is made of is needed only while it is
built — is the same one `partcad.build_plan` orders the Build tab by, and the two have to agree. The thumbnails
and measurements (`manufacturing.details`) come a few lines at a time, so that the table fills in and other tabs
get a turn; the daemon caches each thumbnail under the shape's hash *and* its size. What the user chose is kept
by the extension host, in `~/.partcad/garage/default/bvb/<object>.json` — never by the daemon, which may be
somebody else's — and sent with every Build and Assembly request.

**Build** is the build plan (`manufacturing.plan`) on the left and a page of the instruction book on the right.
The plan is asked for alone first, because it is cheap and the list is what the user came for, and then again
with `document: true` for the pages, which takes every illustration to be drawn. Each plan item names the page
it shows, so the list and the book are one plan in one order.

**Assembly** is the very document `pc instructions -t html|pdf` writes: built once in
`partcad/assembly_guide.py` as the renderer-independent model in `partcad/document.py`, handed over by
`assembly.guide` through `document.to_data(embed_images=True)`, and drawn by `src/webview/document.ts` one page
at a time, in the format, with the **Recursive** and **Build parts** choices, the header asks for. The file
itself comes back beside the model and is kept by the host for **Save…**: a PDF is not something a webview can
show, and both are written from the one model. The illustrations are inlined as data URIs rather than pointed at, because they live in a temporary
directory that is deleted as soon as the document is built — and because the CSP forbids fetching anything
anyway. An assembly PartCAD cannot write instructions for (not an ASSY file, or not meant to be built) is
refused with the reason, and the tab shows that.

The **Analysis** tabs -- **FEA**, **Dynamic FEA**, **Heat Transfer** and **CFD**, in that order -- are the one
thing in this panel besides Simulation that *does* something rather than asks about something: selecting a
scenario runs a solver, through the same `Shape.analyze_async()` that `pc cae <analysis>` runs. Each tab is named
after its analysis on the command line -- `fea` (static), `dynamic` (modal: natural frequencies and mode
shapes), `thermal` (steady-state heat transfer) and `cfd` -- and that id, not the label, is what the host asks
`cae.analyze` for, so all four are one pane (`AnalysisView`, drawing with `CaeResult`) and one command
(`partcad.cae`) and a fifth analysis is a row in `ANALYSIS_TABS`/`ANALYSIS_LABELS` (`src/webview/messages.ts`), a
pane in the HTML and an entry in the host's `TAB_COMMANDS`.

A part's section for an analysis is a map of **named scenarios**, the way `simulate:` is a map of named
simulations: each one set of boundary conditions, with a `desc:`, the requirement `feature:` it demonstrates, and
optionally an `implementation:` and `params:` of its own. (The older unnamed form, `fea: {fix: ..., load: ...}`,
is read as one scenario named `default`.) What a part declares is asked on every show of a part, once for all four
tabs -- `cae.list`, which reads the configuration and runs nothing, asked under the group's own id (`analysis`)
-- exactly as Simulation's `simulate.list` is, and the strips are rebuilt when it arrives. A tab is enabled only
when the part declares at least one scenario for it; until the answer arrives every tab says it is asking, a
daemon that cannot answer leaves them disabled saying so, and one that declares none says that in its tooltip
("This part declares no CFD scenarios: it has no 'cfd:' section"). The group is enabled when any of its tabs is.
A section that is there and cannot be read is the exception: its tab is enabled, so that the sentence saying what
is wrong with it -- `cae.list`'s `errors` -- can be read where the model would be.

The tab is laid out like Simulation, with the same list (`scenarioList.ts`): the scenarios on the left, in the
order the part declares them, the first selected, each row's tooltip its `desc:`; the selected one on the right.
Selecting one runs it -- `cae.analyze` with `scenario`, which is `pc cae <analysis> -f <name>` -- the first time
it is looked at for this object, and the answer is kept, per scenario *and* per implementation, until the next
show, so going back to one already run shows it rather than starting a solver again. Before each name is how its
run went: a green ✓ when it ran and found nothing, a red ✗ when it found something, a red ! when it could not
run, … while it runs, and an empty slot of the same width before it has. A scenario that could not run -- one
that cannot be read, a solver that would not start, no sandbox to start it in, an implementation that does not
resolve -- is not a refusal of the request any more: it comes back as that scenario's `error`, and the tab shows
the sentence where the model would have been. `pc ide view --analysis-fea --scenario <name>` opens the tab on
that scenario instead of the first (the show's `scenario`, as for `--validation-simulation`), and `pc ide state`
reports each analysis tab's selected scenario, what each is set to run with, and each one's verdict.

Three things about the selected scenario are worth knowing:

* **Over it is the Simulation tab's toolbar**, which is the Draft tab's: **Analysed by** is the package field
  (see "The package field"), filled in with the solver the scenario runs with unasked -- its own
  `implementation:`, else the configured default, `cae.defaults` (the user configuration's
  `caeFeaImplementation`, `caeDynamicImplementation`, `caeThermalImplementation` or `caeCfdImplementation`),
  which the host adds to `cae.list`'s answer -- and offering the solvers `//pub/feature/cae` registers for the
  analysis (`CAE_IMPLEMENTATIONS`, the analysis's `SIMULATION_PLUGINS`). That is the order `pc cae` resolves
  them in, so that one is never sent as an override; another, chosen or typed, runs the scenario with it, as
  `pc cae <analysis> --implementation`, and **Analyse** runs it afresh with what the field says. A scenario
  naming a solver nobody registered (its package's own, `:fea`) is offered as itself, first. Under the toolbar
  is what the scenario says it is (`desc:`), as under a simulation's.
* **The model is drawn according to its extension**, because which format an analysis writes is the
  implementation's decision and not PartCAD's. `glb`/`gltf`/`stl` get an orbit camera; `png`/`jpg`/`svg` and
  the other still-image types get an image that pans and zooms (wheel to zoom about the pointer, drag to pan,
  double-click to reset). Anything else is named, along with what could have been drawn, and the path the
  model was written to (`<part>.<analysis>.<scenario>.<extension>`). The model arrives as bytes rather than as
  that path: a webview has no file system in reach, and the daemon may not even be on this machine.
* **The findings are the bottom fifth of the pane, and only when there are any.** An analysis that found
  nothing is a pass, and a pass gives the model the whole pane. This is also what `pc test` checks: its `fea`,
  `dynamic`, `thermal` and `cfd` tests fail a part whose analysis produced any finding.

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

The Validation group holds **Test** (above), **Simulation** and **Process Emulation**, which has nothing in it
yet and is always disabled -- so the group is always enabled, for Test, and opens on it. Simulation is offered
only for an object that declares a simulation: whether it does is asked on every show (`simulate.list`, which reads the `simulate:`
section and runs nothing), exactly as Build vs Buy's tree is, and the panel's strip is rebuilt when the answer
arrives.

The tab is laid out like Build: the simulations on the left, in the order the object declares them, the first
selected (or the one `pc ide view --validation-simulation --scenario <name>` names); the selected one on the
right. Selecting one runs it -- `simulate.run`, which is `pc sim -f <name>` --
the first time it is looked at for this object, and the answer is kept until the next show. What comes back is
the verdict of its `validation:` expression, said once: as a mark before the simulation's name in the list (a
green ✓ when it held, a red ✗ when it did not, a red ! when it could not run, a muted • when there was nothing
to check it against, … while it runs, and an empty slot of the same width before it has run, so the names line
up). The page itself does not repeat the name or the verdict.

Over the page is the Draft tab's toolbar, with the Draft tab's classes: **Simulated by**, which plugin runs it,
and **Simulate**. **Simulated by** is the package field (see "The package field"): its quick choices are the two
plugins `//pub/feature/simulate` registers (`SIMULATION_PLUGINS`), and it is filled in with the one the
simulation names -- matched by what follows its `:`, because a package usually names it through a dependency of
its own (`sim-mujoco:mujoco`), and offered as itself, first, when it is neither. While that one is in it nothing
is overridden; another, chosen or typed, runs the simulation with it (`pc sim --plugin`),
the way choosing a drawing package draws again, and **Simulate** runs it afresh. Answers are kept per
simulation *and* per plugin, so switching back to one already run shows it. Under the toolbar is what the
simulation is about, then two pictures of the scene: before anything moved on the left, after the run on the
right, an arrow between them.

Under the pictures is what the verdict is made of, folded away behind a strip of three titles: **Criteria** (the
`validation:` expression), **Before** and **After** (the two objects the plugin reported, which are what that
expression is evaluated over, as indented JSON with each short array of plain values on one line --
`prettyJson` -- so a position or a quaternion reads as one). A title opens its view and, when it is the one
open, folds it away again; the open one carries ▾. One is open at a time, the pictures shrink to make room
rather than being pushed off the page, and which one is open is kept from one simulation to the next, so the
*after* of several runs can be compared by clicking down the list. A strip rather than three disclosure
triangles, because three of those open at once would leave no room for the pictures.

Those pictures are taken by the simulation plugin, not drawn here. PartCAD asks every run for them, from where
the scene is looked at when it is rendered -- `viewport_origin` and `viewport_up` of its `render: png:`,
the scene's own over its package's, and the corner a part is drawn from when neither says -- and the plugin
draws the scene as its simulator had it at the first instant and the last, both framed alike so that what moved
is seen to have moved. They come back as bytes rather than paths for the reason a render does. A plugin that
takes none -- one older than the request -- leaves the verdict standing and the tab says there are no pictures.
