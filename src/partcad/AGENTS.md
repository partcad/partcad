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
isort --check --filter-files src/partcad tests/partcad
```

All three gate — each is a `pre-commit` hook and a `Lint (...)` job in `test.yml`, and the tree satisfies
all three, so a finding from any of them is yours. See the root [AGENTS.md](../../AGENTS.md) for the two flags that
are load-bearing (`--filter-files`, and the `Flake8-pyproject` plugin without which flake8 reads no config
at all).

## Conventions

- **Async naming**: every externally visible coroutine has a name ending in `_async`, paired with a synchronous
  wrapper of the same name without the suffix. Coroutines run on asyncio's event loop; CPU-heavy work runs on a
  separate thread pool (sized to CPU cores minus 1). Tasks on the thread pool must not call coroutines that use
  `asyncio.Lock()`. An assembly is instantiated on the *unconstrained* pool instead: it computes nothing itself,
  it waits for its parts, and each of those takes a thread from the constrained one -- assemblies waiting there
  is how enough of them at once run it out of threads, every one waiting for a part with nowhere left to run.

- **Admission limits**: `threadsMax` also caps how many tests and how many linting checks run at once, and both
  go through `concurrency.ReentrantGate` rather than a bare `asyncio.Semaphore`. A check may run the other
  checks itself -- `CamTest` runs the whole suite over everything an assembly is procured from, from inside the
  call the gate has already admitted -- so nested work is charged to the permit its caller already holds. A
  semaphore counts it as a new arrival instead, and once as many callers as the limit are each waiting on a
  nested call, every permit is held by somebody waiting for one and the loop stops for good. That is what hung
  `pc test -r`, and with it the daemon serving it. The gate keeps one semaphore per event loop for the same
  reason `sandbox_lock.py` polls: these are taken from several loops at once, and the daemon runs one
  `asyncio.run()` per request, so a semaphore kept for the process belongs to whichever request created it.

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

- **Engineering analysis** (`./src/partcad/cae.py`, `Shape.analyze_async()`, `./src/partcad/test/cae.py`):
  `pc cae fea`/`pc cae cfd` are a third output section, `cae:`, resolved by the very code that resolves
  `export:` and `render:` -- same `path`/`package`, same sandbox, same meta-wrapper (`wrapper_export.py`), and
  `Shape._run_implementation_async()` is the body all three share. It is deliberately **not** in
  `output.SECTIONS`: that tuple answers "which sections does a file type of `pc export`/`pc render` live in",
  and a `fea` left in there would be offered to `pc render -t` and would fall back to a render implementation.
  It also has no built-in package -- PartCAD ships no solver -- so `output.builtin_project()` answers `None`
  for it and everything downstream has to cope with a missing bottom layer.

  What is genuinely new is the two halves either side of the script. Going in, the *part* declares the
  boundary conditions in a section named after the analysis, because they belong to the part and not to
  whoever analyses it; `cae.py` parses `fix:`/`load:`, converts the units (a bare number is a mass in
  kilograms, weighed into newtons at `GRAVITY`; everything is stored as force), and `assign_ports()` attaches
  them to the ports `render_overlay.collect_async()` already knows how to find -- so `pc render --with-ports`
  draws exactly what a solver was told. Coming back, the implementation reports **findings** beside the file
  it wrote, a JSON array that `pc cae` prints, `pc test`'s `fea`/`cfd` checks fail on, and the IDE lists under
  the model. `cae.py` imports nothing from `partcad`, which is what lets it be tested without a sandbox.

  Both checks are gated on the part *declaring* the section, and that gate is the whole cost model: a
  `pc test -r` over a package tree must not start a solver for every bolt in it, and a bolt with no `fea:` has
  nothing to tell one. Declaring `fea:` is how a user asks for the check, which is why it needs no flag.

  A **missing or misconfigured plugin fails**: the implementation is named `<package>:<file type>` by the
  part's `implementation:` or by the user configuration, and if that package is not a dependency, did not
  load, or declares no such file type, the configuration is wrong on every machine and no install mends it.
  `CaeTest` resolves it separately from running it, so the two are told apart.

  **An analysis that does not run also fails**, and this is deliberately not a skip. A skip says the question
  does not apply here; a plugin that resolved, was asked, and produced no answer has failed -- no mesher, no
  solver, a sandbox that will not build, a crash. `CaeTest` cannot tell those apart and does not try: it
  relays whatever the implementation said, through `cae.dysfunction_report()`, which adds the two things the
  sentence usually omits and the reader always needs -- which implementation was asked, and which machine it
  did not work on.

  This was the other way round until it was found to be hiding things worth failing over: a CFD implementation
  that never converges, and a plugin that cannot be installed on a whole platform. The consequence is the
  point -- declaring `fea:` in a shared package makes `pc test` fail for everyone who has not installed what
  the implementation needs, which is what declaring it means. A package that does not want that should not
  declare the section, the same gate that stops `pc test -r` starting a solver for every bolt in a tree.

  That failure is the one verdict `pc test` does **not** cache, via `Test.NOT_CACHEABLE` on the `test_ctx`. A
  cache key describes the question -- the shape's hash, the boundary conditions, the implementation and its
  options -- and nothing in it describes the machine, because a test cannot know what its implementation needs
  installed. Installing CalculiX therefore changes no key, and a remembered failure would go on failing a part
  that now analyses perfectly well. `CaeTest` is the only test that reaches that state, and the flag exists
  for it.

- **A part is a body, not a skin** (`wrappers/wrapper_common.solidify`, `brep_inspect.py`,
  `test/shell.py`): a shell is a set of faces with nothing said about which side of them is material; a solid
  is a shell declared to bound a volume. The declaration changes nothing about how the shape looks and
  everything about what can be computed from it — a boolean taken against a shell comes back with no solid in
  it — so a part handed back as a shell renders, exports and measures correctly and is wrong for interference,
  CAM, FEA and any mass in a bill of materials. cadquery and build123d both let a script return one, and a
  partType that meshes triangles builds one by nature.

  So the wrappers convert: `solidify()` replaces a **closed** shell with the solid it already bounds,
  descending into compounds (which is the case that happens, since `combine()` compounds whatever a script
  returned) and orienting the result, because a closed shell whose faces point inward would otherwise become a
  solid of negative volume — the failure `test/solidity.py` exists to report. It returns its argument
  unchanged when there is nothing to convert, so a part with no shell in it serializes to the bytes it always
  did. An **open** shell is left alone: there is no solid it bounds, and declaring one anyway would replace an
  honest surface with an invalid solid that computes nonsense. Neither is a part read from a *file* — `step`,
  `brep`: those wrappers hand over what the file holds, because the file is the authority on what the part is,
  `pc convert` round-trips through them, and a surface model somebody shipped is worth reporting rather than
  quietly changing.

  Which leaves the core to notice the ones that were not converted, and it does that **without a CAD kernel
  and without a sandbox**: `brep_inspect.py` reads the `TShapes` section of the BREP payload the core already
  holds — one record per shape, each opening with a two-letter type code — and counts the shells no solid
  references. Every solid is bounded by a shell, so "the payload contains a shell" is true of a box and says
  nothing; what is asked is whether a shell bounds anything. It counts the references rather than resolving
  them, so it never has to know which end of the record list the indices count from. `test/shell.py` is the
  check that reports the result, and it is the cheapest one `pc test` runs. Do not answer this question in a
  sandbox, and do not turn the scanner into a BREP reader: everything between a record's type code and the line
  its sub-shape list ends on is geometry, and is skipped unread.

  **No object can exclude itself from this check, nor from `degenerate` or `solidity`, and none of the three
  may be given a setting that lets it.** All three report a fact about the geometry — a surface where a body
  was meant, a part that collapsed in one direction, a solid that is inside out — and a part in that state is
  one nothing downstream can compute with, whatever it was meant to be. A check an object can turn off is a
  check that reports on the objects that did not need checking. A *kind* of object that is exempt is exempt on
  what it is and decided here: a sketch is not measured for having size in every direction, and an assembly is
  checked through its parts. What to do about a part that fails is a decision to take on that part.

- **One shape, one lock** (`Shape.locked()`): a shape is held still both while it is instantiated and while
  any file derived from it is produced. They are one question because the output path is derived from the
  shape -- `<part>.<format>` beside the package -- so two concurrent runs over one shape resolve to one path
  and interleave there, one deleting a model between the moment its owner wrote it and the moment its owner
  read it back. It is re-entrant because the operations nest (`analyze_async` holds it across
  remove-run-verify and calls `get_wrapped` and `_run_implementation_async` inside that), which a bare
  `asyncio.Lock` cannot do without waiting on itself for good. The cost is that two different outputs of one
  shape no longer overlap; PartCAD's parallelism is across shapes.

- **Drawing ports and interfaces** (`./src/partcad/render_overlay.py`, `./src/partcad/wrappers/stroke_text.py`):
  `pc render --with-ports`/`--with-interfaces` draws the connection metadata on top of a projection.
  `render_overlay.py` answers only *where* the ports are — a lookup for a part, a walk for an assembly (and so
  for a scene, which is one), all of it plain arithmetic on `geom.Location` plus the port sketches' existing
  envelopes, so the core stays free of OCP — and `builtin/render/render_svg.py` does the drawing, because it is
  the only side that knows where the camera is. The labels are line segments from `stroke_text.py` rather than
  an SVG `<text>` element: PNG and JPEG go through the SVG and would keep one, but DXF converts paths only, and
  real text geometry would need a font whose version this repository does not control. Two things ask for the
  overlay and neither overrides the other — the command line, and a `render:` file type declaring
  `with_ports:`/`with_interfaces:` — which is `render_overlay.effective()`, and is how
  `examples/feature_interface` keeps four such drawings checked in.

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

**Neither schema is here.** Both `partcad_utils/schema/partcad.json` (the `partcad.yaml` schema) and
`partcad_utils/schema/assy.json` (the ASSY one) live beside `partcad_utils.assy_lint`, the checker that reads
both, and ship through `[tool.setuptools.package-data]` in `pyproject.toml` and the PyInstaller spec's copy of
that directory. They are there because a client checks the file it is editing without a daemon and without a
CAD kernel: a schema under `partcad` would mean importing one to read a JSON file. `lint/all.py` registers the
checks — the names it gives them are what `pc lint -f` filters on — and `get_partcad_schema()` is the one way
in for anything that wants the configuration schema itself.

`lint/schema.py` is the *package* half of both checks: `SchemaLinting` walks a package's `partcad.yaml`,
`AssySchemaLinting` its `.assy` files, and `YamlLinting` under them is the shared body — reading the file and
handing it to `assy_lint.validate_source`. Walking a package needs the package graph, which is daemon work,
while each client checks the one file being edited in its own process (`partcad_client.lint`, reached by
`pc lint --file`). Two implementations of that check would let an editor and CI disagree about a file, so there
is one, in the package both ends already depend on. That is also why `AssySchemaLinting.get_targets` asks
`assy_lint.is_assy_file` rather than "does this file have a schema": both kinds have one now, and the looser
question would have it walk `partcad.yaml` too and report every finding twice.

A `partcad.yaml` is a Jinja2 template exactly as an ASSY file is — `ProjectLocal` renders it, `includePaths`
and all — so it goes through the same masking rather than straight to `yaml.safe_load`, and every finding
carries the line and column it came from. **A gap in the configuration schema is now a squiggle on a working
file**, not a message in a CI log nobody reads: whatever PartCAD's own tooling writes has to validate. `pc init`
writes empty (null) sections, so every section accepts null; every registered part type has to be in the
`parts` enum (`sdf` was not, and two shipped examples failed their own check because of it).

The **scene** schema is that same schema with `how` forbidden, derived from it by
`assy_lint.scene_schema()` rather than kept beside it as a second file — a copy is a copy that stops matching.
Which of the two a given `.assy` is checked against is not a property of the file but of what points at it, so
the package half reads the declaration (exact) and each client works it out best effort: `pc lint --file` from
the `partcad.yaml` files around the file, the VS Code extension from the package contents it has already
loaded. All three lean the same way — unknown means assembly, because reading an assembly as a scene would put
a false error on correct code.

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
