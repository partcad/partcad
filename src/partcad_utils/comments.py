#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Comments: the discussion a package and each of its objects carry, as every reader reads it.

Any declaration -- a part, an assembly, a scene, a sketch, an interface,
software, a provider, a repository, a part or sketch type, a colour, a material,
a finish -- and the package itself may say ``comments:``: a list of *threads*,
each an ordered list of comments, oldest first::

    parts:
      bracket:
        type: step
        comments:
          - - ref: face:12
              name: Ada Lovelace
              date: 2026-11-19 14:31:01 UTC
              text: This face is **too thin** to print.
              attachments: [photos/bracket-crack.jpg]
            - ref: face:12
              name: Charles Babbage
              date: 2026-11-19 15:02:44 UTC
              text: Thickened to 2 mm.

Each comment has ``name`` (who wrote it: their ``git config user.name``),
``date`` (UTC, to the second, as :data:`DATE_FORMAT` writes it), ``text``
(Markdown) and, where it has any, ``attachments`` (files, relative to the
package). ``ref`` says what *inside* the object it is about, in the terms of the
object's kind (see :func:`describe_ref`), and a comment with none is about the
object as a whole. What a thread is about is the ``ref`` of its first comment
(:func:`thread_ref`); a reply carries the same one.

A comment says nothing about what an object *is*: nothing PartCAD builds,
caches or qualifies reads it, and ``comments`` is among the keys a shape's cache
key leaves out (``partcad.shape._NON_GEOMETRIC_CONFIG_KEYS``), so that writing
one costs no rebuild.

