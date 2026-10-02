## 1. Confirm the finding and establish the baseline

- [ ] 1.1 Bring up the dev container (root `AGENTS.md`, "Where commands run") — everything below runs inside it
- [ ] 1.2 Instrument `PythonRuntime.run_async_onced` to count and time invocations (recipe in `design.md`,
      "How to measure"); confirm a part with `offset` + `scale` rendered to four formats costs seven runs
- [ ] 1.3 Measure the fixed per-run cost: `python -X importtime -c "import build123d, cadquery"` inside a
      provisioned sandbox. Record the number and the machine
- [ ] 1.4 Record the baseline (`runs`, `sandbox_busy`, `wall`) for two workloads: a single multi-format part,
      and a whole package (`pc --no-ansi render`)
- [ ] 1.5 Confirm the latent bug at `shape.py:832` — `WRAPPER_FORMATS[format_name]` inside a loop over `format`
      — by calling `render_async` with `format_name=None` and observing `KeyError: None`. Note it in the PR;
      step 2 removes the loop rather than patching it
- [ ] 1.6 Paste the baselines into the PR description before writing implementation code

## 2. Step 1 — batch the render formats

- [ ] 2.1 Read `Shape.render_async()` (`shape.py:702-875`) in full, including `render_getopts()`
      (`shape.py:642`), so per-format path and option resolution is understood before it moves
- [ ] 2.2 Restructure `render_async` to resolve every requested format up front into
      `(format, final_filepath, request_options)` and issue a single invocation
- [ ] 2.3 Compute the union of `WRAPPER_FORMATS` dependency lists, then **re-impose** the ordering invariant so
      `CADQUERY_OCP` is asserted last (`shape.py:714-747` and the note at `shape.py:833-835`)
- [ ] 2.4 Add `wrapper_render.py` dispatching to the existing `wrapper_render_<format>.py` exporters; do not
      rewrite the exporters themselves
- [ ] 2.5 Define the multi-format response: per-format `success` / `exception`, so one failing exporter does not
      abort the others. Keep the single-format response shape backward compatible
- [ ] 2.6 Update the callers: `Project.render_async()` (`project.py:1179-1220`) currently creates one coroutine
      per shape *per format* — it should now create one per shape
- [ ] 2.7 Leave `render_svg_somewhere()` (`shape.py:565-640`) alone in this step; fold it in only if it falls
      out cleanly
- [ ] 2.8 Read `dev-tools/pyinstaller/README.md` and make whatever entry it requires for the new wrapper file
- [ ] 2.9 Re-measure: run count for the four-format part should drop from 7 to 4

## 3. Step 2 — fold transforms into the producing invocation

- [ ] 3.1 Read `Shape.get_wrapped()` (`shape.py:208-270`) and `transform.py` in full
- [ ] 3.2 Add an optional `transform` field to the instantiation request, applied inside the wrapper before it
      serializes its result
- [ ] 3.3 Add a per-factory capability flag so factories convert one at a time; unconverted factories keep using
      `transform.py`
- [ ] 3.4 Keep `transform.py` as the fallback for shapes served from the cache, where there is no producing
      invocation to fold into
- [ ] 3.5 **Verify the cache key is unaffected.** `Shape.__init__` folds `offset`/`scale` into the hash
      (`shape.py:144-149`). Add a test that a part with a transform and the same part without one produce
      different cache entries, and that changing the transform value invalidates the entry
- [ ] 3.6 Convert `PartFactoryWrapper`'s `compound` call (`part_factory_wrapper.py:162-177`) so a multi-shape
      wrapper result is compounded in the invocation that produced it
- [ ] 3.7 Re-measure: run count for the four-format part should drop from 4 to 2

## 4. Step 3 — warm wrapper hosts (do not start before 2 and 3 have landed)

- [ ] 4.1 Design the framing (`design.md` D3): length-prefixed frames, body encoding unchanged
- [ ] 4.2 Add the host process and a client that speaks to it, keeping one-shot invocation working unchanged as
      the fallback
- [ ] 4.3 Audit every wrapper for module-level mutable state and reset it per request. Known instances:
      `wrapper_common._request_name` / `_request_label` (`wrapper_common.py:22-23`),
      `ocp_serialize._zstd_warned` and `downcast_LUT`, and the process-global `os.chdir()` at
      `wrapper_common.py:43`
- [ ] 4.4 Implement host invalidation: retire a host on any install into its sandbox or v-env, especially one
      that trips `invalidate_dependent_guards()` (`runtime_python.py:83`)
- [ ] 4.5 Implement crash handling: detect host death, restart, retry the in-flight request **once**, and
      surface a second failure as a real error
- [ ] 4.6 Wire host ownership into `partcad-service-json-rpc` so hosts survive across `pc` commands; confirm a
      non-daemon `pc` run still works with hosts scoped to its own lifetime
- [ ] 4.7 Coordinate with `sandbox-run-concurrency` if it has landed: a warm host is a long-lived *reader* of
      its environment and must participate in that gate

## 5. Correctness

- [ ] 5.1 Golden-output test: for each supported format, the file produced by the batched path is byte-identical
      to the one produced today (or geometrically equivalent where an exporter embeds a timestamp)
- [ ] 5.2 A render where one format fails and the others succeed still writes the successful outputs and reports
      the failure
- [ ] 5.3 A shape with `offset` and `scale` produces identical geometry through the folded path and the
      `transform.py` fallback
- [ ] 5.4 State-bleed test for step 3: a request run alone and the same request run after several others on the
      same warm host produce identical output
- [ ] 5.5 Confirm the core still never imports OCP: `import partcad` followed by a full render must leave `OCP`
      absent from `sys.modules` in the core process

## 6. Validate

- [ ] 6.1 `poetry run pytest partcad partcad-cli -x -p no:error-for-skips -p no:warnings --dist no`
- [ ] 6.2 `poetry run behave` — `features/render.feature` and `features/export.feature` are the relevant ones
- [ ] 6.3 Re-run the measurement harness and record run count and wall clock **per step**, next to the baseline
- [ ] 6.4 Record peak RSS: warm hosts hold the CAD stack resident between requests, which is the trade being made
- [ ] 6.5 Build and smoke-test the PyInstaller bundle (`dev-tools/pyinstaller/README.md`). A missing wrapper file
      breaks the frozen bundle while the wheels stay green — this is the failure mode that will not show up in CI
      unless it is tested for

## 7. Land it

- [ ] 7.1 Remove or promote the measurement harness — do not leave it half-committed
- [ ] 7.2 Move the delta spec into `openspec/specs/sandbox-process-reuse/spec.md`
- [ ] 7.3 Run `pre-commit run --config dev-tools/pre-commit-config.yaml` inside the container and re-stage
      anything the formatting hooks rewrote
- [ ] 7.4 Commit inside the container; verify with `git log -1 --stat`
