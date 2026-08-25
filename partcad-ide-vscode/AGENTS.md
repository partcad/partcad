# partcad-ide-vscode

Visual Studio Code extension providing navigation and UI for `partcad` projects. Node/TypeScript toolchain
(`npm`). Run all commands below from
this directory (`partcad-ide-vscode/`).

## The backend

**This extension is a JSON-RPC client and nothing else.** It talks to the standalone `partcad-json-rpc`
executable, translating each `partcad.*` command the UI issues into the CLI-shaped JSON-RPC method and routing
the service's notifications back under the `?/partcad/*` names the handlers listen on. See
`src/common/backend.ts` and `src/common/provision.ts`.

By default it connects over the per-workspace socket **daemon** (`partcad.serviceChannel: socket`): it runs
`pc daemon start`, reads the printed socket path, and connects. `partcad.serviceChannel: stdio` runs a
dedicated process over stdin/stdout instead. "Restart PartCAD"/reset runs `pc daemon stop` to tear down the
warm context.

Where the executable comes from is `resolveServicePath`: the `partcad.servicePath` setting, then an existing
standalone install, then the extension's own download directory, then `~/.local/bin`, then a plain `PATH`
lookup. That last one is why a user with their own Python needs no download at all -- `pip install partcad`
puts `partcad-json-rpc` on the `PATH`. Only when none of them resolves does the extension offer to download a
bundle, and declining leaves it with no backend rather than falling back to something.

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

End-to-end walkthrough, with the data flow diagram: [docs/partcad-viewer.md](./docs/partcad-viewer.md).

`src/viewer/` is the extension-host half of the viewer: a TCP server on a constant loopback port
(`PartcadViewerServer`) that `partcad` processes connect to, and the webview panel that displays what they
send (`PartcadViewer`). `src/webview/viewer.ts` is the renderer that runs *inside* that webview.

Three things about it are load-bearing:

- **Two webpack bundles, two tsconfigs.** The extension host is CommonJS; the webview is a browser context and
  three.js ships its addons as ES modules only, so `src/webview` compiles under `tsconfig.webview.json` (and is
  excluded from `tsconfig.json`). `npm run compile` builds both.
- **The panel's CSP forbids network access.** Geometry arrives over `postMessage` and is parsed from memory;
  three.js is bundled rather than loaded from a CDN. Do not add an asset that is fetched at runtime — that is
  what rules out drei's `environment` presets, and why the renderer uses `RoomEnvironment`.
- **The wire format is shared with Python.** `src/viewer/protocol.ts` mirrors
  `partcad-ide-client/src/partcad_ide_client/protocol.py`, which is the normative description. Changing one
  means changing both. `src/test/suite/viewerProtocol.test.ts` covers this side.

Geometry reaches the viewer already tessellated: `partcad` renders to binary glTF in a sandbox and sends it
compressed, so the extension never needs a CAD library. It used to hand live OCP objects to the third-party
`OCP CAD Viewer` extension, which is why that dependency is gone.

## Installing a package's dependencies

`partcad.installPackage` runs the daemon's `install` operation - the PartCAD counterpart of `npm install`: it
downloads every imported package and prepares every sketch, part and assembly (see `pc install`). The extension
runs it automatically the first time a workspace directory is opened, once the package has loaded, against
whatever `partcad.packagePath` resolves to. "The first time" is remembered per config path in the workspace
state, so reopening the window is not another download; `partcad.installOnOpen: "false"` turns the automatic
run off and leaves the palette command.

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

Inside the PartCAD IDE this runs alongside `partcad-ide-standalone/bootstrap/extension.js`, which does the same
thing for the tools bundled in the application. Both prepend, and `bootstrap` points `partcad.servicePath` at
the bundled service, which `resolveServicePath` honours first -- so the two agree on the directory and the only
effect is that it appears on `PATH` twice.

This has nothing to do with `src/terminal.ts`, which creates the `PartCAD` output pseudoterminal: that is a log
surface with a no-op `handleInput`, not a shell, and has no environment to inherit.

## ASSY diagnostics

`.assy` files are registered as YAML for highlighting but are not YAML: they are Jinja2 templates that render
to YAML and then have to match the ASSY schema. `src/PartcadLint.ts` checks the open document (debounced on
edit, immediately on open/save) through the `partcad.lintFile` command and publishes the answer into a
`partcad` diagnostic collection.

**The check never reaches the daemon**, and there is no RPC method for it. It is the client's own file --
usually one the editor has not saved -- and it needs no package graph, no CAD runtime and no loaded context, so
sending it would mean shipping the buffer across a wire to have it read back, and would leave the editor silent
exactly when the package fails to load *because* of the file being typed into. `JsonRpcBackend.lintFile`
answers it by running `pc --no-ansi lint --file <path> --stdin --json`, feeding the buffer on stdin. Same
reasoning as `pc daemon stop`: defer to the CLI rather than keep a second copy here.

The checker is `partcad_utils.assy_lint` (schema: `partcad-utils/src/partcad_utils/schema/assy.json`), shared
with the daemon-side package lint so an editor and CI cannot disagree about a file. It masks each Jinja2
construct with equally sized filler before parsing, which is what keeps every finding on its source line and
column; findings that depend on what the mask hid are dropped rather than guessed. Change the schema or the
message wording there, not here.

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

## Build / package

```bash
npm ci && npm run vsce-package   # builds partcad.vsix (vscode:prepublish runs webpack)
code --install-extension partcad.vsix
```

That is the whole build, everywhere: `.github/workflows/vsix.yml` runs it once and attaches
`partcad-<version>.vsix` to the GitHub release, and `partcad-ide-standalone/build.sh` runs it for the copy that
ships inside the PartCAD IDE. It used to be `nox --session build_package`, which had to populate `bundled/libs`
first and had to run per platform because those were compiled wheels. There is no Python in this package any
more, so one build serves every platform.

After changing `partcad` core code while developing through this extension, click "Restart PartCAD" in the
PartCAD `Context` view (or restart VS Code) to pick up the change.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `eslint` on changed `.ts` files and are required to
pass in CI before a PR can merge.
