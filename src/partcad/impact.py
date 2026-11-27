#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a change reaches, and what each object it reaches now risks: Impact.

A change is what happened between two states of the subject's repository (see
'partcad.package_versions'): HEAD to STAGED (what is staged), STAGED to WORKTREE
(what is not), HEAD to WORKTREE (everything not committed yet), a revision to
WORKTREE (everything since). Every package of that repository the context has
loaded is compared at both ('partcad.changes'), and then, in two directions:

* **Affects** -- the objects that changed, then everything that uses them,
  transitively: the closure of Used By ('partcad.usage');
* **Affected by** -- for an object, what it uses that changed: the closure of
  its Dependencies; and the dependencies whose pins moved.

Impact looks where Used By looks: the whole loaded context. A dependent that
pins the subject's package by git commit is not affected until it moves its pin,
so it is listed apart ('pinned').

Each object reached gets findings, from analyzers each with a severity and a
cost ('ANALYZERS'): a reference that no longer resolves is *breaking*, a shape
that moved is *changed*, an object with requirements or tests is to *verify*,
and a change of prose alone is *info*. The cheap ones run every time; 'measure'
(how much a shape moved) and 'test' (running the tests) are callables a caller
passes in, because they build shapes and run wrappers, which is the daemon's to
do.
"""

import os
import typing

from partcad_utils.object_names import NAMED_KINDS

from . import changes as pc_changes
from . import logging as pc_logging
from . import package_versions, usage

BREAKING = "breaking"
CHANGED = "changed"
VERIFY = "verify"
INFO = "info"
SEVERITIES = (BREAKING, CHANGED, VERIFY, INFO)

# The analyzers that run on every object reached, and what each costs: only the
# ones that read declarations run unasked.
ANALYZERS = {
    "references": {"cost": "declarations", "severities": [BREAKING]},
    "interfaces": {"cost": "declarations", "severities": [BREAKING, CHANGED]},
    "geometry": {"cost": "declarations; with measure, builds both states", "severities": [CHANGED]},
    "requirements": {"cost": "declarations; with test, runs the tests", "severities": [VERIFY]},
    "outputs": {"cost": "files", "severities": [VERIFY]},
    "prose": {"cost": "declarations", "severities": [INFO]},
}

# What is written next to an object from it: rendered pictures and drawings,
# exported files checked in beside the package.
_OUTPUT_EXTENSIONS = (".png", ".svg", ".jpg", ".jpeg", ".gif", ".pdf", ".dxf", ".stl", ".step", ".3mf", ".glb", ".gltf")

# How deep the closure of what uses what is followed.
_DEPTH = 16


def _key(package: str, name: str) -> str:
    return pc_changes.qualified(package, name)


def repository_packages(ctx, project) -> list:
    """The loaded packages whose files are in the repository the package 'project' is in -- 'project' first."""
    repository = package_versions.repository_of(project.config_dir)
    if repository is None:
        return [project]
    workdir = os.path.realpath(repository.repo.workdir)
    found = [project]
    for loaded in usage._loaded_projects(ctx):
        if loaded is project or loaded.name == project.name:
            continue
        directory = os.path.realpath(getattr(loaded, "config_dir", "") or "")
        if directory == workdir or directory.startswith(workdir.rstrip(os.sep) + os.sep):
            if package_versions.exported_sha(directory) is None and not ctx.is_downloaded(loaded):
                found.append(loaded)
    return found


def changed_objects(ctx, project, before: str, after: typing.Optional[str]) -> dict:
    """Every object of the repository's loaded packages that changed from 'before' to 'after', by its full name."""
    found = {}
    for package in repository_packages(ctx, project):
        try:
            compared = pc_changes.changes(ctx, package.name, before, after)
        except ValueError as e:
            pc_logging.debug("%s: %s" % (package.name, e))
            continue
        for row in compared["objects"]:
            found[row["object"]] = {**row, "package": package.name}
    return found


