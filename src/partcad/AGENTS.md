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
  checks itself -- `ManufacturabilityTest` runs the whole suite over everything an assembly is procured from,
  from inside the call the gate has already admitted -- so nested work is charged to the permit its caller
  already holds. A
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
  declare a `fileHash`, and `ManufacturabilityTest.software_failure()` enforces the same rule where it bites
  -- a board nobody can flash is not a board anybody can make, so a part fails the manufacturing test when its
  software does not
  resolve, cannot be fetched, or does not match its `fileHash`.

  `pc add` writes a `fileHash` by itself where it can: given a URL rather than a path it fetches the file once
  (`actions/add.py`) and records the hash of what came back, so an object added that way is pinned from the
  moment it exists. That is also why `FileFactoryUrl` raises on a failed HTTP status -- without it a 404 page
  is written out as the file, and `pc add` would pin the hash of an error page.

  `fileHash` itself is **not** a software feature and does not live here: it sits beside `fileFrom`/`fileUrl`
  and pins the *bytes* of any file a package fetches rather than carries, so it belongs to `file_factory.py`,
  which refuses a download that does not hash to it (and deletes what it refused, or the next run would skip
  the download and reuse it). It is optional in the declaration and required for reproducibility:
  `unreproducible_reason()` is the one statement of that rule, and
  `ManufacturabilityTest.reproducibility_failure()` is what makes a fetched-but-unpinned object fail the
  manufacturing test -- manufacturing is repetition, and a file
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

- **A file type may name the package that implements it** (`output.split_format`,
  `Shape._output_implementor`): `pc export -t sim-gazebo:world`, the spelling `import:`, `simulation:` and
  `pc cae --implementation` already took. It exists because there are formats PartCAD ships no implementation
  of — an engine's own scene format lives in that engine's plugin package — so the bare name has nothing to
  resolve. The named package goes in as a layer directly *above* `//builtin` rather than replacing the lot,
  unlike `import_declaration()` with the same spelling, because this section also decides where the file
  goes: `output_dir` and `prefix` are the caller's business whoever writes the file.

  Two places filter a format name against a list and both had to learn about it: `Project.render_async()`
  enumerates the file types this package and the built-in ones declare, and a path is in neither, so
  `pc export -t <package>:<type>` reported success and wrote nothing; and the daemon's
  `_validate_output_format()` rejected it before resolving it. Anything else that grows such a list needs the
  same treatment — "which types can I write" is a question a path has already answered.

- **Built-in packages** (`./src/partcad/builtin`): PartCAD ships six packages inside itself, reachable from
  every context as `//builtin/export`, `//builtin/render`, `//builtin/import`, `//builtin/open`,
  `//builtin/cam` and `//builtin/scene` (loaded
  on demand by `Context.get_project`, see `output.py`). All but the last declare implementations — the file
  types `pc export`, `pc render`, `pc import`, `pc open` and `pc cam` write — in
  exactly the form a user's package declares one: a `path` to a script, its `pythonRequirements`, and the
  parameters. So adding a
  format, changing its defaults or changing which dependencies it needs is an edit to `builtin/*/partcad.yaml`, not
  to `shape.py`. The scripts run in a sandbox through `wrappers/wrapper_export.py`; they are data files, so
  anything new under `builtin/` has to be listed in `pyproject.toml`'s `package-data` and in the PyInstaller
  spec (see "Packaging" in the root [AGENTS.md](../../AGENTS.md)). The requirement strings there are the versions
  `sandbox_versions.py` pins, which `tests/partcad/unit/test_output.py` enforces — as does a check that every
  built-in package validates against PartCAD's own configuration schema, since nothing else reads them.

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

