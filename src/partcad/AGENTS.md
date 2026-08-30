# partcad

Core Python module implementing PartCAD's digital-thread logic (packages, parts, assemblies, providers).
Source: `./src/partcad`. Tests: `./tests/partcad`. It is one of the packages inside the single `partcad`
wheel, which also carries `partcad_ide_client` (see "The PartCAD IDE viewer client" below) — run all commands
below from the repo root unless noted.

## Setup

All commands on this page run **inside the dev container**, not on the host — see "Where commands run" in the
root [AGENTS.md](../../AGENTS.md) for how to enter it. Dependencies are already installed in the image; re-run
`poetry install` only after changing `pyproject.toml`. The virtualenv is not auto-activated, so prefix the
commands below with `poetry run` (e.g. `poetry run pytest ...`).

```bash
poetry install   # from repo root; installs the whole `partcad` wheel in editable mode
```

## Test and validate changes

Running `pytest` to a clean pass is the required validation step for any change under `partcad/`:

```bash
pytest tests/partcad -x -p no:error-for-skips -p no:warnings --dist no   # matches CI (test-pytest job)
pytest tests/partcad -n 4 --timeout 300 -m "not slow"              # matches the pre-commit hook, faster locally
```

Tests live in `./tests/partcad` (`tests/partcad/unit`); slow tests are marked `slow` and excluded by the pre-commit hook's `-m
"not slow"`. Treat a failing `pytest` run as blocking — do not consider a change to this module complete until
it passes.

## Lint / format

```bash
black --check src/partcad tests/partcad     # line-length 120 (pyproject.toml)
flake8 src/partcad tests/partcad
isort --check src/partcad tests/partcad
```

## Conventions

- **Async naming**: every externally visible coroutine has a name ending in `_async`, paired with a synchronous
  wrapper of the same name without the suffix. Coroutines run on asyncio's event loop; CPU-heavy work runs on a
  separate thread pool (sized to CPU cores minus 1). Tasks on the thread pool must not call coroutines that use
  `asyncio.Lock()`. An assembly is instantiated on the *unconstrained* pool instead: it computes nothing itself,
  it waits for its parts, and each of those takes a thread from the constrained one -- assemblies waiting there
  is how enough of them at once run it out of threads, every one waiting for a part with nowhere left to run.

- **Sandbox concurrency**: a wrapper runs in a sandbox *environment* -- the runtime's own conda prefix, or the
  session v-env of a package that has requirements of its own -- and `sandbox_lock.py` is what holds those
  apart. `EnvironmentLock` is a readers/writer lock keyed on the environment's path: running a wrapper reads it,
  installing into it or creating it writes, so any number of wrappers share an environment while an install has
  it to itself. `process_slots` caps how many sandbox interpreters run at once, because a wrapper is a whole CAD
  process and it is the machine, not the thread pool, that decides how many fit; `threadsMax` sizes it. Both are
  polled rather than blocked on: they are taken from several event loops at once (a part is instantiated on a
  worker thread running a loop of its own), and a task that blocked its own loop waiting for a lock the task
  beside it is about to release would never see it released.
- **Location/coordinate format**: 3D locations (OpenCASCADE `TopLoc_Location`) are represented as
  `[[x, y, z], [rx, ry, rz], angle]` — translation in mm, then an axis vector and rotation angle (degrees)
  around it.

- **Software is not a shape** (`software.py`, `software_factory*.py`): a package's `software:` section declares
  the files a product ships with -- firmware images, binaries -- and `Software` deliberately does not inherit
  `Shape`. There is no geometry, so nothing here renders, exports, tessellates or caches a shape; what it shares
  with the shape factories is the `path`/`fileFrom` plumbing, and it shares it by following the same shape of
  code rather than by inheriting a class built for shapes. Only one type exists, `raw`; the ones that follow it
  name a firmware flashing procedure for the same file, so they belong beside `SoftwareFactoryRaw` and never as
  a second way of pointing at a file.

  A part or an assembly lists what it ships with in its own `software:`, resolved **once**, by
  `ShapeFactory.__init__`, into `software_resolved` -- that is the only place that knows which package authored
  the declaration, and an alias or an enrich hands the configuration on to packages where a bare name would mean
  something else. Every assembly's bill of materials then lists that software with the commit its package was
  read at (`revision.py`), because a firmware image, unlike a bracket, is a different file once its package
  publishes again. `lint/software.py` is what keeps that answerable: a file the package does not carry has to
  declare a `fileHash`, and `CamTest.software_failure()` enforces the same rule where it bites -- a board nobody
  can flash is not a board anybody can make, so a part fails the manufacturing test when its software does not
  resolve, cannot be fetched, or does not match its `fileHash`.

  `pc add` writes a `fileHash` by itself where it can: given a URL rather than a path it fetches the file once
  (`actions/add.py`) and records the hash of what came back, so an object added that way is pinned from the
  moment it exists. That is also why `FileFactoryUrl` raises on a failed HTTP status -- without it a 404 page
  is written out as the file, and `pc add` would pin the hash of an error page.

  `fileHash` itself is **not** a software feature and does not live here: it sits beside `fileFrom`/`fileUrl`
  and pins the *bytes* of any file a package fetches rather than carries, so it belongs to `file_factory.py`,
  which refuses a download that does not hash to it (and deletes what it refused, or the next run would skip
  the download and reuse it). It is optional in the declaration and required for reproducibility:
  `unreproducible_reason()` is the one statement of that rule, and `CamTest.reproducibility_failure()` is what
  makes a fetched-but-unpinned object fail the manufacturing test -- manufacturing is repetition, and a file
  that may be a different file tomorrow cannot be made again. There are three ways out and any one will do: a
  `vendor` and an `sku` (ordering the same SKU again is what "the same again" means for a bought thing), a
  file the package carries, or a `fileHash`. Only parts and assemblies can take the first -- the schema gives
  `vendor`/`sku` to those two alone -- so a sketch and a piece of software fall through to the file, which is
  why the check reaches sketches at all even though nothing manufactures a drawing. `lint/software.py`
  answers the same rule earlier, on the declaration, and only for software. A file a repository plugin serves
  is exempt for now (`PACKAGE_FILE_SOURCES`): a `fileHash` given for one is verified, it is simply not
  required yet.

  Keep all of it clear of the hashes PartCAD computes for itself -- `CacheHash`, a git revision -- which
  identify something PartCAD built or fetched, where this states in advance which bytes were asked for.

  That test reads more than the shape's hash covers, which is what `Test.cache_key_suffix()` exists for: a
  corrected `fileHash` has to move the cache key, or `pc test` answers the new declaration with the old one's
  failure.

- **Built-in packages** (`./src/partcad/builtin`): PartCAD ships two packages inside itself, reachable from
  every context as `//builtin/export` and `//builtin/render` (loaded on demand by `Context.get_project`, see
  `output.py`). They declare the file types `pc export` and `pc render` write, in exactly the form a user's
  package declares one — a `path` to a script, its `pythonRequirements`, and the export parameters. So adding a
  format, changing its defaults or changing which dependencies it needs is an edit to `builtin/*/partcad.yaml`, not
  to `shape.py`. The scripts run in a sandbox through `wrappers/wrapper_export.py`; they are data files, so
  anything new under `builtin/` has to be listed in `pyproject.toml`'s `package-data` and in the PyInstaller
  spec (see "Packaging" in the root [AGENTS.md](../../AGENTS.md)). The requirement strings there are the versions
  `sandbox_versions.py` pins, which `tests/partcad/unit/test_output.py` enforces.

