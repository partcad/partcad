#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What is staged and what is not, staging it, and making a new revision of it.

The subject is a package or one object of it, in the git repository the
package's files are in. Three states of it matter here (see
'partcad.package_versions'): HEAD, the last revision; STAGED, what the git index
holds, which a new revision is made of; and WORKTREE, the files on disk.

* **Status** says, object by object, what is staged (HEAD to STAGED) and what is
  not (STAGED to WORKTREE) -- by comparing what each object *means* at those
  states ('partcad.changes') rather than which lines of which files moved -- and
  what else in the repository is staged or changed: other objects of the
  package, other packages, files in no package.
* **Stage** stages every change of the subject that is not staged yet. For an
  object that is the files it is built from and its own declaration in
  'partcad.yaml': only the lines of that declaration, so that another object's
  edit in the same file stays out.
* **New revision** commits what is staged, and nothing else, once the checks
  before it pass: something of the subject is staged; anything else staged is
  agreed to; the index is the one the caller looked at; no merge is in progress.
  Its author is whoever the client says -- a daemon may be on another machine,
  whose git identity is not the user's.
"""

import os
import re
import shutil
import subprocess
import tempfile
import typing

from . import changes as pc_changes
from . import logging as pc_logging
from . import package_versions

# What a row of the status says a path is, in the repository's terms.
STAGED_SECTION = "staged"
UNSTAGED_SECTION = "unstaged"
UNTRACKED_SECTION = "untracked"


def _repository(project):
    repository = package_versions.repository_of(project.config_dir)
    if repository is None:
        raise ValueError("%s is not in a git repository" % project.name)
    return repository


def _workdir(repository) -> str:
    return os.path.realpath(repository.repo.workdir)


def _package_dir_of(repository, path: str) -> str:
    """The directory, inside the repository, of the package a repository path belongs to: the nearest above it with a 'partcad.yaml'.

    A path deleted from the working tree belongs to the package it was in: a
    'partcad.yaml' deleted with it is still in the index or at HEAD, so that
    deleting a sub-package is a change of that sub-package and not of the
    package above it.
    """
    workdir = _workdir(repository)
    parts = path.split("/")[:-1]
    deleted = not os.path.lexists(os.path.join(workdir, *path.split("/")))
    while True:
        candidate = "/".join(parts)
        if os.path.isfile(os.path.join(workdir, *parts, pc_changes.PACKAGE_FILE)):
            return candidate
        if deleted and _manifest_was_there(repository, "/".join(parts + [pc_changes.PACKAGE_FILE])):
            return candidate
        if not parts:
            return None
        parts = parts[:-1]


def _manifest_was_there(repository, path: str) -> bool:
    """Whether the index or HEAD holds 'path'."""
    import pygit2

    repo = repository.repo
    try:
        if path in repo.index:
            return True
    except (KeyError, ValueError, pygit2.GitError):
        pass
    try:
        return not repo.head_is_unborn and path in repo.head.peel(pygit2.Commit).tree
    except (KeyError, ValueError, pygit2.GitError):
        return False


def _inside(path: str, directory: str) -> bool:
    return directory == "" or path == directory or path.startswith(directory.rstrip("/") + "/")


def _git_status(repository) -> dict:
    """Every path git reports, as {path: set of sections}."""
    import pygit2
    from pygit2.enums import FileStatus

    staged_flags = (
        FileStatus.INDEX_NEW
        | FileStatus.INDEX_MODIFIED
        | FileStatus.INDEX_DELETED
        | FileStatus.INDEX_RENAMED
        | FileStatus.INDEX_TYPECHANGE
    )
    unstaged_flags = FileStatus.WT_MODIFIED | FileStatus.WT_DELETED | FileStatus.WT_RENAMED | FileStatus.WT_TYPECHANGE
    found = {}
    try:
        statuses = repository.repo.status(untracked_files="all")
    except pygit2.GitError as e:
        raise ValueError("git could not say what changed: %s" % e) from e
    for path, flags in statuses.items():
        sections = set()
        if flags & staged_flags:
            sections.add(STAGED_SECTION)
        if flags & unstaged_flags:
            sections.add(UNSTAGED_SECTION)
        if flags & FileStatus.WT_NEW:
            sections.add(UNTRACKED_SECTION)
        if flags & FileStatus.CONFLICTED:
            sections.add("conflicted")
        if sections:
            found[path] = sections
    return found


def _head_state(repository) -> typing.Optional[str]:
    return "HEAD" if repository.head() is not None else None


def _object_rows(ctx, package: str, before: typing.Optional[str], after: typing.Optional[str]) -> list:
    """The objects of 'package' that changed from 'before' to 'after'; with no 'before' -- no commit yet -- every object, added."""
    return _compared(ctx, package, before, after)[0]


def _compared(ctx, package: str, before: typing.Optional[str], after: typing.Optional[str]) -> tuple:
    """'_object_rows', and whether the package's own declaration changed too."""
    if before is None:
        from partcad_utils.object_names import NAMED_KINDS

        after_project = pc_changes.package_at(ctx, package, after)
        rows = [
            {"kind": kind, "name": name, "object": pc_changes.qualified(package, name), "how": [pc_changes.ADDED]}
            for kind in NAMED_KINDS
            for name in sorted(pc_changes._configs(after_project, kind))
        ]
        declared = pc_changes._package_declaration(after_project) if after_project is not None else {}
        return rows, bool(declared)
    try:
        compared = pc_changes.changes(ctx, package, before, after)
    except ValueError:
        return [], False
    return compared["objects"], compared["package_changed"]


