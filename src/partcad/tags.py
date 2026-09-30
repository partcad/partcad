#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Context tags, and the ``unless`` condition that skips what cannot work here.

A *tag* is a short string naming something that is true of *here*: of the
machine PartCAD is running on, or of how it has been configured to work. The
context carries the set of tags true of itself (see ``Context.tags``), and any
declaration in a ``partcad.yaml`` -- the package itself, or one of its
sketches, parts, assemblies, providers, ... -- may name the tags it does not
work under::

    unless: [arm64]

The declaration is then skipped wherever one of those tags holds, with an
``INFO`` line saying so, instead of being loaded and failing at use.

``unless`` is a list of *clauses*, any one of which excludes (**OR**). A clause
is either a single tag, or a list of tags that must **all** hold together
(**AND**). That is what lets an exclusion be stated in terms of the machine and
its configuration at once::

    unless: [[arm, useDocker, useDockerKicad]]

-- "not on an Arm machine that is going to run KiCad in a container", which is
the KiCad example's actual condition and the case that prompted all of this:
KiCad's official container images are published for ``linux/amd64`` only, so
that sandbox cannot be pulled on an Arm host at all. Somebody who turned the
container off and has ``kicad-cli`` installed natively is not covered by the
clause and keeps the package. That is a property of the package, not a bug in
it, and a package saying so is better than every consumer of it discovering it
the hard way.

What is *not* here, deliberately, is the inverse condition ("only on"). A
declaration is expected to work everywhere; naming the exceptions keeps the
common case unwritten, and keeps a new platform from silently excluding
everything that was written before it existed. Nor is there a negation
*operator*: ``!useDocker`` is a tag in its own right, one the context carries
when that option is off, and ``!`` means nothing anywhere else. A tag is
matched, never evaluated.

The tags a context carries are these. First, what the machine is:

* **Architecture**, as ``platform.machine()`` says it, lowercased -- plus the
  canonical spelling and the family:

  - ``x86_64`` and ``amd64`` on 64-bit Intel/AMD (both, because the two
    spellings name the same thing and which one a host reports depends on the
    operating system);
  - ``arm64`` and ``aarch64`` on 64-bit Arm, plus the family tag ``arm``;
  - ``i386`` and ``x86`` on 32-bit Intel, plus the family tag ``x86``;
  - ``arm`` on 32-bit Arm, alongside the exact ``armv7l``/``armv6l``.

* **Operating system**: ``linux``, ``macos`` (also ``darwin``) or ``windows``.

* **Operating system and version**, ``<os>-<version>``:

  - on Linux, the distribution rather than the kernel, from
    ``/etc/os-release``: ``ubuntu`` and ``ubuntu-24.04``, plus whatever
    ``ID_LIKE`` names (``debian``), because "this needs a Debian" is the
    statement a package actually wants to make;
  - on macOS, ``macos-26`` and ``macos-26.1``;
  - on Windows, ``windows-11``.

Then, how PartCAD has been configured to work -- one tag per boolean option in
``CONFIG_TAGS``, named after the option and carried in one of two spellings:
``useDocker`` when it is on and ``!useDocker`` when it is off. Both spellings
exist so that either answer can be named; a package that cares which way an
option is set should not have to guess what "absent" meant.

These report the option **as configured**, not as it ends up applying:
``useDocker`` is a master switch over the others, so ``useDockerKicad`` and
``!useDocker`` can hold at once. It reads oddly until you want exactly that
distinction, and a package excluding itself usually does -- "the container was
asked for" and "the container will actually be used" are different questions.

Anything else the user wants to condition on is theirs to add, through the
``tags`` user configuration option (or ``PC_TAGS``).

