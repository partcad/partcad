#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc comment add` -- write a comment on an object, or on the package, into its `partcad.yaml`.

    pc comment add bracket -m "This face is **too thin** to print." --ref face:12
    pc comment add bracket -m "Chamfer this." --ref 'edges("|Z").edges(">X")'          # a CadQuery selection
    pc comment add bracket -m "Thickened to 2 mm." --reply 0 --attach photos/after.jpg
    pc comment add -m "Release notes go in CHANGELOG.md from now on."      # the package itself

A comment starts a thread of its own unless `--reply` names the thread it answers,
by the index `pc comment list` shows. It is signed with the name `git config
user.name` gives on this machine -- never the daemon's, which can be on another --
and dated now, in UTC. Daemon work (`comment.add`), because it writes a
declaration the warm context then has to read again, as `pc add` does.
"""

import os
import sys

import rich_click as click

from partcad_utils import comments as pc_comments

from ... import object_kind
from ...service import run

# The kinds a comment can be written on that no flag of their own names.
KINDS = (
    "part",
    "assembly",
    "scene",
    "sketch",
    "interface",
    "software",
    "provider",
    "repository",
    "partType",
    "sketchType",
    "material",
    "color",
    "finish",
)


@click.command(
    help=(
        "Write a comment on OBJECT -- or, without OBJECT, on the package -- signed with 'git config user.name' and "
        "dated now. It starts a thread unless --reply names the thread it answers. " + object_kind.LOOKED_UP
    ),
)
@click.option(
    "--message",
    "-m",
    "text",
    type=str,
    required=True,
    help="What the comment says, in Markdown; '-' reads it from standard input",
)
@click.option(
    "--ref",
    type=str,
    default=None,
    help=(
        "What inside the object it is about: 'face:12' or 'edge:3' of a part, or a selection -- CadQuery's "
        "'faces(\">Z\")', build123d's 'faces().sort_by(Axis.Z)[-1]' -- or a link name of an assembly"
    ),
)
@click.option(
    "--reply", "thread", type=int, default=None, help="The thread it answers, as 'pc comment list' numbers it"
)
@click.option(
    "--attach",
    "attachments",
    multiple=True,
    metavar="FILE",
    help="A file that goes with it, inside the package; may be given more than once",
)
@click.option("--author", type=str, default=None, help="Who wrote it, where 'git config user.name' should not say")
@click.option("--package", "-P", type=str, default="", show_envvar=True, help="Package to find the object in")
@click.option("--assembly", "-a", is_flag=True, help=object_kind.flag_help("an assembly"))
@click.option("--scene", "-S", is_flag=True, help=object_kind.flag_help("a scene"))
@click.option("--sketch", "-s", is_flag=True, help=object_kind.flag_help("a sketch"))
@click.option("--interface", "-i", is_flag=True, help=object_kind.flag_help("an interface"))
@click.option("--kind", type=click.Choice(KINDS), default=None, help="The kind of the object, for any kind")
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, text, ref, thread, attachments, author, package, assembly, scene, sketch, interface, kind, object):
    if text == "-":
        text = sys.stdin.read()
    flagged = [name for name, said in (("assembly", assembly), ("scene", scene), ("sketch", sketch)) if said]
    if interface:
        flagged.append("interface")
    if kind:
        flagged.append(kind)
    if len(set(flagged)) > 1:
        raise click.UsageError("The object is one kind of object, and %s are named" % " and ".join(flagged))
    if flagged and not object:
        raise click.UsageError("A kind is said of an object, and none is named: the comment would be on the package")
    base = getattr(cli_ctx, "path", None) or os.getcwd()
    name = author or pc_comments.author(base if os.path.isdir(base) else os.path.dirname(base))
    if not name:
        raise click.UsageError(
            "Nobody to sign the comment with: set your name with 'git config --global user.name \"Your Name\"', "
            "or say it with --author"
        )
    params = {
        "package": package,
        "name": name,
        "text": text,
        "ref": ref,
        "thread": thread,
        # Absolute, as 'pc add' sends a file: the daemon does not share this
        # working directory, and writes each relative to the package.
        "attachments": [os.path.abspath(path) for path in attachments] or None,
    }
    if object:
        params["object"] = object
        if flagged:
            params["kind"] = flagged[0]
    run(cli_ctx, "comment.add", params, needs_context=True)
