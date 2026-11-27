#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What every `pc ops` command shares: its subject, its states, and how it prints what the daemon answers.

The IDE's Operations tabs on the command line -- Revisions, Dependencies, Used
By and Impact. Each command is about one subject: an object, or with no OBJECT
(or one written as a package path, `//pub/std`) a whole package -- the package
`-P` selects, or this one. Each asks one daemon method (`ops.*`, see
`partcad_utils.ops_views`) the question the tab asks, so a terminal and the IDE
cannot come to disagree. What stays here is printing: a table a person reads,
`--json` for a script, and for `diff` the unified diff the daemon writes,
coloured on a terminal that wants colour.

Client side only, so nothing here imports `partcad` (see "Command boundary" in
`src/partcad_cli/AGENTS.md`).
"""

import datetime
import json

import rich_click as click

from . import object_kind

PACKAGE = "package"


def target_options(command):
    """-P, and the flags saying what kind of object OBJECT is, for a command whose OBJECT may be left out."""
    for option in reversed(
        (
            click.option(
                "--package",
                "-P",
                type=str,
                default="",
                show_envvar=True,
                help="Package to find the object in, or the package itself when no OBJECT is given",
            ),
            click.option("--interface", "-i", is_flag=True, help=object_kind.flag_help("an interface")),
            click.option("--assembly", "-a", is_flag=True, help=object_kind.flag_help("an assembly")),
            click.option("--scene", "-S", is_flag=True, help=object_kind.flag_help("a scene")),
            click.option("--sketch", "-s", is_flag=True, help=object_kind.flag_help("a sketch")),
        )
    ):
        command = option(command)
    return command


def _names_a_package(name: str) -> bool:
    """Whether OBJECT is written as a package path -- '//pub/std', './sub', '//pkg@v1' -- rather than as an object."""
    return ":" not in name and (name.startswith("//") or name.startswith("./") or name.startswith("../") or name == ".")


def target_params(package, interface, assembly, scene, sketch, object) -> dict:
    """The request's object, its kind when a flag said it -- or, with no OBJECT, the package as the subject."""
    said = [
        kind
        for kind, flag in (("interface", interface), ("assembly", assembly), ("scene", scene), ("sketch", sketch))
        if flag
    ]
    if len(said) > 1:
        raise click.UsageError("OBJECT is one kind of object: %s" % ", ".join("--" + kind for kind in said))
    if object and _names_a_package(object):
        if package:
            raise click.UsageError("%s is a package, and -P names another" % object)
        package, object = object, None
    if not object:
        if said:
            raise click.UsageError("--%s says what OBJECT is, and no OBJECT is given" % said[0])
        return {"package": package or ".", "kind": PACKAGE}
    params = {"package": package, "object": object}
    if said:
        params["kind"] = said[0]
    return params


def state_options(command):
    """--from, --to, --staged, --unstaged and --since: the two states a comparison is between."""
    for option in reversed(
        (
            click.option("--from", "from_state", type=str, default=None, help="The state to compare from (HEAD)"),
            click.option("--to", "to_state", type=str, default=None, help="The state to compare to (WORKTREE)"),
            click.option("--staged", is_flag=True, help="What is staged: --from HEAD --to STAGED"),
            click.option("--unstaged", is_flag=True, help="What is not staged: --from STAGED --to WORKTREE"),
            click.option(
                "--since", type=str, default=None, help="Everything since a revision: --from REV --to WORKTREE"
            ),
        )
    ):
        command = option(command)
    return command


def state_params(from_state, to_state, staged, unstaged, since) -> dict:
    """The 'from' and 'to' a request carries, from whichever way the command line said them."""
    said = [name for name, value in (("--staged", staged), ("--unstaged", unstaged), ("--since", since)) if value]
    if len(said) > 1 or (said and (from_state or to_state)):
        raise click.UsageError("%s say the states twice: give one of them" % ", ".join(said + ["--from/--to"]))
    if staged:
        return {"from": "HEAD", "to": "STAGED"}
    if unstaged:
        return {"from": "STAGED", "to": "WORKTREE"}
    if since:
        return {"from": since, "to": "WORKTREE"}
    found = {}
    if from_state:
        found["from"] = from_state
    if to_state:
        found["to"] = to_state
    return found


def _when(seconds) -> str:
    """A commit time as a person reads it, in this machine's own time zone."""
    if not seconds:
        return ""
    try:
        return datetime.datetime.fromtimestamp(int(seconds)).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def echo_json(result) -> None:
    click.echo(json.dumps(result, indent=2))


