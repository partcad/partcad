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
  it runs the launcher, reads the printed socket path, and connects; `partcad.serviceChannel: stdio` runs a
  dedicated process over stdin/stdout instead. "Restart PartCAD"/reset sends `daemon.stop` to tear down the
  warm context. See `src/common/backend.ts` and `src/common/provision.ts`.
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