- **Routes** (`./src/partcad/cam.py`, `Shape.route_async()`, `./src/partcad/builtin/cam/`):
  `pc cam` is a fourth output section, `cam:`, resolved by the very code that resolves the other three, and
  out of `output.SECTIONS` for the reason `cae:` is. It differs from `cae:` in one thing that matters: it
  **has a built-in package**. A route is arithmetic on the object's own outline rather than somebody else's
  program with a release cycle of its own, which is the test `export:`/`render:` pass and a solver does not,
  so `//builtin/cam` ships and `camImplementation` names it by default.

  The object declares the job in a `cam:` section of its own -- the same word as the package-level section,
  and deliberately so. For CAE the two names differ because boundary conditions and mesh sizes are different
  kinds of thing; here the tool, the depth and the feed are the file type's parameters *and* the object's
  statement about itself, so they are one namespace with `//builtin/cam`, the package and the object as its
  three layers. What keeps that unambiguous is that `cam.KEYS` is a **closed** set: an object's section holds
  job parameters and nothing else, so it can never be read as a file-type declaration, and a key that is
  neither is refused with a sentence rather than passed through.

  `cam.py` parses and converts (lengths to millimetres, feeds to millimetres per minute, and both at *every*
  layer through `normalize_job()` -- a `2400 mm/min` written by the package is as much PartCAD's to understand
  as one written on the object). Like `cae.py` it imports nothing from `partcad`, which is what lets it be
  tested without a sandbox. It requires nothing, on purpose: "a route needs a cutter diameter" is
  `//builtin/cam`'s statement about itself, not PartCAD's about a plugin it has never seen.

  The section is also the object's **opt-in**, and `Project.routable_shapes_async()` is where that is read:
  `pc cam` with no object named visits every sketch and part that declares one and passes over the rest
  silently, which is why `cam.declared_config()` exists beside `config_of()` -- deciding what to visit must
  not raise on a neighbour's broken section. Sketches and parts only; an assembly is put together rather than
  cut.

  Coming back, the implementation reports **stats** beside the file it wrote, the way a `cae:` one reports
  findings, and `wrapper_export.py` passes them through without interpreting them: what is worth counting
  differs between a router and a wire EDM.

  `pc test` runs it as the `cam` check (`./src/partcad/test/cam.py`), which is `CaeTest`'s shape over
  `route_async()`: the same gate (declare the section or the check does not apply), the same cache key
  (the job, the implementation, and its resolved options), the same refusal to call a failure a skip. One
  thing differs, and it is where the file goes: an analysis keeps its model beside the package because the
  model is the answer somebody asked for, while a route a *check* produced is a by-product that would be
  indistinguishable from the one `pc cam` writes -- so the check routes into a temporary directory and
  deletes it.

  **The check that used to be called `cam` is `manufacturability`** (`./src/partcad/test/manufacturability.py`
  and its four method-specific siblings). It asks whether an object can be made or bought at all; this one
  asks whether the program that makes it can be produced. One word answered both until `pc cam` existed. `-f`
  filters by name prefix, which is what makes the split clean: `-f manufacturability` selects that check and
  its siblings, `-f cam` selects the route check alone. Renaming a check changes every cached verdict's key,
  so the first `pc test` after this re-runs everything -- once.

