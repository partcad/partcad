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

import difflib
import os
import shutil
import subprocess
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
    """The directory, inside the repository, of the package a repository path belongs to: the nearest above it with a 'partcad.yaml'."""
    workdir = _workdir(repository)
    parts = path.split("/")[:-1]
    while True:
        candidate = "/".join(parts)
        if os.path.isfile(os.path.join(workdir, *parts, pc_changes.PACKAGE_FILE)):
            return candidate
        if not parts:
            return None
        parts = parts[:-1]


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
    if before is None:
        from partcad_utils.object_names import NAMED_KINDS

        after_project = pc_changes.package_at(ctx, package, after)
        return [
            {"kind": kind, "name": name, "object": pc_changes.qualified(package, name), "how": [pc_changes.ADDED]}
            for kind in NAMED_KINDS
            for name in sorted(pc_changes._configs(after_project, kind))
        ]
    try:
        return pc_changes.changes(ctx, package, before, after)["objects"]
    except ValueError:
        return []


def _relative_to(path: str, directory: str) -> str:
    return path[len(directory) + 1 :] if directory else path


def status(ctx, project, kind: typing.Optional[str] = None, name: typing.Optional[str] = None) -> dict:
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
    staged = _object_rows(ctx, package, _head_state(repository), package_versions.STAGED) if index else []
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


def _declaration_lines(text: str, kind: str, name: str) -> typing.Optional[tuple]:
    """The lines [start, end) 'partcad.yaml' declares '<kind> <name>' on; None where it does not, or cannot be read."""
    import yaml

    from partcad_utils.object_names import SECTIONS

    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return None
    if not isinstance(root, yaml.MappingNode):
        return None
    for key, value in root.value:
        if getattr(key, "value", None) != SECTIONS.get(kind) or not isinstance(value, yaml.MappingNode):
            continue
        for entry_key, entry_value in value.value:
            if getattr(entry_key, "value", None) == name:
                end = entry_value.end_mark.line + (1 if entry_value.end_mark.column > 0 else 0)
                return entry_key.start_mark.line, max(end, entry_key.start_mark.line + 1)
    return None


def _overlaps(start: int, end: int, span: typing.Optional[tuple]) -> bool:
    if span is None:
        return False
    if start == end:
        # An insertion between lines: inside the span, or at its end.
        return span[0] <= start <= span[1]
    return start < span[1] and span[0] < end


def stage_declaration(index_text: str, work_text: str, kind: str, name: str) -> typing.Optional[str]:
    """'index_text' with the lines of '<kind> <name>' taken from 'work_text' and every other line left as it was.

    None where neither side declares it in a form that can be read without
    rendering ('partcad.yaml' may be a Jinja2 template), which is when the
    whole file is staged instead.
    """
    a = index_text.splitlines(keepends=True)
    b = work_text.splitlines(keepends=True)
    in_index = _declaration_lines(index_text, kind, name)
    in_work = _declaration_lines(work_text, kind, name)
    if in_index is None and in_work is None:
        return None
    merged = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            merged.extend(a[i1:i2])
        elif _overlaps(j1, j2, in_work) or _overlaps(i1, i2, in_index):
            merged.extend(b[j1:j2])
        else:
            merged.extend(a[i1:i2])
    return "".join(merged)


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


def _git_executable() -> typing.Optional[str]:
    return shutil.which("git")


def commit(repository, message: str, author: typing.Optional[dict] = None) -> str:
    """Commit what the index holds, with 'message', as 'author' ({'name', 'email'}); the new commit's id.

    By git itself where it is installed, so that the repository's hooks and
    signing apply as they would to the user's own commit; otherwise with
    pygit2, which refuses a repository that signs its commits.
    """
    author = {key: value for key, value in (author or {}).items() if value}
    workdir = _workdir(repository)
    git = _git_executable()
    if git is not None:
        env = dict(os.environ)
        if author.get("name"):
            env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = author["name"]
        if author.get("email"):
            env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = author["email"]
        done = subprocess.run(
            [git, "commit", "--quiet", "--file", "-"],
            cwd=workdir,
            input=message,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        if done.returncode != 0:
            raise ValueError("git commit failed: %s" % (done.stderr.strip() or done.stdout.strip()))
        repository.repo.index.read(True)
        return str(repository.repo.head.target)

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
    tree = repo.index.write_tree()
    parents = [] if repo.head_is_unborn else [repo.head.target]
    reference = "HEAD"
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
) -> dict:
    """Commit what is staged as a new revision of the subject, once 'check' allows it and 'checks' pass.

    'checks(status)' runs what has to pass on the staged state -- lint and the
    qualification tests -- and returns the failures, which refuse the revision.
    Returns {'sha', 'short', 'summary', 'checks'}; raises 'Refused'.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A new revision needs a message")
    why = project.not_written_to()
    if why is not None:
        raise ValueError("%s: no revision of it can be made: %s" % (project.name, why))
    result = status(ctx, project, kind, name)
    check(result, expect_index, include_others, accept)
    ran = []
    if checks is not None:
        ran = checks(result) or []
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
    sha = commit(repository, message.strip() + "\n", author)
    pc_logging.info("Made the revision %s of %s" % (package_versions.short(sha), result.get("object") or project.name))
    return {
        "package": project.name,
        "object": result.get("object"),
        "sha": sha,
        "short": package_versions.short(sha),
        "summary": message.strip().splitlines()[0],
        "checks": ran,
    }
