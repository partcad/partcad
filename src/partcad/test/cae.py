#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The shared body of the CAE checks `pc test` runs: FEA, and CFD.

A part passes when the analysis has **no findings**. That is the whole verdict,
and it is deliberately not a threshold PartCAD holds an opinion about: what
counts as too much stress or too much drag is the solver's judgement, expressed
by whether it says anything at all. PartCAD's part of the bargain is to run the
implementation the user configured and to report what it reported.

Two things bound how expensive this is, and both are the same gate:

* Only a **part** is analysed. An assembly is a set of parts that each carry
  their own boundary conditions, and a load on the whole of one says nothing
  about which member bears it.
* Only a part that **declares the section**. A `pc test -r` over a package tree
  would otherwise start a solver for every bolt in it, and a bolt with no
  `fea:` has nothing for a solver to be told. Declaring `fea:` is how a user
  says "check this one", which is why the check needs no flag of its own.

Everything else - which implementation, what the boundary conditions mean, what
units they are in - is `partcad.cae` and `Shape.analyze_async()`, shared with
`pc cae fea` so that the test and the command cannot disagree about a part.

Named after what it checks, like `cam.py` and `connect.py` beside it, and
emphatically *not* `cae_test.py`: that matches pytest's default `*_test.py`
pattern, so any collection that reaches `src/` imports this module as a test
file -- under a package name that does not resolve -- and the run dies during
collection rather than running anything.
"""

import hashlib
import json

from .. import cae as pc_cae
from .. import logging as pc_logging  # noqa: F401  # re-exported to the CAE test subclasses
from .. import output
from .. import runtime as pc_runtime
from ..part import Part
from .test import Test


class CaeTest(Test):
    def __init__(self, analysis: str) -> None:
        """One check per analysis, named after it: `pc test -f fea` selects it."""
        super().__init__(analysis)
        self.analysis = analysis

    def _config(self, shape):
        """The boundary conditions, or None when this test does not apply.

        A malformed section is *not* None: it is a failure, and it is raised
        rather than swallowed so that `test()` reports the sentence saying what
        is wrong with it.
        """
        if not isinstance(shape, Part):
            return None
        return pc_cae.config_of(shape, self.analysis)

    def cache_key_suffix(self, ctx, shape) -> str:
        """What this test reads beyond the shape, folded into the cache key.

        Three things, none of which moves `shape.hash`:

        * the boundary conditions, because a part whose load has just been
          doubled must not be answered with the verdict on the old one;
        * which implementation ran, because two solvers are two answers, and
          switching to one that is installed here is exactly what a user does
          after the first run;
        * the implementation's own configuration, because a package that
          re-tunes a solver's parameters has changed the question as surely as
          changing the load would.

        The last of those is the options as `analysis_getopts()` resolves them,
        which is the whole layering and not just the object's own `cae:`
        section: the implementing package's defaults are most of what a solver
        is told, and a package that re-tunes one of them would otherwise be
        answered with the verdict from before it did. They are read as the
        *declared* text and not as anything computed from running it -
        re-running the analysis to decide whether a cached answer may be used
        would cost precisely what the cache saves.
        """
        try:
            config = self._config(shape)
        except pc_cae.CaeConfigError as e:
            # A malformed section is its own cache key: correcting it has to
            # produce a fresh run rather than the failure of what it replaced.
            return ".malformed=" + hashlib.md5(str(e).encode()).hexdigest()
        if config is None:
            return ""

        parts = [json.dumps(config.to_data(), sort_keys=True)]
        try:
            # The part's own 'implementation:' if it declared one, exactly as
            # 'test()' resolves it -- otherwise the key describes the run the
            # user configuration would have produced rather than the run that
            # happens, and re-pointing a part at another solver would be
            # answered from the cache of the first.
            options_project, format_name = shape._analysis_implementation(
                ctx, self.analysis, declared=config.implementation
            )
            parts.append("%s:%s" % (options_project.name, format_name))
            opts, _output_dir = shape._output_getopts(
                ctx, format_name, output.CAE, ctx.get_project(shape.project_name), options_project
            )
            parts.append(json.dumps(opts, sort_keys=True, default=str))
        except Exception as e:
            # The implementation could not be resolved -- not installed, not a
            # dependency, misspelt. That is its own question and its own answer,
            # so it gets its own key rather than borrowing the one belonging to
            # a run that did resolve.
            parts.append("unresolved:%s" % e)
        return "." + self.analysis + "=" + hashlib.md5("\n".join(parts).encode()).hexdigest()

    def _a_container_was_available(self, ctx) -> bool:
        """Whether a container was available to run this implementation in.

        Two ways for that to be true, and only one of them is on this machine.
        A local daemon is the obvious one. The other is `pythonSandbox: remote`,
        which sends the command to a service that starts the container over
        there -- so the host needs no daemon of its own, and asking its daemon
        would report "no container runtime" on a machine whose every part is
        already being built in one.
        """
        if getattr(ctx.user_config, "python_sandbox", None) == "remote":
            return True
        return pc_runtime.docker_available()

    def _verdict(self, ctx, shape, impl, report: str) -> bool:
        """What an analysis that produced no answer costs: a failure, or a skip.

        A failure by default, and that default is the whole contract of this
        check: a part asked a question, the implementation was asked it, and
        nothing came back. Whatever the reason -- no solver, no mesher, a crash
        -- the part has no answer, and a check that passed anyway would make
        `fea:` decoration.

        The exception is a machine with **no container runtime**, and it is the
        only one. A container is how an implementation brings what pip cannot
        install: an image can carry a solver, a mesher and the shared libraries
        under them, and nothing else PartCAD has can. On a machine with no
        container runtime there is no arrangement under which such an
        implementation could have been given what it needs, so the question was
        never really put -- and the honest verdict for a question nobody could
        ask is a skip.

        That the implementation declares an image or not does not change it, and
        deliberately: an implementation is free to say nothing about containers
        and still need a solver, and reading the declaration would make the
        verdict depend on how well its author documented themselves rather than
        on what this machine can do. What the declaration is good for is the
        *message*, which names the image when there is one.

        Once a runtime answers, the excuse is gone entirely -- a registry that
        cannot be reached, an image that will not start, a solver missing from
        the image are all things somebody can fix, and calling them
        "unavailable" would hide exactly the failures a plugin's own CI exists
        to catch. That is the half that keeps this narrow enough to be worth
        having, and it is why continuous integration, which has a container
        runtime, sees every one of these as a failure.

        "Answers" is not "answers *here*", though, and the `remote` sandbox is
        the case that makes the difference: it runs the implementation in a
        container on somebody else's machine and needs no daemon on this one. A
        host configured that way has a container runtime in every sense that
        matters to this question -- one carried the analysis -- so a failure
        there is a failure, and reading the local daemon would have excused it.

        Either way the reader gets the same sentence, which is the point of
        `dysfunction_report()`: what was asked, what it said, and which platform
        it did not work on. A skip that said less than a failure would be a way
        of not finding out.
        """
        if self._a_container_was_available(ctx):
            return self.failed(shape, "%s", report)

        try:
            image = impl.docker_image or (impl.container or {}).get("image")
        except Exception:
            # `container` raises on a `container:` that names no `image:`. That
            # is its own failure, reported where the declaration is read; here
            # it only means there is no image name to put in this sentence, and
            # raising out of an error path would replace a report the user needs
            # with a traceback about a different mistake.
            image = None
        return self.skipped(
            shape,
            "%s\n\t%s",
            report,
            "There is no container runtime on this machine, so there is no way to give this implementation"
            " what pip cannot install%s. Start one, or install what the message above names, to have this"
            " analysis run here." % (" -- it runs in '%s'" % image if image else ""),
        )

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = None) -> bool:
        """Run the analysis, and pass the shape only if it found nothing.

        **There is one way to pass: the analysis ran and reported no findings.**
        Everything else is a failure, and the report says which of them it was.
        A part that declares `fea:` has asked a question, and any answer other
        than "nothing to report" is something a user has to act on:

        * the part declared the section wrongly;
        * the implementation could not be resolved -- not a dependency, did not
          load, declares no such file type;
        * the implementation resolved and could not run: no mesher, no solver,
          an unprovisionable sandbox, a crash;
        * the analysis ran and reported findings.

        **Not running is not a reason to skip.** A skip says the question does
        not apply here; a plugin that was asked to do something and did not do it
        has failed, and calling that a skip reports a part as checked when
        nothing checked it. That was this check's earlier behaviour -- a missing
        `ccx` warned and passed -- and it hid two things worth failing over: a
        CFD implementation that never converges, and a plugin that cannot be
        installed on this platform at all.

        **Nothing is a skip any more**, including a machine with no container
        runtime. That one was a skip while a `container:` meant "a sandbox is
        not enough" -- nothing was asked, because the thing that asks could not
        start, so the verdict said nothing about the implementation or the part.
        A `dockerImage` is a different claim: it names the sandbox to prefer,
        while the same package's requirements say how to run without one. So a
        machine with no container runtime is a machine that has to supply the
        dependencies itself, and a part that asked a question and got no answer
        has failed either way.

        What that absence still earns is a sentence PartCAD has to write, since
        the implementation never ran to write one: both remedies, because either
        fixes it and only the reader knows which is easier where they are.

        The consequence is real and is the point: declaring `fea:` in a shared
        package makes `pc test` fail for everyone who has not installed what the
        implementation needs. That is what declaring it means. A package that
        does not want the whole world running a solver should not declare the
        section, which is the same gate that keeps `pc test -r` from starting a
        solver for every bolt in a tree.

        What the failure must carry is *why*, because the reasons need different
        actions: install a solver, use another machine, or fix the part. The
        implementation is what knows which, so whatever it said is reported
        verbatim -- see `partcad.cae.dysfunction_report()`.
        """
        # Not `= {}` in the signature, the way the sibling checks have it: this
        # is the one that *writes* to `test_ctx` (`NOT_CACHEABLE`, below), and a
        # default argument is one dict shared by every call that omits one. A
        # direct call with no context would otherwise set the flag on the
        # default itself and leave it set for every later caller.
        if test_ctx is None:
            test_ctx = {}

        try:
            config = self._config(shape)
        except pc_cae.CaeConfigError as e:
            # The part asked for this analysis and got the request wrong. That
            # is a failure of the package rather than of the part, and saying so
            # here is the only place a user finds out without running `pc cae`.
            return self.failed(shape, "%s", e)

        if config is None:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            # Resolved here, and separately, so that failing to resolve it
            # reads differently from failing to run it. Both are failures now,
            # but they ask for different things: a name that resolves to nothing
            # is a configuration to correct, and a plugin that will not run is a
            # machine to equip or a platform to leave.
            #
            # Both halves are asked, because both are the configuration's fault:
            # whether the package resolves at all, and whether it declares the
            # file type with the 'extension:' an analysis needs. Neither becomes
            # true or false depending on what is installed here.
            options_project, format_name = shape._analysis_implementation(
                ctx, self.analysis, declared=config.implementation
            )
            impl, _ = shape.analysis_getopts(
                ctx,
                self.analysis,
                format_name,
                ctx.get_project(shape.project_name),
                None,
                options_project,
                None,
            )
        except Exception as e:
            return self.failed(shape, "the '%s' implementation could not be resolved: %s", self.analysis, e)

        try:
            result = await shape.analyze_async(ctx, self.analysis)
        except pc_cae.CaeConfigError as e:
            return self.failed(shape, "%s", e)
        except pc_runtime.SandboxUnavailable as e:
            # The one failure PartCAD writes rather than the implementation:
            # the implementation never started, so it has nothing to say. What
            # it earns is both remedies rather than one -- start a runtime, or
            # install what the implementation needs here -- because either fixes
            # it and only the reader knows which is easier where they are.
            #
            # Whether it is a failure at all is `_verdict`'s to decide, and the
            # answer is the same one it gives the branch below: no container
            # runtime is a skip, and everything else is a failure. Deciding it
            # in one place is what keeps "the sandbox would not start" and "the
            # solver was missing from it" from being answered differently, which
            # they were while this branch answered for itself.
            #
            # Uncacheable either way: starting a container runtime changes no
            # cache key, so a remembered verdict would outlive its reason.
            test_ctx[self.NOT_CACHEABLE] = True
            return self._verdict(
                ctx,
                shape,
                impl,
                pc_cae.dysfunction_report(
                    "%s:%s" % (shape.project_name, shape.name),
                    self.analysis,
                    "%s:%s" % (options_project.name, format_name),
                    e,
                    remedy=pc_cae.NO_RUNTIME_REMEDY,
                ),
            )
        except Exception as e:
            # The implementation was asked and did not deliver. That is a
            # failure whatever the reason -- no solver, no mesher, a sandbox
            # that cannot be built, a crash -- because the part asked a question
            # and got no answer.
            #
            # Reported as `analyze_async` wrote it, which is also what `pc cae`
            # prints: which implementation was asked, what it said, and which
            # machine it did not work on. `pc test` used to compose that here,
            # and then a user who ran the command instead was told less about
            # the same failure. Anything that arrives without a report already
            # on it -- something raised outside the part `analyze_async` wraps
            # -- gets one here, because the two things a bare sentence is
            # missing are exactly the two this check knows.
            #
            # Not remembered, though. This is the one verdict here that can be
            # about the machine rather than about the part, and the cache key
            # describes only the question: the boundary conditions, the
            # implementation, its options. Installing the solver changes none of
            # them, so a cached failure would outlive the reason for it and go
            # on failing a part that now analyses perfectly well.
            test_ctx[self.NOT_CACHEABLE] = True
            report = (
                str(e)
                if isinstance(e, pc_cae.CaeFailed)
                else pc_cae.dysfunction_report(
                    "%s:%s" % (shape.project_name, shape.name),
                    self.analysis,
                    "%s:%s" % (options_project.name, format_name),
                    e,
                )
            )
            return self._verdict(ctx, shape, impl, report)

        findings = result.get("findings") or []
        if findings:
            return self.failed(
                shape,
                "%s",
                pc_cae.findings_report("%s:%s" % (shape.project_name, shape.name), self.analysis, findings),
            )
        return self.passed(shape)
