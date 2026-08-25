# partcad

Core Python module implementing PartCAD's digital-thread logic (packages, parts, assemblies, providers).
Source: `./src/partcad`, plus `./src/partcad_ide_client`, a symlink to the `partcad-ide-client` component that
this distribution also ships (see "The PartCAD IDE viewer client" below). Tests: `./tests`. Part of the shared
Poetry workspace rooted at the repo root — run all commands below from the repo root unless noted.

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
  format, changing its defaults or changing which dependencies it needs is an edit to `builtin/*/partcad.yaml`, not
  to `shape.py`. The scripts run in a sandbox through `wrappers/wrapper_export.py`; they are data files, so
  anything new under `builtin/` has to be listed in `pyproject.toml`'s `package-data` and in the PyInstaller
  spec (see "Packaging" in the root [AGENTS.md](../AGENTS.md)). The requirement strings there are the versions
  `sandbox_versions.py` pins, which `tests/unit/test_output.py` enforces.

- **Sandbox environment** (`./src/partcad/python_env.py`): importing `partcad` sweeps every `PYTHON*` variable
  out of `os.environ` and puts back only `PARTCAD_PYTHON_ENV`. Everything PartCAD spawns — the wrappers, `pip`,
  `-m venv`, conda — inherits that, which is why a sandbox interpreter runs with plain `-sOOu` rather than the
  `-I` it used to: `-I` implies `-E`, and `-E` would have made the sandbox ignore PartCAD's own
  `PYTHONHASHSEED=0` along with the user's `PYTHONPATH`. So do not reintroduce `-I`/`-E` on a sandbox command
  the environment already covers, and add anything a sandbox interpreter has to be told through the environment
  to `PARTCAD_PYTHON_ENV`, where the sweep cannot take it away again.

  Below `sandbox_versions.MIN_PYTHON_VERSION_SAFE_PATH` the environment does *not* cover it: `PYTHONSAFEPATH`
  arrived in 3.11 and an older interpreter ignores it, which would leave the directory PartCAD runs from first
  on `sys.path` for the `-m venv`/`-m pip` calls that provision a sandbox. Those versions keep `-I` and go on
  ignoring `PYTHONHASHSEED` — no flag pins a hash seed, so isolation and reproducibility cannot both be had
  there. `tests/unit/test_python_env.py` asserts the outcome (a `venv.py`/`pip.py` beside the interpreter never
  wins) on whichever version is running, so both branches are covered by the CI matrix rather than by a
  comment.

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

## The PartCAD IDE viewer client

`./src/partcad_ide_client` is a **relative symlink** to `../../partcad-ide-client/src/partcad_ide_client`, and
that is how this distribution comes to ship a second top-level package: the Python half of the socket protocol
that connects `partcad` to the PartCAD IDE extension's **PartCAD Viewer**. `pip install partcad` therefore
makes `import partcad_ide_client` work, and nothing has to install it separately. setuptools dereferences the
symlink, so the wheel and the sdist both carry real files — `partcad-ide-client` keeps its own directory,
tests and AGENTS.md, and stops being a distribution.

**The symlink is load-bearing.** A checkout with `core.symlinks=false` — Git for Windows' default unless
Developer Mode is on — writes it as a small text file naming the target, `packages.find` then finds nothing
there, and the wheel builds *successfully* without the package. `tests/unit/test_ide_client_is_shipped.py`
exists to turn that silent success into a failing test; the `import partcad_ide_client` checks in `build.yml`
and `deploy.yml` are the same guard in CI. Released wheels are built on Linux (`deploy.yml` pins
`ubuntu-24.04`), so the exposure is a Windows contributor's local build, not the release.

It ships here rather than as a distribution of its own because it was never on PyPI and every process that
could import it is a process that already imports `partcad` — `partcad.viewer` is its only importer in the
tree. Two distributions owning one import name is the thing being avoided: pip does not detect the overlap when
installing, and uninstalling either one then deletes the module out from under the other, silently. So do not
give `partcad-ide-client` a `pyproject.toml` again, and do not vendor a second copy into the VS Code
extension's `bundled/libs` — under `useBundled` that copy would land first on `sys.path` and shadow this one in
the language server process only, leaving two different clients in play depending on which process is asking.

The other half of the protocol is `partcad-ide-vscode/src/viewer/protocol.ts`. **A change to the wire format is
a change to both files**, and the frame layout is specified once, in
`partcad-ide-client/src/partcad_ide_client/protocol.py` — that docstring is the normative description.
`partcad-ide-vscode/docs/partcad-viewer.md` walks the whole path end to end.

Two properties of the package are deliberate and easy to break:

- **No dependencies, standard library only.** It is imported into whatever interpreter is driving PartCAD, and
  depending on anything (a CAD library above all — which is exactly what depending on `ocp_vscode` did) risks
  dragging a second, differently-provisioned stack into that interpreter. Note that this is a constraint on the
  package, not on `partcad`: it is why the package can sit here without adding a single requirement.
- **It does not import `partcad`.** Geometry has already been tessellated into glTF by a PartCAD sandbox before
  it reaches here, so there is nothing to import. `partcad` imports *this*, lazily, from `partcad.viewer`.

The glTF payload codec (`encode_gltf`/`decode_gltf`) has two other implementations that have to agree with it:
`ocp_serialize.encode_gltf` in the sandbox, and `decodeGltf` in the extension. Neither can import this package,
which is why each carries its own copy; `tests/unit/test_viewer.py` and the extension's
`viewerProtocol.test.ts` are what catch a drift.

Its own tests live with the component, in `partcad-ide-client/tests`; `tests/unit/test_ide_client_is_shipped.py`
here covers the packaging side.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