def subject_of(result: dict) -> str:
    return result.get("object") or result.get("package") or "it"


def print_revisions(result: dict) -> None:
    """The revisions of the subject, newest first: '*' before the one checked out, how an object changed in each."""
    if not result.get("published"):
        click.echo("%s is not published yet: it has no commits in a git repository" % result.get("package"))
        return
    head = result.get("head")
    rows = result.get("revisions") or []
    if not rows:
        click.echo("No revision changed %s" % subject_of(result))
    for entry in rows:
        mark = "*" if entry.get("sha") == head else " "
        notes = []
        if entry.get("how"):
            notes.append(", ".join(entry["how"]))
        if entry.get("in"):
            notes.append("in " + ", ".join(entry["in"]))
        click.echo(
            "%s %s  %s  %s  %s%s"
            % (
                mark,
                entry.get("short"),
                _when(entry.get("time")),
                entry.get("author") or "",
                entry.get("summary"),
                "  (%s)" % "; ".join(notes) if notes else "",
            )
        )
    if result.get("more") and rows:
        click.echo("... more: --after %s" % rows[-1].get("sha"))


def wants_color() -> bool:
    """Whether the diff is coloured: on a terminal (click decides that), and not under the global '--no-ansi'."""
    context = click.get_current_context(silent=True)
    root = context.find_root() if context is not None else None
    return not (root is not None and root.params.get("no_ansi"))


def print_unified(text: str) -> None:
    """A unified diff, coloured the way 'git diff' colours one where colour is wanted."""
    color = wants_color()
    for line in (text or "").splitlines():
        if not color:
            click.echo(line)
        elif line.startswith(("+++", "---")):
            click.echo(click.style(line, bold=True))
        elif line.startswith("@@"):
            click.echo(click.style(line, fg="cyan"))
        elif line.startswith("+"):
            click.echo(click.style(line, fg="green"))
        elif line.startswith("-"):
            click.echo(click.style(line, fg="red"))
        else:
            click.echo(line)


def _object_rows(rows: list, indent: str = "  ") -> None:
    for row in rows:
        click.echo(
            "%s%-9s  :%-24s  %s" % (indent, row.get("kind") or "", row.get("name"), ", ".join(row.get("how") or []))
        )


def print_changes(changes: dict) -> None:
    """What changed in a package object by object, and the files no object is built from."""
    if not changes:
        return
    if changes.get("objects"):
        click.echo("Objects:")
        _object_rows(changes["objects"])
    if changes.get("files"):
        click.echo("Other files:")
        for entry in changes["files"]:
            click.echo("  %-9s  %s" % (entry.get("how"), entry.get("path")))
    if changes.get("package_changed"):
        click.echo("The package's own declaration changed")


def print_status(result: dict) -> None:
    """What is staged and what is not, by object, and what else of the repository is."""
    where = result.get("branch") or ("detached at %s" % (result.get("head") or "")[:8])
    click.echo("%s   %s" % (subject_of(result), where))
    for title, rows in (
        ("Staged -- in a new revision:", result.get("staged")),
        ("Not staged -- not in it:", result.get("unstaged")),
    ):
        if rows:
            click.echo(title)
            _object_rows(rows)
    loose = [
        entry
        for entry in result.get("files") or []
        if result.get("own_files") is None or entry["path"] in result["own_files"]
    ]
    if loose:
        click.echo("Files:")
        for entry in loose:
            click.echo("  %-20s  %s" % (", ".join(entry.get("sections") or []), entry.get("path")))
    if result.get("partial"):
        click.echo("Changed again since they were staged: %s" % ", ".join(":" + name for name in result["partial"]))
    others = [row["object"] for row in result.get("others_staged") or []]
    elsewhere = [entry for entry in result.get("elsewhere") or [] if entry.get("staged") or entry.get("unstaged")]
    if others or elsewhere:
        click.echo("Elsewhere in this repository:")
        for name in others:
            click.echo("  staged      %s" % name)
        for entry in elsewhere:
            click.echo(
                "  %-10s  %s"
                % (
                    "staged" if entry.get("staged") else "not staged",
                    entry.get("package") or entry.get("directory") or "files in no package",
                )
            )
    if result.get("advice"):
        click.echo("")
        click.echo("To stage it, run 'pc ops rev stage', or ask your agent:")
        click.echo('  "%s"' % result["advice"])


