#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the host's directories appear inside the ``docker`` sandbox.

The rule is that they appear where they already are. The context root, the
internal state directory and PartCAD's own installation are bind-mounted at the
paths they have outside, so a path in a log line, in an exception, in a cached
artifact or in a file a solver wrote means the same thing on both sides of the
container boundary, and nothing has to be translated on the way in or read back
differently on the way out.

That is worth more than it sounds. The sandbox directory itself lives under the
internal state directory, so a virtual environment created inside the container
is at the path the host knows it by: what is installed into it, what is cached
about it and what locks it all agree without anyone translating. (Its
``pyvenv.cfg`` still points at the image's interpreter, which the host does not
have -- that environment is only ever run over there, which is the point of
naming it after the image.) A traceback names a file the user can open, and the
whole class of bug where a path is rewritten in one place and not another does
not arise.

Windows is the exception, and it has to be: ``C:\\Users\\you`` is not a path a
Linux container can have. There a drive letter becomes a top-level directory the
way Docker Desktop mounts it -- ``C:\\Users\\you`` as ``/c/Users/you`` -- which
is the one place PartCAD translates, and the reason ``translate()`` exists at
all rather than being an identity nobody would write down.
"""

import os
import re
from typing import Optional

# 'C:\...' or 'c:/...' at the very start, and nothing else. A path that does not
# match is either already POSIX or is a UNC path, and neither is a drive letter
# to map.
_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")


class UnmountablePath(Exception):
    """A host path that cannot be given to a container.

    Raised rather than mangled: a bind mount silently pointing at the wrong
    place is a sandbox that renders the wrong file, and a UNC path quietly
    turned into something under '/' would be exactly that.
    """


def translate(host_path: str, windows: Optional[bool] = None) -> str:
    """The path ``host_path`` has inside the container.

    Itself, everywhere but Windows. ``windows`` overrides the detection, which
    is what lets the mapping be tested on the platform it is not used on -- the
    only platform where anybody would notice it is wrong is the one where CI is
    slowest to tell you.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return host_path

    if host_path.startswith("\\\\") or host_path.startswith("//"):
        raise UnmountablePath(
            "'%s' is a network path, which cannot be bind-mounted into a container. "
            "Use a path on a local drive, or the 'remote' sandbox, which sends the files rather "
            "than mounting them." % host_path
        )

    matched = _DRIVE.match(host_path)
    if not matched:
        raise UnmountablePath(
            "'%s' does not begin with a drive letter, so there is no way to say where it goes "
            "inside a container. Absolute paths only." % host_path
        )

    drive = matched.group(1).lower()
    rest = host_path[matched.end() :].replace("\\", "/")
    return "/%s/%s" % (drive, rest) if rest else "/%s" % drive


def _comparable(path: str, windows: bool) -> str:
    """``path`` in the form two of them are compared in.

    Windows accepts both separators and ignores case, so ``C:\\Work``,
    ``C:/work`` and ``c:\\WORK`` are one directory and have to compare as one.
    Everything that decides something about a *pair* of paths goes through
    here -- whether one contains another, whether an argument sits under a
    mount -- because a rule applied in one of those places and not the other is
    a rule with a hole in it, and both holes failed the same way: a directory
    mounted twice because neither was seen to contain the other, or a path
    reaching the container unrewritten.

    Off Windows a path is compared as it is written. Case is significant there,
    and a backslash is a legal character in a file name rather than a
    separator -- folding either would merge two directories that are two.
    """
    return path.replace("\\", "/").lower() if windows else path


def _tidy(path: str) -> str:
    """``path`` without a trailing separator, unless that is all it is.

    Deliberately not ``os.path.abspath``: these paths are already absolute, and
    on Windows they are absolute in a way the host's ``os.path`` does not
    recognise when the host is not Windows -- which is every machine this is
    tested on.
    """
    stripped = path.rstrip("/\\")
    return stripped if stripped else path[:1]


def mounts(host_paths, windows: Optional[bool] = None) -> dict:
    """The bind mounts for these host directories, as the docker SDK wants them.

    Deduplicated and with nested paths dropped: mounting both a directory and
    something inside it gives the container two views of the same files, and
    which one a write lands in is then up to the order Docker happened to apply
    them in. The outermost wins, which is the one that contains the other.

    All writable. Mounting the installation read-only was tried and taken back
    out: it bought little -- a wrapper is read and executed, and what it writes
    goes to the cache or back over its own protocol -- and cost a second thing
    that could differ between two containers of one image, on a mount contract
    that is a stopgap rather than a boundary. The boundary is the container.
    """
    if windows is None:
        windows = os.name == "nt"

    kept = []
    for path in sorted({_tidy(p) for p in host_paths}, key=len):
        if not any(contains(outer, path, windows) for outer in kept):
            kept.append(path)

    return {path: {"bind": translate(path, windows), "mode": "rw"} for path in kept}


def contains(outer: str, inner: str, windows: Optional[bool] = None) -> bool:
    """Whether ``inner`` is ``outer`` or sits under it.

    On Windows neither the case nor the separator decides: 'C:\\Users\\you' and
    'c:/users/you/.partcad' are a parent and a child. Comparing them literally
    meant they were not seen as one -- so both were mounted, which is the two
    views of one directory 'mounts' exists to prevent. See '_comparable'.

    The trailing separator is checked so that a textual prefix is not mistaken
    for a parent: '/srv/pkg' does not contain '/srv/pkg-other'.
    """
    if windows is None:
        windows = os.name == "nt"
    outer, inner = _comparable(outer, windows), _comparable(inner, windows)
    if outer == inner:
        return True
    if windows:
        return inner.startswith(outer + "/")
    return inner.startswith(outer + "/") or inner.startswith(outer + "\\")


def rewrite(argument: str, host_paths, windows: Optional[bool] = None) -> str:
    """``argument`` with any mounted host path in it replaced by its container path.

    A no-op everywhere but Windows, where the interpreter is handed a command
    line built out of host paths and the container knows them under other names.
    Only whole path prefixes are replaced, longest first, so a mount nested
    inside another cannot half-rewrite a path belonging to the outer one.

    This covers the command line and the working directory. It does **not**
    reach inside what is written to the process's standard input, which for a
    PartCAD wrapper is one serialized request that may carry paths of its own --
    that is why the `remote` sandbox, which has the same problem in a harder
    form, translates at the protocol level instead.
    """
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return argument

    for host in sorted({_tidy(p) for p in host_paths}, key=len, reverse=True):
        # Neither case nor separator decides here either: an argument built
        # with one and a mount recorded with the other name one directory.
        # '_comparable' substitutes character for character, so the offset
        # below still indexes the original.
        if _comparable(argument, windows).startswith(_comparable(host, windows)):
            return translate(host, windows) + argument[len(host) :].replace("\\", "/")
    return argument
