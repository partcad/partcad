#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""That the lock over conda is one lock, held by whoever is running conda.

There is one conda per machine and one package cache under it, so every conda
sandbox -- the Python one of each version, and the Node.js one -- has to be
provisioned behind the same lock. Each of them used to build a FileLock of its
own over the one lock file instead, which held across processes and, by
accident, across threads. It did not hold across the tasks of one event loop,
which is what a render actually is: the second task to reach conda was the same
*thread* asking filelock for a lock it already held through another object, and
filelock refuses that outright rather than hanging on it. So a render that
provisioned two conda sandboxes died with

    Deadlock: lock '~/.partcad/.conda.lock' is already held by a different
    FileLock instance in this thread.

What is tested here is therefore both halves: that the second acquire does not
raise, and that it does not simply walk in either -- 'is_singleton=True', the
fix filelock's message suggests, would have made that error go away by letting
two conda installs run at once, which is the thing the lock exists to prevent.
"""

import asyncio
from types import SimpleNamespace

from partcad import sandbox_lock


def test_every_conda_sandbox_shares_one_lock(tmp_path):
    """The Python sandboxes of two versions and the Node.js one, one object."""
    python_311 = sandbox_lock.conda(str(tmp_path))
    python_313 = sandbox_lock.conda(str(tmp_path))
    javascript = sandbox_lock.conda(str(tmp_path))

    assert python_311 is python_313
    assert python_311 is javascript
    assert python_311.lock_path.endswith(sandbox_lock.CONDA_LOCK_NAME)


def test_a_second_workspace_gets_a_lock_of_its_own(tmp_path):
    assert sandbox_lock.conda(str(tmp_path)) is not sandbox_lock.conda(str(tmp_path / "elsewhere"))


def test_two_provisions_on_one_loop_do_not_raise(tmp_path):
    """The failure this reproduces: two conda sandboxes in one render.

    Both tasks run on the loop of one thread and both hold the lock across an
    'await', which is what made filelock's per-thread deadlock check fire.
    """
    lock = sandbox_lock.conda(str(tmp_path))
    inside = 0
    peak = 0

    async def provision():
        nonlocal inside, peak
        async with lock.acquire_async(write=True):
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.01)
            inside -= 1

    async def both():
        await asyncio.wait_for(asyncio.gather(provision(), provision()), timeout=10)

    asyncio.run(both())

    # Not raising is only half of it: one at a time is what the lock is for.
    assert peak == 1


def test_a_provision_waiting_leaves_the_loop_free(tmp_path):
    """Waiting is what has to be asynchronous.

    conda runs for minutes under this lock, so a task that waited for it by
    blocking would be blocking the loop the holder needs in order to finish.
    """
    lock = sandbox_lock.conda(str(tmp_path))
    order = []

    async def holder():
        async with lock.acquire_async(write=True):
            order.append("conda-in")
            await asyncio.sleep(0.05)
            order.append("conda-out")

    async def waiter():
        await asyncio.sleep(0.01)
        async with lock.acquire_async(write=True):
            order.append("npm")

    async def both():
        await asyncio.wait_for(asyncio.gather(holder(), waiter()), timeout=10)

    asyncio.run(both())
    assert order == ["conda-in", "conda-out", "npm"]


def _conda_runtimes(tmp_path):
    """The three conda sandboxes a render can want at once.

    Constructed for real, because what is being tested is what __init__ hands
    them. Nothing conda-related runs: the sandbox directories do not exist, so
    each of them stops at "not initialized" and provisioning is never entered.
    """
    from partcad.runtime_javascript_conda import CondaJavaScriptRuntime
    from partcad.runtime_python_conda import CondaPythonRuntime

    ctx = SimpleNamespace(user_config=SimpleNamespace(internal_state_dir=str(tmp_path)))
    return (
        CondaPythonRuntime(ctx, "3.11"),
        CondaPythonRuntime(ctx, "3.13"),
        CondaJavaScriptRuntime(ctx, "22"),
    )


def test_the_conda_runtimes_hold_the_same_lock(tmp_path):
    """Two Python versions and a Node.js: one conda, so one lock object."""
    python_311, python_313, javascript = _conda_runtimes(tmp_path)

    assert python_311.global_conda_lock is python_313.global_conda_lock
    assert python_311.global_conda_lock is javascript.global_conda_lock
    assert python_311.global_conda_lock is sandbox_lock.conda(str(tmp_path))


def test_two_runtimes_provisioning_on_one_loop(tmp_path):
    """The CI failure itself, through the runtimes' own install lock.

    Rendering the examples provisions a 3.11 sandbox and a 3.13 one, and the
    tasks that do it share a thread. Before the lock was shared this raised
    filelock's "already held by a different FileLock instance in this thread".
    """
    python_311, python_313, javascript = _conda_runtimes(tmp_path)
    inside = 0
    peak = 0

    async def provision(runtime):
        nonlocal inside, peak
        async with runtime.async_lock_install():
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.01)
            inside -= 1

    async def all_of_them():
        await asyncio.wait_for(
            asyncio.gather(provision(python_311), provision(python_313), provision(javascript)),
            timeout=10,
        )

    asyncio.run(all_of_them())

    assert peak == 1