def _relative_to(path: str, directory: str) -> str:
    return path[len(directory) + 1 :] if directory else path


def status(ctx, project, kind: typing.Optional[str] = None, name: typing.Optional[str] = None) -> dict:
    """What is staged and what is not -- see '_status' -- read from one index.

    Each part of the answer reads the index on its own (git's status, the tree
    it holds, the package as staged), so they are read again until the index
    is the same before and after: what 'others' finds staged elsewhere and the
    tree a new revision is made of ('index') are then of one index.
    """
    repository = _repository(project)
    path = os.path.join(repository.repo.path, "index")
    for _attempt in range(3):
        before = package_versions._index_identity(path)
        result = _status(ctx, project, kind, name)
        if package_versions._index_identity(path) == before:
            return result
    raise ValueError("The index of %s kept changing while it was read: look again" % _workdir(repository))


def _status(ctx, project, kind: typing.Optional[str] = None, name: typing.Optional[str] = None) -> dict:
    """What is staged and what is not, for a package or -- with 'kind' and 'name' -- one object of it.

    {'package', 'object', 'repository', 'branch', 'head', 'index', 'staged',
    'unstaged', 'untracked', 'files', 'elsewhere', 'partial', 'state',
    'advice'}: 'staged' and 'unstaged' are rows per object ({'kind', 'name',
    'object', 'how'}), 'files' the files of the package no object is built from
    with the sections git puts each in, 'elsewhere' the other packages and the
    files in no package that are staged or changed, 'partial' the objects
    staged and changed again since, 'index' the id of the tree the index holds
    -- what 'new_revision' is told back, so that it commits the index the
    caller looked at -- and 'advice' one sentence to hand an agent when
    anything of the subject is not staged.
    """
    repository = _repository(project)
    repo = repository.repo
    head = repository.head()
    try:
        branch = None if repo.head_is_detached or repo.head_is_unborn else repo.head.shorthand
    except Exception:  # pylint: disable=broad-except
        branch = None
    if branch is None and repo.head_is_unborn:
        try:
            branch = repo.references["HEAD"].target.rpartition("/")[2]
        except Exception:  # pylint: disable=broad-except
            branch = None
    paths = _git_status(repository)
    conflicted = sorted(path for path, sections in paths.items() if "conflicted" in sections)
    index = None
    if not conflicted:
        index = package_versions.index_tree(repository)

    relpath = repository.relpath
    package = project.name
    staged, package_staged = (
        _compared(ctx, package, _head_state(repository), package_versions.STAGED) if index else ([], False)
    )
    unstaged = _object_rows(ctx, package, package_versions.STAGED, None) if index else []
    own = None
    if name is not None:
        name = name.partition(";")[0]
        others_staged = [row for row in staged if row["name"] != name]
        staged = [row for row in staged if row["name"] == name]
        unstaged = [row for row in unstaged if row["name"] == name]
        # The files the object is built from, as it is on disk and as it is staged.
        own = set(pc_changes.object_files(project, kind, name))
        if index:
            own.update(
                pc_changes.object_files(pc_changes.package_at(ctx, package, package_versions.STAGED), kind, name)
            )
    else:
        others_staged = []

    files = []
    elsewhere = {}
    untracked = []
    for path, sections in sorted(paths.items()):
        owner = _package_dir_of(repository, path)
        if owner == relpath or (owner is None and relpath == "" and _inside(path, relpath)):
            rel = _relative_to(path, relpath)
            files.append({"path": rel, "sections": sorted(sections)})
            if UNTRACKED_SECTION in sections:
                untracked.append(rel)
            continue
        key = owner if owner is not None else ""
        entry = elsewhere.setdefault(key, {"directory": key, "package": None, "staged": 0, "unstaged": 0})
        if STAGED_SECTION in sections:
            entry["staged"] += 1
        if sections & {UNSTAGED_SECTION, UNTRACKED_SECTION}:
            entry["unstaged"] += 1
    for entry in elsewhere.values():
        entry["package"] = _package_name_of(ctx, repository, entry["directory"])

    # The files of the objects that changed, which the rows of those objects
    # already say: what is left of 'files' is what no object is built from.
    object_paths = {pc_changes.PACKAGE_FILE}
    for row in staged + unstaged:
        object_paths.update(pc_changes.object_files(project, row["kind"], row["name"]))
    names_staged = {row["name"] for row in staged}
    partial = sorted(row["name"] for row in unstaged if row["name"] in names_staged)
    result = {
        "package": package,
        "object": pc_changes.qualified(package, name) if name else None,
        "kind": kind,
        "repository": _workdir(repository),
        "branch": branch,
        "head_ref": _head_ref(repo),
        "head": head,
        "detached": bool(repo.head_is_detached),
        "index": index,
        "state": _repository_state(repo),
        "conflicted": conflicted,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "files": files,
        "own_files": sorted(own) if own is not None else None,
        "object_paths": sorted(object_paths),
        "partial": partial,
        "others_staged": others_staged,
        "package_staged": package_staged,
        "elsewhere": sorted(elsewhere.values(), key=lambda entry: entry["directory"]),
    }
    result["advice"] = advice(result)
    return result


