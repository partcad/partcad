#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Operations methods: Revisions, Dependencies, Used By and Impact of a package or of one object.

Each method is one 'pc ops' command, one MCP tool and what one IDE view is drawn
from (see 'partcad_utils.ops_views', which says which kinds of subject each
applies to). A request names its subject the way every object request does --
'package', and 'object' for one object of it, 'kind' when the caller knows it --
and the state it is asked at the way every reference names one: after an '@'
('//pkg@v1.2', '//pkg@STAGED'), or with 'from' and 'to' for a comparison.

The work is PartCAD's (see 'partcad.changes', 'partcad.revisions',
'partcad.working_copy', 'partcad.usage' and 'partcad.impact'); what is here is
reading the request, refusing what does not apply, and the checks a new
revision runs, which build shapes and so are the daemon's to run.
"""

import asyncio

from partcad_utils import ops_views

from .operations import (
    USAGE_ERROR,
    JsonRpcError,
    _ctx,
    _invalidate_context,
    _package_of_request,
    _qualified,
    _resolve_object,
    _said_kind,
)


def _subject(ctx, pc, params, method: str):
    """(the package, the kind, the object's name or None) a request is about; refused where 'method' does not apply.

    An object when the request names one ('object'), its kind as said or as
    looked up; the package ('package', or the one the command runs in)
    otherwise.
    """
    if params.get("object"):
        resolved = _resolve_object(ctx, pc, params)
        if resolved is None:
            raise JsonRpcError(USAGE_ERROR, "The package of %s is not found" % params.get("object"))
        package, name = resolved
        project = ctx.get_project(package)
        if project is None:
            raise JsonRpcError(USAGE_ERROR, "Package %s is not found" % package)
        name = name.partition(";")[0]
        kind = _said_kind(params)
        if kind is None or kind == ops_views.PACKAGE:
            kind = project.object_kind(name) or _kind_elsewhen(ctx, project, name, params)
        if kind is None:
            raise JsonRpcError(USAGE_ERROR, "%s declares no '%s'" % (project.name, name))
        label = _qualified(project.name, name)
    else:
        project = _package_of_request(ctx, pc, {"package": params.get("package")})
        kind, name, label = ops_views.PACKAGE, None, project.name
    why = ops_views.refusal(method, kind, label)
    if why:
        raise JsonRpcError(USAGE_ERROR, why)
    return project, kind, name


def _kind_elsewhen(ctx, project, name: str, params):
    """What 'name' is at the states the request names, or at HEAD: an object removed since is still what it was."""
    from partcad import changes, package_versions

    for state in (params.get("from"), params.get("to"), "HEAD"):
        if not isinstance(state, str) or not state or state == package_versions.WORKTREE:
            continue
        try:
            found = changes.package_at(ctx, project.name, state)
        except ValueError:
            continue
        kind = found.object_kind(name) if found is not None else None
        if kind is not None:
            return kind
    return None


def _state(params, key: str, default):
    """A state a request names under 'key' -- a commit-ish, 'STAGED' or 'WORKTREE' -- or 'default'."""
    from partcad import package_versions

    value = params.get(key)
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        raise JsonRpcError(USAGE_ERROR, "'%s' is a revision, STAGED or WORKTREE, not %r" % (key, value))
    if not package_versions.is_state(value):
        try:
            package_versions.check_revision(value)
        except ValueError as e:
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
    return value


def _named(ctx, project, state: str) -> str:
    """'state', refused unless the package's repository has such a revision (a state is always there).

    The parent of a first commit ('<sha>~1') is taken: it is nothing, an empty side.
    """
    from partcad import package_versions, revisions

    if package_versions.is_state(state):
        return state
    current = revisions.current_project(ctx, project)
    repository = package_versions.repository_of(current.config_dir) if current is not None else None
    if repository is None:
        raise JsonRpcError(
            USAGE_ERROR, "%s is not in a git repository, so it has no revision '%s'" % (current.name, state)
        )
    if package_versions.before_history(repository, state):
        # The parent of a first commit: nothing, which a comparison takes as an empty side.
        return state
    try:
        package_versions.resolve(repository, state, fetch=ctx.is_downloaded(current), user_config=ctx.user_config)
    except ValueError as e:
        raise JsonRpcError(USAGE_ERROR, str(e)) from e
    return state


def _int(params, key: str, default: int) -> int:
    value = params.get(key)
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as e:
        raise JsonRpcError(USAGE_ERROR, "'%s' is a number, not %r" % (key, value)) from e
    if number < 1:
        raise JsonRpcError(USAGE_ERROR, "'%s' is at least 1" % key)
    return number


def _subject_answer(project, kind, name) -> dict:
    return {"package": project.name, "object": _qualified(project.name, name) if name else None, "kind": kind}


def views(session, params):
    """The Operations views the subject has, each with the commands that apply to it.

    What the IDE draws the Operations group from, and 'pc ops summary' prints
    (see 'partcad_utils.ops_views'). With 'summary', one line from each view as
    well: how many revisions, what is staged and not, how many dependencies and
    users.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, kind, name = _subject(ctx, pc, params, "ops.rev.list")
    answer = {"subject": _subject_answer(project, kind, name), "views": ops_views.views_for(kind)}
    if params.get("summary"):
        answer["summary"] = _summary(ctx, project, kind, name)
    return answer


def _summary(ctx, project, kind, name) -> dict:
    from partcad import package_versions, revisions, usage, working_copy

    found = {}
    if name is None:
        listed = revisions.history(ctx, project, limit=revisions.PAGE)
    else:
        listed = revisions.object_history(ctx, project, kind, name, limit=revisions.PAGE)
    found["revisions"] = {"count": len(listed["revisions"]), "more": listed["more"], "head": listed["head"]}
    if package_versions.repository_of(project.config_dir) is not None and project.not_written_to() is None:
        try:
            status = working_copy.status(ctx, project, None if name is None else kind, name)
            found["status"] = {
                "staged": len(status["staged"]),
                "unstaged": len(status["unstaged"]),
                "branch": status["branch"],
            }
        except ValueError as e:
            found["status"] = {"error": str(e)}
    if kind in ops_views.view("dependencies")["kinds"]:
        if name is None:
            deps = usage.package_dependencies(ctx, project)
            found["dependencies"] = {
                "declared": len(deps["declared"]),
                "undeclared": len(deps["undeclared"]),
                "subpackages": len(deps["subpackages"]),
            }
        else:
            found["dependencies"] = {"objects": len(usage.object_dependencies(ctx, project, kind, name))}
    if name is None:
        found["usedBy"] = {
            "packages": len(usage.package_dependents(ctx, project)),
            "objects": len(usage.package_used_by(ctx, project.name)),
        }
    else:
        found["usedBy"] = {"objects": len(usage.object_used_by(ctx, project.name, name))}
    return found


# ---- Revisions -------------------------------------------------------------


def rev_list(session, params):
    """The revisions of the subject, newest first, a page at a time: every one of a package's, an object's own.

    A package lists every commit that changed its directory; an object, only
    the commits that changed it -- its declaration or a file it is built from --
    each with how ('partcad.revisions.object_history'). 'limit' is the size of
    a page (100), 'after' the 'next' of the page before.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, kind, name = _subject(ctx, pc, params, "ops.rev.list")
    from partcad import revisions

    limit = _int(params, "limit", revisions.PAGE)
    after = params.get("after") or None
    try:
        if name is None:
            answer = revisions.history(ctx, project, limit=limit, after=after)
        else:
            with pc.logging.Process("Revisions", project.name, name):
                answer = revisions.object_history(ctx, project, kind, name, limit=limit, after=after)
    except ValueError as e:
        # An 'after' this history does not go back through.
        raise JsonRpcError(USAGE_ERROR, str(e)) from e
    answer["kind"] = kind
    return answer


def rev_diff(session, params):
    """The subject at one state and at another, side by side and as a unified diff.

    'from' (HEAD by default) and 'to' (WORKTREE by default) are each a
    commit-ish, 'STAGED' or 'WORKTREE'. Each side is the object as 'pc copy'
    writes one, or for a package its 'partcad.yaml' as rendered, with what
    changed in it object by object ('partcad.revisions.compare_states').
    'lines' is how many lines of context the unified diff keeps.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, kind, name = _subject(ctx, pc, params, "ops.rev.diff")
    from partcad import package_versions, revisions

    before = _named(ctx, project, _state(params, "from", "HEAD"))
    after = _named(ctx, project, _state(params, "to", package_versions.WORKTREE))
    lines = params.get("lines")
    try:
        lines = revisions.UNIFIED_CONTEXT if lines is None else int(lines)
    except (TypeError, ValueError) as e:
        raise JsonRpcError(USAGE_ERROR, "'lines' is a number of lines, not %r" % (lines,)) from e
    compared_kind = revisions.PACKAGE if name is None else kind
    with pc.logging.Process("Diff", project.name, "%s..%s" % (before, after)):
        try:
            answer = revisions.compare_states(ctx, project, compared_kind, name, before, after, context=lines)
        except ValueError as e:
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
    answer["kind"] = kind
    answer["object"] = _qualified(project.name, name) if name else None
    return answer


def _writable(project):
    why = project.not_written_to()
    if why is not None:
        raise JsonRpcError(USAGE_ERROR, "%s: %s" % (project.name, why))


def rev_status(session, params):
    """What of the subject is staged and what is not, object by object, and what else in the repository is.

    See 'partcad.working_copy.status'; 'index' is what 'ops.rev.new' is told
    back as 'expect_index', and 'advice' the sentence to hand an agent.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, kind, name = _subject(ctx, pc, params, "ops.rev.status")
    from partcad import working_copy

    try:
        return working_copy.status(ctx, project, None if name is None else kind, name)
    except ValueError as e:
        raise JsonRpcError(USAGE_ERROR, str(e)) from e


def rev_stage(session, params):
    """Stage every change of the subject that is not staged: a package's own files, an object's files and declaration.

    See 'partcad.working_copy.stage'. Answers what was staged, and the status
    after it.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, kind, name = _subject(ctx, pc, params, "ops.rev.stage")
    _writable(project)
    from partcad import working_copy

    with pc.logging.Process("Stage", project.name, name or ""):
        try:
            staged = working_copy.stage(ctx, project, None if name is None else kind, name)
            staged["status"] = working_copy.status(ctx, project, None if name is None else kind, name)
        except ValueError as e:
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
    for note in staged["notes"]:
        pc.logging.warning(note)
    if staged["staged"]:
        pc.logging.info("Staged %s" % ", ".join(staged["staged"]))
    else:
        pc.logging.info("Nothing of %s was left to stage" % (staged["object"] or project.name))
    return staged


def _lint_failures(ctx, project) -> list:
    """What lint says is wrong with 'project': the messages of the checks that failed."""
    from partcad.lint.all import get_linting_checks
    from partcad.lint.lint import Severity

    async def run():
        found = []
        checks = get_linting_checks(ctx.user_config.threads_max)
        reports = await asyncio.gather(
            *[
                check.validate_cached(ctx, project, target, {})
                for check in checks
                for target in check.get_targets(ctx, project)
            ]
        )
        for report in reports:
            for level, message in report.messages:
                if level == Severity.FAILED:
                    found.append(message)
        return found

    return asyncio.run(run())


_GETTERS = ("part", "assembly", "scene", "sketch")


def _checks(ctx, pc, project, status: dict) -> list:
    """Lint the staged package, and run the qualification tests of every staged object that changed: what a new revision needs to pass."""
    from partcad import package_versions
    from partcad.qual import report

    staged = ctx.get_project(package_versions.versioned_name(project.name, package_versions.STAGED))
    if staged is None:
        return [{"name": "load", "passed": False, "summary": "the staged package could not be loaded"}]
    ran = []
    # Actions, not processes: they run inside the new revision's own process,
    # and a process is one at a time.
    with pc.logging.Action("Lint", staged.name):
        failures = _lint_failures(ctx, staged)
    ran.append(
        {
            "name": "lint",
            "passed": not failures,
            "summary": "lint passed" if not failures else "lint: %s" % "; ".join(failures[:5]),
        }
    )
    getters = {"part": ctx.get_part, "assembly": ctx.get_assembly, "scene": ctx.get_scene, "sketch": ctx.get_sketch}
    for row in status.get("staged") or []:
        if row["kind"] not in _GETTERS or "removed" in row["how"]:
            continue
        path = _qualified(staged.name, row["name"])
        shape = getters[row["kind"]](path)
        if shape is None:
            ran.append(
                {
                    "name": "qual test",
                    "object": row["object"],
                    "passed": False,
                    "summary": "%s could not be loaded" % path,
                }
            )
            continue
        with pc.logging.Action("Qual", staged.name, row["name"]):
            results = asyncio.run(report.run_async(ctx, shape, verify=True))
        failed = [result.name for result in results if result.status == report.FAILED]
        ran.append(
            {
                "name": "qual test",
                "object": row["object"],
                "passed": not failed,
                "summary": "%s: %s" % (row["object"], "passed" if not failed else "failed " + ", ".join(failed)),
            }
        )
    return ran


def rev_new(session, params):
    """Commit what is staged as a new revision of the subject.

    Refused -- with 'data.code' saying why and 'data.status' what is staged --
    when nothing of the subject is staged ('nothing-staged'), when something
    else is staged and 'include_others' does not agree to it
    ('others-staged'), when changes of the subject are not staged or were
    changed again since and 'yes' does not agree to that ('warnings'), when the
    index is not the one 'expect_index' names, or moved while the checks ran
    ('index-changed'), when HEAD moved meanwhile ('head-moved'), when git did
    not say which revision it made ('unidentified'), and when lint
    or the qualification tests of what is staged fail ('checks-failed'), which
    'skip_checks' does not run. 'author' ({'name', 'email'}) is who the client
    says the user is, and is required whole: the daemon's own git identity is
    not the user's.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, kind, name = _subject(ctx, pc, params, "ops.rev.new")
    _writable(project)
    from partcad import working_copy

    author = params.get("author") if isinstance(params.get("author"), dict) else None
    checks = None if params.get("skip_checks") else (lambda status: _checks(ctx, pc, project, status))
    with pc.logging.Process("Revision", project.name, name or ""):
        try:
            made = working_copy.new_revision(
                ctx,
                project,
                params.get("message") or "",
                None if name is None else kind,
                name,
                author=author,
                expect_index=params.get("expect_index") or None,
                include_others=bool(params.get("include_others")),
                accept=bool(params.get("yes")),
                checks=checks,
                author_required=True,
            )
        except working_copy.Refused as e:
            raise JsonRpcError(USAGE_ERROR, str(e), data={"code": e.code, "status": e.status}) from e
        except ValueError as e:
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
    for entry in made["checks"]:
        pc.logging.info(entry["summary"])
    pc.logging.info("Made the revision %s: %s" % (made["short"], made["summary"]))
    if made.get("hooks_changed"):
        pc.logging.warning("The repository's hooks changed what was committed: %s" % ", ".join(made["hooks_changed"]))
    return made


# ---- Dependencies ----------------------------------------------------------


def deps_list(session, params):
    """What the subject depends on: a package's declared and undeclared dependencies and sub-packages, an object's references.

    At a revision ('//pkg@v1.2') as at the working tree. See
    'partcad.usage.package_dependencies' and 'object_dependencies'. Asking
    what kind each object is, or which commit a dependency is at, may download
    the package it is in.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, kind, name = _subject(ctx, pc, params, "ops.deps.list")
    from partcad import usage

    with pc.logging.Process("Dependencies", project.name, name or ""):
        if name is None:
            answer = usage.package_dependencies(ctx, project)
        else:
            try:
                answer = {"dependencies": usage.object_dependencies(ctx, project, kind, name)}
            except ValueError as e:
                raise JsonRpcError(USAGE_ERROR, str(e)) from e
    answer.update(_subject_answer(project, kind, name))
    return answer


def _dependency_name(params) -> str:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise JsonRpcError(USAGE_ERROR, "No dependency is named")
    return name


def deps_add(session, params):
    """Declare a dependency of a package: 'name', 'location' (a path, a git URL, a tarball URL) and, for git, 'track'.

    What 'pc add dep' did (see 'Project.add_import'): a git dependency is
    pinned to the commit its branch is at now.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, _kind, _name = _subject(ctx, pc, params, "ops.deps.add")
    _writable(project)
    name = _dependency_name(params)
    location = params.get("location")
    if not isinstance(location, str) or not location:
        raise JsonRpcError(USAGE_ERROR, "No location is given for %s" % name)
    with pc.logging.Process("AddDep", project.name, name):
        added = project.add_import(name, location, track=params.get("track") or None)
    if not added:
        raise JsonRpcError(USAGE_ERROR, "%s was not added to %s" % (name, project.name))
    _invalidate_context(session, params)
    return {"package": project.name, "name": name, "added": True}


def deps_remove(session, params):
    """Take a dependency out of a package's declaration, naming the objects of it that still use it."""
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    project, _kind, _name = _subject(ctx, pc, params, "ops.deps.remove")
    _writable(project)
    name = _dependency_name(params)
    from partcad import usage
    from partcad.context import _dependency_package_name

    declared = project.dependencies() or {}
    if name not in declared:
        raise JsonRpcError(USAGE_ERROR, "%s declares no dependency '%s'" % (project.name, name))
    dependency = _dependency_package_name(project.name, name, declared[name])
    users = [
        row["object"]
        for row in usage.used_by(ctx, lambda package, _object: usage._is_within(package, dependency))
        if row["package"] == project.name
    ]
    with pc.logging.Process("RemoveDep", project.name, name):
        removed = project.remove_import(name)
    if not removed:
        raise JsonRpcError(USAGE_ERROR, "%s was not removed from %s" % (name, project.name))
    if users:
        pc.logging.warning("Still used by %s, which will not load until they use something else" % ", ".join(users))
    _invalidate_context(session, params)
    return {"package": project.name, "name": name, "removed": True, "users": users}


def deps_update(session, params):
    """Move tracked dependencies' pins to the tip of their branches, then fetch every import again.

    Of the package the request names, and of only the dependencies 'names'
    lists when it lists any; with 'all', of every package of the workspace,
    which is what 'pc update' did.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    names = params.get("names") or None
    if names is not None and (not isinstance(names, list) or not all(isinstance(each, str) for each in names)):
        raise JsonRpcError(USAGE_ERROR, "'names' is a list of dependency names")
    package = None
    if not params.get("all"):
        project, _kind, _name = _subject(ctx, pc, params, "ops.deps.update")
        _writable(project)
        from partcad.actions.package.update import workspace_packages

        if project.name not in {each.name for each in workspace_packages(ctx)}:
            raise JsonRpcError(
                USAGE_ERROR,
                "%s is imported, not a package of this workspace: its pins are moved by its own maintainers, not"
                " from here" % project.name,
            )
        package = project.name
    with pc.logging.Process("Update", package or "this"):
        stats = pc.actions.package.update(ctx, package=package, names=names)
    if stats["pinned"] or stats["current"]:
        pc.logging.info(
            "Pinned %d tracked dependencies to the tip of their branch, %d were there already"
            % (stats["pinned"], stats["current"])
        )
    if stats["failed"]:
        pc.logging.error("Failed to update %d tracked dependencies" % stats["failed"])
    _invalidate_context(session, params)
    return {**stats, "package": package}


# ---- Used By and Impact ----------------------------------------------------


def _load(pc, ctx, params):
    if params.get("load"):
        from partcad import usage

        with pc.logging.Process("Load", ctx.name):
            usage.load_workspace(ctx)


def used_by(session, params):
    """What uses the subject, among what the context has loaded.

    An object: the objects that refer to it, each with how and how many times.
    A package: the packages that declare it as a dependency, each with the
    revision it pins and how far that is behind, and the objects that use
    anything in it. A package at a revision ('//pkg@v1.2'): what uses it at
    that revision. 'load' loads every package of the workspace first.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    _load(pc, ctx, params)
    project, kind, name = _subject(ctx, pc, params, "ops.used_by")
    from partcad import revisions, usage

    answer = _subject_answer(project, kind, name)
    if name is not None:
        answer["objects"] = usage.object_used_by(ctx, project.name, name)
        return answer
    current = revisions.current_project(ctx, project)
    sha = getattr(project, "revision_sha", None)
    if current is not project and sha:
        answer["package"] = current.name
        answer["revision"] = sha
        answer["packages"] = []
        answer["objects"] = usage.revision_used_by(ctx, current.name, sha)
        return answer
    answer["packages"] = usage.package_dependents(ctx, project)
    answer["objects"] = usage.package_used_by(ctx, project.name)
    return answer


def _at(ctx, getter, row, state: str):
    """The object of a reached row at 'state' -- as loaded for 'WORKTREE'."""
    from partcad import package_versions

    package = (
        row["package"] if state == package_versions.WORKTREE else package_versions.versioned_name(row["package"], state)
    )
    return getter(_qualified(package, row["name"]))


def _measure(ctx, before: str, after: str):
    """How much a changed part or assembly moved: 'pc compare' of it at 'before' against it at 'after'.

    Each row says the states its own package is compared at: a package of
    another repository has none of the subject's, and no earlier shape of it
    is there to measure against.
    """
    from partcad import compare as pc_compare

    def measure(row):
        states = row.get("states") or {"from": before, "to": after}
        if states.get("outside"):
            return {"skipped": "not in the repository compared: there is no earlier state of it to measure against"}
        getter = ctx.get_part if row["kind"] == "part" else ctx.get_assembly
        reference = _at(ctx, getter, row, states["from"])
        current = _at(ctx, getter, row, states["to"])
        if reference is None or current is None:
            return {"error": "not there at %s" % (states["from"] if reference is None else states["to"])}
        report = asyncio.run(pc_compare.compare_async(ctx, reference, current, limits={}, worst=0))
        return {key: report.get(key) for key in ("volume", "mass", "passed") if key in report}

    return measure


def _test(ctx, after: str):
    """The qualification tests of a reached object, run at the state its row says -- 'after' in the subject's repository.

    An object of another repository is tested as it is loaded: the subject's
    states are not states of its repository.
    """
    from partcad.qual import report

    def test(row):
        getters = {"part": ctx.get_part, "assembly": ctx.get_assembly, "scene": ctx.get_scene, "sketch": ctx.get_sketch}
        if row["kind"] not in getters:
            return {"skipped": "not tested"}
        states = row.get("states") or {"to": after}
        shape = _at(ctx, getters[row["kind"]], row, states["to"])
        if shape is None:
            return {"error": "could not be loaded"}
        results = asyncio.run(report.run_async(ctx, shape, verify=True))
        failed = [result.name for result in results if result.status == report.FAILED]
        return {"passed": not failed, "failed": failed}

    return test


def impact(session, params):
    """What a change reaches: of the subject's repository from 'from' to 'to', for a package or one object.

    'from' (HEAD) and 'to' (WORKTREE) are each a commit-ish, 'STAGED' or
    'WORKTREE': HEAD to STAGED is what is staged, STAGED to WORKTREE what is
    not. Looks where Used By looks -- the loaded context, the workspace after
    'load'. 'measure' measures how much each changed shape moved, 'test' runs
    the qualification tests of every object reached; both build shapes. See
    'partcad.impact'.
    """
    ctx = _ctx(session, params)
    if ctx is None:
        return None
    pc = session.partcad
    _load(pc, ctx, params)
    project, kind, name = _subject(ctx, pc, params, "ops.impact")
    from partcad import impact as pc_impact
    from partcad import package_versions

    before = _named(ctx, project, _state(params, "from", "HEAD"))
    after = _named(ctx, project, _state(params, "to", package_versions.WORKTREE))
    with pc.logging.Process("Impact", project.name, "%s..%s" % (before, after)):
        try:
            return pc_impact.impact(
                ctx,
                project,
                None if name is None else kind,
                name,
                before=before,
                after=after,
                measure=_measure(ctx, before, after) if params.get("measure") else None,
                test=_test(ctx, after) if params.get("test") else None,
            )
        except ValueError as e:
            raise JsonRpcError(USAGE_ERROR, str(e)) from e
