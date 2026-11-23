#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc ops rev` and `pc ops used-by` share: what they are about, and how they print what the daemon answers.

The IDE's Operations tabs on the command line. Every one of them is about an
object or, with no OBJECT, a whole package -- the package `-P` selects, or this
one -- and asks one daemon method (`revisions.list`, `revisions.compare`,
`revisions.uses`, `revisions.used_by`, `usage.used_by`) the question the tab
asks, so a terminal and the IDE cannot come to disagree. What stays here is
printing: a table a person reads, `--json` for a script, and for `diff` the
unified diff the daemon writes, coloured on a terminal that wants colour.

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


def target_params(package, interface, assembly, scene, sketch, object) -> dict:
    """The request's object, its kind when a flag said it -- or, with no OBJECT, the package as the subject."""
    said = [
        kind
        for kind, flag in (("interface", interface), ("assembly", assembly), ("scene", scene), ("sketch", sketch))
        if flag
    ]
    if len(said) > 1:
        raise click.UsageError("OBJECT is one kind of object: %s" % ", ".join("--" + kind for kind in said))
    if not object:
        if said:
            raise click.UsageError("--%s says what OBJECT is, and no OBJECT is given" % said[0])
        return {"package": package or ".", "kind": PACKAGE}
    params = {"package": package, "object": object}
    if said:
        params["kind"] = said[0]
    return params


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


def print_revisions(result: dict) -> None:
    """The commits that changed the package, newest first: '*' before the one checked out."""
    if not result.get("published"):
        click.echo("%s is not published yet: it has no commits in a git repository" % result.get("package"))
        return
    head = result.get("head")
    for entry in result.get("revisions") or []:
        mark = "*" if entry.get("sha") == head else " "
        click.echo(
            "%s %s  %s  %s  %s"
            % (mark, entry.get("short"), _when(entry.get("time")), entry.get("author") or "", entry.get("summary"))
        )


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


def print_dependencies(result: dict) -> None:
    """The dependencies a package declares at a revision: the name it declares, the commit, what loads it there."""
    rows = result.get("dependencies") or []
    if not rows:
        click.echo("%s declares no dependencies at %s" % (result.get("package"), (result.get("revision") or "")[:8]))
        return
    width = max(len(row.get("name") or "") for row in rows)
    for row in rows:
        click.echo(
            "%s  %s  %s"
            % (
                (row.get("name") or "").ljust(width),
                (row.get("short") or "-").ljust(8),
                row.get("versioned") or row.get("package"),
            )
        )


def print_used_by(result: dict, what: str) -> None:
    """The loaded objects that use something: how many times, the kind and the object."""
    rows = result.get("objects") or []
    if not rows:
        click.echo("Nothing PartCAD has loaded uses %s" % what)
        return
    for row in rows:
        click.echo("%4d  %-9s  %s" % (row.get("count") or 0, row.get("kind") or "", row.get("object")))