def _package_name_of(ctx, repository, directory: str) -> typing.Optional[str]:
    """The name the package in a repository directory is loaded under, where it is loaded."""
    target = os.path.realpath(os.path.join(_workdir(repository), *directory.split("/"))) if directory else None
    if target is None:
        return None
    for name, loaded in list(ctx.projects.items()):
        if loaded is None or package_versions.is_versioned(name):
            continue
        if os.path.realpath(getattr(loaded, "config_dir", "") or "") == target:
            return name
    return None


def _repository_state(repo) -> typing.Optional[str]:
    """What git is in the middle of -- a merge, a rebase, a cherry-pick -- or None."""
    try:
        state = repo.state()
    except Exception:  # pylint: disable=broad-except
        return None
    names = {
        1: "merge",
        2: "revert",
        3: "revert",
        4: "cherry-pick",
        5: "cherry-pick",
        6: "bisect",
        7: "rebase",
        8: "rebase",
        9: "rebase",
        10: "apply-mailbox",
        11: "apply-mailbox",
    }
    return names.get(int(state)) if int(state) else None


def advice(result: dict) -> typing.Optional[str]:
    """One sentence to hand an agent, when anything of the subject is not staged; None when everything is."""
    pending = list(result.get("unstaged") or [])
    loose = [
        entry["path"]
        for entry in _subject_files(result)
        if set(entry["sections"]) & {UNSTAGED_SECTION, UNTRACKED_SECTION}
    ]
    if not pending and not loose:
        return None
    what = []
    for row in pending:
        what.append(":%s (%s)" % (row["name"], ", ".join(row["how"])))
    subject = result.get("object") or result.get("package")
    if result.get("object") is None:
        covered = set(result.get("object_paths") or [])
        loose = [path for path in loose if path not in covered]
        what.extend(loose[:5])
        if len(loose) > 5:
            what.append("%d more files" % (len(loose) - 5))
    listed = ", ".join(what) if what else "its files"
    return (
        "Stage the changes to %s that are not staged yet -- %s -- for a new revision, "
        "and leave everything else as it is (or run 'pc ops rev stage %s')." % (subject, listed, subject)
    )


# ---- stage ------------------------------------------------------------------


def _section(text: str, kind: str) -> typing.Optional[tuple]:
    """Where 'partcad.yaml' declares its '<kind>'s: (the line of the section's key, [(name, start, end), ...]).

    Lines [start, end) of each declaration, in the order written; (None, [])
    for a file with no such section, None for one that cannot be read without
    rendering it.
    """
    import yaml

    from partcad_utils.object_names import SECTIONS

    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return None
    if root is None:
        return None, []
    if not isinstance(root, yaml.MappingNode):
        return None
    for key, value in root.value:
        if getattr(key, "value", None) != SECTIONS.get(kind):
            continue
        if not isinstance(value, yaml.MappingNode):
            return key.start_mark.line, []
        entries = []
        pairs = list(value.value)
        for position, (entry_key, entry_value) in enumerate(pairs):
            if position + 1 < len(pairs):
                # Up to the next one: where a value ends is where the next
                # key starts, which is indented, so not the end of a line.
                end = pairs[position + 1][0].start_mark.line
            else:
                end = entry_value.end_mark.line + (1 if entry_value.end_mark.column > 0 else 0)
            entries.append((entry_key.value, entry_key.start_mark.line, max(end, entry_key.start_mark.line + 1)))
        return key.start_mark.line, entries
    return None, []