def print_package_dependencies(result: dict) -> None:
    """A package's declared dependencies, what it uses without declaring, and its sub-packages."""
    declared = result.get("declared") or []
    if declared:
        click.echo("Declared:")
        width = max(len(row.get("name") or "") for row in declared)
        for row in declared:
            pinned = (row.get("pinned") or "")[:8]
            click.echo(
                "  %s  %-6s  %-8s  %s%s"
                % (
                    (row.get("name") or "").ljust(width),
                    row.get("type") or "",
                    row.get("short") or pinned or "-",
                    row.get("location") or row.get("package") or "",
                    "  (tracks %s)" % row["track"] if row.get("track") else "",
                )
            )
    else:
        click.echo("%s declares no dependencies" % result.get("package"))
    if result.get("undeclared"):
        click.echo("Used, not declared:")
        for row in result["undeclared"]:
            click.echo(
                "  %s  (by %s)" % (row["package"], ", ".join(":" + user["name"] for user in row.get("users") or []))
            )
    if result.get("subpackages"):
        click.echo("Sub-packages:")
        for row in result["subpackages"]:
            click.echo("  %s" % row.get("package"))


def print_object_dependencies(result: dict) -> None:
    """What an object names, and places: how, how many times, and the commit the package it comes from is at."""
    rows = result.get("dependencies") or []
    if not rows:
        click.echo("%s names no other object" % subject_of(result))
        return
    for row in rows:
        click.echo(
            "%4d  %-9s  %-40s  %-20s  %s"
            % (
                row.get("count") or 0,
                row.get("kind") or "",
                row.get("object"),
                ", ".join(row.get("how") or []),
                row.get("short") or "",
            )
        )


def print_used_by(result: dict, what: str) -> None:
    """The packages that declare the subject a dependency, and the loaded objects that use it."""
    for row in result.get("packages") or []:
        behind = row.get("behind")
        click.echo(
            "package  %-30s  %-6s  %s%s"
            % (
                row.get("package"),
                row.get("type") or "",
                row.get("short") or "",
                "  (%d revisions behind)" % behind if isinstance(behind, int) and behind else "",
            )
        )
    rows = result.get("objects") or []
    if not rows and not result.get("packages"):
        click.echo("Nothing PartCAD has loaded uses %s" % what)
        return
    for row in rows:
        click.echo(
            "%4d  %-9s  %-40s  %s"
            % (row.get("count") or 0, row.get("kind") or "", row.get("object"), ", ".join(row.get("how") or []))
        )


def print_impact(result: dict) -> None:
    """What a change reaches: each object with how it is reached and its findings, then the pins."""
    summary = result.get("summary") or {}
    changed = result.get("changed") or []
    click.echo(
        "%s, %s to %s: %d object%s changed, %d reached"
        % (
            subject_of(result),
            result.get("from"),
            result.get("to"),
            len(changed),
            "" if len(changed) == 1 else "s",
            len(result.get("affects") or []),
        )
    )
    if summary:
        click.echo(
            "  "
            + ", ".join(
                "%d %s" % (summary[key], key) for key in ("breaking", "changed", "verify", "info") if summary.get(key)
            )
        )
    for row in result.get("affects") or []:
        reached = "changed" if row.get("reached") == "changed" else "via " + " -> ".join(row.get("via") or [])
        click.echo("  %-9s  %-40s  %s" % (row.get("kind") or "", row.get("object"), reached))
        for finding in row.get("findings") or []:
            click.echo("      %-8s  %s" % (finding.get("severity"), finding.get("summary")))
    if result.get("affected_by"):
        click.echo("Affected by:")
        for row in result["affected_by"]:
            click.echo("  %-40s  via %s" % (row.get("object"), " -> ".join(row.get("path") or [])))
    if result.get("pins"):
        click.echo("Dependencies whose declaration changed:")
        for row in result["pins"]:
            click.echo(
                "  %-20s  %s  %s -> %s"
                % (row["name"], row["how"], (row.get("from") or "-")[:8], (row.get("to") or "-")[:8])
            )
    if result.get("pinned"):
        click.echo("Pinned to an older revision, so not affected until they update:")
        for row in result["pinned"]:
            behind = row.get("behind")
            click.echo(
                "  %-30s  pins %s%s"
                % (
                    row.get("package"),
                    row.get("short") or "-",
                    " (%d revisions behind)" % behind if isinstance(behind, int) else "",
                )
            )


def run_subject(cli_ctx, method: str, target: tuple, extra: dict = None):
    """Ask 'method' about the subject 'target' -- (package, the four kind flags, OBJECT) -- with 'extra' params."""
    from .service import run

    request = {**target_params(*target), **(extra or {})}
    result = run(cli_ctx, method, request, needs_context=True)
    if result is None:
        raise click.ClickException("The daemon gave no answer")
    return result
