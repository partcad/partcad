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

- **Built-in packages** (`./src/partcad/builtin`): PartCAD ships two packages inside itself, reachable from
  every context as `//builtin/export` and `//builtin/render` (loaded on demand by `Context.get_project`, see
  `output.py`). They declare the file types `pc export` and `pc render` write, in exactly the form a user's
  package declares one — a `path` to a script, its `pythonRequirements`, and the export parameters. So adding a
  format, changing its defaults or changing what it needs installed is an edit to `builtin/*/partcad.yaml`, not
  to `shape.py`. The scripts run in a sandbox through `wrappers/wrapper_export.py`; they are data files, so
  anything new under `builtin/` has to be listed in `pyproject.toml`'s `package-data` and in the PyInstaller
  spec (see "Packaging" in the root [AGENTS.md](../AGENTS.md)). The requirement strings there are the versions
  `sandbox_versions.py` pins, which `tests/unit/test_output.py` enforces.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