def _declaration_lines(text: str, kind: str, name: str) -> typing.Optional[tuple]:
    """The lines [start, end) 'partcad.yaml' declares '<kind> <name>' on; None where it does not, or cannot be read."""
    found = _section(text, kind)
    for entry, start, end in (found[1] if found else []):
        if entry == name:
            return start, end
    return None


def stage_declaration(index_text: str, work_text: str, kind: str, name: str) -> typing.Optional[str]:
    """'index_text' with the lines of '<kind> <name>' taken from 'work_text' and every other line left as it was.

    Its lines in the index are replaced by its lines in the working tree, or
    taken out where it is gone; a new one goes in after the declaration it
    follows in the working tree, under the section's key, which goes in too
    where the index has no such section. Refused, with ValueError, where what
    that makes is anything but the index's file with this one declaration
    changed. None where neither side can be read without rendering it
    ('partcad.yaml' may be a Jinja2 template), which is when the whole file is
    staged instead.
    """
    a = index_text.splitlines(keepends=True)
    b = work_text.splitlines(keepends=True)
    in_index_section = _section(index_text, kind)
    in_work_section = _section(work_text, kind)
    if in_index_section is None and in_work_section is None:
        return None
    if in_index_section is None or in_work_section is None:
        raise ValueError(
            "%s cannot be read without rendering it, so %s %s cannot be staged alone: stage the file"
            % (pc_changes.PACKAGE_FILE, kind, name)
        )
    in_index = next(((start, end) for entry, start, end in in_index_section[1] if entry == name), None)
    in_work = next(((start, end) for entry, start, end in in_work_section[1] if entry == name), None)
    if in_index is None and in_work is None:
        return None
    if in_work is not None and b[in_work[1] - 1 : in_work[1]] and not b[in_work[1] - 1].endswith("\n"):
        b[in_work[1] - 1] += "\n"
    lines = b[in_work[0] : in_work[1]] if in_work is not None else []
    if in_index is not None:
        merged = a[: in_index[0]] + lines + a[in_index[1] :]
    elif in_index_section[0] is None:
        # No such section in the index: it goes in with its key, at the end.
        tail = a[:]
        if tail and not tail[-1].endswith("\n"):
            tail[-1] += "\n"
        merged = tail + [b[in_work_section[0]]] + lines
    else:
        # After the one before it in the working tree, where the index has it;
        # otherwise first in the section.
        order = [entry for entry, _start, _end in in_work_section[1]]
        before = order[: order.index(name)]
        ends = {entry: end for entry, _start, end in in_index_section[1]}
        at = next((ends[entry] for entry in reversed(before) if entry in ends), None)
        if at is None:
            at = in_index_section[1][0][1] if in_index_section[1] else in_index_section[0] + 1
        if at > 0 and at <= len(a) and not a[at - 1].endswith("\n"):
            # After a last line with no line break: one first, or the two join.
            a = a[: at - 1] + [a[at - 1] + "\n"] + a[at:]
        merged = a[:at] + lines + a[at:]
    text = "".join(merged)
    if not _only_declaration_changed(text, index_text, work_text, kind, name):
        raise ValueError(
            "The lines of %s %s in %s cannot be staged alone without changing what else it declares: stage the"
            " file, or its lines by hand ('git add -p')" % (kind, name, pc_changes.PACKAGE_FILE)
        )
    return text


def _only_declaration_changed(merged: str, index_text: str, work_text: str, kind: str, name: str) -> bool:
    """Whether 'merged' reads as the index's 'partcad.yaml' with '<kind> <name>' as the working tree has it, and nothing else."""
    import yaml

    from partcad_utils.object_names import SECTIONS

    try:
        found = yaml.safe_load(merged) or {}
        expected = yaml.safe_load(index_text) or {}
        wanted = yaml.safe_load(work_text) or {}
    except yaml.YAMLError:
        return False
    if not all(isinstance(document, dict) for document in (found, expected, wanted)):
        return False
    section = SECTIONS.get(kind)
    declarations = dict(expected.get(section) or {})
    declarations.pop(name, None)
    if name in (wanted.get(section) or {}):
        declarations[name] = wanted[section][name]
    expected[section] = declarations

    def normal(document):
        # An empty section and none at all say the same.
        return {
            key: value for key, value in document.items() if value not in (None, {}) or key not in SECTIONS.values()
        }

    return normal(found) == normal(expected)


