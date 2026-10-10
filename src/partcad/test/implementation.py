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
a failure**, with one excuse -- an implementation that declares a container is
how what it needs arrives, on a machine with no container runtime to start one.
`_verdict()` is that policy, and its docstring is the argument for it. Answering
it once per check would be answering it differently sooner or later, and then a
part whose solver is missing would be failed by one check and excused by the one
beside it on the same machine.

Named after what the checks have in common rather than after either of them, and
emphatically *not* `implementation_test.py`: that matches pytest's default
`*_test.py` pattern, so any collection that reaches `src/` imports this module as
a test file -- see the note at the top of `test/cae.py`.
"""

import typing

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

    @staticmethod
    def _declared_image(impl) -> typing.Tuple[bool, typing.Optional[str]]:
        """Whether the implementation says a container is how it runs, and in which image.

        Either spelling says so: a `container:`, which runs it there and nowhere
        else, and a `dockerImage`, which names the image its sandbox is built
        from where there is a runtime to build one. A `container:` that names no
        image is a broken declaration rather than a statement about this
        machine, so it claims nothing here -- it fails with its own sentence,
        wherever it is read.
        """
        if impl is None:
            return False, None
        try:
            container = impl.container
        except Exception:
            container = None
        image = impl.docker_image or (container or {}).get("image")
        return bool(image), image

    def _verdict(self, ctx, shape, impl, report: str) -> bool:
        """What an implementation that produced no answer costs: a failure, or a skip.

        A failure by default, and that default is the whole contract of these
        checks: an object asked a question, the implementation was asked it, and
        nothing came back. Whatever the reason -- no solver, no mesher, no
        simulator, a crash -- the object has no answer, and a check that passed
        anyway would make `fea:` or `simulate:` decoration.

        **There is one excuse**, and it is the case where the implementation was
        never given the environment it says it needs. An implementation that
        names a `container:` or a `dockerImage` is stating that a container is
        how what pip cannot install arrives -- a solver, a mesher, the shared
        libraries under them. On a machine with no container runtime that
        statement has nowhere to land, nothing was ever really asked, and the
        honest verdict for a question nobody could ask is a skip.

        It is narrow in both directions, and both are the point:

        * **An implementation that names no image gets no excuse.** It said it
          runs in an ordinary sandbox, and a machine with a working sandbox is a
          machine it was supposed to work on. A simulator that is a wheel, a
          solver the package installs with pip: if those do not run here, that
          is the implementation or the platform, and somebody can fix it.
        * **A container runtime that answers removes the excuse entirely.** A
          registry that cannot be reached, an image that will not start, a
          solver missing from the image are all things somebody can fix, and
          calling them "unavailable" would hide exactly the failures a plugin's
          own CI exists to catch -- which is why continuous integration, which
          has a runtime, sees every one of these as a failure.

        "Answers" is not "answers *here*", though, and the `remote` sandbox is
        the case that makes the difference: it runs the implementation in a
        container on somebody else's machine and needs no daemon on this one. A
        host configured that way has a container runtime in every sense that
        matters to this question -- one carried the run -- so a failure there is
        a failure, and reading the local daemon would have excused it.

        This is the rule `docs/source/features.rst` ("Engineering analysis") and
        `runtime.SandboxUnavailable` state. Until the `sim` check arrived the
        code read only the machine and excused everything on one without a
        runtime, image or not; moving it here was when the two were made to
        agree, so `fea` and `cfd` are as strict as the documentation said they
        were.

        Either way the reader gets the same sentence, which is the point of the
        dysfunction reports (`partcad.cae.dysfunction_report()`,
        `partcad.simulation.dysfunction_report()`): what was asked, what it
        said, and which platform it did not work on. A skip that said less than
        a failure would be a way of not finding out.
        """
        declares_one, image = self._declared_image(impl)
        if not declares_one or self._a_container_was_available(ctx):
            return self.failed(shape, "%s", report)

        return self.skipped(
            shape,
            "%s\n\t%s",
            report,
            "There is no container runtime on this machine, and this implementation runs in '%s': that is how"
            " it brings what pip cannot install. Start one, or install what the message above names, to have"
            " this run here." % image,
        )