- **Sandbox environment** (`./src/partcad/python_env.py`): importing `partcad` sweeps every `PYTHON*` variable
  out of `os.environ` and puts back only `PARTCAD_PYTHON_ENV`. Everything PartCAD spawns — the wrappers, `pip`,
  `-m venv`, conda — inherits that, which is why a sandbox interpreter runs with plain `-sOOu` rather than the
  `-I` it used to: `-I` implies `-E`, and `-E` would have made the sandbox ignore PartCAD's own
  `PYTHONHASHSEED=0` along with the user's `PYTHONPATH`. So do not reintroduce `-I`/`-E` on a sandbox command
  the environment already covers, and add anything a sandbox interpreter has to be told through the environment
  to `PARTCAD_PYTHON_ENV`, where the sweep cannot take it away again.

  Below `sandbox_versions.MIN_PYTHON_VERSION_SAFE_PATH` the environment does *not* cover it: `PYTHONSAFEPATH`
  arrived in 3.11 and an older interpreter ignores it, which would leave the directory PartCAD runs from first
  on `sys.path` for the `-m venv`/`-m pip` calls that provision a sandbox. Those calls — and only those — keep
  `-I` there, which is why `PythonRuntime` carries two flag lists (`python_flags` for a wrapper,
  `python_provisioning_flags` for a `-m` command) and picks between them in `flags_for()`. A wrapper is run by
  path, so its `sys.path[0]` is PartCAD's own `wrappers/` directory rather than anything a user writes to;
  giving it `-I` would buy no isolation and would cost it `PYTHONHASHSEED`, since `-I` implies `-E`. So do not
  collapse the two lists back into one, and do not hand `-I` to anything but a `-m` command.
  `tests/partcad/unit/test_python_env.py` asserts the outcomes (a `venv.py`/`pip.py` beside the interpreter
  never wins; a wrapper's sibling import is never shadowed by a file in PartCAD's working directory; the hash
  seed is honored on every version) on whichever version is running, so both branches are covered by the CI
  matrix rather than by a comment.

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

