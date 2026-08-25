# partcad_ide_client

The Python half of the socket protocol that connects `partcad` to the PartCAD IDE extension's **PartCAD
Viewer**. Source: `./src/partcad_ide_client`. Tests: `./tests/partcad_ide_client`. Run all commands below from
the repo root unless noted.

**A package, not a distribution.** Nothing is published under this name: it is one of the packages inside the
single `partcad` wheel, so `pip install partcad` is what puts `import partcad_ide_client` on a machine. See
"The PartCAD IDE viewer client" in [../partcad/AGENTS.md](../partcad/AGENTS.md) for the rationale, including
why giving this directory a `pyproject.toml` of its own would be a mistake.

The other half of the protocol lives in `ide/vscode/src/viewer/protocol.ts`. **A change to the wire
format is a change to both files**, and the frame layout is specified once, in
`src/partcad_ide_client/protocol.py` — that docstring is the normative description.

## Constraints

Two properties of this package are deliberate and easy to break:

- **No dependencies.** It lands in whatever interpreter `partcad` is installed into. Depending on anything (a
  CAD library above all — which is exactly what depending on `ocp_vscode` did) risks dragging a second,
  differently-provisioned stack into that interpreter, and would put that dependency into the `partcad` wheel
  along with it. Standard library only.
- **It does not import `partcad`.** Geometry has already been tessellated into glTF by a PartCAD sandbox
  before it reaches here, so there is nothing to import. `partcad` imports *this*, lazily, from
  `partcad.viewer`.

The glTF payload codec (`encode_gltf`/`decode_gltf`) has two other implementations that have to agree with it:
`ocp_serialize.encode_gltf` in the sandbox, and `decodeGltf` in the extension. Neither can import this package,
which is why each carries its own copy; `tests/partcad/unit/test_viewer.py` and the extension's
`viewerProtocol.test.ts` are what catch a drift.

## Setup

All commands run **inside the dev container** — see "Where commands run" in the root
[AGENTS.md](../../AGENTS.md). Dependencies are already installed; re-run `poetry install` only after changing
`pyproject.toml`. Prefix commands with `poetry run`.

## Test and validate changes

```bash
poetry run pytest tests/partcad_ide_client -x -p no:error-for-skips -p no:warnings --dist no   # matches CI
poetry run behave                                                                            # integration tests
```

The client tests stand up a fake IDE on an ephemeral port and point the client at it with `PARTCAD_IDE_PORT`,
so they never collide with a PartCAD IDE the developer actually has open.

To exercise the whole path — a real part, tessellated in a sandbox, over a real socket — point a `partcad` at a
listening socket and show something; `tests/partcad/unit/test_viewer.py` covers the core side with the sandbox
stubbed out, and the sandbox side is covered by the render tests.

## Lint / format

```bash
poetry run black --check src/partcad_ide_client tests/partcad_ide_client
```

Note that `flake8` reports E501 at 79 columns on every file in this repo (it does not read the 120-column
setting from `pyproject.toml` without a plugin), and `isort` disagrees with the tree as committed; neither
gates a PR. See the root [AGENTS.md](../../AGENTS.md).

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
