## Why

PartCAD does its geometry work in sandboxed Python subprocesses, and it starts a **brand new interpreter for
every individual operation**. Each one imports the CAD stack (OCP, and usually build123d and/or CadQuery) from
cold before it does any work. For anything but a very large model, that import dominates the wall clock.

There is more than one such operation per shape. Counting the invocation sites:

- **Instantiation** — one subprocess per part: `part_factory_step.py:44`, `part_factory_brep.py:51`,
  `part_factory_3mf.py:68`, `part_factory_sdf.py:84`, `part_factory_extrude.py:80`,
  `part_factory_sweep.py:95`, `part_factory_scad.py:246`, `part_factory_wrapper.py:135`.
- **Transforms** — `offset`, `scale` and `compound` each spawn their own subprocess through `transform._run()`
  (`transform.py:33-55`). `Shape.get_wrapped()` calls `offset` and `scale` as two separate invocations
  (`shape.py:252` and `shape.py:254`), *after* instantiation has already finished in a third.
  `PartFactoryWrapper.instantiate()` adds a `compound` call (`part_factory_wrapper.py:174`).
- **Rendering** — one subprocess **per format**. `Shape.render_async()` loops over formats
  (`shape.py:765`) and inside the loop re-serializes the same payload (`shape.py:828`) and spawns a fresh
  interpreter (`shape.py:842`). `render_svg_somewhere()` (`shape.py:617`) is another.

So one file-backed part carrying `offset` and `scale`, rendered to svg + step + stl + 3mf, costs **seven**
interpreter starts — seven cold imports of OCP, seven trips through the `ensure_async` chain, and seven
serializations of the same BREP payload. The render loop is the most obviously wasteful of these: the wrapper
decodes the shape, exports one format, exits, and the next invocation decodes the identical bytes again.

Each invocation also re-walks the dependency-assurance chain. `part_factory_3mf.py:54-60` issues five
`ensure_async` calls before its single run; every one of them re-enters `once_async()`
(`runtime_python.py:331`), which re-takes the runtime locks and stats guard files. The same five-call preamble
appears in `part_factory_scad.py:232-238`, `part_factory_wrapper.py:114-120` and `shape.py:836-837`.

This is the largest remaining cost after sandbox runs are allowed to overlap at all (see the sibling proposal
`sandbox-run-concurrency`, which is a prerequisite for the benefit here being visible on a multi-core machine).

## What Changes

Three steps, deliberately ordered so each is independently shippable and independently measurable:

1. **Batch the render formats.** One wrapper invocation per shape that exports every requested format, instead
   of one per format. The wrapper already holds the decoded shape; today that decode is discarded and redone.
2. **Fold the transforms into the producing invocation.** Carry `offset`/`scale` in the request that produces
   the shape rather than spawning two further processes to post-process it, keeping `transform.py` as the
   fallback for shapes that arrive from the cache or from a factory that cannot apply them inline.
3. **Reuse warm interpreters.** A persistent wrapper host per (runtime, v-env): a process that imports the CAD
   stack once and then serves length-prefixed requests over its stdin/stdout for as long as it is useful.
   `partcad-service-json-rpc` already owns the runtimes for the daemon's lifetime, so warm hosts kept there
   survive across `pc` commands, not merely within one.

Steps 1 and 2 are contained and low-risk. Step 3 is the large one and should not start until 1 and 2 have
landed and been measured.

Not a user-visible behavior change: the same shapes and the same exported files, from the same inputs.

## Capabilities

### New Capabilities

- `sandbox-process-reuse`: The requirement that the cost of starting a sandbox interpreter and importing the CAD
  stack is amortized rather than paid per operation — that a shape's exports share one invocation, that
  transformations do not each require their own, and that interpreters may be kept warm and reused across
  operations without weakening the isolation the sandbox provides.

## Impact

- **Modified**: `partcad/src/partcad/shape.py` — `render_async()`'s per-format loop, and the `offset`/`scale`
  application in `get_wrapped()`.
- **Modified**: `partcad/src/partcad/wrappers/wrapper_render_*.py` — accept a list of output formats in one
  request. Check `dev-tools/pyinstaller/README.md` before adding or renaming any wrapper file: the frozen
  bundle collects them explicitly and a new file can be invisible to it while the wheels stay fine.
- **Modified**: `partcad/src/partcad/transform.py` — remains the fallback path; gains no new responsibilities.
- **Modified (step 3)**: `partcad/src/partcad/runtime_python.py`, plus a new wrapper-host module and its
  counterpart in `partcad-service-json-rpc`.
- **New specs**: `openspec/specs/sandbox-process-reuse/spec.md`.
- **Unchanged**: the envelope format itself (`shape_envelope.py` / `wrappers/ocp_serialize.py`) — the request
  and response bodies grow fields, but the encoding is untouched.

## Non-Goals

- Allowing sandbox operations to overlap. That is the sibling proposal `sandbox-run-concurrency`; this change
  reduces the amount of work, that one lets the work spread across cores. They are complementary and neither
  subsumes the other.
- Reducing the cost of a cache hit; see the sibling proposal `shape-cache-efficiency`.
- Weakening sandbox isolation, or letting the core process import OCP. The core carries opaque BREP envelopes
  and must keep doing so (`shape_envelope.py` header).
- Changing which packages get installed into a sandbox, or their pinned versions
  (`sandbox_versions.PINNED_REQUIREMENTS`).