def _stage_path(repository, index, path: str) -> None:
    full = os.path.join(_workdir(repository), *path.split("/"))
    if os.path.lexists(full):
        index.add(path)
    else:
        try:
            index.remove(path)
        except (KeyError, OSError, ValueError):
            pass


def stage(ctx, project, kind: typing.Optional[str] = None, name: typing.Optional[str] = None) -> dict:
    """Stage every change of the subject that is not staged: {'staged', 'partial', 'notes'}.

    A package: its own files, untracked ones included, and none of its
    sub-packages'. An object: the files it is built from -- at the working tree,
    and at the index for one that is gone -- and the lines of its own
    declaration in 'partcad.yaml' ('stage_declaration'). Refused for a
    revision, and while the index has conflicts.
    """
    import pygit2

    why = project.not_written_to()
    if why is not None:
        raise ValueError("%s: nothing of it can be staged: %s" % (project.name, why))
    repository = _repository(project)
    repo = repository.repo
    relpath = repository.relpath
    paths = _git_status(repository)
    if any("conflicted" in sections for sections in paths.values()):
        raise ValueError("The index has conflicts: resolve them before staging anything")
    index = repo.index
    index.read(True)
    staged = []
    notes = []
    pending = {
        path
        for path, sections in paths.items()
        if sections & {UNSTAGED_SECTION, UNTRACKED_SECTION} and _package_dir_of(repository, path) == relpath
    }
    if name is None:
        for path in sorted(pending):
            _stage_path(repository, index, path)
            staged.append(_relative_to(path, relpath))
    else:
        name = name.partition(";")[0]
        files = set(pc_changes.object_files(project, kind, name))
        staged_project = pc_changes.package_at(ctx, project.name, package_versions.STAGED)
        files.update(pc_changes.object_files(staged_project, kind, name))
        for rel in sorted(files):
            path = "/".join(part for part in (relpath, rel) if part)
            if path in pending:
                _stage_path(repository, index, path)
                staged.append(rel)
        config = "/".join(part for part in (relpath, pc_changes.PACKAGE_FILE) if part)
        if config in pending:
            with open(os.path.join(_workdir(repository), *config.split("/")), "r", encoding="utf-8") as f:
                work_text = f.read()
            try:
                entry = index[config]
                index_text = repo[entry.id].data.decode("utf-8")
                mode = entry.mode
            except (KeyError, UnicodeDecodeError):
                index_text = ""
                mode = pygit2.enums.FileMode.BLOB
            merged = stage_declaration(index_text, work_text, kind, name)
            if merged is None:
                _stage_path(repository, index, config)
                notes.append(
                    "%s could not be read without rendering it, so all of it was staged" % pc_changes.PACKAGE_FILE
                )
                staged.append(pc_changes.PACKAGE_FILE)
            elif merged != index_text:
                blob = repo.create_blob(merged.encode("utf-8"))
                index.add(pygit2.IndexEntry(config, blob, mode))
                staged.append(pc_changes.PACKAGE_FILE + " (the declaration of %s)" % name)
    index.write()
    return {
        "package": project.name,
        "object": pc_changes.qualified(project.name, name) if name else None,
        "staged": staged,
        "notes": notes,
    }


# ---- new revision -----------------------------------------------------------


class Refused(ValueError):
    """A new revision that is not made, with what the caller can do about it."""

    def __init__(self, message: str, code: str, status: dict):
        super().__init__(message)
        self.code = code
        self.status = status


def _subject_files(result: dict) -> list:
    """The rows of 'files' that are the subject's: all of a package's, or the files an object is built from."""
    own = result.get("own_files")
    files = result.get("files") or []
    return files if own is None else [entry for entry in files if entry["path"] in own]


def warnings(result: dict) -> list:
    """What a caller is asked to agree to before the staged changes are committed as they are."""
    found = []
    if result.get("unstaged") or any(
        set(entry["sections"]) & {UNSTAGED_SECTION, UNTRACKED_SECTION} for entry in _subject_files(result)
    ):
        found.append(
            "Changes of %s are not staged, and will not be in this revision"
            % (result.get("object") or result["package"])
        )
    if result.get("partial"):
        found.append(
            "Changed again since they were staged, so what was built and tested is not what will be committed: %s"
            % ", ".join(":" + name for name in result["partial"])
        )
    if result.get("detached"):
        found.append("HEAD is detached: the new revision will be on no branch")
    return found


