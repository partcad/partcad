## 1. Confirm the finding before changing anything

- [ ] 1.1 Read `partcad/src/partcad/runtime_python.py` lines 131-160 (`VenvLock`), 160-200 (`__init__`),
      247-283 (the lock helpers) and 506-618 (`run_async_onced`) end to end
- [ ] 1.2 Confirm `Context.get_python_runtime()` (`context.py:1028-1043`) returns a single memoized instance for
      the version every call site asks for, by logging the `id()` of the runtime at each `run_async` call site
      during an `examples/` render
- [ ] 1.3 Confirm `self.lock` (`runtime_python.py:173`) is held across `await p.communicate()`
      (`runtime_python.py:571`) — e.g. by logging acquire/release with thread ids
- [ ] 1.4 Settle the `VenvLock` question from `design.md`: does `FileLock(..., thread_local=False)`
      (`runtime_python.py:146`) provide intra-process mutual exclusion, or only cross-process? Check the pinned
      `filelock` version's source; write the answer into `design.md` before designing around it
- [ ] 1.5 Confirm the same serialization applies to the synchronous path (`sync_lock()`,
      `runtime_python.py:257`, used by `run_onced()` at line 364), so the fix covers both

## 2. Establish the baseline

- [ ] 2.1 Bring up the dev container (root `AGENTS.md`, "Where commands run") — all of the below runs inside it
- [ ] 2.2 Write the throwaway measurement script from `design.md` ("How to measure") under `dev-tools/perf/`
- [ ] 2.3 Pick a workload with several independent parts. Suggested: a scratch package importing
      `examples/produce_part_step`, `examples/produce_part_cadquery_primitive` and
      `examples/produce_part_build123d_primitive`; the mixed CadQuery/build123d flavour is also the race case
- [ ] 2.4 Record, on a warm cache-free run: wall clock, sandbox busy time, run count, peak overlap, core count,
      peak RSS. Expect `peak_overlap == 1`
- [ ] 2.5 Record the same numbers for `pc --no-ansi render` over a package with several shapes and formats, to
      capture the `Project.render_async` gather path (`project.py:1220`) specifically
- [ ] 2.6 Paste both baselines into the PR description before writing any implementation code

## 3. Implement the readers/writer gate

- [ ] 3.1 Add the gate: a keyed readers/writer lock over environment paths, with non-blocking-for-the-loop
      acquisition (`design.md` D1, D2a). Put it in a new module rather than growing `runtime_python.py`
- [ ] 3.2 Unit-test the gate in isolation first: readers share, a writer excludes, ordering is FIFO enough not
      to starve writers, and acquisition never blocks a running event loop
- [ ] 3.3 Convert `async_lock()`/`sync_lock()` (`runtime_python.py:257-272`) to take a *read* on the sandbox key
      and, when a session is given, on the v-env key — in that order
- [ ] 3.4 Convert the `ensure*` family and v-env creation to take a *write* on the key they mutate. Note there
      are four near-duplicate `ensure` variants (`ensure_onced` 678, `ensure_onced_locked` 719,
      `ensure_async_onced` 761, `ensure_async_onced_locked` 803) — treat their duplication as pre-existing and
      do not refactor it here
- [ ] 3.5 Audit every lock acquisition site for ordering against `runtime_python_conda.py`'s
      `sync_lock_install`/`async_lock_install` global conda lock; keep the conda lock outermost
- [ ] 3.6 Remove `self.lock` (the `threading.RLock`) once nothing acquires it, or document precisely what it
      still guards if something does
- [ ] 3.7 Confirm no blocking lock acquisition remains inside a coroutine anywhere in `runtime_python.py`

## 4. Prove the install/run race did not come back

- [ ] 4.1 Read `runtime_python.py:36-68` and `sandbox_versions.GUARD_INVALIDATED_BY` so the hazard is
      understood before testing for it
- [ ] 4.2 Add a regression test next to `partcad/tests/unit/test_runtime_python.py`: a package with both a
      CadQuery-flavoured and a build123d-flavoured part, built concurrently from a cold sandbox, asserting both
      shapes come out valid
- [ ] 4.3 Run it ≥20 times (and under `pytest -n 4`) to shake out a load-dependent failure; a race that
      reproduces one time in ten will otherwise land green
- [ ] 4.4 Assert specifically on the crash signature the existing code already diagnoses: non-zero exit with
      empty stdout *and* empty stderr (`runtime_python.py:601-616`). That is what an OCP collision looks like
- [ ] 4.5 Mark the test `slow` if it provisions sandboxes, so the pre-commit hook's `-m "not slow"` still runs
      fast, and confirm CI (which does not exclude `slow`) still picks it up

## 5. Concurrency cap and adjacent cleanups

- [ ] 5.1 Add the process-wide sandbox-execution semaphore (`design.md` D3), sized from
      `user_config.threads_max` with `ThreadPoolManager`'s `constrained` count as the fallback
- [ ] 5.2 Verify the cap is honoured by re-running the measurement script and checking
      `peak_overlap <= cap`
- [ ] 5.3 Optional, same failure mode, different object: `Shape.get_wrapped()` (`shape.py:208-210`) also holds a
      blocking `threading.RLock` across `await`s, including across a whole sandbox run. Its scope is one shape
      so it does not serialize unrelated work, but it does stall the loop. Fix it here or file it separately —
      do not leave it unmentioned

## 6. Validate

- [ ] 6.1 `poetry run pytest partcad partcad-cli -x -p no:error-for-skips -p no:warnings --dist no`
- [ ] 6.2 `poetry run behave` (integration tests under `./features`; `render.feature` and `test.feature` are the
      relevant ones)
- [ ] 6.3 Re-run the measurement script and record the "after" numbers next to the baseline from task 2.6
- [ ] 6.4 Record peak RSS before and after — concurrency multiplies OCP-sized processes and this is the most
      likely unpleasant surprise
- [ ] 6.5 Confirm rendered artifacts are byte-identical (or geometrically equivalent, where an exporter embeds a
      timestamp) to the ones produced before the change
- [ ] 6.6 Sanity-check a single-core / `threadsMax: 1` configuration still works and does not regress

## 7. Land it

- [ ] 7.1 Delete the throwaway measurement script, or promote it to a maintained benchmark under `dev-tools/`
      with a short README — do not leave it half-committed
- [ ] 7.2 Move the delta spec into `openspec/specs/sandbox-concurrency/spec.md`
- [ ] 7.3 Run `pre-commit run --config dev-tools/pre-commit-config.yaml` inside the container and re-stage
      anything the formatting hooks rewrote
- [ ] 7.4 Commit inside the container; verify with `git log -1 --stat` that the hooks ran and the file set is
      what you intended