Tags are matched case-insensitively and are carried in the spelling PartCAD
names them by, which is why ``useDocker`` is camelCase (it is an option name)
while ``arm64`` is not.
"""

import platform
from typing import Iterable, Optional

from . import logging as pc_logging

# The key a declaration names its exclusions under.
UNLESS_KEY = "unless"

# The boolean user-configuration options a context reports as tags, by the name
# they are configured under and the attribute holding what was configured. Each
# contributes exactly one tag: the option's name when it is on, and that name
# prefixed with '!' when it is off.
#
# Only options that decide *how the work gets done* belong here. That is what a
# package can meaningfully exclude itself on; the rest of the configuration
# (where things are cached, how loud the log is) says nothing about whether a
# design can be built, and putting it here would turn PartCAD's internals into a
# compatibility surface.
CONFIG_TAGS = (
    ("useDocker", "use_docker"),
    ("useDockerPython", "use_docker_python_declared"),
    ("useDockerKicad", "use_docker_kicad_declared"),
)


def _normalize_tag(value) -> str:
    """The one spelling a tag is compared under: stripped and lowercased."""
    return str(value).strip().lower()


def _arch_tags() -> set[str]:
    machine = _normalize_tag(platform.machine())
    if not machine:
        return set()

    tags = {machine}
    if machine in ("x86_64", "amd64", "x64"):
        tags.update(("x86_64", "amd64"))
    elif machine in ("aarch64", "arm64", "armv8b", "armv8l"):
        tags.update(("arm64", "aarch64", "arm"))
    elif machine in ("i386", "i486", "i586", "i686", "x86"):
        tags.update(("i386", "x86"))
    elif machine.startswith("arm"):
        tags.add("arm")
    return tags


def _linux_os_tags() -> set[str]:
    """The distribution's tags, which on Linux is what '<os>-<version>' means.

    'linux-6.8' would name the kernel, which is not what anybody conditions on;
    'ubuntu-24.04' is. Read from '/etc/os-release', the one thing every
    distribution agrees to publish. A container or an image without one (a
    'scratch'-based image, say) simply contributes no distribution tags.
    """
    try:
        release = platform.freedesktop_os_release()
    except (OSError, AttributeError):
        # No '/etc/os-release' (or a Python without the accessor, which none of
        # the versions PartCAD supports is). Not an error: the OS family tag
        # above still holds, and that is the tag most declarations name.
        return set()

    tags = set()
    distro = _normalize_tag(release.get("ID", ""))
    if not distro:
        return tags
    tags.add(distro)

    # 'ID_LIKE' is a space-separated list of the distributions this one is
    # derived from. Ubuntu says "debian", so 'unless: [debian]' covers both.
    for like in _normalize_tag(release.get("ID_LIKE", "")).split():
        if like:
            tags.add(like)

    version = _normalize_tag(release.get("VERSION_ID", ""))
    if version:
        tags.add("%s-%s" % (distro, version))
    return tags


def _macos_os_tags() -> set[str]:
    tags = {"macos", "darwin"}
    version = _normalize_tag(platform.mac_ver()[0])
    if not version:
        return tags

    parts = version.split(".")
    tags.add("macos-%s" % parts[0])
    if len(parts) > 1:
        tags.add("macos-%s.%s" % (parts[0], parts[1]))
    return tags


def _windows_os_tags() -> set[str]:
    tags = {"windows"}
    release = _normalize_tag(platform.win32_ver()[0])
    if release:
        tags.add("windows-%s" % release)
    return tags


def _os_tags() -> set[str]:
    system = _normalize_tag(platform.system())
    if system == "linux":
        return {"linux"} | _linux_os_tags()
    if system == "darwin":
        return _macos_os_tags()
    if system == "windows":
        return _windows_os_tags()
    # Something PartCAD has never run on. Report what it calls itself rather
    # than nothing, so that a package can still exclude it by name.
    return {system} if system else set()


def host_tags() -> set[str]:
    """Every tag true of the machine this process runs on."""
    return _arch_tags() | _os_tags()


def parse_tags(value) -> list[str]:
    """The tags in a user-supplied list, or in a whitespace/comma-separated string.

    Spelling is left as the user wrote it - matching is case-insensitive, so
    nothing is gained by folding it here and something is lost: these are shown
    back to the user by 'pc system status'.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return [tag for tag in (str(item).strip() for item in value) if tag]


