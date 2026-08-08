## Context

This document is written for an implementer picking the work up cold. It records what was found, how it was
found, and what has *not* been verified, so the implementer can tell the two apart.

### How a sandbox run reaches the lock

1. A factory calls `await self.runtime.run_async(cmd, stdin, session=...)`. Call sites:
   `part_factory_step.py:44`, `part_factory_brep.py:51`, `part_factory_3mf.py:68`, `part_factory_sdf.py:84`,
   `part_factory_extrude.py:80`, `part_factory_sweep.py:95`, `part_factory_scad.py:246`,
   `part_factory_wrapper.py:135`, `transform.py:47`, `shape.py:617` (SVG), `shape.py:842` (all render formats),
   `actions/assembly/import_assy.py:39`, `test/cam_analysis.py:28`.
2. `run_async()` (`runtime_python.py:506`) calls `once_async()`, then `run_async_onced()`.
3. `run_async_onced()` (`runtime_python.py:510`) enters `async with self.async_lock(session)` at line 524 and
   holds it until it returns at line 618 — spanning `create_subprocess_exec` (561) and `communicate` (571).

### The three primitives, and what each actually guards

| Primitive | Where | Scope | What it really does |
|---|---|---|---|
| `asyncio.Lock` | `get_async_lock()`, `runtime_python.py:247` | per (thread, event loop, runtime) — stored in `self.tls`, keyed by `id(self)` and `id(loop)` | Serializes every sandbox operation issued from the *same* thread/loop. This is what makes `Project.render_async`'s `asyncio.gather` serial. |
| `threading.RLock` | `self.lock`, created at `runtime_python.py:173` | one per `PythonRuntime` instance ⇒ effectively one per process | Serializes every sandbox operation across *all* threads. Acquired blocking, inside a coroutine, held across `await`. |
| `FileLock` (`VenvLock`) | `runtime_python.py:131-149` | one file per (sandbox, venv) | Cross-**process** guard. Constructed with `thread_local=False` (line 146). |

**A claim to verify before relying on it (task 1.4):** with `thread_local=False`, `filelock` keeps its
reentrancy counter shared across threads rather than thread-local, which means a second thread calling
`acquire()` on an already-held lock object increments the counter and returns immediately instead of waiting.
If that reading is right, `VenvLock` provides *no* intra-process mutual exclusion today — all of the
intra-process exclusion comes from the `RLock` — and the new design must not assume otherwise. Confirm against
the pinned `filelock` version before building on it.

### Why the lock is there

`runtime_python.py:511-523` documents the hazard, and it is genuine:

> Two parts of the same package (e.g. a CadQuery part and a build123d part) share a session v-env; if the
> install loop is left outside this lock, a build123d install — which pulls `cadquery-ocp-novtk` and overwrites
> the shared OCP native module — can slip in between another part's `CADQUERY_OCP` re-assertion and the moment
> that part actually runs `import cadquery` […]

Supporting machinery for the same hazard: `sandbox_versions.GUARD_INVALIDATED_BY`,
`invalidate_dependent_guards()` (`runtime_python.py:83`), `needs_reassert()`/`clear_reassert()`, and the
`FORCE_REINSTALL_FLAGS` comment at `runtime_python.py:62-68`. Read all of it before changing the locking; the
guard/reassert bookkeeping is what makes the VTK-enabled build win *eventually*, and the lock is what makes it
win *at the instant a run starts*.

### What is not the problem

- It is not `FileLock` contention: that is cross-process and the bottleneck reproduces in a single process.
- It is not the thread pool sizing: the pool is correctly sized (`sync_threads.py:44-70`), it is simply blocked.
- It is not `Shape.get_wrapped`'s own lock (`shape.py:209`), though that method has the same
  blocking-lock-across-`await` shape and is worth fixing in passing (task 5.3). Its scope is one shape, so it
  does not serialize unrelated work.

## Goals / Non-Goals

**Goals**

- Independent sandbox operations run concurrently, bounded by an explicit cap.
- Mutual exclusion is scoped to the environment being mutated (a sandbox path or a v-env path), not to the
  runtime object.
- No sandbox operation blocks an event loop while waiting for a lock.
- The install/run race that motivated the current lock remains impossible, and a test proves it.

**Non-Goals**

- Fewer or cheaper sandbox invocations (sibling proposal: `sandbox-process-reuse`).
- Cross-process concurrency policy. The `FileLock` layer stays as the cross-process guard for installs.
- Any change to what a wrapper receives or returns.

## Decisions

### D1 — Readers/writer, keyed by environment path

Model the environment (`self.path` for the sandbox, `session["path"]` for a v-env) as a resource with:

- **Writers** — anything that mutates it: `ensure*` when the install guard is absent, and v-env creation
  (`python -m venv`). Exclusive against every other holder of the same key.
- **Readers** — a run that only executes an interpreter in an environment already known good. Shared.