It lives here rather than in ``partcad`` because both ends read it: the daemon,
which lists comments and writes them into a ``partcad.yaml``
(``comment.list``/``comment.add``), and every client, which composes the
comment it sends -- the name is the *client's* git identity, never the
daemon's, since a daemon can be on somebody else's machine -- and the editor
extension, whose TypeScript twin of the reference grammar is
``ide/vscode/src/webview/comments.ts``. Stdlib only, like the rest of
``partcad_utils``.
"""

import datetime
import re
import typing

# The key a declaration and a package carry their threads under.
KEY = "comments"

# How a comment's date is written: UTC, human readable, to the second.
DATE_FORMAT = "%Y-%m-%d %H:%M:%S UTC"
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} UTC$")

# The two kinds of element a part's or a sketch's comment can be pinned to, and
# how a reference to one is spelled: 'face:12', 'edge:3'. Numbered as OCCT
# numbers a shape's faces and edges ('TopExp.MapShapes'), from one: the
# numbering a topology finding's "face 3" uses, and the one a STEP or BREP file
# of the shape keeps.
FACE = "face"
EDGE = "edge"
ELEMENTS = (FACE, EDGE)
REF_SEPARATOR = ":"

# The kinds whose comments point at a face or an edge, and the kinds whose
# comments point at a link -- a name the object addresses one of its children
# by, or the names down to something deeper, joined with ':' the way a port of
# something inside is named ('shape_ports.qualify').
ELEMENT_KINDS = ("part", "sketch")
LINK_KINDS = ("assembly", "scene")

# The kinds whose comments point at an entry point of a script: the plugins.
PLUGIN_KINDS = ("provider", "repository", "partType", "sketchType")

_ELEMENT_REF = re.compile(r"^(%s):([1-9][0-9]*)$" % "|".join(ELEMENTS))


def date(moment: typing.Optional[datetime.datetime] = None) -> str:
    """When a comment was written, as one is dated: now, unless ``moment`` says otherwise.

    A naive ``moment`` is taken to be in UTC already.
    """
    if moment is None:
        moment = datetime.datetime.now(datetime.timezone.utc)
    elif moment.tzinfo is not None:
        moment = moment.astimezone(datetime.timezone.utc)
    return moment.strftime(DATE_FORMAT)


def element_ref(element: str, index: int) -> str:
    """The reference to one face or edge of a shape: ``element_ref("face", 12)`` is 'face:12'."""
    if element not in ELEMENTS:
        raise ValueError("A comment points at a %s, not at a '%s'" % (" or an ".join(ELEMENTS), element))
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise ValueError("Faces and edges are numbered from one: %r" % (index,))
    return "%s%s%d" % (element, REF_SEPARATOR, index)


def parse_element_ref(ref) -> typing.Optional[typing.Tuple[str, int]]:
    """``(element, index)`` for a reference to a face or an edge ('face:12'), or None for any other."""
    if not isinstance(ref, str):
        return None
    found = _ELEMENT_REF.match(ref.strip())
    if found is None:
        return None
    return found.group(1), int(found.group(2))


def describe_ref(ref) -> str:
    """What a reference points at, as a sentence says it: 'face 12', 'link#2', or 'the whole object'."""
    if not ref:
        return "the whole object"
    element = parse_element_ref(ref)
    if element is not None:
        return "%s %d" % element
    return str(ref)


def thread_ref(thread) -> typing.Optional[str]:
    """What a thread is about: the 'ref' of its first comment, or None for the object as a whole."""
    if not thread:
        return None
    first = thread[0]
    ref = first.get("ref") if isinstance(first, dict) else None
    return ref if isinstance(ref, str) and ref else None


def _text(value) -> str:
    """A field as text: a date YAML read as a timestamp written back the way a comment's date is."""
    if isinstance(value, datetime.datetime):
        return date(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    return "" if value is None else str(value)


def normalized_entry(entry) -> typing.Optional[dict]:
    """One comment as a reader takes it: its fields as text, or None for something that is not a comment."""
    if not isinstance(entry, dict):
        return None
    result = {}
    ref = entry.get("ref")
    if ref is not None and ref != "":
        result["ref"] = _text(ref)
    for key in ("name", "date", "text"):
        result[key] = _text(entry.get(key))
    attachments = entry.get("attachments")
    if isinstance(attachments, (list, tuple)):
        files = [_text(item) for item in attachments if item is not None and _text(item)]
        if files:
            result["attachments"] = files
    return result


def threads(declaration) -> typing.List[typing.List[dict]]:
    """The threads a declaration (or a package's configuration) carries, as readers take them.

    Whatever is not a thread of comments is passed over rather than refused:
    the linter is what says a ``comments:`` is malformed (the schema), and a
    reader that refused a whole object over it would hide the object's other
    threads. Each thread keeps its position, so that the index a reply names
    (``comment.add``'s ``thread``) is the index of that thread in the file;
    a thread that has no comment left in it is an empty list in its place.
    """
    if not isinstance(declaration, dict):
        return []
    section = declaration.get(KEY)
    if not isinstance(section, (list, tuple)):
        return []
    result = []
    for thread in section:
        if not isinstance(thread, (list, tuple)):
            result.append([])
            continue
        result.append([entry for entry in (normalized_entry(item) for item in thread) if entry is not None])
    return result


def entry(
    name: str,
    text: str,
    ref: typing.Optional[str] = None,
    attachments: typing.Optional[typing.Sequence[str]] = None,
    when: typing.Optional[str] = None,
) -> dict:
    """One comment, as it is written: refused, with ValueError, where it would not be one.

    ``when`` is its date as :data:`DATE_FORMAT` writes it, and now when absent.
    The fields are in the order a reader reads them: what it is about, who,
    when, what, and what goes with it.
    """
    name = (name or "").strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError(
            "A comment says who wrote it, and nobody is named: set it with 'git config --global user.name \"Your Name\"'"
        )
    if not isinstance(text, str) or not text.strip():
        raise ValueError("A comment says something, and this one is empty")
    result = {}
    if ref is not None:
        if not isinstance(ref, str):
            raise ValueError("What a comment is about is named by a string, not by %r" % (ref,))
        ref = ref.strip()
        if ref:
            result["ref"] = ref
    result["name"] = name
    if when is None:
        when = date()
    elif not isinstance(when, str) or not DATE_PATTERN.match(when):
        raise ValueError("A comment is dated in UTC to the second, '%s': not %r" % (date(), when))
    result["date"] = when
    result["text"] = text.rstrip()
    files = []
    for item in attachments or ():
        if not isinstance(item, str) or not item.strip():
            raise ValueError("An attachment is named by its file name, not by %r" % (item,))
        files.append(item.strip().replace("\\", "/"))
    if files:
        result["attachments"] = files
    return result


def author(directory: typing.Optional[str] = None) -> typing.Optional[str]:
    """Who is writing a comment, as git on *this* machine says: ``git config user.name``, or None.

    Asked in ``directory`` -- the package, where a repository-local identity
    applies -- and in the user's own configuration otherwise. For a client
    only: a daemon can be on somebody else's machine, and its git configuration
    names whoever runs it there.
    """
    import os
    import subprocess

    cwd = directory if directory and os.path.isdir(directory) else None
    try:
        found = subprocess.run(
            ["git", "config", "user.name"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = found.stdout.strip() if found.returncode == 0 else ""
    return name or None