def config_tags(user_config=None) -> set[str]:
    """How PartCAD is configured to work, as tags: 'useDocker' or '!useDocker'.

    An option this build does not have contributes nothing rather than
    defaulting to one answer or the other: neither 'useDocker' nor '!useDocker'
    is true of a PartCAD that has no such option, and claiming either would make
    a package exclude itself over a question that was never asked.
    """
    tags = set()
    for option, attribute in CONFIG_TAGS:
        value = getattr(user_config, attribute, None)
        if value is None:
            continue
        tags.add(option if value else "!" + option)
    return tags


def context_tags(user_config=None) -> set[str]:
    """The tag set a context starts with: this host's, this configuration's, and
    whatever the user adds on top."""
    tags = host_tags() | config_tags(user_config)
    extra = parse_tags(getattr(user_config, "tags", None))
    if extra:
        tags.update(extra)
    pc_logging.debug("Context tags: %s" % ", ".join(sorted(tags)))
    return tags


def parse_unless(value, where: str) -> list[list[str]]:
    """The clauses an ``unless`` declaration excludes on.

    Returns a list of clauses; a clause is a list of tags. A clause holds when
    **every** tag in it holds (AND), and the declaration is excluded when
    **any** clause holds (OR). So::

        unless: arm64                            -> [[arm64]]
        unless: [arm64, windows]                 -> [[arm64], [windows]]
        unless: [[arm, useDocker], macos]        -> [[arm, useDocker], [macos]]

    A single tag may be written on its own at either level, because
    ``unless: arm64`` is what a one-tag exclusion is written as by everybody who
    writes one, and a one-tag clause reads better as ``macos`` than ``[macos]``.

    Raises ``ValueError`` on anything else, including an empty clause: a clause
    with no tags holds vacuously, so it would exclude the declaration
    everywhere, which nobody writes on purpose. A misspelled *tag* cannot be
    caught -- a tag is any string, and the set of them is open -- but a
    misshapen declaration can be, and it has to be: an ``unless`` that silently
    means nothing is an exclusion that silently does not happen.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    elif not isinstance(value, (list, tuple)):
        raise ValueError("%s: '%s' must be a tag, or a list of tags and tag lists" % (where, UNLESS_KEY))

    clauses = []
    for item in value:
        if isinstance(item, str):
            item = [item]
        elif isinstance(item, (list, tuple)):
            item = list(item)
            if not item:
                raise ValueError("%s: '%s' must not contain an empty list of tags" % (where, UNLESS_KEY))
        else:
            raise ValueError("%s: '%s' must contain tags and lists of tags" % (where, UNLESS_KEY))
        for tag in item:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("%s: '%s' must contain non-empty tags" % (where, UNLESS_KEY))
        clauses.append([tag.strip() for tag in item])
    return clauses


def describe_clause(clause: Iterable[str]) -> str:
    """A clause as it goes into a message: 'arm64', or 'arm and useDocker'."""
    return " and ".join(clause)


def excluded_by(config, tags: Iterable[str], where: str) -> Optional[str]:
    """The clause that excludes this declaration here, or None if none does.

    Returned as the text of the clause rather than as a list, because every
    caller of this wants it for a message. The tags come back in the spelling
    the declaration used, which is the one the user will go looking for.

    'config' is a declaration's configuration object. A declaration written in
    the shorthand form (a bare string, e.g. a part declared as just its path)
    carries no keys and is therefore never excluded.
    """
    if not isinstance(config, dict):
        return None
    clauses = parse_unless(config.get(UNLESS_KEY), where)
    if not clauses:
        return None
    # Normalized here rather than held normalized on the context, so that the
    # tags a context reports stay in the spelling PartCAD names them by. Paid
    # for only by a declaration that has an 'unless' at all, which is why the
    # early return above comes first.
    present = {_normalize_tag(tag) for tag in tags}
    for clause in clauses:
        if all(_normalize_tag(tag) in present for tag in clause):
            return describe_clause(clause)
    return None