def _config(project, kind: str, name: str) -> dict:
    if project is None:
        return {}
    try:
        config = project.object_config(kind, name)
    except Exception:  # pylint: disable=broad-except
        return {}
    return config if isinstance(config, dict) else {}


def _parameters(config: dict) -> dict:
    found = config.get("parameters") or {}
    return found if isinstance(found, dict) else {}


def _parameter_type(value) -> typing.Optional[str]:
    if isinstance(value, dict):
        declared = value.get("type")
        if declared:
            return str(declared)
        value = value.get("default")
    return type(value).__name__ if value is not None else None


def _passes(ctx, user: dict, parameter: str) -> bool:
    """Whether the declaration of a user of an object writes a value for 'parameter' into a name it gives it."""
    loaded = ctx.get_project(user["package"])
    raw = (getattr(loaded, "_object_configs", {}) or {}).get(user["kind"], {}).get(user["name"]) if loaded else None
    if isinstance(raw, dict) and isinstance(raw.get("with"), dict) and parameter in raw["with"]:
        # An enrich sets its source's parameters under 'with:'.
        return True
    text = repr(raw)
    return (";%s=" % parameter) in text or (",%s=" % parameter) in text


def _finding(severity: str, analyzer: str, summary: str, **detail) -> dict:
    return {"severity": severity, "analyzer": analyzer, "summary": summary, **detail}


def _references(ctx, row: dict, before, after, users: list) -> list:
    """Breaking: an object gone while used, a parameter gone or retyped while passed, a reference that no longer resolves."""
    found = []
    if pc_changes.REMOVED in row.get("how", []) and users:
        found.append(
            _finding(
                BREAKING,
                "references",
                "removed while %d object%s use%s it"
                % (len(users), "" if len(users) == 1 else "s", "s" if len(users) == 1 else ""),
                users=[user["object"] for user in users],
            )
        )
        return found
    old = _parameters(_config(before, row["kind"], row["name"]))
    new = _parameters(_config(after, row["kind"], row["name"]))
    for parameter in sorted(set(old) - set(new)):
        passing = [user["object"] for user in users if _passes(ctx, user, parameter)]
        found.append(
            _finding(
                BREAKING if passing else CHANGED,
                "references",
                "parameter '%s' removed%s"
                % (
                    parameter,
                    "; %s pass%s it" % (", ".join(passing), "es" if len(passing) == 1 else "") if passing else "",
                ),
                users=passing,
            )
        )
    for parameter in sorted(set(old) & set(new)):
        if _parameter_type(old[parameter]) != _parameter_type(new[parameter]):
            passing = [user["object"] for user in users if _passes(ctx, user, parameter)]
            if passing:
                found.append(
                    _finding(
                        BREAKING,
                        "references",
                        "parameter '%s' is now %s; %s pass it"
                        % (parameter, _parameter_type(new[parameter]), ", ".join(passing)),
                        users=passing,
                    )
                )
    if after is not None and pc_changes.DECLARATION in row.get("how", []):
        raw = (getattr(after, "_object_configs", {}) or {}).get(row["kind"], {}).get(row["name"])
        for package, name, how in usage.references_how(after, row["kind"], raw if raw is not None else {}):
            target = ctx.get_project(package)
            if target is None or target.object_kind(name) is None:
                found.append(
                    _finding(BREAKING, "references", "names %s:%s (%s), which is not there" % (package, name, how))
                )
    return found