def others(result: dict) -> list:
    """What is staged outside the subject: other objects of the package, other packages, files in no package."""
    found = [row["object"] for row in result.get("others_staged") or []]
    own = result.get("own_files")
    if own is not None:
        found.extend(
            entry["path"]
            for entry in result.get("files") or []
            if STAGED_SECTION in entry["sections"]
            and entry["path"] != pc_changes.PACKAGE_FILE
            and entry["path"] not in own
        )
    if result.get("object") and result.get("package_staged"):
        # The package's own declaration -- its dependencies, its settings --
        # is in the same file as the object's, and is no part of the object.
        found.append("the package's own declaration in %s" % pc_changes.PACKAGE_FILE)
    for entry in result.get("elsewhere") or []:
        if entry["staged"]:
            found.append(entry["package"] or (entry["directory"] or "files in no package"))
    return found


def check(result: dict, expect_index: typing.Optional[str], include_others: bool, accept: bool) -> None:
    """Raise 'Refused' unless the status allows a new revision on these terms."""
    if result.get("conflicted"):
        raise Refused("The index has conflicts: resolve them first", "conflicts", result)
    if result.get("state"):
        raise Refused("A %s is in progress: finish it first" % result["state"], "in-progress", result)
    subject_staged = bool(result.get("staged")) or any(
        STAGED_SECTION in entry["sections"] for entry in _subject_files(result)
    )
    if not subject_staged:
        raise Refused(
            "Nothing of %s is staged. %s" % (result.get("object") or result["package"], result.get("advice") or ""),
            "nothing-staged",
            result,
        )
    if expect_index and expect_index != result.get("index"):
        raise Refused("What is staged changed since it was looked at: look again", "index-changed", result)
    staged_elsewhere = others(result)
    if staged_elsewhere and not include_others:
        raise Refused(
            "Also staged, and would be in this revision: %s" % ", ".join(staged_elsewhere), "others-staged", result
        )
    pending = warnings(result)
    if pending and not accept:
        raise Refused("; ".join(pending), "warnings", result)


def _said_made(repo, said: str, message: str) -> typing.Optional[str]:
    """The commit 'git commit' said it made -- 'said' is what it printed -- of the ones it names, the one with 'message'."""
    import pygit2

    for found in _MADE.findall(said):
        try:
            commit = repo.revparse_single(found).peel(pygit2.Commit)
        except (KeyError, ValueError, pygit2.GitError):
            continue
        if commit.message.strip() == message.strip():
            return str(commit.id)
    return None


def _holds(repo, branch: typing.Optional[str], sha: str) -> bool:
    """Whether 'branch' -- or HEAD, detached -- is at the commit 'sha' or past it."""
    import pygit2

    try:
        tip = repo.references[branch].target if branch else repo.head.target
        return str(tip) == sha or repo.descendant_of(tip, pygit2.Oid(hex=sha))
    except (KeyError, ValueError, pygit2.GitError):
        return False


def _head_ref(repo) -> typing.Optional[str]:
    """The branch HEAD is on, as a reference name ('refs/heads/main'); None while it is detached."""
    try:
        if repo.head_is_detached:
            return None
        return repo.references["HEAD"].target
    except Exception:  # pylint: disable=broad-except
        return None


def _move_index(repository, expected: str, tree: str) -> bool:
    """Make the index hold 'tree' where it still holds 'expected', as git writes one: under its lock.

    git takes 'index.lock' to stage anything; holding it while the index is
    compared and replaced is what keeps a 'git add' finishing meanwhile from
    being written over. Where the lock is taken, or the index moved, the index
    is left as it is.
    """
    import pygit2

    repo = repository.repo
    path = os.path.join(repo.path, "index")
    lock = path + ".lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except OSError:
        return False
    moved = False
    try:
        if package_versions.index_tree(repository) == expected:
            scratch = tempfile.mkdtemp(prefix="partcad-index-")
            try:
                written = os.path.join(scratch, "index")
                index = pygit2.Index(written)
                index.read_tree(repo[tree])
                index.write()
                with open(written, "rb") as f:
                    os.write(descriptor, f.read())
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
            moved = True
    except (OSError, KeyError, ValueError, pygit2.GitError) as e:
        pc_logging.debug("Left the index as it was: %s" % e)
    finally:
        os.close(descriptor)
        if moved:
            os.replace(lock, path)
        else:
            try:
                os.unlink(lock)
            except OSError:
                pass
    return moved


def _git_executable() -> typing.Optional[str]:
    return shutil.which("git")


