#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the checks that put a question to somebody else's program share.

The `fea` and `cfd` checks hand a part to a solver (`test/cae.py`), and the `sim`
check hands a part or an assembly to a simulator (`test/sim.py`). In each, the
program is an implementation another package supplies -- PartCAD ships neither a
solver nor a simulator -- and in each the hard question is not what the program
said but what to make of it saying nothing at all.

The answer is one policy, and it lives here so that it is one: **not running is
a failure**, with one excuse, which is a machine that has no container runtime.
`_verdict()` is that policy, and its docstring is the argument for it.
Answering it once per check would be answering it differently sooner or later,
and then a part whose solver is missing would be failed by one check and excused
by the one beside it on the same machine.

Named after what the checks have in common rather than after either of them, and
emphatically *not* `implementation_test.py`: that matches pytest's default
`*_test.py` pattern, so any collection that reaches `src/` imports this module as
a test file -- see the note at the top of `test/cae.py`.
"""

from .. import runtime as pc_runtime
from .test import Test


class ImplementationTest(Test):
    """A check whose answer comes from an implementation another package supplies."""

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
        """What an implementation that produced no answer costs: a failure, or a skip.

        A failure by default, and that default is the whole contract of these
        checks: an object asked a question, the implementation was asked it, and
        nothing came back. Whatever the reason -- no solver, no mesher, no
        simulator, a crash -- the object has no answer, and a check that passed
        anyway would make `fea:` or `simulate:` decoration.

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
        matters to this question -- one carried the run -- so a failure there is
        a failure, and reading the local daemon would have excused it.

        Either way the reader gets the same sentence, which is the point of the
        dysfunction reports (`partcad.cae.dysfunction_report()`,
        `partcad.simulation.dysfunction_report()`): what was asked, what it
        said, and which platform it did not work on. A skip that said less than
        a failure would be a way of not finding out.

        Moved here from `CaeTest` when the `sim` check arrived, with nothing
        changed but the word "analysis" in the sentence it writes, so that a
        missing simulator and a missing solver are answered by one rule.
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
            " run here." % (" -- it runs in '%s'" % image if image else ""),
        )
