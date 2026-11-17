#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the IDE's Revisions tab is drawn from: a package's history, and an object compared with one of its revisions.

The list is the commits that changed the package (see
'package_versions.revisions'), newest first. A package in no repository -- or in
one where nothing of it was ever committed -- has none, and is "not published
yet".

A comparison is of two texts, the object as the context holds it now and the
same object loaded at the revision ('<package>@<sha>:<name>', see
'package_versions'), each written out the way 'pc copy' would write it
('partcad.serialize') -- so what differs is what the object *means*, and two
spellings of one declaration compare equal. A package is compared by its
'partcad.yaml' as Jinja2 rendered it when PartCAD read it
('ProjectLocal.rendered_config'): the very text PartCAD parsed, rather than a
second rendering of it that could come out otherwise.

The comparison is made here rather than in the IDE, as rows of a side-by-side
view (see 'side_by_side'), because Python has a line differ and the webview has
no business shipping one.
"""

import difflib
import typing

from . import package_versions
from . import revision as pc_revision
from . import serialize

# The kind a comparison of a whole package is asked for with.
PACKAGE = "package"


def current_project(ctx, project):
    """The package without a revision that 'project' is, or is a revision of; 'project' itself where there is none."""
    if project is None:
        return None
    name = package_versions.unversioned(project.name)
    if name == project.name:
        return project
    return ctx.get_project(name) or project


def history(ctx, project) -> dict:
    """{'package', 'published', 'head', 'revisions'} of the package 'project' is (or is a revision of)."""
    current = current_project(ctx, project)
    repository = package_versions.repository_of(current.config_dir) if current is not None else None
    revisions = package_versions.revisions(repository) if repository is not None else []
    return {
        "package": current.name if current is not None else None,
        "published": bool(revisions),
        "head": repository.head() if repository is not None else None,
        "revisions": revisions,
    }


def object_text(project, kind: str, name: typing.Optional[str]) -> typing.Optional[str]:
    """The text an object -- or with 'PACKAGE', a whole package -- is compared by; None where there is no such thing."""
    if project is None:
        return None
    if kind == PACKAGE:
        return getattr(project, "rendered_config", None)
    try:
        return serialize.yaml_text(name, serialize.declaration(project, kind, name))
    except ValueError:
        return None


def side_by_side(left: typing.Optional[str], right: typing.Optional[str]) -> list:
    """The rows of a side-by-side comparison of two texts.

    One row per line of either side: {'tag', 'left', 'right', 'leftLine',
    'rightLine'}, where 'tag' is 'equal', 'replace' (a line changed: both
    sides), 'delete' (on the left only) or 'insert' (on the right only), and a
    side with no line in a row is None there. Lines are numbered from 1.
    """
    a = (left or "").splitlines()
    b = (right or "").splitlines()
    rows = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(_row("equal", a, b, i1 + offset, j1 + offset))
        elif tag == "replace":
            for offset in range(max(i2 - i1, j2 - j1)):
                i = i1 + offset if i1 + offset < i2 else None
                j = j1 + offset if j1 + offset < j2 else None
                if i is not None and j is not None:
                    tag_here = "replace"
                else:
                    tag_here = "delete" if j is None else "insert"
                rows.append(_row(tag_here, a, b, i, j))
        elif tag == "delete":
            for i in range(i1, i2):
                rows.append(_row("delete", a, b, i, None))
        elif tag == "insert":
            for j in range(j1, j2):
                rows.append(_row("insert", a, b, None, j))
    return rows


def _row(tag: str, a: list, b: list, i, j) -> dict:
    return {
        "tag": tag,
        "left": a[i] if i is not None else None,
        "right": b[j] if j is not None else None,
        "leftLine": i + 1 if i is not None else None,
        "rightLine": j + 1 if j is not None else None,
    }


def compare(ctx, project, kind: str, name: typing.Optional[str], revision: str) -> dict:
    """The object now and at 'revision', side by side: {'revision', 'short', 'left', 'right', 'same', 'rows'}.

    The revision is the left side and the context as it is now the right, the
    way a change reads: from what it was to what it is. A side where the object
    is not declared says so ('missing') and is compared as empty.
    """
    current = current_project(ctx, project)
    if current is None:
        raise ValueError("The package is not loaded")
    versioned_name = package_versions.versioned_name(current.name, revision)
    at_revision = ctx.get_project(versioned_name)
    if at_revision is None:
        raise ValueError("%s could not be loaded" % versioned_name)
    # Said by its commit, whatever it was asked by: a downloaded copy answering
    # for its own commit knows it from its repository (see 'revision').
    sha = (
        getattr(at_revision, "revision_sha", None)
        or pc_revision.package_revision(at_revision)
        or package_versions.split(versioned_name)[1]
    )
    left = object_text(at_revision, kind, name)
    right = object_text(current, kind, name)
    return {
        "package": current.name,
        "revision": sha,
        "short": package_versions.short(sha),
        "loaded": at_revision.name,
        "left": {"label": package_versions.short(sha), "missing": left is None},
        "right": {"label": "Current", "missing": right is None},
        "same": (left or "") == (right or ""),
        "rows": side_by_side(left, right),
    }