- **A subtractive part names what it is cut from and what cuts it** (`part_config_manufacturing.py`,
  `test/manufacturability_subtractive.py`, `test/manufacturability_machine.py`): `subtractive` was a label until
  this -- a part declared it and nothing read it. It now carries two claims, and each is checked.

  `source:` is the stock. Cutting only removes material, so the part has to be what is left of it: nothing of it
  outside the stock, and the stock bigger somewhere. Both halves, because each catches a different mistake and
  neither implies the other -- a part that pokes out cannot be cut from it at all, and a part that fills it
  exactly is one whose `source:` names itself. Measured by `wrapper_manufacturability.enclosure`, which returns
  the four volumes rather than a boolean so a failure can say whether it missed by a rounding error or by a
  feature. Required, like `sheet_metal`'s: subtraction is *defined* by what it starts from, so a declaration naming no
  stock has not said what the method means. That is a breaking change to a method parts already declare, and
  the fixtures in this tree that carried `subtractive` as scaffolding were moved to `additive` rather than
  given a stock they do not have -- see the note at the top of each.

  The **machine** is named by adding its own subsection -- `cnc:`, `drilling:` or `laser:` -- rather than by a
  `machine:` key, because the three do not take the same options and one namespace would leave nothing to say
  which belongs to which. None of them is CNC: the machine that can make anything the other two can, and what
  every `subtractive` part written before this meant. `MACHINE_KEYS` is closed for the reason `cam.KEYS` is, and the axis is `toolAxis:` rather than `direction:` because an object's `cam:` section already has a `direction` meaning climb or conventional, and both reach one implementation in one request.

  The two limited machines get a check each (`manufacturability-laser`, `manufacturability-drilling`), and each
  applies **only to a part that named it** -- a package that has said `method: subtractive` for a year must not
  start failing a check about a laser it does not own, which is what `MachineConfig.declared` is for. Both rest
  on `wrapper_manufacturability.wall_alignment`, which classifies every face against the machine's axis by
  **sampling its normal** rather than by reading its surface type: a cylinder is a wall when it is coaxial with
  the axis and a defect when it lies across it, and a spline extruded along the axis is a perfectly good wall no
  type test would accept. Drilling asks one thing more and asks it of a different subject -- the material the
  machine *took away*, which is `source` minus the part -- because a drilled plate's straight sides came with
  the stock and asking the part's own walls would fail every plate for having them.

  `pc cam` writes for all three from the one `gcode` file type, and which one comes from `manufacturing:` and
  not from `cam:` (`Shape._route_machine_data`, applied after every other layer so nothing can override it):
  what a part is made on is a property of the part, and a route for a machine nobody owns is the failure that
  reaches the shop floor. A part that names no machine produces the bytes it always produced, which is worth
  keeping true -- `_orient` is the identity for the default `-Z` precisely so that it stays so.

  `examples/produce_part_subtractive` is the whole of it, and its laser-cut `blank` is what the sheet metal
  example bends -- named across packages, so the piece that goes into the brake is a part whose own making is
  described rather than one asserted to exist.

- **A sheet metal part names what is bent and how** (`part_config_manufacturing.py`,
  `test/manufacturability_sheet_metal.py`, `wrappers/dxf_metadata.py`): `sheet_metal` is the one manufacturing
  method that is not described by the part alone. The others say how a shape comes out of stock; this one says
  an existing flat piece went through a brake, so its `manufacturing:` section carries a `source:` (the part
  that is bent) and an `instructions:` (the sketch that says where the bends are), both required and both
  resolved as references against the part's own package. The outline, the holes and the cut-outs belong to the
  `source`, which is cut flat and so is usually an ordinary `subtractive` part -- they are deliberately
  **not** describable inside the sheet metal step, because the process that bends cannot make them. `source`
  is not held to that method, though: what the check asks of it is that it is *flat*, so a bought-in blank
  declaring no method, a `forming` one sheared to outline, and an `alias` or `enrich` of a part declared
  elsewhere are all blanks it takes.

  `ManufacturabilitySheetMetalTest` asks one question of each half: the blank is flat top and bottom (the
  horizontal plane through its extreme Z meets it in an area rather than at a point --
  `wrapper_manufacturability.flatness`, which sums the horizontal planar faces at each extreme rather than
  taking a boolean, since a tolerance deciding whether two planes are the same plane is the very thing being
  measured), and every bend line states a positive `angle` in degrees, a positive inner `radius`, and a
  `direction` of up or down. It is the one test whose `cache_key_suffix()` has to *resolve another object* to
  state what it read -- `manufacturing:` is one of the keys a shape's hash deliberately leaves out, and so is
  the drawing the instructions come from -- which is why that hook is a coroutine.

  `examples/produce_part_sheet_metal` is the whole of it in one package, and is what the end-to-end
  `@pc-test-sheet-metal` scenario in `features/test.feature` runs against.

