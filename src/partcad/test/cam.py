#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The `cam` check `pc test` runs: an object that asks to be cut can be cut.

An object that declares a `cam:` section has said it is made on a machine. This
check puts that to the test the only way there is -- it produces the route and
sees whether one comes back. A part passes when a route was written; it fails
when the section is wrong, when the implementation cannot be resolved, or when
the implementation was asked and delivered nothing.

It is the exact shape of the `fea`/`cfd` checks beside it, and for the same
reasons:

* Only a **sketch or a part**. An assembly is put together rather than cut, and
  a scene is an arrangement of things that were each cut on their own, so
  neither has an outline a machine could follow.
* Only an object that **declares the section**. A `pc test -r` over a package
  tree would otherwise start a CAD sandbox for every bolt in it, and a bolt with
  no `cam:` has nothing to be routed. Declaring `cam:` is how a user says "check
  this one", which is why the check needs no flag of its own.

What it does *not* share with those two is where the file goes. An analysis
writes its model beside the package and keeps it, because the model is the
answer somebody asked for; a route produced by a check is a by-product, and one
left beside the package would be indistinguishable from the one `pc cam` writes
-- checked in by accident, or read as current long after the part moved on. So
this writes into a temporary directory and deletes it. What the check keeps is
the verdict.

**This is not `partcad.test.manufacturability`**, which is the check that asks
whether an object can be made or bought *at all*: whether its geometry suits the
method it declares, whether what it is made of is reproducible, whether a
supplier could be found. That one was called `cam` until `pc cam` existed, at
which point one word was answering two questions. This one asks the narrower and
more concrete thing: run the post-processor, and see if a program comes out.
"""

import hashlib
import json
import shutil
import tempfile

from .. import cam as pc_cam
from .. import output
from .. import runtime as pc_runtime
from ..part import Part
from ..sketch import Sketch
from .test import Test


class CamTest(Test):
    def __init__(self) -> None:
        """`pc test -f cam` selects it, and nothing else now starts with `cam`."""
        super().__init__("cam")

    def _config(self, shape):
        """The job the object declares, or None when this test does not apply.

        A malformed section is *not* None: it is a failure, and it is raised
        rather than swallowed so that `test()` reports the sentence saying what
        is wrong with it -- the same split `CaeTest._config` makes.
        """
        if not isinstance(shape, (Part, Sketch)):
            return None
        return pc_cam.config_of(shape)

    async def cache_key_suffix(self, ctx, shape) -> str:
        """What this test reads beyond the shape, folded into the cache key.

        Three things, none of which moves `shape.hash`, and they are the three
        `CaeTest` folds in for the same reasons:

        * the job, because an object whose tool has just been halved must not be
          answered with the verdict on the old one;
        * which implementation ran, because two post-processors are two answers;
        * the implementation's own configuration as `cam_getopts()` resolves it
          -- the whole layering, not the object's own section alone, because the
          implementing package's defaults are most of what the run is told and a
          package that re-tunes one of them has changed the question.
        """
        try:
            config = self._config(shape)
        except pc_cam.CamConfigError as e:
            # A malformed section is its own cache key: correcting it has to
            # produce a fresh run rather than the failure of what it replaced.
            return ".malformed=" + hashlib.md5(str(e).encode()).hexdigest()
        if config is None:
            return ""

        parts = [json.dumps(config.to_data(), sort_keys=True)]
        try:
            options_project, format_name = shape._route_implementation(ctx, declared=config.implementation)
            parts.append("%s:%s" % (options_project.name, format_name))
            opts, _output_dir = shape._output_getopts(
                ctx, format_name, output.CAM, ctx.get_project(shape.project_name), options_project
            )
            parts.append(json.dumps(opts, sort_keys=True, default=str))
        except Exception as e:
            # The implementation could not be resolved -- not installed, not a
            # dependency, misspelt. Its own question and its own answer, so it
            # gets its own key rather than borrowing one belonging to a run that
            # did resolve.
            parts.append("unresolved:%s" % e)
        return ".cam=" + hashlib.md5("\n".join(parts).encode()).hexdigest()

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = None) -> bool:
        """Produce the route, and pass the object only if one came back.

        **There is one way to pass: a route was written.** Everything else is a
        failure, and the report says which of them it was:

        * the object declared the section wrongly;
        * the implementation could not be resolved -- not a dependency, did not
          load, declares no such file type, declares no `extension:`;
        * the implementation resolved and produced nothing: a sandbox that will
          not build, a crash, a tool bigger than the hole it was asked to cut,
          an outline the offset consumed.

        **Not producing one is not a reason to skip**, the same rule `CaeTest`
        follows. A skip says the question does not apply here; an object that
        declares `cam:` has asked one, and an implementation that was asked and
        did not answer has failed. Calling that a skip reports an object as
        checked when nothing checked it.

        A **sandbox that cannot be provisioned** is the one thing this check does
        not hold against the object, and only because nothing was ever asked:
        there is no arrangement under which the implementation could have run,
        so the verdict would be about the machine. It skips, loudly, with the
        whole report -- and is not remembered, because installing what the
        machine lacked changes no cache key.
        """
        # Not `= {}` in the signature: this check writes to `test_ctx`, and a
        # mutable default is one dict shared by every call that omits one. The
        # same note `CaeTest.test` carries.
        if test_ctx is None:
            test_ctx = {}

        try:
            config = self._config(shape)
        except pc_cam.CamConfigError as e:
            # The object asked to be cut and got the request wrong. A failure of
            # the package rather than of the object, and saying so here is how a
            # user finds out without running `pc cam`.
            return self.failed(shape, "%s", e)

        if config is None:
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        try:
            # Resolved separately from running it, so that failing to resolve
            # reads differently from failing to run: a name that resolves to
            # nothing is a configuration to correct, and an implementation that
            # will not run is a machine to equip. Both halves are asked --
            # whether the package resolves, and whether it declares the file
            # type with the `extension:` a route needs -- because neither
            # becomes true or false depending on what is installed here.
            options_project, format_name = shape._route_implementation(ctx, declared=config.implementation)
            shape.cam_getopts(ctx, format_name, ctx.get_project(shape.project_name), None, options_project, None)
        except Exception as e:
            return self.failed(shape, "the 'cam' implementation could not be resolved: %s", e)

        implementation = "%s:%s" % (options_project.name, format_name)
        # Into a directory of this check's own, removed whatever happens. A
        # route left beside the package would be the file `pc cam` writes, with
        # nothing to say it came from a test -- see the module docstring.
        output_dir = tempfile.mkdtemp(prefix="partcad-cam-test-")
        try:
            result = await shape.route_async(ctx, output_dir=output_dir)
        except pc_cam.CamConfigError as e:
            return self.failed(shape, "%s", e)
        except pc_runtime.SandboxUnavailable as e:
            # The implementation never started, so it has nothing to say and the
            # verdict would be about this machine. Not remembered: provisioning
            # a sandbox changes no cache key, so a remembered skip would outlive
            # its reason.
            test_ctx[self.NOT_CACHEABLE] = True
            return self.skipped(
                shape,
                "%s",
                pc_cam.dysfunction_report(
                    "%s:%s" % (shape.project_name, shape.name),
                    implementation,
                    e,
                    remedy=pc_cam.NO_RUNTIME_REMEDY,
                ),
            )
        except Exception as e:
            # Asked, and no route. A failure whatever the reason, because the
            # object asked to be cut and nothing came out. Reported as
            # `route_async` wrote it -- which implementation was asked, what it
            # said, which machine -- so that `pc cam` and `pc test -f cam` say
            # the same thing about the same object. Anything arriving without a
            # report already on it gets one here.
            #
            # Not remembered, for the reason `CaeTest` does not remember its
            # own: this is the one verdict here that can be about the machine
            # rather than about the object, and nothing in the key describes the
            # machine.
            test_ctx[self.NOT_CACHEABLE] = True
            report = (
                str(e)
                if isinstance(e, pc_cam.CamFailed)
                else pc_cam.dysfunction_report("%s:%s" % (shape.project_name, shape.name), implementation, e)
            )
            return self.failed(shape, "%s", report)
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

        # `route_async` already refuses a path that was not written, so reaching
        # here means there is a file. What is worth saying is how big the job
        # turned out to be: a route that is one pass long when the part is 18 mm
        # thick is the kind of thing a reader notices and a check cannot.
        self.debug(shape, "Routed by %s: %s", implementation, json.dumps(result.get("stats") or {}, sort_keys=True))
        return self.passed(shape)