def _interfaces(row: dict, before, after, users: list) -> list:
    """For an interface: a port gone while the interface is used is breaking; a port changed moves every mate on it."""
    if row["kind"] != "interface":
        return []
    old = _config(before, "interface", row["name"]).get("ports") or {}
    new = _config(after, "interface", row["name"]).get("ports") or {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    found = []
    for port in sorted(set(old) - set(new)):
        found.append(_finding(BREAKING if users else CHANGED, "interfaces", "port '%s' removed" % port))
    for port in sorted(set(old) & set(new)):
        if old[port] != new[port]:
            found.append(_finding(CHANGED, "interfaces", "port '%s' moved, and every mate on it" % port))
    return found


def _outputs(project, name: str, own: list) -> list:
    """Files written next to an object from it -- rendered pictures, drawings, exports -- that are now out of date."""
    if project is None:
        return []
    try:
        entries = sorted(os.listdir(project.config_dir))
    except OSError:
        return []
    found = []
    for entry in entries:
        stem, extension = os.path.splitext(entry)
        if stem == name and extension.lower() in _OUTPUT_EXTENSIONS and entry not in own:
            found.append(entry)
    return found


def _analyze(ctx, row: dict, before, after, users: list, direct: bool, measure, test) -> list:
    findings = []
    if direct:
        findings.extend(_references(ctx, row, before, after, users))
        findings.extend(_interfaces(row, before, after, users))
    if row.get("geometry"):
        summary = "shape changed" if direct else "shape changed through %s" % row.get("via", [""])[0]
        finding = _finding(CHANGED, "geometry", summary)
        if measure is not None and row["kind"] in ("part", "assembly"):
            try:
                finding["measured"] = measure(row)
            except Exception as e:  # pylint: disable=broad-except
                finding["measured"] = {"error": str(e)}
        findings.append(finding)
    elif direct and row.get("prose"):
        findings.append(_finding(INFO, "prose", "only its description, comments or other prose changed"))
    config = _config(after, row["kind"], row["name"])
    if row.get("geometry") or not direct:
        if config.get("requirements") or config.get("qual"):
            finding = _finding(VERIFY, "requirements", "its requirements and tests need running again")
            if test is not None:
                try:
                    finding["tested"] = test(row)
                except Exception as e:  # pylint: disable=broad-except
                    finding["tested"] = {"error": str(e)}
            findings.append(finding)
        stale = _outputs(after, row["name"], pc_changes.object_files(after, row["kind"], row["name"]))
        if stale:
            findings.append(
                _finding(VERIFY, "outputs", "made from it, now out of date: %s" % ", ".join(stale), files=stale)
            )
    return findings


def _users(ctx, package: str, name: str) -> list:
    try:
        return usage.object_used_by(ctx, package, name)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s:%s: could not tell what uses it: %s" % (package, name, e))
        return []


def _affects(ctx, starts: list, changed: dict, before_of, after_of, measure, test) -> list:
    """The objects 'starts' (changed rows) reach through what uses them, each with how and its findings."""
    rows = {}
    queue = []
    for row in starts:
        users = _users(ctx, row["package"], row["name"])
        entry = {**row, "reached": "changed", "via": [], "users": [user["object"] for user in users]}
        entry["findings"] = _analyze(
            ctx, entry, before_of(row["package"]), after_of(row["package"]), users, True, measure, test
        )
        rows[row["object"]] = entry
        queue.append((row["object"], users, [row["object"]], 0))
    while queue:
        source, users, path, depth = queue.pop(0)
        if depth >= _DEPTH:
            continue
        for user in users:
            key = user["object"]
            if key in rows:
                continue
            reached = changed.get(key)
            further = _users(ctx, user["package"], user["name"])
            entry = {
                "kind": user["kind"],
                "name": user["name"],
                "package": user["package"],
                "object": key,
                "how": (reached or {}).get("how", []),
                "geometry": True,
                "reached": "via",
                "via": path,
                "users": [other["object"] for other in further],
            }
            entry["findings"] = _analyze(
                ctx, entry, before_of(user["package"]), after_of(user["package"]), further, False, measure, test
            )
            rows[key] = entry
            queue.append((key, further, path + [key], depth + 1))
    return list(rows.values())


def _affected_by(ctx, project, kind: str, name: str, changed: dict) -> list:
    """What '<kind> <name>' uses, transitively, that changed: each with the path it is used through."""
    found = []
    seen = set()
    queue = [(project, kind, name, [])]
    while queue:
        owner, owner_kind, owner_name, path = queue.pop(0)
        if len(path) >= _DEPTH:
            continue
        try:
            dependencies = usage.object_dependencies(ctx, owner, owner_kind, owner_name)
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("%s:%s: could not tell what it uses: %s" % (owner.name, owner_name, e))
            continue
        for row in dependencies:
            key = row["object"]
            if key in seen:
                continue
            seen.add(key)
            here = path + [key]
            if key in changed:
                found.append({**changed[key], "path": here})
            loaded = ctx.get_project(row["package"])
            if loaded is not None and row.get("kind"):
                queue.append((loaded, row["kind"], row["name"], here))
    return found


def moved_pins(ctx, project, before: str, after: typing.Optional[str]) -> list:
    """The dependencies of the package whose declaration changed between the two states: a pin moved, a branch, a location."""
    left = pc_changes.package_at(ctx, project.name, before)
    right = pc_changes.package_at(ctx, project.name, after)
    old = (left.dependencies() or {}) if left is not None else {}
    new = (right.dependencies() or {}) if right is not None else {}
    found = []
    for name in sorted(set(old) | set(new)):
        a = old.get(name)
        b = new.get(name)
        if a == b:
            continue
        pinned_a = a.get("revision") if isinstance(a, dict) else None
        pinned_b = b.get("revision") if isinstance(b, dict) else None
        found.append(
            {
                "name": name,
                "how": (
                    "added"
                    if a is None
                    else "removed" if b is None else "pin moved" if pinned_a != pinned_b else "changed"
                ),
                "from": None if pinned_a is None else str(pinned_a),
                "to": None if pinned_b is None else str(pinned_b),
            }
        )
    return found


def impact(
    ctx,
    project,
    kind: typing.Optional[str] = None,
    name: typing.Optional[str] = None,
    before: str = "HEAD",
    after: typing.Optional[str] = None,
    measure: typing.Optional[typing.Callable[[dict], dict]] = None,
    test: typing.Optional[typing.Callable[[dict], dict]] = None,
) -> dict:
    """What the change from 'before' to 'after' reaches, for a package or one object of it.

    {'package', 'object', 'from', 'to', 'changed', 'affects', 'affected_by',
    'pins', 'pinned', 'summary'}: 'changed' is every object of the
    package that changed; 'affects' the objects reached, each with 'reached'
    ('changed' or 'via'), the path it is reached through and its findings;
    'affected_by' what an object uses that changed; 'pins' the dependencies
    whose declaration changed; 'pinned' the packages pinning this one at an
    older revision, which are not affected until they update; 'summary' how
    many findings there are of each severity.
    """
    after = after or package_versions.WORKTREE
    changed = changed_objects(ctx, project, before, after)

    def before_of(package):
        return pc_changes.package_at(ctx, package, before)

    def after_of(package):
        return pc_changes.package_at(ctx, package, after)

    if name is not None:
        name = name.partition(";")[0]
        subject = _key(project.name, name)
        starts = [changed[subject]] if subject in changed else []
        affected_by = _affected_by(ctx, project, kind, name, changed) if kind in NAMED_KINDS else []
    else:
        starts = [row for row in changed.values() if row["package"] == project.name]
        affected_by = [row for row in changed.values() if row["package"] != project.name]
    affects = _affects(ctx, starts, changed, before_of, after_of, measure, test)
    summary = {severity: 0 for severity in SEVERITIES}
    for row in affects:
        for finding in row["findings"]:
            summary[finding["severity"]] = summary.get(finding["severity"], 0) + 1
    pinned = [row for row in usage.package_dependents(ctx, project) if row.get("type") == "git"]
    return {
        "package": project.name,
        "object": _key(project.name, name) if name else None,
        "kind": kind,
        "from": before,
        "to": after,
        "changed": [row for row in changed.values() if row["package"] == project.name],
        "affects": affects,
        "affected_by": affected_by,
        "pins": moved_pins(ctx, project, before, after),
        "pinned": pinned,
        "summary": summary,
    }