- **A sketch says what its drawing said** (`Sketch.get_annotations`, `Shape.CACHED_SIDE_DATA`,
  `wrappers/dxf_metadata.py`): BREP has nowhere to put an angle written against a line, and a DXF says exactly
  that in XDATA. So the import reads it and the sketch carries it: one record per element -- its type, layer,
  handle, where it is, and the key/value pairs -- keyed to the same layer filters the import was given, so the
  annotations describe what is *in* the sketch. `CACHED_SIDE_DATA` is what makes it survive, because a sketch
  that comes out of the cache is never instantiated; it is an entry of its own beside the geometry, and a
  cached shape whose side data is **absent** is built again rather than answered with nothing -- an empty
  entry means "read, and it said nothing", while no entry means "written before any of this existed", and a
  check would act on the difference. This is also what makes sheet metal instructions *a sketch* rather than
  *a DXF file*: `dxf` is the only type that states anything today, and nothing downstream knows that.

  One thing had to give for that to be usable at all. CadQuery's DXF importer builds **faces**: it merges
  each layer's entities into wires and asks each wire for the face it bounds, so a drawing whose lines do not
  close fails outright -- and a drawing whose lines do not close is exactly what bend instructions are. So
  `wrapper_import_dxf` keeps the face import as the first answer and falls back to the wires the selected
  layers draw, with a warning naming what happened, because the other way to reach that fallback is an
  outline with a gap in it. Every DXF that imports today imports byte-identically; this is a second answer to
  a question that had none. The fallback mirrors the importer's layer rule (case-insensitive, `include` and
  `exclude` mutually exclusive) and `dxf_metadata.is_included` applies the same one, so the geometry and the
  annotations describe one set of elements.

  **Which layers of a drawing a sketch reads is an object-type parameter**, not merely a field
  (`sketch_factory.py`, `sketch_factory_dxf.py`, `Project.declare_object_type_parameters`). `include` and
  `exclude` are contributed by the `dxf` type the way `material`/`color`/`tolerance` are contributed to a
  part, with the sketch's own registry of policed names; the top-level fields stay what they always were, as
  the default. What that buys is a reference setting them -- `bends;include=BEND_UP,BEND_DOWN` -- on a sketch
  that declares no `parameters:` at all, which is one drawing read as many ways as there are uses for it
  instead of one declaration per combination of layers. Two pieces make it work: `get_object` declares the
  accepted names on the object's behalf when a reference sets one (a name the type does **not** contribute is
  left alone, so a typo stays a typo), and `parse_parameterized_name` treats a comma-separated fragment with
  no `=` as a continuation of the value before it, because a list value has commas in it and a comma is also
  what separates parameters.

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
  `//builtin/scene` is the odd one out: it declares an *object* rather than a way of producing one — the
  scene a `simulate:` places its subject in when it names none of its own. It is an ordinary `assy` scene
  whose `.assy` is a Jinja2 template, and the only thing that makes it the default is that
  `simulation.DEFAULT_SCENE` names it.

  **There is deliberately no `//builtin/simulate`.** `simulation:` is a third section resolved exactly like
  the other two — a plugin is an `output.Implementation` like any other — and PartCAD implements none of it.
  A simulator is somebody's program with a release cycle of its own, so PartCAD ships the concept (the
  section, `wrappers/wrapper_simulate.py`, the runner in `simulation.py`) and a package supplies the physics:
  `partcad/partcad-sim-mujoco` is the MuJoCo one and `partcad/partcad-sim-gazebo` the Gazebo one. Each
  declares four things about one format — `import:` to read it, `export:` to write it, `simulation:` to run
  it and `open:` to look at it — because they are one piece of knowledge and a reader and a writer maintained
  apart disagree. A plugin's `format:` therefore resolves in **its own** package as well as the scene's
  (`simulation._export_scene_async` passes the plugin as the options package), which is what lets it name the
  format it implements itself.
  `simulation:` is also **not** in `output.SECTIONS`: everything that reads that tuple is asking which file
  types exist, and a simulation is not one.

  **`import:` is the fourth, and the mirror image of `export:`.** It declares who turns somebody else's
  file format *into* a PartCAD object, and it is why there is no `assembly_factory_urdf.py` any more:
  `assembly_factory_imported.py` is one factory for every such type, and the reader it runs is named by the
  declaration. Everything below the reader — sandbox, tree walk, part registration, the report of what was
  dropped — was identical in the three factories that used to exist, so only the reader knows XML and only
  the reader is a plugin. `//builtin/import` ships `urdf` and nothing else; `mjcf` and `world` belong to the
  two engine plugins, beside the exporter, the `open:` entry and the simulator that share their knowledge of
  the format. The wheel carries no copy of either, so `type: world` resolves to nothing and says which
  package to name: the spelling is the full path, `type: sim-gazebo:world`.

  **A type named by its full path is resolved from the package that declared the object, not from the root.**
  `Context.get_project_from()`, not `get_project()`: a package's objects are created as part of loading it,
  so the package doing the asking is not in `ctx.projects` yet and a root-first lookup answers None for a
  dependency that is declared perfectly well. That is not a corner case — it is every object of this kind on
  the way in — and it worked on the second attempt, which is what made it look like a flake.

  Two things about it are easy to get wrong. **`import:` was the old name of `dependencies:`**, and
  `project_config.py` used to migrate it in silence — copy the value across and delete the key — which would
  now eat a reader declaration before anything could read it, then try to fetch it as a package. So the
  migration is gone and the old use is **reported** instead: `Configuration._obsolete_import_entries()`
  looks for a dependency's required `type:` (`git`/`tar`/`local`/`external`) or its transport-only keys
  (`url`, `relPath`, `revision`, `subfolder`, `onlyInRoot`, `cacheVersion`, `includePaths`, `plugin`), none of
  which a reader declaration has. Do not restore the copy: guessing is what made the two ambiguous.

  **How loudly is the one thing that depends on whose package it is**, and both halves were learned the hard
  way on #637. In the *root* package it is an error and the package is broken, the way every other unreadable
  `partcad.yaml` is — that is the file the user can fix. In an *imported* one it is a warning and the package
  stays usable for everything else it declares, because `Context.import_project()` reports a broken import as
  an error of its own: `//pub/universe` in the public index uses the old spelling today, so marking it broken
  failed `pc list all -r` — every command that merely walks past it — over a section the user cannot reach,
  let alone rename. And do not make it raise in either case: an exception escaping a project factory strands
  the name in `Context._projects_being_loaded`, so every later import of it reports a recursion that is not
  happening — naming the innocent package rather than the one that failed. Both of those broke
  `Examples ... via bundle`, in that order. And an
  object type that no built-in factory is registered for is what
  `factory.instantiate()` routes here, which is also how `project.produces_own_parts()` decides, by exclusion,
  which objects materialize parts of their own: PartCAD cannot list the types in a section whose whole point
  is that it does not know what is in it.

  **`open:` is the fifth, and the only one whose implementation is not a script.** It declares the
  third-party applications `pc open` launches, as data: binaries per OS, a container image, the arguments
  each front end takes, and what the application can read. The logic is the same for every tool and stays in
  `partcad_client.external`, which now *builds* its `Tool` table from those declarations instead of holding
  five literals. Blender's argument builder was the one callable in that table and is now `fileArgs:`
  templates (`{path}`, `{path_repr}`) plus `ownFormats:` — a package cannot ship a Python function into a
  frozen client.

  The subtlety is where the table is read. `pc open` deliberately needs **no package graph** (it is handed a
  path; the window belongs to whoever ran the command; a daemon can be remote), so the built-in entries are
  read straight off disk out of the wheel — `partcad_client` locates them with `importlib.util.find_spec`
  without importing `partcad`, the same reason `object_types` holds its own copy of PartCAD's tables. Only a
  tool a *package* declares needs the graph, and that is the `open.tools` method: the daemon says **which**
  applications exist, and never opens one. Do not add a method that opens a file.

