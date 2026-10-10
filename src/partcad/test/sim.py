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
  nothing checked it. The one excuse is theirs too -- a machine with no
  container runtime -- and so is the code deciding it,
  `ImplementationTest._verdict()`;
* a run whose `validation:` does not hold, or will not evaluate.

A declaration with **no `validation:`** passes once it has run. It states no
condition, so running -- the plugin resolved, the scene was exported, the
simulator came back with a `before` and an `after` -- is the whole of what it
asked, and the check says so out loud (`INFO`) so that the pass is not read as
more than it is.

Only a **part or an assembly that declares the section** is checked. A
`pc test -r` over a package tree would otherwise start a simulator for every
bolt in it, and a bolt with no `simulate:` has nothing to be placed in a world
for; declaring one is how a user says "check this one", which is why the check
needs no flag of its own. The same gate the analyses and the route have.

What this does not do is decide how a simulation runs. That is
`partcad.simulation.run_declared_async()`, the very loop `pc sim` runs, so the
command and the check run the same simulations the same way -- relative plugin
and scene names resolved from the package the object is in, and a run nothing
about has changed read back from the artifact cache rather than simulated again
(see `cache_artifacts`).
"""

import hashlib
import json

from .. import cae as pc_cae
from .. import runtime as pc_runtime
from .. import simulation as pc_simulation
from .implementation import ImplementationTest
from .test import Test


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
        """What the verdict depends on beyond the shape: the declarations themselves.

        A verdict on an object that declares a simulation is never remembered
        here (see `test()`), so this exists for the other case -- the "not
        applicable" pass every object without a `simulate:` gets, which *is*
        remembered. It must not be the answer for the same object once it has
        declared one, and nothing guarantees the shape's hash moves when it does:
        `simulate:` says nothing about the geometry, and is one of the keys the
        hash leaves out (see `shape._NON_GEOMETRIC_CONFIG_KEYS`). So the
        declarations are folded in here, and declaring the first simulation of
        an object is a new question rather than a cached answer to the old one.
        """
        declarations = self._declarations(shape)
        if not declarations:
            return ""
        declared = [[declaration.name, declaration.config] for declaration in declarations]
        return ".sim=" + hashlib.md5(json.dumps(declared, sort_keys=True, default=str).encode()).hexdigest()

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = None) -> bool:
        """Run every simulation the object declares, and pass it only if all of them held.

        Each of the object's simulations runs, whatever became of the one before
        it, and each failure is reported on its own: a package author fixing one
        claim wants to know about the other three now rather than one test run
        at a time.
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

        if test_ctx.get("force_manufacturing"):
            # Reached through another object -- an assembly's manufacturability
            # check testing what it is procured from, or a part's testing its
            # stock -- rather than because this object was asked about. Whether
            # it can be *had* does not turn on whether it behaves as it claims
            # to in a world, and the object's own claims are checked where it is
            # tested in its own right. Running them here as well would run each
            # one once per assembly using the object, concurrently with the
            # object's own run, in the one run directory a simulation of it has.
            self.debug(
                shape, "Simulated where it is tested, not as something %s is made from", test_ctx.get("action_prefix")
            )
            return self.TEST_PASSED

        # Never remembered as a bit, whatever the outcome. What a simulation
        # answered is already remembered where the whole question is in the
        # key: 'simulation.run_async' keys a run on the scene (and with it the
        # subject), the plugin, its options, its environment and the content of
        # its script, and re-evaluates the 'validation:' over a hit. A verdict
        # bit here could only be keyed on the shape and the declarations -- not
        # the plugin's script, not the scene's -- so it would outlive an edit to
        # either. And a run that failed may have failed on the machine, which no
        # key describes, for the reason `CaeTest` does not remember one either.
        test_ctx[self.NOT_CACHEABLE] = True

        kind = pc_simulation.subject_kind(shape)
        # Unreported: the verdict lines are this check's to write, below. See
        # `run_async`'s `report`.
        results = await pc_simulation.run_declared_async(ctx, shape, kind, report=False)

        verdicts = [self._judge(ctx, shape, result) for result in results]
        if all(verdicts):
            return self.passed(shape)
        return self.TEST_FAILED

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

        if result.passed is None:
            self.info(
                shape,
                "the simulation '%s' ran; it states no 'validation', so running is all it was checked for",
                result.name,
            )
        else:
            self.debug(shape, "the simulation '%s' validated", result.name)
        return self.TEST_PASSED
