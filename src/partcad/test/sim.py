#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The `sim` check `pc test` runs: an object does what its `simulate:` says.

`simulate:` is where a part or an assembly states what it is supposed to do --
or not do -- once it is placed in a world and the world is switched on: not fall
over, not slide off. `pc sim` runs those claims on request. This runs them as a
check, so that the claim is held to every time the package is tested rather
than whenever somebody remembers to ask -- which is what lets the claim be
written *first*: declare what the part must do, watch `pc test` fail, and design
until it passes.

There is one way to pass, and it is the same one `pc sim` reports as `PASSED`:
every simulation the object declares ran, and every `validation:` it states
held. Everything else fails, and says which object, which simulation and why:

* a declaration whose plugin or scene cannot be found -- no `simulation:`
  named, a package that is not a dependency or did not load, a scene that is
  not there or cannot hold a subject. Wrong wherever the package is opened, so
  no machine excuses it;
* a plugin that resolved and did not deliver -- a sandbox that will not build, a
  simulator that will not install on this platform, a crash. **Not running is
  not a reason to skip**, for the reason the `fea`/`cfd` checks give: the object
  asked a question, and calling no answer a skip reports it as checked when
  nothing checked it. The one excuse is theirs too -- a plugin that names a
  `container:` or a `dockerImage`, on a machine with no container runtime -- and
  so is the code deciding it, `ImplementationTest._verdict()`;
* a run whose `validation:` does not hold, or will not evaluate.

A declaration with **no `validation:`** states no condition, so there is nothing
to check a run of it against, and it is not run. What that costs depends on who
asked. Walking a package or a tree of them, it is **skipped**, out loud: the
package may hold a claim somebody is still writing, and the rest of the package
deserves its verdict. Asked about by name -- `pc test <object>`, which is
`Test.NAMED` -- it **fails**: somebody asked whether this object does what it
says, and it says nothing.

Only a **part or an assembly that declares the section** is checked. A
`pc test -r` over a package tree would otherwise start a simulator for every
bolt in it, and a bolt with no `simulate:` has nothing to be placed in a world
for; declaring one is how a user says "check this one", which is why the check
needs no flag of its own. The same gate the analyses and the route have.

What this does not do is decide how a simulation runs. That is
`partcad.simulation.run_async()`, the code `pc sim` runs, so the command and the
check run a simulation the same way -- relative plugin and scene names resolved
from the package the object is in, and a run nothing about has changed read back
from the artifact cache rather than simulated again (see `cache_artifacts`).