`./src/partcad_ide_client` is the Python half of the socket protocol that connects `partcad` to the PartCAD
IDE extension's **PartCAD Viewer**. It is a sibling package in the same wheel, so `pip install partcad` makes
`import partcad_ide_client` work and nothing has to install it separately.

It ships that way rather than as a distribution of its own because it was never on PyPI and every process that
could import it is a process that already imports `partcad` — `partcad.viewer` is its only importer in the
tree. Two distributions owning one import name is the thing being avoided: pip does not detect the overlap when
installing, and uninstalling either one then deletes the module out from under the other, silently. So do not
give `partcad_ide_client` a `pyproject.toml` of its own, and do not vendor a second copy into the VS Code
extension — a copy that lands first on `sys.path` shadows this one in one process and not another, leaving two
different clients in play depending on which process is asking.

The other half of the protocol is `ide/vscode/src/viewer/protocol.ts`. **A change to the wire format is
a change to both files**, and the frame layout is specified once, in
`src/partcad_ide_client/protocol.py` — that docstring is the normative description.
`ide/vscode/docs/partcad-viewer.md` walks the whole path end to end.

Two properties of the package are deliberate and easy to break:

- **No dependencies, standard library only.** It is imported into whatever interpreter is driving PartCAD, and
  depending on anything (a CAD library above all — which is exactly what depending on `ocp_vscode` did) risks
  dragging a second, differently-provisioned stack into that interpreter. Note that this is a constraint on the
  package, not on `partcad`: it is why the package can sit here without adding a single requirement.
- **It does not import `partcad`.** Geometry has already been tessellated into glTF by a PartCAD sandbox before
  it reaches here, so there is nothing to import. `partcad` imports *this*, lazily, from `partcad.viewer`.

The glTF payload codec (`encode_gltf`/`decode_gltf`) has two other implementations that have to agree with it:
`ocp_serialize.encode_gltf` in the sandbox, and `decodeGltf` in the extension. Neither can import this package,
which is why each carries its own copy; `tests/partcad/unit/test_viewer.py` and the extension's
`viewerProtocol.test.ts` are what catch a drift.

Its own tests live in `tests/partcad_ide_client`.

## Commit

`pre-commit` hooks (`dev-tools/pre-commit-config.yaml`) run `pytest`, formatting, and lint checks on commit and
are required to pass in CI before a PR can merge.
