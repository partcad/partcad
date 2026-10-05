## Context

This document is written for an implementer picking the work up cold. It records what was found, how the pieces
fit together, and which claims are estimates rather than measurements.

### The invocation protocol as it exists today

Every wrapper is a standalone script run as `python -sOOIu wrapper_<x>.py <path> [<cwd>]`, whose stdin carries
one serialized request and whose stdout carries one serialized response. `wrapper_common.handle_input()`
(`partcad/src/partcad/wrappers/wrapper_common.py:26`) reads stdin **to EOF** and deserializes the whole thing;
`handle_output()` writes the response and flushes. `deserialize()` takes the *last non-empty line* of the
output (`shape_envelope.py`, `deserialize`), which is how stray wrapper stdout is tolerated.

Two properties of that protocol matter here:

- It is one-shot and EOF-terminated. Reuse requires framing, because a warm host cannot read to EOF.
- The core never holds a live OCP object. `shape_envelope.py` (core side) keeps shapes as opaque
  `{"name", "label", "brep"}` dicts; only `wrappers/ocp_serialize.py` (sandbox side) turns them back into
  geometry. That invariant is the point of the split and must survive any change here.

### Where the invocations come from

| Operation | Site | Notes |
|---|---|---|
| Instantiate a part | `part_factory_{step,brep,3mf,sdf,extrude,sweep,scad,wrapper}.py` | One per part |
| `offset` | `shape.py:252` via `transform.py:33` | Separate process, *after* instantiation |
| `scale` | `shape.py:254` via `transform.py:33` | Another separate process |
| `compound` | `part_factory_wrapper.py:174` via `transform.py:33` | Another |
| Render, per format | `shape.py:842`, inside the loop at `shape.py:765` | One process **per format** |
| Render SVG (thumbnail path) | `shape.py:617` | Yet another |

`Shape.render_async()` is worth reading closely (`shape.py:702-875`): `obj = await self.get_wrapped(ctx)` is
fetched **once** at line 757, and then the loop re-serializes that same `obj` at line 828 and ships it to a new
interpreter at line 842 for each format. Note also the latent bug at line 832 — `dependencies =
WRAPPER_FORMATS[format_name]` uses the *outer* `format_name`, not the loop's `format`, so the multi-format path
(`format_name=None`) would raise `KeyError: None`. In practice only the single-format path is exercised. Batching
removes this footgun rather than fixing it in place; say so in the PR so it is not mistaken for an unrelated
drive-by.

### The per-invocation preamble

Each invocation re-walks the dependency-assurance chain — five `ensure_async` calls in
`part_factory_3mf.py:54-60`, `part_factory_scad.py:232-238` and `part_factory_wrapper.py:114-120`, and the
per-format list in `shape.py:836-837`. Each of those re-enters `once_async()` (`runtime_python.py:331`), which
re-takes the runtime locks and stats guard files. Individually cheap (a few stats and a lock cycle); the point
is that it is paid once per operation, and the whole thrust of this change is to have fewer operations.

The installs are correctly *ordered* rather than gathered, and the comments explaining why
(`shape.py:833-835`, `runtime_python.py:36-68`) are load-bearing: build123d pulls `cadquery-ocp-novtk`, which
overwrites the OCP native module `cadquery-ocp` installs, so `CADQUERY_OCP` must be re-asserted last. Do not
"optimize" that into an `asyncio.gather`.

## Goals / Non-Goals

**Goals**

- One sandbox invocation per shape for all of its exports.
- No dedicated invocation for a transform that the producing invocation could have applied itself.
- A supported way to keep an interpreter warm and serve many requests from it, with the daemon as its owner.
- Every step independently measurable, and independently revertable.

**Non-Goals**

- Overlapping sandbox operations (sibling proposal: `sandbox-run-concurrency`).
- Cheaper cache hits (sibling proposal: `shape-cache-efficiency`).
- Any relaxation of the "core never imports OCP" rule.
- Changing pinned CAD-stack versions.

## Decisions

### D1 — Step 1: batch the formats (do this first)

Change `Shape.render_async()` to collect `(format, filepath, options)` for every requested format, install the
union of the formats' dependency lists **in a dependency-safe order**, and issue one invocation carrying the
list. A new `wrapper_render.py` dispatches to the existing per-format exporters, which stay where they are.

Two details that will bite:

- **Dependency ordering across a union.** `WRAPPER_FORMATS` (`shape.py:714-747`) is per-format and each list is
  already ordered so `CADQUERY_OCP` lands last. Unioning them naively can break that. Compute the union, then
  re-impose the invariant explicitly rather than relying on iteration order.
- **Partial failure.** Today one format failing leaves the others unaffected because they are separate
  processes. After batching, the response must report per-format success/failure, and a failure in one exporter
  must not abort the rest. Mirror the existing error surface: `result["success"]` plus `result["exception"]`,
  now per format.

Expected win: for a shape rendered to N formats, N cold CAD-stack imports and N BREP decodes collapse to one.

### D2 — Step 2: fold transforms into the producing invocation

