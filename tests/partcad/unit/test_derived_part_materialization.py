#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How a part that only exists once an assembly is built gets built.

A URDF link or a STEP component is not declared in 'partcad.yaml' - the
assembly's own source file declares it - so resolving one has to instantiate
that assembly first, and instantiating is asynchronous.

That crosses the sync/async boundary, and it used to be crossed with a
'threading.Thread(...).start(); .join()', to borrow an event loop that
'asyncio.run()' could not create on a thread that already had one. What these
pin down is that it is crossed the way the rest of the codebase crosses it -
an '_async' implementation with a synchronous wrapper - because the thread cost
three things at once:

* 'join()' blocked the caller's event loop for the whole build;
* the thread was invisible to 'threads_max' and to the traced executors in
  'ThreadPoolManager', which is where every other thread in the core comes from;
* moving the work off the calling thread threw away the ownership of
  'Assembly.lock', an RLock chosen to be re-entrant precisely so that a nested
  resolution -- an assembly resolving one of the parts it itself produces --
  passes through instead of blocking on a lock the waiting thread holds.
"""

import ast
import asyncio
import pathlib
import threading

import pytest

from partcad.project import Project


class _FakeAssembly:
    """An assembly that records how its instantiation was reached."""

    def __init__(self):
        self.children = []
        self.threads = []
        self.loops = []

    async def do_instantiate(self):
        self.threads.append(threading.current_thread().name)
        self.loops.append(id(asyncio.get_running_loop()))
        self.children.append("link")


class _SlowAssembly(_FakeAssembly):
    def __init__(self, delay=0.05):
        super().__init__()
        self.delay = delay

    async def do_instantiate(self):
        await asyncio.sleep(self.delay)
        await super().do_instantiate()


def _bare_project(assembly, owner="robot"):
    """A Project with only what the materialization path reads.

    __init__ wants a configuration, a directory and a context, none of which have
    anything to say about which thread the build happens on.
    """
    prj = Project.__new__(Project)
    prj.name = "//pkg"
    prj.parts = {}
    prj._object_configs = {"assembly": {owner: {"type": "urdf"}}}
    prj._derived_parts_lock = threading.Lock()
    prj._derived_parts_attempted = set()
    prj._derived_parts_building = {}
    prj.get_assembly = lambda name, *args, **kwargs: assembly
    return prj


# ---- the cheap path ----------------------------------------------------------


def test_a_declared_part_builds_nothing():
    """The common case must not cost an event loop, let alone a thread."""
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)
    prj.parts = {"widget": object()}

    prj._materialize_derived_part("widget")

    assert assembly.threads == []


def test_a_name_no_assembly_produces_builds_nothing():
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    prj._materialize_derived_part("brackets/left")

    assert assembly.threads == []


def test_each_owner_is_claimed_once():
    """A build that produced nothing must not be repeated on every lookup."""
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    prj._materialize_derived_part("robot/base")
    assembly.children.clear()  # as an empty URDF would leave it
    prj._materialize_derived_part("robot/wheel")

    assert len(assembly.threads) == 1


# ---- the thread the build runs on --------------------------------------------


def test_the_sync_path_builds_on_the_calling_thread():
    """The heart of it. A thread hop is what lost 'Assembly.lock' ownership."""
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    prj._materialize_derived_part("robot/base")

    assert assembly.threads == [threading.current_thread().name]


def test_the_async_path_builds_on_the_callers_thread_and_loop():
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)
    seen = {}

    async def main():
        seen["thread"] = threading.current_thread().name
        seen["loop"] = id(asyncio.get_running_loop())
        await prj._materialize_derived_part_async("robot/base")

    asyncio.run(main())

    assert assembly.threads == [seen["thread"]]
    assert assembly.loops == [seen["loop"]], "the build must be awaited on the caller's own loop"


def test_the_async_path_does_not_block_the_callers_loop():
    """What 'thread.join()' did, and what a 75 minute silent CI hang looks like.

    The old code blocked the calling thread until the build finished. When the
    caller was a coroutine -- 'ProviderCart.add_object' is one -- that thread was
    an event loop, so every other task on it stopped, including whatever would
    have logged progress.
    """
    assembly = _SlowAssembly()
    prj = _bare_project(assembly)
    ticks = []

    async def main():
        async def ticker():
            while True:
                await asyncio.sleep(0.005)
                ticks.append(1)

        task = asyncio.create_task(ticker())
        await prj._materialize_derived_part_async("robot/base")
        task.cancel()

    asyncio.run(main())

    assert ticks, "the loop made no progress while the assembly was being built"


# ---- what a coroutine reaching the synchronous accessor gets ------------------


def test_the_sync_accessor_refuses_a_running_loop_by_name():
    """Loudly, and naming the way out.

    Borrowing a thread to get a clean loop is what this replaces, so the one
    thing it must not do is quietly find another way to block the caller's loop.
    """
    assembly = _FakeAssembly()
    prj = _bare_project(assembly)

    async def main():
        with pytest.raises(RuntimeError, match="get_part_async"):
            prj._materialize_derived_part("robot/base")

    asyncio.run(main())

    assert assembly.threads == []


def test_a_build_that_fails_is_reported_not_raised():
    """A part that cannot be built is a missing part, not an exception."""

    class Broken(_FakeAssembly):
        async def do_instantiate(self):
            raise Exception("the URDF is unreadable")

    prj = _bare_project(Broken())

    prj._materialize_derived_part("robot/base")  # must not raise

    async def main():
        await prj._materialize_derived_part_async("robot/base")

    prj._derived_parts_attempted.clear()
    asyncio.run(main())  # must not raise either


# ---- two callers, one owner ---------------------------------------------------
#
# 'AssemblyFactoryAssy.handle_node_list()' dispatches its links with
# 'asyncio.create_task', so two derived parts of one assembly really are resolved
# at the same time. Whoever arrives second must wait for the build rather than go
# and look its part up: 'children' is filled as the factory works, so a lookup
# made mid-build finds a part that is not registered yet, and 'handle_node()'
# raises "Part not found" on it.
#
# This could not bite while materialization ran on a thread the caller joined --
# that blocked the caller's loop, so no second task of it could run at all --
# which is exactly the blocking this change removes.


class _RegisteringAssembly(_FakeAssembly):
    """An assembly whose build registers its parts, slowly, like a real one."""

    def __init__(self, project, names, delay=0.05):
        super().__init__()
        self.project = project
        self.names = names
        self.delay = delay
        self.builds = 0

    async def do_instantiate(self):
        self.builds += 1
        await asyncio.sleep(self.delay)
        for name in self.names:
            self.project.parts[name] = object()
        await super().do_instantiate()


def test_a_second_caller_waits_for_the_build_instead_of_looking_up_mid_build():
    """Driven through get_part_async(), because the lookup is the point.

    Waiting for both callers and *then* checking proves nothing: the builder has
    finished by then, so the parts are registered whatever the second caller
    did. What matters is the value that second caller returns, which it looks up
    the instant materialization hands back.
    """
    names = ["robot/base", "robot/wheel"]
    prj = _bare_project(None)
    assembly = _RegisteringAssembly(prj, names)
    prj.get_assembly = lambda name, *a, **k: assembly
    # Stand in for get_object(): the registry lookup, without a real package.
    prj._part_object = lambda name, *a, **k: prj.parts.get(name)

    async def main():
        return await asyncio.gather(*(prj.get_part_async(n) for n in names))

    found = asyncio.run(main())

    assert all(part is not None for part in found), (
        "a caller was handed None for a part whose assembly was still being built; "
        "AssemblyFactoryAssy.handle_node() raises 'Part not found' on that"
    )
    assert assembly.builds == 1, "the owner was built more than once"


def test_the_waiter_does_not_rebuild_when_the_build_produced_nothing():
    """An empty URDF leaves 'children' empty; that is still one attempt, not two."""
    prj = _bare_project(None)
    assembly = _RegisteringAssembly(prj, names=[])  # registers nothing
    prj.get_assembly = lambda name, *a, **k: assembly

    async def main():
        await asyncio.gather(
            prj._materialize_derived_part_async("robot/base"),
            prj._materialize_derived_part_async("robot/wheel"),
        )

    asyncio.run(main())

    assert assembly.builds == 1


def test_a_failed_build_still_releases_the_waiter():
    """The waiter must not be left waiting on an event nobody will set."""

    class Failing(_FakeAssembly):
        def __init__(self):
            super().__init__()
            self.builds = 0

        async def do_instantiate(self):
            self.builds += 1
            await asyncio.sleep(0.01)
            raise Exception("the URDF is unreadable")

    prj = _bare_project(None)
    assembly = Failing()
    prj.get_assembly = lambda name, *a, **k: assembly

    async def main():
        await asyncio.wait_for(
            asyncio.gather(
                prj._materialize_derived_part_async("robot/base"),
                prj._materialize_derived_part_async("robot/wheel"),
            ),
            timeout=10,
        )

    asyncio.run(main())  # must not hang

    assert assembly.builds == 1


# ---- the synchronous accessor must claim nothing it cannot honour --------------
#
# Both of these deadlock rather than fail if the running-loop check is made after
# the claim or after the wait, which is why each is bounded by a timeout: a
# regression here has to show up as a failure, not as a suite that never ends.


def test_a_coroutine_reaching_the_sync_accessor_mid_build_does_not_block_the_loop():
    """It must be refused, not parked on the builder's event.

    'done' is set by the builder, and the builder is a task on this very loop.
    Blocking the loop to wait for it means it can never run -- the command
    deadlocks outright, which is worse than the blocking this change removed.
    """
    prj = _bare_project(None)
    assembly = _SlowAssembly(delay=0.05)
    prj.get_assembly = lambda name, *a, **k: assembly

    async def main():
        builder = asyncio.create_task(prj._materialize_derived_part_async("robot/base"))
        await asyncio.sleep(0.01)  # let the builder claim the owner
        with pytest.raises(RuntimeError, match="get_part_async"):
            prj._materialize_derived_part("robot/wheel")
        await builder

    asyncio.run(asyncio.wait_for(main(), timeout=10))


def test_a_refused_sync_caller_leaves_no_claim_behind():
    """Otherwise the owner is marked as building by a build that never starts.

    The claim used to be taken before the caller was checked, so the raise
    unwound past an event nobody would ever set, and every later async caller
    polled on it for good.
    """
    prj = _bare_project(None)
    assembly = _RegisteringAssembly(prj, ["robot/base"])
    prj.get_assembly = lambda name, *a, **k: assembly

    async def refused():
        with pytest.raises(RuntimeError, match="get_part_async"):
            prj._materialize_derived_part("robot/base")

    asyncio.run(refused())

    assert prj._derived_parts_building == {}, "a build was claimed by a caller that never ran one"
    assert "robot" not in prj._derived_parts_attempted, "the owner was marked attempted without an attempt"

    # And the owner is still buildable afterwards.
    async def main():
        await asyncio.wait_for(prj._materialize_derived_part_async("robot/base"), timeout=10)

    asyncio.run(main())
    assert "robot/base" in prj.parts


# ---- no coroutine is left calling the synchronous accessor ---------------------


def _src_root():
    """The 'src' directory of this checkout, from this file's own location."""
    return pathlib.Path(__file__).resolve().parents[3] / "src"