A run against a v-env implicitly depends on the parent sandbox as well, so a run must hold a read on *both* the
sandbox key and (if a session is in play) the v-env key. Acquire in a fixed order — sandbox first, then v-env —
so no cycle is possible. Note `runtime_python_conda.py` overrides `sync_lock_install`/`async_lock_install` with
a conda-global lock; keep it outermost so the ordering stays total.

### D2 — Never block an event loop

`asyncio.Lock` cannot be used for cross-thread coordination (it is bound to one loop, which is exactly why the
current code needs the `RLock` alongside it). Two viable approaches:

- **D2a (recommended, smallest diff):** keep `threading`-level primitives for cross-thread coordination, but
  acquire them off-loop — `await asyncio.to_thread(gate.acquire_read, key)` — so waiting parks the coroutine
  instead of freezing the thread. Release is non-blocking and can stay inline.
- **D2b:** route every sandbox run through one dedicated owner loop and use `asyncio` primitives throughout.
  Cleaner in the long run, much larger blast radius.

Take D2a unless something during implementation makes it untenable; record the reason if you switch.

### D3 — An explicit concurrency cap

Removing the lock uncovers unbounded fan-out: `Project.render_async` can gather hundreds of coroutines. Add a
process-wide semaphore around sandbox *execution* sized from `user_config.threads_max` (fall back to
`ThreadPoolManager`'s `constrained` count, `sync_threads.py:60`). Each sandbox process is CPU-heavy and can be
memory-heavy, so this cap is a correctness-of-resource-use concern, not a nicety.

### D4 — Keep the guard/reassert bookkeeping untouched

`invalidate_dependent_guards()`, `needs_reassert()` and `FORCE_REINSTALL_FLAGS` are orthogonal to *when* things
may run concurrently. Do not restructure them in this change; a diff that touches both is very hard to review.

## Risks

| Risk | Mitigation |
|---|---|
| Reintroducing the OCP-clobbering race, which manifests as a native crash with **no traceback and no stderr** | Task 4 is a dedicated regression test. Note the existing diagnostic at `runtime_python.py:601-616` — a non-zero exit with no output is the signature; make the test assert on it. |
| A deadlock from mixed lock ordering with `runtime_python_conda.py`'s global conda lock | D1's fixed acquisition order; task 3.5 audits every acquisition site. |
| Memory exhaustion once many OCP interpreters run at once | D3's semaphore, plus task 6.4 records peak RSS in the benchmark. |
| Flaky tests that only fail under load | Task 4.3 runs the regression test repeatedly (≥20 iterations) under `-n` parallelism. |

## How to measure

There is no benchmark in the repo today; build one first (task 2) so the "before" number is real rather than
inferred. A self-contained recipe that needs no telemetry backend:

```python
# dev-tools/perf/measure_sandbox_concurrency.py  (throwaway, do not ship)
import asyncio, time
import partcad as pc
from partcad.runtime_python import PythonRuntime

spans = []
orig = PythonRuntime.run_async_onced

async def traced(self, *a, **kw):
    t0 = time.monotonic()
    try:
        return await orig(self, *a, **kw)
    finally:
        spans.append((t0, time.monotonic()))

PythonRuntime.run_async_onced = traced

t0 = time.monotonic()
ctx = pc.init("examples")            # or a package with several parts
ctx.render(project_path="//examples/produce_part_step", format="stl")
wall = time.monotonic() - t0

busy = sum(e - s for s, e in spans)
# Max overlap: how many sandbox processes were ever in flight at once.
events = sorted([(s, 1) for s, _ in spans] + [(e, -1) for _, e in spans])
cur = peak = 0
for _, d in events:
    cur += d
    peak = max(peak, cur)
print(f"wall={wall:.1f}s  sandbox_busy={busy:.1f}s  runs={len(spans)}  peak_overlap={peak}")
```

**Today's expected reading:** `peak_overlap == 1` and `busy ≈ wall`. That is the signature of full
serialization and is the "before" number to record in the PR.

**Acceptance:** with the change, `peak_overlap` reaches `min(len(spans), cap)`, and on a multi-core machine
wall-clock for N independent parts drops toward `busy / peak_overlap` plus overhead. State the machine's core
count alongside the numbers — the result is meaningless without it.

Use the packages under `examples/` for the workload (`produce_part_step`, `produce_part_cadquery_primitive`,
`produce_part_build123d_primitive`, `produce_assembly_assy`). A mixed-flavour package is the interesting case
for both performance and the race.

## Open questions for the implementer

1. Should the concurrency cap be shared with, or independent of, `ThreadPoolManager`'s constrained pool? A part
   instantiation occupies a pool thread *and* a sandbox slot; if the two counts are equal, the pool thread is
   simply the thing that waits. Independent counts may be better once renders (which do not use the pool) are
   also concurrent.
2. Should a run against a v-env whose install guards are all present skip the sandbox-level read entirely? It
   would reduce contention but weakens the "sandbox is not being mutated under me" guarantee.
3. Is per-**package** install serialization worth keeping as a simplification, given every part of a package
   shares one session v-env (`get_session()`, `runtime_python.py:918`)? It would make writers coarse but
   simple, and installs are already the rare path once guards exist.
