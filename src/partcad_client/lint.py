#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Checking the files this machine is editing, without asking a daemon.

An ASSY file is a Jinja2 template that renders to YAML and then has to match the
ASSY schema. Checking one is pure text work: no package graph, no CAD runtime,
no context -- and the file in question is often not on disk at all, but a buffer
an editor has not saved yet. Sending that to the daemon would be shipping the
client's own file across a wire to have it read back, and would leave the editor
silent exactly when the daemon is down or the package fails to load, which is
usually *because* of the file being typed into.

So every client checks locally, through here: `pc lint --file` in the CLI
process, and the VS Code extension by running that same command (or, on the
Python backend, by calling this from its bundled language server). The check
itself is `partcad_utils.assy_lint`, shared with the daemon-side package lint so
an editor and CI cannot disagree about a file.
"""

from partcad_utils import assy_lint


class FileReport:
    """The findings for one file, and how it was named on the way in."""

    def __init__(self, path: str, diagnostics: list, checked: bool):
        self.path = path
        self.diagnostics = diagnostics
        # False when nothing here knows how to check this kind of file, which is
        # not the same as "checked and clean" and is why callers can tell the
        # two apart (`pc lint --file notes.txt` should say so).
        self.checked = checked

    @property
    def failed(self) -> bool:
        return any(d.severity == assy_lint.SEVERITY_ERROR for d in self.diagnostics)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "checked": self.checked,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


def check_file(path: str, text: str = None) -> FileReport:
    """Check one file, or ``text`` as its unsaved content.

    Raises ``OSError`` if ``text`` is None and the file cannot be read: a caller
    that named a file it cannot open wants to hear about it.
    """
    if assy_lint.schema_name_for_file(path) is None:
        return FileReport(path, [], checked=False)
    if text is None:
        with open(path, "r", encoding="utf-8") as file:
            text = file.read()
    return FileReport(path, assy_lint.validate_source(text, assy_lint.get_schema(assy_lint.ASSY_SCHEMA)), checked=True)


def check_files(paths, text: str = None) -> list:
    """Check every path given. ``text`` supplies the content of a single path."""
    paths = list(paths)
    if text is not None and len(paths) != 1:
        raise ValueError("content can only be supplied for a single file")
    # Paths are reported back exactly as they came in: a user who typed a
    # relative path wants to read one, and an editor that passed an absolute one
    # needs it back to match the document it asked about.
    return [check_file(path, text) for path in paths]
