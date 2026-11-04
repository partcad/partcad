## Why

Every piece of CAD work PartCAD does happens in a sandboxed Python subprocess, and today **no two of those
subprocesses ever run at the same time**, on any machine, no matter how many cores it has.

`PythonRuntime.async_lock()` (`partcad/src/partcad/runtime_python.py:265`) acquires two mutual-exclusion
primitives before yielding:

```python
async def async_lock(self, session=None):
    async with self.get_async_lock():        # asyncio.Lock, per (thread, loop, runtime)
        with self.lock:                      # threading.RLock, ONE per runtime instance
            venv = session["hash"] if session is not None else None
            with VenvLock(self, venv):
                yield
```

`run_async_onced()` (`runtime_python.py:510`) wraps that context manager around the *entire* subprocess
lifetime — provisioning, `asyncio.create_subprocess_exec` (line 561), `await p.communicate()` (line 571), and
the output handling that follows — returning only at line 618.

There is effectively **one** `PythonRuntime` instance per process. `Context.get_python_runtime()`
(`context.py:1028`) memoizes by `python_runtime + "-" + version`, and virtually every call site asks for
`"3.11"` / `sandbox_versions.DEFAULT_PYTHON_VERSION`. One instance means one `self.lock`, and that single
`threading.RLock` gates every sandbox execution in the process.

Two distinct consequences follow, and both are load-bearing:

1. **The thread pool is inert.** `ThreadPoolManager` sizes a pool at `cpu_count - 1` (`sync_threads.py:44`) and
   `Part.get_shape()` dispatches each part's instantiation onto it (`part.py:34`). Every one of those threads
   then blocks on the same `RLock` while some other thread's subprocess runs. Worse: a *blocking* lock acquired
   inside a coroutine stalls the whole OS thread, and therefore that thread's entire event loop — so pending
   `aiofiles` cache I/O and any other async work scheduled there stalls too. The slowdown is not confined to
   sandbox runs.

2. **Gathered renders are serial.** `Project.render_async()` (`project.py:1179`) builds a coroutine for every
   shape × format combination and `asyncio.gather`s them on one loop (`project.py:1220`). They all share that
   thread's single `asyncio.Lock` from `get_async_lock()`, so `gather` executes them strictly one at a time.

The lock is not gratuitous. The comment at `runtime_python.py:511-523` documents a real hazard: installing
`build123d` pulls `cadquery-ocp-novtk`, which overwrites the very same OCP native module `cadquery-ocp`
installs, so an install slipping in between another part's `CADQUERY_OCP` re-assertion and its actual run
leaves that run importing a half-installed OCP and dying with an unrelated-looking `ImportError`. That hazard
is real and must survive this change. But the mutual exclusion it motivates is *(venv, install-vs-run)*, while
what is implemented is *(runtime, any run)* — and sessionless runs, which install nothing at that point, are
serialized along with everything else.

## What Changes

- Replace the blanket runtime-wide lock around sandbox execution with a **readers/writer gate keyed on the
  environment being mutated**: package installs and v-env creation take the gate exclusively; interpreter runs
  that install nothing share it.
- Stop acquiring a blocking `threading` primitive inside a coroutine, so a waiting sandbox operation no longer
  stalls its thread's event loop.
- Bound the resulting parallelism with an explicit, process-wide concurrency cap derived from
  `user_config.threads_max`, so lifting the lock does not replace "one interpreter at a time" with "two hundred
  at once".
- Preserve the OCP-clobbering invariant exactly, and add a regression test that would fail if it were lost.
- Record concurrent sandbox execution as a specified capability, so the property is asserted by tests rather
  than left as an accident of how the locks happen to nest.

Not a user-visible behavior change: the same shapes are produced, from the same inputs, with the same contents.

## Capabilities

### New Capabilities

- `sandbox-concurrency`: The requirement that independent sandboxed CAD operations execute concurrently up to a
  configured bound; that mutual exclusion is scoped to the environment actually being mutated rather than to
  the runtime as a whole; that no sandbox operation blocks an event loop while waiting; and that concurrent
  execution never allows a package install to corrupt an environment another operation is already running in.

## Impact

- **Modified**: `partcad/src/partcad/runtime_python.py` — `async_lock()`/`sync_lock()`, `run_async_onced()`,
  `run_onced()`, and the `ensure*` family's locking.
- **Modified (possibly)**: `partcad/src/partcad/runtime_python_conda.py` — it overrides
  `sync_lock_install`/`async_lock_install`; confirm the new scheme composes with its global conda lock without
  inverting lock order.
- **New tests**: concurrency regression coverage alongside `partcad/tests/unit/test_runtime_python.py`.
- **New specs**: `openspec/specs/sandbox-concurrency/spec.md`.
- **Unchanged**: the wire protocol, the wrapper scripts, the shape cache, and every factory. This change is
  confined to *when* sandbox processes are allowed to run, not *what* they do.

## Non-Goals

- Reducing the *number* of sandbox invocations, or making them cheaper to start. That is a separate, larger
  change; see the sibling proposal `sandbox-process-reuse`.
- Reducing the cost of a cache hit; see the sibling proposal `shape-cache-efficiency`.
- Changing `ThreadPoolManager`'s sizing heuristics.
