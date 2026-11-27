#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops summary [OBJECT]`: which Operations views the subject has, and one line from each.

What the IDE draws the Operations group from (`ops.views`): the views a package
or an object of that kind has, with the commands of each that apply to it --
and how many revisions, what is staged and not, how many dependencies and users.
"""

import rich_click as click

from ...operations_args import echo_json, run_subject, target_options


@click.command(
    help=(
        "Say which Operations views OBJECT -- or, with no OBJECT, the package -P selects -- has, the commands "
        "of each that apply to it, and one line from each: its revisions, what is staged, its dependencies and "
        "what uses it"
    )
)
@target_options
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, as_json, object):
    result = run_subject(cli_ctx, "ops.views", (package, interface, assembly, scene, sketch, object), {"summary": True})
    if as_json:
        echo_json(result)
        return
    subject = result.get("subject") or {}
    summary = result.get("summary") or {}
    click.echo("%s (%s)" % (subject.get("object") or subject.get("package"), subject.get("kind")))
    lines = {
        "revisions": _revisions(summary),
        "dependencies": _counts(summary.get("dependencies")),
        "usedby": _counts(summary.get("usedBy")),
        "impact": "",
    }
    for view in result.get("views") or []:
        click.echo("  %-13s %s" % (view["label"], lines.get(view["id"]) or ""))
        click.echo("  %-13s %s" % ("", ", ".join(command["command"] for command in view["commands"])))


def _revisions(summary: dict) -> str:
    found = summary.get("revisions") or {}
    text = "%d%s revisions" % (found.get("count") or 0, "+" if found.get("more") else "")
    status = summary.get("status") or {}
    if "staged" in status:
        text += "; %d staged, %d not staged" % (status["staged"], status["unstaged"])
    return text


def _counts(found) -> str:
    return ", ".join("%d %s" % (value, key) for key, value in (found or {}).items() if isinstance(value, int))
