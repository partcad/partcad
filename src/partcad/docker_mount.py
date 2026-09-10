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


def _tidy(path: str) -> str:
    """``path`` without a trailing separator, unless that is all it is.

    Deliberately not ``os.path.abspath``: these paths are already absolute, and
    on Windows they are absolute in a way the host's ``os.path`` does not
    recognise when the host is not Windows -- which is every machine this is
    tested on.
    """
    stripped = path.rstrip("/\\")
    return stripped if stripped else path[:1]


def mounts(host_paths, windows: Optional[bool] = None, read_only=()) -> dict:
    """The bind mounts for these host directories, as the docker SDK wants them.

    Deduplicated and with nested paths dropped: mounting both a directory and
    something inside it gives the container two views of the same files, and
    which one a write lands in is then up to the order Docker happened to apply
    them in. The outermost wins, which is the one that contains the other.

    A path named in ``read_only`` is mounted 'ro'. That is for a directory the
    sandbox has to *read* and has no business writing -- PartCAD's own
    installation, which it runs the wrappers out of. Only a mount that survives
    deduplication in its own right can be read-only: a path swallowed by an
    outer mount is reached through that one, on that one's terms, which is the
    conservative answer rather than a surprising one -- the outer mount is the
    state directory or the package being worked on, both of which are writable
    by intent, and silently making either of them read-only because something
    read-only sits inside it would break the sandbox rather than protect it.
    """
    if windows is None:
        windows = os.name == "nt"

    # Compared the way 'contains' and 'rewrite' compare: case-insensitively on
    # Windows, where 'C:\PartCAD' and 'c:\partcad' are one directory. Matching
    # case-sensitively here would mean a path asked for read-only and spelled
    # differently came back 'rw' -- a sandbox given write access to something
    # the caller said it must not write, which is the one direction this must
    # not fail in.
    def _key(path: str) -> str:
        return path.lower() if windows else path

    read_only = {_key(_tidy(p)) for p in read_only}

    kept = []
    for path in sorted({_tidy(p) for p in host_paths}, key=len):
        if not any(contains(outer, path, windows) for outer in kept):
            kept.append(path)

    return {
        path: {"bind": translate(path, windows), "mode": "ro" if _key(path) in read_only else "rw"} for path in kept
    }


def contains(outer: str, inner: str, windows: Optional[bool] = None) -> bool:
    """Whether ``inner`` is ``outer`` or sits under it.

    Both separators count, whichever platform this is running on: a Windows
    path may be written with either, and the answer must not depend on where
    the question is asked.

    And on Windows, neither does the case. 'rewrite' already matches
    case-insensitively; comparing case-sensitively here meant 'C:\\Users\\you'
    and 'c:\\users\\you\\.partcad' were not seen as a parent and a child, so both
    were mounted -- the two views of one directory 'mounts' exists to prevent.
    """
    if windows is None:
        windows = os.name == "nt"
    if windows:
        outer, inner = outer.lower(), inner.lower()
    if outer == inner:
        return True
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
        # Case-insensitively, because Windows says 'C:' and 'c:' for one drive
        # and 'Users' and 'users' for one directory.
        if argument.lower().startswith(host.lower()):
            return translate(host, windows) + argument[len(host) :].replace("\\", "/")
    return argument