def _sync_part_lookups_inside_coroutines():
    """(file, line, name, enclosing functions) for each one still there.

    Lexical, so it says nothing about a synchronous helper a coroutine calls -
    but every case found so far has been of this shape, and it is the shape a
    reviewer cannot see: the call reads like any other line in the function.
    """
    found = []

    class Visitor(ast.NodeVisitor):
        def __init__(self, path):
            self.path = path
            self.stack = []

        def _function(self, node, is_async):
            self.stack.append((node.name, is_async))
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node):
            self._function(node, False)

        def visit_AsyncFunctionDef(self, node):
            self._function(node, True)

        def visit_Call(self, node):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in ("get_part", "_get_part") and any(is_async for _, is_async in self.stack):
                enclosing = " > ".join(n for n, _ in self.stack)
                found.append((self.path, node.lineno, name, enclosing))
            self.generic_visit(node)

    modules = sorted(_src_root().rglob("*.py"))
    # A sweep that reads nothing passes for the wrong reason, and the path it
    # walks is derived from this file's location rather than the working
    # directory, so a move of either tree would do exactly that.
    assert len(modules) > 100, "%s is not the source tree" % _src_root()
    for path in modules:
        Visitor(path).visit(ast.parse(path.read_text(encoding="utf-8")))
    return found


def test_no_coroutine_calls_the_synchronous_part_accessor():
    """The synchronous accessor now raises at a coroutine, so this is a bug.

    'Project.get_part()' answers a caller that already owns a loop by naming
    'get_part_async()', because materializing a derived part from there is
    something it cannot do. That is a better answer than the borrowed thread it
    replaced -- but it turns every unconverted coroutine into a failure the
    moment the part it asks for happens to be a derived one, which is a property
    of the package being read rather than of the call.

    Seven such callers existed when the accessor started refusing. Three were
    converted with it -- 'AssemblyFactoryAssy' twice and 'ProviderCart.add_object'
    -- and four were missed: two in 'PartFactoryAlias' resolving the source it
    points at, one in 'PartFactoryEnrich' doing the same, and '_test_async' in
    the JSON-RPC service. The last of those is what failed CI, on the single
    behave scenario that tests a URDF link by name. Sweeping for the call is how
    the other three were found, so the sweep is kept.
    """
    remaining = _sync_part_lookups_inside_coroutines()

    assert remaining == [], "await get_part_async() instead:\n" + "\n".join(
        "  %s:%d %s() in %s" % (path, line, name, enclosing) for path, line, name, enclosing in remaining
    )
