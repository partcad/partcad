#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Check that a package's software says which file it is.

Every software object is a file, and there are two ways a package can be
specific about *which* file:

  * The package carries it. The file is content of the repository, so the
    revision of the package identifies it exactly - which is what a bill of
    materials records beside every software line item.
  * The package pulls it in ('fileFrom'). Nothing about the package identifies
    the file then: the URL serves whatever it serves at the moment it is
    fetched, and the same package revision can produce a different image
    tomorrow. Only a 'fileHash' closes that, so one is required.

That is the whole rule: **in the repository, or pinned**. A firmware image is
the one part of a product that can be swapped without leaving a trace in the
geometry, so a digital thread that cannot say which one went in is not a thread
at all.

The rule itself is 'file_factory.unreproducible_reason()', which the
manufacturing test applies to the file a part is built from as well. What this
check adds is *when* it is answered: at lint time, on the declaration, before
anything has been built or fetched.
"""

import os

from ..context import Context
from ..project import Project
from ..file_factory import unreproducible_reason
from .lint import Linting, LintingReport, Severity


class SoftwareLinting(Linting):
    """The 'in the repository, or pinned' check, per package."""

    def get_targets(self, ctx: Context, package: Project) -> list[str]:
        # The package's own configuration is what declares its software, so it
        # is both the thing being checked and what the result is cached against.
        # Only when it is a real file: a plugin-backed package has no
        # 'partcad.yaml' on disk, and there would be nothing to hash.
        target = os.path.join(package.config_dir, "partcad.yaml")
        return [target] if os.path.isfile(target) else []

    async def validate(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> LintingReport:
        lint_result = LintingReport(package.name)

        try:
            names = sorted(package.object_names("software"))
        except Exception as e:  # pylint: disable=broad-except
            lint_result.add(Severity.FAILED, "Failed to enumerate the software of the package: %s" % e)
            return lint_result

        for name in names:
            config = package.get_software_config(name) or {}
            # The same rule the manufacturing test applies, read from the same
            # place, so that the check and the test cannot come to different
            # answers about one declaration.
            if unreproducible_reason(config) is None:
                continue
            lint_result.add(
                Severity.FAILED,
                "software '%s' is fetched with 'fileFrom: %s' and declares no 'fileHash', "
                "so nothing says which file it is. Either commit the file to this package "
                "and point 'path' at it, or add 'fileHash: <algorithm>:<digest>'." % (name, config.get("fileFrom")),
            )

        return lint_result
