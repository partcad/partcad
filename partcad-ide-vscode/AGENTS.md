# partcad-ide-vscode

Visual Studio Code extension providing navigation and UI for `partcad` projects. Node/TypeScript toolchain
(`npm`), with a `nox`-driven Python side for the bundled LSP tool and its tests. Run all commands below from
this directory (`partcad-ide-vscode/`).

## Backends

The extension talks to PartCAD through a backend selected by the `partcad.backend` setting:

- `service` (default) — uses the standalone `partcad-json-rpc` executable (from
  [`partcad-service-json-rpc`](../partcad-service-json-rpc)); no Python environment required. On first use it
  looks for an existing standalone install, then offers to download one; declining switches the setting to
  `python`. By default it connects over the per-workspace socket **daemon** (`partcad.serviceChannel: socket`):
  it runs `pc daemon start`, reads the printed socket path, and connects; `partcad.serviceChannel: stdio` runs
  a dedicated process over stdin/stdout instead. "Restart PartCAD"/reset runs `pc daemon stop` to tear down the
  warm context. See `src/common/backend.ts` and `src/common/provision.ts`.

  **Daemon handling is the CLI's, not the extension's.** Which socket serves which workspace, whether anything
  is answering on it, and how to stop it and wait are `partcad_client`, reached by running `pc`. A second
  copy of those rules in TypeScript is a copy that can disagree, and a disagreement means the extension quietly
  starting a daemon of its own beside the one `pc` is using. What stays in Node is the socket transport itself,
  because a live notification connection cannot be shelled out.
- `python` — the legacy path: a Python LSP server bundled under `./bundled/tool`, launched with a discovered
  Python interpreter. Behavior is unchanged from previous versions.

The backend abstraction (`src/common/backend.ts`) keeps the extension's command/notification handling identical
across both; the JSON-RPC backend translates the extension's `partcad.*` commands to the CLI-shaped JSON-RPC
methods and routes the service's notifications back under the legacy `?/partcad/*` names.

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

Do not confuse it with `partcad.install`, which bootstraps the PartCAD *Python module* for the `python`
backend and is a no-op for the frozen service.

## Updating PartCAD

"Update PartCAD" (`partcad.update`) updates the PartCAD installation — `pc upgrade`, not `pc update`, which
refetches a package's imports and is "Reload the package" (`partcad.refresh`) here. The extension implements
none of it, which is the point: there is one upgrader, `partcad_client.selfupdate`, and the extension
reaches it the same way a user would.

- `service` — spawns `<bundle>/pc --no-ansi upgrade` in the workspace folder and streams it to
  the output channel (`updateServiceBundle` in `src/common/provision.ts`). `pc` looks up the latest release
  and, only if something newer exists, stops every daemon running on the machine, waits for them, installs the
  new bundle beside the running one, and removes every superseded bundle. The extension then reconnects, at the
  new path — which is why `resolveServicePath` picks the newest `<root>/<version>/` directory rather than a
  fixed one, and how the extension detects that anything happened: the resolved path moves. If there is no `pc`
  beside the service, or it is too old to know the option, the extension downloads the release itself
  (`downloadLatest`), the same path a first install takes.
- `python` — the bundled server's `partcad.install` handler calls `partcad_client.selfupdate` directly
  when PartCAD is already installed, and falls back to its `pip` bootstrap only when there is nothing installed
  to update. No daemon is stopped there, and none needs to be: this backend serves the extension in-process and
  never starts one.

The Explorer's "install"/"needs to be updated" buttons (`partcad.startInstall`) route to `partcad.update` too:
installing what is missing and updating what is stale is one operation, and a user should not have to know
which of the two they are asking for.

The standalone layout is shared with `install.sh` and `pc upgrade`: `<install-dir>/<version>/{pc,partcad,
partcad-json-rpc}`. Installing side by side (rather than over the running copy) is what lets the bundle replace
itself while it is executing, and is required on Windows, where deleting a running executable fails outright.
No superseded bundle is left behind: the idle ones go immediately, and the one the updater is running out of is
removed by a detached reaper once that process exits.

## ASSY diagnostics

`.assy` files are registered as YAML for highlighting but are not YAML: they are Jinja2 templates that render
to YAML and then have to match the ASSY schema. `src/PartcadLint.ts` checks the open document (debounced on
edit, immediately on open/save) through the `partcad.lintFile` command and publishes the answer into a
`partcad` diagnostic collection.

**The check never reaches the daemon**, and there is no RPC method for it. It is the client's own file --
usually one the editor has not saved -- and it needs no package graph, no CAD runtime and no loaded context, so
sending it would mean shipping the buffer across a wire to have it read back, and would leave the editor silent
exactly when the package fails to load *because* of the file being typed into. Each backend answers
`partcad.lintFile` from whatever local PartCAD it has:

- `service` — `JsonRpcBackend.lintFile` runs `pc --no-ansi lint --file <path> --stdin --json`, feeding the
  buffer on stdin. Same reasoning as `pc daemon stop`: defer to the CLI rather than keep a second copy here.
- `python` — the bundled server's `partcad.lintFile` calls `partcad_client.lint` in its own process.

The checker is `partcad_utils.assy_lint` (schema: `partcad-utils/src/partcad_utils/schema/assy.json`), shared
with the daemon-side package lint so an editor and CI cannot disagree about a file. It masks each Jinja2
construct with equally sized filler before parsing, which is what keeps every finding on its source line and
column; findings that depend on what the mask hid are dropped rather than guessed. Change the schema or the
message wording there, not here.

## Setup

```bash
npm install
nox --session setup   # sets up the bundled Python LSP tool environment
```

## Test and validate changes

```bash
npm run lint                                # eslint on src/**/*.ts
npm run format-check                        # prettier check
npm test                                    # vscode-test extension tests (xvfb-run -a npm test on Linux)
nox --session tests                         # pytest src/test/python_tests (bundled LSP tool)
nox --session lint                          # pylint/black/isort on Python + npm run lint on TS
```

## Build / package

```bash
nox --session build_package   # builds partcad.vsix (also runs npm install)
code --install-extension partcad.vsix
```

After changing `partcad` core code while developing through this extension, click "Restart PartCAD" in the
PartCAD `Context` view (or restart VS Code) to pick up the change.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `eslint` on changed `.ts` files and are required to
pass in CI before a PR can merge.
