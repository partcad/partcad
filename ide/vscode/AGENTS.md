# ide/vscode

Visual Studio Code extension providing navigation and UI for `partcad` projects. Node/TypeScript toolchain
(`npm`). Run all commands below from
this directory (`ide/vscode/`).

## The backend

**This extension is a JSON-RPC client and nothing else.** It talks to the standalone `partcad-json-rpc`
executable, translating each `partcad.*` command the UI issues into the CLI-shaped JSON-RPC method and routing
the service's notifications back under the `?/partcad/*` names the handlers listen on. See
`src/common/backend.ts` and `src/common/provision.ts`.

By default it connects over the per-workspace **daemon** (`partcad.serviceChannel: socket`): it runs
`pc daemon start`, reads the printed endpoint, and connects — a socket path on POSIX, a `\\.\pipe\...` name on
Windows, which `net.connect` takes either way. `partcad.serviceChannel: stdio` runs a dedicated process over
stdin/stdout instead. "Restart PartCAD"/reset runs `pc daemon stop` to tear down the warm context.

**What `pc daemon start` prints is checked before it is connected to** (`daemonEndpointIn`). A `pc` with no
daemon for its platform answers with a *sentence* saying so — on stdout, with a zero exit status, which is
where the endpoint goes. Windows `pc` did exactly that until the daemon there was un-gated, and "the first
non-empty line" handed that sentence to `net.connect`: ENOENT about a filename made of English, and a window
with no backend at all. So an answer that is neither an absolute path nor a pipe name means "this installation
has no daemon", and the backend falls back to `stdio` — one service for this window, cold rather than shared,
which is a downgrade and not a failure. It says so in the terminal view, because a user who asked for `socket`
did not get it.

The connect itself retries for a few seconds (`connectEndpoint`). The endpoint `pc` prints is live by the time
it prints it, on both platforms; the retry covers the difference in *how* — a POSIX daemon binds and listens
before it forks, so an early client queues, while the Windows daemon is a separate process whose pipe does not
exist until it is ready, and connecting to a pipe that is not there fails rather than waits.