def _git(git: str, workdir: str, env: dict, *args, input: typing.Optional[str] = None) -> str:
    """Run git; what it printed, or ValueError with what it said where it failed."""
    done = subprocess.run(
        [git, *args],
        cwd=workdir,
        input=input,
        text=True,
        # git reads and writes a commit message as UTF-8 unless configured otherwise.
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
        check=False,
    )
    if done.returncode != 0:
        command = next((arg for arg in args if not arg.startswith("-") and "=" not in arg), "")
        raise ValueError("git %s failed: %s" % (command, done.stderr.strip() or done.stdout.strip()))
    return done.stdout or ""


# What 'git commit' says it made: '[main 1a2b3c4] Subject', '[main (root-commit) 1a2b3c4] ...',
# '[detached HEAD 1a2b3c4] ...', '[feature]x 1a2b] ...' -- the words may be in the user's
# language and a branch may hold a ']', the id is hex; the first ' <hex>] ' on the line is it.
_MADE = re.compile(r"^\[\S.*? ([0-9a-f]{4,64})\] ", re.MULTILINE)


_ANY = object()


def commit(
    repository,
    message: str,
    author: typing.Optional[dict] = None,
    tree: typing.Optional[str] = None,
    parent=_ANY,
    branch=_ANY,
) -> str:
    """Commit what the index holds, with 'message', as 'author' ({'name', 'email'}); the new commit's id.

    By git itself where it is installed, so that the repository's hooks and
    signing apply as they would to the user's own commit; otherwise with
    pygit2, which refuses a repository that signs its commits. 'tree' is the
    tree the commit is of, whatever is staged while it is made -- git commits
    an index of its own holding it -- and refused, with 'index-changed', where
    the index already holds another. 'parent' is the commit it goes on top of
    (None: the first), and 'branch' the branch it goes on ('refs/heads/...';
    None: HEAD detached), each refused with 'head-moved' where HEAD is
    elsewhere: what was agreed to was agreed to against them -- and found and
    said after the fact where HEAD moves while git commits, which git gives no
    way to prevent. A hook may still change what git commits; the caller is
    told ('new_revision').
    """
    author = {key: value for key, value in (author or {}).items() if value}
    workdir = _workdir(repository)
    if tree is not None and package_versions.index_tree(repository) != tree:
        raise Refused("What is staged changed while it was being checked: look again", "index-changed", {})
    if parent is not _ANY and repository.head() != parent:
        raise Refused("HEAD moved while the revision was being checked: look again", "head-moved", {})
    if branch is not _ANY and _head_ref(repository.repo) != branch:
        raise Refused(
            "Another branch was checked out while the revision was being checked: look again", "head-moved", {}
        )
    git = _git_executable()
    if git is not None:
        env = dict(os.environ)
        if author.get("name"):
            env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = author["name"]
        if author.get("email"):
            env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = author["email"]
        scratch = None
        if tree is not None:
            # git commits an index of its own holding exactly 'tree', so that
            # nothing staged meanwhile is in it -- hooks and signing as ever.
            scratch = tempfile.mkdtemp(prefix="partcad-commit-")
            env["GIT_INDEX_FILE"] = os.path.join(scratch, "index")
        try:
            if tree is not None:
                _git(git, workdir, env, "read-tree", tree)
            # The id in full, whatever 'core.abbrev' the user has.
            said = _git(git, workdir, env, "-c", "core.abbrev=40", "commit", "--file", "-", input=message)
        finally:
            if scratch is not None:
                shutil.rmtree(scratch, ignore_errors=True)
        import pygit2

        repo = repository.repo
        # The revision git says it made, not whatever HEAD is by now: the one
        # it names with this message, a hook printing something alike aside.
        made = _said_made(repo, said, message) or str(repo.head.target)
        # git has no way to be told which commit to go on top of: HEAD moved
        # between the check above and git reading it, or the branch moved off
        # the revision since, is found here, and said, with the revision made.
        parents = [str(each) for each in repo[made].peel(pygit2.Commit).parent_ids]
        moved = parent is not _ANY and parents != ([parent] if parent else [])
        if branch is not _ANY:
            moved = moved or _head_ref(repo) != branch or not _holds(repo, branch, made)
        if moved:
            raise Refused(
                "HEAD moved while git was making the revision: it made %s on top of %s"
                % (package_versions.short(made), package_versions.short(parents[0]) if parents else "nothing"),
                "head-moved",
                {"made": made},
            )
        if tree is not None:
            # The index the user stages into still holds what was committed
            # unless something was staged meanwhile: it is then the new
            # revision's, hooks' additions included; otherwise left as it is.
            committed = str(repo[made].peel(pygit2.Commit).tree.id)
            if committed != tree:
                _move_index(repository, tree, committed)
        repo.index.read(True)
        return made

    import pygit2

    repo = repository.repo
    try:
        signs = repo.config.get_bool("commit.gpgsign")
    except (KeyError, ValueError, pygit2.GitError):
        signs = False
    if signs:
        raise ValueError(
            "This repository signs its commits, and git is not installed here to sign one: commit with git"
        )
    try:
        default = repo.default_signature
    except (KeyError, ValueError, pygit2.GitError):
        default = None
    name = author.get("name") or (default.name if default else None)
    email = author.get("email") or (default.email if default else None)
    if not name or not email:
        raise ValueError("Who the author is is not known: set git's user.name and user.email")
    signature = pygit2.Signature(name, email)
    tree = pygit2.Oid(hex=tree) if tree is not None else repo.index.write_tree()
    if parent is not _ANY:
        parents = [pygit2.Oid(hex=parent)] if parent else []
    else:
        parents = [] if repo.head_is_unborn else [repo.head.target]
    # The branch itself, where one is named: libgit2 moves it only from the
    # first parent, which is the compare-and-swap git commit does not offer.
    reference = branch if branch not in (_ANY, None) else "HEAD"
    return str(repo.create_commit(reference, signature, signature, message, tree, parents))