- **A material is a fact a simulation reads** (`material.py`): `mu` sits beside `density`, and
  `PHYSICS_FROM_MATERIAL` is what makes it reach an exporter. A shape names its material by a *reference*
  (`:aluminium`), and resolving one needs the package graph — which the core has and a sandbox does not. So
  `physics_by_shape()` resolves every reference in an export request against the package of the shape that
  wrote it (which is what lets the reference be relative), and `wrapper_export.properties_index()` merges what
  it found *underneath* what each shape states itself. No exporter knows materials exist, which is what keeps
  URDF's `<mu1>`, SDFormat's `<mu>` and MJCF's `friction` agreeing for free.

  Which reference it reads is `properties: material:`, and **a package never writes that by hand**.
  `parameters:` is what is asked of the type that produces the shape; `properties:` is what the shape turned
  out to be, and is filled in by whatever built it. For a type that accepts a `material` parameter — the
  homogeneous ones, `PartFactoryHomogen` — what it turned out to be made of is exactly what was asked for, and
  `PartFactory.record_object_type_properties()` is the instantiation code that writes it down. A `step` part
  accepts no such parameter (its file states a material per solid, and says it better), so nothing is promoted
  and the reader that read the file is what fills the property in.

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

- **Parametric interfaces and ports** (`./src/partcad/expr.py`, `interface_config.py`, `interface.py`,
  `Project.get_interface`): an interface is parametrized the way a part or a sketch is —
  `m-thru;size=4,depth=3` names an instance, `Project.get_interface` builds it from the declaration as a
  template, and the shared `parse_parameterized_name`/`format_parameterized_name`/`apply_parameter_values`
  are what read the suffix, so there is one answer to what `;size=4` means. Three things about it are
  load-bearing:

  **One `parameters:` section holds two kinds, told apart by content.** It has meant the freedom of
  movement a made connection keeps (`InterfaceParameter`) since interfaces existed, and it now also holds
  the construction values a reference sets — because "the same way as for a part" is the point of the
  feature. The split is `interface_config.is_movement_parameter`, and it is safe because the two
  vocabularies do not overlap: a movement parameter is one of the six predefined names, a `[min, max,
  default]` list, or states `min`/`max`/`dir` or `type: move`/`turn`; a part's parameter states none of
  those. Every movement parameter the schema has ever accepted is caught — a custom name is *required* to
  state its `dir` — so nothing written before this changes meaning. `WithPorts` overrides both accessors:
  for a shape that section has only ever meant construction values, so none of it is movement.

  **The name is canonicalized before anything is looked up under it.** An interface's full name is what a
  mating is registered under, so `m-thru;size=4` and `m-thru;size=4.0` being two objects would be two
  halves of a connection that never find each other. `canonical_parameter_values` puts every value through
  the type it is declared as and formats it back the way `expr.format_value` writes one — which is also how
  an expression that produced it spelled it.

  **An inherited instance may restate its boundary** (`sketch:` beside the instance, read by
  `InterfaceInherits` and applied in `Interface.instantiate`). The same opening drawn differently: a slotted
  hole *is* a through hole — it inherits one, so it mates as one and keeps its port where the plain hole would
  have been — and what tells them apart is the outline and the freedom of movement. Without it a slotted hole
  is what it used to be in `//pub/std/metric/m`: an orphan with no parents, no compatibility and no mate.

  **`alias:` is what keeps a published name working.** It is spelled as inheriting exactly one interface,
  once, unnamed, at the origin — which is the shape of inheritance that leaves the ports named as the
  target names them and marks the interface a drop-in for it — plus `_adopt_alias_target()` for the handful
  of things an interface states rather than derives. `//pub/std/metric/m` is the reason it exists: eleven
  thousand enumerated names became aliases of nine parametric interfaces, with identical ports.

  Two things had to be fixed for any of it to mean anything, and both change what an *existing* package
  does — visibly, and for the better:

  * **An interface's own freedom of movement now wins over the inherited one.** The inherited declaration
    used to overwrite it, so a child could say nothing about the freedom it was given — which is what a
    slotted hole is entirely made of (it narrows `moveX` to the length of the slot). `//pub/std/metric/m`
    has always declared `moveZ: {max: length - 2}` on every `mN-screw-L`, and it had never taken effect:
    425 of its interfaces gain the movement they were written to have. Fifty of them gain a range that runs
    *backwards*, because `length - 2` is -1 for the 1mm screws its own lists name — `_check_movement_range`
    reports those and reads them as no movement, which is what they silently were before. Do not remove
    that check on the grounds that the package should be fixed instead: a bound may be an expression now,
    so the next package can write one that inverts too.
  * **`compatible_with` closes over the ancestors.** It used to be accumulated while inheriting, but
    inheriting only *creates* the parent — instantiating it is what fills in what it is in turn compatible
    with, and that had not happened yet — so the chain stopped at the first parent and an `m4-thru-3` never
    reached `m4-opening`. It is a lazy property now, and fifty of that package's interfaces reach one level
    further up than they used to. Nothing loses an entry.

  `expr.py` is the `%...%` syntax, generalized from the one `Interface.instantiate` used for inherited
  interface names. It is not Jinja2 and cannot be: `partcad.yaml` is rendered as a Jinja2 template before it
  is parsed, which is one step before the instance being asked for exists. Expressions are resolved only in
  the sections named in `Interface.EXPRESSION_SECTIONS` (`WithPorts` narrows it to `ports` and `implements`),
  because `%` is an ordinary character in a URL and in prose, and only for an object that declares
  parameters at all — a package written before this must not start reporting errors about a percent sign it
  has always had.

  **What an expression may do is a whitelist over the syntax tree, and it is wider than arithmetic.** The
  form it replaced was an unrestricted `eval`, and one published package uses it as one:
  `//pub/std/metric/cqwarehouse` names its screw interface `%size:value[1:value.index('-')]%`, reading
  "M4-0.7" as 4. So `_ALLOWED_NODES` admits indexing and attribute access, and `SAFE_ATTRIBUTES` is what
  makes the second of those safe — emptying `__builtins__` stops nothing on its own, since
  `().__class__.__base__.__subclasses__()` walks from any literal to every class in the interpreter, and the
  defence is that no name on that list leads anywhere. `format` is off it deliberately: `"{0.__class__}"
  .format(x)` traverses attributes by name at run time, which is the whole of what the list prevents. Adding
  a name to it is a decision about what a package may run at *load* time, not a convenience.

- **What a `partcad.yaml` is rendered with** (`./src/partcad/config_template.py`): the file is a Jinja2 template
  rendered to YAML before it is parsed, and this is the context. Beside the package name and the constants a CAD
  file reaches for, it carries **which PartCAD is doing the rendering** — the version whole, its three numbers,
  and `partcad_version_at_least(...)`. That is what lets one package serve two PartCADs: a package wanting a
  feature this release has and the last one did not writes both forms and picks, rather than raising its
  `partcad:` requirement and going dark for everyone who has not updated (`//pub/std/metric/m` is exactly this).

  Two things about it are deliberate. The comparison is **component-wise** — `0.8.9` is older than `0.8.77`, and
  every comparison of the strings says the opposite. And it is a **Python callable, not a Jinja2 macro**, which
  is what it looks like it should be: a macro always renders to text, so a false one comes back as the string
  `"False"`, which is not empty and so is true to `{% if %}`. A package that must also load on a PartCAD
  predating all of this guards with `partcad_version_major is defined and ...`; Jinja2's `and` short-circuits,
  so the call is never made where the name is absent.

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
