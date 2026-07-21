# partcad-ide-vscode

Visual Studio Code extension providing navigation and UI for `partcad` projects, plus a Python LSP server
bundled under `./bundled/tool`. Node/TypeScript toolchain (`npm`), with a `nox`-driven Python side for the
bundled tool and its tests. Run all commands below from this directory (`partcad-ide-vscode/`).

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