Where the executable comes from is `resolveServicePath`: the `partcad.servicePath` setting, then an existing
standalone install (`$XDG_DATA_HOME/partcad`, or `%LOCALAPPDATA%\PartCAD` on Windows — `install.sh` does not
run there, so naming the POSIX locations in the report only sent Windows users looking somewhere nothing
installs to), then the extension's own download directory, then the download directory it had before it
changed publisher (see "The marketplace identity" below), then `~/.local/bin` where there is one, then a
plain `PATH` lookup (quoted entries and all: Windows quotes a `PATH` entry containing a space, and the quotes
are not part of the directory's name). That last one is why a user with their own Python needs no download at all -- `pip install partcad`
puts `partcad-json-rpc` on the `PATH`.

**The dialog appears if and only if none of those six resolves.** Anything found is used, silently: an
installation the user already has is never a question. When there is none, `ensureServiceExecutable` offers
exactly the two things that can produce one -- `Download` the standalone bundle, or `Find installed PartCAD` and
point at an environment that already has PartCAD in it. There is no third option, and in particular no silent
one: the second button used to read "Use Python instead" and select a `python` backend that had been deleted
with the language server, so the one choice a user with their own Python would obviously make gave them no
backend at all and a log line nobody reads.

`Find installed PartCAD` asks for a **directory**, not the executable -- someone who just ran `pip install partcad`
knows where their environment is, not what the service is called. `serviceUnder` accepts the environment's
`bin` (`Scripts` on Windows), which is what is asked for because that is the directory holding `pc` and
`partcad` beside the service, and also the environment root, which is the obvious near-miss. The answer is
written to `partcad.servicePath`; the setting is `machine`-scoped, so `Global` is the only target it can go to,
which is right for something that describes this machine rather than a workspace.

`ensureServiceExecutable` returns a `ServiceResolution` rather than a path because of what that write does:
`partcad.servicePath` is in `checkIfConfigurationChanged`, so setting it *is* a restart. The `restarting` case
tells `restartBackend` to stand down and let the configuration change drive the single start -- nothing
serialises two of them, and returning a path here as well would race one start against the other.

**The `PATH` it searches is the extension host's, which is not the one the user's terminal has.** The host
inherits `PATH` from whatever launched VS Code -- a desktop launcher, the Dock, an unactivated shell -- so a
`partcad-json-rpc` inside a Python virtual environment is found only when VS Code itself was started from that
environment. Nothing here consults the interpreter `ms-python.python` has selected; `partcad.interpreter` went
with the language server. So "PartCAD is installed and the extension still offers to download it" is expected
rather than a bug -- and `Find installed PartCAD` is what it is for. This is also why `resolveServicePath` takes an
optional `searched` array and why `reportNoService` in `backend.ts` prints it: the message a user gets has to
name the `PATH` it consulted, or it sends them looking in the environment they can see.

**The `PartCAD` terminal view shows what the CLI shows, and does not render it itself.** Colours, level
prefixes and the multi-line progress footer are a state machine (`partcad_utils.logging_ansi_terminal`) that
the CLI runs on its own side, replaying the structured events a daemon forwards. This extension cannot: it is
TypeScript, and a second implementation of that footer is a second thing to keep correct. So the *service*
runs it -- `partcad_utils.logging_ansi_render.AnsiEventRenderer`, one instance per connection -- and sends what
it drew.

`JsonRpcBackend` asks for that with `log.mode {"ansi": true}` as soon as it connects. The service then sends
`?/partcad/terminal` (base64, written into the pty verbatim) **instead of** `?/partcad/log`, not as well as:
the two carry the same information. The `?/partcad/log` handler stays as the fallback for a service too old to
answer `log.mode`, and `rendersLogs` says which of the two is live.

Three things about it are load-bearing:

- **One renderer per connection.** The footer is drawn by moving the cursor back over the lines it last wrote,
  so two clients sharing a renderer would each erase lines from the other's terminal. The daemon is shared;
  the renderer is not. `log.mode` is handled in the transport beside `daemon.stop`, because the dispatcher only
  sees `(request, session)` and the session belongs to every client at once.
- **`\n` becomes `\r\n` on arrival.** The renderer emits bare newlines, which is right for the CLI -- a real
  terminal has ONLCR on. A pseudoterminal does not, so untranslated output walks off to the right. The
  translation belongs here, where the destination is known.
- **Nothing else may write while it is rendering.** An unrendered line inserted between the renderer's writes
  desynchronises the footer's cursor arithmetic. So `?/partcad/error`/`warn` are not echoed when `rendersLogs`
  is set (the renderer already prints them, in colour), and what remains -- the no-backend reports below --
  happens only when there is no renderer running.

**A backend that never starts reports itself in the `PartCAD` terminal view**, not only in the output channel.
Everything else in that view arrives over the backend's own `?/partcad/terminal` and `?/partcad/log`
notifications, which is precisely what a missing backend cannot send, so `terminal.ts` carries a
`setTerminalWriter`/`writeTerminal` pair: `extension.ts` registers the writer (it owns the terminal, the
reopen/popup settings and the context) and `common/backend.ts` calls it without importing `extension.ts`, which
would be an import cycle. Before that, no backend meant a silent, inert window.

**Daemon handling is the CLI's, not the extension's.** Which socket serves which workspace, whether anything
is answering on it, and how to stop it and wait are `partcad_client`, reached by running `pc`. A second copy of
those rules in TypeScript is a copy that can disagree, and a disagreement means the extension quietly starting
a daemon of its own beside the one `pc` is using. What stays in Node is the socket transport itself, because a
live notification connection cannot be shelled out.

### There used to be a second backend

A Python language server under `bundled/tool`, with PartCAD's dependencies vendored into `bundled/libs`,
selected by `partcad.backend: "python"`. It is gone, along with the setting, `partcad.interpreter`,
`partcad.importStrategy`, the `ms-python.python` dependency, and 3,361 lines of Python.

It was never the only way to do anything: the JSON-RPC backend registers every command the language server did,
and two more. And it could not have worked where it was shipped -- `bundled/libs` held compiled wheels
(`pygit2`, `aiohttp` and `cffi` publish no `py3-none-any` wheel at all) while the `.vsix` is built once, on
Linux, for one CPython. Do not reintroduce a second backend; extend this one.

## The PartCAD Viewer

End-to-end walkthrough, with the data flow diagram and what each tab is:
[docs/partcad-viewer.md](./docs/partcad-viewer.md).

`src/viewer/` is the extension-host half of the viewer: a TCP server on a constant loopback port
(`PartcadViewerServer`) that `partcad` processes connect to, and the webview panel that displays what they
send (`PartcadViewer`). `src/webview/` is what runs *inside* that webview: `viewer.ts` is the shell,
`scene.ts` the three.js renderer, and one module per tab beside it.

**The panel is a strip of tabs over one object, not a canvas.** 3D first, then the bill of materials and the
assembly instructions for an assembly, then FEA and CFD for a part, then supply information for anything that
can be bought. Only the 3D
view comes over the viewer protocol; every other tab is a question about `<package>:<name>` that the renderer
cannot ask itself -- the CSP forbids network access and the daemon is behind the host's JSON-RPC connection --
so it asks the host (`fetchTab`) and the host answers (`tabData`), on first look. Which is why the show
message carries the object's **package**: without it the panel offers the 3D view alone.

None of those tabs is implemented here. `bom`, `assembly.guide`, `supply.quote` and `cae.analyze` are the CLI's
own operations (`pc bom`, the book `pc render -t html` writes, the cart `pc supply quote` fills, the analysis
`pc cae fea`/`pc cae cfd` runs), asked for as data rather
than as a file -- the same rule as everywhere else in this extension: extend the one backend, do not
reimplement it in TypeScript.

The FEA and CFD tabs are the one pair that *acts* rather than asks: selecting one runs a solver. The field
over the model names which -- pre-filled from `cae.defaults` (the user configuration's
`caeFeaImplementation`/`caeCfdImplementation`) and filled in even when the run failed, which is when a user
most needs to see what was tried. The model is drawn by its extension, because the format is the
implementation's choice: a mesh gets an orbit camera, a picture pans and zooms. See
[docs/partcad-viewer.md](./docs/partcad-viewer.md).

Four things about it are load-bearing:

- **Two webpack bundles, two tsconfigs.** The extension host is CommonJS; the webview is a browser context and
  three.js ships its addons as ES modules only, so `src/webview` compiles under `tsconfig.webview.json` (and is
  excluded from `tsconfig.json`). `npm run compile` builds both.
- **The listen options are platform-specific, and getting that wrong is silent.** `SO_REUSEPORT` lets a second
  window share the viewer port instead of losing it, and libuv implements it only where it also load-balances
  — Linux and the BSDs — *rejecting the bind with ENOTSUP everywhere else*. Asking for it unconditionally
  therefore took the whole viewer down on Windows and macOS, with one line in the output channel to show for
  it, from the moment VS Code shipped a Node new enough to pass the option through (22.12). There is nothing
  to ask for instead on Windows: `listen` has no `reuseAddr` (that is `dgram`, for UDP), and libuv sets
  neither `SO_REUSEADDR` nor `SO_EXCLUSIVEADDRUSE` for a TCP server there on purpose, since `SO_REUSEADDR` on
  Windows means "take a port another process is using". `listenOptions` decides, and the second window falls
  back to the `EADDRINUSE` branch, which is what it always did.
- **The panel's CSP forbids network access.** Geometry arrives over `postMessage` and is parsed from memory;
  three.js is bundled rather than loaded from a CDN. Do not add an asset that is fetched at runtime — that is
  what rules out drei's `environment` presets, and why the renderer uses `RoomEnvironment`.
- **The wire format is shared with Python.** `src/viewer/protocol.ts` mirrors
  `src/partcad_ide_client/protocol.py`, which is the normative description. Changing one
  means changing both. `src/test/suite/viewerProtocol.test.ts` covers this side.
- **A crash on the way up used to look like an idle panel.** The HTML's resting state is "Nothing to display
  yet.", and the renderer replaces it once geometry arrives -- so a renderer that never ran left exactly the
  message shown before the user has asked for anything. `scene.ts` builds its `THREE.WebGLRenderer` at module
  scope, and that constructor throws in a window with no WebGL, during `viewer.ts`'s *import*: no `message`
  handler registered, no `ready` posted, nothing logged. `host.ts` traps `error`/`unhandledrejection` and puts
  the reason in the overlay; it lives there because every webview module imports it, and a module's
  dependencies are evaluated before its own body, so it is installed before anything can throw.
- **Nothing is escaped on its way into a pane.** What the tabs display is text out of a package's
  configuration -- a description, a part name, a supplier's answer -- so every pane builds its DOM node by
  node through `src/webview/dom.ts` rather than assigning `innerHTML`. `textContent` cannot be talked into
  being markup; a template literal can.

Geometry reaches the viewer already tessellated: `partcad` renders to binary glTF in a sandbox and sends it
compressed, so the extension never needs a CAD library. It used to hand live OCP objects to the third-party
`OCP CAD Viewer` extension, which is why that dependency is gone.

## What the Explorer says while starting

The `partcadExplorer` welcome views in `package.json` are the only status the user sees before the tree
appears, and they are selected by context keys rather than by anything that inspects the backend. Which key
means what:

- **`partcad.serviceMissing`** -- `restartBackend` found nothing to connect to. Set there because that is the
  only place that can tell "no service" from "a service that has not answered yet".
- **`partcad.activated`** -- a service is connected and `activate` has been *sent*. Not that it succeeded.
- **`partcad.installed`** -- `?/partcad/loaded` (or `packageLoaded`) came back, so activation finished.
- **`partcad.failed`** -- something along the way reported failure, `activateFailed` included.

So `activated && !installed` is "connected, activation in flight or failed" -- and activation runs the health
checks, so on a cold install it is in flight for a while. That state used to be one welcome view reading
**"PartCAD v0.8.15 is not found."**, which was wrong in both halves of it: the extension was talking to a
PartCAD, and the version it named was the version it was talking to. A user who had just pointed the extension
at their own environment was told it had not been found. It is two views now, split on `partcad.failed` --
starting, and did-not-finish-starting -- and neither claims anything about what is installed. The version came
out of the text with it, along with its entry in `dev-tools/bumpversion.toml`.

`?/partcad/error` and `?/partcad/warn` go to the `PartCAD` terminal view as well as to a popup, because the
Explorer can only say that activation did not finish; the reason arrives on those notifications, and a popup
is dismissed or (with `partcad.showNotifications` turned down) never shown.

Nothing emits `INSTALLED`/`INSTALL_FAILED` any more -- `events.py` still defines them and `extension.ts` still
listens -- so `partcad.installed` moves only through `loaded`/`packageLoaded`. Do not read the name as "the
PartCAD Python module is installed"; that meaning belonged to the language server, along with the no-op
`partcad.install` command.

## Installing a package's dependencies

`partcad.installPackage` runs the daemon's `install` operation - the PartCAD counterpart of `npm install`: it
downloads every imported package and prepares every sketch, part and assembly (see `pc install`). It runs
against whatever `partcad.packagePath` resolves to. "The first time" is remembered per config path in the
workspace state, so reopening the window is never a second download.

**`partcad.installOnOpen` defaults to `"false"`, so this does not happen on its own.** It used to, once per
workspace, and the cost was not what "install the dependencies" suggests: `install` begins with
`ctx.get_all_packages()` under `force_update = True`, which is the whole transitive closure re-fetched --
measured at 101 packages and 268 seconds for `examples/`, with a warm cache and force-update *off*, 62 of them
the entire `//pub` index. Then every object is asked for its cache key, which resolves aliases, enriches and
links and runs plugin scripts (the LDraw ones to their 180 second deadline). And `socket_server.py` holds one
`_dispatch_lock` around every dispatch, so for the duration nothing else the window asks for - expanding a
node, opening a part, linting - is served. The tree appears, because `install` runs after `packageLoaded`, and
then the window is frozen behind it.

Turning it on is a reasonable thing for a user to do; doing it to them on first open is not.

Do not confuse it with `partcad.install`, which is a no-op: it bootstrapped the PartCAD Python module for the
backend that no longer exists, and survives only so an old command binding does not break.

## Updating PartCAD

"Update PartCAD" (`partcad.update`) updates the PartCAD installation — `pc upgrade`, not `pc update`, which
refetches a package's imports and is "Reload the package" (`partcad.refresh`) here. The extension implements
none of it, which is the point: there is one upgrader, `partcad_client.selfupdate`, and the extension
reaches it the same way a user would.

It spawns `<bundle>/pc --no-ansi upgrade` in the workspace folder and streams it to the output channel
(`updateServiceBundle` in `src/common/provision.ts`). `pc` looks up the latest release and, only if something
newer exists, stops every daemon running on the machine, waits for them, installs the new bundle beside the
running one, and removes every superseded bundle. The extension then reconnects, at the new path — which is why
`resolveServicePath` picks the newest `<root>/<version>/` directory rather than a fixed one, and how the
extension detects that anything happened: the resolved path moves. If there is no `pc` beside the service, or
it is too old to know the option, the extension downloads the release itself (`downloadLatest`), the same path
a first install takes.

The other direction is a refusal, and deliberately so: `pc upgrade` run *inside* a bundle this extension
downloaded errors out and says to update the extension instead. See "The tools on the terminal PATH" below for
how it knows.

The Explorer's "install"/"needs to be updated" buttons (`partcad.startInstall`) route to `partcad.update` too:
installing what is missing and updating what is stale is one operation, and a user should not have to know
which of the two they are asking for.

The standalone layout is shared with `install.sh` and `pc upgrade`: `<install-dir>/<version>/{pc,partcad,
partcad-json-rpc}`. Installing side by side (rather than over the running copy) is what lets the bundle replace
itself while it is executing, and is required on Windows, where deleting a running executable fails outright.
No superseded bundle is left behind: the idle ones go immediately, and the one the updater is running out of is
removed by a detached reaper once that process exits.

## The tools on the terminal PATH

`src/common/terminalPath.ts` prepends the directory holding `pc`/`partcad` to `PATH` for terminals opened in
this window, through `context.environmentVariableCollection`, so `pc` works without the user installing
anything or editing a shell profile. `partcad.addToolsToTerminalPath` (default true) turns it off.

The directory is `path.dirname()` of whatever `resolveServicePath` found. A standalone bundle is
`<install-dir>/<version>/{pc,partcad,partcad-json-rpc}`, one directory holding all three, so the executable the
extension already resolved names it -- and one `PATH` entry covers every entry point.

It also sets `PARTCAD_MANAGED_BY=vscode-extension` on those terminals. `partcad_client.selfupdate` reads it and
makes `pc upgrade` refuse: a bundle this extension downloaded is replaced by updating the extension, and
upgrading from inside it would install a second copy the extension does not know about. Keep the two constants
in step; `selfupdate.py` is the only reader.

Four things about it are deliberate:

- **Unconditional.** No `getScoped` per workspace folder, no check for a PartCAD package in the workspace, and
  no check for what is on `PATH` already. An activated extension means the tools belong in every terminal of
  the window. Some of `resolveServicePath`'s fallbacks (`~/.local/bin`, a plain PATH lookup) resolve to a
  directory that is on PATH anyway; prepending it again is inert.
- **Not persistent.** `collection.persistent = false`, against the default. `pc upgrade` installs beside the
  running bundle and deletes every superseded one, so a restored collection would put a deleted directory on
  the PATH of every terminal until activation caught up. Re-applying on each activation cannot go stale.
- **`clear()` before `prepend()`.** `prepend` appends to what the collection holds, so refreshing after an
  upgrade would otherwise leave both the old and the new directory on PATH, oldest first.
- **The trailing `path.delimiter`** is part of the prepended value, not decoration.

Refreshed on activation, on `?/partcad/scriptsPath`, after `updateServiceBundle`, and on any configuration
change (cheap and idempotent, so it does not work out which setting moved).

Inside the PartCAD IDE this runs alongside `ide/standalone/bootstrap/extension.js`, which does the same
thing for the tools bundled in the application. Both prepend, and `bootstrap` points `partcad.servicePath` at
the bundled service, which `resolveServicePath` honours first -- so the two agree on the directory and the only
effect is that it appears on `PATH` twice.

This has nothing to do with `src/terminal.ts`, which creates the `PartCAD` output pseudoterminal: that is a log
surface with a no-op `handleInput`, not a shell, and has no environment to inherit.

## YAML diagnostics

Two documents are checked: `.assy` files and a package's `partcad.yaml`. Both are registered as YAML for
highlighting and neither is YAML -- each is a Jinja2 template that renders to YAML and then has to match a
schema. (`.world` files are registered the same way, against `xml`: a Gazebo world *is* XML, so the editor's
own XML support is the whole of what it needs -- there is no PartCAD check for one, and none is wanted.)
`src/PartcadLint.ts` checks the open document (debounced on edit, immediately on open/save) through the
`partcad.lintFile` command and publishes the answer into a `partcad` diagnostic collection.

**Keeping the `yaml` language id is what keeps the highlighting.** The id is how the editor picks a grammar, so
a PartCAD id of its own would have to bring a grammar of its own; the `languages` contribution in
`package.json` claims `partcad.yaml` by filename and `.assy` by extension, and gives each the PartCAD icon,
without taking either away from `yaml`. Diagnostics need none of that -- they are published per document URI,
beside whatever else has an opinion about the file. `isPackageConfigDocument` matches the basename rather than
the extension, because a `parts.yaml` next door is somebody's own file and not a package configuration.

**The check never reaches the daemon**, and there is no RPC method for it. It is the client's own file --
usually one the editor has not saved -- and it needs no package graph, no CAD runtime and no loaded context, so
sending it would mean shipping the buffer across a wire to have it read back, and would leave the editor silent
exactly when the package fails to load *because* of the file being typed into. `JsonRpcBackend.lintFile`
answers it by running `pc --no-ansi lint --file <path> --stdin --json`, feeding the buffer on stdin. Same
reasoning as `pc daemon stop`: defer to the CLI rather than keep a second copy here.

An **ASSY** file a **scene** points at is checked against the same schema with `how` forbidden, and which of the
two a given file is is not a property of the file. (A `partcad.yaml` has no flavor -- nothing points at a
package configuration -- so `flavorOf` returns nothing for one and none is sent.) `PartcadLint.flavorOf` answers it from the package contents
the Explorer has already loaded -- the declaration itself -- and leaves the question to `pc lint` for a file no
loaded package mentions. Both sides go through `pathKey` (`common/paths.ts`) rather than comparing paths as
strings: `Uri.fsPath` lower-cases a Windows drive letter and PartCAD does not, so the editor's spelling of a
document and the daemon's spelling of the same file never matched there and every scene was checked as an
assembly. The daemon answers the same question with `os.path.samefile`; this one has to work on a buffer that
has never been saved, so it normalises instead of asking the filesystem. Both lean the same way when they cannot tell: unknown means assembly, because reading
an assembly as a scene would put a false error on correct code.

The checker is `partcad_utils.assy_lint` (schemas: `src/partcad_utils/schema/assy.json` and
`partcad.json`), shared with the daemon-side package lint so an editor and CI cannot disagree about a file. It
masks each Jinja2 construct with equally sized filler before parsing, which is what keeps every finding on its
source line and column; findings that depend on what the mask hid are dropped rather than guessed. Change the
schema or the message wording there, not here -- and remember that a gap in the configuration schema is now a
squiggle on a working file, so anything PartCAD's own tooling writes has to validate.

## Opening a file in a third-party application

The Explorer's per-item **"Open in > ..."** menu hands the item's file to `partcad.openExternal`, which runs
`pc --no-ansi open --with <tool> [--type <type>] [--use-docker] [--docker-image <image>] <path> --json`. Four
applications, each offered for the objects it can actually open:

| Menu entry | Command | Shown for |
| --- | --- | --- |
| FreeCAD | `partcad.openInFreeCAD` | parts and assemblies |
| Blender | `partcad.openInBlender` | parts and assemblies |
| Gazebo | `partcad.openInGazebo` | scenes of type `world` (`viewItem == sceneWorld`) |
| KiCad | `partcad.openInKiCad` | parts of type `kicad` (`viewItem == partKicad`) |

The two narrow ones are why `PartcadItem` gives those objects a context value of their own: `viewItem` is one
string compared exactly, so "a scene Gazebo can open" and "a part KiCad can open" have to *be* separate
values. Both are then added back to every other clause that names their kind, because a world scene is a scene
everywhere else and a KiCad part is a part.

**It never reaches the daemon, and there is no RPC method for it** -- a stronger version of the rule
`pc lint --file` follows. A daemon can be remote: "open this in FreeCAD" sent to one would put a window on
somebody else's screen, on a machine that may have no display at all, and the path would name a file only the
client has. So the finding of the application, the container and the X forwarding are `partcad_client.external`
and nothing here reimplements them; what stays in TypeScript is the menu, the setting, and showing the failure.

The failure is the interesting half. `pc open` prints its reason as JSON *and* exits non-zero, so
`JsonRpcBackend.openExternal` reads the JSON with `allowFailure` and throws the message as it came --
`PartcadExplorer.openWith` shows it verbatim in the error dialog's detail. That message is the answer the user
needs (which X server to install and what to allow, or how to let PartCAD use a container); replacing it with
"the command failed" would throw away the whole point of the command.

What is handed over is `config.item_path`, not the item's `itemPath`. The tree sets `itemPath` only for the
types this editor can *edit* -- the scripts -- so a STEP or BREP part, which is exactly what another CAD
application is for, has none; `config.item_path` is the file the daemon reported for the object either way.
The menu is therefore on the same items as "Export" and an object that has no file of its own says so when it
is picked, rather than being silently missing from the menu.

The object's declared `config.type` is handed over too, as `--type`, and it is the *only* other thing this
tree contributes. It is there because a file name does not always say what it holds -- a `.py` is a CadQuery
script, a build123d one or an SDF one -- and Blender reads meshes and nothing else, so a part that is not
already one is converted to STL before it is opened. Which types are meshes
(`partcad_client.object_types`), whether this one needs converting, where the mesh goes and who does the
converting are all decided by `pc open`; nothing here branches on the type, and nothing here knows that
Blender is the application it matters for.

And no more than that is decided here. A `kicad` part's file is the STEP KiCad's command line writes out of
the board; the board is the `.kicad_pro` beside it, and swapping one for the other is a fact about KiCad that
lives in `external.TOOLS` (`Tool.companions`), not in this tree. Same for how Gazebo is launched: `gz sim`,
`ign gazebo` and `gazebo` are three front ends of one application and `Tool.binary_args` is where that is
written down -- as is Blender being handed `--python-expr` rather than a file name, because the only file
Blender *opens* is a `.blend`.

`partcad.open.useDocker` and `partcad.open.dockerImage` are read here, on the way to that command line, rather
than being worked out anywhere in Python: PartCAD decides *how* to run the application, and the settings only
say what it is allowed to do. Adding a second application is a command, a menu entry and a row in
`external.TOOLS` -- no new branch in this extension.

## Setup

```bash
npm install
```

## Test and validate changes

```bash
npm run lint                                # eslint on src/**/*.ts
npm run format-check                        # prettier check
npm test                                    # vscode-test extension tests (xvfb-run -a npm test on Linux)
```

`npm test` downloads a VS Code and opens `sampleWorkspace/` in it -- a directory that has to exist and has to
be free of PartCAD content, or the extension activates through `workspaceContains` before the test that
activates it. `.vscode-test.js` sets `PARTCAD_EXTENSION_NO_PROMPTS=1`, because a runner has no PartCAD
installed and activation would otherwise put up the modal "shall I download it?" dialog that nothing headless
can answer. Both of those are why the suite now runs on `windows-latest` in `npm-test.yml`, where it had been
disabled as "for some reason doesn't run test suite".

**Windows and macOS behaviour is tested from the Linux runner where it can be.** A platform-specific decision
belongs in a pure function that takes the platform (`pathKey`, `listenOptions`, `daemonEndpointIn`,
`resolveServicePath`'s `searched` list) so a test can ask what it would do somewhere else. Everything in this
file that starts "on Windows" was shipped broken at some point precisely because nothing asked.

### Testing against the IDE, not against VS Code

**`npm test` downloads stock VS Code, so it says nothing about the editor that ships.** That is the right
default -- what it checks is this extension's logic -- but it is blind to everything the PartCAD IDE puts
around it: the built-in extension set, `product.json`'s `configurationDefaults` (`partcad.backend`,
`partcad.serviceChannel`), the bootstrap extension and the first-start workspace it creates, the embedded
`partcad-json-rpc` the extension is meant to find without a dialog, and the branded application shell itself.
Nothing here started that editor until #609, and it could not start at all on macOS for two releases without a
single test in this repository noticing.

So a change to any of those is tested against a **built** IDE. `.vscode-test.js` offers a second
configuration, `bundledIde`, when `PARTCAD_IDE_PATH` names one. What it wants is the application *binary* --
not the bundle, and not the `bin/` launcher:

```bash
# macOS. The executable's name belongs to the editor this was built from --
# VSCodium's, today -- so it is read rather than written down here.
app="$HOME/Applications/PartCAD IDE.app"
export PARTCAD_IDE_PATH="$app/Contents/MacOS/$(plutil -extract CFBundleExecutable raw "$app/Contents/Info.plist")"

# Linux. Resolved through the launcher `install.sh` symlinks, rather than
# assuming the layout it owns.
app="$(dirname "$(dirname "$(readlink -f "$HOME/partcad-bin/partcad-ide")")")"
export PARTCAD_IDE_PATH="$app/partcad-ide"

npm run pretest && npx vscode-test --label bundledIde        # xvfb-run -a ... on Linux
```

```powershell
# Windows. There is no `install.sh` there -- the setup program puts the
# application here -- and `fromPath` is read by Node, so it wants a native path.
$env:PARTCAD_IDE_PATH = Join-Path $env:LOCALAPPDATA "Programs\PartCAD IDE\partcad-ide.exe"
npm run pretest; npx vscode-test --label bundledIde
```

The first two are the ones `build-ide-standalone.yml` uses, and neither hardcodes a name it can ask for. The
first version of that step wrote `Contents/MacOS/VSCodium` and was right about today's bundle and wrong in
principle; `ide/standalone/AGENTS.md` has which plist field means what.

**CI runs this on macOS and Linux only.** The `install` job drops Windows from its matrix -- there is no shell
installer there, and `install-windows` runs the setup program instead -- so the Windows form above is the one
to use by hand and the one nothing checks. Do not reach it by running the Bash recipe under Git Bash: there is
no `~/partcad-bin/partcad-ide` to resolve, and if there were, `readlink -f` answers with an MSYS path
(`/c/...`) that `useInstallation.fromPath` cannot use.

Unset, the configuration is not offered and `npm test` is unchanged, so nobody needs a bundle to work here.
`.github/workflows/build-ide-standalone.yml` sets it after installing a build, which is the only place it runs
in CI -- `ide/standalone/AGENTS.md` has how that bundle is made.

Three things the bundled run needs, all of which have already cost a debugging session:

- **`PARTCAD_EXTENSION_NO_PROMPTS=1` still applies.** The IDE *does* carry a service, so the download dialog is
  not the risk it is under stock VS Code -- but a prompt of any kind is still something a headless run cannot
  answer, and on Windows an unanswered modal keeps the window from ever closing.
- **The built IDE already contains a released copy of this extension.** `--extensionDevelopmentPath`, which the
  runner passes, is what makes the checkout win. A test asserting on extension *version* rather than behaviour
  will read whichever copy it happened to get.
- **A first `Display` provisions a conda environment**, which takes about three minutes on a clean machine
  against roughly two seconds warm. A test that exercises geometry needs a warmed `~/.partcad/conda` or a
  budget that admits the cold path; the 60s Mocha timeout is sized for activation, not for that.

## Build / package

```bash
npm ci && npm run vsce-package   # builds partcad.vsix (vscode:prepublish runs webpack)
code --install-extension partcad.vsix
```

That is the whole build, everywhere: `.github/workflows/vsix.yml` runs it once and attaches
`partcad-<version>.vsix` to the GitHub release, and `ide/standalone/build.sh` runs it for the copy that
ships inside the PartCAD IDE. It used to be `nox --session build_package`, which had to populate `bundled/libs`
first and had to run per platform because those were compiled wheels. There is no Python in this package any
more, so one build serves every platform.

The same workflow packages `ide/vscode-shim` beside it, into the same artifact and onto the same release. That
is the marketplace entry this extension used to be published under -- see "The marketplace identity" below.

## The icon

`resources/logo.svg` is the PartCAD mark, and it is the only drawing here: the activity bar container, the
three views in it, the `partcad.yaml`/`.assy`/`.world` file icons and the `PartCAD` terminal view all point at
that one file, and so does the PartCAD IDE, which renders its application icons from it
(`ide/standalone/tools/make_icons.py`). `resources/logo_128x128.png` is the same mark rasterized, which is
what `package.json`'s `icon` has to be: `vsce` refuses an SVG there.

That `.png` is the one image in this repository that is **not** in Git LFS, and it has to stay that way. No
checkout in `.github/workflows` asks for LFS, `vsce package` copies the file into the `.vsix` without looking
at it, and the result is an extension whose icon is a 130-byte pointer -- which is exactly what every release
up to 0.8.35 shipped. `.gitattributes` names the file and says so.

The corollary is that this package should carry **no other image**. `docs/` used to hold `image1.png` and
`image2.png`, which were byte-identical copies of `docs/source/images/vscode1.png` and `vscode2.png` at the
repository root -- nothing referenced them (`README.md` links the originals by absolute URL, which is what the
marketplace needs), and they shipped in every `.vsix` as two more LFS pointers. They are gone. An image this
package genuinely needs has to be added the way the icon is: named in `.gitattributes` and kept out of LFS, or
it arrives as text.

After changing `partcad` core code while developing through this extension, click "Restart PartCAD" in the
PartCAD `Context` view (or restart VS Code) to pick up the change.

## The marketplace identity

This extension is `PartCAD.partcad-official`. It used to be `OpenVMP.partcad`, and a publisher is half of an
extension's identity, so that was a different extension rather than an earlier name for this one -- nothing
in the marketplace or the editor carries an installation across.

The `name` is the other half, and it is `partcad-official` rather than `partcad` because the marketplace does
not let two publishers share an extension name: `partcad` belongs to the old entry, which `ide/vscode-shim`
still publishes to, so this one cannot also be called that. `displayName` is unaffected -- the extension is
"PartCAD" in the Extensions view either way, which is what a user searches for. Do not try `partcad_official`:
`vsce` validates both `name` and `publisher` against `/^[a-z0-9][a-z0-9\-]*$/i` and rejects an underscore.

Three things follow, and all are already done:

* **The old entry is not abandoned.** `ide/vscode-shim` is published to it: no code, one
  `extensionDependencies` on `PartCAD.partcad-official`, so an installation of the old entry updates into a
  dependency on this one. Its `AGENTS.md` has the rest, including the ordering rule -- **this extension has to
  be published first**, because the editor fails an install whose dependency cannot be resolved.

* **`globalStorageUri` moved with the identity, twice.** It is named after the extension, so bundles this
  extension had downloaded into `globalStorage/openvmp.partcad/` (before the publisher moved) or
  `globalStorage/partcad.partcad/` (before the name did) are not in
  `globalStorage/partcad.partcad-official/` where it now looks. `resolveServicePath` reads both old roots as
  fallbacks (`legacyBundleRoots` in `src/common/provision.ts`) -- without them, an upgrade across a move tells
  a user whose PartCAD is sitting right there that none was found, and downloads a second copy. They are
  fallbacks and not the download target: new bundles go to the current root, so the old directories are
  superseded rather than kept in step.

* **The id is not a prefix of `PartCAD.partcad-ide-bootstrap` any more.** It was, and the checks in
  `.github/workflows/build-ide-standalone.yml` that look for the extension inside a built IDE still require a
  version digit after the id rather than a bare `*`, which is what kept them from accepting the bootstrap
  extension in its place. Keep that -- it costs nothing and the next id may share a prefix again.

The extension id appears outside this package too -- `ide/standalone/build.sh` installs it into the IDE by id,
`.github/workflows/build-ide-standalone.yml` checks the built IDE contains it (matched case-insensitively,
since the editor lowercases the directory it installs into), `.devcontainer/devcontainer.json` lists it,
`ide/standalone/tests/` asserts on it, and `src/test/suite/extension.test.ts` activates the extension by it.
`ide/vscode-shim/package.json` depends on it. Those are the places to change together if it ever moves again,
along with the install instructions in `README.md`, `docs/source/installation.rst` and
`ai-agents/common/skills/setup/SKILL.md`.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `eslint` on changed `.ts` files and are required to
pass in CI before a PR can merge.
