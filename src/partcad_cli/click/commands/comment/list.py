#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc comment list` -- the threads of comments on an object, or on the package.

    pc comment list bracket
    pc comment list                 # the package's own
    pc comment list bracket --json  # as 'comment.list' answers it

Each thread is shown with the index `pc comment add --reply` names it by, what it
is about, and every comment of it oldest first. Daemon work (`comment.list`).
"""

import json
import sys

import rich_click as click

from ... import object_kind
from ...service import run
from .add import KINDS


def _indented(text: str, by: str) -> str:
    return "\n".join(by + line if line else line for line in text.splitlines())


def describe(found: dict) -> str:
    """One object's threads, as the command prints them."""
    what = found.get("object") or ""
    kind = found.get("kind")
    heading = "%s (%s)" % (what, kind) if kind else "The package %s" % what
    if found.get("error"):
        return "%s: %s" % (what, found["error"])
    threads = found.get("threads") or []
    lines = ["%s: %s" % (heading, "%d thread(s)" % len(threads) if threads else "no comments")]
    for thread in threads:
        lines.append("  [%d] on %s" % (thread.get("index", 0), thread.get("about") or "the whole object"))
        for comment in thread.get("comments") or []:
            lines.append("    %s, %s:" % (comment.get("name") or "?", comment.get("date") or "?"))
            lines.append(_indented(comment.get("text") or "", "      "))
            for attachment in comment.get("attachments") or []:
                lines.append("      Attached: %s" % attachment)
    return "\n".join(lines)


@click.command(
    help="List the threads of comments on OBJECT -- or, without OBJECT, on the package. " + object_kind.LOOKED_UP
)
@click.option("--json", "api", is_flag=True, help="Print what the daemon answered, as JSON")
@click.option("--package", "-P", type=str, default="", show_envvar=True, help="Package to find the object in")
@click.option("--assembly", "-a", is_flag=True, help=object_kind.flag_help("an assembly"))
@click.option("--scene", "-S", is_flag=True, help=object_kind.flag_help("a scene"))
@click.option("--sketch", "-s", is_flag=True, help=object_kind.flag_help("a sketch"))
@click.option("--interface", "-i", is_flag=True, help=object_kind.flag_help("an interface"))
@click.option("--kind", type=click.Choice(KINDS), default=None, help="The kind of the object, for any kind")
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, api, package, assembly, scene, sketch, interface, kind, object):
    said = [name for name, flag in (("assembly", assembly), ("scene", scene), ("sketch", sketch)) if flag]
    if interface:
        said.append("interface")
    if kind:
        said.append(kind)
    if len(set(said)) > 1:
        raise click.UsageError("The object is one kind of object, and %s are named" % " and ".join(said))
    params = {"package": package}
    if object:
        params["object"] = object
        if said:
            params["kind"] = said[0]
    elif said:
        raise click.UsageError("A kind is said of an object, and none is named")
    result = run(cli_ctx, "comment.list", params, needs_context=True)
    if result is None:
        return
    if api:
        sys.stdout.write(json.dumps(result, indent=4) + "\n")
    else:
        sys.stdout.write("\n\n".join(describe(found) for found in (result.get("objects") or {}).values()) + "\n")
    sys.stdout.flush()
