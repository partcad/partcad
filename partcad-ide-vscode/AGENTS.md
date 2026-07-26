# partcad-ide-vscode

Visual Studio Code extension providing navigation and UI for `partcad` projects. Node/TypeScript toolchain
(`npm`), with a `nox`-driven Python side for the bundled LSP tool and its tests. Run all commands below from
this directory (`partcad-ide-vscode/`).

## Backends

The extension talks to PartCAD through a backend selected by the `partcad.backend` setting:

- `service` (default) — runs the standalone `partcad-json-rpc` executable (from
  [`partcad-service-json-rpc`](../partcad-service-json-rpc)) over stdio; no Python environment required. On
  first use it looks for an existing standalone install, then offers to download one; declining switches the
  setting to `python`. See `src/common/backend.ts` and `src/common/provision.ts`.
- `python` — the legacy path: a Python LSP server bundled under `./bundled/tool`, launched with a discovered
  Python interpreter. Behavior is unchanged from previous versions.

The backend abstraction (`src/common/backend.ts`) keeps the extension's command/notification handling identical
across both; the JSON-RPC backend translates the extension's `partcad.*` commands to the CLI-shaped JSON-RPC
methods and routes the service's notifications back under the legacy `?/partcad/*` names.

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
