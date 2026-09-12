#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
# Created: 2026-09-09
#
# Licensed under Apache License, Version 2.0.
#

"""The build backend: setuptools, plus a refusal to ship a wheel without the skills.

`src/partcad/ai_agents/skills` and `src/partcad/ai_agents/plugin.json` are
symlinks into `ai-agents/`, which is what puts the AI agent skills in the wheel
without keeping a second copy of them (see `ai-agents/README.md`). A checkout
where git did not materialize a symlink has, in its place, a small text file
holding the path the symlink pointed at -- and that is where this fails quietly
rather than loudly:

    skills/**/*  ->  []                 nothing matches a file named `skills`
    plugin.json  ->  52 bytes of path   matches, and is copied as content

So the wheel builds, installs, imports, runs `pc version`, and has no skills in
it at all; `pc init` then installs nothing, on every machine that wheel reaches.
Windows is where this happens -- Git for Windows checks symlinks out as text
files unless `core.symlinks` is on -- but it is not only Windows: GitHub's
source *zip* exports do the same thing on every platform, so
`pip install <that zip>` has the same hole.

This backend is `setuptools.build_meta` with one precondition in front of the
two hooks that produce a redistributable artifact. It is not a build step and
it copies nothing: it looks at what setuptools is about to package and refuses
if the skills are not there to package.

`build_editable` is deliberately *not* guarded. An editable install reads the
working tree as it is, so nothing is frozen into an artifact that outlives the
checkout, and refusing there would fail `poetry install` -- the whole
development environment -- over a data file the developer can fix with one
`git config`.
"""

import json
import os

# Everything a PEP 517 frontend may call. The hooks not named below are
# re-exported unchanged, which is the point: this is setuptools, with a
# precondition, and the day setuptools grows a hook it should arrive here
# without this file being edited.
from setuptools.build_meta import *  # noqa: F401,F403
from setuptools.build_meta import build_sdist as _build_sdist
from setuptools.build_meta import build_wheel as _build_wheel
from setuptools.command.egg_info import manifest_maker

# Relative to the project root, which is the directory a PEP 517 build runs in.
_PACKAGE = os.path.join("src", "partcad", "ai_agents")
_SKILLS = os.path.join(_PACKAGE, "skills")
_MANIFEST = os.path.join(_PACKAGE, "plugin.json")

# What a checkout that dropped the symlinks should be told to do. The cause is
# named as well as the cure: whoever sees this is as likely to be installing
# from a source zip, where `core.symlinks` is not the answer and the sdist is.
_ADVICE = """
This is what a checkout looks like when git did not materialize the symlinks in
"%s" (Git for Windows does this unless "core.symlinks" is on, and a GitHub
source zip does it everywhere). The wheel would build without the skills in it,
install cleanly, and leave "pc init" with nothing to install.

    git config core.symlinks true
    git checkout -- .

Or build from an sdist, where these are ordinary files.
""" % _PACKAGE


# The sdist template, which lives beside this file rather than at the top of the
# repository. `MANIFEST.in` is a name setuptools resolves against the project
# root and offers no setting for: `[sdist] template` in a `setup.cfg` does not
# reach it, because the file list is built by `egg_info`'s `manifest_maker`
# rather than by `sdist`, and that reads the class attribute below.
#
# It is one line, and the failure mode if a future setuptools stops honouring it
# is loud rather than silent: the sdist loses this backend, and the wheel built
# from that sdist fails immediately on a `backend-path` that does not exist.
manifest_maker.template = os.path.join("dev-tools", "MANIFEST.in")


def _skills():
    """Every skill that would go into the artifact, by directory name."""
    if not os.path.isdir(_SKILLS):
        return []
    return sorted(name for name in os.listdir(_SKILLS) if os.path.isfile(os.path.join(_SKILLS, name, "SKILL.md")))


def _check_the_skills_are_there():
    """Raise unless the AI agent skills are real files this build can package.

    Both halves are checked for what they are rather than for existing: an
    unmaterialized symlink *exists*, as a file containing a path, and the
    manifest one is a file either way -- which is why it is parsed.
    """
    problems = []

    if not os.path.isdir(_SKILLS):
        problems.append("%s is not a directory" % _SKILLS)
    elif not _skills():
        problems.append("%s holds no <name>/SKILL.md" % _SKILLS)

    try:
        with open(_MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if not isinstance(manifest, dict) or "name" not in manifest:
            problems.append("%s is not a plugin manifest" % _MANIFEST)
    except FileNotFoundError:
        problems.append("%s is missing" % _MANIFEST)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        problems.append("%s does not parse as JSON (%s)" % (_MANIFEST, e))

    if not problems:
        return

    raise SystemExit(
        "Refusing to build: the AI agent skills would not be in the artifact.\n\n  "
        + "\n  ".join(problems)
        + "\n"
        + _ADVICE
    )


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    """`setuptools.build_meta.build_wheel`, once the skills are known to be there."""
    _check_the_skills_are_there()
    return _build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    """`setuptools.build_meta.build_sdist`, once the skills are known to be there.

    An sdist is the other artifact that outlives the checkout, and the one a
    wheel gets built from later -- an sdist without the skills produces a wheel
    without them, on a machine where nothing is wrong.
    """
    _check_the_skills_are_there()
    return _build_sdist(sdist_directory, config_settings)