def new_revision(
    ctx,
    project,
    message: str,
    kind: typing.Optional[str] = None,
    name: typing.Optional[str] = None,
    author: typing.Optional[dict] = None,
    expect_index: typing.Optional[str] = None,
    include_others: bool = False,
    accept: bool = False,
    checks: typing.Optional[typing.Callable[[dict], list]] = None,
    author_required: bool = False,
) -> dict:
    """Commit what is staged as a new revision of the subject, once 'check' allows it and 'checks' pass.

    'checks(status)' runs what has to pass on the staged state -- lint and the
    qualification tests -- and returns the failures, which refuse the revision.
    With 'author_required', an 'author' without both a name and an email is
    refused rather than completed from this machine's git configuration: a
    daemon may be on somebody else's machine.
    Returns {'sha', 'short', 'summary', 'checks', 'hooks_changed'}, the last
    the paths a hook of the repository changed in the commit; raises 'Refused'.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A new revision needs a message")
    why = project.not_written_to()
    if why is not None:
        raise ValueError("%s: no revision of it can be made: %s" % (project.name, why))
    result = status(ctx, project, kind, name)
    check(result, expect_index, include_others, accept)
    if author_required and not (isinstance(author, dict) and author.get("name") and author.get("email")):
        raise ValueError(
            "Who the author is is not known: set git's user.name and user.email where the revision is asked for"
        )
    # The tree the status was read from, and the checks run on: the one the
    # revision is made of, or none is made.
    tree = result.get("index")
    ran = []
    if checks is not None:
        ran = checks(result) or []
        tested = ctx.projects.get(package_versions.versioned_name(project.name, package_versions.STAGED))
        if tested is not None and getattr(tested, "revision_tree", tree) != tree:
            raise Refused("What is staged changed while it was being checked: look again", "index-changed", result)
        failed = [entry for entry in ran if not entry.get("passed")]
        if failed:
            refused = Refused(
                "Checks failed on what is staged: %s"
                % "; ".join(entry.get("summary", entry.get("name", "")) for entry in failed),
                "checks-failed",
                result,
            )
            refused.status["checks"] = ran
            raise refused
    repository = _repository(project)
    try:
        sha = commit(
            repository,
            message.strip() + "\n",
            author,
            tree=tree,
            parent=result.get("head"),
            branch=result.get("head_ref"),
        )
    except Refused as refused:
        # The status it was refused on, and what it says of itself ('made').
        refused.status = {**result, **(refused.status or {})}
        raise
    # A hook of the repository may have changed what git committed: that is
    # the repository's own rule, and it is said rather than undone.
    changed_by_hooks = _changed_paths(repository, tree, sha) if tree is not None else []
    pc_logging.info("Made the revision %s of %s" % (package_versions.short(sha), result.get("object") or project.name))
    return {
        "package": project.name,
        "object": result.get("object"),
        "sha": sha,
        "short": package_versions.short(sha),
        "summary": message.strip().splitlines()[0],
        "checks": ran,
        "hooks_changed": changed_by_hooks,
    }


def _changed_paths(repository, tree: str, sha: str) -> list:
    """The paths the commit 'sha' holds otherwise than 'tree' does: what a hook changed in it."""
    import pygit2

    repo = repository.repo
    try:
        committed = repo[sha].peel(pygit2.Commit).tree
        if str(committed.id) == tree:
            return []
        diff = repo[tree].diff_to_tree(committed)
    except (KeyError, ValueError, pygit2.GitError):
        return []
    return sorted({delta.new_file.path or delta.old_file.path for delta in diff.deltas})