`Shape.get_wrapped()` applies `offset`/`scale` at `shape.py:248-254` by round-tripping the shape through
`transform.offset` and then `transform.scale` — two extra processes, each of which decodes and re-encodes the
whole payload.

Add an optional `transform` field to the instantiation request that a wrapper applies before it serializes its
result. Keep `transform.py` intact as the fallback for the cases where there is no producing invocation to fold
into: a shape served from the cache, and any factory not yet updated. Guard the fold behind a per-factory
capability flag so factories can be converted one at a time instead of in one large diff.

**Cache-key warning.** `Shape.__init__` already folds `offset` and `scale` into the cache hash
(`shape.py:144-149`), so a shape's cached entry is keyed on its transform. Applying the transform earlier does
not change the key — but verify it, because getting this wrong silently serves untransformed geometry.

### D3 — Step 3: warm wrapper hosts

A host process per (runtime, v-env) that imports the CAD stack once, then loops: read one framed request,
dispatch it to the same wrapper entry points used today, write one framed response.

- **Framing.** The current protocol is EOF-terminated and cannot be reused as-is. Use length-prefixed frames.
  Keep the *body* encoding exactly as it is (`shape_envelope` / `ocp_serialize`) so only the transport changes.
- **Ownership and lifetime.** The daemon (`partcad-service-json-rpc`) already owns the runtimes and the warm
  PartCAD context (root `CLAUDE.md`), so hosts kept there survive across `pc` commands. A non-daemon `pc` run
  must keep working, with hosts scoped to that process's lifetime — do not make the daemon a hard requirement.
- **Invalidation.** A host must be retired when the environment beneath it changes: any install into its
  sandbox or v-env, in particular one that trips `invalidate_dependent_guards()` (`runtime_python.py:83`).
  A host holding an OCP module that has since been overwritten on disk is exactly the failure the guard
  bookkeeping exists to prevent. This interacts directly with the sibling `sandbox-run-concurrency` proposal's
  readers/writer gate — a host is a long-lived *reader*.
- **Crash isolation.** A wrapper that segfaults today kills one operation. In a warm host it kills every
  queued request on that host. Detect the death, restart the host, and retry the in-flight request **once**;
  a second failure is a genuine error and must surface as one.
- **State bleed.** Wrappers today get a fresh interpreter each time and may rely on it. `wrapper_common`
  keeps module-level `_request_name`/`_request_label` (`wrapper_common.py:22-23`); `ocp_serialize` keeps
  `_zstd_warned` and the lazily-built `downcast_LUT`. Audit every wrapper for module-level mutable state and
  reset per request. `os.chdir()` in `handle_input()` (`wrapper_common.py:43`) is process-global and a
  particularly sharp edge.

## Risks

| Risk | Mitigation |
|---|---|
| Batching changes error semantics: one bad format takes down the others | D1's per-format result reporting; a test that renders a good and a deliberately failing format together |
| The frozen PyInstaller bundle misses a new wrapper file | Read `dev-tools/pyinstaller/README.md` first; task 6.5 tests the built bundle, not just the wheels |
| A warm host serves a request against a clobbered OCP | D3's invalidation rule, tied to the install guards |
| Cross-request state bleed produces wrong geometry rather than an error | D3's audit; task 5.4 asserts identical output for a request run alone vs. run after others on the same host |
| Step 3 balloons and blocks steps 1-2 from shipping | Ship 1 and 2 first, each with its own measurement |

## How to measure

Same harness as the sibling proposal — monkeypatch `PythonRuntime.run_async_onced` to record spans — but the
headline number here is the **count**, not the overlap:

```python
print(f"wall={wall:.1f}s  sandbox_busy={busy:.1f}s  runs={len(spans)}")
```

Also measure the fixed cost each of those runs pays, inside a provisioned sandbox:

```bash
# path from ctx.get_python_runtime("3.11").path
<sandbox>/bin/python -X importtime -c "import build123d, cadquery" 2>&1 | tail -1
```

Multiply the two. That product is the budget this change is going after.

**Expected today** for one part with `offset` + `scale`, rendered to svg + step + stl + 3mf: `runs == 7`.
**After step 1:** 4. **After step 2:** 2. **After step 3:** the CAD-stack import is paid once per host, not per
run.

Report the run count and wall clock at each step separately. A single before/after number spanning all three
steps hides which one actually paid off.

## Open questions for the implementer

1. Should batching extend across *shapes* as well as formats — one invocation exporting many parts? It would
   amortize further, but it couples unrelated shapes' failures and complicates progress reporting. Probably a
   later step; note the decision either way.
2. How long should a warm host live when idle, and how many should exist per v-env? One is simplest; a small
   pool interacts better with `sandbox-run-concurrency`'s cap.
3. Should `wrapper_common.handle_input()` grow the framed mode, or should a new host module wrap the existing
   entry points without touching them? The latter keeps one-shot invocation working unchanged and is likely the
   safer path.
4. Does the daemon's existing lifecycle (`pc daemon start`/`stop`) need new surface to report or reset warm
   hosts, e.g. for `pc status`?
