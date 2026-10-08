#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Checking the files this machine is editing, without asking a daemon.

An ASSY file and a `partcad.yaml` are both Jinja2 templates that render to YAML
and then have to match a schema. Checking one is pure text work: no package
graph, no CAD runtime, no context -- and the file in question is often not on
disk at all, but a buffer an editor has not saved yet. Sending that to the
daemon would be shipping the client's own file across a wire to have it read
back, and would leave the editor silent exactly when the daemon is down or the
package fails to load, which is usually *because* of the file being typed into.
A `partcad.yaml` is the sharpest case of that: the file that decides whether the
package loads at all is the one a daemon cannot tell you about while it is
broken.

So every client checks locally, through here: `pc lint --file` in the CLI
process, and the VS Code extension by running that same command. The check
itself is `partcad_utils.assy_lint`, shared with the daemon-side package lint so
an editor and CI cannot disagree about a file.

Three things about a file are not in it, and have to be worked out before it
can be checked: the values it renders with (an ASSY file's parameters, from its
declaration), whether an **ASSY** file is an **assembly** or a **scene** (a
scene is checked against the same schema with ``how`` forbidden, see
`partcad.scene`), and whether what it describes is marked manufacturable. They
are properties of what points at the file, so they are answered best effort,
from the `partcad.yaml` files around it, by `partcad_utils.lint_context` -- the
same code the daemon asks, so the two cannot answer differently. A caller that
knows the flavor better says so instead. A `partcad.yaml` has no flavor: nothing
points at a package configuration, and there is only one schema for it.
"""

from partcad_utils import assy_lint, lint_context


class FileReport:
    """The findings for one file, and how it was named on the way in."""

    def __init__(self, path: str, diagnostics: list, checked: bool, flavor: str = None):
        self.path = path
        self.diagnostics = diagnostics
        # False when nothing here knows how to check this kind of file, which is
        # not the same as "checked and clean" and is why callers can tell the
        # two apart (`pc lint --file notes.txt` should say so).
        self.checked = checked
        # What the file was read as. Reported back so that a caller can see
        # which way the detection went, and an editor can show it. None where
        # the question does not arise -- a `partcad.yaml`, or a file type
        # nothing here checks -- rather than a flavor nothing chose.
        self.flavor = flavor

    @property
    def failed(self) -> bool:
        return any(d.severity == assy_lint.SEVERITY_ERROR for d in self.diagnostics)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "checked": self.checked,
            "flavor": self.flavor,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


def detect_flavor(path: str) -> str:
    """Whether ``path`` is pointed at by a scene, best effort.

    Returns `FLAVOR_SCENE` when at least one scene names this file and no
    assembly does, and `FLAVOR_ASSEMBLY` otherwise -- including whenever the
    answer cannot be worked out at all.

    **Best effort, and it leans one way on purpose.** Reading a scene as an
    assembly costs a missed finding (a ``how:`` nobody objected to); reading an
    assembly as a scene costs a false error on correct code, which is worse in
    an editor and worse in CI. So anything unresolved -- no package found, a
    `partcad.yaml` that will not parse, a declaration whose path only resolves
    with parameters -- lands on the assembly schema. The search itself is
    `partcad_utils.lint_context`, shared with the daemon.
    """
    return lint_context.describe(path).flavor or assy_lint.FLAVOR_ASSEMBLY


def check_file(
    path: str, text: str = None, flavor: str = None, include_paths=(), parameter_overrides=None
) -> FileReport:
    """Check one file, or ``text`` as its unsaved content.

    The file is checked as it renders, with the values PartCAD would render it
    with, worked out from the `partcad.yaml` files around it -- see
    `partcad_utils.lint_context`, which also answers whether it is read as an
    assembly or a scene and whether the rules for what is to be made apply.
    ``flavor`` overrides the first of those (see `assy_lint.FLAVORS`); it is
    ignored for a `partcad.yaml`, which has one schema and no flavor.
    ``include_paths`` are more directories to include from, and
    ``parameter_overrides`` the values that replace declared defaults, by object
    -- see `lint_context.describe`.

    Raises ``OSError`` if ``text`` is None and the file cannot be read: a caller
    that named a file it cannot open wants to hear about it.
    """
    if assy_lint.schema_name_for_file(path) is None:
        return FileReport(path, [], checked=False)
    if text is None:
        with open(path, "r", encoding="utf-8") as file:
            text = file.read()
    context = lint_context.describe(path, include_paths=include_paths, parameter_overrides=parameter_overrides)
    if assy_lint.is_assy_file(path) and flavor in assy_lint.FLAVORS:
        context.flavor = flavor
    schema = assy_lint.schema_for_file(path, context.flavor)
    return FileReport(path, context.check(text, schema), checked=True, flavor=context.flavor)


def check_files(paths, text: str = None, flavor: str = None, include_paths=(), parameter_overrides=None) -> list:
    """Check every path given. ``text`` supplies the content of a single path; the rest is as `check_file`."""
    paths = list(paths)
    if text is not None and len(paths) != 1:
        raise ValueError("content can only be supplied for a single file")
    # Paths are reported back exactly as they came in: a user who typed a
    # relative path wants to read one, and an editor that passed an absolute one
    # needs it back to match the document it asked about.
    return [check_file(path, text, flavor, include_paths, parameter_overrides) for path in paths]
