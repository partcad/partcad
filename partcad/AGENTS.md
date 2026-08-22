# partcad

Core Python module implementing PartCAD's digital-thread logic (packages, parts, assemblies, providers).
Source: `./src/partcad`. Tests: `./tests`. Part of the shared Poetry workspace rooted at the repo root — run
all commands below from the repo root unless noted.

## Setup

All commands on this page run **inside the dev container**, not on the host — see "Where commands run" in the
root [AGENTS.md](../AGENTS.md) for how to enter it. Dependencies are already installed in the image; re-run
`poetry install` only after changing `pyproject.toml`. The virtualenv is not auto-activated, so prefix the
commands below with `poetry run` (e.g. `poetry run pytest ...`).

```bash
poetry install   # from repo root; installs partcad (and partcad-cli) in editable mode
```

## Test and validate changes

Running `pytest` to a clean pass is the required validation step for any change under `partcad/`:

```bash
pytest partcad -x -p no:error-for-skips -p no:warnings --dist no   # matches CI (test-pytest job)
pytest partcad/tests -n 4 --timeout 300 -m "not slow"              # matches the pre-commit hook, faster locally
```

Tests live in `./tests` (`tests/unit`); slow tests are marked `slow` and excluded by the pre-commit hook's `-m
"not slow"`. Treat a failing `pytest` run as blocking — do not consider a change to this module complete until
it passes.

## Lint / format

```bash
black --check partcad     # line-length 120 (pyproject.toml)
flake8 partcad
isort --check partcad
```

## Conventions

- **Async naming**: every externally visible coroutine has a name ending in `_async`, paired with a synchronous
  wrapper of the same name without the suffix. Coroutines run on asyncio's event loop; CPU-heavy work runs on a
  separate thread pool (sized to CPU cores minus 1). Tasks on the thread pool must not call coroutines that use
  `asyncio.Lock()`.
- **Location/coordinate format**: 3D locations (OpenCASCADE `TopLoc_Location`) are represented as
  `[[x, y, z], [rx, ry, rz], angle]` — translation in mm, then an axis vector and rotation angle (degrees)
  around it.

## Schemas and linting

`./src/partcad/schema/partcad.json` is the schema `lint/schema.py` validates `partcad.yaml` against, and
`lint/all.py` registers the checks — the names it gives them are what `pc lint -f` filters on. Anything added to
`schema/` ships through `[tool.setuptools.package-data]` in `pyproject.toml` and through the PyInstaller spec's
copy of the whole directory.

The ASSY schema and its checker are **not** here: they are `partcad_utils.assy_lint` and
`partcad_utils/schema/assy.json`. `AssySchemaLinting` is the *package* half — walking a package's `.assy` files
needs the package graph, which is daemon work — while each client checks the one file being edited in its own
process (`partcad_client.lint`, reached by `pc lint --file`). Two implementations of that check would let an
editor and CI disagree about a file, so there is one, in the package both ends already depend on.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
