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

One thing has to be decided before an **ASSY** file can be checked: whether it
is an **assembly** or a **scene**, because a scene is checked against the same
schema with ``how`` forbidden (see `partcad.scene`). That is not a property of
the file -- it is a property of what points at it -- so it is answered best
effort, by `detect_flavor` below, and a caller that knows better says so
instead. A `partcad.yaml` has no flavor: nothing points at a package
configuration, and there is only one schema for it.
"""

import os

import yaml

from partcad_utils import assy_lint

# How far up from the file the search for a package declaring it goes. A
# package's own directory is where it is normally declared; an ancestor package
# can declare it too, with a `path:` that reaches down. Bounded because this
# runs on every keystroke in an editor, and because walking to the filesystem
# root would start reading other people's packages.
MAX_PACKAGE_DEPTH = 8

# The sections that may point at an ASSY file, and the flavor each one makes it.
_SECTIONS = {
    "assemblies": assy_lint.FLAVOR_ASSEMBLY,
    "scenes": assy_lint.FLAVOR_SCENE,
}

# The object types within those sections that name an ASSY file. A scene of
# type 'world' points at a Gazebo world, not at an ASSY, and says nothing about
# how any '.assy' file should be read.
_ASSY_TYPES = ("assy",)


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
    `partcad.yaml` that will not parse, a declaration whose path is a Jinja2
    expression -- lands on the assembly schema.

    What it looks at is the `assemblies:` and `scenes:` sections of every
    `partcad.yaml` from the file's own directory upwards. That is text, not a
    loaded context: a package graph would answer this exactly, and it would
    also mean the editor could not check a file until the whole package loaded,
    which is precisely when checking matters most.
    """
    target = os.path.abspath(path)
    referenced_by_scene = False

    directory = os.path.dirname(target)
    for _ in range(MAX_PACKAGE_DEPTH):
        config_path = os.path.join(directory, "partcad.yaml")
        if os.path.isfile(config_path):
            for flavor in _declared_in(config_path, target):
                if flavor == assy_lint.FLAVOR_ASSEMBLY:
                    # One assembly is enough: the file has to satisfy the full
                    # schema for that assembly to be readable, whatever else
                    # also points at it.
                    return assy_lint.FLAVOR_ASSEMBLY
                referenced_by_scene = True
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent

    return assy_lint.FLAVOR_SCENE if referenced_by_scene else assy_lint.FLAVOR_ASSEMBLY


def _declared_in(config_path: str, target: str):
    """Yield the flavor of every declaration in this package that names 'target'."""
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        # A `partcad.yaml` is itself a Jinja2 template, so one that does not
        # parse as plain YAML is not necessarily broken - it just cannot be read
        # from here. Either way there is nothing to learn from it.
        return
    if not isinstance(config, dict):
        return

    package_dir = os.path.dirname(os.path.abspath(config_path))
    for section, flavor in _SECTIONS.items():
        declarations = config.get(section)
        if not isinstance(declarations, dict):
            continue
        for name, declaration in declarations.items():
            if not isinstance(declaration, dict) or declaration.get("type") not in _ASSY_TYPES:
                continue
            declared = declaration.get("path")
            if declared is None:
                declared = "%s.assy" % name
            if not isinstance(declared, str) or "{" in declared:
                # A templated path; what it resolves to is not knowable here.
                continue
            if os.path.abspath(os.path.join(package_dir, declared)) == target:
                yield flavor


def check_file(path: str, text: str = None, flavor: str = None) -> FileReport:
    """Check one file, or ``text`` as its unsaved content.

    ``flavor`` says whether to read an ASSY file as an assembly or as a scene
    (see `assy_lint.FLAVORS`); None works it out with `detect_flavor`. It is
    ignored for a `partcad.yaml`, which has one schema and no flavor -- and the
    search is not run for one either, so an editor checking a configuration on
    every keystroke does not walk the tree above it to answer a question that
    does not apply.

    Raises ``OSError`` if ``text`` is None and the file cannot be read: a caller
    that named a file it cannot open wants to hear about it.
    """
    if assy_lint.schema_name_for_file(path) is None:
        return FileReport(path, [], checked=False)
    if not assy_lint.is_assy_file(path):
        flavor = None
    elif flavor not in assy_lint.FLAVORS:
        flavor = detect_flavor(path)
    if text is None:
        with open(path, "r", encoding="utf-8") as file:
            text = file.read()
    schema = assy_lint.schema_for_file(path, flavor)
    return FileReport(path, assy_lint.validate_source(text, schema), checked=True, flavor=flavor)


def check_files(paths, text: str = None, flavor: str = None) -> list:
    """Check every path given. ``text`` supplies the content of a single path."""
    paths = list(paths)
    if text is not None and len(paths) != 1:
        raise ValueError("content can only be supplied for a single file")
    # Paths are reported back exactly as they came in: a user who typed a
    # relative path wants to read one, and an editor that passed an absolute one
    # needs it back to match the document it asked about.
    return [check_file(path, text, flavor) for path in paths]
