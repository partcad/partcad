#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ide install` -- put the PartCAD extension into an editor on this machine.

From the ``.vsix`` published on a GitHub release (the latest one unless told
otherwise), or from a ``.vsix`` on disk. In-process, and with no daemon call at
all: it is this machine's editor that is changed, by the process running on it,
and a daemon can be remote. Same reason as `pc upgrade`; see "Command boundary"
in src/partcad_cli/AGENTS.md, and `partcad_client.ide` for the rest.
"""

import json

import rich_click as click


@click.command(
    help="Install the PartCAD extension into an editor on this machine -- the PartCAD IDE, VSCodium or "
    "Visual Studio Code -- from a GitHub release of PartCAD or from a .vsix file. Anything after '--' is "
    "passed to the editor, e.g. '-- --extensions-dir DIR' for a profile of its own."
)
@click.option(
    "--with",
    "editor",
    type=str,
    default=None,
    metavar="EDITOR",
    help="The editor to install into, by name (partcad-ide, codium, code) or path. By default the first of "
    "those on the PATH.",
)
@click.option(
    "--version",
    "version",
    type=str,
    default=None,
    metavar="VERSION",
    help="The PartCAD release to take the extension from. By default the latest one.",
)
@click.option(
    "--vsix",
    "vsix",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Install this .vsix file instead of downloading one.",
)
@click.option("--json", "as_json", is_flag=True, help="Print what happened as JSON, including the reason on failure.")
@click.argument("editor_args", nargs=-1, type=click.UNPROCESSED, metavar="[-- EDITOR_ARGS...]")
@click.pass_context
def cli(click_ctx, editor, version, vsix, as_json, editor_args) -> None:
    # Deferred, so that `pc --help` does not import it.
    from partcad_client import ide

    if vsix is not None and version is not None:
        raise click.UsageError(
            "--vsix is the package to install, and --version says which release to download one from; pass one of them."
        )
    try:
        result = ide.install_extension(
            editor=editor,
            version=version,
            vsix=vsix,
            editor_args=editor_args,
            log=(lambda _line: None) if as_json else (lambda line: click.echo(line, err=True)),
        )
    except ide.IdeError as e:
        if as_json:
            click.echo(json.dumps({"ok": False, "error": str(e)}))
            click_ctx.exit(1)
        raise click.ClickException(str(e))
    if as_json:
        click.echo(json.dumps(result))
        return
    click.echo("Installed %s into %s." % (result["extension"], result["editor"]))