**The verdict is remembered too**, in `pc test`'s own cache, the way every
check's is. What it depends on is the shape, the declarations -- including the
`validation:` expressions, which the artifact cache deliberately leaves out --
and, per declaration, the key of the run it was judged on
(`simulation.question_key_async()`), which covers the scene, the plugin, its
options, its environment and the content of every script involved. So editing a
validation re-judges the run, from the cached run; editing anything that would
change the run runs it again; and nothing else changes the answer. Only a
verdict reached on keyed runs that all came back is remembered: a skip (which
has to be said every time it happens), a plugin that did not deliver (which may
be the machine), a declaration that does not resolve, and one with no
`validation:` (whose verdict depends on who asked) are worked out again on
every run.
"""

import hashlib
import json
import uuid

from .. import cae as pc_cae
from .. import runtime as pc_runtime
from .. import simulation as pc_simulation
from .implementation import ImplementationTest
from .test import Test

# What 'force_manufacturing' is spelt as on a 'test_ctx': set by the
# manufacturability checks when they test what another object is made from.
FORCE_MANUFACTURING = "force_manufacturing"


class SimTest(ImplementationTest):
    def __init__(self) -> None:
        """Named "sim", after `pc sim`: `pc test -f sim` selects it, and nothing else starts with it."""
        super().__init__("sim")

    def _declarations(self, shape) -> list:
        """The simulations this object declares, or nothing when the check does not apply."""
        if pc_simulation.subject_kind(shape) is None:
            return []
        return pc_simulation.of_shape(shape)

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What the verdict depends on beyond the shape.

        Nothing, for an object that declares no simulation: its "not applicable"
        is a property of the declaration, which the next part of the key covers
        the moment there is one.

        Otherwise, every declaration as written -- `validation:` included, which
        is the one thing a verdict depends on that the run it is judged on does
        not -- and, for each one with a validation, the key of that run. Without
        the second half the verdict would be keyed on the shape and the words of
        the declaration alone, and would outlive an edit to the plugin's script,
        to the scene, or to anything else `run_async` would have run again for:
        `simulate:` is outside the shape's hash, and so is everything about the
        world it is placed in.

        A run with no key -- a declaration that does not resolve, a subject that
        says `cache: false` -- makes the whole suffix one nothing can match. Such
        a verdict is never stored (see `test()`), and a key that could be met
        again would be one a stale answer could be found under if it ever were.
        """
        declarations = self._declarations(shape)
        if not declarations:
            return ""
        kind = pc_simulation.subject_kind(shape)
        entries = []
        for declaration in declarations:
            entry = {"name": declaration.name, "config": declaration.config}
            if declaration.validation:
                run = await pc_simulation.question_key_async(ctx, shape, kind, declaration)
                entry["run"] = run if run is not None else "unkeyed-%s" % uuid.uuid4().hex
            entries.append(entry)
        return ".sim=" + hashlib.md5(json.dumps(entries, sort_keys=True, default=str).encode()).hexdigest()

    async def test_cached(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        """The cached verdict -- except for an object reached through what it is made into.

        A manufacturability check testing an assembly's parts, or a part's
        stock, runs every check over that object with `force_manufacturing` set
        (see `ManufacturabilityTest`). This check has nothing to say in that
        walk (see `test()`), and the cache must not be asked: the key does not
        carry the flag, so the walk would be handed the object's own verdict --
        making an assembly unmanufacturable because a part does not stand up --
        or would leave its "nothing to say" behind as the object's own pass.
        """
        if test_ctx.get(FORCE_MANUFACTURING):
            return await self.test(tests_to_run, ctx, shape, dict(test_ctx))
        return await super().test_cached(tests_to_run, ctx, shape, test_ctx)

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = None) -> bool:
        """Run every simulation the object declares, and pass it only if all of them held.

        Each of the object's simulations is judged, whatever became of the one
        before it, and each failure is reported on its own: a package author
        fixing one claim wants to know about the other three now rather than one
        test run at a time. One after another rather than together, for the
        reason `pc sim` runs them that way: a simulator is what fills the
        machine, not the event loop.
        """
        # Not `= {}` in the signature: this check writes to `test_ctx`, and a
        # mutable default is one dict shared by every call that omits one. The
        # same note `CaeTest.test` carries.
        if test_ctx is None:
            test_ctx = {}

        declarations = self._declarations(shape)
        if not declarations:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        if test_ctx.get(FORCE_MANUFACTURING):
            # Reached through another object -- an assembly's manufacturability
            # check testing what it is procured from, or a part's testing its
            # stock -- rather than because this object was asked about. Whether
            # it can be *had* does not turn on whether it behaves as it claims
            # to in a world, and the object's own claims are checked where it is
            # tested in its own right. Running them here as well would run each
            # one once per assembly using the object, concurrently with the
            # object's own run, in the one run directory a simulation of it has.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(
                shape, "Simulated where it is tested, not as something %s is made from", test_ctx.get("action_prefix")
            )
            return self.TEST_PASSED

        kind = pc_simulation.subject_kind(shape)
        verdicts = []
        for declaration in declarations:
            if not declaration.validation:
                verdicts.append(self._unvalidated(shape, declaration, test_ctx))
                continue
            # Unreported: the verdict lines are this check's to write. See
            # `run_async`'s `report`.
            result = await pc_simulation.run_async(ctx, shape, kind, declaration, report=False)
            if not self._judged_on_a_keyed_run(result):
                test_ctx[self.NOT_CACHEABLE] = True
            verdicts.append(self._judge(ctx, shape, result))

        if all(verdicts):
            return self.passed(shape)
        return self.TEST_FAILED

    @staticmethod
    def _judged_on_a_keyed_run(result) -> bool:
        """Whether this run's verdict may be remembered: the run came back, and had a key.

        A validation that held or did not is a fact about the run, and the run
        is in the key. Anything else -- a declaration that did not resolve, a
        plugin that did not deliver (which may be the machine, and starting a
        runtime or installing a simulator changes no key), a run nothing could
        key -- is worked out again next time.
        """
        return result.error is None and result.passed is not None and result.artifact_key is not None

    def _unvalidated(self, shape, declaration, test_ctx: dict) -> bool:
        """A declaration that states no `validation:`: a skip in a walk, a failure when asked about.

        It is not run either way. There is nothing to judge a run of it by, so
        running it would start a simulator to say nothing; and whether it was
        asked about is all its verdict turns on, so nothing is remembered.
        """
        # The verdict depends on who asked, which the cache key does not carry;
        # and a skip has to be said every time it happens, which a remembered
        # pass does not do.
        test_ctx[self.NOT_CACHEABLE] = True
        if test_ctx.get(self.NAMED):
            return self.failed(
                shape,
                "the simulation '%s' states no 'validation', so there is nothing to check it against. Add a"
                " condition over 'before' and 'after' that is true when it went as it should; 'pc sim --json'"
                " prints what the plugin reports to write it against",
                declaration.name,
            )
        return self.skipped(
            shape,
            "the simulation '%s' states no 'validation', so there is nothing to check it against, and it was"
            " not run. Testing this object by name fails it until it states one",
            declaration.name,
        )

    def _judge(self, ctx, shape, result) -> bool:
        """One simulation's verdict, said once, in the check's own name."""
        if result.error is not None:
            if result.misconfigured or result.plugin is None:
                # Nothing ran, and nothing on this machine is why: the
                # declaration names a plugin or a scene that is not there.
                return self.failed(shape, "the simulation '%s' could not be run: %s", result.name, result.error)

            # The plugin resolved and did not deliver. What it said is relayed as
            # it stands, with which plugin and which machine; whether that is a
            # failure or the one excuse is the rule the analyses follow.
            remedy = pc_cae.NO_RUNTIME_REMEDY if isinstance(result.exception, pc_runtime.SandboxUnavailable) else None
            report = pc_simulation.dysfunction_report(
                result.object_name,
                result.name,
                result.plugin_name,
                result.exception if result.exception is not None else result.error,
                remedy=remedy,
            )
            return self._verdict(ctx, shape, result.plugin, report)

        if result.passed is False:
            return self.failed(shape, "%s", pc_simulation.validation_report(result))

        self.debug(shape, "the simulation '%s' validated", result.name)
        return self.TEST_PASSED
