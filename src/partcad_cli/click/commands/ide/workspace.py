#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ide workspace <directory>` -- open a package as an editor's workspace, in the PartCAD workbench.

The editor is the PartCAD IDE, VSCodium or Visual Studio Code on this machine,
and the window is on this machine's screen -- which is why this runs here and
asks no daemon anything, for the reason `pc ide open` and `pc upgrade` do not:
a daemon can be remote. Which editor, and how its window is told to show the
workbench, is `partcad_client.ide`.

It is a command of its own rather than a directory given to `pc ide open`,
because the two are different gestures: `pc ide open` puts *one object* in front
of a person in a design application and waits for it to come back edited, while
this puts a whole package in front of them in the IDE and returns at once.
"""

import json

import rich_click as click


@click.command(
    help="Open a directory as the workspace of an editor on this machine -- the PartCAD IDE, VSCodium or "
    "Visual Studio Code -- in the PartCAD workbench. Anything after '--' is passed to the editor."
)
@click.option(
    "--with",
    "editor",
    type=str,
    default=None,
    metavar="EDITOR",
    help="The editor, by name (partcad-ide, codium, code) or path. By default the first of those on the PATH.",
)
@click.option("--json", "as_json", is_flag=True, help="Print what happened as JSON, including the reason on failure.")
@click.argument("directory", type=click.Path(exists=True, file_okay=False), default=".")
@click.argument("editor_args", nargs=-1, type=click.UNPROCESSED, metavar="[-- EDITOR_ARGS...]")
@click.pass_context
def cli(click_ctx, editor: str, as_json: bool, directory: str, editor_args: tuple) -> None:
    # Deferred, so that `pc --help` does not import it.
    from partcad_client import ide

    try:
        result = ide.open_workspace(
            directory,
            editor=editor,
            editor_args=editor_args,
            log=(lambda _line: None) if as_json else click.echo,
        )
    except ide.IdeError as e:
        if as_json:
            click.echo(json.dumps({"ok": False, "editor": editor, "path": directory, "error": str(e)}))
            click_ctx.exit(1)
        raise click.ClickException(str(e))
    if as_json:
        click.echo(json.dumps(result))
